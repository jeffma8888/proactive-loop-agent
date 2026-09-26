"""Black-box oracle for foundry iteration 320 (state-dir iteration 466): ROADMAP row #109
retired from the index as SUPERSEDED, written by the tester from the spec alone.

WHY THIS MODULE EXISTS. Row #109 claimed for 360+ iterations that ``SPEC.md`` "has NO size
guard" while ``tests/test_iter255_behavior.py::SPEC_CEILING_AFTER_SLICE = 95_500`` asserts the
live file (and iteration 464 was reverted on exactly that guard). The spec retires the row into
the Done ledger and ``ROADMAP_ARCHIVE.md`` with an honest SUPERSEDED disposition so nobody
re-opens it as unfinished.

WHAT THIS MODULE GRADES, durably (no dependence on which commit ``HEAD`` is):
(1) the index no longer carries a ``| 109 |`` row and still meets the shipped ``>= 20``
numeric-row floor (``test_iter168`` / ``test_iter264`` / ``test_iter265`` /
``test_roadmap_size_budget``); (2) the archive holds exactly one ``- **#109 -- `` bullet in
the "Rows shipped after iter-133" section, immediately after ``#282`` and before the
"Relocated Done-ledger lines" heading, carrying the retirement tag and all six index cells
byte-for-byte behind field labels with no pipe; (3) ledger conservation: exactly one ``- #109 ``
ship record, in ``ROADMAP.md`` only, appended after ``#298``, <= 120 chars, tagged
``(foundry iter 320)`` and naming SUPERSEDED / ``SPEC_CEILING_AFTER_SLICE`` / ``95_500`` /
``#179/#270``; (4) ``ROADMAP.md`` stays under the binding ``test_iter241::test_b09c`` pin and
the ``test_iter214`` 4,000-char headroom floor.

SPEC DRIFT RECORDED, NOT GRADED. pm.md predicted "index 20 -> 19", "net-negative bytes
(< 34,529)" and "no test file changed"; four shipped oracles pin the index at >= 20 rows and
three pin the archive/ledger record counts as literals, so the shippable shape is
"retire #109 + one QUEUED replacement row + re-keyed literals". This module encodes the
oracle-consistent reading; the literal predictions are noted in the tester report.

ISOLATION CONTRACT (honored). Reads the two Markdown files as a consumer would; no
implementation import, no subprocess, no network. Deterministic and offline.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

REPO: Final[Path] = Path(__file__).resolve().parents[1]
ROADMAP: Final[Path] = REPO / "ROADMAP.md"
ARCHIVE: Final[Path] = REPO / "ROADMAP_ARCHIVE.md"

RETIRED_ROW: Final[str] = "109"
SHIP_TAG: Final[str] = "(foundry iter 320)"
INDEX_ROW: Final[re.Pattern[str]] = re.compile(r"^\| (\d+) \|", re.MULTILINE)
#: Shipped floor on numeric index rows (test_iter168 / test_iter264 / test_iter265).
MIN_INDEX_ROWS: Final[int] = 20

LEDGER_HEADING: Final[str] = "## Done ledger"
LEDGER_ROW: Final[re.Pattern[str]] = re.compile(r"^- #(\d+) ", re.MULTILINE)
LEDGER_LINE_PREFIX: Final[str] = "- #109 "
PREVIOUS_NEWEST_LEDGER_PREFIX: Final[str] = "- #298 "
LEDGER_MAX_CHARS: Final[int] = 120
LEDGER_TOKENS: Final[tuple[str, ...]] = (
    "SUPERSEDED",
    "SPEC_CEILING_AFTER_SLICE",
    "95_500",
    "#179/#270",
)

ARCHIVE_SECTION_HEADING: Final[str] = "## Rows shipped after iter-133"
ARCHIVE_PREDECESSOR_PREFIX: Final[str] = "- **#282 -- "
ARCHIVE_NEXT_HEADING: Final[str] = "## Relocated Done-ledger lines"
ARCHIVE_BULLET_PREFIX: Final[str] = "- **#109 -- "
RETIREMENT_TAG: Final[str] = (
    "(retired from the index in iter-466, foundry iter 320). Verbatim index text as it "
    "stood at retirement, pipes replaced by field labels so this bullet cannot be parsed "
    "as a table row: ENHANCEMENT: "
)
#: The six index cells of row #109 as they stood at retirement, byte-for-byte, keyed by the
#: field label the #179-shaped bullet must place in front of each.
LABELLED_CELLS: Final[tuple[tuple[str, str], ...]] = (
    (
        "ENHANCEMENT: ",
        "**Char-size budget test for the per-iteration required-reading docs** -- "
        "`ROADMAP.md` (~40KB operator trigger) and `SPEC.md` (90,269 chars) have NO size "
        "guard, and the 200KB-roadmap stall cost iters 90-91 all 8 attempts and 0 commits. "
        "Must prove itself against a synthetic over-budget file, and must NOT rewrite "
        "`SPEC.md` (operator-owned).",
    ),
    ("LAYER: ", "DX/integrity"),
    ("VALUE: ", "Med"),
    ("RISK: ", "Very Low"),
    ("SOURCE: ", "PM scout-B B3 (iter-100)"),
    (
        "STATUS: ",
        "**QUEUED -- `SPEC.md` HALF ONLY** (the `ROADMAP.md` half shipped as row #138, "
        "iter 158). `SPEC.md` is operator-owned at ~90,879 chars with NO operator-documented "
        "threshold, so any budget must sit ABOVE today's size -- an arbitrary, ratchet-shaped "
        "number. Settle the threshold before coding.",
    ),
)

#: Binding size pin on ROADMAP.md (test_iter241::test_b09c) and the operator cap with its
#: 4,000-char headroom floor (test_iter214).
ROADMAP_BINDING_CAP: Final[int] = 35_428
ROADMAP_HARD_CAP: Final[int] = 40_000
ROADMAP_HEADROOM_FLOOR: Final[int] = 4_000


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _lines(path: Path) -> list[str]:
    return _read(path).splitlines()


def _only_index_of(lines: list[str], prefix: str) -> int:
    hits = [i for i, line in enumerate(lines) if line.startswith(prefix)]
    assert len(hits) == 1, f"expected exactly one line starting {prefix!r}; got {hits}"
    return hits[0]


# ==========================================================================
# Behavior 1 -- the index no longer carries row #109 and still meets the row floor
# ==========================================================================


def test_b1_row_109_left_the_index_and_the_index_keeps_its_floor() -> None:
    text = _read(ROADMAP)
    numbers = INDEX_ROW.findall(text)
    assert RETIRED_ROW not in numbers, "row #109 must be gone from the index table"
    assert re.search(r"^\| 109 ", text, re.MULTILINE) is None
    assert len(numbers) >= MIN_INDEX_ROWS, (
        f"index has {len(numbers)} numeric rows; the shipped floor is {MIN_INDEX_ROWS}"
    )
    assert len(set(numbers)) == len(numbers), f"duplicate index row numbers: {numbers}"


# ==========================================================================
# Behavior 2 -- exactly one #179-shaped archive bullet, placed after #282
# ==========================================================================


def test_b2_archive_holds_one_labelled_verbatim_bullet_right_after_282() -> None:
    lines = _lines(ARCHIVE)
    bullet_at = _only_index_of(lines, ARCHIVE_BULLET_PREFIX)
    bullet = lines[bullet_at]
    assert RETIREMENT_TAG in bullet
    assert "|" not in bullet, "the bullet must not be parseable as a table row"

    cursor = 0
    for label, cell in LABELLED_CELLS:
        position = bullet.find(label + cell, cursor)
        assert position >= cursor, f"missing or out-of-order field {label!r} + verbatim cell"
        cursor = position + len(label) + len(cell)

    section_at = _only_index_of(lines, ARCHIVE_SECTION_HEADING)
    predecessor_at = _only_index_of(lines, ARCHIVE_PREDECESSOR_PREFIX)
    next_heading_at = _only_index_of(lines, ARCHIVE_NEXT_HEADING)
    assert section_at < predecessor_at < bullet_at < next_heading_at
    between = [line for line in lines[predecessor_at + 1 : bullet_at] if line.strip()]
    assert between == [], f"#109 must directly follow the #282 bullet; found {between!r}"


# ==========================================================================
# Behavior 3 -- one ship record, in the ledger only, appended after #298, tagged
# ==========================================================================


def test_b3_ledger_conservation_and_the_superseded_narration() -> None:
    roadmap_lines = _lines(ROADMAP)
    ledger_at = _only_index_of(roadmap_lines, LEDGER_LINE_PREFIX)
    row = roadmap_lines[ledger_at]
    assert len(row) <= LEDGER_MAX_CHARS, f"ledger row is {len(row)} chars: {row!r}"
    assert row.endswith(SHIP_TAG), row
    for token in LEDGER_TOKENS:
        assert token in row, f"ledger narration must name {token!r}: {row!r}"

    previous_at = _only_index_of(roadmap_lines, PREVIOUS_NEWEST_LEDGER_PREFIX)
    assert previous_at < ledger_at, "the #109 record must be appended after the #298 record"
    heading_at = _only_index_of(roadmap_lines, LEDGER_HEADING)
    assert heading_at < ledger_at

    assert not any(
        line.startswith(LEDGER_LINE_PREFIX) for line in _lines(ARCHIVE)
    ), "a ship record lives in exactly one file; the archive must hold no '- #109 ' line"


# ==========================================================================
# Behavior 4 -- ROADMAP.md stays under the binding pin and the headroom floor
# ==========================================================================


def test_b4_roadmap_stays_under_the_binding_pin_and_headroom_floor() -> None:
    text = _read(ROADMAP)
    chars = len(text)
    size = len(text.encode("utf-8"))
    assert chars < ROADMAP_BINDING_CAP, f"ROADMAP.md is {chars} chars; pin is {ROADMAP_BINDING_CAP}"
    assert size < ROADMAP_BINDING_CAP, f"ROADMAP.md is {size} bytes; pin is {ROADMAP_BINDING_CAP}"
    assert ROADMAP_HARD_CAP - chars >= ROADMAP_HEADROOM_FLOOR, (
        f"only {ROADMAP_HARD_CAP - chars} chars of headroom under {ROADMAP_HARD_CAP}"
    )
