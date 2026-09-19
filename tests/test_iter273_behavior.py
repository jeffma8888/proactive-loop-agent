"""Black-box behavior tests for foundry iteration 315 (ROADMAP #294) -- the one-shot
20-item hand-off wall in ``tests/test_iter270_behavior.py::test_b7`` retires, and the
assertion re-anchors on the permanent 6-item gauge ``census.MIN_BINDING_HEADROOM``.

WHY THIS ITERATION EXISTS, in one paragraph a future reader needs. Foundry iter 312
promised the NEXT iteration 20 items of collected-item headroom and wrote that promise as
an UNCONDITIONAL assertion. Honoured once (at 47), the promise then outlived its
beneficiary: with the live count 20 under the README rounding boundary, every commit
adding 1..21 collected items was red, so the only legal deltas were 0 or >= 22. A gate
that forbids adding tests is a defect on a repo whose headline is auditability; it already
compressed one spec-conformant 12-item module to 4 items under a cap-killed tester round.

WHAT THIS MODULE GRADES: Expected Behaviors 1, 2, 3, 5 and 6 of the iteration spec.
Behavior 4 (the engineer's tree collects exactly what HEAD collected and README is
byte-identical) is a commit-time measurement that belongs in the tester's report, not in
a test that would be vacuous in every fresh clone; Behavior 7 is a no-op typecheck.

THIS MODULE'S OWN SIZE IS PART OF THE PROOF (Behavior 6). At the live count this
iteration inherited, a module of this size was ILLEGAL under the retired wall; the
re-anchored ``test_b7`` staying green with these items collected is the feature working.
Nothing here spawns a second ``--collect-only`` child: the live gauge is exercised only
through the seam ``test_b7`` already reads, with the count INJECTED, so the suite keeps
its one collection subprocess.

ISOLATION CONTRACT (honored). Every assertion below is written from this iteration's spec
(``pm.md`` Expected Behaviors and Acceptance Criteria), from the conventions of the repo's
own ``tests/`` tree, and from the product's OBSERVABLE surface. **No file under ``src/``
was read, no engineer's or reviewer's note was opened, no implementation patch and no
``git diff`` was inspected.** Fully offline and deterministic: every arm is a pure
function of tracked text or of the injected gauge. Nothing is written inside the repo.
"""

from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path
from typing import Final

import pytest

import tests.test_iter263_behavior as census
import tests.test_iter264_behavior as ledger
import tests.test_iter270_behavior as subject
import tests.test_readme_and_ci_contract as guard

REPO: Final[Path] = Path(__file__).resolve().parents[1]
TESTS_DIR: Final[Path] = REPO / "tests"
SRC_DIR: Final[Path] = REPO / "src"
ROADMAP: Final[Path] = REPO / "ROADMAP.md"
ARCHIVE: Final[Path] = REPO / "ROADMAP_ARCHIVE.md"
SUBJECT_PATH: Final[Path] = TESTS_DIR / "test_iter270_behavior.py"

#: Behavior 1/2. The function whose bound moves. Its NAME is kept verbatim (zero item-id
#: churn is an Acceptance Criterion), so it is spelled once here and looked up by name.
SUBJECT_TEST: Final[str] = (
    "test_b7_the_published_floor_is_unmoved_and_room_is_handed_to_the_next_iteration"
)

#: Behavior 2. The retired one-shot constant. Spelled in two halves so that THIS module
#: does not become the last file under ``tests/`` that still carries the token -- the
#: spec's own check is ``rg`` over ``tests/`` and ``src/`` printing nothing.
RETIRED_NAME: Final[str] = "MIN_BINDING_HEADROOM" + "_HANDED_ON"

#: Behavior 2. History the replacement note must keep: the one-shot budget and what was
#: actually handed on when it was honoured (ledger row #291).
RETIRED_BUDGET: Final[int] = 20
HANDED_ON_AT_ITER312: Final[int] = 47

#: Behavior 2. The phrase the old docstring and message used, gone after the re-anchor.
RETIRED_PHRASE: Final[str] = "whole purpose"

#: Behavior 2/6. ``test_iter270`` collects this many items before AND after the change.
SUBJECT_ITEMS: Final[int] = 11

