"""Black-box behavior tests for factory iteration 124 --- the ``syntax_error`` parse memo.

Feature under test: ``SyntaxErrorCollector`` memoizes its PARSE VERDICT in a
bounded, explicitly clearable MODULE-level map keyed on the content of each
candidate file, so re-collecting an unchanged tree still reads but never
re-compiles. Two module-level functions publish the state --- ``clear_parse_memo()``
and ``parse_memo_stats()`` --- and a module constant caps the entry count. The
observable signal stream is required to be byte-identical to the pre-memo one:
warm output equals cold output, a changed file invalidates exactly itself, and
eviction never changes what is emitted.

ISOLATION CONTRACT (honored): written strictly against this iteration's spec
(``pm.md`` "Expected Behaviors" 1-9) plus the published ``README.md`` and the
conventions of the existing modules under ``tests/``. Every assertion drives a
public surface --- ``SyntaxErrorCollector(...).collect(root)``, the two new
module-level functions, the module's exported cap constant, and the ``pla`` CLI
through ``proactive_loop.cli.main(argv) -> int``. **No file under ``src/`` was
read while writing this module, no engineer / reviewer / fix note was opened,
and no ``git diff`` was consulted.** Where the shape of the collector was needed
it was obtained by RUNNING it and by ``inspect.signature`` on its public
constructor, never by reading its source.

Fully offline and deterministic: synthetic ``tmp_path`` trees only (never the
in-repo tree, so no collector can leak repo state --- iter-15 lesson), no
network, no API key, no sleeps, and NO DURATION IS ASSERTED ANYWHERE (roadmap
row #129's standing constraint --- the speed win is measured by hand at the
gate, never by a test).

Because the memo is deliberately MODULE-level (process-global) state, every test
here calls ``clear_parse_memo()`` before it asserts on counters, so no test can
inherit another's hits/misses.

AMBIGUITY NOTES (PM feedback):

* Behavior 5 says "the module's exported cap constant" without naming it. The
  only public module-level integer whose name carries both MEMO and MAX is
  ``PARSE_MEMO_MAX_ENTRIES``, so the tests bind to that, and they pin it TWICE:
  once at its shipped value (a tree of ``cap + 4`` distinct files) and once with
  the constant monkeypatched small. The second form is what proves the cap is
  READ at runtime rather than baked in --- with the patch lifted the same tree
  stores every file, so the guard cannot pass vacuously.
* Behavior 7 says "a ``*.py`` file larger than ``max_read_bytes``".
  ``max_read_bytes`` is a CONSTRUCTOR parameter (default 5,000,000), not a module
  constant, so the oversize case is expressed with an explicit small
  ``max_read_bytes`` and the fixture is asserted to exceed the collector's own
  live value. That avoids a 5 MB fixture and follows the reviewer's rule of
  naming the live value instead of a number assumed about it.
* Behavior 3 says the ``summary`` "ends with the new 1-based error line". The
  expected line number is DERIVED in the test by compiling the same bytes with
  stdlib ``compile()``, so the assertion cannot drift between the Python 3.12
  and 3.13 legs of CI if a future release renumbers a diagnostic.
* Behavior 9 says "twice as two separate invocations". These are two in-process
  ``main()`` calls (the convention of ``tests/test_iter88_behavior.py``), which is
  the STRICTER reading: the memo survives between them, so a warm/cold output
  divergence is observable here. Two fresh subprocesses would each start cold
  and could not detect it at all.
* Behavior 8 is strengthened by one assertion the spec implies but does not
  state: ``parse_memo_stats()`` must be a SNAPSHOT, i.e. mutating the returned
  dict cannot change what the next call reports.
* Behavior 9 says the broken case "prints that file's path exactly once". Taken
  as a SUBSTRING count that is false of the shipped renderer for a reason that
  has nothing to do with this feature: the human view prints the relpath twice on
  the SAME line (once inside the summary text, once as the trailing ``-> path``
  column), which is long-standing published output. The claim being tested is
  therefore that the file is REPORTED once --- exactly one stdout line mentions
  it, and the group header counts one signal. Read as a substring count the
  assertion would fail on unchanged pre-memo behavior, which is a spec-wording
  bug, not a product defect.
"""

