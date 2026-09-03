"""Black-box behavior tests for foundry iteration 260 --- the published suite-size
floor is raised one rounded step, and the set of files that pin it is ENUMERATED and
checked in both directions.

Feature under test (``pm.md`` "## Feature"): raise the published test floor one
hundred-step at every carrier, and ship a two-sided census oracle that names the
carrier set and fails when any carrier disagrees.

Why it matters (``pm.md`` "## Why"): before this iteration the loop was blocked ---
``live // 100 * 100 == PUBLISHED_FLOOR`` had ZERO test functions of headroom, so the
next test added anywhere reddened a PUBLIC build.

ISOLATION CONTRACT (honored): every assertion below was written from this
iteration's ``pm.md`` plus the tracked ``tests/`` tree and the tracked prose files
(``README.md``, ``ROADMAP.md``). No implementation source under ``src/`` was read,
no engineer or reviewer notes were read, and no ``git diff`` was consulted. The
census helpers under test live in ``tests/test_readme_and_ci_contract.py``, which
the isolation contract explicitly places inside the readable domain.

AMBIGUITY NOTES (PM feedback --- ``pm.md`` shipped with "## Expected Behaviors" left
as ``TBD -- refining``, so the numbered behaviors below are this stage's reading of
the one-sentence "## Feature" statement, not a quotation of the spec):

* The Feature sentence does not say WHERE the carrier set must be enumerated, nor
  in what form. Tested as: a module-level, importable, ordered collection of
  repo-relative path strings living beside the census helper. That is the only
  reading under which "names the carrier set" is machine-checkable.
* "fails when any carrier disagrees" is read as BOTH directions, because the
  Feature calls the oracle "two-sided": a declared carrier that stops claiming the
  live floor fails, AND an undeclared tracked file that starts claiming it fails.
  Behavior 5 tests all three reachable branches.
* The Feature does not say whether the census may keep its own copy of the floor.
  Tested as: it may NOT (behavior 7) --- a census carrying a seventh copy of the
  number would be the one carrier nothing checks.
* SECOND MEASURED BLIND SPOT, same family, also reported rather than failed: the
  exclusion is per-LINE, so a history sentence WRAPPED across two lines leaves the
  second line carrying the token with no marker on it. That is live in the tree
  today --- ``tests/test_iter143_behavior.py`` writes the arrow on one line and
  ``it past 5,50X).`` on the next (digits altered here on purpose). It is harmless
  because that file is a DECLARED carrier, where a claim is what the census wants;
  in an undeclared file the same wrap would red a public build. Behavior 8's live
  census is what currently keeps this safe.
* An earlier draft of behavior 4 asserted that NO carrier may contain the
  superseded token outside a history line. Measured, that is wrong and it is worth
  recording as spec feedback: three carriers legitimately hold it as
  ``STALE_FLOOR_TOKEN = "..."`` and as ``assert <old> not in intro`` --- i.e. as the
  mechanism that ENFORCES the bump. The test now asserts the narrower, correct
  property (the PUBLIC artifact carries no superseded claim).
* MEASURED BLIND SPOT, reported rather than asserted as a defect: the history
  exclusion is a substring test against an ASCII arrow, and this repo writes the
  same arrow BOTH ways --- ``README.md`` already contains a U+2192 arrow today. A
  bump-history line written with U+2192 would therefore be classified as a LIVE
  claim, and on an undeclared file that reds a public build. Behavior 9 pins the
  narrow fact that the hazard is not live on the shipping tree (zero tracked lines
  pair the live token with U+2192); it deliberately does NOT assert the exclusion
  handles U+2192, because the spec never says it should. Recommend the next spec
  either add the Unicode arrow to the marker set or state the ASCII-only rule.

Fully offline and deterministic: the census helpers are pure over in-memory
mappings, the live-tree checks read only tracked files, and the one collection
subprocess is the guard module's own ``collect_live_test_count()`` helper. No
network, no API key, no sleeps. The tracked tree is never written --- every
mutation in the two-sided family is applied to a COPY of a dict literal.

This module deliberately contains NO comma-grouped copy of the live floor token:
writing one would make this file an UNDECLARED carrier and red the live census.
Every token it needs is derived at run time from the README.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from tests import test_readme_and_ci_contract as guard

REPO_ROOT = Path(__file__).resolve().parents[1]

#: The floor this iteration raises the published claim TO, as a bare int (no
#: comma-grouped token -- see the module docstring).
EXPECTED_FLOOR = 5_700

#: The floor it is raised FROM.
SUPERSEDED_FLOOR = 5_600

_LIVE_COUNT: list[int] = []


def _live_count() -> int:
    """One real collection per module run, memoized -- collection is the long pole."""
    if not _LIVE_COUNT:
        _LIVE_COUNT.append(guard.collect_live_test_count())
    return _LIVE_COUNT[0]


def _intro_text() -> str:
    """The human-owned block: everything above the portfolio marker."""
    text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert guard.MARKER in text, "README lost its portfolio marker"
    return text.split(guard.MARKER, 1)[0]


def _tracked_paths() -> tuple[str, ...]:
    listing = subprocess.run(
        ("git", "ls-files", "-z"),
        cwd=str(REPO_ROOT),
        capture_output=True,
        check=True,
        timeout=60,
        text=False,
    ).stdout
    return tuple(raw.decode("utf-8") for raw in listing.split(b"\0") if raw)


# --------------------------------------------------------------------------- #
# 1. the README publishes the RAISED floor
# --------------------------------------------------------------------------- #


def test_b1_the_readme_intro_publishes_the_raised_rounded_floor() -> None:
    """The one number every carrier is keyed to moved up one hundred-step."""
    floor = guard.published_floor()
    assert floor == EXPECTED_FLOOR, (
        f"the README's intro publishes a floor of {floor}, expected {EXPECTED_FLOOR}"
    )
    assert floor % 100 == 0, floor
    intro = _intro_text()
    assert f"{guard.floor_token(floor)}+" in intro, (
        "the raised floor is not published as a '+' floor in the human-owned intro"
    )
    assert guard.floor_token(SUPERSEDED_FLOOR) not in intro, (
        "the intro still publishes the superseded floor"
    )


# --------------------------------------------------------------------------- #
# 2. the raised floor is TRUE, FRESH, and leaves real headroom
# --------------------------------------------------------------------------- #


def test_b2_the_raised_floor_is_true_fresh_and_unblocks_the_suite() -> None:
    """The blocking guard was ``live // 100 * 100 == floor`` at ZERO headroom."""
    live = _live_count()
    floor = guard.published_floor()
    assert live >= floor, f"only {live} tests collect against a published floor of {floor}"
    assert live - floor < guard.SUITE_SIZE_SLACK, (
        f"the published floor is {live - floor} tests stale (slack {guard.SUITE_SIZE_SLACK})"
    )
    assert live // 100 * 100 == floor, (
        f"the rounded live count is {live // 100 * 100}, not the published {floor}"
    )
    assert (live + 1) // 100 * 100 == floor, (
        f"adding ONE test would still red the build: live={live} rounds off the floor"
    )
    assert guard.suite_size_problems(_intro_text(), live) == [], (
        "the README's own suite-size guard rejects the raised floor at the live count"
    )


