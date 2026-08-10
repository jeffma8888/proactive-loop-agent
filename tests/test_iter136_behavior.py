"""Black-box behavior tests for iteration 136 (foundry iter-129) --- ONE shared
per-scan text provider, so ``todos`` / ``merge_conflict`` / ``syntax_error`` stop
independently opening and decoding the SAME files inside one scan.

ISOLATION CONTRACT (honored): every assertion below is written against THIS
iteration's spec (``pm.md`` "Expected Behaviors" 1-10) and drives only public
surfaces --- the three content collectors' ``collect(root)``, the orchestration
seam ``proactive_loop.cli._collect(workspace) -> WorkspaceSnapshot`` (the same
seam ``tests/test_iter92_behavior.py`` drives), the ``pla`` CLI through
``cli.main(argv) -> int``, and the new module's documented five-name seam
(``read_text`` / ``scan_scope`` / ``clear_text_cache`` / ``text_cache_stats`` /
``TEXT_CACHE_MAX_BYTES``).  **No file under ``src/`` was read, no engineer /
reviewer / fix notes were read, and no ``git diff`` was consulted.**  Where a
signature was needed it was taken from the RUNNING product
(``inspect.signature`` on the public callables), which is the same "read the
product's own help" affordance the role grants.

Fully offline and deterministic: no network, every writable target under
``tmp_path``, and the only reads outside ``tmp_path`` are of this repository's
own tree (behavior 1's realistic-workspace case), which is never mutated.

AMBIGUITY / SPEC-CONTRADICTION NOTES (PM feedback, see ``tester.md``):

* **Behavior 2 contradicts Acceptance Criterion 2 for the undecodable file, and
  AC2 is the clause that must win.**  Behavior 2 demands ``max(per-path reads)
  == 1`` and "3 calls over 3 paths" for a fixture whose third member (``bad.py``)
  is deliberately NOT valid UTF-8.  AC2 mandates that a cache MISS reads
  ``Path.read_text(encoding="utf-8")`` STRICT first and only falls back to a
  second ``errors="replace"`` read on ``UnicodeDecodeError``.  An undecodable
  file therefore costs exactly TWO physical ``read_text`` calls per scan by
  mandate, and the only way to reach Behavior 2's literal 3 would be a single
  replace-read for everyone --- which is precisely the correctness regression
  Behavior 5 (and the armed ``--fail-on-kind syntax_error`` CI gate) forbids.
  Tested reading: each file is FILLED at most once per scan; a decodable file
  costs exactly 1 read, an undecodable one exactly 2, so the spec's own
  three-file fixture drops 8 reads -> 4.  ``test_b02b_*`` asserts Behavior 2's
  literal ``max == 1`` on an all-decodable fixture, where it IS satisfiable.
* Behavior 1 says stdout is "byte-identical before and after this change".  A
  live before/after comparison goes vacuous the moment the change is committed,
  so the durable oracle used here is the module's own documented fallback: OUTSIDE
  a scope the provider is a pure pass-through that reads every call, i.e. exactly
  the pre-change I/O path.  In-scope (shared) vs out-of-scope (pass-through)
  signals are compared field-for-field AND order-for-order, in one process, on
  both a fixture and this repository.
* Behavior 9 says ``clear_text_cache()`` "resets all five to ``0`` in place".
  Only the observable is asserted (a subsequent ``text_cache_stats()`` reads all
  zeros); no identity/aliasing claim is made about the returned dict.
* Behavior 4 says the cache "is still emptied" when the body raises.  ``entries``
  and ``bytes`` are the cache; ``hits`` / ``misses`` / ``declined`` are lifetime
  counters that survive a scope (measured), and only ``clear_text_cache()`` zeroes
  them.  Asserted accordingly.
"""

from __future__ import annotations

import io
import pathlib
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

from proactive_loop import cli
from proactive_loop.collectors import (
    MergeConflictCollector,
    SyntaxErrorCollector,
    TodoCollector,
    all_collectors,
)
from proactive_loop.collectors import text_source

REPO = Path(__file__).resolve().parents[1]

