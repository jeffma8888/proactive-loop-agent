"""Iteration 162 (factory iter 168) -- black-box verification of the retire-on-ship brake.

WHAT THIS ITERATION CLAIMS (restated from the PM spec so this file stands alone)
"Retire on ship" -- a row whose status has gone SHIPPED/CLOSED/ABANDONED leaves the
live ``ROADMAP.md`` index and lands in ``ROADMAP_ARCHIVE.md`` as a bullet -- has only
ever been PROSE in the roadmap's own header, and that control failed four iterations
running: 5 settled rows and 3,443 chars of dead index text accumulated against a
40,000-char ceiling with 1,021 chars of headroom left. This iteration (a) retires rows
#138, #197, #198, #199 and #200 into the archive and (b) converts the prose into an
ORACLE: a pure census ``settled_rows_needing_retirement(text)`` that names any settled
row still parked in the index, with a single enumerated, self-cleaning exemption
(``SETTLED_ROWS_PINNED_TO_INDEX == ("121",)``, because ``test_iter115_behavior.py``
requires exactly one live row #121). Nothing under ``src/`` changes.

HOW THIS FILE VERIFIES IT, INDEPENDENTLY
The unit under test is a documentation control, so its public surfaces are the two
tracked markdown documents and the importable pure function -- there is no CLI verb to
drive. The independence therefore comes from a SECOND IMPLEMENTATION: every rule in the
spec (which line is an index row, which cell is the status, which prefixes are settled)
is re-implemented here from the spec's WORDING under an ``_indep_`` prefix, and the two
implementations are required to AGREE on the live document. A shared bug would have to
be invented twice, in two different regex dialects, to slip through. Row/archive
membership is likewise re-counted with this file's own regexes rather than the guard
module's counters.

Four traps this file respects on purpose.
1. VACUOUS GREEN. ``census(live) == ()`` also passes when the parser returns nothing at
   all, so the live document is additionally required to yield >= 20 parsed rows AND the
   census is fired on a MUTATED COPY OF THE LIVE TEXT (a planted settled row in the
   file's real shape) where it must return exactly the planted row. A fixture-only
   two-sided proof leaves the live half unproven.
2. AMBIENT / GITIGNORED STATE. Every path read here (``ROADMAP.md``,
   ``ROADMAP_ARCHIVE.md``, the guard module) is git-tracked, so every precondition holds
   in the throwaway fresh clone each ship is re-verified from. No test reads
   ``state/``, a log, or a repo-directory basename.
3. INTERPRETER SKEW. CI runs 3.12 and 3.13 and 3.13 strips the common leading docstring
   indent at compile time, so nothing here asserts on indentation or on docstring text.
4. TABLE-SHAPE COLLATERAL. Retirements are BULLETS: a bullet carrying a ``|`` would be
   parsed as a table row and would red ``test_iter133_behavior.py``, so the archive's
   table census ([98, 40]) and the pipe-freedom of each new bullet are asserted here too.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

from tests.test_iter164_behavior import SPEC_RETIRED_ROWS
from tests.test_roadmap_size_budget import (
    RETIRED_ROWS,
    SETTLED_ROWS_PINNED_TO_INDEX,
    parse_index_rows,
    settled_rows_needing_retirement,
)

REPO: Final[Path] = Path(__file__).resolve().parents[1]
ROADMAP: Final[Path] = REPO / "ROADMAP.md"
ARCHIVE: Final[Path] = REPO / "ROADMAP_ARCHIVE.md"

#: The operator's ceiling, spelled independently of the guard module (behavior 11).
CEILING: Final[int] = 40000

#: The settled prefixes, spelled from the spec wording rather than imported, so a
#: silent edit to the guard's tuple cannot silently redefine what this file checks.
SETTLED: Final[tuple[str, ...]] = ("**SHIPPED", "**CLOSED", "**ABANDONED")

#: Statuses that must NEVER be reported: open work is exactly what the index is for.
OPEN_PREFIXES: Final[tuple[str, ...]] = ("**QUEUED", "**BLOCKED")

#: The nine rows retired so far, spelled a THIRD time (behavior 7 makes all three agree).
EXPECTED_RETIRED: Final[frozenset[str]] = frozenset(
    {"143", "146", "155", "195", "138", "197", "198", "199", "200"}
)

#: The single exemption and its reason (behaviors 4, 6, 9).
PINNED: Final[str] = "121"

#: The archive's table census (behavior 10): two tables, these body-row counts.
ARCHIVE_TABLE_BODIES: Final[tuple[int, ...]] = (98, 40)

_INDEP_ROW = re.compile(r"^\|\s*(\d+)\s*\|")
_INDEP_SEPARATOR = re.compile(r"^\|[-\s|:]+\|$", re.MULTILINE)


# ---------------------------------------------------------------------------
# Second implementation -- built from the spec's WORDING, not from the guard.
# ---------------------------------------------------------------------------
def _indep_index_rows(text: str) -> tuple[tuple[str, str], ...]:
    """Re-derive ``(row_number, status_cell)`` for every ``| N | ... |`` line.

    The spec's rule, restated: an index row is a line beginning with a pipe whose
    first cell is a bare integer, and its STATUS is the last pipe-delimited cell.
    """
    found: list[tuple[str, str]] = []
    for raw in text.splitlines():
        line = raw.rstrip()
        match = _INDEP_ROW.match(line)
        if match is None:
            continue
        cells = line.split("|")
        if cells and cells[0].strip() == "":
            cells = cells[1:]
        if cells and cells[-1].strip() == "":
            cells = cells[:-1]
        if len(cells) < 2:
            continue
        found.append((match.group(1), cells[-1].strip()))
    return tuple(found)


def _indep_census(text: str, exempt: tuple[str, ...] = (PINNED,)) -> tuple[str, ...]:
    """Settled, not exempt, in index order -- the spec's rule, independently coded."""
    return tuple(
        row
        for row, status in _indep_index_rows(text)
        if status.startswith(SETTLED) and row not in exempt
    )


