"""Black-box behavior tests for factory iteration 130 --- the ``todos`` extraction memo.

Feature under test: ``TodoCollector`` memoizes its per-line TODO/FIXME/XXX/checkbox
EXTRACTION on a content digest of each file's decoded text, in a bounded
MODULE-level map, so re-scanning an unchanged tree (every ``pla watch`` tick) stops
re-running the regex pass while emitting byte-identical signals. Two module-level
functions publish the state --- ``clear_todo_memo()`` and ``todo_memo_stats()`` ---
and TWO module constants bound it: ``TODO_MEMO_MAX_ENTRIES`` (how many values may be
retained) and ``TODO_MEMO_MAX_ITEMS_PER_FILE`` (how large a retained value may be).

ISOLATION CONTRACT (honored): written strictly against this iteration's spec
(``pm.md`` "Expected Behaviors" 1-10) plus the conventions of the existing modules
under ``tests/`` (``test_iter124_behavior.py`` is the shipped sibling memo and its
test file is the style precedent). Every assertion drives a public surface ---
``TodoCollector(...).collect(root)``, the two new module-level functions, the two
exported cap constants, and the installed ``pla`` console script. **No file under
``src/`` was read while writing this module, no engineer / reviewer / fix note was
opened, and no ``git diff`` was consulted.** Where the shape of the collector was
needed it was obtained by RUNNING it and by ``inspect.signature`` on its public
constructor, never by reading its source.

Fully offline and deterministic: synthetic ``tmp_path`` trees only (never the in-repo
tree, so no collector can leak repo state --- iter-15 lesson), no network, no API key,
no sleeps, and NO DURATION IS ASSERTED ANYWHERE (roadmap row #129's standing
constraint --- the speed win is measured by hand at the gate, never by a test).

Because the memo is deliberately MODULE-level (process-global) state, every test here
calls ``clear_todo_memo()`` before it asserts on counters, so no test can inherit
another's hits/misses.

AMBIGUITY NOTES (PM feedback):

* Behavior 1 lists six fields to compare and omits ``timestamp``. This module
  compares SEVEN (``timestamp`` included, as ``test_iter124_behavior.py`` does): the
  shipped collector leaves it ``None``, so including it is strictly stronger and
  would catch a memo that started stamping a cached value.
* Behavior 4 says the returned signals "differ from the warm run by exactly one added
  signal". Emission order is a global sort across files, so an inserted signal can
  legitimately move its neighbours; the assertion is therefore a MULTISET difference
  (exactly one row added, zero removed), which is order-independent and still exact.
* Behavior 6(a) says "MORE distinct file contents than the cap". The shipped cap is
  4096, so the fixture writes ``cap + 4`` files; that is the same shape (and the same
  cost class) as the shipped ``test_iter124_behavior.py::test_b05...`` guard.
* Behavior 7(a) says a second collect "increases ``misses`` by 1 again ... while a
  sibling 1-TODO file contributes no new miss". Read as an EXACT delta of 1: any
  larger delta would mean the sibling was also dropped.
* Behavior 9 says ``entries`` "equals the number of retained values". A test cannot
  count the private map, so this is asserted the only observable way: over a tree of
  K distinct contents whose values all fit both caps, ``entries == K``.
* Behavior 10(b) says two subprocess invocations must print byte-identical stdout.
  Each subprocess starts with a COLD memo, so this pins cross-process reproducibility
  (the memo is process-local and never persisted); the warm/cold identity inside one
  process is what behavior 1 pins.
"""

from __future__ import annotations

import inspect
import os
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

from proactive_loop.collectors import todos as todos_mod
from proactive_loop.collectors.syntax_error import (
    SyntaxErrorCollector,
    clear_parse_memo,
    parse_memo_stats,
)
from proactive_loop.collectors.todos import (
    TODO_MEMO_MAX_ENTRIES,
    TODO_MEMO_MAX_ITEMS_PER_FILE,
    TodoCollector,
    clear_todo_memo,
    todo_memo_stats,
)
from proactive_loop.models import ContextSignal