#: The three content collectors this row touches, in registry order.
CONTENT_SOURCES = ("todos", "merge_conflict", "syntax_error")

#: Bytes that are NOT valid UTF-8 (0xff 0xfe is not a legal sequence) carrying
#: BOTH a ``TODO:`` line and a conflict marker, plus an unclosed paren that a
#: strict Python parse would reject -- the file that makes the strict/replace
#: divergence observable (spec behavior 5).
BAD_BYTES = b"# TODO: bad bytes \xff\xfe here\n<<<<<<< HEAD\nx = (\n"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _fixture(root: Path) -> Path:
    """The spec's 3-file workspace: a .py, a .md, and an undecodable .py."""
    (root / "mod.py").write_text("x = 1\n# TODO: fix mod\n", encoding="utf-8")
    (root / "note.md").write_text("- TODO: write docs\n", encoding="utf-8")
    (root / "bad.py").write_bytes(BAD_BYTES)
    return root


def _decodable_fixture(root: Path) -> Path:
    """An ALL-decodable workspace, where behavior 2's literal max==1 is reachable."""
    (root / "mod.py").write_text("x = 1\n# TODO: fix mod\n", encoding="utf-8")
    (root / "note.md").write_text("- TODO: write docs\n", encoding="utf-8")
    (root / "other.py").write_text("y = 2\n# TODO: fix other\n", encoding="utf-8")
    return root


def _fields(sig: object) -> tuple[object, ...]:
    """Every published field of a signal -- the full behavior-1 comparison key."""
    return tuple(
        getattr(sig, name) for name in ("source", "kind", "summary", "detail", "path", "weight")
    )


def _content_rows(signals: list) -> list[tuple[object, ...]]:  # noqa: ANN401 - list[ContextSignal]
    """Ordered field rows for the three collectors this row touches."""
    return [_fields(s) for s in signals if s.source in CONTENT_SOURCES]


def _shared_rows(workspace: Path) -> list[tuple[object, ...]]:
    """One real scan -- the shared provider is active inside ``cli._collect``."""
    return _content_rows(list(cli._collect(workspace).signals))


def _passthrough_rows(workspace: Path) -> list[tuple[object, ...]]:
    """The same three collectors OUTSIDE any scope == the pre-change read path."""
    rows: list[tuple[object, ...]] = []
    for collector in (TodoCollector(), MergeConflictCollector(), SyntaxErrorCollector()):
        rows += [_fields(s) for s in collector.collect(workspace)]
    return rows


