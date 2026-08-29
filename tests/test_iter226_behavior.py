"""Black-box behavior tests for state-dir iteration 248 (ships as ``foundry iter 248``):
A SECOND SETTLED DONE-LEDGER BATCH IS RELOCATED TO THE ARCHIVE, BUYING BACK HEADROOM.

Feature under test (``pm.md`` "Feature"): relocate the settled Done-ledger bullets from
``ROADMAP.md`` into ``ROADMAP_ARCHIVE.md`` VERBATIM, leave behind the rows existing oracles
pin to ``ROADMAP.md``, and restore at least 4,000 chars of headroom so the next
iteration can record itself without redding the build.

WHY IT MATTERS, MEASURED. ``ROADMAP.md`` carries a hard 40,000-char ceiling
(``tests/test_roadmap_size_budget.py``) and iteration 214 contracts a 4,000-char
headroom FLOOR under it, so the appendable budget at the pre-move size of 35,514 chars
was 486 chars. That is what reverted a reviewer-APPROVED, tester-green
iteration 247 -- roadmap bookkeeping alone, on the only failing assertion in 5,222 tests.
This iteration is the second relocation batch under the conservation guard that iteration 214
shipped for exactly this purpose.

SPEC AMBIGUITY, REPORTED AS PM FEEDBACK (see ``tester.md``). ``pm.md`` also says to "extend
``RELOCATION_ANCHOR`` with the rows added since the first relocation". That instruction is
UNNECESSARY and obeying it would RED an already-shipped module: all 10 relocated rows are
ALREADY anchor members, so conservation holds untouched, while
``tests/test_roadmap_ledger_conservation.py::test_the_anchor_is_the_measured_pre_relocation_census``
pins ``len(RELOCATION_ANCHOR) == 81``. This module therefore tests the INVARIANT the anchor
exists to protect (conservation over the pair) and asserts the anchor already covers the moved
rows -- never that the constant grew.

MODULE NAME -- DERIVED FROM THE REPO, never from the state-dir number. ``git ls-files tests``
holds 230 entries whose highest ``test_iterNN_behavior.py`` is **225**, so 226 is the next free
name, and ``git cat-file -e HEAD:tests/test_iter226_behavior.py`` FAILED
(``path ... does not exist in 'HEAD'``) before the first byte was written. Naming a module from
the state-dir counter (248 here) is what overwrote a shipped 18,786-byte oracle in state-dir 186.

ISOLATION CONTRACT (honored, no exception). Every assertion below is derived from this
iteration's ``pm.md``, from the two tracked Markdown documents themselves, and from the
conventions of the existing modules under ``tests/`` (``test_iter214_behavior.py`` supplies the
digest-pin and monotone-floor idioms; ``test_roadmap_size_budget.py`` and
``test_roadmap_ledger_conservation.py`` supply the imported helpers). **No file under ``src/``
was read, no ``git diff`` was inspected, and neither ``engineer.md`` nor ``reviewer.md`` was
opened.**

OFFLINE, DETERMINISTIC, FRESH-CLONE SAFE. Every assertion reads only TRACKED text at paths
resolved from ``__file__``: no network, no subprocess, no ``git`` invocation at test time, no
clock, and no dependence on gitignored loop state (the iter-154 trap). The pre-move ledger text
cannot be re-derived from a shipped tree -- it no longer lives in ``ROADMAP.md`` -- so the moved
slice is pinned by DIGEST, which fixes content **and order** in one constant, where a per-row set
comparison would catch neither a rewording nor a reordering.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Final

from tests.test_iter214_behavior import (
    CHAR_LIMIT as ITER214_CHAR_LIMIT,
    MIN_HEADROOM as ITER214_MIN_HEADROOM,
    RELOCATED_ROWS as FIRST_BATCH_ROWS,
)
from tests.test_roadmap_ledger_conservation import (
    LEDGER_ROWS_PINNED_TO_ROADMAP,
    RELOCATION_ANCHOR,
    check_ledger_conservation,
    ledger_rows,
)
from tests.test_roadmap_size_budget import (
    ROADMAP_CHAR_LIMIT,
    check_char_budget,
    count_archive_bullets,
    count_index_rows,
    settled_rows_needing_retirement,
)

REPO: Final[Path] = Path(__file__).resolve().parents[1]
ROADMAP: Final[Path] = REPO / "ROADMAP.md"
ARCHIVE: Final[Path] = REPO / "ROADMAP_ARCHIVE.md"

#: A Done-ledger SHIP RECORD, LINE-ANCHORED -- the same shape the shipped conservation guard
#: matches. Row numbers are quoted inside other rows' prose constantly ("pairs with row #138"),
#: so an unanchored probe counts prose as records, and the anchor also keeps the archive's
#: ``- **#N -- `` RETIREMENT bullets out of this census.
LEDGER_BULLET: Final[re.Pattern[str]] = re.compile(r"(?m)^- #(\d+) ")

#: The 10 rows this iteration relocated, in the order they stood in the pre-move ledger.
#: Measured from ``git show HEAD:ROADMAP.md`` against the working tree before a byte of this
#: module was written; recorded here because the order is NOT numeric (it runs ... 207, 196,
#: 208 ...) and a reordering must fail.
SECOND_BATCH_ROWS: Final[tuple[str, ...]] = ('198', '202', '203', '204', '207', '196', '208', '209', '206', '211')

#: SHA-256 of the 10 relocated bullets joined by ``chr(10)``, measured from the pre-move
#: ``ROADMAP.md`` blob and re-measured on the post-move archive (identical). Fixes content AND
#: order in one constant, so a reworded, re-wrapped, truncated or reordered bullet all fail.
SECOND_BATCH_SHA256: Final[str] = '42dfff7ccdbf3fbf5970ba9b0ab7f62b9986b8668dc89a833d0b98f16a839b5a'

#: Endpoint pins, EXTRACTED programmatically from the archive (never retyped), so a digest
#: mismatch can be read by a human without re-deriving the whole slice.
OLDEST_RELOCATED: Final[str] = '- #198 Reclaim ROADMAP.md char headroom: retired 5 settled... (iter 162, factory iter 168)'
NEWEST_RELOCATED: Final[str] = '- #211 .gitignore + make clean cover the... (iter 174, factory iter 178)'

#: The measured mass the relocation removed from ``ROADMAP.md``: the sum of the 10 bullet
#: lines plus one newline each. This is the headroom the iteration bought back, and it is what
#: makes "the relocation was not cosmetic" a measurement rather than an impression.
SECOND_BATCH_MASS: Final[int] = 865

#: The one heading in ``ROADMAP_ARCHIVE.md`` that owns relocated ship records, quoted verbatim.
#: Two batches under two headings would still conserve every row while making the archive
#: unreadable, so the single-heading claim is asserted rather than assumed.
ARCHIVE_LEDGER_HEADING: Final[str] = '## Relocated Done-ledger lines (SHIP RECORDS, not retirement bullets)'

#: Monotone FLOORS, disclosed as floors and never as totals: the archive's relocated ledger only
#: grows, and ``ROADMAP.md``'s ledger gains a row every ship. Pinning equality here would red an
#: innocent later iteration for shipping, which is the failure mode iteration 247 already paid.
ARCHIVE_LEDGER_BULLETS_FLOOR: Final[int] = 50
ROADMAP_LEDGER_BULLETS_FLOOR: Final[int] = 41

#: The 40,000-char ceiling and the 4,000-char headroom floor, pinned as LITERALS here and
#: cross-checked against the two sibling modules that own them. A future contributor who
#: WEAKENS either number to make a fat append fit reds this module, which is the point: the
#: whole value of this iteration is the floor, so the floor must not be quietly negotiable.
CHAR_LIMIT: Final[int] = 40000
MIN_HEADROOM: Final[int] = 4000

#: Retirement-bullet counts for the relocated rows, measured on the archive AFTER the move.
#: Relocating a ship record must not touch the separate ``- **#N -- `` retirement census; rows
#: absent from this mapping had a count of zero and must still.
SECOND_BATCH_RETIREMENT_COUNTS: Final[dict[str, int]] = {'198': 1, '196': 1, '208': 1, '209': 1, '206': 1, '211': 1}

#: ``tests/test_roadmap_size_budget.py`` pins row #121 as archived-yet-deliberately-live in the
#: index. It is a FIRST-batch row, so this iteration must not have disturbed it.
PINNED_ARCHIVED_INDEX_ROW: Final[str] = "121"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def bullet_lines(text: str, rows: tuple[str, ...]) -> tuple[str, ...]:
    """Every ledger bullet LINE in ``text`` whose row number is in ``rows``, in file order.

    Line-anchored and whole-line, so the returned strings are exactly what a digest can be
    taken over. Kept separate from :func:`ledger_rows` (which returns row NUMBERS) because
    verbatimness is a claim about the TEXT, and a row-number census cannot make it.
    """
    out: list[str] = []
    for line in text.splitlines():
        match = LEDGER_BULLET.match(line)
        if match is not None and match.group(1) in rows:
            out.append(line)
    return tuple(out)


def appendable_budget(text: str, limit: int = CHAR_LIMIT, floor: int = MIN_HEADROOM) -> int:
    """Chars a contributor may APPEND to ``text`` before the headroom floor fires.

    This is the number that actually governs an iteration -- headroom alone reads as
    comfortable at 5,351 chars while only 1,351 are spendable -- so it is
    computed once here and reported in the failure message rather than re-derived by eye at
    each call site.
    """
    return limit - floor - len(text)


def heading_owning(text: str, line: str) -> str | None:
    """The nearest preceding ``#``-prefixed heading for ``line``, or ``None`` if unheaded."""
    current: str | None = None
    for candidate in text.splitlines():
        if candidate.startswith("#"):
            current = candidate.strip()
        if candidate == line:
            return current
    raise AssertionError(f"line not found in text: {line!r}")