# Behavior 1's comparison contract (the spec's six fields, plus ``timestamp`` --- see
# AMBIGUITY NOTES).
_FIELDS = ("source", "kind", "summary", "detail", "path", "weight", "timestamp")
_STATS_KEYS = {"hits", "misses", "entries"}


def _rows(sigs: list[ContextSignal]) -> list[tuple[object, ...]]:
    """Field-by-field projection of a signal list, in emission order."""
    return [tuple(getattr(s, f) for f in _FIELDS) for s in sigs]


def _todo_tree(root: Path) -> Path:
    """The spec's *todo tree*: one ``.py``, one ``.ts``, one ``.js``, one ``.md`` with
    actionable items, plus one scanned-extension file with none.

    Returns the ``.py`` file that behavior 4 edits.
    """
    py = root / "a.py"
    py.write_text("# TODO: alpha\nA = 1\n", encoding="utf-8")
    web = root / "web"
    web.mkdir()
    (web / "app.ts").write_text("// FIXME: beta\n", encoding="utf-8")
    (web / "lib.js").write_text("x = 1\n// XXX gamma\n", encoding="utf-8")
    (root / "notes.md").write_text("intro\n\n- [ ] delta\n", encoding="utf-8")
    (root / "clean.py").write_text("B = 2\n", encoding="utf-8")  # no actionable item
    return py


def _distinct_tree(root: Path, count: int) -> None:
    """``count`` files of pairwise-distinct content, each carrying one TODO."""
    for i in range(count):
        (root / f"m{i:05d}.py").write_text(f"# TODO: item {i}\nV = {i}\n", encoding="utf-8")


# ----------------------------------------------------------------------------
# Behavior 1 -- warm output is field-identical to cold output
# ----------------------------------------------------------------------------


def test_b01_warm_output_is_field_identical_to_cold_output(tmp_path: Path) -> None:
    _todo_tree(tmp_path)

    clear_todo_memo()
    cold = TodoCollector().collect(tmp_path)
    warm = TodoCollector().collect(tmp_path)

    # Non-vacuity: a tree that emitted nothing would make equality meaningless.
    assert len(cold) == 4, f"expected four todo signals; got {_rows(cold)!r}"
    assert len(warm) == len(cold)
    assert _rows(warm) == _rows(cold), (
        "a warm collect must be indistinguishable from a cold one, in the same "
        f"order;\n  cold={_rows(cold)!r}\n  warm={_rows(warm)!r}"
    )
    # And the second collect really was warm, or behavior 1 is untested.
    assert todo_memo_stats()["hits"] >= 1, todo_memo_stats()


# ----------------------------------------------------------------------------
# Behavior 2 -- a second collect over an unchanged tree performs ZERO extractions
# ----------------------------------------------------------------------------


def test_b02_second_collect_over_unchanged_tree_performs_zero_extractions(
    tmp_path: Path,
) -> None:
    _todo_tree(tmp_path)

    clear_todo_memo()
    TodoCollector().collect(tmp_path)
    first = todo_memo_stats()
    assert first["misses"] >= 1, f"a cold collect must extract; got {first!r}"
    assert first["hits"] == 0, f"a cold collect cannot hit; got {first!r}"

    TodoCollector().collect(tmp_path)
    second = todo_memo_stats()
    assert second["misses"] == first["misses"], (
        "an unchanged tree must not be re-extracted even once: misses moved from "
        f"{first['misses']} to {second['misses']}"
    )
    assert second["hits"] >= first["hits"] + 1, (
        f"the second collect must be served from the memo; {first!r} -> {second!r}"
    )
    # Stronger, and the reason the win exists: EVERY scanned file hits, including
    # the one with no actionable item (an empty result is a legitimate cached value).
    assert second["hits"] == first["misses"], (
        "every file scanned cold must hit warm, clean files included; "
        f"{first!r} -> {second!r}"
    )


# ----------------------------------------------------------------------------
# Behavior 3 -- a fresh collector instance still hits the memo
# ----------------------------------------------------------------------------