from __future__ import annotations

import inspect
import os
from pathlib import Path

import pytest

from proactive_loop.cli import main
from proactive_loop.collectors import syntax_error as syntax_error_mod
from proactive_loop.collectors.syntax_error import (
    PARSE_MEMO_MAX_ENTRIES,
    SyntaxErrorCollector,
    clear_parse_memo,
    parse_memo_stats,
)
from proactive_loop.models import ContextSignal

# Behavior 1's comparison contract, verbatim from the spec.
_FIELDS = ("source", "kind", "summary", "detail", "path", "weight", "timestamp")

_BROKEN = "def f(:\n"
_STATS_KEYS = {"hits", "misses", "entries"}


def _rows(sigs: list[ContextSignal]) -> list[tuple[object, ...]]:
    """Field-by-field projection of a signal list, in emission order."""
    return [tuple(getattr(s, f) for f in _FIELDS) for s in sigs]


def _distinct_tree(root: Path, count: int, *, broken_every: int = 0) -> list[str]:
    """Write ``count`` ``*.py`` files of pairwise-distinct content.

    Returns the forward-slashed relpaths of the BROKEN ones (empty unless
    ``broken_every`` is set), so a caller can assert on emission without
    mirroring the walk order.
    """
    broken: list[str] = []
    for i in range(count):
        rel = f"m{i:05d}.py"
        if broken_every and i % broken_every == 0:
            (root / rel).write_text(f"# {i}\ndef f{i}(:\n", encoding="utf-8")
            broken.append(rel)
        else:
            (root / rel).write_text(f"V{i} = {i}\n", encoding="utf-8")
    return broken


def _expected_error_line(source: str) -> int:
    """The 1-based line stdlib ``compile`` reports for ``source``.

    Derived, not assumed, so the guard survives a CPython diagnostic change.
    Fail-closed: a source that actually parses is a broken fixture.
    """
    try:
        compile(source, "<fixture>", "exec")
    except SyntaxError as exc:  # the only expected outcome
        assert exc.lineno is not None, "fixture must report a line number"
        return exc.lineno
    raise AssertionError("fixture is not a syntax error; the test proves nothing")


# ----------------------------------------------------------------------------
# Behavior 1 -- warm output is byte-identical to cold output
# ----------------------------------------------------------------------------


def test_b01_warm_output_is_field_identical_to_cold_output(tmp_path: Path) -> None:
    (tmp_path / "ok.py").write_text("A = 1\n", encoding="utf-8")
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "bad.py").write_text("B = 2\n" + _BROKEN, encoding="utf-8")

    clear_parse_memo()
    cold = SyntaxErrorCollector().collect(tmp_path)
    warm = SyntaxErrorCollector().collect(tmp_path)

    # Non-vacuity: a tree that emitted nothing would make equality meaningless.
    assert len(cold) == 1, f"expected one syntax_error signal; got {_rows(cold)!r}"
    assert len(warm) == len(cold)
    assert _rows(warm) == _rows(cold), (
        "a warm collect must be indistinguishable from a cold one; "
        f"cold={_rows(cold)!r} warm={_rows(warm)!r}"
    )
    # And the second collect really was warm, or behavior 1 is untested.
    assert parse_memo_stats()["hits"] >= 1, parse_memo_stats()


# ----------------------------------------------------------------------------
# Behavior 2 -- a second collect over an unchanged tree performs ZERO parses
# ----------------------------------------------------------------------------


def test_b02_second_collect_over_unchanged_tree_performs_zero_parses(
    tmp_path: Path,
) -> None:
    n = 6
    _distinct_tree(tmp_path, n)

    clear_parse_memo()
    SyntaxErrorCollector().collect(tmp_path)
    first = parse_memo_stats()
    assert first["misses"] == n, f"cold collect must parse all {n} files; got {first!r}"
    assert first["hits"] == 0, f"cold collect cannot hit; got {first!r}"
    assert first["entries"] == n, first

    SyntaxErrorCollector().collect(tmp_path)
    second = parse_memo_stats()
    assert second["misses"] == n, (
        "an unchanged tree must not be re-parsed even once: misses moved from "
        f"{first['misses']} to {second['misses']}"
    )
    assert second["hits"] == n, (
        f"every one of {n} files must be served from the memo; got {second!r}"
    )
    assert second["entries"] == n, second