# ---------------------------------------------------------------------------
# Behavior 1 -- the relocation happened: the batch left ROADMAP.md and landed in the archive.
# ---------------------------------------------------------------------------


def test_b1_every_relocated_row_left_the_roadmap_ledger() -> None:
    still_there = tuple(r for r in SECOND_BATCH_ROWS if r in ledger_rows(_read(ROADMAP)))
    assert still_there == (), f"rows never left ROADMAP.md: {still_there}"


def test_b1_every_relocated_row_is_recorded_in_the_archive_exactly_once() -> None:
    archive_rows = ledger_rows(_read(ARCHIVE))
    mine = tuple(r for r in archive_rows if r in SECOND_BATCH_ROWS)
    assert sorted(mine, key=int) == sorted(SECOND_BATCH_ROWS, key=int), (
        f"archive ledger does not hold exactly the relocated batch: {mine}"
    )
    assert len(archive_rows) == len(set(archive_rows)), (
        "a ship record is recorded twice in the archive ledger"
    )


def test_b1_the_batch_is_exactly_ten_rows_and_disjoint_from_the_first_batch() -> None:
    assert len(SECOND_BATCH_ROWS) == 10
    assert len(set(SECOND_BATCH_ROWS)) == 10, "a row is named twice in the batch"
    assert set(SECOND_BATCH_ROWS).isdisjoint(set(FIRST_BATCH_ROWS)), (
        "a row relocated by iteration 214 is claimed again: "
        f"{sorted(set(SECOND_BATCH_ROWS) & set(FIRST_BATCH_ROWS), key=int)}"
    )


