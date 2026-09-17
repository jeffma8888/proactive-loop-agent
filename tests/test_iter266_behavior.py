"""Independent second opinion on iteration 421: the BARE-INTEGER mirrors of the
published suite-size floor, which are the sites the floor census structurally cannot see
and the measured reason the same work was reverted once already.

MODULE NAME, derived from the REPO and never from the state-dir counter (the 2026-08-19
operator pin). ``git ls-files tests`` tops out at ``test_iter265_behavior.py`` on the tree
under test, +1 = ``266``, and ``git cat-file -e HEAD:tests/test_iter266_behavior.py``
FAILED (``path ... does not exist in 'HEAD'``) before the first byte was written, with no
worktree file at that path either. The module was then ``git add``-ed BEFORE any
instrument here measured the tree, because :func:`guard.tracked_text_sources` walks
``git ls-files`` and reads the WORKTREE: an untracked module sits outside the very census
this file reasons about, and ``git add -N`` would stage the EMPTY blob (measured: the
staged blob is ``52d3c03``, not ``e69de29``).

NO FLOOR NUMBER IS SPELLED ANYWHERE IN THIS MODULE, in any of its three spellings, and
that is a correctness requirement rather than a style rule. The census in
``tests/test_readme_and_ci_contract.py`` reports any tracked file that claims the live
floor while not being one of the eight declared carriers, and this module is tracked. So
every number below is DERIVED at run time from ``guard.published_floor()``. A literal
here would make the oracle its own ninth carrier and red a public build on the very
commit that added it.

WHAT THIS MODULE OWNS, AND WHY IT IS THE ARM NOTHING ELSE GRADES.
``guard.floor_claim_lines`` matches exactly two spellings of the floor: the comma-grouped
token a Markdown file publishes and the PEP 515 underscore literal a Python module pins.
It cannot see the BARE-INTEGER spelling (``PUBLISHED_FLOOR = <floor>``), so every such
mirror is invisible to all six shipped floor censuses. Measured on the tree under test:
three declared carriers hold six such mirrors between them, and the two constants
``tests/test_iter143_behavior.py`` and ``tests/test_iter204_behavior.py`` pin the floor in
that spelling ALONE -- each satisfies the comma-spelling census through an unrelated line
elsewhere in the same file, so a raise that misses them passes every census and reds a
DIFFERENT module's assertion. That is exactly how the previous attempt at this raise died
with 14 failures across 6 modules while the census reported no problem at all.

The same blind spot has an outer ring, and this module closes that too. The per-carrier arm
reads only the eight DECLARED carriers, so a bare-integer mirror in any OTHER tracked file
is seen by nothing at all: not by the censuses (wrong spelling) and not by that arm (wrong
file). Measured over the whole tracked tree at the floor under test, exactly three
non-carrier files hold a floor-cued bare four-digit integer, and each is a deliberate
record rather than a claim -- an unrelated relocated-text bound, a pre-bump gauge fixture,
and a named historical digit constant. Those three are enumerated with reasons, and the
census is an equality against that enumeration, so the FOURTH such file fails here by name.

WHAT IS DELIBERATELY NOT RE-ASSERTED HERE, because restating an owned expectation
multiplies the sites the NEXT raise has to re-key -- the very defect the retired roadmap
row existed to clear:

* Expected Behaviors 1 and 2's LIVE arm. ``tests/test_iter250_behavior.py::test_b2`` and
  ``tests/test_iter263_behavior.py::test_b6`` already spawn a ``--collect-only``
  subprocess over the whole suite; a third copy would add tens of seconds to every run to
  re-measure a number two shipped oracles gate. Reported out of band in ``tester.md``.
* Expected Behavior 3's README intro and Expected Behaviors 5-8's record sites, which
  ``tests/test_iter265_behavior.py`` grades in nine items over the same two documents.
  This module grades only the arm that module names as out of its scope: the bare-integer
  spelling, plus the two cross-module quotations that no census reads as claims.
* Expected Behavior 9 (``ROADMAP.md`` under its ratchet). Asserting a size bound here
  would make this module a size-bounding module, and ``tests/test_iter172_behavior.py``
  freezes that membership to a one-entry allowlist. Owned by
  ``tests/test_iter241_behavior.py`` and ``tests/test_roadmap_size_budget.py``; measured
  out of band and reported in ``tester.md``.
* Expected Behaviors 11 and 12 (the suite itself and ``make typecheck``) are commands, not
  properties of tracked text; both are run out of band and reported in ``tester.md``.

ISOLATION CONTRACT (honored, no exception). Every assertion is derived from this
iteration's ``pm.md`` Expected Behaviors, from the tracked Markdown documents and test
modules themselves, and from the conventions of the existing modules under ``tests/``. No
file under ``src/`` was read, no engineer's or reviewer's note was opened, no
``IMPLEMENTATION.patch`` and no ``git diff`` was inspected. Fully offline and
deterministic: pure functions of tracked text plus the single ``git ls-files`` subprocess
``guard`` already owns -- no network, no clock, no mtime, and nothing is written inside
the product repo.

DURABILITY. Nothing here compares the worktree against a ``HEAD`` blob to prove the raise
"happened": that shape inverts the moment the commit lands, and every ship is re-verified
from a throwaway fresh clone where ``HEAD`` already carries the new floor. Every check is
a relation between tracked files at whatever floor the README currently publishes, so it
grades the NEXT raise as strictly as it grades this one.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import tests.test_readme_and_ci_contract as guard

REPO = Path(__file__).resolve().parents[1]

#: This module's own path as ``git ls-files`` spells it. It is tracked, so the
#: whole-tree census below would otherwise read this file's own vocabulary.
SELF_PATH = f"tests/{Path(__file__).name}"

#: The step between two published floors. The README publishes a floor rounded DOWN to a
#: hundred, so a raise is exactly one hundred; ``guard.floor_token`` asserts that shape.
FLOOR_STEP = 100

#: A line is only READ as a floor mirror when it names the floor's vocabulary. Without a
#: cue, every four-digit rounded number in a test module (char budgets, line numbers,
#: iteration counts) would manufacture a false obligation -- the precise failure mode that
#: made the bare-substring version of the comma-spelling census unshippable.
MIRROR_CUES = ("FLOOR", "suite_size_problems", "published_floor")

#: A bare four-digit integer that is NOT part of a larger grouped number. The lookaround
#: refuses a digit, comma, underscore or decimal point on either side, so ``36,000``,
#: ``36_000`` and ``376000`` are not read as mirrors of a four-digit floor.
BARE_INTEGER = re.compile(r"(?<![\d,_.])(\d{4})(?![\d,_])")

#: The declared carriers that hold bare-integer mirrors, and HOW MANY each holds, as
#: measured on the tree under test. These are MINIMA, not exact counts: a later raise may
#: add a mirror, but it may not satisfy this oracle by DELETING one, which is the cheap
#: false fix an exactness pin would invite and a floor-only assertion would not catch.
MIRROR_SITES: dict[str, int] = {
    "tests/test_iter143_behavior.py": 1,
    "tests/test_iter171_behavior.py": 4,
    "tests/test_iter204_behavior.py": 1,
}

#: The cross-module quotation: one carrier pins ANOTHER carrier's bare-integer constant as
#: a string literal, so the mirror has two homes and a raise must re-key both. Neither
#: home is visible to the comma-spelling census.
QUOTED_MIRROR = re.compile(r"\"(PUBLISHED_FLOOR = (\d{4}))\"")
QUOTED_MIRROR_OWNER = "tests/test_iter171_behavior.py"
QUOTED_MIRROR_TARGET = "tests/test_iter143_behavior.py"

#: The tracked files that are NOT declared carriers yet still hold a floor-cued bare
#: four-digit integer, each with the measured reason it is not an obligation. Scoping the
#: previous arm to the declared carriers leaves a hole exactly one level out: a bare-integer
#: mirror in a NON-carrier file is invisible to every shipped census (which cannot see the
#: spelling) AND to the per-carrier arm above (which never reads the file). This dict turns
#: that hole into a ratchet -- a NEW such file must be declared a carrier or explained here.
#:
#: No number is spelled in these reasons, deliberately: this module is tracked, so a literal
#: would make the oracle its own carrier. The values are prose, and the census below reads
#: the files themselves.
NON_CARRIER_MIRRORS: dict[str, str] = {
    "tests/test_iter168_behavior.py": (
        "an unrelated constant that happens to end in the cue vocabulary -- it bounds "
        "relocated roadmap text, not the suite size, and no raise may re-key it"
    ),
    "tests/test_iter176_behavior.py": (
        "a deliberately pre-bump intro fixture: the gauge is exercised against the "
        "superseded value on purpose, so re-keying it would delete the regression it pins"
    ),
    "tests/test_iter250_behavior.py": (
        "a named historical digit constant, kept at its recorded value by contract so the "
        "bare spelling stays covered after the value it records is superseded"
    ),
}


#: The archive's retirement bullets, and the two modules that mirror their TOTAL: one
#: asserts it against the live document, the other quotes that module's assertion. The
#: total moves by one on every sanctioned retirement, so both mirrors are re-keyed by the
#: retiring iteration or they are stale by exactly the count of rows it retired.
ARCHIVE_BULLET = re.compile(r"^- \*\*#(\d+)\s")
CENSUS_OWNER = "tests/test_iter214_behavior.py"
CENSUS_MIRROR = "tests/test_iter256_behavior.py"

#: A narration step in the retirement-census comment (``84 -> 85``). Bounded to two and
#: three digits and refused a comma on either side so it cannot match inside a
#: comma-grouped floor token, where ``5,900 -> 6,000`` would otherwise read as
#: ``900 -> 6``.
NARRATION_STEP = re.compile(r"(?<![\d,_])(\d{2,3}) -> (\d{2,3})(?![\d,_])")


def _read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def _floor() -> int:
    """The floor the README's own intro publishes, as an int -- the single source."""
    return guard.published_floor()


