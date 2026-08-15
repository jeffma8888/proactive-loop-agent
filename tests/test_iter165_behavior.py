"""Black-box behavior tests for factory iteration 165 --- the ``merge_conflict`` memo.

Feature under test: ``MergeConflictCollector`` memoizes its per-line conflict-marker
COUNT on a digest of each file's decoded text, in a bounded MODULE-level map, so a
``pla watch`` tick line-scans one distinct file content at most once per process while
emitting byte-identical signals. Two module-level functions publish the state ---
``clear_merge_conflict_memo()`` and ``merge_conflict_memo_stats()`` --- and ONE module
constant bounds it: ``MERGE_CONFLICT_MEMO_MAX_ENTRIES`` (how many counts may be
retained). Unlike ``todos`` there is no second per-file item cap, because the memoized
value is a single ``int``.

ISOLATION CONTRACT (honored): written strictly against this iteration's spec
(``pm.md`` "Expected Behaviors" 1-8) plus the conventions of the existing modules under
``tests/`` (``test_iter130_behavior.py`` is the shipped sibling-memo precedent for this
style, and ``test_iter28_behavior.py`` is the precedent for this collector's fixtures).
Every assertion drives a public surface --- ``MergeConflictCollector(...).collect(root)``,
the two new module-level functions, and the exported cap constant. **No file under
``src/`` was read while writing this module, no engineer / reviewer / fix note was
opened, and no ``git diff`` was consulted.** Where the shape of the collector was needed
it was obtained by RUNNING it and by ``inspect.signature`` on its public constructor,
never by reading its source.

Fully offline and deterministic: synthetic ``tmp_path`` trees only (never the in-repo
tree, so no collector can leak repo state --- iter-15 lesson), no network, no API key,
no sleeps, and NO DURATION IS ASSERTED ANYWHERE (roadmap row #129's standing constraint
--- the speed win is measured by hand at the gate, never by a test).

Because the memo is deliberately MODULE-level (process-global) state, an autouse fixture
clears it --- and the sibling ``todos`` memo --- before every test, so no test can
inherit another's hits/misses under any collection or ``-n`` distribution order.

AMBIGUITY NOTES (PM feedback):

* Behavior 3 lists six fields to compare and omits ``timestamp``. This module compares
  SEVEN (``timestamp`` included, as ``test_iter130_behavior.py`` does): the shipped
  collector leaves it ``None``, so including it is strictly stronger and would catch a
  memo that started stamping a cached value.
* Behavior 5 says the edit "increases ``misses`` by exactly 1". Read as an exact delta,
  and this module additionally pins the ``hits`` delta at 0 for that scan: the fixture
  holds one file, so a hit there could only be a stale answer.
* Behavior 6 says ``entries <= 2`` under a cap of 2. The observed value is exactly 2;
  the spec's inequality is asserted as written (a stricter equality would over-pin an
  eviction policy the spec leaves free beyond "deterministic FIFO").
* Behavior 8's "capped at ``max_items``" is exercised with ``max_items=2`` over three
  marker files rather than 31 files at the shipped default of 30 --- same contract,
  and it keeps this module's fixtures cheap (the 30-cap itself is already pinned by
  ``test_iter28_behavior.py::test_b10_deterministic_cap_at_max_items``).
* Behavior 8's oversize case is asserted as a DELTA across two scans of the same tree
  (add the oversize file, rescan): that is what "leaves ``hits + misses`` unchanged"
  can mean observably, and it also proves the oversize file is not emitted.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from proactive_loop.collectors import merge_conflict as merge_conflict_mod
from proactive_loop.collectors.merge_conflict import (
    MERGE_CONFLICT_MEMO_MAX_ENTRIES,
    MergeConflictCollector,
    clear_merge_conflict_memo,
    merge_conflict_memo_stats,
)
from proactive_loop.collectors.todos import (
    TodoCollector,
    clear_todo_memo,
    todo_memo_stats,
)
from proactive_loop.models import ContextSignal

# Behavior 3's comparison contract (the spec's six fields, plus ``timestamp`` --- see
# AMBIGUITY NOTES).
_FIELDS = ("source", "kind", "summary", "detail", "path", "weight", "timestamp")
_STATS_KEYS = {"hits", "misses", "entries"}

# Two genuine markers (an open and a close line); the counter counts marker LINES.
_TWO_MARKERS = "<<<<<<< HEAD\nours\n=======\ntheirs\n>>>>>>> feature\n"
# One genuine marker (open only) --- still a real conflict signal.
_ONE_MARKER = "<<<<<<< HEAD\nours only\n"


@pytest.fixture(autouse=True)
def _cold_memos() -> None:
    """Both content memos start EMPTY for every test in this module.

    The memo under test is module-level on purpose (that is behavior 3), so without
    this the counters would depend on execution order.
    """
    clear_merge_conflict_memo()
    clear_todo_memo()


def _rows(sigs: list[ContextSignal]) -> list[tuple[object, ...]]:
    """Field-by-field projection of a signal list, in emission order."""
    return [tuple(getattr(s, f) for f in _FIELDS) for s in sigs]


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _three_distinct(root: Path) -> Path:
    """Behaviors 2 and 3: three scanned-extension files, three DISTINCT contents, at
    least one carrying genuine marker lines.

    Returns the marker file.
    """
    marked = _write(root / "a.py", _TWO_MARKERS)
    _write(root / "notes.md", "just prose, no markers\n")
    _write(root / "web" / "app.ts", "const x = 1;\n")
    return marked


# ---------------------------------------------------------------------------
# Behavior 1 -- the seam exists, is typed, and its snapshot is immutable
# ---------------------------------------------------------------------------


def test_b01_the_seam_is_importable_and_the_cap_is_a_positive_int() -> None:
    """Behavior 1: the three public names import, and the cap is an ``int`` > 0."""
    assert callable(clear_merge_conflict_memo)
    assert callable(merge_conflict_memo_stats)
    assert isinstance(MERGE_CONFLICT_MEMO_MAX_ENTRIES, int)
    assert not isinstance(MERGE_CONFLICT_MEMO_MAX_ENTRIES, bool), "a bool is not a cap"
    assert MERGE_CONFLICT_MEMO_MAX_ENTRIES > 0, (
        "the shipped cap must permit retention; "
        f"got {MERGE_CONFLICT_MEMO_MAX_ENTRIES!r}"
    )


def test_b01_stats_is_a_dict_str_int_with_exactly_three_keys() -> None:
    """Behavior 1: key set is EXACTLY hits/misses/entries and every value is an int."""
    stats = merge_conflict_memo_stats()
    assert isinstance(stats, dict)
    assert set(stats) == _STATS_KEYS, f"unexpected key set: {sorted(stats)!r}"
    for key, value in stats.items():
        assert isinstance(key, str), f"key {key!r} is not a str"
        assert isinstance(value, int) and not isinstance(value, bool), (
            f"stats[{key!r}] must be an int; got {value!r}"
        )
    assert stats == {"hits": 0, "misses": 0, "entries": 0}, (
        "a cleared memo reports three zeros"
    )


def test_b01_mutating_the_returned_snapshot_cannot_reach_the_memo(
    tmp_path: Path,
) -> None:
    """Behavior 1: the returned dict is a snapshot, not a live view."""
    _three_distinct(tmp_path)
    MergeConflictCollector().collect(tmp_path)

    first = merge_conflict_memo_stats()
    baseline = dict(first)
    first["hits"] = 10_000
    first["misses"] = -1
    first["entries"] = -1
    first["injected"] = 1

    assert merge_conflict_memo_stats() == baseline, (
        "mutating the snapshot must not change what the next call returns"
    )
    assert set(merge_conflict_memo_stats()) == _STATS_KEYS, (
        "an injected key must not survive into the next snapshot"
    )
    assert merge_conflict_memo_stats() is not merge_conflict_memo_stats(), (
        "each call must hand back a fresh snapshot object"
    )


# ---------------------------------------------------------------------------
# Behavior 2 -- a cold scan is one miss per decoded candidate, and no hits
# ---------------------------------------------------------------------------


def test_b02_cold_scan_is_one_miss_per_decoded_candidate_and_no_hits(
    tmp_path: Path,
) -> None:
    """Behavior 2: 3 distinct contents -> misses 3, hits 0, entries 3."""
    _three_distinct(tmp_path)

    sigs = MergeConflictCollector().collect(tmp_path)

    assert [s.path for s in sigs] == ["a.py"], (
        "only the marker file may emit a signal; got "
        f"{[s.path for s in sigs]!r}"
    )
    assert merge_conflict_memo_stats() == {"hits": 0, "misses": 3, "entries": 3}, (
        f"cold scan counters wrong: {merge_conflict_memo_stats()!r}"
    )


# ---------------------------------------------------------------------------
# Behavior 3 -- a FRESH collector instance is served entirely from the memo
# ---------------------------------------------------------------------------


def test_b03_a_fresh_instance_is_served_entirely_from_the_module_level_memo(
    tmp_path: Path,
) -> None:
    """Behavior 3: the memo is module-level, not per-instance."""
    _three_distinct(tmp_path)

    cold_rows = _rows(MergeConflictCollector().collect(tmp_path))
    assert merge_conflict_memo_stats()["misses"] == 3

    # A NEWLY constructed collector, with no intervening clear.
    warm_rows = _rows(MergeConflictCollector().collect(tmp_path))

    stats = merge_conflict_memo_stats()
    assert stats["misses"] == 3, (
        "a warm pass must add no miss (a per-instance memo would show 6); "
        f"got {stats!r}"
    )
    assert stats["hits"] == 3, f"every candidate must be a hit; got {stats!r}"
    assert warm_rows == cold_rows, (
        "the warm signal list must be field-for-field equal to the cold one"
    )


# ---------------------------------------------------------------------------
# Behavior 4 -- K byte-identical files share ONE scan, each keeps its own path
# ---------------------------------------------------------------------------


def test_b04_identical_files_share_one_scan_and_still_report_their_own_paths(
    tmp_path: Path,
) -> None:
    """Behavior 4: 5 identical files -> misses 1, hits 4, 5 distinct paths."""
    names = [f"f{i}.py" for i in range(5)]
    for name in names:
        _write(tmp_path / name, _TWO_MARKERS)

    sigs = MergeConflictCollector().collect(tmp_path)

    assert merge_conflict_memo_stats() == {"hits": 4, "misses": 1, "entries": 1}, (
        "identical content must be scanned once and served 4 times; got "
        f"{merge_conflict_memo_stats()!r}"
    )
    assert [s.path for s in sigs] == sorted(names), (
        "every file keeps its own relative path"
    )
    assert [s.summary for s in sigs] == [
        f"{name}: 2 conflict markers" for name in sorted(names)
    ], "each summary reports that file's own path and marker count"


# ---------------------------------------------------------------------------
# Behavior 5 -- an edit can never hit a stale entry
# ---------------------------------------------------------------------------


def test_b05_an_edit_invalidates_the_entry_and_the_new_count_is_reported(
    tmp_path: Path,
) -> None:
    """Behavior 5: append a marker line -> exactly one new miss, count 3 not 2."""
    target = _write(tmp_path / "e.py", _TWO_MARKERS)
    collector = MergeConflictCollector()
    collector.collect(tmp_path)
    warm = collector.collect(tmp_path)
    assert [s.summary for s in warm] == ["e.py: 2 conflict markers"]
    before = merge_conflict_memo_stats()

    with target.open("a", encoding="utf-8") as handle:
        handle.write("<<<<<<< HEAD\n")

    sigs = MergeConflictCollector().collect(tmp_path)
    after = merge_conflict_memo_stats()

    assert after["misses"] - before["misses"] == 1, (
        f"the edited content must be exactly one new miss; {before!r} -> {after!r}"
    )
    assert after["hits"] - before["hits"] == 0, (
        f"a stale hit would be a wrong answer; {before!r} -> {after!r}"
    )
    assert [s.summary for s in sigs] == ["e.py: 3 conflict markers"], (
        f"the new marker count must be reported; got {[s.summary for s in sigs]!r}"
    )


# ---------------------------------------------------------------------------
# Behavior 6 -- the entry cap bounds RETENTION, never correctness
# ---------------------------------------------------------------------------


def _five_distinct_marker_files(root: Path) -> list[str]:
    names = [f"g{i}.py" for i in range(5)]
    for i, name in enumerate(names):
        _write(root / name, f"<<<<<<< HEAD\nvariant {i}\n>>>>>>> feature\n")
    return sorted(names)


def test_b06_a_lowered_cap_bounds_entries_and_changes_no_signal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Behavior 6: cap 2 over 5 distinct contents -> entries <= 2, same signals."""
    _five_distinct_marker_files(tmp_path)
    shipped_rows = _rows(MergeConflictCollector().collect(tmp_path))

    monkeypatch.setattr(merge_conflict_mod, "MERGE_CONFLICT_MEMO_MAX_ENTRIES", 2)
    clear_merge_conflict_memo()
    capped_rows = _rows(MergeConflictCollector().collect(tmp_path))

    stats = merge_conflict_memo_stats()
    assert stats["entries"] <= 2, (
        f"the cap must be read at call time and bound retention; got {stats!r}"
    )
    assert stats["misses"] == 5, f"all five contents are still scanned; got {stats!r}"
    assert capped_rows == shipped_rows, (
        "the cap may cost speed, never correctness: signals must be unchanged"
    )