def test_b1_the_live_ledgers_are_non_vacuous_so_the_absence_check_can_fail() -> None:
    # An absence claim over an EMPTY census is vacuously true, which is the fail-open shape
    # this repo has paid for before. Both sides are therefore floored.
    assert len(ledger_rows(_read(ROADMAP))) >= ROADMAP_LEDGER_BULLETS_FLOOR
    assert len(ledger_rows(_read(ARCHIVE))) >= ARCHIVE_LEDGER_BULLETS_FLOOR


# ---------------------------------------------------------------------------
# Behavior 2 -- VERBATIM: content, order, placement and shape all survive the move.
# ---------------------------------------------------------------------------


def test_b2_the_relocated_bullets_are_byte_identical_to_the_pre_move_text() -> None:
    bullets = bullet_lines(_read(ARCHIVE), SECOND_BATCH_ROWS)
    digest = hashlib.sha256("\n".join(bullets).encode("utf-8")).hexdigest()
    assert digest == SECOND_BATCH_SHA256, (
        "the relocated bullets are not byte-identical (or not in pre-move order) -- "
        f"measured {digest}, pinned {SECOND_BATCH_SHA256}"
    )


def test_b2_the_endpoints_are_quoted_verbatim_including_the_iteration_suffix() -> None:
    bullets = bullet_lines(_read(ARCHIVE), SECOND_BATCH_ROWS)
    assert bullets[0] == OLDEST_RELOCATED
    assert bullets[-1] == NEWEST_RELOCATED