def _indep_count_index_rows(text: str, row: str) -> int:
    return len(re.findall(rf"^\|\s*{re.escape(row)}\s*\|", text, re.MULTILINE))


def _indep_count_archive_bullets(text: str, row: str) -> int:
    return len(re.findall(rf"^- \*\*#{re.escape(row)} -- ", text, re.MULTILINE))


def _indep_archive_table_bodies(text: str) -> tuple[int, ...]:
    """Body-row counts per table: a run of pipe lines following a separator line."""
    bodies: list[int] = []
    inside = False
    for raw in text.splitlines():
        line = raw.strip()
        if _INDEP_SEPARATOR.match(line):
            inside = True
            bodies.append(0)
            continue
        if inside and line.startswith("|"):
            bodies[-1] += 1
            continue
        if inside:
            inside = False
    return tuple(bodies)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _live_roadmap() -> str:
    return _read(ROADMAP)


def _live_archive() -> str:
    return _read(ARCHIVE)


# Synthetic index in the live file's real 7-column shape. Never the live document.
_SYNTHETIC: Final[str] = """\
Prose above the table mentioning row | 900 | which is not a row.

| # | Enhancement | Layer | Value | Risk | Source | Status |
|---|-------------|-------|-------|------|--------|--------|
| 901 | **Something open** -- detail. | DX | Med | Low | PM | **QUEUED** |
| 902 | **Something shipped** -- detail. | DX | Med | Low | PM | **SHIPPED -- iter-1** |
| 121 | **The pinned row** -- detail. | Typing | Med | Low | PM | **SHIPPED -- iter-139** |
| 903 | **Something blocked** -- detail. | DX | Med | Low | PM | **BLOCKED -- needs a human** |
| 904 | **Something closed** -- detail. | DX | Med | Low | PM | **CLOSED -- superseded** |
| 905 | **Something abandoned** -- detail. | DX | Med | Low | PM | **ABANDONED -- wrong layer** |
- **#906 -- an archive bullet, not an index row** (shipped iter-2).
"""


# ---------------------------------------------------------------------------
# Behavior 1 -- a PURE census function keyed on the last cell, in index order.
# ---------------------------------------------------------------------------
def test_b1_the_census_is_pure_and_reads_only_its_argument() -> None:
    """Same text in, same tuple out, and nothing on disk is consulted.

    The planted row #902 is returned while live-only rows never appear, which is
    the observable proof the function did not reach for ``ROADMAP.md`` itself.
    """
    first = settled_rows_needing_retirement(_SYNTHETIC)
    second = settled_rows_needing_retirement(_SYNTHETIC)
    assert first == second
    assert "902" in first
    live_only = {row for row, _ in parse_index_rows(_live_roadmap())}
    assert live_only.isdisjoint(set(first) - {"121"})


def test_b1_the_census_reports_in_index_order() -> None:
    """Order is the file's order, so a reader can walk the index top to bottom."""
    assert settled_rows_needing_retirement(_SYNTHETIC) == ("902", "904", "905")


def test_b1_an_empty_document_is_reported_as_clean_not_crashed() -> None:
    assert settled_rows_needing_retirement("") == ()
    assert parse_index_rows("") == ()