def test_b03_fresh_collector_instance_still_hits_the_memo(tmp_path: Path) -> None:
    """The memo must be MODULE-level: ``all_collectors()`` rebuilds every collector
    per scan, so an instance-level memo would be dead on arrival."""
    _todo_tree(tmp_path)

    clear_todo_memo()
    TodoCollector().collect(tmp_path)
    warm = todo_memo_stats()

    for _ in range(2):
        TodoCollector().collect(tmp_path)  # a distinct object each time

    after = todo_memo_stats()
    assert after["misses"] == warm["misses"], (
        "only the first collect may extract; a new instance must reuse the "
        f"module-level memo. misses {warm['misses']} -> {after['misses']}"
    )
    assert after["hits"] == 2 * warm["misses"], (
        f"both later ticks must be all hits; got {after!r} after {warm!r}"
    )


def test_b03_a_differently_named_instance_still_reports_its_own_source(
    tmp_path: Path,
) -> None:
    """Guard on what must NOT be cached: ``source`` is per-instance, so a warm memo
    may not leak the warming instance's name into another instance's signals."""
    _todo_tree(tmp_path)

    clear_todo_memo()
    TodoCollector().collect(tmp_path)
    other = TodoCollector(name="other_todos").collect(tmp_path)

    assert other, "fixture must emit signals"
    assert {s.source for s in other} == {"other_todos"}, (
        f"a warm memo must not bake in the warming instance's name; got {_rows(other)!r}"
    )
    assert todo_memo_stats()["hits"] >= 1, "the second collect must have been warm"


# ----------------------------------------------------------------------------
# Behavior 4 -- editing exactly one file invalidates exactly that file
# ----------------------------------------------------------------------------


def test_b04_editing_one_file_invalidates_exactly_that_file(tmp_path: Path) -> None:
    target = _todo_tree(tmp_path)

    clear_todo_memo()
    TodoCollector().collect(tmp_path)
    warm_sigs = TodoCollector().collect(tmp_path)
    warm_stats = todo_memo_stats()

    new_text = target.read_text(encoding="utf-8") + "# TODO: added\n"
    target.write_text(new_text, encoding="utf-8")
    added_lineno = len(new_text.splitlines())
    assert added_lineno > 1, "the added line must not be line 1, or the path is ambiguous"

    after_sigs = TodoCollector().collect(tmp_path)
    after_stats = todo_memo_stats()

    assert after_stats["misses"] == warm_stats["misses"] + 1, (
        "exactly one file changed, so exactly one new extraction is allowed; "
        f"misses {warm_stats['misses']} -> {after_stats['misses']}"
    )

    before = Counter(_rows(warm_sigs))
    now = Counter(_rows(after_sigs))
    removed = before - now
    added = now - before
    assert removed == Counter(), f"nothing may be dropped; lost {list(removed)!r}"
    assert sum(added.values()) == 1, (
        f"exactly one signal must appear; added {list(added.elements())!r}"
    )
    (added_row,) = added.elements()
    rel = target.relative_to(tmp_path).as_posix()
    expected_path = f"{rel}:{added_lineno}"
    assert added_row[_FIELDS.index("path")] == expected_path, (
        f"the new signal must be located at {expected_path!r}; got {added_row!r}"
    )
    assert added_row[_FIELDS.index("summary")] == "TODO: added", added_row
    assert len(after_sigs) == len(warm_sigs) + 1 <= 30, (
        "the fixture must stay under the max_items cap so nothing is displaced"
    )


# ----------------------------------------------------------------------------
# Behavior 5 -- byte-identical files share ONE extraction, keep their own paths
# ----------------------------------------------------------------------------


def test_b05_byte_identical_files_share_one_extraction(tmp_path: Path) -> None:
    body = "# TODO: shared\n"
    (tmp_path / "a.py").write_text(body, encoding="utf-8")
    (tmp_path / "b.py").write_text(body, encoding="utf-8")

    clear_todo_memo()
    sigs = TodoCollector().collect(tmp_path)

    stats = todo_memo_stats()
    assert stats["misses"] == 1, (
        f"two byte-identical files must cost exactly one extraction; got {stats!r}"
    )
    assert stats["entries"] == 1, stats
    assert stats["hits"] == 1, stats

    paths = sorted(s.path or "" for s in sigs)
    assert paths == ["a.py:1", "b.py:1"], (
        f"each copy must report its OWN path; got {_rows(sigs)!r}"
    )