def test_b02_fresh_collector_instances_still_hit_the_memo(tmp_path: Path) -> None:
    """The memo must be MODULE-level: the real workload builds a NEW collector
    per tick, so an instance-level memo would never hit (the spec's trap)."""
    n = 4
    _distinct_tree(tmp_path, n)
    clear_parse_memo()

    for _ in range(3):
        SyntaxErrorCollector().collect(tmp_path)  # a distinct object each time

    stats = parse_memo_stats()
    assert stats["misses"] == n, f"only the first tick may parse; got {stats!r}"
    assert stats["hits"] == 2 * n, f"ticks 2 and 3 must be all hits; got {stats!r}"


# ----------------------------------------------------------------------------
# Behavior 3 -- changing one file invalidates exactly that file
# ----------------------------------------------------------------------------


def test_b03_changing_one_file_invalidates_only_that_file(tmp_path: Path) -> None:
    n = 5
    _distinct_tree(tmp_path, n)
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    target = pkg / "changed.py"
    target.write_text("KEEP = 0\n", encoding="utf-8")
    total = n + 1

    clear_parse_memo()
    SyntaxErrorCollector().collect(tmp_path)
    warm = parse_memo_stats()
    assert warm == {"hits": 0, "misses": total, "entries": total}, warm

    new_source = "A = 1\nB = 2\n" + _BROKEN
    target.write_text(new_source, encoding="utf-8")
    sigs = SyntaxErrorCollector().collect(tmp_path)

    after = parse_memo_stats()
    assert after["misses"] == total + 1, (
        "exactly one file changed, so exactly one new parse is allowed; "
        f"misses {warm['misses']} -> {after['misses']}"
    )
    assert after["hits"] == total - 1, (
        f"the {total - 1} unchanged files must all hit; got {after!r}"
    )

    rel = target.relative_to(tmp_path).as_posix()
    assert rel == "pkg/changed.py"
    matching = [s for s in sigs if s.path == rel]
    assert len(matching) == 1, (
        f"the changed file must be reported once at {rel!r}; got {_rows(sigs)!r}"
    )
    sig = matching[0]
    assert sig.kind == "syntax_error", sig.kind
    expected_line = _expected_error_line(new_source)
    assert (sig.summary or "").endswith(str(expected_line)), (
        f"summary must end with the new 1-based error line {expected_line}; "
        f"got {sig.summary!r}"
    )
    # Fail-closed: line 1 would also "end with a digit", so prove it moved.
    assert expected_line > 1, "fixture must break below line 1 to be meaningful"


# ----------------------------------------------------------------------------
# Behavior 4 -- byte-identical files share one parse
# ----------------------------------------------------------------------------


def test_b04_byte_identical_files_share_one_parse(tmp_path: Path) -> None:
    k = 3
    body = "X = 1\n" + _BROKEN
    rels = ["a.py", "pkg/b.py", "pkg/deep/c.py"]
    assert len(rels) == k
    for rel in rels:
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")

    clear_parse_memo()
    sigs = SyntaxErrorCollector().collect(tmp_path)

    assert len(sigs) == k, f"each copy must be reported; got {_rows(sigs)!r}"
    assert sorted(s.path or "" for s in sigs) == sorted(rels), _rows(sigs)
    for s in sigs:
        assert (s.summary or "").startswith(f"{s.path}:"), (
            f"each signal must name its OWN path; got {s.summary!r} for {s.path!r}"
        )

    stats = parse_memo_stats()
    assert stats["misses"] == 1, (
        f"{k} byte-identical files must cost exactly one parse; got {stats!r}"
    )
    assert stats["entries"] == 1, stats
    assert stats["hits"] == k - 1, stats


# ----------------------------------------------------------------------------
# Behavior 5 -- the memo is bounded
# ----------------------------------------------------------------------------