# ---------------------------------------------------------------------------
# Behavior 2 -- two-sided on SYNTHETIC text, one axis per test.
# ---------------------------------------------------------------------------
def test_b2_a_settled_row_left_parked_in_the_index_is_reported() -> None:
    assert "902" in settled_rows_needing_retirement(_SYNTHETIC)


def test_b2_each_settled_prefix_fires_on_its_own() -> None:
    """SHIPPED, CLOSED and ABANDONED are three independent triggers."""
    for row, status in (("902", "SHIPPED"), ("904", "CLOSED"), ("905", "ABANDONED")):
        assert row in settled_rows_needing_retirement(_SYNTHETIC), status


def test_b2_a_row_on_the_allowlist_is_not_reported() -> None:
    assert PINNED not in settled_rows_needing_retirement(_SYNTHETIC)


def test_b2_open_and_blocked_rows_are_not_reported() -> None:
    reported = settled_rows_needing_retirement(_SYNTHETIC)
    assert "901" not in reported, "QUEUED work belongs in the index"
    assert "903" not in reported, "BLOCKED work belongs in the index"


def test_b2_lines_that_are_not_index_rows_are_ignored() -> None:
    """Prose carrying pipes, the header, the separator and an archive bullet."""
    parsed = {row for row, _ in parse_index_rows(_SYNTHETIC)}
    assert "900" not in parsed, "prose mentioning | 900 | is not a table row"
    assert "906" not in parsed, "an archive bullet is not a table row"
    assert parsed == {"901", "902", "121", "903", "904", "905"}


# ---------------------------------------------------------------------------
# Behaviors 3 + 5 -- the live property, and it is NOT vacuous.
# ---------------------------------------------------------------------------
def test_b3_the_live_index_holds_no_unretired_settled_row() -> None:
    assert settled_rows_needing_retirement(_live_roadmap()) == ()


def test_b5_the_live_parse_finds_at_least_twenty_rows() -> None:
    """An empty parse must not be able to satisfy behavior 3."""
    assert len(parse_index_rows(_live_roadmap())) >= 20


def test_b5_the_verdict_is_a_subset_of_the_parsed_rows() -> None:
    text = _live_roadmap() + (
        "\n| 998 | **Planted** -- detail. | DX | Med | Low | PM | **SHIPPED -- iter-x** |\n"
    )
    parsed = {row for row, _ in parse_index_rows(text)}
    assert set(settled_rows_needing_retirement(text)) <= parsed


def test_b5_the_brake_fires_on_the_live_documents_own_shape() -> None:
    """The live half of two-sidedness: plant one settled row in the REAL text.

    A synthetic-only proof passes on a parser that returns nothing for the live
    file's shape, which is exactly how a fail-open guard reads as green.
    """
    live = _live_roadmap()
    planted = live.replace(
        "| 201 |",
        "| 998 | **Planted settled row** -- detail. | DX | Med | Low | PM | "
        "**SHIPPED -- iter-x** |\n| 201 |",
        1,
    )
    assert planted != live, "anchor row #201 vanished -- update this fixture"
    assert settled_rows_needing_retirement(planted) == ("998",)


def test_b5_the_allowlist_is_keyed_on_the_row_number_not_the_status_text() -> None:
    """Renumbering the exempt live row makes it report -- the exemption is per row."""
    live = _live_roadmap()
    renumbered = re.sub(r"^\|\s*121\s*\|", "| 999 |", live, count=1, flags=re.MULTILINE)
    assert renumbered != live
    assert settled_rows_needing_retirement(renumbered) == ("999",)


# ---------------------------------------------------------------------------
# Independence -- a SECOND implementation of the spec must agree on the live text.
# ---------------------------------------------------------------------------
def test_two_independent_parsers_agree_on_the_live_index() -> None:
    assert _indep_index_rows(_live_roadmap()) == parse_index_rows(_live_roadmap())


def test_two_independent_censuses_agree_on_the_live_index() -> None:
    live = _live_roadmap()
    assert _indep_census(live) == settled_rows_needing_retirement(live) == ()


def test_two_independent_censuses_agree_on_the_synthetic_index() -> None:
    assert _indep_census(_SYNTHETIC) == settled_rows_needing_retirement(_SYNTHETIC)


# ---------------------------------------------------------------------------
# Behaviors 4 + 6 -- the exemption is enumerated, and it is self-cleaning.
# ---------------------------------------------------------------------------
def test_b4_the_allowlist_is_non_empty_and_names_only_row_121() -> None:
    assert SETTLED_ROWS_PINNED_TO_INDEX == (PINNED,)