#: Behavior 5. The Done-ledger row this commit adds, verbatim from the spec, the row it
#: must directly follow, and the tag the row must cite.
NEW_ROW: Final[str] = (
    "- #294 `test_iter270::test_b7` re-anchors on the 6-item gauge; "
    "the 20-item hand-off wall retires (foundry iter 315)"
)
PRIOR_ROW_PREFIX: Final[str] = "- #293 "
NEW_ROW_PREFIX: Final[str] = "- #294 "
SHIP_TAG: Final[str] = "foundry iter 315"
#: A FLOOR, not a freeze: the live pin was 83 when #294 landed and only ever grows;
#: ``test_iter264`` owns the exact count (re-keyed there each time a row is added).
EXPECTED_LEDGER_ROWS_AFTER: Final[int] = 83

#: Behavior 6. The spec's headline arithmetic: with 20 items of headroom inherited, adds
#: of 1..14 items are legal under the 6-item wall and 15 is the first that is not.
LARGEST_LEGAL_ADD: Final[int] = 14


def _subject_tree() -> ast.Module:
    return ast.parse(SUBJECT_PATH.read_text(encoding="utf-8"), filename=str(SUBJECT_PATH))


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{SUBJECT_PATH.name} no longer defines {name}")


def _module_level_int_names(tree: ast.Module, value: int) -> set[str]:
    """Every module-level name bound to the literal ``value``."""
    names: set[str] = set()
    for node in tree.body:
        targets: list[ast.expr] = []
        bound: ast.expr | None = None
        if isinstance(node, ast.Assign):
            targets, bound = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, bound = [node.target], node.value
        if isinstance(bound, ast.Constant) and bound.value == value:
            names.update(t.id for t in targets if isinstance(t, ast.Name))
    return names


def _headroom_fields(live: int) -> dict[str, int]:
    report = guard.headroom_report(guard._intro(), live)
    return {key: int(value) for key, value in re.findall(r"(\w+)=(\d+)", report)}


def _live_at_headroom(headroom: int) -> int:
    """The injected live count at which the gauge reports exactly ``headroom``.

    Derived from the guard's own seams rather than spelled, so the fixture follows a
    later README floor raise instead of pinning today's numbers; the caller re-reads the
    gauge to prove the derivation before relying on it.
    """
    binding_at = guard.published_floor() + guard.SUITE_ROUNDING_WINDOW + 1
    return binding_at - 1 - headroom


def _subject_test() -> None:
    getattr(subject, SUBJECT_TEST)()


# ===========================================================================
# Behavior 1 -- the bound is the census gauge, and nothing else.
# ===========================================================================
def test_b1_test_b7_compares_headroom_against_the_census_gauge_and_nothing_else() -> None:
    """Behavior 1: exactly one ``Compare`` in ``test_b7`` has ``fields["binding_headroom"]``
    on its left; its right operand is ``census.MIN_BINDING_HEADROOM`` (an ``Attribute`` on
    the name ``census``, itself bound by importing the census module); and no ``Compare``
    in the function names a bare module-level name bound to 20.
    """
    tree = _subject_tree()
    function = _function(tree, SUBJECT_TEST)
    compares = [node for node in ast.walk(function) if isinstance(node, ast.Compare)]
    headroom_compares = [
        node
        for node in compares
        if isinstance(node.left, ast.Subscript)
        and isinstance(node.left.slice, ast.Constant)
        and node.left.slice.value == "binding_headroom"
    ]
    assert len(headroom_compares) == 1, (
        f"expected exactly one Compare on fields['binding_headroom'] in {SUBJECT_TEST}, "
        f"found {len(headroom_compares)}"
    )
    (compare,) = headroom_compares
    assert len(compare.ops) == 1 and isinstance(compare.ops[0], ast.GtE), ast.dump(compare)
    (bound,) = compare.comparators
    assert isinstance(bound, ast.Attribute), ast.dump(bound)
    assert isinstance(bound.value, ast.Name) and bound.value.id == "census", ast.dump(bound)
    assert bound.attr == "MIN_BINDING_HEADROOM", ast.dump(bound)

    census_imports = [
        alias
        for node in tree.body
        if isinstance(node, ast.Import)
        for alias in node.names
        if alias.asname == "census"
    ]
    assert [alias.name for alias in census_imports] == ["tests.test_iter263_behavior"], (
        "`census` must be bound by importing the module that OWNS the wall"
    )
    assert census.MIN_BINDING_HEADROOM == 6

    twenties = _module_level_int_names(tree, RETIRED_BUDGET)
    assert twenties == set(), f"a module-level name is still bound to 20: {sorted(twenties)}"
    bare_names = {
        operand.id
        for node in compares
        for operand in (node.left, *node.comparators)
        if isinstance(operand, ast.Name)
    }
    assert bare_names.isdisjoint({"MIN_BINDING_HEADROOM"}) and RETIRED_NAME not in bare_names
    literal_twenties = [
        node
        for node in compares
        for operand in (node.left, *node.comparators)
        if isinstance(operand, ast.Constant) and operand.value == RETIRED_BUDGET
    ]
    assert literal_twenties == [], "test_b7 still compares against a literal 20"