def test_b2_the_batch_order_matches_the_pre_move_ledger_order_not_a_sort() -> None:
    bullets = bullet_lines(_read(ARCHIVE), SECOND_BATCH_ROWS)
    observed = tuple(LEDGER_BULLET.match(b).group(1) for b in bullets)  # type: ignore[union-attr]
    assert observed == SECOND_BATCH_ROWS, f"order changed in the move: {observed}"
    assert observed != tuple(sorted(SECOND_BATCH_ROWS, key=int)), (
        "the pre-move order was NOT numeric, so an order test that a sort would also pass "
        "proves nothing -- this assertion keeps the previous one honest"
    )


def test_b2_all_relocated_bullets_sit_under_the_one_relocated_ledger_heading() -> None:
    archive = _read(ARCHIVE)
    owning = {heading_owning(archive, b) for b in bullet_lines(archive, SECOND_BATCH_ROWS)}
    assert owning == {ARCHIVE_LEDGER_HEADING}, (
        f"relocated bullets are split across headings: {sorted(map(str, owning))}"
    )


def test_b2_both_batches_share_one_heading_with_no_heading_between_them() -> None:
    # A second batch appended under its own heading would still conserve every row while
    # fragmenting the archive; this is the structural half of "verbatim, under one heading".
    archive = _read(ARCHIVE)
    lines = archive.splitlines()
    ledger_idx = [i for i, l in enumerate(lines) if LEDGER_BULLET.match(l)]
    assert ledger_idx, "the archive holds no ledger bullets at all"
    between = [l for l in lines[ledger_idx[0] : ledger_idx[-1] + 1] if l.startswith("#")]
    assert between == [], f"a heading splits the relocated ledger: {between}"


def test_b2_no_relocated_bullet_carries_a_pipe_so_none_can_parse_as_a_table_row() -> None:
    offenders = tuple(b for b in bullet_lines(_read(ARCHIVE), SECOND_BATCH_ROWS) if "|" in b)
    assert offenders == (), f"pipe in a relocated bullet: {offenders}"


# ---------------------------------------------------------------------------
# Behavior 3 -- the pins the spec says to leave behind are still in ROADMAP.md.
# ---------------------------------------------------------------------------