def test_b06_a_zero_cap_disables_retention_without_changing_signals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Behavior 6: cap 0 -> entries 0 and hits 0 on two consecutive scans."""
    _five_distinct_marker_files(tmp_path)
    shipped_rows = _rows(MergeConflictCollector().collect(tmp_path))

    monkeypatch.setattr(merge_conflict_mod, "MERGE_CONFLICT_MEMO_MAX_ENTRIES", 0)
    clear_merge_conflict_memo()

    first_rows = _rows(MergeConflictCollector().collect(tmp_path))
    first = merge_conflict_memo_stats()
    second_rows = _rows(MergeConflictCollector().collect(tmp_path))
    second = merge_conflict_memo_stats()

    assert first["entries"] == 0 and second["entries"] == 0, (
        f"cap 0 must retain nothing; {first!r} then {second!r}"
    )
    assert first["hits"] == 0 and second["hits"] == 0, (
        f"with nothing retained there can be no hit; {first!r} then {second!r}"
    )
    assert second["misses"] == 2 * first["misses"], (
        f"every scan must re-scan every content; {first!r} then {second!r}"
    )
    assert first_rows == shipped_rows and second_rows == shipped_rows, (
        "disabling retention must not change a single emitted signal"
    )


# ---------------------------------------------------------------------------
# Behavior 7 -- clearing is scoped to ONE memo
# ---------------------------------------------------------------------------


def _todo_and_conflict(root: Path) -> None:
    _write(root / "both.py", "# TODO: land the memo\n" + _TWO_MARKERS)


def test_b07_clearing_the_merge_conflict_memo_leaves_the_todo_memo_intact(
    tmp_path: Path,
) -> None:
    """Behavior 7: the two maps are separate; clearing one cannot reach the other."""
    _todo_and_conflict(tmp_path)
    TodoCollector().collect(tmp_path)
    MergeConflictCollector().collect(tmp_path)
    todo_before = todo_memo_stats()
    assert todo_before["entries"] > 0, "precondition: the todo memo is warm"
    assert merge_conflict_memo_stats()["entries"] > 0, "precondition: mc memo is warm"

    clear_merge_conflict_memo()

    assert merge_conflict_memo_stats() == {"hits": 0, "misses": 0, "entries": 0}, (
        f"the mc memo must be fully cleared; got {merge_conflict_memo_stats()!r}"
    )
    assert todo_memo_stats() == todo_before, (
        f"the todo memo must be untouched; {todo_before!r} -> {todo_memo_stats()!r}"
    )
    assert todo_memo_stats()["entries"] > 0, "and still non-zero"


def test_b07_clearing_the_todo_memo_leaves_the_merge_conflict_memo_intact(
    tmp_path: Path,
) -> None:
    """Behavior 7, symmetric direction."""
    _todo_and_conflict(tmp_path)
    TodoCollector().collect(tmp_path)
    MergeConflictCollector().collect(tmp_path)
    mc_before = merge_conflict_memo_stats()
    assert mc_before["entries"] > 0, "precondition: the mc memo is warm"

    clear_todo_memo()

    assert todo_memo_stats() == {"hits": 0, "misses": 0, "entries": 0}, (
        f"the todo memo must be fully cleared; got {todo_memo_stats()!r}"
    )
    assert merge_conflict_memo_stats() == mc_before, (
        f"the mc memo must be untouched; {mc_before!r} -> "
        f"{merge_conflict_memo_stats()!r}"
    )
    assert merge_conflict_memo_stats()["entries"] > 0, "and still non-zero"


# ---------------------------------------------------------------------------
# Behavior 8 -- no semantic change, and only decoded text is counted
# ---------------------------------------------------------------------------


def test_b08_signals_equal_an_enumerated_list_cold_and_warm(tmp_path: Path) -> None:
    """Behavior 8a: exact expected list, ascending relpath, on both passes."""
    _write(tmp_path / "a.md", _TWO_MARKERS)
    _write(tmp_path / "c.ts", _TWO_MARKERS)
    _write(tmp_path / "sub" / "b.py", _ONE_MARKER)
    _write(tmp_path / "clean.py", "no markers here\n")

    expected = [
        ("merge_conflict", "merge_conflict", "a.md: 2 conflict markers", "", "a.md", 0.9, None),
        ("merge_conflict", "merge_conflict", "c.ts: 2 conflict markers", "", "c.ts", 0.9, None),
        (
            "merge_conflict",
            "merge_conflict",
            "sub/b.py: 1 conflict marker",
            "",
            "sub/b.py",
            0.9,
            None,
        ),
    ]

    collector = MergeConflictCollector()
    assert _rows(collector.collect(tmp_path)) == expected, "cold pass"
    assert _rows(MergeConflictCollector().collect(tmp_path)) == expected, "warm pass"

    # ... and the max_items cap still truncates the SAME ascending list.
    capped = MergeConflictCollector(max_items=2)
    assert _rows(capped.collect(tmp_path)) == expected[:2], "cold, capped at 2"
    assert _rows(MergeConflictCollector(max_items=2).collect(tmp_path)) == expected[:2], (
        "warm, capped at 2"
    )


def test_b08_a_file_too_large_to_read_is_neither_a_hit_nor_a_miss(
    tmp_path: Path,
) -> None:
    """Behavior 8b: misses count DECODED texts, not directory entries."""
    _write(tmp_path / "small.py", _ONE_MARKER)
    collector = MergeConflictCollector(max_read_bytes=64)
    collector.collect(tmp_path)
    before = merge_conflict_memo_stats()
    assert before == {"hits": 0, "misses": 1, "entries": 1}, (
        f"precondition: exactly the small file was scanned; got {before!r}"
    )

    oversize = _write(tmp_path / "big.py", "<<<<<<< HEAD\n" + ("x" * 500) + "\n")
    assert oversize.stat().st_size > 64, "fixture must exceed max_read_bytes"

    sigs = MergeConflictCollector(max_read_bytes=64).collect(tmp_path)
    after = merge_conflict_memo_stats()

    assert (after["hits"] + after["misses"]) - (
        before["hits"] + before["misses"]
    ) == 1, (
        "the oversize file must contribute neither a hit nor a miss (the one "
        f"increment is the small file's hit); {before!r} -> {after!r}"
    )
    assert after["misses"] == before["misses"], (
        f"no new content was decoded; {before!r} -> {after!r}"
    )
    assert [s.path for s in sigs] == ["small.py"], (
        f"the oversize file must not be reported; got {[s.path for s in sigs]!r}"
    )
