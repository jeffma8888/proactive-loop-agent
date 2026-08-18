"""Black-box acceptance tests for state iter-158 (ships as ``factory iter 164``).

FEATURE UNDER TEST
A two-sided char-size budget guard for ``ROADMAP.md`` -- a hard ceiling of 40,000
chars plus an anti-vacuity floor of 10,000 -- shipped together with the
retirement of four settled index rows into ``ROADMAP_ARCHIVE.md``.

WHY THESE ASSERTIONS ARE WRITTEN AGAINST THE SPEC AND NOT THE SHIPPED MODULE
This file was authored under the tester isolation contract: the spec, the two
tracked Markdown documents and the public surface of the guard, never the
product source. So every threshold below is spelled as the SPEC's own literal
(``40000``, ``10000``, the ten retired row numbers, the pinned row ``121``)
rather than imported as a symbol. Importing the guard's constant and asserting
it equals itself is a tautology; a second, independent spelling of the operator's
number is the only way a wrong constant is caught by a test. State iter-162
extended the retirement census from 4 rows to 9 and added behavior 8 below, which
asserts the two independent spellings AGREE -- so the second spelling is now a
cross-check rather than a copy that can silently drift.

WHY THE CENSUS REGEXES ARE RE-IMPLEMENTED HERE
Behaviors 6 and 7 are a PAIR property -- absent from the live index AND present
in the archive -- over two files with two different shapes (``| N |`` table rows
vs ``- **#N --`` bullets). Reusing the shipped helpers would inherit any quirk in
them, including a wrong-shaped probe that fails OPEN and reads as "safe to
delete". The row censuses are therefore written from scratch from the documented
shapes and the shipped helpers are additionally cross-checked for agreement.

Offline, deterministic, no network, no clock, no subprocess, no writes: pure
length and string arithmetic over two GIT-TRACKED documents plus the guard's
importable pure function. Nothing here reads gitignored or per-machine state, so
every precondition holds in a throwaway fresh clone.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

from tests.test_roadmap_size_budget import (
    RETIRED_ROWS,
    ROADMAP_CHAR_FLOOR,
    ROADMAP_CHAR_LIMIT,
    check_char_budget,
    count_archive_bullets,
    count_index_rows,
    settled_rows_needing_retirement,
)

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[1]
ROADMAP_PATH: Final[Path] = REPO_ROOT / "ROADMAP.md"
ARCHIVE_PATH: Final[Path] = REPO_ROOT / "ROADMAP_ARCHIVE.md"
GUARD_MODULE_PATH: Final[Path] = REPO_ROOT / "tests" / "test_roadmap_size_budget.py"

#: The operator's stall threshold, spelled independently of the guard module.
SPEC_LIMIT: Final[int] = 40000

#: The spec's anti-vacuity floor, spelled independently of the guard module.
SPEC_FLOOR: Final[int] = 10000

#: Every retired row: absent from the index, present in the archive. 4 retired by
#: state iter-158 (this file's own iteration) and 5 more by state iter-162, which
#: installed the retire-on-ship brake. Spelled independently of the guard module's
#: ``RETIRED_ROWS`` on purpose -- see
#: :func:`test_b8_the_two_retirement_censuses_agree`.
SPEC_RETIRED_ROWS: Final[tuple[str, ...]] = (
    "143",
    "146",
    "155",
    "195",
    "138",
    "197",
    "198",
    "199",
    "200",
    "129",
)

#: The pinned counter-example: archived AND deliberately retained in the index.
SPEC_PINNED_ROW: Final[str] = "121"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _live_index_rows(row: str) -> int:
    """Count ``ROADMAP.md`` index rows for ``row`` -- table shape, line-anchored."""
    text = _read(ROADMAP_PATH)
    return len(re.findall(rf"(?m)^\|\s*{re.escape(row)}\s*\|", text))


def _archive_bullets(row: str) -> int:
    """Count ``ROADMAP_ARCHIVE.md`` entries for ``row`` -- bullet shape, line-anchored."""
    text = _read(ARCHIVE_PATH)
    return len(re.findall(rf"(?m)^- \*\*#{re.escape(row)} --", text))


# --------------------------------------------------------------------------- #
# Behavior 1 -- pure importable function over TEXT, fired two-sided on synthetic
# input. A guard that has never been seen to fire is indistinguishable from
# `assert True`, so both directions are asserted and the live file is never the
# instrument used to test the instrument.
# --------------------------------------------------------------------------- #


def test_b1_budget_reports_failure_one_char_over_the_limit() -> None:
    verdict = check_char_budget("x" * (SPEC_LIMIT + 1))
    assert verdict.ok is False, (
        f"a {SPEC_LIMIT + 1}-char document must breach the {SPEC_LIMIT}-char "
        f"budget; got ok={verdict.ok!r} message={verdict.message!r}"
    )
    assert verdict.chars == SPEC_LIMIT + 1


def test_b1_budget_reports_ok_one_char_under_the_limit() -> None:
    verdict = check_char_budget("x" * (SPEC_LIMIT - 1))
    assert verdict.ok is True, (
        f"a {SPEC_LIMIT - 1}-char document is inside the budget; "
        f"got ok={verdict.ok!r} message={verdict.message!r}"
    )
    assert verdict.chars == SPEC_LIMIT - 1


def test_b1_budget_is_pure_over_text_and_ignores_the_live_file() -> None:
    """The verdict is a function of the argument only, not of the tracked file."""
    live_chars = len(_read(ROADMAP_PATH))
    synthetic = "y" * (SPEC_LIMIT + 500)
    verdict = check_char_budget(synthetic)
    assert verdict.chars == len(synthetic) != live_chars
    assert verdict.ok is False


def test_b1_budget_measures_chars_not_bytes() -> None:
    """A char budget measured in BYTES drifts toward a false green near the ceiling."""
    text = "\u00e9" * SPEC_LIMIT  # LIMIT chars, 2x that many UTF-8 bytes
    assert len(text.encode("utf-8")) > SPEC_LIMIT
    verdict = check_char_budget(text)
    assert verdict.chars == SPEC_LIMIT
    assert verdict.ok is True, (
        "a document of exactly LIMIT multi-byte chars is inside a CHAR budget; "
        f"got {verdict.message!r}"
    )


# --------------------------------------------------------------------------- #
# Behavior 2 -- the limit is the operator's LITERAL, never derived from the live
# file. A derived ceiling re-authorises whatever the file already grew to.
# --------------------------------------------------------------------------- #


def test_b2_limit_equals_the_operator_number() -> None:
    assert ROADMAP_CHAR_LIMIT == SPEC_LIMIT


def test_b2_floor_equals_the_spec_number() -> None:
    assert ROADMAP_CHAR_FLOOR == SPEC_FLOOR


def test_b2_limit_is_assigned_exactly_once_as_a_bare_literal() -> None:
    """A value comparison cannot tell `40_000` from `len(ROADMAP.read_text()) + n`."""
    source = _read(GUARD_MODULE_PATH)
    assignments = re.findall(r"(?m)^ROADMAP_CHAR_LIMIT[^=\n]*=\s*(.+)$", source)
    assert len(assignments) == 1, (
        f"expected exactly one module-level ROADMAP_CHAR_LIMIT assignment, "
        f"found {len(assignments)}: {assignments!r}"
    )
    rhs = assignments[0].strip()
    assert re.fullmatch(r"40_?000", rhs), (
        f"the limit must be a bare literal, not an expression; got {rhs!r}"
    )


def test_b2_limit_is_not_computed_from_the_budgeted_file() -> None:
    source = _read(GUARD_MODULE_PATH)
    for forbidden in ("ROADMAP_CHAR_LIMIT: Final[int] = len", "ROADMAP_CHAR_LIMIT = len"):
        assert forbidden not in source, f"derived, ratcheting limit: {forbidden!r}"


# --------------------------------------------------------------------------- #
# Behavior 3 -- the live file passes the ceiling.
# --------------------------------------------------------------------------- #


def test_b3_live_roadmap_is_within_the_char_ceiling() -> None:
    chars = len(_read(ROADMAP_PATH))
    assert chars <= SPEC_LIMIT, (
        f"ROADMAP.md is {chars} chars, over the {SPEC_LIMIT}-char budget by "
        f"{chars - SPEC_LIMIT}; retire settled rows into ROADMAP_ARCHIVE.md"
    )


def test_b3_live_roadmap_verdict_is_ok_through_the_public_checker() -> None:
    verdict = check_char_budget(_read(ROADMAP_PATH))
    assert verdict.ok is True, verdict.message


# --------------------------------------------------------------------------- #
# Behavior 4 -- anti-vacuity floor, two-sided. A ceiling-only assertion passes
# on a 0-byte or half-written file, which is the costliest failure mode.
# --------------------------------------------------------------------------- #


def test_b4_live_roadmap_clears_the_anti_vacuity_floor() -> None:
    chars = len(_read(ROADMAP_PATH))
    assert chars >= SPEC_FLOOR, (
        f"ROADMAP.md is only {chars} chars, below the {SPEC_FLOOR}-char floor: "
        "the file looks truncated or half-written"
    )


def test_b4_floor_fires_on_an_empty_document() -> None:
    verdict = check_char_budget("")
    assert verdict.ok is False, "an empty ROADMAP.md must be BROKEN, not comfortably small"
    assert verdict.chars == 0


def test_b4_floor_fires_one_char_under_the_floor() -> None:
    verdict = check_char_budget("z" * (SPEC_FLOOR - 1))
    assert verdict.ok is False
    assert verdict.chars == SPEC_FLOOR - 1


def test_b4_floor_passes_one_char_over_the_floor() -> None:
    verdict = check_char_budget("z" * (SPEC_FLOOR + 1))
    assert verdict.ok is True, verdict.message


# --------------------------------------------------------------------------- #
# Behavior 5 -- the breach message is actionable: file, measured chars, limit,
# headroom.
# --------------------------------------------------------------------------- #


def test_b5_breach_message_names_file_count_limit_and_headroom() -> None:
    over_by = 137
    chars = SPEC_LIMIT + over_by
    verdict = check_char_budget("x" * chars)
    message = verdict.message
    assert verdict.ok is False
    assert "ROADMAP.md" in message, message
    assert str(chars) in message, f"measured char count {chars} missing from {message!r}"
    assert str(SPEC_LIMIT) in message, f"limit {SPEC_LIMIT} missing from {message!r}"
    assert str(-over_by) in message, f"headroom {-over_by} missing from {message!r}"


def test_b5_floor_message_is_actionable_too() -> None:
    chars = 42
    verdict = check_char_budget("x" * chars)
    message = verdict.message
    assert verdict.ok is False
    assert "ROADMAP.md" in message, message
    assert str(chars) in message, message
    assert str(SPEC_FLOOR) in message, message


def test_b5_message_is_non_empty_in_the_passing_case() -> None:
    """A guard whose green path prints nothing cannot be told from a dead one."""
    verdict = check_char_budget("x" * (SPEC_LIMIT - 10))
    assert verdict.ok is True
    assert "ROADMAP.md" in verdict.message
    assert str(verdict.chars) in verdict.message


# --------------------------------------------------------------------------- #
# Behavior 6 -- the 4 retired rows are retired AND preserved (pair property).
# --------------------------------------------------------------------------- #


def test_b6_retired_rows_are_absent_from_the_live_index() -> None:
    still_present = {row: _live_index_rows(row) for row in SPEC_RETIRED_ROWS}
    assert all(count == 0 for count in still_present.values()), (
        f"retired rows must hold no live `| N |` index row: {still_present!r}"
    )


def test_b6_retired_rows_are_present_in_the_archive() -> None:
    archived = {row: _archive_bullets(row) for row in SPEC_RETIRED_ROWS}
    assert all(count >= 1 for count in archived.values()), (
        "every retired row must survive as a `- **#N --` archive bullet "
        f"(archive first, then drop): {archived!r}"
    )


def test_b6_shipped_census_helpers_agree_with_an_independent_probe() -> None:
    roadmap = _read(ROADMAP_PATH)
    archive = _read(ARCHIVE_PATH)
    for row in (*SPEC_RETIRED_ROWS, SPEC_PINNED_ROW):
        assert count_index_rows(roadmap, row) == _live_index_rows(row), row
        assert count_archive_bullets(archive, row) == _archive_bullets(row), row


def test_b6_archive_bullets_are_not_table_rows() -> None:
    """The archive's own shape: a bullet that parsed as a table row would red the build."""
    archive = _read(ARCHIVE_PATH)
    for row in SPEC_RETIRED_ROWS:
        assert len(re.findall(rf"(?m)^\|\s*{row}\s*\|", archive)) == 0, row