def test_b05_returned_signals_are_fresh_objects_each_call(tmp_path: Path) -> None:
    """A cached value must not be handed out as shared, mutable ``ContextSignal``
    objects: two calls must build new signals, or a caller mutates the cache."""
    (tmp_path / "a.py").write_text("# TODO: shared\n", encoding="utf-8")

    clear_todo_memo()
    first = TodoCollector().collect(tmp_path)
    second = TodoCollector().collect(tmp_path)

    assert _rows(first) == _rows(second)
    assert first and second
    ids = {id(s) for s in first} & {id(s) for s in second}
    assert not ids, "no ContextSignal object may be shared between two collect() calls"


# ----------------------------------------------------------------------------
# Behavior 6 -- an exported entry cap bounds the memo and is read at runtime
# ----------------------------------------------------------------------------


def test_b06a_entries_never_exceed_the_shipped_cap(tmp_path: Path) -> None:
    cap = TODO_MEMO_MAX_ENTRIES
    assert isinstance(cap, int) and not isinstance(cap, bool) and cap > 0, (
        f"bad cap constant: {cap!r}"
    )
    _distinct_tree(tmp_path, cap + 4)

    clear_todo_memo()
    sigs = TodoCollector().collect(tmp_path)
    stats = todo_memo_stats()
    assert stats["misses"] == cap + 4, (
        f"every distinct file must be extracted once; got {stats!r}"
    )
    assert stats["entries"] <= cap, (
        f"entries must never exceed the cap {cap}; got {stats!r}"
    )
    assert sigs, "eviction must not suppress emission"


def test_b06b_cap_is_read_at_runtime_and_output_is_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    total = 12
    small = 5
    _distinct_tree(tmp_path, total)

    clear_todo_memo()
    unpatched = TodoCollector().collect(tmp_path)
    assert todo_memo_stats()["entries"] == total, (
        "with the shipped cap this tree fits entirely, so the patched assertion "
        f"below is really about the constant; got {todo_memo_stats()!r}"
    )

    monkeypatch.setattr(todos_mod, "TODO_MEMO_MAX_ENTRIES", small)
    clear_todo_memo()
    patched = TodoCollector().collect(tmp_path)
    stats = todo_memo_stats()
    assert stats["entries"] <= small, (
        f"cap patched to {small} but memo holds {stats['entries']} entries"
    )
    assert stats["misses"] == total, stats
    assert _rows(patched) == _rows(unpatched), (
        "a lowered cap must not change emitted signals;\n"
        f"  unpatched={_rows(unpatched)!r}\n  patched={_rows(patched)!r}"
    )
    assert len(unpatched) >= 2, "non-vacuous compare required"


def test_b06c_cap_zero_disables_retention_without_changing_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _todo_tree(tmp_path)

    clear_todo_memo()
    reference = TodoCollector().collect(tmp_path)

    monkeypatch.setattr(todos_mod, "TODO_MEMO_MAX_ENTRIES", 0)
    clear_todo_memo()
    first = TodoCollector().collect(tmp_path)
    assert todo_memo_stats()["entries"] == 0, (
        f"retention must be disabled at cap 0; got {todo_memo_stats()!r}"
    )
    second = TodoCollector().collect(tmp_path)
    stats = todo_memo_stats()
    assert stats["hits"] == 0, f"nothing is retained, so nothing may hit; got {stats!r}"
    assert stats["entries"] == 0, stats
    assert _rows(first) == _rows(reference), "cap 0 must not change emitted signals"
    assert _rows(second) == _rows(reference), "cap 0 must not change emitted signals"
    assert reference, "non-vacuous compare required"


# ----------------------------------------------------------------------------
# Behavior 7 -- what is NOT retained
# ----------------------------------------------------------------------------