@contextmanager
def _read_counts(monkeypatch: pytest.MonkeyPatch) -> Iterator[Counter[Path]]:
    """Count physical ``Path.read_text`` calls per RESOLVED path for the duration.

    Keyed on the resolved path, never the file name: this repository holds a dozen
    distinct ``__init__.py`` files, and a name-keyed counter reported 6 reads of
    "``__init__.py``" that were really 1 read of each of six different modules.
    """
    counts: Counter[Path] = Counter()
    original = pathlib.Path.read_text

    def spy(self: Path, *args: object, **kwargs: object) -> str:
        counts[self.resolve()] += 1
        return original(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(pathlib.Path, "read_text", spy)
    try:
        yield counts
    finally:
        monkeypatch.undo()


def _per_path(counts: Counter[Path], root: Path, *names: str) -> dict[str, int]:
    """Project a resolved-path read counter down to ``{filename: count}``."""
    return {name: counts[(root / name).resolve()] for name in names}


@contextmanager
def _provider_calls(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    """Record which file names the COLLECTORS ask the provider for."""
    seen: list[str] = []
    original = text_source.read_text

    def spy(full: Path, *, strict: bool) -> str | None:
        seen.append(full.name)
        return original(full, strict=strict)

    monkeypatch.setattr(text_source, "read_text", spy)
    try:
        yield seen
    finally:
        monkeypatch.undo()


def _cli(argv: list[str]) -> tuple[int, str, str]:
    """Run the front door in-process; return (exit code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli.main(argv)
    return code, out.getvalue(), err.getvalue()


@pytest.fixture(autouse=True)
def _isolated_cache() -> Iterator[None]:
    """Every test starts and ends on zeroed counters -- no cross-test coupling."""
    text_source.clear_text_cache()
    yield
    text_source.clear_text_cache()


# ===========================================================================
# Behavior 1 --- output is unchanged (shared read == pass-through read)
# ===========================================================================
def test_b01a_fixture_signals_are_identical_shared_vs_passthrough(tmp_path: Path) -> None:
    ws = _fixture(tmp_path)
    shared, passthrough = _shared_rows(ws), _passthrough_rows(ws)
    assert shared, "the fixture must produce content signals, or this oracle is vacuous"
    assert shared == passthrough, (
        "sharing one decode between the three content collectors changed their signals; "
        f"in-scope={shared!r} != pass-through={passthrough!r}"
    )


def test_b01b_repo_signals_are_identical_shared_vs_passthrough() -> None:
    """The realistic workspace: this repository's own tree, full fields AND order."""
    shared, passthrough = _shared_rows(REPO), _passthrough_rows(REPO)
    assert len(shared) > 10, f"expected a non-trivial repo signal set, got {len(shared)}"
    assert shared == passthrough, (
        "the repo's content signals differ between the shared and pass-through read paths"
    )


def test_b01c_signals_json_is_byte_identical_across_two_runs(tmp_path: Path) -> None:
    """No per-scan cache may leak into the next scan's answer."""
    ws = _fixture(tmp_path)
    first = _cli(["signals", "--workspace", str(ws), "--json"])
    second = _cli(["signals", "--workspace", str(ws), "--json"])
    assert first[0] == second[0] == 0, f"signals --json must exit 0; got {first[0]}/{second[0]}"
    assert first[1] == second[1], "two consecutive `signals --json` runs must be byte-identical"


# ===========================================================================
# Behavior 2 --- each file is physically read at most ONCE per scan
# ===========================================================================
def test_b02a_one_scan_reads_each_file_once_twice_only_when_undecodable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """8 reads over 3 paths becomes 4: the cross-collector redundancy is gone.

    ``bad.py`` costs 2 by Acceptance Criterion 2 (strict attempt, then the
    ``errors="replace"`` fallback); see the module docstring's contradiction note.
    """
    ws = _fixture(tmp_path)
    with _read_counts(monkeypatch) as counts:
        cli._collect(ws)
    fixture_counts = _per_path(counts, ws, "mod.py", "note.md", "bad.py")
    assert fixture_counts["mod.py"] == 1, (
        f"a decodable .py is read by all three collectors and must be decoded ONCE; "
        f"got {fixture_counts!r}"
    )
    assert fixture_counts["note.md"] == 1, (
        f"a decodable .md is read by two collectors and must be decoded ONCE; got {fixture_counts!r}"
    )
    assert fixture_counts["bad.py"] == 2, (
        "an undecodable file costs exactly one strict attempt plus one replace fallback "
        f"(AC2), never three per-collector reads; got {fixture_counts!r}"
    )
    assert sum(fixture_counts.values()) == 4 < 8, (
        f"total reads must fall from the pre-change 8 to 4; got {fixture_counts!r}"
    )


def test_b02b_all_decodable_fixture_reads_every_path_exactly_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Behavior 2's literal assertion, on the fixture where it is satisfiable."""
    ws = _decodable_fixture(tmp_path)
    names = ("mod.py", "note.md", "other.py")
    with _read_counts(monkeypatch) as counts:
        cli._collect(ws)
    per_path = _per_path(counts, ws, *names)
    assert max(per_path.values()) == 1, f"every path must be read at most once; got {per_path!r}"
    assert sum(per_path.values()) == len(names), (
        f"total reads must equal the number of admitted paths; got {per_path!r}"
    )


def test_b02c_repo_scan_never_reads_one_path_more_than_twice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The redundancy is gone on the real tree, not only on a 3-file fixture."""
    with _read_counts(monkeypatch) as counts:
        cli._collect(REPO)
    worst = counts.most_common(3)
    assert counts, "instrumentation caught no reads at all -- the oracle is broken"
    assert worst[0][1] <= 2, (
        "a repo file was decoded more than twice in one scan (once strict, at most once more "
        f"as the replace fallback): {[(str(p), n) for p, n in worst]!r}"
    )


# ===========================================================================
# Behavior 3 --- no caching outside a scan
# ===========================================================================
def test_b03a_direct_collect_rereads_and_caches_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = _fixture(tmp_path)
    with _read_counts(monkeypatch) as counts:
        TodoCollector().collect(ws)
        TodoCollector().collect(ws)
    mod_reads = _per_path(counts, ws, "mod.py")["mod.py"]
    assert mod_reads == 2, (
        f"two out-of-scope collect() calls must read the file twice; got {mod_reads}"
    )
    assert text_source.text_cache_stats()["entries"] == 0, (
        "no scope is open, so nothing may be retained: "
        f"{text_source.text_cache_stats()!r}"
    )


def test_b03b_direct_collect_sees_content_changed_between_calls(tmp_path: Path) -> None:
    ws = _fixture(tmp_path)
    before = [s.summary for s in TodoCollector().collect(ws) if s.path.startswith("mod.py")]
    (ws / "mod.py").write_text("y = 2\n# TODO: changed marker\n", encoding="utf-8")
    after = [s.summary for s in TodoCollector().collect(ws) if s.path.startswith("mod.py")]
    assert before == ["TODO: fix mod"], f"unexpected pre-edit summary: {before!r}"
    assert after == ["TODO: changed marker"], (
        f"an out-of-scope collect() must reflect the NEW content; got {after!r}"
    )
    assert text_source.text_cache_stats()["entries"] == 0


# ===========================================================================
# Behavior 4 --- the scope is clean on both edges and exception-safe
# ===========================================================================
def test_b04a_scope_is_empty_on_entry_and_after_exit(tmp_path: Path) -> None:
    ws = _fixture(tmp_path)
    with text_source.scan_scope():
        assert text_source.text_cache_stats()["entries"] == 0, "a scope must start empty"
        text_source.read_text(ws / "mod.py", strict=True)
        assert text_source.text_cache_stats()["entries"] == 1, (
            "the mid-scope check is vacuous unless a read really populates the cache"
        )
    assert text_source.text_cache_stats()["entries"] == 0, "the scope must empty on exit"
    with text_source.scan_scope():
        assert text_source.text_cache_stats()["entries"] == 0, (
            "a second scope must also start empty"
        )


def test_b04b_body_exception_propagates_unchanged_and_still_empties(tmp_path: Path) -> None:
    ws = _fixture(tmp_path)
    sentinel = RuntimeError("scope body blew up")
    with pytest.raises(RuntimeError) as caught:
        with text_source.scan_scope():
            text_source.read_text(ws / "note.md", strict=True)
            assert text_source.text_cache_stats()["entries"] == 1
            raise sentinel
    assert caught.value is sentinel, "the body's exception must propagate unchanged"
    assert text_source.text_cache_stats()["entries"] == 0, (
        "a raising body must still leave the cache empty (finally-clear): "
        f"{text_source.text_cache_stats()!r}"
    )
    assert text_source.text_cache_stats()["bytes"] == 0


# ===========================================================================
# Behavior 5 --- the strict/replace divergence survives, in either order
# ===========================================================================
def test_b05a_scan_emits_todo_and_conflict_but_no_syntax_error_for_bad_bytes(
    tmp_path: Path,
) -> None:
    ws = _fixture(tmp_path)
    rows = _shared_rows(ws)
    kinds = {(row[1], row[4]) for row in rows}
    assert ("todo", "bad.py:1") in kinds, f"the undecodable file's TODO must survive: {kinds!r}"
    assert ("merge_conflict", "bad.py") in kinds, (
        f"the undecodable file's conflict marker must survive: {kinds!r}"
    )
    assert not [row for row in rows if row[1] == "syntax_error"], (
        "syntax_error must still REFUSE an undecodable file (a false syntax_error turns the "
        f"public CI build red via --fail-on-kind): {rows!r}"
    )


def test_b05b_signals_and_reads_are_independent_of_collector_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = _fixture(tmp_path)
    orders = {
        "todos-first": (TodoCollector(), MergeConflictCollector(), SyntaxErrorCollector()),
        "syntax-first": (SyntaxErrorCollector(), MergeConflictCollector(), TodoCollector()),
    }
    results: dict[str, tuple[frozenset, dict[str, int]]] = {}
    for name, collectors in orders.items():
        text_source.clear_text_cache()
        with _read_counts(monkeypatch) as counts:
            with text_source.scan_scope():
                rows = [_fields(s) for c in collectors for s in c.collect(ws)]
        results[name] = (
            frozenset(rows),
            _per_path(counts, ws, "mod.py", "note.md", "bad.py"),
        )
    first, second = results["todos-first"], results["syntax-first"]
    assert first[0] == second[0], (
        "whichever collector touches the file first must not change the signals emitted: "
        f"{first[0] ^ second[0]!r}"
    )
    assert first[1] == second[1] == {"mod.py": 1, "note.md": 1, "bad.py": 2}, (
        f"read counts must be order-independent; got {first[1]!r} then {second[1]!r}"
    )


def test_b05c_replacement_chars_still_reach_the_published_summary(tmp_path: Path) -> None:
    """The replace-read policy is user-visible; it must not be quietly tightened."""
    ws = _fixture(tmp_path)
    summaries = [row[2] for row in _shared_rows(ws) if row[1] == "todo" and "bad.py" in str(row[4])]
    assert summaries and "\ufffd" in summaries[0], (
        f"the U+FFFD replacement chars must survive into the todo summary; got {summaries!r}"
    )


def test_b05d_armed_fail_on_kind_gate_still_exits_zero_on_this_repo() -> None:
    """The exact gate ``Makefile``/``ci.yml`` run: a false positive reddens main."""
    code, _, _ = _cli(
        [
            "signals",
            "--workspace",
            str(REPO),
            "--fail-on-kind",
            "merge_conflict",
            "--fail-on-kind",
            "syntax_error",
            "--fail-on-kind",
            "secret_file",
        ]
    )
    assert code == 0, f"the armed CI signal gate must stay green on this repo; exit={code}"


# ===========================================================================
# Behavior 6 --- per-collector read caps still bind
# ===========================================================================
def test_b06a_small_cap_collector_skips_the_oversized_file_in_a_shared_scope(
    tmp_path: Path,
) -> None:
    ws = _fixture(tmp_path)
    big = ws / "big.py"
    big.write_text("# TODO: huge\n" + ("# pad\n" * 400), encoding="utf-8")
    with text_source.scan_scope():
        generous = TodoCollector(max_read_bytes=10_000_000).collect(ws)
        frugal = TodoCollector(max_read_bytes=50).collect(ws)
    assert big.stat().st_size > 50, "the fixture must actually exceed the small cap"
    assert "big.py:1" in {s.path for s in generous}, (
        "the large-cap collector must see the oversized file (positive control)"
    )
    assert not [s for s in frugal if s.path.startswith("big.py")], (
        f"a small-cap collector must not emit for an oversized file: {[s.path for s in frugal]!r}"
    )


def test_b06b_small_cap_collector_never_asks_the_provider_for_the_oversized_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = _fixture(tmp_path)
    (ws / "big.py").write_text("# TODO: huge\n" + ("# pad\n" * 400), encoding="utf-8")
    with _provider_calls(monkeypatch) as seen:
        with text_source.scan_scope():
            TodoCollector(max_read_bytes=10_000_000).collect(ws)
            assert "big.py" in seen, (
                "the spy is not wired to the seam the collectors call -- the negative "
                f"assertion below would be vacuous; saw {seen!r}"
            )
            seen.clear()
            MergeConflictCollector(max_read_bytes=50).collect(ws)
    assert "big.py" not in seen, (
        "a collector must stat-guard BEFORE consulting the provider, or a shared cache "
        f"silently defeats its own read cap; saw {seen!r}"
    )
    assert "mod.py" in seen, f"the small-cap collector must still read small files; saw {seen!r}"


# ===========================================================================
# Behavior 7 --- the byte budget degrades to re-reading, never to a wrong answer
# ===========================================================================
def test_b07a_tiny_byte_budget_keeps_the_signals_identical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = _fixture(tmp_path)
    unpatched = _shared_rows(ws)
    monkeypatch.setattr(text_source, "TEXT_CACHE_MAX_BYTES", 10)
    starved = _shared_rows(ws)
    assert starved == unpatched, (
        "a starved cache must degrade to re-reading, never to a different answer; "
        f"{starved!r} != {unpatched!r}"
    )


def test_b07b_tiny_byte_budget_declines_and_never_exceeds_the_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = _fixture(tmp_path)
    monkeypatch.setattr(text_source, "TEXT_CACHE_MAX_BYTES", 10)
    with text_source.scan_scope():
        for collector in (TodoCollector(), MergeConflictCollector(), SyntaxErrorCollector()):
            collector.collect(ws)
        inside = text_source.text_cache_stats()
    assert inside["declined"] > 0, (
        "the cap is read at CALL time, so a monkeypatch must take effect and decline "
        f"oversized entries; got {inside!r}"
    )
    assert inside["bytes"] <= 10, f"cached bytes must never exceed the live cap; got {inside!r}"


def test_b07c_generous_budget_declines_nothing(tmp_path: Path) -> None:
    """Control for b07b: the decline counter is not simply always positive."""
    ws = _fixture(tmp_path)
    with text_source.scan_scope():
        for collector in (TodoCollector(), MergeConflictCollector(), SyntaxErrorCollector()):
            collector.collect(ws)
        inside = text_source.text_cache_stats()
    assert inside["declined"] == 0, f"a 32 MiB budget must decline nothing here; got {inside!r}"
    assert inside["entries"] == 3, f"all three fixture files should be cached; got {inside!r}"


# ===========================================================================
# Behavior 8 --- an unreadable file is skipped exactly as today, and not cached
# ===========================================================================
def test_b08_unreadable_file_is_skipped_without_aborting_or_caching(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = _fixture(tmp_path)
    (ws / "gone.py").write_text("# TODO: vanish\n<<<<<<< HEAD\n", encoding="utf-8")
    original = pathlib.Path.read_text

    def raising(self: Path, *args: object, **kwargs: object) -> str:
        if self.name == "gone.py":
            raise OSError(2, "No such file or directory")
        return original(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(pathlib.Path, "read_text", raising)
    with text_source.scan_scope():
        rows = [
            _fields(s)
            for c in (TodoCollector(), MergeConflictCollector(), SyntaxErrorCollector())
            for s in c.collect(ws)
        ]
        inside = text_source.text_cache_stats()
    monkeypatch.undo()
    paths = {str(row[4]) for row in rows}
    assert not [p for p in paths if p.startswith("gone.py")], (
        f"an unreadable file must contribute no signal; got {sorted(paths)!r}"
    )
    assert {"mod.py:2", "note.md:1", "bad.py:1", "bad.py"} <= paths, (
        f"the surviving files in the same directory must still emit; got {sorted(paths)!r}"
    )
    assert inside["entries"] == 3, (
        f"only the three readable files may be cached; got {inside!r}"
    )


def test_b08b_unreadable_file_does_not_abort_a_full_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = _fixture(tmp_path)
    (ws / "gone.py").write_text("# TODO: vanish\n", encoding="utf-8")
    original = pathlib.Path.read_text

    def raising(self: Path, *args: object, **kwargs: object) -> str:
        if self.name == "gone.py":
            raise OSError(2, "No such file or directory")
        return original(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(pathlib.Path, "read_text", raising)
    rows = _shared_rows(ws)
    monkeypatch.undo()
    assert {row[4] for row in rows if row[1] == "todo"} == {"mod.py:2", "note.md:1", "bad.py:1"}, (
        f"the scan must survive the OSError and keep every other signal; got {rows!r}"
    )


# ===========================================================================
# Behavior 9 --- the stats / clear seam
# ===========================================================================
def test_b09a_stats_exposes_exactly_five_integer_keys() -> None:
    stats = text_source.text_cache_stats()
    assert set(stats) == {"entries", "bytes", "hits", "misses", "declined"}, (
        f"the documented stats keys changed: {sorted(stats)!r}"
    )
    assert all(isinstance(v, int) for v in stats.values()), f"every value must be an int: {stats!r}"


def test_b09b_second_request_for_the_same_path_is_a_hit(tmp_path: Path) -> None:
    ws = _fixture(tmp_path)
    with text_source.scan_scope():
        text_source.read_text(ws / "mod.py", strict=True)
        first = text_source.text_cache_stats()
        text_source.read_text(ws / "mod.py", strict=True)
        second = text_source.text_cache_stats()
    assert (first["hits"], first["misses"]) == (0, 1), f"first read must be a miss: {first!r}"
    assert second["hits"] == 1, f"the second request must be a HIT; got {second!r}"
    assert second["misses"] == first["misses"], (
        f"a hit must not also count as a miss; got {second!r}"
    )


def test_b09c_clear_resets_all_five_and_is_safe_outside_a_scope(tmp_path: Path) -> None:
    ws = _fixture(tmp_path)
    with text_source.scan_scope():
        text_source.read_text(ws / "mod.py", strict=True)
        text_source.read_text(ws / "mod.py", strict=True)
    assert text_source.text_cache_stats()["hits"] >= 1, "the pre-clear state must be non-zero"
    text_source.clear_text_cache()  # outside any scope
    assert text_source.text_cache_stats() == {
        "entries": 0,
        "bytes": 0,
        "hits": 0,
        "misses": 0,
        "declined": 0,
    }, f"clear_text_cache() must zero all five counters; got {text_source.text_cache_stats()!r}"
    text_source.clear_text_cache()  # idempotent, still outside a scope
    assert text_source.text_cache_stats()["entries"] == 0


def test_b09d_strict_caller_gets_none_for_undecodable_bytes(tmp_path: Path) -> None:
    """The provider's documented return contract, exercised directly."""
    ws = _fixture(tmp_path)
    with text_source.scan_scope():
        assert text_source.read_text(ws / "bad.py", strict=True) is None, (
            "a strict caller must be told to SKIP an undecodable file (None), not handed "
            "replacement-charred text"
        )
        replaced = text_source.read_text(ws / "bad.py", strict=False)
    assert replaced is not None and "\ufffd" in replaced, (
        f"a replace caller must still receive the charred text; got {replaced!r}"
    )


def test_b09e_read_text_propagates_oserror(tmp_path: Path) -> None:
    with text_source.scan_scope():
        with pytest.raises(OSError):
            text_source.read_text(tmp_path / "no-such-file.py", strict=True)


# ===========================================================================
# Behavior 10 --- `signals --timings` is undisturbed
# ===========================================================================
def test_b10a_timings_leaves_stdout_byte_identical(tmp_path: Path) -> None:
    ws = _fixture(tmp_path)
    plain_code, plain_out, plain_err = _cli(["signals", "--workspace", str(ws)])
    timed_code, timed_out, timed_err = _cli(["signals", "--workspace", str(ws), "--timings"])
    assert plain_code == timed_code == 0, f"exits must be 0; got {plain_code}/{timed_code}"
    assert timed_out == plain_out, "--timings must not touch stdout"
    assert plain_err == "", f"the plain run must print nothing on stderr; got {plain_err!r}"
    assert timed_err, "--timings must print its table on stderr"


def test_b10b_timings_prints_one_row_per_collector_in_registry_order(tmp_path: Path) -> None:
    ws = _fixture(tmp_path)
    _, _, err = _cli(["signals", "--workspace", str(ws), "--timings"])
    names = [c.name for c in all_collectors()]
    rows = [
        line.split()[0]
        for line in err.splitlines()
        if line.startswith("  ") and line.split() and line.split()[0] != "TOTAL"
    ]
    assert rows == names, (
        f"--timings must print exactly one row per collector in registry order; got {rows!r}"
    )