# --------------------------------------------------------------------------- #
# 3. the carrier set is ENUMERATED, tracked, and duplicate-free
# --------------------------------------------------------------------------- #


def test_b3_the_carrier_set_is_an_enumerated_collection_of_tracked_paths() -> None:
    carriers = guard.PUBLISHED_FLOOR_CARRIERS
    assert isinstance(carriers, tuple), type(carriers)
    assert len(carriers) >= 2, carriers
    assert len(set(carriers)) == len(carriers), f"duplicate carrier: {carriers}"
    assert "README.md" in carriers, "the README publishes the floor, so it is a carrier"
    tracked = set(_tracked_paths())
    untracked = [path for path in carriers if path not in tracked]
    assert untracked == [], f"declared carriers are not tracked by git: {untracked}"
    for path in carriers:
        assert not path.startswith("/") and ".." not in path, path


# --------------------------------------------------------------------------- #
# 4. every carrier claims the RAISED floor and none still claims the old one
# --------------------------------------------------------------------------- #


def test_b4_every_declared_carrier_claims_the_raised_floor() -> None:
    floor = guard.published_floor()
    token = guard.floor_token(floor)
    stale: list[str] = []
    for path in guard.PUBLISHED_FLOOR_CARRIERS:
        text = (REPO_ROOT / path).read_text(encoding="utf-8")
        if not guard.floor_claim_lines(text, token):
            stale.append(path)
    assert stale == [], f"the bump missed these carriers: {stale}"


def test_b4b_the_public_artifact_no_longer_publishes_the_superseded_floor() -> None:
    """The README is the published surface, so a leftover old token there is public."""
    old = guard.floor_token(SUPERSEDED_FLOOR)
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert old not in readme, (
        f"README.md still publishes the superseded floor {old} somewhere"
    )