def test_b3_every_pinned_ledger_row_is_still_recorded_in_the_roadmap() -> None:
    rows = ledger_rows(_read(ROADMAP))
    for row, reason in LEDGER_ROWS_PINNED_TO_ROADMAP.items():
        assert row in rows, f"pinned ledger row #{row} was relocated -- {reason}"
        assert row not in SECOND_BATCH_ROWS, f"row #{row} is pinned yet claimed as moved"


def test_b3_no_pinned_ledger_row_leaked_into_the_archive_ledger() -> None:
    archive_rows = ledger_rows(_read(ARCHIVE))
    leaked = tuple(r for r in LEDGER_ROWS_PINNED_TO_ROADMAP if r in archive_rows)
    assert leaked == (), f"pinned row recorded in the archive ledger: {leaked}"


def test_b3_the_archived_yet_live_index_row_is_untouched_by_this_batch() -> None:
    # Row #121 is archived AND deliberately kept as a live index row. It is a first-batch
    # row, so a second batch that "tidied" it would red test_roadmap_size_budget.py.
    assert count_index_rows(_read(ROADMAP), PINNED_ARCHIVED_INDEX_ROW) == 1
    assert PINNED_ARCHIVED_INDEX_ROW not in SECOND_BATCH_ROWS


# ---------------------------------------------------------------------------
# Behavior 4 -- CONSERVATION: no ship record was lost or duplicated by the move.
# ---------------------------------------------------------------------------


def test_b4_the_shipped_conservation_guard_is_green_on_the_live_pair() -> None:
    verdict = check_ledger_conservation(_read(ROADMAP), _read(ARCHIVE), RELOCATION_ANCHOR)
    assert verdict.ok, verdict.message


def test_b4_no_row_number_is_recorded_in_both_documents() -> None:
    both = set(ledger_rows(_read(ROADMAP))) & set(ledger_rows(_read(ARCHIVE)))
    assert both == set(), f"recorded twice across the pair: {sorted(both, key=int)}"


def test_b4_the_anchor_already_covers_the_batch_so_it_needed_no_extension() -> None:
    # pm.md ordered RELOCATION_ANCHOR extended "with the rows added since the first
    # relocation". Measured: every row in this batch is ALREADY a member, so the invariant
    # holds untouched -- and the anchor's own oracle pins its length at 81, so obeying the
    # instruction literally would have RED an already-shipped module. Reported in tester.md.
    missing = tuple(r for r in SECOND_BATCH_ROWS if r not in RELOCATION_ANCHOR)
    assert missing == (), (
        f"rows outside the anchor were relocated, so the anchor DOES need extending: {missing}"
    )


def test_b4_the_anchor_is_a_monotone_floor_that_still_covers_both_batches() -> None:
    covered = set(FIRST_BATCH_ROWS) | set(SECOND_BATCH_ROWS)
    assert covered <= set(RELOCATION_ANCHOR)
    assert len(covered) == len(FIRST_BATCH_ROWS) + len(SECOND_BATCH_ROWS)


# ---------------------------------------------------------------------------
# Behavior 5 -- the separate RETIREMENT census is unmoved by a ledger relocation.
# ---------------------------------------------------------------------------


def test_b5_every_relocated_row_keeps_its_exact_retirement_count() -> None:
    archive = _read(ARCHIVE)
    live = {
        row: count_archive_bullets(archive, row)
        for row in SECOND_BATCH_ROWS
        if count_archive_bullets(archive, row)
    }
    assert live == SECOND_BATCH_RETIREMENT_COUNTS, (
        "relocating a ship record changed the retirement census: "
        f"{sorted(set(live.items()) ^ set(SECOND_BATCH_RETIREMENT_COUNTS.items()))}"
    )


def test_b5_the_two_bullet_shapes_are_distinguishable_so_the_census_is_meaningful() -> None:
    ship = "- #77 shipped something (iter 1, factory iter 1)"
    retirement = "- **#77 -- retired: reason"
    assert count_archive_bullets(ship, "77") == 0
    assert count_archive_bullets(retirement, "77") == 1
    assert ledger_rows(ship) == ("77",)
    assert ledger_rows(retirement) == ()