def test_b05_memo_is_bounded_by_the_exported_cap_constant(tmp_path: Path) -> None:
    """At the SHIPPED cap: more distinct files than the cap leaves entries == cap,
    and eviction does not change the emitted signal list."""
    cap = PARSE_MEMO_MAX_ENTRIES
    assert isinstance(cap, int) and cap > 0, f"bad cap constant: {cap!r}"
    total = cap + 4
    broken = _distinct_tree(tmp_path, total, broken_every=500)
    assert len(broken) >= 2, "need several broken files for a non-vacuous compare"

    clear_parse_memo()
    evicting = SyntaxErrorCollector().collect(tmp_path)
    stats = parse_memo_stats()
    assert stats["misses"] == total, stats
    assert stats["entries"] == cap, (
        f"entries must saturate at the cap {cap}, never exceed it; got {stats!r}"
    )

    clear_parse_memo()
    fresh = SyntaxErrorCollector().collect(tmp_path)
    assert _rows(evicting) == _rows(fresh), (
        "eviction must never change output; "
        f"evicting={_rows(evicting)[:3]!r} fresh={_rows(fresh)[:3]!r}"
    )
    assert len(evicting) >= 2, f"non-vacuous compare required; got {_rows(evicting)!r}"


def test_b05_cap_constant_is_read_at_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fail-closed companion: with the cap patched DOWN the memo stops at the
    patched value, and with the patch lifted the same tree stores every file --
    so the bound is really the constant and not a coincidence of tree size."""
    total = 12
    small = 5
    _distinct_tree(tmp_path, total)

    monkeypatch.setattr(syntax_error_mod, "PARSE_MEMO_MAX_ENTRIES", small)
    clear_parse_memo()
    SyntaxErrorCollector().collect(tmp_path)
    patched = parse_memo_stats()
    assert patched["entries"] == small, (
        f"cap patched to {small} but memo holds {patched['entries']} entries"
    )
    assert patched["misses"] == total, patched

    monkeypatch.undo()
    clear_parse_memo()
    SyntaxErrorCollector().collect(tmp_path)
    unpatched = parse_memo_stats()
    assert unpatched["entries"] == total, (
        "with the shipped cap this tree fits entirely, so the previous assertion "
        f"was really about the constant; got {unpatched!r}"
    )


# ----------------------------------------------------------------------------
# Behavior 6 -- clear_parse_memo() empties it
# ----------------------------------------------------------------------------


def test_b06_clear_parse_memo_empties_the_memo(tmp_path: Path) -> None:
    _distinct_tree(tmp_path, 3)
    SyntaxErrorCollector().collect(tmp_path)
    assert parse_memo_stats()["entries"] >= 1, "precondition: memo must be warm"

    assert clear_parse_memo() is None, "clear_parse_memo() must return None"
    assert parse_memo_stats() == {"hits": 0, "misses": 0, "entries": 0}, (
        f"clear must zero every counter; got {parse_memo_stats()!r}"
    )

    SyntaxErrorCollector().collect(tmp_path)
    after = parse_memo_stats()
    assert after["misses"] >= 1, f"a cleared memo must re-parse; got {after!r}"
    assert after["hits"] == 0, f"nothing can be cached after a clear; got {after!r}"


# ----------------------------------------------------------------------------
# Behavior 7 -- skipped files never populate the memo
# ----------------------------------------------------------------------------


def test_b07_skipped_files_never_populate_the_memo(tmp_path: Path) -> None:
    limit = 512
    (tmp_path / "clean.py").write_text("A = 1\n", encoding="utf-8")
    oversized = tmp_path / "big.py"
    oversized.write_bytes(_BROKEN.encode("utf-8") + b"# pad\n" * 400)
    (tmp_path / "latin.py").write_bytes(b"# caf\xe9\n" + _BROKEN.encode("utf-8"))
    (tmp_path / "nul.py").write_bytes(b"A = 1\x00\n" + _BROKEN.encode("utf-8"))
    (tmp_path / ".broken.py").write_text(_BROKEN, encoding="utf-8")

    collector = SyntaxErrorCollector(max_read_bytes=limit)
    # Name the LIVE value rather than assume it (reviewer's rule): the oversize
    # fixture must really exceed the collector's own limit, and the clean file
    # must really be under it, or this test proves nothing.
    assert oversized.stat().st_size > collector.max_read_bytes
    assert (tmp_path / "clean.py").stat().st_size < collector.max_read_bytes

    clear_parse_memo()
    sigs = collector.collect(tmp_path)

    assert sigs == [], (
        "every broken file here is skipped before the parse, so nothing may be "
        f"emitted; got {_rows(sigs)!r}"
    )
    stats = parse_memo_stats()
    assert stats["entries"] == 1, (
        "only the one successfully-decoded, NUL-free file may be memoized; "
        f"got {stats!r}"
    )
    assert stats["misses"] == 1, stats
    assert stats["hits"] == 0, stats


# ----------------------------------------------------------------------------
# Behavior 8 -- stats shape
# ----------------------------------------------------------------------------


def test_b08_parse_memo_stats_shape(tmp_path: Path) -> None:
    clear_parse_memo()
    empty = parse_memo_stats()
    assert isinstance(empty, dict)
    assert set(empty) == _STATS_KEYS, f"unexpected key set: {sorted(empty)!r}"
    assert all(isinstance(v, int) and not isinstance(v, bool) for v in empty.values())
    assert all(v >= 0 for v in empty.values()), empty

    _distinct_tree(tmp_path, 2)
    SyntaxErrorCollector().collect(tmp_path)
    SyntaxErrorCollector().collect(tmp_path)
    warm = parse_memo_stats()
    assert set(warm) == _STATS_KEYS, sorted(warm)
    assert all(isinstance(v, int) and v >= 0 for v in warm.values()), warm
    assert warm["hits"] > 0 and warm["misses"] > 0, (
        f"a non-trivial reading is needed to test the shape; got {warm!r}"
    )

    # Strengthening (see AMBIGUITY NOTES): the reading is a snapshot.
    snapshot = dict(warm)
    warm["hits"] = -1
    warm["bogus"] = 1
    assert parse_memo_stats() == snapshot, (
        "parse_memo_stats() must hand back a copy, not live internal state"
    )

    # The published signature is annotated, per the acceptance criteria.
    for fn in (clear_parse_memo, parse_memo_stats):
        sig = inspect.signature(fn)
        assert sig.return_annotation is not inspect.Signature.empty, (
            f"{fn.__name__} must be fully type-annotated"
        )


# ----------------------------------------------------------------------------
# Behavior 9 -- no user-visible CLI change
# ----------------------------------------------------------------------------


def _signals(workspace: Path, capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    capsys.readouterr()  # drain
    rc = main(["signals", "--workspace", str(workspace), "--collector", "syntax_error"])
    return rc, capsys.readouterr().out


@pytest.mark.parametrize("plant_broken", [False, True], ids=["clean_tree", "broken_tree"])
def test_b09_two_signals_invocations_produce_identical_stdout(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    plant_broken: bool,
) -> None:
    for name in [k for k in list(os.environ) if k.startswith("PLA_")]:
        monkeypatch.delenv(name, raising=False)

    _distinct_tree(tmp_path, 3)
    rel = "pkg/broken.py"
    if plant_broken:
        (tmp_path / "pkg").mkdir()
        (tmp_path / rel).write_text("A = 1\n" + _BROKEN, encoding="utf-8")

    clear_parse_memo()
    rc1, out1 = _signals(tmp_path, capsys)
    rc2, out2 = _signals(tmp_path, capsys)

    assert rc1 == 0 and rc2 == 0, f"exit codes {rc1}, {rc2}"
    assert out1 == out2, (
        "a warm invocation must print byte-identical stdout;\n"
        f"first={out1!r}\nsecond={out2!r}"
    )
    assert out1.strip(), "stdout must not be empty, or the compare is vacuous"
    if plant_broken:
        mentions = [ln for ln in out1.splitlines() if rel in ln]
        assert len(mentions) == 1, (
            f"the broken file must be REPORTED on exactly one line; got {out1!r}"
        )
        assert "(1)" in out1, (
            f"the group header must count exactly one signal; got {out1!r}"
        )
    else:
        assert rel not in out1, out1
