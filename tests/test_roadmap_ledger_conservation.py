"""Repo contract: a Done-ledger SHIP RECORD may never vanish from the ROADMAP pair.

``ROADMAP.md`` carries a hard 40,000-char ceiling (``tests/test_roadmap_size_budget.py``),
and its Done ledger grew append-only against that ceiling -- which reaches the cap BY
CONSTRUCTION. Iteration 235 therefore relocated the 40 oldest ledger bullets verbatim into
``ROADMAP_ARCHIVE.md``. This module is the control that makes relocating safe to repeat.

WHY an oracle rather than a note in the header. The sibling brake's own docstring records
that "archive first, then drop" lived only as prose and "that control failed four
iterations running", accumulating 5 settled rows and 3,443 chars of dead text against a
ceiling with 1,021 chars left. A relocation is a DELETE plus an INSERT in two documents:
the failure mode is a bullet deleted from ``ROADMAP.md`` that never lands in the archive,
which no existing guard can see, because every archive counter in this repo is anchored on
the BOLD retirement shape ``- **#N -- `` and a relocated ledger line keeps the plain
``- #N `` shape on purpose.

The invariant is deliberately over ROW NUMBERS and over the UNION of the two documents, so
it constrains WHERE a record lives no more than it has to: a record may sit in either file
and must sit in exactly one. VERBATIMNESS of the moved text is a different claim, owned by
this iteration's behavior module, and is not restated here.

:data:`RELOCATION_ANCHOR` is a monotone FLOOR, not a total: it is the census measured at
the moment of the first relocation, so it cannot decay the way a hand-maintained
denominator does -- new ledger rows simply widen the union. A LATER relocation must extend
it with the rows added since, and the verdict message says so.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

REPO: Final[Path] = Path(__file__).resolve().parents[1]
ROADMAP: Final[Path] = REPO / "ROADMAP.md"
ARCHIVE: Final[Path] = REPO / "ROADMAP_ARCHIVE.md"

#: A ship record, LINE-ANCHORED. Row numbers are quoted inside other rows' prose
#: constantly ("pairs with row #138"), so an unanchored probe would count prose as
#: records; and the anchor is what keeps the archive's ``- **#N -- `` retirement bullets
#: -- a different kind of entry, with three counters of their own -- out of this census.
LEDGER_BULLET: Final[re.Pattern[str]] = re.compile(r"(?m)^- #(\d+) ")

#: Ledger rows that must STAY in ``ROADMAP.md`` when their neighbours are relocated, each
#: with the reason. Mirrors ``SETTLED_ROWS_PINNED_TO_INDEX`` in the size-budget module: an
#: enumerated exception, never a wildcard, and self-cleaning (see the test below).
LEDGER_ROWS_PINNED_TO_ROADMAP: Final[dict[str, str]] = {
    "168": (
        "tests/test_iter145_behavior.py::"
        "test_b12_the_roadmap_records_the_row_as_selected_for_this_iteration accepts a "
        "record for row #168 as a live INDEX row or a Done-ledger line in ROADMAP.md, and "
        "#168 is no longer in the index -- so relocating its bullet leaves the row "
        "unrecorded in that file and reds the build"
    ),
}

#: The 81 rows the ledger held at ``40a0791``, in ledger order, measured from
#: ``git show HEAD:ROADMAP.md`` immediately before the first relocation.
RELOCATION_ANCHOR: Final[tuple[str, ...]] = (
    "121", "125", "128", "131", "134", "139", "141", "145",
    "147", "148", "149", "150", "152", "153", "154", "156",
    "157", "159", "160", "162", "164", "166", "167", "168",
    "174", "175", "176", "177", "180", "181", "183", "186",
    "187", "188", "189", "155", "195", "138", "197", "199",
    "200", "198", "202", "203", "204", "207", "196", "208",
    "209", "206", "211", "201", "213", "214", "129", "215",
    "216", "217", "219", "185", "220", "221", "223", "224",
    "225", "178", "226", "136", "227", "228", "229", "230",
    "233", "222", "151", "234", "235", "236", "237", "238",
    "239",
)


@dataclass(frozen=True)
class ConservationVerdict:
    """The outcome of one conservation measurement over the ROADMAP pair.

    ``message`` is populated in the GREEN case too, for the reason the sibling
    size-budget verdict gives: a guard that only ever prints on failure cannot tell a
    passing measurement from one that forgot to measure, and the actionable facts (how
    many records each document holds, which rows are missing or doubled) are worth having
    either way.
    """

    ok: bool
    missing: tuple[str, ...]
    duplicated: tuple[str, ...]
    message: str


def ledger_rows(text: str) -> tuple[str, ...]:
    """Row numbers recorded as Done-ledger ship records in ``text``.

    Pure, and takes TEXT rather than a path, so the guard built on it can be fired at
    synthetic documents instead of only at the live pair it polices.
    """
    return tuple(LEDGER_BULLET.findall(text))


def check_ledger_conservation(
    roadmap: str,
    archive: str,
    anchor: tuple[str, ...] = RELOCATION_ANCHOR,
) -> ConservationVerdict:
    """Every ``anchor`` row is recorded in exactly one of the two documents.

    Two failure directions, reported separately because they need opposite repairs: a
    MISSING row was deleted from one document without landing in the other (the
    relocation lost a ship record), while a DUPLICATED row is recorded twice, which makes
    ``grep`` ambiguous about where a record lives and lets one copy drift from the other.
    """
    in_roadmap = set(ledger_rows(roadmap))
    in_archive = set(ledger_rows(archive))
    missing = tuple(row for row in anchor if row not in in_roadmap | in_archive)
    duplicated = tuple(row for row in anchor if row in in_roadmap & in_archive)
    ok = not missing and not duplicated
    counted = (
        f"{len(in_roadmap)} ship record(s) in ROADMAP.md, {len(in_archive)} relocated "
        f"into ROADMAP_ARCHIVE.md, against an anchor of {len(anchor)}"
    )
    if ok:
        message = f"ledger conservation holds: {counted}"
    else:
        message = (
            f"ledger conservation BROKEN: {counted}; missing from BOTH documents: "
            f"{list(missing)}; recorded in BOTH: {list(duplicated)}. Restore the bullet "
            "verbatim, or -- if the anchor is stale after a later relocation -- extend "
            "RELOCATION_ANCHOR with the rows added since, never shrink it"
        )
    return ConservationVerdict(ok=ok, missing=missing, duplicated=duplicated, message=message)


def _read(path: Path) -> str:
    """Text of ``path``, failing loudly rather than conserving an empty string."""
    text = path.read_text(encoding="utf-8")
    assert text.strip(), f"{path.name} must not be empty (a vacuous census is no census)"
    return text


# ---------------------------------------------------------------------------
# The live pair.
# ---------------------------------------------------------------------------
def test_the_live_pair_conserves_every_pre_relocation_ship_record() -> None:
    verdict = check_ledger_conservation(_read(ROADMAP), _read(ARCHIVE))

    assert verdict.ok, verdict.message


def test_the_two_documents_never_record_the_same_row() -> None:
    """Disjointness over the LIVE rows, not only the anchored ones.

    The anchor bounds history; this catches a fresh row copied into both documents, which
    the anchor could not see because that row postdates it.
    """
    both = set(ledger_rows(_read(ROADMAP))) & set(ledger_rows(_read(ARCHIVE)))

    assert both == set(), f"these rows are recorded in BOTH documents: {sorted(both)}"


def test_both_documents_actually_carry_ship_records() -> None:
    """Anti-vacuity: a relocation that moved nothing would satisfy conservation trivially."""
    assert ledger_rows(_read(ROADMAP)), "ROADMAP.md records no ship record at all"
    assert ledger_rows(_read(ARCHIVE)), "ROADMAP_ARCHIVE.md holds no relocated record"


def test_the_verdict_reports_its_measurement_in_the_green_case_too() -> None:
    verdict = check_ledger_conservation(_read(ROADMAP), _read(ARCHIVE))

    assert verdict.ok
    assert "ROADMAP.md" in verdict.message and "ROADMAP_ARCHIVE.md" in verdict.message
    assert str(len(RELOCATION_ANCHOR)) in verdict.message


# ---------------------------------------------------------------------------
# The guard is two-sided: it must FIRE, or green proves nothing.
# ---------------------------------------------------------------------------
#: A synthetic pair, so the fire-tests never touch the live documents.
_SYNTHETIC_ROADMAP: Final[str] = (
    "## Done ledger\n\n- #300 kept here (iter 1, factory iter 1)\n"
)
_SYNTHETIC_ARCHIVE: Final[str] = (
    "## Relocated\n\n- #301 relocated (iter 2, factory iter 2)\n"
)
_SYNTHETIC_ANCHOR: Final[tuple[str, ...]] = ("300", "301", "302")


def test_the_guard_fires_on_a_record_missing_from_both_documents() -> None:
    verdict = check_ledger_conservation(
        _SYNTHETIC_ROADMAP, _SYNTHETIC_ARCHIVE, _SYNTHETIC_ANCHOR
    )

    assert verdict.ok is False
    assert verdict.missing == ("302",)
    assert "302" in verdict.message, "the message must name the row that went missing"


def test_the_guard_fires_on_a_record_duplicated_across_the_pair() -> None:
    verdict = check_ledger_conservation(
        _SYNTHETIC_ROADMAP,
        _SYNTHETIC_ARCHIVE + "- #300 kept here (iter 1, factory iter 1)\n",
        ("300", "301"),
    )

    assert verdict.ok is False
    assert verdict.duplicated == ("300",)
    assert "300" in verdict.message


def test_a_relocation_that_drops_the_bullet_entirely_is_caught() -> None:
    """The exact defect this module exists for: deleted from the index, never archived."""
    verdict = check_ledger_conservation(
        "## Done ledger\n\n", _SYNTHETIC_ARCHIVE, _SYNTHETIC_ANCHOR
    )

    assert verdict.ok is False
    assert verdict.missing == ("300", "302")


# ---------------------------------------------------------------------------
# The matcher: what counts as a ship record, and what deliberately does not.
# ---------------------------------------------------------------------------
def test_the_matcher_ignores_the_archive_retirement_bullet_shape() -> None:
    """Behavior 6's protection, stated where the matcher lives.

    ``count_archive_bullets`` and two independent counters anchor on ``- **#N -- ``, and
    one of them asserts exactly ONE per retired row -- so a relocated bullet rewritten
    into that shape would double-count row #121, which is both already-retired and in the
    relocated group. The two shapes must stay disjoint in BOTH directions.
    """
    retirement = "- **#121 -- close the deferred flag** (shipped iter-139).\n"
    ship_record = "- #121 Close the deferred disallow_any_generics flag (iter 139)\n"

    assert ledger_rows(retirement) == ()
    assert ledger_rows(ship_record) == ("121",)


def test_the_matcher_is_line_anchored_so_quoted_row_numbers_are_not_records() -> None:
    quoted = "- #300 a real record that also mentions row #138 mid-prose\n"

    assert ledger_rows(quoted) == ("300",)
    assert ledger_rows("prose naming - #138 inside a sentence\n") == ()


# ---------------------------------------------------------------------------
# The anchor and the allowlist are both self-cleaning.
# ---------------------------------------------------------------------------
def test_the_anchor_is_the_measured_pre_relocation_census() -> None:
    assert len(RELOCATION_ANCHOR) == 81
    assert len(set(RELOCATION_ANCHOR)) == len(RELOCATION_ANCHOR), "duplicate anchor row"
    assert RELOCATION_ANCHOR[0] == "121", "the oldest recorded ship is row #121"
    assert RELOCATION_ANCHOR[-1] == "239", "the newest ship at the relocation was #239"


def test_every_pinned_row_stays_in_the_live_roadmap_with_a_stated_reason() -> None:
    """SELF-CLEANING allowlist: a stale exemption is a failure, not a free pass.

    Each member must still be recorded in ``ROADMAP.md`` (else the exemption is dead
    text), must be ABSENT from the archive's relocated section (else it was relocated
    anyway and the exemption did not hold), and must carry a reason naming the oracle that
    requires it -- so the next relocation can tell a live pin from a forgotten one.
    """
    in_roadmap = set(ledger_rows(_read(ROADMAP)))
    in_archive = set(ledger_rows(_read(ARCHIVE)))

    for row, reason in LEDGER_ROWS_PINNED_TO_ROADMAP.items():
        assert row in in_roadmap, f"pinned row #{row} is no longer recorded in ROADMAP.md"
        assert row not in in_archive, f"pinned row #{row} was relocated despite the pin"
        assert "tests/" in reason and "::" in reason, (
            f"the pin on row #{row} must name the oracle that requires it; got {reason!r}"
        )