# ===========================================================================
# Behavior 2 -- the one-shot constant is gone; the note keeps the history.
# ===========================================================================
def test_b2_the_hand_off_constant_is_retired_and_the_note_keeps_the_history() -> None:
    """Behavior 2: the retired token appears in no ``.py`` under ``tests/`` or ``src/``,
    and the ``#: Behavior 7`` comment that replaces it names both 20 and 47 as history and
    points at the permanent wall by name.
    """
    hits = sorted(
        str(path.relative_to(REPO))
        for root in (TESTS_DIR, SRC_DIR)
        for path in root.rglob("*.py")
        if RETIRED_NAME in path.read_text(encoding="utf-8")
    )
    assert hits == [], f"retired constant still referenced in: {hits}"

    lines = SUBJECT_PATH.read_text(encoding="utf-8").splitlines()
    starts = [i for i, line in enumerate(lines) if line.startswith("#: Behavior 7")]
    assert len(starts) == 1, f"expected one `#: Behavior 7` note, found {len(starts)}"
    block: list[str] = []
    for line in lines[starts[0] :]:
        if not line.startswith("#:"):
            break
        block.append(line)
    note = " ".join(block)
    assert 1 <= len(block) <= 3, f"the historical note must be 1-3 lines, got {len(block)}"
    assert str(RETIRED_BUDGET) in note and str(HANDED_ON_AT_ITER312) in note, note
    assert "census.MIN_BINDING_HEADROOM" in note, note
    assert RETIRED_NAME not in note
    following = lines[starts[0] + len(block)]
    assert following.strip() == "", (
        "the note must stand alone -- no `Final[int]` binding may follow it: " + following
    )


def test_b2b_test_b7_keeps_its_name_and_the_module_keeps_its_eleven_items() -> None:
    """Behavior 2 (zero item-id churn): the function NAME survives verbatim, the module
    still defines eleven collected items, and neither the docstring nor the assertion
    message still calls the hand-off "this iteration's whole purpose".
    """
    tree = _subject_tree()
    defined = [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]
    tests_defined = [name for name in defined if name.startswith("test_")]
    assert SUBJECT_TEST in tests_defined
    assert len(tests_defined) == SUBJECT_ITEMS, tests_defined
    assert callable(getattr(subject, SUBJECT_TEST))

    function = _function(tree, SUBJECT_TEST)
    docstring = ast.get_docstring(function) or ""
    assert docstring, f"{SUBJECT_TEST} must keep a docstring"
    assert RETIRED_PHRASE not in docstring.lower(), docstring
    assert "6-item wall" in docstring or "MIN_BINDING_HEADROOM" in docstring, docstring
    source = inspect.getsource(getattr(subject, SUBJECT_TEST))
    assert RETIRED_PHRASE not in source.lower(), source