def test_b07a_over_cap_value_is_not_retained_but_is_fully_emitted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert isinstance(TODO_MEMO_MAX_ITEMS_PER_FILE, int), TODO_MEMO_MAX_ITEMS_PER_FILE
    assert not isinstance(TODO_MEMO_MAX_ITEMS_PER_FILE, bool)
    assert TODO_MEMO_MAX_ITEMS_PER_FILE > 0, TODO_MEMO_MAX_ITEMS_PER_FILE

    big = tmp_path / "big.py"
    big.write_text("# TODO: one\n# TODO: two\n# TODO: three\n", encoding="utf-8")
    (tmp_path / "small.py").write_text("# TODO: only\n", encoding="utf-8")

    monkeypatch.setattr(todos_mod, "TODO_MEMO_MAX_ITEMS_PER_FILE", 2)
    clear_todo_memo()
    first = TodoCollector().collect(tmp_path)
    before = todo_memo_stats()

    from_big = sorted(s.path or "" for s in first if (s.path or "").startswith("big.py"))
    assert from_big == ["big.py:1", "big.py:2", "big.py:3"], (
        "declining to RETAIN an over-cap value must never drop emitted signals; "
        f"got {_rows(first)!r}"
    )

    second = TodoCollector().collect(tmp_path)
    after = todo_memo_stats()
    assert after["misses"] == before["misses"] + 1, (
        "exactly the over-cap file may be re-extracted; the 1-item sibling must "
        f"hit. misses {before['misses']} -> {after['misses']}"
    )
    assert after["hits"] == before["hits"] + 1, (
        f"the sibling must be served from the memo; {before!r} -> {after!r}"
    )
    assert _rows(second) == _rows(first), "non-retention must not change output"


def test_b07b_an_unread_oversized_file_adds_no_entry(tmp_path: Path) -> None:
    limit = 512
    (tmp_path / "small.py").write_text("# TODO: only\n", encoding="utf-8")
    oversized = tmp_path / "big.md"
    oversized.write_text("- [ ] pad\n" * 200, encoding="utf-8")

    collector = TodoCollector(max_read_bytes=limit)
    # Name the LIVE value rather than assume it: the oversize fixture must really
    # exceed the collector's own limit, and the small file must be under it.
    assert oversized.stat().st_size > collector.max_read_bytes
    assert (tmp_path / "small.py").stat().st_size < collector.max_read_bytes

    clear_todo_memo()
    sigs = collector.collect(tmp_path)
    stats = todo_memo_stats()

    assert stats["entries"] == 1, (
        f"only the one file actually read may be memoized; got {stats!r}"
    )
    assert stats["misses"] == 1, stats
    assert [s.path for s in sigs] == ["small.py:1"], (
        f"an oversized file is skipped unread, so it emits nothing; got {_rows(sigs)!r}"
    )


# ----------------------------------------------------------------------------
# Behavior 8 -- clear_todo_memo() empties it
# ----------------------------------------------------------------------------


def test_b08_clear_todo_memo_empties_the_memo(tmp_path: Path) -> None:
    _todo_tree(tmp_path)
    clear_todo_memo()
    pre_clear = TodoCollector().collect(tmp_path)
    assert todo_memo_stats()["entries"] >= 1, "precondition: memo must be warm"

    assert clear_todo_memo() is None, "clear_todo_memo() must return None"
    assert todo_memo_stats() == {"hits": 0, "misses": 0, "entries": 0}, (
        f"clear must zero every counter; got {todo_memo_stats()!r}"
    )

    after = TodoCollector().collect(tmp_path)
    stats = todo_memo_stats()
    assert stats["misses"] >= 1, f"a cleared memo must re-extract; got {stats!r}"
    assert stats["hits"] == 0, f"nothing can be cached after a clear; got {stats!r}"
    assert _rows(after) == _rows(pre_clear), (
        "clearing the memo must not change emitted signals;\n"
        f"  before={_rows(pre_clear)!r}\n  after={_rows(after)!r}"
    )


# ----------------------------------------------------------------------------
# Behavior 9 -- todo_memo_stats() is a snapshot
# ----------------------------------------------------------------------------


