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
The budget was bought back by retiring 4 settled index rows into
``ROADMAP_ARCHIVE.md``, and the file's own rule is "never drop a row without
first confirming the archive has it". A trim is therefore only correct as a PAIR
(absent here AND present there), which is a property no single-file check can
see. Row #121 is the pinned counter-example that keeps the rule honest: it is
BOTH archived AND deliberately retained in the live index, because
``test_iter115_behavior.py`` requires exactly one row #121 there. So archive
presence is NOT a licence to delete -- a retirement needs a test census -- and
scout B's slate for this very iteration got that wrong. Pinning #121 here means
the next contributor's wrong retirement is a red build, not a lost oracle.

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

#: The 4 settled rows retired into ``ROADMAP_ARCHIVE.md`` by iteration 158. Each
#: must now be ABSENT from the live index and PRESENT in the archive.
RETIRED_ROWS: Final[tuple[str, ...]] = ("143", "146", "155", "195")

#: Archived YET deliberately kept in the live index (``test_iter115_behavior.py``
#: pins exactly one row #121 naming the deferred flag and ``type-arg``). The
#: counter-example that proves archive presence alone does not license deletion.
PINNED_ARCHIVED_ROW: Final[str] = "121"

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