def test_b6_every_exemption_is_still_live_and_still_settled() -> None:
    """A stale exemption is a build failure, not a free pass."""
    live = _live_roadmap()
    statuses = dict(_indep_index_rows(live))
    for row in SETTLED_ROWS_PINNED_TO_INDEX:
        assert _indep_count_index_rows(live, row) == 1, (
            f"row #{row} is exempted but is not present exactly once in the live "
            "index -- drop the stale exemption"
        )
        assert statuses[row].startswith(SETTLED), (
            f"row #{row} is exempted from retirement but its status is not settled "
            f"({statuses[row][:60]!r})"
        )


def test_b6_no_exempted_row_is_also_recorded_as_retired() -> None:
    """The two lists are mutually exclusive by construction."""
    assert set(SETTLED_ROWS_PINNED_TO_INDEX).isdisjoint(EXPECTED_RETIRED)


# ---------------------------------------------------------------------------
# Behavior 7 -- both retirement censuses agree, and name all nine rows.
# ---------------------------------------------------------------------------
def test_b7_both_retirement_censuses_name_the_same_nine_rows() -> None:
    assert set(RETIRED_ROWS) == set(SPEC_RETIRED_ROWS) == EXPECTED_RETIRED
    assert len(set(RETIRED_ROWS)) == len(RETIRED_ROWS) == 9
    assert len(set(SPEC_RETIRED_ROWS)) == len(SPEC_RETIRED_ROWS) == 9


def test_b7_the_five_rows_retired_this_iteration_are_in_both_censuses() -> None:
    for row in ("138", "197", "198", "199", "200"):
        assert row in RETIRED_ROWS, row
        assert row in SPEC_RETIRED_ROWS, row


# ---------------------------------------------------------------------------
# Behavior 8 -- the PAIR property, counted with this file's own regexes.
# ---------------------------------------------------------------------------
def test_b8_every_retired_row_left_the_index() -> None:
    live = _live_roadmap()
    parked = {row: _indep_count_index_rows(live, row) for row in sorted(EXPECTED_RETIRED)}
    assert all(count == 0 for count in parked.values()), (
        f"retired rows still parked in the live index: "
        f"{ {row: n for row, n in parked.items() if n} }"
    )


def test_b8_every_retired_row_landed_in_the_archive_exactly_once() -> None:
    archive = _live_archive()
    bullets = {row: _indep_count_archive_bullets(archive, row) for row in sorted(EXPECTED_RETIRED)}
    assert all(count == 1 for count in bullets.values()), (
        f"archive bullet count != 1 for: "
        f"{ {row: n for row, n in bullets.items() if n != 1} }"
    )


def test_b8_no_retirement_bullet_carries_a_pipe() -> None:
    """A bullet containing ``|`` is parsed as a table row and reds iter-133."""
    for raw in _live_archive().splitlines():
        line = raw.rstrip()
        match = re.match(r"^- \*\*#(\d+) -- ", line)
        if match is None or match.group(1) not in EXPECTED_RETIRED:
            continue
        assert "|" not in line, f"row #{match.group(1)} bullet carries a pipe"


# ---------------------------------------------------------------------------
# Behavior 9 -- archive presence is not a licence to delete.
# ---------------------------------------------------------------------------
def test_b9_row_121_is_both_archived_and_still_live() -> None:
    assert _indep_count_index_rows(_live_roadmap(), PINNED) == 1, (
        "test_iter115_behavior.py requires exactly one live index row #121"
    )
    assert _indep_count_archive_bullets(_live_archive(), PINNED) == 1


# ---------------------------------------------------------------------------
# Behavior 10 -- the archive's table shape is unchanged.
# ---------------------------------------------------------------------------
def test_b10_the_archive_still_holds_exactly_two_tables_of_the_same_size() -> None:
    bodies = _indep_archive_table_bodies(_live_archive())
    assert bodies == ARCHIVE_TABLE_BODIES
    assert sum(bodies) == 138


def test_b10_the_live_roadmap_still_holds_exactly_one_table() -> None:
    """The row regex is line-anchored, so a second numeric table would silently
    feed non-index rows into the census."""
    assert len(_INDEP_SEPARATOR.findall(_live_roadmap())) == 1


# ---------------------------------------------------------------------------
# Behavior 11 -- the trim actually bought headroom.
# ---------------------------------------------------------------------------
def test_b11_the_live_roadmap_is_under_the_operator_ceiling() -> None:
    chars = len(_live_roadmap())
    assert chars < CEILING, f"ROADMAP.md is {chars} chars, ceiling {CEILING}"


def test_b11_the_trim_left_more_than_two_thousand_chars_of_headroom() -> None:
    """The stated purpose was buying headroom, not merely staying legal: the row
    that shipped this claims 36,981 chars against 40,000."""
    headroom = CEILING - len(_live_roadmap())
    assert headroom > 2000, f"only {headroom} chars of headroom -- the trim did not land"
