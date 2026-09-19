"""Black-box behavior tests for foundry iteration 312 (ROADMAP #291) -- the 41 redundant
"this iteration did not bump the version" test definitions retire from ``tests/``, the
duplicate-body ratchet moves DOWN, and the collected-item window the published floor
opens is handed to the next iteration with room to spend.

WHY THIS ITERATION EXISTS, in one paragraph a future reader needs. The README publishes
the suite size as a FLOOR rounded down to a hundred, so the live collected count may sit
anywhere inside a window above it; three consecutive iterations (426, 427, 428 by the
state-dir counter) were reverted because that window had closed to SIX items while
``roles/tester.md`` obliges every iteration to add a new behavior module. One assertion
-- ``assert __version__ == "0.1.1"`` -- was a separately-collected test in 44 modules.
Retiring 41 of those copies is the one increment the wall PAYS for instead of charging:
it needs no README token flip and no floor re-key, and every item it frees is add-budget
for the next iteration.

WHAT THIS MODULE GRADES: Expected Behaviors 1-8 of the iteration spec, in order. It is
deliberately NOT a second spelling of opinions that already ship:

* the equality ``REDUNDANT_TEST_DEFINITIONS == redundant_definition_total(corpus)`` is
  owned by ``tests/test_iter263_behavior.py::test_b5``. This module asserts the property
  that arm cannot see -- the RATCHET DIRECTION, i.e. that the pin moved DOWN from the 38
  this commit inherited -- as an inequality, so it never needs re-keying when the number
  legitimately falls again.
* the ``ROADMAP.md`` char ceiling, the archive-bullet total and the 120-char ledger-row
  bound are owned by ``tests/test_roadmap_size_budget.py``,
  ``tests/test_iter214_behavior.py`` and ``tests/test_iter264_behavior.py``. Re-asserting
  any of them here would be the very duplication this iteration retires.
* the published floor is never SPELLED here. It is read through
  ``tests/test_readme_and_ci_contract.py``, so this module can never become the stale
  carrier a later raise forgets.

THE CENSUS INSTRUMENT IS IMPORTED, NOT RE-WRITTEN. ``tests/test_iter263_behavior.py``
already owns ``code_lines`` / ``body_fingerprint`` / ``normalized_test_bodies``, and the
repo's own ROADMAP #289 records that a roster or a helper spelled twice is a defect. The
one predicate this module does add (``sole_version_freeze``) is a DIFFERENT question --
"is this whole test nothing but the version freeze?" -- and it is proved two-sided on
synthetic source text before it is pointed at the corpus, because an absence census that
silently stops recognizing its subject reports a clean zero forever.

ONE MEASURED SURPRISE, recorded rather than smoothed over: the sole-assertion family has
FOUR members after this commit, not the three the spec names. The fourth,
``tests/test_iter151_behavior.py::test_anchor_version_unchanged``, was never part of the
44-copy family because it reaches the constant through ``from proactive_loop import
__version__`` instead of the two spellings the family used, so no shipped fingerprint
ever grouped it. It is asserted here as a member of the surviving set rather than deleted
or hidden -- this iteration's scope is the 41 named pairs and nothing else.

ISOLATION CONTRACT (honored). Every assertion below is written from this iteration's spec
(``pm.md`` Expected Behaviors 1-8 and its Acceptance Criteria), from the conventions of
the repo's own ``tests/`` tree, and from the product's OBSERVABLE surface obtained by
IMPORTING its public package. **No file under ``src/`` was read, no engineer's or
reviewer's note was opened, no implementation patch and no ``git diff`` was inspected.**
Fully offline and deterministic: every arm is a pure function of tracked text, except the
one arm that runs the shipped collection gauge, which is the same child process the floor
guard already owns. Nothing is written inside the product repo.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Final

import tests.test_iter263_behavior as census
import tests.test_readme_and_ci_contract as guard

REPO: Final[Path] = Path(__file__).resolve().parents[1]
TESTS_DIR: Final[Path] = REPO / "tests"
ROADMAP: Final[Path] = REPO / "ROADMAP.md"
ARCHIVE: Final[Path] = REPO / "ROADMAP_ARCHIVE.md"

#: Behavior 1. The 41 ``(module, function)`` pairs this iteration retires -- exactly ONE
#: module-level definition per module. Transcribed from the spec's deletion set and then
#: re-derived: every module named here must still exist (Behavior 2), which is what stops
#: a typo in this table from passing as a successful deletion.
VICTIMS: Final[dict[str, str]] = {
    "test_iter17_behavior.py": "test_behavior_11_no_version_bump",
    "test_iter20_behavior.py": "test_b11_no_version_bump",
    "test_iter21_behavior.py": "test_behavior_17_version_unchanged",
    "test_iter22_behavior.py": "test_no_version_bump_additive_flag",
    "test_iter23_behavior.py": "test_no_version_bump_additive_error_handling",
    "test_iter25_behavior.py": "test_b7_version_is_unchanged_additive_flag_no_bump",
    "test_iter26_behavior.py": "test_behavior_17_version_unchanged",
    "test_iter29_behavior.py": "test_behavior_16_version_unchanged",
    "test_iter32_behavior.py": "test_behavior7_no_version_bump_additive_provider",
    "test_iter33_behavior.py": "test_version_unchanged_additive_tool",
    "test_iter34_behavior.py": "test_version_unchanged_additive_extension",
    "test_iter35_behavior.py": "test_eb8_version_unchanged_test_only_iteration",
    "test_iter39_behavior.py": "test_b11_version_unchanged",
    "test_iter41_behavior.py": "test_behavior_07_version_pinned",
    "test_iter45_behavior.py": "test_version_unchanged_additive_tool",
    "test_iter48_behavior.py": "test_b13_version_unchanged",
    "test_iter49_behavior.py": "test_behavior7_no_version_bump_additive_provider",
    "test_iter51_behavior.py": "test_version_is_unchanged_no_bump",
    "test_iter54_behavior.py": "test_version_unchanged",
    "test_iter56_behavior.py": "test_version_unchanged_additive_extension",
    "test_iter57_behavior.py": "test_b10_version_unchanged",
    "test_iter60_behavior.py": "test_b6_version_stays_pinned",
    "test_iter61_behavior.py": "test_version_unchanged",
    "test_iter64_behavior.py": "test_behavior12_version_unchanged",
    "test_iter65_behavior.py": "test_behavior7_no_version_bump_additive_provider",
    "test_iter66_behavior.py": "test_no_version_bump_additive_tool",
    "test_iter67_behavior.py": "test_eb6_no_version_bump",
    "test_iter68_behavior.py": "test_b6_version_is_not_bumped_observability_only",
    "test_iter69_behavior.py": "test_eb12_version_is_not_bumped",
    "test_iter71_behavior.py": "test_eb8_module_version_is_not_bumped",
    "test_iter72_behavior.py": "test_no_version_bump_additive_widening",
    "test_iter75_behavior.py": "test_b12_version_unchanged",
    "test_iter76_behavior.py": "test_version_unchanged",
    "test_iter77_behavior.py": "test_b10_version_unchanged",
    "test_iter79_behavior.py": "test_b07_version_constant_unchanged",
    "test_iter92_behavior.py": "test_b7_version_unchanged",
    "test_iter93_behavior.py": "test_b11_version_unchanged",
    "test_iter95_behavior.py": "test_b7c_version_unchanged",
    "test_iter96_behavior.py": "test_behavior_supplementary_version_unchanged",
    "test_iter98_behavior.py": "test_b08_version_constant_unchanged",
    "test_iter99_behavior.py": "test_b11_version_unchanged",
}

#: Behavior 1 anti-vacuity: the roster is the size the spec claims. A shrunken table
#: would let deleted-but-unlisted work pass, and an empty one would pass trivially.
VICTIM_COUNT: Final[int] = 41

#: Behavior 4. The three copies deliberately KEPT, each at a named address. The first is
#: a canonical keeper pinned in ``census.FAMILIES``; the other two live in modules whose
#: exact collected counts are pinned in ``census.REMAINDERS``. Touching any of the three
#: reds ``tests/test_iter263_behavior.py`` itself.
KEEPERS: Final[tuple[tuple[str, str], ...]] = (
    ("test_iter81_behavior.py", "test_b8_version_frozen"),
    ("test_iter83_behavior.py", "test_b8_version_frozen"),
    ("test_iter87_behavior.py", "test_b7_version_frozen"),
)

#: Behavior 3. The measured fourth member of the sole-assertion family -- see the module
#: docstring for why it was never one of the 44 and is not in scope to delete.
OUT_OF_FAMILY_SURVIVOR: Final[tuple[str, str]] = (
    "test_iter151_behavior.py",
    "test_anchor_version_unchanged",
)

#: The frozen version string the surviving contract asserts.
FROZEN_VERSION: Final[str] = "0.1.1"

#: Behavior 2. The measured floor on what a touched module still collects. The smallest
#: survivor is ``tests/test_iter51_behavior.py`` at exactly this many items, so a module
#: emptied by a later over-eager deletion pass fails here rather than silently vanishing.
MIN_SURVIVING_COLLECTED: Final[int] = 4

#: Behavior 5. The value ``census.REDUNDANT_TEST_DEFINITIONS`` carried BEFORE this
#: commit. The ratchet may only ever move DOWN, so this is asserted as a strict upper
#: bound and never as an equality: a later iteration that pays more duplication down
#: must not have to re-key this module, and a RISE (a re-added byte-identical collected
#: test) must fail here as well as there.
RATCHET_BEFORE: Final[int] = 38

#: Behavior 7. The collected-item room this iteration hands to the next one. The spec
#: spends at most 25 of the 47 items the deletions bought and requires at least 20 to
#: survive the new module; ``census.MIN_BINDING_HEADROOM`` is the hard wall at 6, so
#: this is the deliberately stricter budget claim, not a duplicate of it.
MIN_BINDING_HEADROOM_HANDED_ON: Final[int] = 20

#: Behavior 8. The Done-ledger row this commit adds and the tag it must cite -- the
#: repo's own counter (git's newest subject was ``foundry iter 311``), never the state
#: dir's. The vocabulary is ``foundry``; a ``factory`` slip reverted a whole iteration.
LEDGER_ROW: Final[str] = "291"
SHIP_TAG: Final[str] = "foundry iter 312"

#: Behavior 8. The measured before -> after figures the ledger narration must name, so
#: the record cannot become a vague sentence that no reader can check.
LEDGER_FIGURES: Final[tuple[str, ...]] = ("6092", "6051", "38", "21")

_INDEX_ROW_RE: Final[re.Pattern[str]] = re.compile(rf"(?m)^\|\s*{LEDGER_ROW}\s*\|")


# ===========================================================================
# Helpers -- pure functions over source TEXT, so every arm below is offline.
# ===========================================================================
def _module_text(name: str) -> str:
    return (TESTS_DIR / name).read_text(encoding="utf-8")


def collected_names(source_text: str) -> tuple[str, ...]:
    """The module-level ``test_``-prefixed function names one module collects."""
    return tuple(census.normalized_test_bodies(source_text))


def _is_version_reference(node: ast.expr) -> bool:
    """``__version__`` or ``<anything>.__version__``, the two spellings the family used."""
    if isinstance(node, ast.Name):
        return node.id == "__version__"
    if isinstance(node, ast.Attribute):
        return node.attr == "__version__"
    return False


def sole_version_freeze(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Is this whole test nothing but ``assert <...>__version__ == "0.1.1"``?

    Docstring and import statements are ignored, because the family's three fingerprints
    differed only in whether the constant was imported inside the body. Anything else in
    the body -- a registry count, a CLI invocation, a second assertion -- makes the test
    a compound test that this iteration deliberately leaves alone.
    """
    body = list(node.body)
    if body:
        head = body[0]
        if (
            isinstance(head, ast.Expr)
            and isinstance(head.value, ast.Constant)
            and isinstance(head.value.value, str)
        ):
            body = body[1:]
    statements = [
        statement
        for statement in body
        if not isinstance(statement, ast.Import | ast.ImportFrom)
    ]
    if len(statements) != 1 or not isinstance(statements[0], ast.Assert):
        return False
    test = statements[0].test
    if not isinstance(test, ast.Compare) or len(test.ops) != 1:
        return False
    if not isinstance(test.ops[0], ast.Eq):
        return False
    right = test.comparators[0]
    return (
        _is_version_reference(test.left)
        and isinstance(right, ast.Constant)
        and right.value == FROZEN_VERSION
    )