# ---------------------------------------------------------------------------
# Behavior 6 -- HEADROOM: the point of the iteration, measured against both constants.
# ---------------------------------------------------------------------------


def test_b6_the_roadmap_is_inside_its_char_budget() -> None:
    verdict = check_char_budget(_read(ROADMAP))
    assert verdict.ok, verdict.message


def test_b6_the_relocation_bought_back_at_least_the_contracted_headroom() -> None:
    chars = len(_read(ROADMAP))
    headroom = CHAR_LIMIT - chars
    assert headroom >= MIN_HEADROOM, (
        f"ROADMAP.md is {chars:,} chars, leaving {headroom:,} of headroom against a "
        f"contracted floor of {MIN_HEADROOM:,} -- relocate more settled ledger rows"
    )


def test_b6_the_removed_mass_is_the_headroom_the_iteration_bought() -> None:
    # Non-cosmetic by measurement: the batch is real text, and its mass is the delta the
    # relocation contributed. Pinned so a future edit that shrinks the bullets to fake a
    # bigger win is visible.
    bullets = bullet_lines(_read(ARCHIVE), SECOND_BATCH_ROWS)
    mass = sum(len(b) + 1 for b in bullets)
    assert mass == SECOND_BATCH_MASS, f"batch mass changed: {mass} vs {SECOND_BATCH_MASS}"
    assert mass > 0


def test_b6_the_appendable_budget_is_positive_and_is_headroom_minus_the_floor() -> None:
    text = _read(ROADMAP)
    budget = appendable_budget(text)
    assert budget == CHAR_LIMIT - MIN_HEADROOM - len(text)
    assert budget > 0, (
        f"nothing can be appended to ROADMAP.md: {len(text):,} chars against a "
        f"{CHAR_LIMIT:,} ceiling with a {MIN_HEADROOM:,} floor"
    )


def test_b6_the_two_constants_agree_with_the_modules_that_own_them() -> None:
    # A future contributor who weakens the ceiling or the floor to make a fat append fit
    # reds THIS module too, so the floor cannot be quietly renegotiated in one file.
    assert CHAR_LIMIT == ROADMAP_CHAR_LIMIT == ITER214_CHAR_LIMIT == 40000
    assert MIN_HEADROOM == ITER214_MIN_HEADROOM == 4000


# ---------------------------------------------------------------------------
# Behavior 7 -- the surrounding roadmap invariants are undisturbed.
# ---------------------------------------------------------------------------


def test_b7_the_settled_row_brake_still_reports_a_clean_index() -> None:
    assert settled_rows_needing_retirement(_read(ROADMAP)) == ()


def test_b7_the_roadmap_still_holds_exactly_one_table() -> None:
    bodies: list[int] = []
    run = 0
    for line in _read(ROADMAP).splitlines():
        if line.startswith("|"):
            run += 1
        elif run:
            bodies.append(run)
            run = 0
    if run:
        bodies.append(run)
    assert len(bodies) == 1 and bodies[0] >= 20, bodies


def test_b7_the_relocation_touched_no_index_row() -> None:
    # A ledger relocation is a LEDGER edit. If a moved row also had a live index row, the
    # move would have silently retired open work -- so no batch row may appear in the index.
    roadmap = _read(ROADMAP)
    indexed = tuple(r for r in SECOND_BATCH_ROWS if count_index_rows(roadmap, r))
    assert indexed == (), f"a relocated row still has a live index row: {indexed}"


# ---------------------------------------------------------------------------
# Two-sided fire tests -- every check above must be able to FAIL.
# ---------------------------------------------------------------------------