# ===========================================================================
# Behavior 3 -- the wall is now exactly six, proved on both sides of it.
# ===========================================================================
def test_b3_a_headroom_of_exactly_the_wall_passes_test_b7(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Behavior 3: injecting a live count that leaves exactly ``MIN_BINDING_HEADROOM``
    items of binding headroom (6092 at today's floor) lets ``test_b7`` pass. Before the
    re-anchor every count from 6079 to 6092 failed it.
    """
    at_wall = _live_at_headroom(census.MIN_BINDING_HEADROOM)
    fields = _headroom_fields(at_wall)
    assert fields["binding_headroom"] == census.MIN_BINDING_HEADROOM, fields
    assert fields["live"] == at_wall, fields

    monkeypatch.setattr(guard, "collect_live_test_count", lambda *_a, **_k: at_wall)
    _subject_test()


def test_b3b_one_item_under_the_wall_fails_test_b7_naming_the_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Behavior 3: one more item (6093 at today's floor, headroom 5) makes ``test_b7``
    raise ``AssertionError`` whose message carries the gauge's own report text and the
    wall it enforces -- so the red is actionable, not a bare ``assert``.
    """
    under = _live_at_headroom(census.MIN_BINDING_HEADROOM) + 1
    fields = _headroom_fields(under)
    assert fields["binding_headroom"] == census.MIN_BINDING_HEADROOM - 1, fields
    report = guard.headroom_report(guard._intro(), under)

    monkeypatch.setattr(guard, "collect_live_test_count", lambda *_a, **_k: under)
    with pytest.raises(AssertionError) as excinfo:
        _subject_test()
    message = str(excinfo.value)
    assert report in message, message
    assert str(census.MIN_BINDING_HEADROOM) in message, message
    assert RETIRED_PHRASE not in message.lower(), message


# ===========================================================================
# Behavior 5 -- the record sites, all three, in one commit.
# ===========================================================================
def test_b5_ledger_row_294_is_appended_once_directly_after_293_and_the_pin_moved_past_82() -> None:
    """Behavior 5: ROADMAP.md holds the spec's row verbatim, exactly once, on the line
    directly after ``- #293 ...``; the row fits the ledger bound and cites the ship tag;
    ``EXPECTED_LEDGER_ROWS`` moved past 82 (83 when #294 landed; ``test_iter264`` owns the
    live count); ROADMAP_ARCHIVE.md never mentions #294.
    """
    lines = ROADMAP.read_text(encoding="utf-8").splitlines()
    prior = [i for i, line in enumerate(lines) if line.startswith(PRIOR_ROW_PREFIX)]
    assert len(prior) == 1, f"expected one row #293, found {len(prior)}"
    assert lines[prior[0] + 1] == NEW_ROW, (
        f"the line after #293 is not the spec's row #294:\n{lines[prior[0] + 1]!r}"
    )
    mine = [line for line in lines if line.startswith(NEW_ROW_PREFIX)]
    assert mine == [NEW_ROW], mine
    assert len(NEW_ROW) <= ledger.MAX_LEDGER_ROW_CHARS
    assert NEW_ROW.endswith(f"({SHIP_TAG})")
    assert NEW_ROW in ledger._ledger_rows("\n".join(lines))

    assert ledger.EXPECTED_LEDGER_ROWS >= EXPECTED_LEDGER_ROWS_AFTER
    assert len(ledger._ledger_rows("\n".join(lines))) == ledger.EXPECTED_LEDGER_ROWS

    archive = ARCHIVE.read_text(encoding="utf-8")
    assert "#294" not in archive, "row #294 was not a queued index row; the archive is untouched"


# ===========================================================================
# Behavior 6 -- what the re-anchor makes legal, as the spec states it.
# ===========================================================================
def test_b6_from_twenty_inherited_items_adds_of_one_to_fourteen_are_legal_and_fifteen_is_not() -> None:
    """Behavior 6: the spec's headline claim -- at the inherited 20 items of headroom,
    adding 1..14 collected items keeps the gauge at or above the 6-item wall and 15 is
    the first add that breaches it. Read through the guard's pure gauge with the count
    injected, so this is a property of the wall, not of today's floor.
    """
    inherited = _live_at_headroom(RETIRED_BUDGET)
    assert _headroom_fields(inherited)["binding_headroom"] == RETIRED_BUDGET

    legal = [
        n
        for n in range(1, LARGEST_LEGAL_ADD + 2)
        if _headroom_fields(inherited + n)["binding_headroom"] >= census.MIN_BINDING_HEADROOM
    ]
    assert legal == list(range(1, LARGEST_LEGAL_ADD + 1)), legal
    breach = _headroom_fields(inherited + LARGEST_LEGAL_ADD + 1)["binding_headroom"]
    assert breach == census.MIN_BINDING_HEADROOM - 1, breach
    assert breach < census.MIN_BINDING_HEADROOM