def sole_version_freeze_addresses(sources: dict[str, str]) -> tuple[str, ...]:
    """``{label: source text}`` -> sorted ``'label::name'`` for every sole-freeze test.

    The caller owns reading the tree, so the synthetic proof arm and the corpus arm walk
    the identical code path.
    """
    found: list[str] = []
    for label in sorted(sources):
        for node in ast.parse(sources[label]).body:
            if (
                isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
                and node.name.startswith("test_")
                and sole_version_freeze(node)
            ):
                found.append(f"{label}::{node.name}")
    return tuple(found)


def _function(module_name: str, function_name: str) -> ast.FunctionDef:
    for node in ast.parse(_module_text(module_name)).body:
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            return node
    raise AssertionError(f"{module_name} has no module-level def {function_name}")


def _ledger_rows() -> list[str]:
    return [
        line
        for line in ROADMAP.read_text(encoding="utf-8").splitlines()
        if line.startswith(f"- #{LEDGER_ROW} ")
    ]


# ===========================================================================
# Behavior 1 -- the 41 named definitions are gone.
# ===========================================================================
def test_b1_the_forty_one_version_freeze_duplicates_are_absent() -> None:
    """Behavior 1: no module-level ``test_``-prefixed function of the named name remains
    in any of the 41 modules. Resolved by AST rather than by substring, so a name that
    survives only inside a docstring, a comment or a censused string literal elsewhere in
    the tree is not mistaken for a live collected test.
    """
    assert len(VICTIMS) == VICTIM_COUNT, (
        f"the deletion roster must hold {VICTIM_COUNT} pairs; it holds {len(VICTIMS)}"
    )
    survivors: list[str] = []
    reached = 0
    for module_name, function_name in sorted(VICTIMS.items()):
        names = collected_names(_module_text(module_name))
        assert names, f"{module_name} parsed to ZERO collected tests -- census is broken"
        reached += 1
        if function_name in names:
            survivors.append(f"{module_name}::{function_name}")
    assert reached == VICTIM_COUNT, f"only reached {reached} of {VICTIM_COUNT} modules"
    assert survivors == [], (
        "these duplicate version-freeze definitions were supposed to retire in this "
        f"commit and are still collected: {survivors}"
    )


