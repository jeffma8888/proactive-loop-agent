"""Independent second opinion on the published floor raise that pays ROADMAP row #282.

MODULE NAME, derived from the REPO and never from the state-dir counter (the 2026-08-19
operator pin). The foundry state dir is ``iter-421`` while the shipping tag is ``foundry
iter 307``: the two counters differ, and that offset is not arithmetic anyone may
reuse. Derived the mandated way instead -- ``git ls-files tests`` tops out at
``test_iter264_behavior.py``, +1 = ``265``, and ``git cat-file -e
HEAD:tests/test_iter265_behavior.py`` FAILED (``path ... does not exist in 'HEAD'``)
before the first byte was written, with no worktree file at that path either. The module
was then ``git add -N``-ed BEFORE any instrument here measured the tree, because
:func:`guard.tracked_text_sources` walks ``git ls-files`` and reads the WORKTREE: an
untracked module would sit outside the very census this file reasons about.

NO FLOOR NUMBER IS SPELLED ANYWHERE IN THIS MODULE, in either spelling, and that is a
correctness requirement rather than a style rule. The census in
``tests/test_readme_and_ci_contract.py`` reports any tracked file that claims the live
floor while not being one of the eight declared carriers, and this module is tracked. So
every number below is DERIVED at run time through ``guard.published_floor()``,
``guard.floor_token()`` and ``guard.floor_tokens()``. A literal here would make the
oracle its own ninth carrier and red a public build the moment it shipped.

WHY THIS MODULE COLLECTS TWENTY ITEMS AND WHY THAT IS AFFORDABLE NOW. This is the first
iteration in four in which the tester's mandated new module can exist at all. Measured on
the tree under test with ``make readme-headroom`` before this file was written:
``live=6008 binding_at=6099 binding_headroom=90``, against
``tests/test_iter263_behavior.py``'s ``MIN_BINDING_HEADROOM``, which is asserted over a
live collection with no provenance gate and therefore prices every collected item
anywhere in the suite. Twenty items leave that gauge far above its floor; the three
preceding iterations had a budget of zero and their testers could not pay duty 1 at all.

WHAT IS DELIBERATELY NOT RE-ASSERTED HERE, because restating an owned expectation is not
free -- it multiplies the sites a later raise must re-key, which is the exact defect this
row existed to clear:

* The live-collection arm of Expected Behavior 2. ``tests/test_iter263_behavior.py``'s
  ``test_b6`` and ``tests/test_iter250_behavior.py``'s ``test_b2`` already spawn a
  ``--collect-only`` subprocess against the whole suite; a third copy would add tens of
  seconds to every run to re-measure a number two shipped oracles already gate. The
  window arithmetic the raise OPENS is graded here as a pure function instead, and the
  live figure is reported out of band in ``tester.md``.
* Expected Behavior 3's "each carrier claims the live floor and no higher one".
  ``tests/test_iter250_behavior.py``'s ``test_b11``/``test_b12`` own both sides,
  parametrized over the same tuple. This module grades the arm nothing owns: that the
  census is NON-VACUOUS per carrier (Expected Behavior 10).
* Expected Behaviors 8 and 9 -- the ``ROADMAP.md`` char budget and the "no ``src/``, no
  lockfile" property. The first is owned three times over
  (``tests/test_roadmap_size_budget.py``, ``tests/test_iter214_behavior.py``,
  ``tests/test_iter241_behavior.py``) and the second is the worktree-keyed
  ``git status --porcelain`` shape factory iter 304 deliberately RETIRED from ``tests/``:
  re-adding it would re-create a veto that reds on every later commit. Both are verified
  out of band and reported in ``tester.md``.

ISOLATION CONTRACT (honored, no exception). Every assertion is derived from this
iteration's ``pm.md`` Expected Behaviors 1-10, from the two tracked Markdown documents,
from the README, and from the conventions of the existing modules under ``tests/``. No
file under ``src/`` was read, no engineer's or reviewer's note was opened, no
``IMPLEMENTATION.patch`` and no ``git diff`` was inspected. Fully offline and
deterministic: pure functions of tracked text plus the one ``git ls-files`` subprocess
``guard`` already owns -- no network, no clock, no mtime, and nothing written inside the
product repo.

DURABILITY. Nothing here compares the worktree against a ``HEAD`` blob to prove the raise
"happened", because that shape inverts the moment the commit lands and every ship is
re-verified from a throwaway fresh clone. The proof that the raise is real and is THIS
iteration's is taken from tracked text that survives the commit: the Done-ledger row
tagged with the shipping tag must narrate one step, from the token one hundred below the
live floor to the live floor itself.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import tests.test_readme_and_ci_contract as guard
from tests.test_iter256_behavior import SUPERSEDED_ALLOWANCES
from tests.test_iter257_behavior import ITERATION_TAG, RAISE_TAG
from tests.test_iter263_behavior import MIN_BINDING_HEADROOM
from tests.test_iter264_behavior import (
    EXPECTED_LEDGER_ROWS,
    MAX_LEDGER_ROW_CHARS,
    MIN_INDEX_ROWS,
)

REPO = Path(__file__).resolve().parents[1]
ROADMAP = REPO / "ROADMAP.md"
ARCHIVE = REPO / "ROADMAP_ARCHIVE.md"

#: The roadmap row this iteration retires, as it is written in both documents.
ROW = "282"

#: The step between two published floors. The README publishes a floor rounded DOWN to a
#: hundred, so a raise is exactly one hundred; ``guard.floor_token`` asserts that shape.
FLOOR_STEP = 100

#: Independent parsers. ``tests/test_iter264_behavior.py`` owns one pair over the same
#: two documents; the iter-168 convention is that two independent parsers must agree on
#: the live index, so these are written from the document's grammar rather than imported.
_INDEP_INDEX_ROW = re.compile(r"^\|[ \t]*(\d+)[ \t]*\|")
_INDEP_LEDGER_ROW = re.compile(r"^- #(\d+)\s")
_INDEP_ARCHIVE_BULLET = re.compile(r"^- \*\*#(\d+)\s")

#: The field labels a retirement bullet carries in place of the index row's table pipes,
#: so the bullet can never be parsed back as a row. Owned as a shape by
#: ``tests/test_iter264_behavior.py``; named here to grade THIS row's bullet.
_RETIREMENT_FIELDS = ("LAYER:", "VALUE:", "RISK:", "SOURCE:", "STATUS:")


def _read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def _intro() -> str:
    text = _read("README.md")
    assert guard.MARKER in text, "README lost its human-owned marker"
    return text.split(guard.MARKER, 1)[0]


def _floor() -> int:
    return guard.published_floor()


def _live_token() -> str:
    return guard.floor_token(_floor())


def _superseded_token() -> str:
    return guard.floor_token(_floor() - FLOOR_STEP)


def _boundary(spelling: str) -> re.Pattern[str]:
    """The same digit-bounded matcher :func:`guard.floor_claim_lines` uses.

    Re-derived rather than imported so a doctored sample here is edited by exactly the
    rule the census reads it with: a bare substring replace would also rewrite the larger
    grouped numbers this repo pins for its own char budgets, and the resulting sample
    would prove nothing about the census.
    """
    return re.compile(rf"(?<![\d,_]){re.escape(spelling)}(?![\d])")


def _demote(text: str) -> str:
    """Rewrite every LIVE floor claim in ``text`` back to the superseded floor."""
    floor = _floor()
    for live, old in zip(guard.floor_tokens(floor), guard.floor_tokens(floor - FLOOR_STEP)):
        text = _boundary(live).sub(old, text)
    return text


def _index_ids(text: str) -> list[str]:
    return [
        match.group(1)
        for line in text.splitlines()
        if (match := _INDEP_INDEX_ROW.match(line)) is not None
    ]


def _ledger_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if _INDEP_LEDGER_ROW.match(line)]


def _archive_bullets(text: str) -> list[str]:
    return [line for line in text.splitlines() if _INDEP_ARCHIVE_BULLET.match(line)]


def _superseded_spellings() -> tuple[str, ...]:
    old = _floor() - FLOOR_STEP
    return (*guard.floor_tokens(old), str(old))


# ===========================================================================
# Behavior 1 -- the README publishes the new floor in both intro sentences.
# ===========================================================================
def test_b1_the_intro_publishes_the_live_floor_twice_and_the_old_one_nowhere() -> None:
    """Behavior 1: both intro sentences carry the live floor and the superseded token has
    left the human-owned block entirely. Every token is derived from the README's own
    claim through the guard, so this assertion cannot go stale at the next raise.
    """
    token = _live_token()
    old = _superseded_token()
    assert token != old, "the live and superseded tokens collapsed -- the guard is broken"
    intro = _intro()
    assert f"**{token}+ tests**" in intro, (
        f"the badge sentence does not publish the live floor {token}: it still reads "
        f"{old} or something else"
    )
    assert f"**{token}+ passing tests**" in intro, (
        f"the 'what this demonstrates' sentence does not publish the live floor {token}"
    )
    assert f"{old}+" not in intro, (
        f"the superseded floor token {old} survives above the human-owned marker, so the "
        "intro publishes two different floors at once"
    )


def test_b1b_the_intro_claims_the_floor_in_exactly_the_two_carve_out_sentences() -> None:
    """Behavior 1, the other half: the operator's carve-out permits exactly the floor
    NUMBER to move above the marker, so the intro must carry exactly two claim lines --
    no third site quietly grew, and no claim was replaced by prose the census cannot see.
    """
    intro = _intro()
    live_lines = guard.floor_claim_lines(intro, _live_token())
    assert len(live_lines) == 2, (
        "the intro must claim the live floor on exactly the two carve-out sentences, but "
        f"the census sees claim lines at {live_lines}"
    )
    stale_lines = guard.floor_claim_lines(intro, _superseded_token())
    assert stale_lines == (), (
        f"the intro still claims the superseded floor at line(s) {stale_lines}"
    )


# ===========================================================================
# Behavior 2 -- the window the new floor opens is real and bounded.
# ===========================================================================
def _rounds_to_the_published_floor(floor: int, live: int) -> bool:
    """The ROUNDING rule that decides whether ``live`` may publish ``floor``.

    Stated here as arithmetic because the two walls this repo lives under are owned in
    different places and are NOT equivalent: :func:`guard.suite_size_problems` enforces the
    ``SUITE_SIZE_SLACK`` staleness wall only, and is deliberately BLIND to the rounding
    window -- moving the rounding rule into that verdict was explicitly recorded as out of
    scope when the gauge learned to report ``binding_at``. Reading them as one verdict is
    the mis-measurement that sized a reverted oracle off the wrong figure.
    """
    return live // 100 * 100 == floor and (live + 1) // 100 * 100 == floor


def test_b2_the_raise_opens_a_window_and_both_walls_sit_where_the_gauge_says() -> None:
    """Behavior 2, as a pure function of the published floor rather than a third live
    collection of the whole suite. The freshly published floor must accept a collection
    two items above it (the claim may not sit ON the wall), and the TWO independent walls
    must agree with the gauge's own fields: the rounding window's far edge is
    ``binding_at - 1``, and the staleness wall is ``red_at``. Asserted as two separate
    rules on purpose -- the spec called them equivalent and they are not.
    """
    floor = _floor()
    intro = _intro()
    assert guard.suite_size_problems(intro, floor + 2) == [], (
        "the published floor rejects a collection two items above it, so the raise left "
        "no margin at all"
    )
    top = floor + guard.SUITE_ROUNDING_WINDOW
    assert _rounds_to_the_published_floor(floor, floor + 2), (
        "a collection two items above the published floor does not round to it"
    )
    assert _rounds_to_the_published_floor(floor, top), (
        f"a collection of {top} must still round to the published floor {floor}"
    )
    assert not _rounds_to_the_published_floor(floor, top + 1), (
        f"a collection of {top + 1} rounds to the NEXT hundred, so it may not publish "
        f"{floor}; the rounding window is not bounded where the gauge says it is"
    )
    assert guard.suite_size_problems(intro, floor + guard.SUITE_SIZE_SLACK) != [], (
        "the staleness wall no longer rejects a collection a full slack above the "
        "published floor, so the floor could go stale without any oracle noticing"
    )
    report = guard.headroom_report(intro, floor + 2)
    fields = {key: int(value) for key, value in re.findall(r"(\w+)=(\d+)", report)}
    assert fields["published"] == floor and fields["floor"] == floor, report
    assert fields["binding_at"] == top + 1, report
    assert fields["red_at"] == floor + guard.SUITE_SIZE_SLACK, report
    assert fields["binding_headroom"] >= MIN_BINDING_HEADROOM, (
        "at two items above the freshly published floor the gauge already reports less "
        f"room than the suite-wide minimum, so the raise bought nothing: {report}"
    )


# ===========================================================================
# Behavior 3 + 10 -- the per-carrier census is NON-VACUOUS, one item per carrier.
# ===========================================================================
@pytest.mark.parametrize("carrier", guard.PUBLISHED_FLOOR_CARRIERS)
def test_b3_demoting_one_carrier_makes_the_census_name_exactly_that_carrier(
    carrier: str,
) -> None:
    """Behaviors 3 and 10 together, as eight separate collected items. For EACH declared
    carrier: the live tree disagrees nowhere, and rewriting that ONE file's live-floor
    claims back to the superseded token makes the census report EXACTLY that file and
    nothing else. This is the arm that a re-key cannot satisfy by accident -- a carrier
    whose claim never moved, or one the census is blind to, fails here while its seven
    siblings still pass.
    """
    floor = _floor()
    sources = guard.tracked_text_sources()
    assert carrier in sources, f"{carrier} is declared a floor carrier but is not tracked"
    assert guard.published_floor_disagreements(sources, floor) == [], (
        "the live tracked tree already disagrees about the floor, so this item cannot "
        "tell a blind census from a green one"
    )
    demoted = _demote(sources[carrier])
    assert demoted != sources[carrier], (
        f"{carrier} carries no digit-bounded claim of the live floor {_live_token()} in "
        "either spelling, so the re-key never reached it"
    )
    problems = guard.published_floor_disagreements({**sources, carrier: demoted}, floor)
    assert len(problems) == 1, (
        f"demoting only {carrier} must produce exactly one finding, but the census "
        f"reported {problems}"
    )
    assert problems[0].startswith(f"{carrier}: "), (
        f"the census blamed the wrong file: {problems[0]}"
    )
    assert "no longer claims the floor" in problems[0], problems[0]


# ===========================================================================
# Behavior 4 -- every superseded-floor allowance moved one step, one item per key.
# ===========================================================================
@pytest.mark.parametrize("path", sorted(SUPERSEDED_ALLOWANCES))
def test_b4_each_declared_allowance_records_the_new_superseded_floor(path: str) -> None:
    """Behavior 4, as five separate collected items -- one per declared allowance. Each
    site must STILL carry its anchor beside a mention of the floor one step behind the
    live one, so the raise moved the RECORD family with the claim family and no exemption
    is left pointing at a number nothing writes any more.
    """
    sources = guard.tracked_text_sources()
    assert path in sources, f"{path} is a declared allowance but is not tracked"
    text = sources[path]
    spellings = _superseded_spellings()
    for anchor in SUPERSEDED_ALLOWANCES[path]:
        hits = [
            line
            for line in text.splitlines()
            if anchor in line and any(spelling in line for spelling in spellings)
        ]
        assert hits, (
            f"{path}: the exemption anchored on {anchor!r} no longer matches a line that "
            f"names the superseded floor {_superseded_token()} -- either the record "
            "family did not move with the raise, or the exemption is now dead weight"
        )


def test_b4b_the_allowance_probe_fails_when_a_single_record_site_is_left_behind() -> None:
    """Behavior 10 on the allowance side: the per-key items above are non-vacuous. Strip
    the superseded mentions out of ONE site's text and the predicate they share must go
    false for that site while the others are untouched. Pure function of a dict, so no
    file is written and no monkeypatch outlives the test.
    """
    sources = guard.tracked_text_sources()
    spellings = _superseded_spellings()
    victim = sorted(SUPERSEDED_ALLOWANCES)[0]

    def records(text: str, anchors: tuple[str, ...]) -> bool:
        return all(
            any(
                anchor in line and any(spelling in line for spelling in spellings)
                for line in text.splitlines()
            )
            for anchor in anchors
        )

    assert records(sources[victim], SUPERSEDED_ALLOWANCES[victim]), (
        f"{victim} does not record the superseded floor on the live tree"
    )
    stripped = sources[victim]
    for spelling in spellings:
        stripped = stripped.replace(spelling, "")
    assert not records(stripped, SUPERSEDED_ALLOWANCES[victim]), (
        "the allowance predicate still passes after every superseded mention was removed"
    )
    others = sorted(set(SUPERSEDED_ALLOWANCES) - {victim})
    assert others, "the allowance set collapsed to a single key"
    for path in others:
        assert records(sources[path], SUPERSEDED_ALLOWANCES[path]), (
            f"{path} stopped recording the superseded floor while {victim} was doctored"
        )


# ===========================================================================
# Behavior 5 -- the narration oracle grades THIS raise, not a settled one.
# ===========================================================================
def test_b5_the_shipping_tag_narrates_this_raise_and_the_settled_tag_cannot() -> None:
    """Behavior 5: the two keys are SEPARATE. ``ITERATION_TAG`` keys settled relocation
    history whose ledger row can never move; the shipping tag keys the raise landing now.
    Exactly one Done-ledger row carries the shipping tag, and it narrates one step -- the
    superseded token, then ``->``, then the live token. The settled row must NOT carry
    that pair, because the iteration it records never published the live floor.
    """
    assert ITERATION_TAG != RAISE_TAG, (
        "the settled-history key and the current-raise key are the same string, which is "
        "the frozen-row-vs-live-floor time bomb: paying a raise then demands that a "
        "settled row narrate a number its iteration never published"
    )
    ledger = _ledger_lines(_read("ROADMAP.md"))
    narration = f"{_superseded_token()} -> {_live_token()}"
    shipped = [line for line in ledger if f"(foundry iter {RAISE_TAG})" in line]
    assert len(shipped) == 1, (
        f"exactly one Done-ledger row must be tagged (foundry iter {RAISE_TAG}); found "
        f"{len(shipped)}: {shipped}"
    )
    assert narration in shipped[0], (
        f"the shipping row does not narrate {narration!r}: {shipped[0]}"
    )
    settled = [line for line in ledger if f"(foundry iter {ITERATION_TAG})" in line]
    assert settled, f"the settled row tagged (foundry iter {ITERATION_TAG}) vanished"
    for line in settled:
        assert narration not in line, (
            f"a settled history row was rewritten to narrate this raise: {line}"
        )


# ===========================================================================
# Behavior 6 -- the row left the index, and only that row.
# ===========================================================================
def test_b6_the_paid_row_left_the_index_and_took_its_re_pricing_with_it() -> None:
    """Behavior 6: the index no longer holds the paid row, the ``_Re-priced:`` note that
    corrected that row is gone with it (a correction cannot outlive the row it corrects),
    and the index is still above its floor -- so no second row was retired to make room.
    """
    text = _read("ROADMAP.md")
    ids = _index_ids(text)
    assert ids, "the independent index parser found no rows at all -- it is fail-open"
    assert ROW not in ids, (
        f"row #{ROW} is still an OPEN index row, so the retirement never landed: {ids}"
    )
    assert f"| {ROW} |" not in text, (
        f"a raw '| {ROW} |' table cell survives even though the parser sees no such row"
    )
    repriced = [
        line
        for line in text.splitlines()
        if "_Re-priced:" in line and f"#{ROW}" in line
    ]
    assert repriced == [], (
        f"the _Re-priced: note about row #{ROW} outlived the row it corrected: {repriced}"
    )
    assert len(ids) >= MIN_INDEX_ROWS, (
        f"the index fell to {len(ids)} rows, under the {MIN_INDEX_ROWS}-row floor: more "
        "than the one paid row was retired in this commit"
    )


# ===========================================================================
# Behavior 7 -- the retirement is recorded in both documents, in the shipped shape.
# ===========================================================================
def test_b7_the_retirement_is_recorded_once_in_each_document() -> None:
    """Behavior 7: one archive bullet carrying the pre-ship row text with the table pipes
    replaced by field labels, and exactly one Done-ledger row, short enough for the
    ledger's per-row budget and tagged with the shipping iteration. The ledger total is
    checked against the sibling module's pinned expectation rather than a literal here, so
    the two records cannot drift apart silently.
    """
    roadmap = _read("ROADMAP.md")
    archive = _read("ROADMAP_ARCHIVE.md")

    bullets = [line for line in _archive_bullets(archive) if line.startswith(f"- **#{ROW} ")]
    assert len(bullets) == 1, (
        f"the archive must gain exactly one '- **#{ROW} ' retirement bullet; found "
        f"{len(bullets)}"
    )
    bullet = bullets[0]
    assert f"foundry iter {RAISE_TAG}" in bullet, (
        f"the retirement bullet does not name the shipping iteration {RAISE_TAG}: {bullet[:200]}"
    )
    missing = [label for label in _RETIREMENT_FIELDS if label not in bullet]
    assert missing == [], (
        "the retirement bullet must reproduce the index row's fields as LABELS so it can "
        f"never be parsed back as a table row; missing {missing}"
    )
    assert "|" not in bullet, (
        "the retirement bullet still carries a table pipe, so the archive can be parsed "
        "as holding an open index row"
    )

    rows = [line for line in _ledger_lines(roadmap) if line.startswith(f"- #{ROW} ")]
    assert len(rows) == 1, f"the Done ledger must gain exactly one '- #{ROW} ' row; found {len(rows)}"
    assert len(rows[0]) <= MAX_LEDGER_ROW_CHARS, (
        f"the ledger row is {len(rows[0])} chars, over the {MAX_LEDGER_ROW_CHARS}-char budget"
    )
    assert f"(foundry iter {RAISE_TAG})" in rows[0], (
        f"the ledger row is not tagged with the shipping iteration: {rows[0]}"
    )
    ledger = _ledger_lines(roadmap)
    assert len(ledger) == EXPECTED_LEDGER_ROWS, (
        f"the independent parser counts {len(ledger)} Done-ledger rows while the sibling "
        f"module pins {EXPECTED_LEDGER_ROWS}: the two records have drifted"
    )
    assert not [line for line in _archive_bullets(archive) if line.startswith(f"- #{ROW} ")], (
        "the ledger row shape appears in the archive too, so the record is duplicated"
    )