def _mirror_lines(text: str) -> tuple[tuple[int, int, str], ...]:
    """Every bare-integer floor mirror in ``text`` as ``(line number, value, line)``.

    History lines are excluded by exactly the markers the comma-spelling census uses:
    a line that RECORDS a superseded floor must go on naming it forever, so a scan that
    cannot tell a record from a claim reports every past bump as a defect and gets
    deleted rather than fixed.
    """
    found: list[tuple[int, int, str]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not any(cue in line for cue in MIRROR_CUES):
            continue
        if any(marker in line for marker in guard.FLOOR_HISTORY_MARKERS):
            continue
        for match in BARE_INTEGER.finditer(line):
            value = int(match.group(1))
            if value % FLOOR_STEP == 0 and 1_000 <= value < 10_000:
                found.append((number, value, line))
    return tuple(found)


def _stale(text: str, floor: int) -> tuple[tuple[int, int, str], ...]:
    return tuple(site for site in _mirror_lines(text) if site[1] != floor)


# ===========================================================================
# Behavior 4 -- the spelling no census can see.
# ===========================================================================
@pytest.mark.parametrize("carrier", guard.PUBLISHED_FLOOR_CARRIERS)
def test_b4a_every_bare_integer_mirror_in_a_carrier_names_the_live_floor(
    carrier: str,
) -> None:
    """Behavior 4, two-sided per declared carrier.

    Side one: no bare-integer mirror is left at a superseded floor. Side two: a carrier
    measured to HOLD mirrors still holds at least as many, so the raise cannot be
    "paid" by deleting the assertion that would have failed.
    """
    floor = _floor()
    text = _read(carrier)
    stale = _stale(text, floor)
    assert stale == (), (
        f"{carrier} still mirrors a superseded floor as a bare integer at "
        f"line(s) {[site[0] for site in stale]}: {[site[1] for site in stale]!r} against "
        f"a published floor of {floor}. No floor census sees this spelling, so the build "
        "goes red inside another module instead of here"
    )
    minimum = MIRROR_SITES.get(carrier, 0)
    live = _mirror_lines(text)
    assert len(live) >= minimum, (
        f"{carrier} held {minimum} bare-integer floor mirror(s) when this oracle was "
        f"written and now holds {len(live)}: a mirror was DELETED rather than re-keyed"
    )


def test_b4b_the_mirror_census_is_non_vacuous_and_names_a_left_behind_mirror() -> None:
    """Behavior 4's anti-vacuity arm: ``stale == ()`` is also what an empty census says.

    Three measurements, in the order that makes the previous arm mean something: the live
    tree really does hold mirrors, demoting one real carrier's mirror to the superseded
    floor makes the census NAME it, and a line that records a bump instead of claiming one
    is still not an obligation.
    """
    floor = _floor()
    total = sum(len(_mirror_lines(_read(path))) for path in guard.PUBLISHED_FLOOR_CARRIERS)
    declared = sum(MIRROR_SITES.values())
    assert total >= declared, (
        f"the bare-integer census finds {total} mirror(s) across the declared carriers "
        f"but {declared} were measured: the previous arm is now vacuous"
    )

    sample = _read(QUOTED_MIRROR_TARGET)
    live_pin = f"PUBLISHED_FLOOR = {floor}"
    assert live_pin in sample, f"{QUOTED_MIRROR_TARGET} lost its bare-integer pin"
    demoted = sample.replace(live_pin, f"PUBLISHED_FLOOR = {floor - FLOOR_STEP}")
    assert demoted != sample, "the probe rewrote nothing, so it proves nothing"
    caught = _stale(demoted, floor)
    assert caught, (
        "the census does not report a carrier left behind at the superseded floor, which "
        "is the single failure it exists to catch"
    )
    assert all(site[1] == floor - FLOOR_STEP for site in caught), caught

    history = f"SUPERSEDED_FLOOR went {floor - FLOOR_STEP} -> {floor} in this bump\n"
    assert BARE_INTEGER.search(history), "the history sample lost its bare integer"
    assert _mirror_lines(history) == (), (
        "a line that RECORDS a superseded floor is being read as a claim, so every past "
        "bump becomes a defect this raise cannot pay"
    )


def test_b4c_the_cross_module_quoted_mirror_matches_the_line_it_quotes() -> None:
    """Behavior 4's second home: one carrier quotes another's bare-integer constant.

    The quoted string must name the live floor AND still exist verbatim as a line in the
    module it pins -- a two-level mirror that goes stale silently, because the quotation
    is a string literal to every census and a comment to every reader.
    """
    floor = _floor()
    quoted = QUOTED_MIRROR.findall(_read(QUOTED_MIRROR_OWNER))
    assert quoted, (
        f"{QUOTED_MIRROR_OWNER} no longer quotes {QUOTED_MIRROR_TARGET}'s bare-integer "
        "floor pin, so nothing pins that constant across modules any more"
    )
    target_lines = {line.strip() for line in _read(QUOTED_MIRROR_TARGET).splitlines()}
    for text, value in quoted:
        assert int(value) == floor, (
            f"{QUOTED_MIRROR_OWNER} quotes {text!r} while the README publishes a floor of "
            f"{floor}: the cross-module mirror was left behind by the raise"
        )
        assert text in target_lines, (
            f"{QUOTED_MIRROR_OWNER} quotes {text!r} but no such line exists in "
            f"{QUOTED_MIRROR_TARGET}: the pin passes on a string that is now fiction"
        )


# ===========================================================================
# Behavior 5 -- the retirement-census total, and the narration that explains it.
# ===========================================================================
def test_b5_the_census_total_and_its_narration_end_at_the_live_count() -> None:
    """Behavior 5: the archive's retirement-bullet total has three homes that must agree.

    The live document, the module that asserts the literal against it, and the module that
    quotes that literal. The narration explaining the last step is graded too: the census
    literal moves by one per retirement, so an unadvanced comment is how a reviewer loses
    the ability to tell a legitimate bump from a lost bullet.
    """
    archive = _read("ROADMAP_ARCHIVE.md")
    live_total = sum(1 for line in archive.splitlines() if ARCHIVE_BULLET.match(line))
    assert live_total > 0, "the independent archive parser found no bullets -- fail-open"

    owner = _read(CENSUS_OWNER)
    assert f"== {live_total}" in owner, (
        f"{CENSUS_OWNER} does not assert the live retirement-bullet total "
        f"({live_total}): the census literal is stale by the number of rows retired"
    )
    mirror = _read(CENSUS_MIRROR)
    assert f'"== {live_total}"' in mirror, (
        f"{CENSUS_MIRROR} quotes a different retirement-bullet total than the live "
        f"{live_total}: the lockstep pair shipped half-paid"
    )

    steps = NARRATION_STEP.findall(mirror)
    assert steps, f"{CENSUS_MIRROR} lost the narration explaining its census literal"
    assert int(steps[-1][1]) == live_total, (
        f"{CENSUS_MIRROR}'s narration ends at {steps[-1][1]} while the archive holds "
        f"{live_total} retirement bullets: the last step was never written down"
    )
    assert int(steps[-1][0]) == live_total - 1, (
        f"{CENSUS_MIRROR}'s last narration step is {steps[-1]}, which is not the single "
        f"+1 move a one-row retirement makes"
    )


# ===========================================================================
# Behavior 4, one level out -- the same spelling in a file no carrier list names.
# ===========================================================================
def _non_carrier_mirror_files() -> dict[str, tuple[int, ...]]:
    """Tracked non-carrier files holding a floor-cued bare-integer mirror, and where.

    Walks the census's OWN source of tracked text so the answer is scoped to the shipping
    tree, not to the worktree: an untracked file is not yet a liability, and a deleted one
    stops being one.
    """
    carriers = set(guard.PUBLISHED_FLOOR_CARRIERS)
    out: dict[str, tuple[int, ...]] = {}
    for path, text in guard.tracked_text_sources().items():
        if path in carriers or path == SELF_PATH:
            continue
        sites = _mirror_lines(text)
        if sites:
            out[path] = tuple(site[0] for site in sites)
    return out


def test_b4d_no_undeclared_file_mirrors_the_floor_as_a_bare_integer() -> None:
    """Behavior 4's blind spot, closed: the spelling outside the declared carriers.

    Two-sided. Side one: the set of non-carrier files holding a floor-cued bare-integer
    mirror equals the enumerated allowlist, so a raise that leaves a mirror in an
    undeclared file fails HERE, naming the file, instead of reding some other module.
    Side two: the allowlist is not a rubber stamp -- every entry names a tracked file that
    really does hold such a line, so an entry cannot outlive the mirror it excuses.
    """
    live = _non_carrier_mirror_files()
    assert set(live) == set(NON_CARRIER_MIRRORS), (
        "the set of undeclared files mirroring the floor as a bare integer drifted from "
        f"the allowlist. Newly mirroring: {sorted(set(live) - set(NON_CARRIER_MIRRORS))} "
        f"-- declare the file a carrier or add an entry stating why its value is a record "
        f"rather than a claim. No longer mirroring: "
        f"{sorted(set(NON_CARRIER_MIRRORS) - set(live))} -- drop the stale entry"
    )
    for path, lines in live.items():
        assert lines, f"{path} was reported with no line numbers"


def test_b4e_every_allowlist_entry_states_a_reason_and_is_not_a_carrier() -> None:
    """The allowlist's own hygiene: a reason, a real file, and no overlap with the census.

    An entry that is ALSO a declared carrier would silence the per-carrier arm for that
    file, which is the one way this ratchet could weaken the guard it extends.
    """
    carriers = set(guard.PUBLISHED_FLOOR_CARRIERS)
    tracked = guard.tracked_text_sources()
    for path, reason in NON_CARRIER_MIRRORS.items():
        assert path in tracked, f"{path} is allowlisted but is not tracked text any more"
        assert path not in carriers, (
            f"{path} is both a declared floor carrier and allowlisted as a non-carrier "
            "record site: the allowlist would silence the per-carrier arm for it"
        )
        assert len(reason) >= 40, (
            f"{path}'s allowlist entry does not state why its value is a record rather "
            f"than a claim: {reason!r}"
        )
    assert SELF_PATH not in NON_CARRIER_MIRRORS, (
        "this module excuses itself in the census, so an allowlist entry for it would be "
        "a second, silent exemption"
    )