# ===========================================================================
# Behavior 2 -- every touched module survives and none empties.
# ===========================================================================
def test_b2_every_touched_module_still_exists_and_still_collects() -> None:
    """Behavior 2: all 41 files are still present and each still collects at least the
    measured minimum. A deletion pass that emptied a module would turn a one-function
    edit into a file removal -- a different, much larger change than the spec sanctions.
    """
    thin: list[str] = []
    for module_name in sorted(VICTIMS):
        path = TESTS_DIR / module_name
        assert path.is_file(), f"{module_name} was DELETED; the spec deletes functions"
        count = len(collected_names(path.read_text(encoding="utf-8")))
        if count < MIN_SURVIVING_COLLECTED:
            thin.append(f"{module_name} collects {count}")
    assert thin == [], (
        f"every touched module must still collect >= {MIN_SURVIVING_COLLECTED} tests: "
        f"{thin}"
    )


# ===========================================================================
# Behavior 3 -- the family is down to its survivors, corpus-wide.
# ===========================================================================
def test_b3_the_sole_assertion_version_freeze_family_is_down_to_its_survivors() -> None:
    """Behavior 3: across EVERY module pytest collects from, the tests whose entire body
    is the version freeze are exactly the three named keepers plus the one out-of-family
    survivor. This is the durable form of "41 collected items were removed": it reds if
    any future iteration re-adds a bare version-freeze test anywhere in the corpus.
    """
    corpus = census._corpus()
    assert len(corpus) >= 100, (
        f"corpus scan reached only {len(corpus)} modules -- the glob is fail-open"
    )
    assert Path(__file__).name in corpus, (
        "the census cannot see its own module, so its result proves nothing"
    )
    expected = tuple(
        sorted(
            f"{module}::{function}"
            for module, function in (*KEEPERS, OUT_OF_FAMILY_SURVIVOR)
        )
    )
    assert sole_version_freeze_addresses(corpus) == expected, (
        "the sole-assertion version-freeze family must be exactly these addresses; a "
        "new member is a re-added duplicate and a missing one is a deleted keeper"
    )