# --------------------------------------------------------------------------- #
# Behavior 7 -- archive presence is NOT sufficient for retirement; row #121 is
# the pinned counter-example (archived AND retained in the live index).
# --------------------------------------------------------------------------- #


def test_b7_pinned_row_121_is_archived() -> None:
    assert _archive_bullets(SPEC_PINNED_ROW) >= 1


def test_b7_pinned_row_121_is_still_exactly_one_live_index_row() -> None:
    count = _live_index_rows(SPEC_PINNED_ROW)
    assert count == 1, (
        f"row #{SPEC_PINNED_ROW} is test-pinned to the live index "
        f"(test_iter115_behavior.py requires exactly one); found {count}"
    )


def test_b7_archived_and_retained_sets_are_disjoint_by_construction() -> None:
    """The asymmetry itself: #121 is archived like the retired rows, yet retained."""
    assert SPEC_PINNED_ROW not in SPEC_RETIRED_ROWS
    assert _archive_bullets(SPEC_PINNED_ROW) >= 1
    assert _live_index_rows(SPEC_PINNED_ROW) == 1
    for row in SPEC_RETIRED_ROWS:
        assert _archive_bullets(row) >= 1
        assert _live_index_rows(row) == 0


# --------------------------------------------------------------------------- #
# Behavior 8 (state iter-162) -- the two retirement censuses AGREE, so extending
# one alone is a red build rather than a silent divergence.
# --------------------------------------------------------------------------- #


