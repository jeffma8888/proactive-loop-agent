"""Repo contract: the ``ROADMAP.md`` char-size budget (state iter-158, ships as ``factory iter 164``).

WHY A SIZE BUDGET IS A BUILD-FAILING ORACLE AND NOT A NOTE IN A HEADER
``ROADMAP.md`` is the one required-reading document an automated role must both
READ and REWRITE on every single iteration, and it is the only one with a
measured history of killing this loop: at 200,022 chars it pushed that stage past
the agent CLI's hard 600-second cap, and iterations 90-91 burned all 8 attempts,
producing 0 commits for ~9 hours. The operator's remedy was a threshold -- keep
the file under ~40,000 chars -- but until this module the threshold lived only in
PROSE, in the file's own header (``ROADMAP.md`` line 21) and in two roadmap rows
(#109, #138). Prose asks every future contributor to REMEMBER a number, which is
exactly the control that failed once already: measured at ship time this file
stood at 39,736 chars, i.e. **264 chars of headroom**, while the measured growth
rate is **+1,859 chars per iteration** (re-measured at iter-121 by piping
``git show`` of each ship sha through ``wc -c``). The very next row of any size
crossed the line. This module converts the number into a test.

WHY THE GUARD IS TWO-SIDED IN BOTH DIRECTIONS
1. Against the DETECTOR being dead. A ceiling assertion that has never been seen
   to FIRE is indistinguishable from ``assert True``, so
   :func:`check_char_budget` is a pure text -> verdict function and is fired at
   ``LIMIT + 1`` chars and at ``LIMIT - 1`` chars on SYNTHETIC strings. The live
   file is never the instrument used to test the instrument.
2. Against the SUBJECT being empty. ``len(text) <= 40_000`` passes on a 0-byte or
   half-written ``ROADMAP.md`` -- the failure that would matter most, because this
   repo has already lost a 987KB document to a truncating open. So the same
   verdict carries an anti-vacuity FLOOR: below 10,000 chars the file is reported
   BROKEN, not comfortably small.

WHY THE LIMIT IS A LITERAL AND MAY NEVER BE DERIVED
A budget computed from the live file's current size (``len(text) + slack``)
ratchets: it silently re-authorises whatever the file has already grown to and
therefore guards nothing. ``ROADMAP_CHAR_LIMIT`` is the operator's number, spelled
as a literal, and :func:`test_the_limit_is_a_literal_never_derived_from_the_live_file`
reads THIS MODULE'S OWN SOURCE to prove the assignment is a bare literal rather
than an expression over the file it polices.

WHY THE RETIREMENT ASSERTIONS SHIP IN THE SAME MODULE
The budget was bought back by retiring settled index rows into
``ROADMAP_ARCHIVE.md`` -- 4 in iteration 158 and 5 more in iteration 162, 9 in
:data:`RETIRED_ROWS` today -- and the file's own rule is "never drop a row
without first confirming the archive has it". A trim is therefore only correct as
a PAIR (absent here AND present there), which is a property no single-file check
can see. Row #121 is the pinned counter-example that keeps the rule honest: it is
BOTH archived AND deliberately retained in the live index, because
``test_iter115_behavior.py`` requires exactly one row #121 there. So archive
presence is NOT a licence to delete -- a retirement needs a test census -- and
scout B's slate for iteration 158 got that wrong. Pinning #121 here means the
next contributor's wrong retirement is a red build, not a lost oracle.

WHY A CEILING WAS NOT ENOUGH, AND WHAT THE BRAKE ADDS
A ceiling bounds the LEVEL and nothing else: each time it is approached, somebody
has to notice and buy headroom back by hand. Measured over the four iterations
after this guard shipped, nobody did -- 5 rows were marked settled and left
parked in the live index, 3,443 chars of dead text, against a file that had
1,021 chars of headroom left. The rule they broke was already written down, in
this very file's header, as prose. :func:`settled_rows_needing_retirement`
converts that prose into a build-failing census, which bounds the growth RATE:
the index can only grow by genuinely-open work, so the buy-back stops recurring
instead of coming due again every few iterations. It fires only on an act the
author actually performed (marking a row settled, then leaving it in the index),
never on being unlucky about size, which is why it is a census and not a
"headroom must exceed N" assertion.

Offline, deterministic, fresh-clone safe: pure text and length arithmetic over
two GIT-TRACKED files plus this module's own source. No product import, no
subprocess, no network, no clock, no writes anywhere. Every asserted path is
tracked by git, so nothing here depends on gitignored or per-machine state.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[1]
ROADMAP: Final[Path] = REPO_ROOT / "ROADMAP.md"
ARCHIVE: Final[Path] = REPO_ROOT / "ROADMAP_ARCHIVE.md"
THIS_MODULE: Final[Path] = Path(__file__).resolve()

#: The budgeted document, named in every verdict message so a failure is
#: actionable without opening this file.
BUDGETED_FILENAME: Final[str] = "ROADMAP.md"

#: The operator's stall threshold, as a LITERAL. Never compute this from the live
#: file: a derived ceiling ratchets to whatever the file grew to and guards
#: nothing. Raising it requires an operator decision, not a passing test.
ROADMAP_CHAR_LIMIT: Final[int] = 40_000

#: Anti-vacuity floor. A ceiling-only check reports GREEN on a truncated or
#: half-written index, which is the failure mode with the highest cost, so
#: anything this small is a defect rather than a comfortable margin.
ROADMAP_CHAR_FLOOR: Final[int] = 10_000

#: The settled rows retired into ``ROADMAP_ARCHIVE.md``: 4 by iteration 158
#: (143, 146, 155, 195) and 5 more by iteration 162 (138, 197, 198, 199, 200).
#: Each must now be ABSENT from the live index and PRESENT in the archive. Kept in
#: lockstep with ``SPEC_RETIRED_ROWS`` in ``tests/test_iter164_behavior.py``, which
#: spells the same 9 numbers independently and asserts the two agree -- so
#: extending one census alone is a red build rather than a silent divergence.
RETIRED_ROWS: Final[tuple[str, ...]] = (
    "143",
    "146",
    "155",
    "195",
    "138",
    "197",
    "198",
    "199",
    "200",
)

#: Archived YET deliberately kept in the live index (``test_iter115_behavior.py``
#: pins exactly one row #121 naming the deferred flag and ``type-arg``). The
#: counter-example that proves archive presence alone does not license deletion.
PINNED_ARCHIVED_ROW: Final[str] = "121"

#: Status-cell prefixes that mean a row is SETTLED -- the decision is made, so the
#: row's only remaining job is the historical record, and the record belongs in the
#: archive rather than in the live index. Matched as a PREFIX because a live status
#: carries its own trailing detail (``**SHIPPED -- iter-139** (factory iter 146).
#: The key was DELETED ...``), so equality would match nothing at all.
SETTLED_STATUS_PREFIXES: Final[tuple[str, ...]] = (
    "**SHIPPED",
    "**CLOSED",
    "**ABANDONED",
)

#: Settled rows deliberately PARKED in the live index, each for a stated reason.
#: #121 is exempt because ``test_iter115_behavior.py`` requires EXACTLY ONE live
#: row #121 -- it owns the deferred ``disallow_any_generics`` / ``type-arg``
#: record -- so retiring it reds that oracle. This is the index-side twin of
#: :data:`PINNED_ARCHIVED_ROW`, which states the same asymmetry from the archive
#: side. The allowlist is SELF-CLEANING: every member must still be BOTH live and
#: settled (see
#: :func:`test_every_pinned_settled_row_is_still_live_and_still_settled`), so a
#: stale exemption fails the build instead of quietly widening into a fail-open
#: dumping ground.
SETTLED_ROWS_PINNED_TO_INDEX: Final[tuple[str, ...]] = ("121",)

#: The literal assignment this module is not allowed to turn into an expression.
_LITERAL_LIMIT_ASSIGNMENT: Final[str] = "ROADMAP_CHAR_LIMIT: Final[int] = 40_000"


@dataclass(frozen=True)
class BudgetVerdict:
    """The outcome of one budget measurement.

    ``message`` is populated on BOTH branches on purpose: a consumer that only
    ever prints the failure text cannot tell a passing guard from a guard that
    forgot to measure, and the four actionable facts (file, measured chars,
    limit, headroom) are worth having in the green case too.
    """

    ok: bool
    chars: int
    message: str


def check_char_budget(
    text: str,
    *,
    name: str = BUDGETED_FILENAME,
    limit: int = ROADMAP_CHAR_LIMIT,
    floor: int = ROADMAP_CHAR_FLOOR,
) -> BudgetVerdict:
    """Measure ``text`` against the two-sided char budget.

    Pure and total: takes TEXT, never a path, so the detector can be fired at
    synthetic strings on both sides of both bounds without touching the tracked
    file it polices.

    Every message -- pass, over-ceiling and under-floor alike -- names the file,
    the measured char count, the limit and the headroom (``limit - chars``, so it
    goes negative on a breach). Numbers are rendered WITHOUT thousands
    separators, so a consumer can assert on ``str(ROADMAP_CHAR_LIMIT)`` directly
    instead of guessing at a formatting convention.
    """
    chars = len(text)
    headroom = limit - chars
    if chars > limit:
        return BudgetVerdict(
            ok=False,
            chars=chars,
            message=(
                f"{name} is {chars} chars, OVER the {limit}-char budget by "
                f"{-headroom} (headroom {headroom}). This file is re-read and "
                f"rewritten every iteration and has stalled the loop once at "
                f"200022 chars: retire settled rows into {ARCHIVE.name} "
                f"(archive first, then drop) or write terser rows."
            ),
        )
    if chars < floor:
        return BudgetVerdict(
            ok=False,
            chars=chars,
            message=(
                f"{name} is only {chars} chars, BELOW the {floor}-char "
                f"anti-vacuity floor (limit {limit}, headroom {headroom}). The "
                f"file looks truncated or half-written, which a ceiling-only "
                f"check would have passed silently."
            ),
        )
    return BudgetVerdict(
        ok=True,
        chars=chars,
        message=(
            f"{name} is {chars} chars, within the {limit}-char budget "
            f"(headroom {headroom}, floor {floor})."
        ),
    )


def count_index_rows(text: str, row: str) -> int:
    """Count live index rows for ``row`` -- ``ROADMAP.md``'s table shape only.

    Anchored at line start so a row NUMBER quoted inside another row's prose (as
    "pairs with row #138" routinely is) cannot be mistaken for the row itself.
    """
    return len(re.findall(rf"(?m)^\|\s*{re.escape(row)}\s*\|", text))


def count_archive_bullets(text: str, row: str) -> int:
    """Count archive entries for ``row`` -- ``ROADMAP_ARCHIVE.md``'s shape only.

    The archive stores retirements as ``- **#143 -- ...`` BULLETS, not table
    rows. Probing it with the index's ``| N |`` shape returns zero for rows that
    ARE archived, i.e. it fails OPEN and reads as "safe to delete"; that wrong
    query cost a wrong answer during this iteration's own PM stage, so the two
    shapes get two named functions.
    """
    return len(re.findall(rf"(?m)^- \*\*#{re.escape(row)} --", text))


def parse_index_rows(text: str) -> tuple[tuple[str, str], ...]:
    """Parse ``ROADMAP.md``'s index table into ``(row number, status cell)`` pairs.

    Pure, and takes TEXT rather than a path, so the brake built on it can be
    fired at synthetic tables instead of at the live file it polices.

    Shape rules, each a measured property of the live file rather than a guess.
    A row is a LINE-ANCHORED ``| N |`` -- anchored for the same reason
    :func:`count_index_rows` is, because row numbers are quoted inside other
    rows' prose all the time ("pairs with row #138"), and the Done-ledger tail
    quotes them again as ``- #168 `` bullets. The STATUS is the LAST
    ``|``-delimited cell: every live row has exactly 7 cells today, but reading
    the last one rather than index 6 keeps the parser correct if a column is ever
    added. A ``| N |`` line that yields a single cell has no status cell distinct
    from its own number, so it is a fragment and is skipped rather than read as a
    row whose status is its number.
    """
    rows: list[tuple[str, str]] = []
    for line in text.splitlines():
        if re.match(r"^\|\s*\d+\s*\|", line) is None:
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 2:
            continue
        rows.append((cells[0], cells[-1]))
    return tuple(rows)


def settled_rows_needing_retirement(text: str) -> tuple[str, ...]:
    """The retire-on-ship BRAKE: settled index rows that were never retired.

    Returns, in index order, the row numbers whose STATUS cell marks the work as
    settled (:data:`SETTLED_STATUS_PREFIXES`) and which are not on the
    :data:`SETTLED_ROWS_PINNED_TO_INDEX` allowlist. An empty tuple means the live
    index holds only genuinely-open work.

    WHY THIS IS AN ORACLE AND NOT A LINE IN A HEADER: "archive first, then drop"
    has lived only as PROSE in ``ROADMAP.md``'s own header, and prose asks every
    future contributor to REMEMBER. That control failed four iterations running,
    which is exactly how 5 settled rows and 3,443 chars of dead index text
    accumulated against a ceiling with 1,021 chars of headroom left. The ceiling
    in :func:`check_char_budget` bounds the LEVEL and has to be bought back by
    hand every time it is reached; this bounds the GROWTH RATE, so the index can
    only grow by open work and the buy-back stops recurring.

    It is deliberately a CENSUS and not a size heuristic: a "keep 2,500 chars
    spare" assertion would revert an innocent iteration for being unlucky, while
    this only ever fires on an act the author actually performed -- marking a row
    settled and leaving it parked.
    """
    return tuple(
        row
        for row, status in parse_index_rows(text)
        if status.startswith(SETTLED_STATUS_PREFIXES)
        and row not in SETTLED_ROWS_PINNED_TO_INDEX
    )


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Behavior 1 -- the detector is alive in both directions, on synthetic input.
# --------------------------------------------------------------------------- #


def test_the_budget_fires_one_char_over_the_limit() -> None:
    verdict = check_char_budget("x" * (ROADMAP_CHAR_LIMIT + 1))
    assert verdict.ok is False, "a file one char over budget must be reported BROKEN"
    assert verdict.chars == ROADMAP_CHAR_LIMIT + 1


def test_the_budget_passes_one_char_under_the_limit() -> None:
    verdict = check_char_budget("x" * (ROADMAP_CHAR_LIMIT - 1))
    assert verdict.ok is True, verdict.message
    assert verdict.chars == ROADMAP_CHAR_LIMIT - 1


def test_the_budget_passes_exactly_at_the_limit() -> None:
    """The ceiling is inclusive: ``<= limit`` is the contract, not ``< limit``."""
    assert check_char_budget("x" * ROADMAP_CHAR_LIMIT).ok is True


# --------------------------------------------------------------------------- #
# Behavior 2 -- the limit is the operator's literal, not a ratchet.
# --------------------------------------------------------------------------- #


def test_the_limit_is_the_operator_number() -> None:
    assert ROADMAP_CHAR_LIMIT == 40000
    assert ROADMAP_CHAR_FLOOR == 10000
    assert ROADMAP_CHAR_FLOOR < ROADMAP_CHAR_LIMIT


def test_the_limit_is_a_literal_never_derived_from_the_live_file() -> None:
    """Prove the constant is a bare literal by reading this module's own source.

    ``ROADMAP_CHAR_LIMIT == 40000`` above would still hold for
    ``len(ROADMAP.read_text()) + 3443``, which is the ratcheting shape this guard
    exists to forbid. Only the source text can distinguish the two.
    """
    source = _read(THIS_MODULE)
    assignments = [
        line
        for line in source.splitlines()
        if line.startswith("ROADMAP_CHAR_LIMIT") and "=" in line
    ]
    assert assignments == [_LITERAL_LIMIT_ASSIGNMENT], (
        "ROADMAP_CHAR_LIMIT must be assigned exactly once, as a literal; found "
        f"{assignments!r}"
    )


# --------------------------------------------------------------------------- #
# Behavior 3 + 4 -- the live, git-tracked file is inside BOTH bounds.
# --------------------------------------------------------------------------- #


def test_the_live_roadmap_is_inside_the_char_budget() -> None:
    verdict = check_char_budget(_read(ROADMAP))
    assert verdict.ok, verdict.message


def test_the_live_roadmap_clears_the_anti_vacuity_floor() -> None:
    """Asserted separately from the ceiling so a truncation cannot hide inside it."""
    chars = len(_read(ROADMAP))
    assert chars >= ROADMAP_CHAR_FLOOR, (
        f"{BUDGETED_FILENAME} is {chars} chars, below the "
        f"{ROADMAP_CHAR_FLOOR}-char floor -- truncated or half-written"
    )


def test_the_floor_fires_on_a_truncated_file() -> None:
    """The firing half of behavior 4: empty and near-empty text are BROKEN."""
    empty = check_char_budget("")
    assert empty.ok is False, "an empty ROADMAP.md must not pass a size budget"
    assert check_char_budget("x" * (ROADMAP_CHAR_FLOOR - 1)).ok is False
    assert check_char_budget("x" * ROADMAP_CHAR_FLOOR).ok is True


# --------------------------------------------------------------------------- #
# Behavior 5 -- the failure message is actionable.
# --------------------------------------------------------------------------- #


def test_the_breach_message_names_file_count_limit_and_headroom() -> None:
    over = ROADMAP_CHAR_LIMIT + 250
    verdict = check_char_budget("x" * over)
    assert verdict.ok is False
    for element in (
        BUDGETED_FILENAME,
        str(over),
        str(ROADMAP_CHAR_LIMIT),
        str(ROADMAP_CHAR_LIMIT - over),
    ):
        assert element in verdict.message, (
            f"breach message must name {element!r}; got {verdict.message!r}"
        )


def test_the_floor_message_names_the_floor_and_the_measured_count() -> None:
    verdict = check_char_budget("x" * 12)
    assert verdict.ok is False
    for element in (BUDGETED_FILENAME, "12", str(ROADMAP_CHAR_FLOOR)):
        assert element in verdict.message, verdict.message


# --------------------------------------------------------------------------- #
# Behavior 6 + 7 -- the trim that bought the headroom is a PAIR, and #121 is
# the counter-example proving archive presence is not a licence to delete.
# --------------------------------------------------------------------------- #


def test_both_budgeted_documents_are_present_and_non_trivial() -> None:
    """Anti-vacuity for behaviors 6-7: absent files would make every probe pass."""
    assert RETIRED_ROWS, "the retirement census must not be empty"
    for path in (ROADMAP, ARCHIVE):
        assert path.is_file(), f"{path} must exist in a fresh clone"
        assert len(_read(path)) > ROADMAP_CHAR_FLOOR, f"{path} looks truncated"


def test_retired_rows_left_the_index_and_landed_in_the_archive() -> None:
    roadmap, archive = _read(ROADMAP), _read(ARCHIVE)
    for row in RETIRED_ROWS:
        assert count_index_rows(roadmap, row) == 0, (
            f"row #{row} was retired in iteration 158 but is back in "
            f"{BUDGETED_FILENAME}; re-retire it or archive the new text"
        )
        assert count_archive_bullets(archive, row) == 1, (
            f"row #{row} must survive as exactly one '- **#{row} --' bullet in "
            f"{ARCHIVE.name}: never drop a row the archive does not hold"
        )


def test_row_121_is_archived_yet_deliberately_kept_in_the_index() -> None:
    """Archive presence is NOT sufficient for retirement -- the pinned exception.

    ``test_iter115_behavior.py`` asserts ``ROADMAP.md`` holds exactly one row
    #121 (it owns the deferred-flag / ``type-arg`` record), and #121 is ALSO in
    the archive. So a contributor who retires every archived row reds the build.
    Both halves are asserted here so the asymmetry is stated where the retirement
    census lives, not only where the flag record lives.
    """
    assert count_archive_bullets(_read(ARCHIVE), PINNED_ARCHIVED_ROW) == 1
    assert count_index_rows(_read(ROADMAP), PINNED_ARCHIVED_ROW) == 1, (
        f"row #{PINNED_ARCHIVED_ROW} is archived but must STAY in the live "
        "index: test_iter115_behavior.py requires exactly one such row"
    )
# --------------------------------------------------------------------------- #
# Behaviors 1-6 of the retire-on-ship brake -- the detector is fired TWO-SIDED on
# SYNTHETIC text (never on the live file it polices), then the live index is
# asserted clean, non-vacuously, with a self-cleaning allowlist.
# --------------------------------------------------------------------------- #

#: A synthetic index table, deliberately NOT the live file: an oracle proven only
#: against the subject it guards cannot be told from ``assert True`` the day that
#: subject changes. It carries one row of every shape that matters -- open
#: (``**QUEUED``), parked on a decision (``**BLOCKED``), the pinned exemption
#: (#121, settled), and one row per settled prefix -- plus the two decoy lines
#: that a naive line scan gets wrong: a Done-ledger bullet quoting a row number,
#: and prose quoting two more.
_SYNTHETIC_INDEX: Final[str] = """\
# Synthetic roadmap index -- fixture only.