def test_b3b_the_sole_freeze_predicate_is_two_sided_on_synthetic_source() -> None:
    """Behavior 3, soundness. The predicate is proved to DETECT and to DISCRIMINATE on
    source text built here, so a future edit that quietly stops recognizing the subject
    fails this arm instead of reporting a clean corpus forever.
    """
    detected = (
        'def test_a() -> None:\n    assert __version__ == "0.1.1"\n\n'
        'def test_b() -> None:\n    """Doc."""\n    import proactive_loop\n'
        '    assert proactive_loop.__version__ == "0.1.1", "message ignored"\n'
    )
    assert sole_version_freeze_addresses({"m.py": detected}) == (
        "m.py::test_a",
        "m.py::test_b",
    ), "the predicate no longer recognizes either spelling of the freeze"
    discriminated = (
        'def test_c() -> None:\n    assert __version__ == "0.2.0"\n\n'
        'def test_d() -> None:\n    assert __version__ == "0.1.1"\n'
        '    assert other() == 1\n\n'
        'def test_e() -> None:\n    assert len(all_collectors()) == 17\n\n'
        'def helper() -> None:\n    assert __version__ == "0.1.1"\n'
    )
    assert sole_version_freeze_addresses({"m.py": discriminated}) == (), (
        "a different version, a compound body and a non-collected helper must all be "
        "outside the family -- the predicate has become a substring match"
    )