def test_b8_the_two_retirement_censuses_agree() -> None:
    """The guard module's ``RETIRED_ROWS`` and this file's ``SPEC_RETIRED_ROWS``
    are two independent spellings of one fact, and a second spelling only buys
    anything while something compares them.

    The comparison lives HERE rather than in the guard module because the import
    edge only runs one way: this file already imports from the guard, so the
    reverse edge would be a circular import.
    """
    assert set(RETIRED_ROWS) == set(SPEC_RETIRED_ROWS), (
        "the retirement censuses diverged -- extend BOTH in the same commit: "
        f"guard {sorted(RETIRED_ROWS)!r} vs spec {sorted(SPEC_RETIRED_ROWS)!r}"
    )
    assert len(set(SPEC_RETIRED_ROWS)) == len(SPEC_RETIRED_ROWS) == 10
    assert len(set(RETIRED_ROWS)) == len(RETIRED_ROWS)


def test_b8_the_retire_on_ship_brake_reports_a_clean_live_index() -> None:
    """The brake's live property, re-asserted from the spec side.

    The planted row spells ``**SHIPPED`` as the SPEC's own literal instead of
    importing ``SETTLED_STATUS_PREFIXES``, per this file's isolation contract, and
    it is fired FIRST so the live assertion below cannot be satisfied by a parser
    that finds nothing.
    """
    planted = (
        "| 400 | a settled row left parked | CLI | High | Low | scout | "
        "**SHIPPED iter 200** (factory iter 206). |\n"
    )
    assert settled_rows_needing_retirement(planted) == ("400",), (
        "the brake must fire on a settled, non-exempt row"
    )
    parked = settled_rows_needing_retirement(_read(ROADMAP_PATH))
    assert parked == (), (
        "ROADMAP.md holds settled index row(s) that were never retired: "
        f"{list(parked)}"
    )