| # | Enhancement | Layer | Value | Risk | Source | Status |
|---|---|---|---|---|---|---|
| 117 | open work | Packaging | Med | Low | scout A | **QUEUED** |
| 142 | parked on a decision | CLI | Med | Med | scout B | **BLOCKED -- needs an operator SPEC decision** |
| 121 | the pinned exemption | Typing | Med | Low | scout A | **SHIPPED -- iter-139** (factory iter 146). Detail follows. |
| 200 | shipped and left parked | CLI | High | Low | scout A | **SHIPPED iter 161** (factory iter 167). |
| 300 | closed without shipping | Docs | Low | Low | scout B | **CLOSED -- folded into #178** |
| 301 | abandoned on measurement | Docs | Low | Low | scout B | **ABANDONED -- the premise was false** |

- #200 -- a Done-ledger bullet, not a table row.
Prose that mentions row #200 and row 301 without being a table row at all.
"""

#: The row numbers :data:`_SYNTHETIC_INDEX` really contains, in index order.
_SYNTHETIC_ROW_NUMBERS: Final[tuple[str, ...]] = (
    "117",
    "142",
    "121",
    "200",
    "300",
    "301",
)


def test_the_brake_names_every_settled_row_left_parked_in_the_index() -> None:
    """The FIRING half: all three settled prefixes are caught, in index order."""
    assert settled_rows_needing_retirement(_SYNTHETIC_INDEX) == ("200", "300", "301")


def test_each_settled_prefix_fires_on_its_own() -> None:
    """Per-prefix, so one dead spelling cannot hide behind the other two."""
    for prefix in SETTLED_STATUS_PREFIXES:
        row = f"| 999 | x | L | Med | Low | scout | {prefix} -- detail |\n"
        assert settled_rows_needing_retirement(row) == ("999",), prefix


def test_the_brake_exempts_a_row_on_the_pinned_allowlist() -> None:
    """#121 is settled AND parsed AND settled-prefixed -- the ALLOWLIST excludes it.

    Asserting only ``"121" not in result`` would also pass if the parser had
    missed the row entirely, i.e. if the exemption were doing no work at all. So
    the row's presence and its settled status are asserted first, and the
    exclusion second.
    """
    parsed = dict(parse_index_rows(_SYNTHETIC_INDEX))
    assert parsed["121"].startswith(SETTLED_STATUS_PREFIXES), parsed["121"]
    assert "121" in SETTLED_ROWS_PINNED_TO_INDEX
    assert "121" not in settled_rows_needing_retirement(_SYNTHETIC_INDEX)


def test_the_brake_ignores_open_and_blocked_rows() -> None:
    """``**QUEUED`` and ``**BLOCKED`` are live work, not a missed retirement."""
    result = settled_rows_needing_retirement(_SYNTHETIC_INDEX)
    assert "117" not in result, "a QUEUED row is open work, not a missed retirement"
    assert "142" not in result, "a BLOCKED row is parked on a decision, not settled"


def test_the_row_parser_ignores_lines_that_are_not_index_rows() -> None:
    """Header, separator, ledger bullets and prose quoting row numbers are not rows.

    The two decoys are the ones a line scan gets wrong in opposite directions:
    ``- #200 -- ...`` is the Done-ledger shape (an unanchored search for the
    number would count it), and the prose line quotes ``#200`` and ``301`` again.
    Both would double-count rows the fixture already holds, so the assertion is
    on the EXACT sequence rather than on membership.
    """
    numbers = tuple(row for row, _status in parse_index_rows(_SYNTHETIC_INDEX))
    assert numbers == _SYNTHETIC_ROW_NUMBERS, (
        "the parser must find exactly the 6 fixture rows -- the Done-ledger "
        f"bullet and the prose lines are not rows; got {numbers!r}"
    )


def test_the_row_parser_skips_a_single_cell_fragment() -> None:
    """``| 143 |`` alone has no status cell of its own, so it is not a row."""
    assert parse_index_rows("| 143 |\n") == ()
    assert settled_rows_needing_retirement("| 143 |\n") == ()


def test_an_empty_document_yields_no_rows_and_no_findings() -> None:
    """Total on the degenerate input -- and see the anti-vacuity test below for why
    an empty parse must never be able to satisfy the live-tree property."""
    assert parse_index_rows("") == ()
    assert settled_rows_needing_retirement("") == ()


def test_the_pinned_allowlist_is_non_empty_and_states_its_sole_member() -> None:
    """The allowlist is an explicit, enumerated exception -- never a wildcard."""
    assert SETTLED_ROWS_PINNED_TO_INDEX == ("121",)
    assert PINNED_ARCHIVED_ROW in SETTLED_ROWS_PINNED_TO_INDEX, (
        "the archive-side pin and the index-side allowlist must name the same "
        "row: they are two halves of one asymmetry"
    )


def test_the_live_index_holds_no_settled_row_that_was_never_retired() -> None:
    """The live property this iteration installs: retire on ship, enforced."""
    parked = settled_rows_needing_retirement(_read(ROADMAP))
    assert parked == (), (
        f"{BUDGETED_FILENAME} still holds settled index row(s) {list(parked)}: a "
        "row whose STATUS says SHIPPED/CLOSED/ABANDONED belongs in "
        f"{ARCHIVE.name} (archive first, then drop, then extend RETIRED_ROWS). "
        "If one must stay, add it to SETTLED_ROWS_PINNED_TO_INDEX with the "
        "reason -- as row #121 is."
    )


def test_the_live_row_parser_is_not_vacuous() -> None:
    """Anti-vacuity for the live property above.

    ``settled_rows_needing_retirement(text) == ()`` passes trivially on a parser
    that finds nothing -- a renamed column, a reformatted table, a truncated file
    -- which is the same fail-open shape the char FLOOR exists to stop. So the
    live index must parse to a substantial number of rows, and every finding must
    be one of the rows actually parsed.
    """
    roadmap = _read(ROADMAP)
    numbers = [row for row, _status in parse_index_rows(roadmap)]
    assert len(numbers) >= 20, (
        f"only {len(numbers)} index rows parsed out of {BUDGETED_FILENAME}; the "
        "table shape changed and this census is now blind"
    )
    assert set(settled_rows_needing_retirement(roadmap)) <= set(numbers)
    assert len(set(numbers)) == len(numbers), f"duplicate index rows: {numbers!r}"


def test_every_pinned_settled_row_is_still_live_and_still_settled() -> None:
    """SELF-CLEANING allowlist: a stale exemption is a failure, not a free pass.

    An allowlist nobody prunes becomes a fail-open dumping ground -- the exact
    end state this brake exists to prevent. So each member must still be BOTH
    present in the live index (else the exemption is dead text) AND carry a
    settled status (else it is exempting a row the brake would never have
    flagged, which hides a wrong entry).
    """
    roadmap = _read(ROADMAP)
    statuses = dict(parse_index_rows(roadmap))
    for row in SETTLED_ROWS_PINNED_TO_INDEX:
        assert count_index_rows(roadmap, row) == 1, (
            f"row #{row} is on SETTLED_ROWS_PINNED_TO_INDEX but has "
            f"{count_index_rows(roadmap, row)} live index rows -- drop the "
            "stale exemption"
        )
        assert statuses[row].startswith(SETTLED_STATUS_PREFIXES), (
            f"row #{row} is exempted from retirement but its status is not "
            f"settled ({statuses[row][:60]!r}); the exemption is wrong"
        )