# ===========================================================================
# Behavior 4 -- the surviving contract still holds, at three named addresses.
# ===========================================================================
def test_b4_the_version_freeze_contract_survives_at_three_named_addresses() -> None:
    """Behavior 4: each keeper still exists as a collected test, still asserts the frozen
    version, and carries no decorator (an undecorated def is one collected item, which is
    what makes the item arithmetic of this iteration checkable). The product's public
    package is then asked directly, so the contract is graded against the live constant
    rather than against three copies of a claim about it.
    """
    import proactive_loop

    for module_name, function_name in KEEPERS:
        node = _function(module_name, function_name)
        assert node.decorator_list == [], (
            f"{module_name}::{function_name} gained a decorator, so its collected-item "
            "count is no longer one"
        )
        assert sole_version_freeze(node), (
            f"{module_name}::{function_name} no longer asserts only the version freeze"
        )
        fingerprint = census.body_fingerprint(
            census.code_lines(_module_text(module_name)), node
        )
        assert FROZEN_VERSION in fingerprint, (
            f"{module_name}::{function_name} lost the frozen version string"
        )
    assert proactive_loop.__version__ == FROZEN_VERSION, (
        "a test-corpus-only iteration must not move the package version; got "
        f"{proactive_loop.__version__!r}"
    )


# ===========================================================================
# Behavior 5 -- the ratchet moved DOWN and the instrument was not widened.
# ===========================================================================
def test_b5_the_duplicate_body_ratchet_moved_down() -> None:
    """Behavior 5, direction. The pin is strictly below the value this commit inherited.
    Asserted as an inequality on purpose: the equality against the freshly measured
    corpus total is owned by ``test_iter263::test_b5``, and a second copy of that number
    here would be the duplication defect this iteration exists to retire.
    """
    assert census.REDUNDANT_TEST_DEFINITIONS < RATCHET_BEFORE, (
        "the duplicate-body ratchet must move DOWN in this commit: it was "
        f"{RATCHET_BEFORE} and is {census.REDUNDANT_TEST_DEFINITIONS}. A rise records "
        "that a byte-identical collected test was re-added -- delete it instead."
    )
    assert census.REDUNDANT_TEST_DEFINITIONS >= 0


def test_b5b_the_census_fingerprint_was_not_widened() -> None:
    """Behavior 5, instrument. ``body_fingerprint`` still DISTINGUISHES two bodies whose
    only difference is the assertion message, which is what keeps the ratchet honest: a
    message-blind fingerprint would report far more redundancy than the pin allows and
    could only be landed by RAISING the ratchet, the one move it forbids.
    """
    source = (
        'def test_a() -> None:\n    assert __version__ == "0.1.1", "one message"\n\n'
        'def test_b() -> None:\n    assert __version__ == "0.1.1", "another message"\n\n'
        'def test_c() -> None:\n    assert __version__ == "0.1.1", "one message"\n'
    )
    bodies = census.normalized_test_bodies(source)
    assert bodies["test_a"] != bodies["test_b"], (
        "body_fingerprint has been widened to ignore the assertion message; the ratchet "
        "constant cannot absorb that in this commit"
    )
    assert bodies["test_a"] == bodies["test_c"], (
        "two byte-identical bodies must still group, or the census detects nothing"
    )
    assert census.duplicate_body_groups({"m.py": source}) == {
        bodies["test_a"]: ("m.py::test_a", "m.py::test_c")
    }
    assert census.redundant_definition_total({"m.py": source}) == 1