def test_b4c_the_roadmap_records_the_bump_as_history_not_as_a_claim() -> None:
    """The separation the census promises, verified on the SHIPPING tree.

    ``ROADMAP.md`` names both floors in its Done ledger and is deliberately NOT a
    carrier; if the exclusion did not work, that row would read as an undeclared
    file claiming the live floor and would red a public build.
    """
    token = guard.floor_token(guard.published_floor())
    roadmap = (REPO_ROOT / "ROADMAP.md").read_text(encoding="utf-8")
    assert token in roadmap, "the roadmap does not record this bump at all"
    assert guard.floor_claim_lines(roadmap, token) == (), (
        "the roadmap's bump-history row is being read as a LIVE floor claim"
    )
    assert "ROADMAP.md" not in guard.PUBLISHED_FLOOR_CARRIERS


# --------------------------------------------------------------------------- #
# 5. the census is TWO-SIDED (all three reachable branches, on dict literals)
# --------------------------------------------------------------------------- #

_PROBE_FLOOR = 6_600
_PROBE_TOKEN = "6,600"


def _agreeing_sources() -> dict[str, str]:
    return {path: f"claims {_PROBE_TOKEN}+ here\n" for path in guard.PUBLISHED_FLOOR_CARRIERS}


def test_b5a_a_full_house_of_agreeing_carriers_reports_nothing() -> None:
    assert guard.published_floor_disagreements(_agreeing_sources(), _PROBE_FLOOR) == []


def test_b5b_a_carrier_the_bump_missed_is_named() -> None:
    sources = _agreeing_sources()
    missed = guard.PUBLISHED_FLOOR_CARRIERS[-1]
    sources[missed] = "claims 6,500+ here\n"
    problems = guard.published_floor_disagreements(sources, _PROBE_FLOOR)
    assert len(problems) == 1, problems
    assert missed in problems[0], problems
    assert _PROBE_TOKEN in problems[0], problems


def test_b5c_a_declared_carrier_absent_from_the_tree_is_named() -> None:
    sources = _agreeing_sources()
    gone = guard.PUBLISHED_FLOOR_CARRIERS[0]
    del sources[gone]
    problems = guard.published_floor_disagreements(sources, _PROBE_FLOOR)
    assert len(problems) == 1, problems
    assert gone in problems[0] and "not in the tracked tree" in problems[0], problems


def test_b5d_an_undeclared_file_that_claims_the_floor_is_named_with_its_line() -> None:
    sources = _agreeing_sources()
    sources["docs/some_new_note.md"] = f"intro\nthe suite has {_PROBE_TOKEN}+ tests\n"
    problems = guard.published_floor_disagreements(sources, _PROBE_FLOOR)
    assert len(problems) == 1, problems
    assert "docs/some_new_note.md" in problems[0], problems
    assert "undeclared" in problems[0] and "2" in problems[0], problems


def test_b5e_both_sides_are_reported_together_declared_first() -> None:
    """A single verdict must not hide one side behind the other."""
    sources = _agreeing_sources()
    missed = guard.PUBLISHED_FLOOR_CARRIERS[-1]
    sources[missed] = "nothing about the floor\n"
    sources["zz_undeclared.md"] = f"{_PROBE_TOKEN}+\n"
    problems = guard.published_floor_disagreements(sources, _PROBE_FLOOR)
    assert len(problems) == 2, problems
    assert missed in problems[0], problems
    assert "zz_undeclared.md" in problems[1], problems


def test_b5f_the_verdict_is_pure_over_the_mapping_and_touches_no_file() -> None:
    """Paths that exist nowhere on disk still produce the right verdict."""
    fake = {path: f"{_PROBE_TOKEN}+\n" for path in guard.PUBLISHED_FLOOR_CARRIERS}
    fake["nonexistent/dir/never_created.md"] = f"{_PROBE_TOKEN}+\n"
    problems = guard.published_floor_disagreements(fake, _PROBE_FLOOR)
    assert len(problems) == 1 and "never_created.md" in problems[0], problems
    assert not (REPO_ROOT / "nonexistent").exists()


def test_b5g_the_carrier_set_is_an_overridable_argument() -> None:
    """The census must be testable against a synthetic set, not only the live one."""
    problems = guard.published_floor_disagreements(
        {"a.md": f"{_PROBE_TOKEN}+\n"}, _PROBE_FLOOR, carriers=("a.md", "b.md")
    )
    assert len(problems) == 1 and "b.md" in problems[0], problems


# --------------------------------------------------------------------------- #
# 6. bump HISTORY is not a claim
# --------------------------------------------------------------------------- #