def test_b09_todo_memo_stats_is_a_typed_snapshot(tmp_path: Path) -> None:
    clear_todo_memo()
    empty = todo_memo_stats()
    assert isinstance(empty, dict)
    assert set(empty) == _STATS_KEYS, f"unexpected key set: {sorted(empty)!r}"
    assert all(isinstance(v, int) and not isinstance(v, bool) for v in empty.values())
    assert all(v == 0 for v in empty.values()), empty

    k = 4
    _distinct_tree(tmp_path, k)
    TodoCollector().collect(tmp_path)
    TodoCollector().collect(tmp_path)
    warm = todo_memo_stats()
    assert set(warm) == _STATS_KEYS, sorted(warm)
    assert all(isinstance(v, int) and v >= 0 for v in warm.values()), warm
    assert warm["entries"] == k, (
        f"entries must equal the number of retained values; got {warm!r}"
    )
    assert warm["hits"] > 0 and warm["misses"] > 0, (
        f"a non-trivial reading is needed to test the shape; got {warm!r}"
    )

    snapshot = dict(warm)
    warm["hits"] = -1
    warm["bogus"] = 1
    assert todo_memo_stats() == snapshot, (
        "todo_memo_stats() must hand back a copy, not live internal state"
    )

    for fn in (clear_todo_memo, todo_memo_stats):
        sig = inspect.signature(fn)
        assert sig.return_annotation is not inspect.Signature.empty, (
            f"{fn.__name__} must be fully type-annotated"
        )


# ----------------------------------------------------------------------------
# Behavior 10 -- independence from the parse memo, and cross-process identity
# ----------------------------------------------------------------------------


def test_b10a_the_two_memos_are_independent(tmp_path: Path) -> None:
    _todo_tree(tmp_path)

    clear_todo_memo()
    clear_parse_memo()
    TodoCollector().collect(tmp_path)
    SyntaxErrorCollector().collect(tmp_path)
    todo_warm = todo_memo_stats()
    parse_warm = parse_memo_stats()
    assert todo_warm["entries"] >= 1 and parse_warm["entries"] >= 1, (
        f"both memos must be warm for a non-vacuous test; {todo_warm!r} {parse_warm!r}"
    )

    clear_todo_memo()
    assert todo_memo_stats()["entries"] == 0, todo_memo_stats()
    assert parse_memo_stats() == parse_warm, (
        f"clear_todo_memo() must not touch the parse memo; {parse_warm!r} -> "
        f"{parse_memo_stats()!r}"
    )

    TodoCollector().collect(tmp_path)
    todo_again = todo_memo_stats()
    clear_parse_memo()
    assert parse_memo_stats()["entries"] == 0, parse_memo_stats()
    assert todo_memo_stats() == todo_again, (
        f"clear_parse_memo() must not touch the todo memo; {todo_again!r} -> "
        f"{todo_memo_stats()!r}"
    )


def _console_script() -> Path:
    """The installed ``pla`` console script (iter114/iter128 resolution convention)."""
    bindir = Path(sys.executable).parent
    candidates = [bindir / "pla", bindir / "pla.exe"]
    which = shutil.which("pla")
    if which:
        candidates.append(Path(which))
    script = next((c for c in candidates if c.is_file()), None)
    assert script is not None, (
        "the `pla` console script must be installed (declared in pyproject and "
        f"installed by `uv sync`); searched {[str(c) for c in candidates]}"
    )
    return script


def test_b10b_two_signals_subprocesses_print_identical_stdout(tmp_path: Path) -> None:
    _todo_tree(tmp_path)
    argv = [
        str(_console_script()),
        "signals",
        "--workspace",
        str(tmp_path),
        "--json",
    ]
    env = {k: v for k, v in os.environ.items() if not k.startswith("PLA_")}

    runs = [
        subprocess.run(argv, capture_output=True, text=True, env=env, timeout=180)
        for _ in range(2)
    ]
    for proc in runs:
        assert proc.returncode == 0, (
            f"`pla signals --json` must succeed; rc={proc.returncode} "
            f"stderr={proc.stderr!r}"
        )
    first, second = runs[0].stdout, runs[1].stdout
    assert first == second, (
        "two separate invocations must print byte-identical stdout;\n"
        f"  first={first!r}\n  second={second!r}"
    )
    assert '"kind": "todo"' in first, (
        f"the fixture must produce todo signals, or the compare is vacuous; got {first!r}"
    )
    assert first.count('"kind": "todo"') == 4, first