# ===========================================================================
# Behavior 6 -- the pinned tables of the sibling census are untouched.
# ===========================================================================
def test_b6_this_iteration_touches_no_module_the_sibling_census_pins() -> None:
    """Behavior 6: the 41 victim modules are DISJOINT from every module named in
    ``census.DELETED``, ``census.REMAINDERS`` and the keys of ``census.FAMILIES``, and
    the keepers are drawn from those very tables. That is the structural reason the three
    tables could be left byte-identical by this change.
    """
    pinned = (
        set(census.DELETED)
        | set(census.REMAINDERS)
        | {module for module, _ in census.FAMILIES}
    )
    assert len(pinned) >= 8, f"the sibling census pins only {len(pinned)} modules"
    overlap = sorted(set(VICTIMS) & pinned)
    assert overlap == [], (
        "this iteration must not edit a module whose collected count or canonical copy "
        f"the sibling census pins exactly: {overlap}"
    )
    assert KEEPERS[0] in census.FAMILIES, (
        f"{KEEPERS[0]} must still be a canonical keeper in the sibling census"
    )
    for module_name, _ in KEEPERS[1:]:
        assert module_name in census.REMAINDERS, (
            f"{module_name} must still carry a pinned remainder in the sibling census"
        )


# ===========================================================================
# Behavior 7 -- the floor is unmoved and the reopened room is handed on.
# ===========================================================================
def test_b7_the_published_floor_is_unmoved_and_room_is_handed_to_the_next_iteration(
) -> None:
    """Behavior 7: the gauge reports the README's own floor unchanged and still TRUE, the
    live count inside the window that floor opens, and at least the budget this iteration
    promised the next one. The floor is read through the guard, never spelled here.
    """
    floor = guard.published_floor()
    live = guard.collect_live_test_count()
    report = guard.headroom_report(guard._intro(), live)
    fields = {key: int(value) for key, value in re.findall(r"(\w+)=(\d+)", report)}
    assert fields["published"] == floor, report
    assert fields["floor"] == floor, report
    assert fields["live"] == live, report
    assert floor <= live <= floor + guard.SUITE_ROUNDING_WINDOW, (
        f"the live count left the window the published floor opens: {report}"
    )
    assert fields["binding_headroom"] >= MIN_BINDING_HEADROOM_HANDED_ON, (
        "this iteration's whole purpose was to hand the next one room to add a behavior "
        f"module in; the gauge reports only {fields['binding_headroom']}: {report}"
    )
    assert guard.suite_size_problems(guard._intro(), live) == [], (
        "the README's published floor is no longer true and fresh after the deletions"
    )


# ===========================================================================
# Behavior 8 -- the iteration is recorded, once, in the ledger.
# ===========================================================================
def test_b8_exactly_one_ledger_row_records_the_ship_with_its_measured_numbers() -> None:
    """Behavior 8: ``ROADMAP.md`` gains exactly ONE ``- #291 ...`` Done-ledger row, it
    cites this commit's tag in the repo's ``foundry`` vocabulary, and its narration names
    the measured before -> after figures rather than describing the change vaguely.
    """
    rows = _ledger_rows()
    assert len(rows) == 1, f"expected exactly one ledger row for #{LEDGER_ROW}: {rows}"
    row = rows[0]
    assert row.endswith(f"({SHIP_TAG})"), (
        f"the row must end with the shipping tag in the foundry vocabulary: {row!r}"
    )
    missing = [figure for figure in LEDGER_FIGURES if figure not in row]
    assert missing == [], (
        f"the ledger narration must name the measured figures {missing}: {row!r}"
    )


def test_b8b_the_row_is_recorded_in_one_document_and_never_entered_the_index() -> None:
    """Behavior 8, conservation. A row created and shipped inside one iteration never
    entered the open index, so it must appear neither as an index table row in
    ``ROADMAP.md`` nor as a bullet in ``ROADMAP_ARCHIVE.md`` -- a row recorded in both
    documents reds the ledger-conservation guard.
    """
    roadmap = ROADMAP.read_text(encoding="utf-8")
    archive = ARCHIVE.read_text(encoding="utf-8")
    assert _INDEX_ROW_RE.search(roadmap) is None, (
        f"row #{LEDGER_ROW} was shipped in the iteration that created it, so it must "
        "never appear as an open-index table row"
    )
    assert f"#{LEDGER_ROW}" not in archive, (
        f"row #{LEDGER_ROW} appears in the archive as well as the ledger, which the "
        "conservation guard forbids"
    )
    assert SHIP_TAG not in archive, (
        f"{SHIP_TAG} must be recorded in the ledger only, not in the archive"
    )