def test_b6_history_lines_are_excluded_from_the_claim_census() -> None:
    text = (
        f"the floor is {_PROBE_TOKEN}+\n"
        f"re-keyed 6,500 -> {_PROBE_TOKEN} when the suite grew\n"
        f"bumped to {_PROBE_TOKEN} at factory iter 260\n"
    )
    assert guard.floor_claim_lines(text, _PROBE_TOKEN) == (1,)


def test_b6b_a_repo_that_is_ONLY_history_claims_nothing() -> None:
    """Otherwise the roadmap's Done ledger would read as a live carrier forever."""
    history_only = f"- raised the floor 6,500 -> {_PROBE_TOKEN} (factory iter 260)\n"
    assert guard.floor_claim_lines(history_only, _PROBE_TOKEN) == ()
    assert guard.published_floor_disagreements(
        {"ROADMAP.md": history_only}, _PROBE_FLOOR, carriers=()
    ) == []


def test_b6c_line_numbers_are_1_based_and_report_every_claim() -> None:
    text = f"x\n{_PROBE_TOKEN}+\ny\n{_PROBE_TOKEN}+\n"
    assert guard.floor_claim_lines(text, _PROBE_TOKEN) == (2, 4)


# --------------------------------------------------------------------------- #
# 7. the census does NOT carry a seventh copy of the floor
# --------------------------------------------------------------------------- #


def test_b7_the_census_derives_the_floor_from_the_readme() -> None:
    intro = _intro_text()
    match = re.search(r"\*\*([\d,]+)\+[^*]*tests\*\*", intro)
    assert match is not None, "the intro lost its suite-size claim"
    assert guard.published_floor() == int(match.group(1).replace(",", "")), (
        "the census's floor disagrees with the number the README actually publishes"
    )


def test_b7b_the_census_module_is_not_itself_an_undeclared_carrier() -> None:
    """A census holding its own copy of the token would be the carrier nothing checks."""
    census_rel = "tests/test_readme_and_ci_contract.py"
    text = (REPO_ROOT / census_rel).read_text(encoding="utf-8")
    token = guard.floor_token(guard.published_floor())
    assert guard.floor_claim_lines(text, token) == (), (
        f"{census_rel} hard-codes the live floor {token}, so it is a seventh carrier"
    )
    assert census_rel not in guard.PUBLISHED_FLOOR_CARRIERS


def test_b7c_the_floor_shape_is_asserted_not_formatted() -> None:
    """A caller handing in a live count instead of a rounded floor is a bug."""
    with pytest.raises(AssertionError):
        guard.floor_token(_live_count() if False else 5_499)
    assert guard.floor_token(EXPECTED_FLOOR).count(",") == 1


# --------------------------------------------------------------------------- #
# 8. the LIVE tree passes the census
# --------------------------------------------------------------------------- #


def test_b8_the_live_shipping_tree_has_zero_carrier_disagreements() -> None:
    sources = guard.tracked_text_sources()
    assert "README.md" in sources, "the census domain returned no README"
    assert guard.published_floor_disagreements(sources, guard.published_floor()) == []


def test_b8b_the_census_domain_is_git_ls_files_only() -> None:
    """An untracked scratch file must not be able to manufacture a finding."""
    sources = guard.tracked_text_sources()
    tracked = set(_tracked_paths())
    strays = sorted(set(sources) - tracked)
    assert strays == [], f"the census read files git does not track: {strays[:5]}"
    assert not any(key.startswith((".venv/", "state/")) for key in sources)


# --------------------------------------------------------------------------- #
# 9. the measured blind spot is not LIVE on the shipping tree
# --------------------------------------------------------------------------- #


def test_b9_no_tracked_line_pairs_the_live_token_with_a_unicode_arrow() -> None:
    """See the docstring: the exclusion is ASCII-only, and this repo uses both arrows.

    This pins only the narrow live fact. It is not an assertion that U+2192 SHOULD be
    excluded -- the spec does not say so -- but a line pairing the two would read as a
    live claim and, on an undeclared file, red a public build.
    """
    token = guard.floor_token(guard.published_floor())
    offenders: list[str] = []
    for path, text in guard.tracked_text_sources().items():
        for number, line in enumerate(text.splitlines(), start=1):
            if token in line and "\u2192" in line:
                offenders.append(f"{path}:{number}")
    assert offenders == [], (
        "these lines pair the live floor token with a U+2192 arrow, which the "
        f"ASCII-only history exclusion cannot see: {offenders}"
    )