_SYNTHETIC_ROADMAP: Final[str] = (
    "## Done ledger\n"
    "- #300 kept a row (iter 1, factory iter 1)\n"
    "- #198 Reclaim ROADMAP.md char headroom: retired 5 settled... (iter 162, factory iter 168)\n"
)
_SYNTHETIC_ARCHIVE: Final[str] = (
    "## Relocated Done-ledger lines (SHIP RECORDS, not retirement bullets)\n"
    "- #301 moved a row (iter 2, factory iter 2)\n"
)


def test_fire_the_absence_check_catches_a_relocated_row_still_in_the_roadmap() -> None:
    still_there = tuple(r for r in SECOND_BATCH_ROWS if r in ledger_rows(_SYNTHETIC_ROADMAP))
    assert still_there == ("198",), still_there


def test_fire_the_digest_catches_a_reworded_bullet() -> None:
    bullets = list(bullet_lines(_read(ARCHIVE), SECOND_BATCH_ROWS))
    bullets[0] = bullets[0].replace("Reclaim", "Reclaimed")
    tampered = hashlib.sha256("\n".join(bullets).encode("utf-8")).hexdigest()
    assert tampered != SECOND_BATCH_SHA256


def test_fire_the_digest_catches_a_reordered_batch() -> None:
    bullets = list(bullet_lines(_read(ARCHIVE), SECOND_BATCH_ROWS))
    bullets.reverse()
    reordered = hashlib.sha256("\n".join(bullets).encode("utf-8")).hexdigest()
    assert reordered != SECOND_BATCH_SHA256, (
        "the digest cannot see order, so the verbatim claim is weaker than advertised"
    )


def test_fire_the_digest_catches_a_dropped_bullet() -> None:
    bullets = list(bullet_lines(_read(ARCHIVE), SECOND_BATCH_ROWS))[:-1]
    truncated = hashlib.sha256("\n".join(bullets).encode("utf-8")).hexdigest()
    assert truncated != SECOND_BATCH_SHA256


def test_fire_the_conservation_guard_catches_a_record_dropped_by_the_move() -> None:
    anchor = ("300", "301", "302")
    verdict = check_ledger_conservation(_SYNTHETIC_ROADMAP, _SYNTHETIC_ARCHIVE, anchor)
    assert not verdict.ok
    assert "302" in verdict.message


def test_fire_the_conservation_guard_catches_a_record_in_both_documents() -> None:
    anchor = ("300", "301")
    doubled = _SYNTHETIC_ARCHIVE + "- #300 kept a row (iter 1, factory iter 1)\n"
    verdict = check_ledger_conservation(_SYNTHETIC_ROADMAP, doubled, anchor)
    assert not verdict.ok
    assert "300" in verdict.message


def test_fire_the_appendable_budget_goes_negative_before_the_ceiling_is_reached() -> None:
    # The floor must bite BELOW the ceiling, or the guard is decorative.
    at_floor = "x" * (CHAR_LIMIT - MIN_HEADROOM)
    assert appendable_budget(at_floor) == 0
    assert appendable_budget(at_floor + "x") == -1
    assert check_char_budget(at_floor).ok, (
        "the appendable budget must run out while the char budget is still green -- "
        "otherwise the headroom floor adds nothing over the ceiling"
    )


def test_fire_the_heading_owner_reports_none_for_an_unheaded_line() -> None:
    assert heading_owning("- #400 orphan (iter 1, factory iter 1)\n", "- #400 orphan (iter 1, factory iter 1)") is None
    assert heading_owning("## H\n- #400 x\n", "- #400 x") == "## H"


def test_fire_the_bullet_matcher_is_line_anchored_and_shape_aware() -> None:
    assert bullet_lines("prose that pairs with row #198 inline\n", SECOND_BATCH_ROWS) == ()
    assert bullet_lines("- **#198 -- retired: reason\n", SECOND_BATCH_ROWS) == ()
    assert len(bullet_lines(_SYNTHETIC_ROADMAP, SECOND_BATCH_ROWS)) == 1
