"""Black-box behavior tests for state-dir iteration 235 (ships as ``foundry iter 209``):
THE SETTLED DONE-LEDGER TAIL IS RELOCATED TO THE ARCHIVE UNDER A CONSERVATION INVARIANT.

Feature under test: ``ROADMAP.md`` carries a hard 40,000-char ceiling
(``tests/test_roadmap_size_budget.py``) while its Done ledger is append-only, so the file
reaches the cap BY CONSTRUCTION -- it stood at 38,752 chars, 1,248 of headroom, 96.9% spent,
against ships that add 100-600 chars each. This iteration relocates the 40 oldest ledger
bullets verbatim into ``ROADMAP_ARCHIVE.md``, keeps the pinned ``#168`` line in place, and
adds a conservation guard so a relocation can never silently lose a ship record.

MODULE NAME -- derived from the REPO, never from the state-dir number. ``git ls-tree
--name-only HEAD tests/`` holds 232 entries whose highest ``test_iterNN_behavior.py`` is
**213**, so 214 is the next free name, and ``git cat-file -e HEAD:tests/test_iter214_behavior.py``
FAILED (``path ... does not exist in 'HEAD'``) before the first byte was written. Naming a
module from the state-dir counter (235 here) is what overwrote a shipped 18,786-byte oracle
in state-dir 186; the two counters differ and the offset is not guaranteed.

ISOLATION CONTRACT (honored, no exception). Every assertion below is derived from this
iteration's spec (``pm.md`` "Expected Behaviors" 1-8), from the two tracked Markdown
documents themselves, and from the conventions of the existing modules under ``tests/``
(``test_iter168_behavior.py`` supplies the two-independent-parsers idiom and the
``from tests.test_roadmap_size_budget import ...`` style; ``test_iter133_behavior.py``
supplies the table-body counter). **No file under ``src/`` was read, no ``git diff`` was
inspected, and neither ``engineer.md`` nor ``reviewer.md`` was opened.**

OFFLINE, DETERMINISTIC, FRESH-CLONE SAFE. Every assertion reads only TRACKED text at paths
resolved from ``__file__``: no network, no subprocess, no ``git`` invocation, no clock, and
no dependence on gitignored loop state (the iter-154 trap, where a test asserted a file
count that only held in this working tree). The pre-relocation census cannot be re-derived
from a shipped tree -- the text it describes no longer lives in ``ROADMAP.md`` -- so it is
embedded as :data:`PRE_RELOCATION_LEDGER`, disclosed as a monotone FLOOR measured once and
never a total: later ships widen the union, they never shrink it.

VERBATIMNESS IS PROVEN BY DIGEST, NOT BY EYE. :data:`RELOCATED_BULLETS_SHA256` is the
SHA-256 of the 40 moved bullets joined by ``chr(10)``, measured from the pre-move blob. A
digest fixes CONTENT **and ORDER** in one constant, so a reworded, re-wrapped, truncated or
reordered bullet all fail -- which a per-row set comparison would not catch.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Final

from tests.test_roadmap_size_budget import (
    check_char_budget,
    count_archive_bullets,
    settled_rows_needing_retirement,
)

REPO: Final[Path] = Path(__file__).resolve().parents[1]
ROADMAP: Final[Path] = REPO / "ROADMAP.md"
ARCHIVE: Final[Path] = REPO / "ROADMAP_ARCHIVE.md"

#: A Done-ledger SHIP RECORD, LINE-ANCHORED. Row numbers are quoted inside other rows'
#: prose constantly ("pairs with row #138"), so an unanchored probe counts prose as
#: records; the anchor also keeps the archive's ``- **#N -- `` RETIREMENT bullets -- a
#: different kind of entry with three counters of its own -- out of this census.
LEDGER_BULLET: Final[re.Pattern[str]] = re.compile(r"(?m)^- #(\d+) ")

#: The 81 rows the Done ledger held immediately BEFORE the relocation, in ledger order,
#: measured from ``git show HEAD:ROADMAP.md``. A monotone FLOOR, not a total: the ledger is
#: not sorted numerically (it runs ... 189, 155, 195, 138, 197 ...), which is why the order
#: is recorded rather than assumed.
PRE_RELOCATION_LEDGER: Final[tuple[str, ...]] = (
    "121", "125", "128", "131", "134", "139", "141", "145", "147", "148",
    "149", "150", "152", "153", "154", "156", "157", "159", "160", "162",
    "164", "166", "167", "168", "174", "175", "176", "177", "180", "181",
    "183", "186", "187", "188", "189", "155", "195", "138", "197", "199",
    "200", "198", "202", "203", "204", "207", "196", "208", "209", "206",
    "211", "201", "213", "214", "129", "215", "216", "217", "219", "185",
    "220", "221", "223", "224", "225", "178", "226", "136", "227", "228",
    "229", "230", "233", "222", "151", "234", "235", "236", "237", "238",
    "239",
)

#: The 40 rows relocated by this iteration, in the order they stood in the ledger. This is
#: ``PRE_RELOCATION_LEDGER[:41]`` minus the pinned ``#168``.
RELOCATED_ROWS: Final[tuple[str, ...]] = tuple(
    row for row in PRE_RELOCATION_LEDGER[:41] if row != "168"
)

#: SHA-256 of the 40 relocated bullets joined by ``chr(10)``, measured from the pre-move
#: ``ROADMAP.md`` blob. Fixes content AND order in one constant.
RELOCATED_BULLETS_SHA256: Final[str] = (
    "586731c7d0f519d831939c6af212730f917c7e7ae2418e55776d21097162526c"
)

#: Endpoint pins, quoted verbatim from the pre-move blob, so a digest mismatch can be read
#: by a human without re-deriving the whole slice.
OLDEST_RELOCATED: Final[str] = (
    "- #121 Close the deferred disallow_any_generics flag: the... "
    "(iter 139, factory iter 146)"
)
NEWEST_RELOCATED: Final[str] = (
    "- #200 scan --snapshot FILE: perceived signals as a... (iter 161, factory iter 167)"
)

#: The one ledger row that must STAY in ``ROADMAP.md`` while its neighbours move, with the
#: reason. ``tests/test_iter145_behavior.py::test_b12_the_roadmap_records_the_row_as_selected_for_this_iteration``
#: accepts row #168 as a live INDEX row or a Done-ledger line in ``ROADMAP.md``, and #168 is
#: no longer in the index -- so relocating its bullet reds that already-shipped oracle.
PINNED_TO_ROADMAP: Final[str] = "168"

#: The 40,000-char ceiling from the sibling budget module, and the headroom this iteration
#: contracted to buy back (``pm.md`` behavior 7).
CHAR_LIMIT: Final[int] = 40_000
MIN_HEADROOM: Final[int] = 4_000

#: Retirement-bullet counts for the relocated rows, measured on the PRE-MOVE archive blob.
#: Row #167 carries TWO retirement bullets and always did -- an earlier draft of this module
#: asserted a ``<= 1`` bound and reddened on it, so the exact census is pinned instead of a
#: guessed bound. Rows absent from this mapping had a count of zero before and must still.
RELOCATED_ROW_RETIREMENT_COUNTS_BEFORE: Final[dict[str, int]] = {
    "121": 1, "125": 1, "131": 1, "149": 1, "156": 1, "159": 1, "160": 1,
    "162": 1, "164": 1, "166": 1, "167": 2, "174": 1, "175": 1, "176": 1,
    "177": 1, "180": 1, "181": 1, "183": 1, "186": 1, "187": 1, "188": 1,
    "155": 1, "195": 1, "138": 1, "197": 1, "199": 1, "200": 1,
}

#: Archive table shape, pinned independently by ``tests/test_iter133_behavior.py`` (98 + 40)
#: and re-asserted here because a relocation that emitted TABLE ROWS instead of bullets
#: would break it silently.
ARCHIVE_TABLE_BODIES: Final[tuple[int, ...]] = (98, 40)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _ledger_bullets(text: str) -> tuple[str, ...]:
    """Every ship-record LINE, in document order. Independent of the guard module."""
    return tuple(
        line for line in text.splitlines() if LEDGER_BULLET.match(line) is not None
    )


def _ledger_rows(text: str) -> tuple[str, ...]:
    return tuple(m.group(1) for m in LEDGER_BULLET.finditer(text))


def _relocated_bullets(text: str) -> tuple[str, ...]:
    """The bullets for the rows :data:`RELOCATED_ROWS` names, in document order.

    Scoped to THIS iteration's 40 rows rather than to every ledger bullet the archive
    happens to hold, because that is the claim behavior 2 actually makes -- the slice this
    iteration moved is verbatim, in order, once each. The unscoped form measured the whole
    document, which silently turned a point-in-time proof into a prohibition: any LATER
    relocation adding one bullet changed the digest, the endpoints and the row set at once.
    That contradicted ``tests/test_roadmap_ledger_conservation.py``, whose stated purpose is
    to be "the control that makes relocating safe to repeat", and it is what blocked the
    second batch. Narrowing the DOMAIN leaves every pinned constant untouched: over the 40
    named rows the digest, both endpoints and the census are bit-for-bit what they were.
    """
    wanted = frozenset(RELOCATED_ROWS)
    return tuple(
        line
        for line in _ledger_bullets(text)
        if (match := LEDGER_BULLET.match(line)) is not None and match.group(1) in wanted
    )


def _conservation_failures(
    roadmap_text: str, archive_text: str, anchor: tuple[str, ...]
) -> tuple[str, ...]:
    """Rows from ``anchor`` recorded in NEITHER document, plus rows in BOTH.

    A second, deliberately independent implementation of the invariant: the shipped guard
    is not imported, so agreement between the two is evidence rather than a tautology.
    """
    left, right = set(_ledger_rows(roadmap_text)), set(_ledger_rows(archive_text))
    missing = tuple(row for row in anchor if row not in left and row not in right)
    duplicated = tuple(sorted(left & right, key=int))
    return missing + duplicated


def _table_bodies(text: str) -> tuple[int, ...]:
    """Body-row count per Markdown table, mirroring ``test_iter133_behavior.py``."""
    out: list[int] = []
    current: list[int] | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            if current is None:
                current = [0, 0]
            elif not current[1] and set(stripped.replace("|", "").replace(" ", "")) <= set("-:"):
                current[1] = 1
            else:
                current[0] += 1
        elif current is not None:
            out.append(current[0])
            current = None
    if current is not None:
        out.append(current[0])
    return tuple(out)


# --------------------------------------------------------------------------------------
# Behavior 1 -- the 40 oldest ledger bullets are gone from ROADMAP.md
# --------------------------------------------------------------------------------------


def test_b1_every_relocated_row_left_the_roadmap_ledger() -> None:
    rows = _ledger_rows(_read(ROADMAP))
    still_there = tuple(row for row in RELOCATED_ROWS if row in rows)
    assert still_there == (), f"rows never left ROADMAP.md: {still_there}"


def test_b1_the_relocation_moved_exactly_forty_rows_and_kept_the_rest() -> None:
    assert len(RELOCATED_ROWS) == 40
    # VANISHED means gone from BOTH documents, which is what this assertion's own message
    # says and what "the rest was kept" claims. Measuring only ROADMAP.md over-stated it
    # into "the other 41 may never move", i.e. a ban on the second batch; a retained row
    # relocated LATER is still kept, it just lives in the archive now.
    recorded = set(_ledger_rows(_read(ROADMAP))) | set(_ledger_rows(_read(ARCHIVE)))
    retained = {row for row in PRE_RELOCATION_LEDGER if row not in set(RELOCATED_ROWS)}
    assert retained <= recorded, (
        f"retained rows vanished: {sorted(retained - recorded, key=int)}"
    )


def test_b1_the_ledger_is_non_vacuous_so_the_absence_check_can_fail() -> None:
    # If the ledger were empty the b1 assertions would pass by finding nothing.
    assert len(_ledger_bullets(_read(ROADMAP))) >= 41


# --------------------------------------------------------------------------------------
# Behavior 2 -- each moved bullet appears VERBATIM in the archive, under ONE new heading
# --------------------------------------------------------------------------------------


def test_b2_the_relocated_bullets_are_byte_identical_to_the_pre_move_text() -> None:
    bullets = _relocated_bullets(_read(ARCHIVE))
    digest = hashlib.sha256(chr(10).join(bullets).encode("utf-8")).hexdigest()
    assert digest == RELOCATED_BULLETS_SHA256, (
        "archive ledger bullets differ from the pre-move slice in content or order; "
        f"got {len(bullets)} bullets, digest {digest}"
    )


def test_b2_the_endpoints_are_quoted_verbatim_including_the_iteration_suffix() -> None:
    bullets = _relocated_bullets(_read(ARCHIVE))
    assert bullets[0] == OLDEST_RELOCATED
    assert bullets[-1] == NEWEST_RELOCATED


def test_b2_every_relocated_row_is_recorded_in_the_archive_exactly_once() -> None:
    rows = _ledger_rows(_read(ARCHIVE))
    mine = tuple(row for row in rows if row in frozenset(RELOCATED_ROWS))
    assert sorted(mine, key=int) == sorted(RELOCATED_ROWS, key=int)
    # Kept over the WHOLE archive, not just this slice: a duplicate anywhere makes ``grep``
    # ambiguous about where a ship record lives, whichever batch relocated it.
    assert len(rows) == len(set(rows)), "a ship record is recorded twice in the archive"


def test_b2_all_relocated_bullets_sit_under_one_dedicated_heading() -> None:
    lines = _read(ARCHIVE).splitlines()
    starts = [i for i, line in enumerate(lines) if line.startswith("## ")]
    owning = {
        max(s for s in starts if s < i)
        for i, line in enumerate(lines)
        if LEDGER_BULLET.match(line) is not None
    }
    assert len(owning) == 1, (
        f"relocated bullets are spread across {len(owning)} sections; expected one"
    )
    heading = lines[owning.pop()].lower()
    assert "ledger" in heading and "relocat" in heading, (
        f"the owning heading does not name itself as relocated ledger lines: {heading!r}"
    )


def test_b2_no_relocated_bullet_carries_a_pipe_so_none_can_parse_as_a_table_row() -> None:
    offenders = tuple(b for b in _ledger_bullets(_read(ARCHIVE)) if "|" in b)
    assert offenders == (), f"pipe in a relocated bullet: {offenders}"


# --------------------------------------------------------------------------------------
# Behavior 3 -- the pinned #168 bullet REMAINS in ROADMAP.md
# --------------------------------------------------------------------------------------


def test_b3_the_pinned_row_is_still_recorded_as_a_roadmap_ledger_line() -> None:
    assert PINNED_TO_ROADMAP in _ledger_rows(_read(ROADMAP))


def test_b3_the_pinned_row_was_not_relocated_and_is_absent_from_the_archive() -> None:
    assert PINNED_TO_ROADMAP not in RELOCATED_ROWS
    assert PINNED_TO_ROADMAP not in _ledger_rows(_read(ARCHIVE))


def test_b3_the_pin_is_reproduced_by_the_iter145_oracles_own_acceptance_rule() -> None:
    # test_iter145 accepts row #168 as a live INDEX row OR a Done-ledger line. It is not in
    # the index, so the ledger line is the ONLY record -- re-derived here, not imported.
    text = _read(ROADMAP)
    in_index = re.search(rf"(?m)^\|\s*#?{PINNED_TO_ROADMAP}\s*\|", text) is not None
    in_ledger = PINNED_TO_ROADMAP in _ledger_rows(text)
    assert in_index or in_ledger
    assert in_ledger, "the ledger line is the only surviving record of the pinned row"


# --------------------------------------------------------------------------------------
# Behaviors 4 and 5 -- conservation across the pair, and the guard is TWO-SIDED
# --------------------------------------------------------------------------------------


def test_b4_the_union_of_the_pair_covers_every_pre_relocation_ship_record() -> None:
    failures = _conservation_failures(
        _read(ROADMAP), _read(ARCHIVE), PRE_RELOCATION_LEDGER
    )
    assert failures == (), f"ship records lost or duplicated: {failures}"


def test_b4_no_row_number_is_recorded_in_both_documents() -> None:
    both = set(_ledger_rows(_read(ROADMAP))) & set(_ledger_rows(_read(ARCHIVE)))
    assert both == set(), f"recorded twice across the pair: {sorted(both, key=int)}"


def test_b4_the_anchor_is_the_whole_pre_move_ledger_not_a_convenient_subset() -> None:
    assert len(PRE_RELOCATION_LEDGER) == 81
    assert len(set(PRE_RELOCATION_LEDGER)) == 81
    assert set(RELOCATED_ROWS) < set(PRE_RELOCATION_LEDGER)


def test_b5_the_invariant_fires_on_a_record_missing_from_both_documents() -> None:
    dropped = RELOCATED_ROWS[7]
    archive = chr(10).join(
        b for b in _ledger_bullets(_read(ARCHIVE)) if not b.startswith(f"- #{dropped} ")
    )
    failures = _conservation_failures(_read(ROADMAP), archive, PRE_RELOCATION_LEDGER)
    assert dropped in failures, (
        f"a bullet deleted from BOTH documents was not reported; got {failures}"
    )


def test_b5_the_invariant_fires_on_a_record_duplicated_across_the_pair() -> None:
    duplicated = RELOCATED_ROWS[0]
    roadmap = _read(ROADMAP) + chr(10) + f"- #{duplicated} re-added by mistake"
    failures = _conservation_failures(roadmap, _read(ARCHIVE), PRE_RELOCATION_LEDGER)
    assert duplicated in failures


def test_b5_the_invariant_is_green_on_a_synthetic_well_formed_pair() -> None:
    # Two-sided in both directions: it must also NOT fire on a correct relocation.
    assert (
        _conservation_failures("- #1 a", "- #2 b" + chr(10) + "- #3 c", ("1", "2", "3"))
        == ()
    )


def test_b5_the_matcher_ignores_the_archive_retirement_bullet_shape() -> None:
    assert _ledger_rows("- **#42 -- retired: reason") == ()
    assert _ledger_rows("- #42 shipped something (iter 1, factory iter 1)") == ("42",)


def test_b5_the_matcher_is_line_anchored_so_quoted_row_numbers_are_not_records() -> None:
    assert _ledger_rows("prose that pairs with row #138 inline") == ()


# --------------------------------------------------------------------------------------
# Behavior 6 -- count_archive_bullets is unchanged for every row
# --------------------------------------------------------------------------------------


def test_b6_the_retirement_counter_ignores_the_relocated_ledger_shape() -> None:
    # Proven on synthetic text, so it holds for EVERY row rather than the live sample only.
    bullet = "- #77 shipped something (iter 1, factory iter 1)"
    assert count_archive_bullets(bullet, "77") == 0
    assert count_archive_bullets("- **#77 -- retired: reason", "77") == 1


def test_b6_the_live_retirement_census_is_unmoved_across_every_row() -> None:
    # A LITERAL on purpose (same discipline as ROADMAP_CHAR_LIMIT): a derived total would
    # re-authorise whatever the archive grew to and could never fire. It therefore moves by
    # exactly +1 whenever an iteration retires an index row, which is a deliberate one-token
    # edit by the PM who retired it -- 70 before iteration 240 retired row #245, and 71
    # before iteration 241 retired row #117 (the packaging-contract oracle), and 72 before
    # iteration 242 retired row #246 (the `run --json` deferred key), and 73 before
    # iteration 244 retired row #247 (the line-number-anchor ban), and 74 before
    # iteration 249 retired row #249 (`run --exclude-path`).
    archive = _read(ARCHIVE)
    counts = {str(row): count_archive_bullets(archive, str(row)) for row in range(301)}
    assert sum(counts.values()) == 75, (
        f"retirement-bullet total moved: {sum(counts.values())} (expected 75). If you just "
        "retired an index row, bump this literal by one and say which row in the comment; "
        "if you did not, a retirement bullet was lost or duplicated."
    )
    # #121 is the double-count trap: already retired AND inside the relocated group.
    assert counts["121"] == 1


def test_b6_every_relocated_row_keeps_its_exact_pre_move_retirement_count() -> None:
    # MEASURED, not assumed: an earlier draft of this test asserted <= 1 per row and FAILED
    # on row #167, which legitimately carries TWO retirement bullets in the archive and did
    # so before the move as well. The invented bound was the bug; the exact pre-move census
    # below is the real claim, and it is what behavior 6 actually says.
    archive = _read(ARCHIVE)
    live = {
        row: count_archive_bullets(archive, row)
        for row in RELOCATED_ROWS
        if count_archive_bullets(archive, row)
    }
    assert live == RELOCATED_ROW_RETIREMENT_COUNTS_BEFORE, (
        "a relocated bullet changed the retirement census: "
        f"{sorted(set(live.items()) ^ set(RELOCATED_ROW_RETIREMENT_COUNTS_BEFORE.items()))}"
    )


# --------------------------------------------------------------------------------------
# Behavior 7 -- ROADMAP.md clears its budget with real headroom
# --------------------------------------------------------------------------------------


def test_b7_the_roadmap_is_inside_its_char_budget() -> None:
    verdict = check_char_budget(_read(ROADMAP))
    assert verdict.ok, verdict.message


def test_b7_the_relocation_bought_back_at_least_four_thousand_chars_of_headroom() -> None:
    verdict = check_char_budget(_read(ROADMAP))
    headroom = CHAR_LIMIT - verdict.chars
    assert headroom >= MIN_HEADROOM, (
        f"only {headroom} chars of headroom; the relocation contracted to leave "
        f">= {MIN_HEADROOM} (was 1248 before the move)"
    )


# --------------------------------------------------------------------------------------
# Behavior 8 -- no existing brake changes verdict
# --------------------------------------------------------------------------------------


def test_b8_the_settled_row_brake_still_reports_a_clean_index() -> None:
    assert settled_rows_needing_retirement(_read(ROADMAP)) == ()


def test_b8_the_archive_still_holds_its_two_pinned_tables_unchanged() -> None:
    assert _table_bodies(_read(ARCHIVE)) == ARCHIVE_TABLE_BODIES


def test_b8_the_roadmap_still_holds_exactly_one_table() -> None:
    bodies = _table_bodies(_read(ROADMAP))
    assert len(bodies) == 1 and bodies[0] >= 20, bodies


def test_b8_this_iterations_own_ship_record_is_in_the_ledger() -> None:
    rows = _ledger_rows(_read(ROADMAP))
    assert "240" in rows, "PM duty 3: this iteration's row is not recorded in the ledger"
