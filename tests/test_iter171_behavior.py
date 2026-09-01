"""Black-box behavior tests for state-dir iteration 166 (ships as ``factory iter 171``):
the iter-143 collection-cleanliness oracle is re-keyed onto a PURE, ONE-DIRECTIONAL
violation helper that ignores coverage parallel-data files written by concurrent
xdist workers.

Why this exists.  The public build went RED at ``c07b267`` (CI run 31924267469) on::

    assert after == before, f"...dirtied the tree: {sorted(after - before)}"
    AssertionError: the collection subprocess dirtied the tree: []
    assert set() == {'?? .coverage.runnervmzvulz.pid5020.X1lSglDx.He8Yd0w110Hh'}

Two defects in one line.  The equality was BIDIRECTIONAL, so a file that VANISHED
during the window failed an assertion about the tree being DIRTIED -- and the
message, built from ``sorted(after - before)``, printed ``[]``: an oracle that
cannot name its own cause.  And the entry was a foreign coverage parallel-data
file, so the test was measuring the whole concurrent suite rather than its own
``--collect-only`` child.

Coverage (numbered to match the iteration spec's Expected Behaviors):

1. ``collection_tree_violations`` is a module-level function of two porcelain-line
   iterables returning ``list[str]``.
2. Directional: an entry in ``before`` and absent from ``after`` is NOT a violation.
3. Newly-present entries ARE violations, returned sorted.
4. The exact CI-observed foreign artifact is excluded, in BOTH orderings of the race.
5. The exclusion is NARROW: ``.coverage``, ``htmlcov/`` and ``.pytest_cache/`` newly
   present are still violations, so a genuinely dirty collection still fails.
6. Pure: correct after ``subprocess`` / ``REPO`` / ``README`` are monkeypatched to
   garbage -- the proof shape iter-143 behavior 4 already uses for
   ``suite_size_problems``.
7. The iter-143 test asserts the helper returns ``[]`` and interpolates that list, so
   a real violation names the offending entries.
8. The pytest/coverage artifact scan in that test is re-keyed onto the violation set,
   not the whole ``after`` set.
9. The floor-and-freshness half of that test is unchanged and still passes.
10. ``PUBLISHED_FLOOR``, ``STALE_FLOOR_TOKEN``, ``SUITE_SIZE_SLACK`` and the README's
    published claim are untouched by this iteration. These pins track the LIVE
    floor, not iter-171's: they were re-keyed 4,800 -> 4,900 at factory iter 207,
    4,900 -> 5,000 at factory iter 212 and 5,000 -> 5,100 at factory iter 242 and
    5,100 -> 5,200 at factory iter 245 and 5,200 -> 5,300 at factory iter 251 and 5,300 -> 5,400
    at factory iter 255 and 5,400 -> 5,500 at factory iter 260, when
    suite growth forced the bump the iter-143 module owns.

ISOLATION: written against the spec's Expected Behaviors and the public helper's
observable answers only.  Behaviors 7-9 are properties OF A TEST MODULE, so they are
measured on ``tests/test_iter143_behavior.py`` as source text with ``ast`` -- reading
``tests/`` is inside this role's contract, and no ``src/`` module, engineer note or
diff was read.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from tests import test_readme_and_ci_contract as guard

REPO = Path(__file__).resolve().parents[1]
README = REPO / "README.md"
ITER143 = REPO / "tests" / "test_iter143_behavior.py"

# The verbatim porcelain entry from the red 3.13 job of CI run 31924267469.
CI_ARTIFACT = "?? .coverage.runnervmzvulz.pid5020.X1lSglDx.He8Yd0w110Hh"

# The oracle under test lives in this function of the iter-143 module.
ORACLE = "test_the_live_count_is_measured_and_agrees_with_the_published_floor"


def _oracle_source() -> str:
    """The source text of the iter-143 oracle function, located by AST, never by line number.

    A line-number anchor would silently slide onto a neighbouring function the next
    time that module is edited, so the function is found by name and its own
    ``end_lineno`` bounds the segment.
    """
    text = ITER143.read_text(encoding="utf-8")
    tree = ast.parse(text)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == ORACLE:
            return ast.get_source_segment(text, node) or ""
    raise AssertionError(f"{ITER143.name} no longer defines {ORACLE}()")


# --------------------------------------------------------------------------- #
# 1. the helper exists with the shape the spec names
# --------------------------------------------------------------------------- #


def test_b01_the_violation_helper_is_a_module_level_function_of_two_line_sets() -> None:
    helper = getattr(guard, "collection_tree_violations", None)
    assert callable(helper), (
        "tests/test_readme_and_ci_contract.py must expose a module-level "
        "collection_tree_violations(before, after)"
    )
    out = helper({"?? kept"}, {"?? kept", "?? appeared"})
    assert isinstance(out, list), f"expected a list, got {type(out).__name__}"
    assert all(isinstance(item, str) for item in out), out
    assert out == ["?? appeared"], out


def test_b01_the_helper_accepts_any_iterable_not_only_sets() -> None:
    """The spec types the parameters as iterables of lines, so a list must work."""
    assert guard.collection_tree_violations(["?? a"], ["?? a", "?? b"]) == ["?? b"]
    assert guard.collection_tree_violations((), iter(["?? b", "?? a"])) == ["?? a", "?? b"]


# --------------------------------------------------------------------------- #
# 2. directional -- a vanished entry is not a defect
# --------------------------------------------------------------------------- #


def test_b02_an_entry_that_vanished_during_the_window_is_not_a_violation() -> None:
    assert guard.collection_tree_violations({"?? .coverage.h.pid1.a.b"}, set()) == []


def test_b02_a_vanished_entry_is_not_a_violation_even_when_it_is_ordinary() -> None:
    """Directionality is a property of the diff, not of the ignore list.

    Without this, behavior 2 could pass purely because the CI filename happens to
    be ignored, leaving a bidirectional equality in place for every other path.
    """
    assert guard.collection_tree_violations({"?? scratch.txt", " M README.md"}, set()) == []


def test_b02_a_vanished_entry_does_not_mask_a_simultaneous_new_one() -> None:
    before = {"?? gone.txt"}
    after = {"?? arrived.txt"}
    assert guard.collection_tree_violations(before, after) == ["?? arrived.txt"]


# --------------------------------------------------------------------------- #
# 3. new entries are violations, sorted
# --------------------------------------------------------------------------- #


def test_b03_newly_present_entries_are_returned_sorted() -> None:
    assert guard.collection_tree_violations(set(), {"?? b", "?? a"}) == ["?? a", "?? b"]


def test_b03_entries_present_in_both_samples_are_not_violations() -> None:
    """Pre-existing dirt is the ambient tree's business, not the child process's."""
    shared = {" M src/proactive_loop/cli.py", "?? untracked-before.txt"}
    assert guard.collection_tree_violations(shared, shared) == []
    assert guard.collection_tree_violations(shared, shared | {"?? new.txt"}) == ["?? new.txt"]


# --------------------------------------------------------------------------- #
# 4. the exact CI-observed artifact is excluded, in both orderings
# --------------------------------------------------------------------------- #


def test_b04_the_exact_ci_observed_coverage_artifact_is_excluded_when_it_appears() -> None:
    assert guard.collection_tree_violations(set(), {CI_ARTIFACT}) == []


def test_b04_the_exact_ci_observed_coverage_artifact_is_excluded_when_it_vanishes() -> None:
    """The failing ordering in run 31924267469: present in ``before``, gone from ``after``."""
    assert guard.collection_tree_violations({CI_ARTIFACT}, set()) == []


def test_b04_the_red_build_scenario_reproduced_end_to_end_is_green() -> None:
    """The literal samples from the red job, plus its assertion, now hold.

    ``before`` held the foreign artifact and ``after`` did not; the shipped oracle
    asserts the helper returns ``[]`` for exactly that pair.
    """
    before = {CI_ARTIFACT}
    after: set[str] = set()
    violations = guard.collection_tree_violations(before, after)
    assert violations == [], violations
    assert not [line for line in violations if ".pytest_cache" in line or ".coverage" in line]


def test_b04_the_exclusion_is_keyed_on_the_path_not_on_the_status_prefix() -> None:
    """A coverage parallel-data file is noise whatever porcelain status it carries."""
    for line in (
        f"?? {CI_ARTIFACT[3:]}",
        f" M {CI_ARTIFACT[3:]}",
        f"A  {CI_ARTIFACT[3:]}",
    ):
        assert guard.collection_tree_violations(set(), {line}) == [], line


def test_b04_other_parallel_data_filenames_of_the_same_class_are_excluded() -> None:
    """The class is ``.coverage.<anything>``, which is what its writer's glob deletes.

    Keying on the one observed filename would leave the guard red on the very next
    CI runner, whose hostname, pid and random suffixes all differ.
    """
    for name in (
        ".coverage.macbook.pid1.aB3.9zQ",
        ".coverage.runner-abc.pid99999.xxxx.yyyy",
        ".coverage.h.1",
    ):
        assert guard.collection_tree_violations(set(), {f"?? {name}"}) == [], name


# --------------------------------------------------------------------------- #
# 5. the exclusion is NARROW -- a genuinely dirty collection still fails
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("artifact", [".coverage", "htmlcov/", ".pytest_cache/"])
def test_b05_a_real_collection_artifact_is_still_a_violation(artifact: str) -> None:
    line = f"?? {artifact}"
    assert guard.collection_tree_violations(set(), {line}) == [line], (
        f"{artifact} must still fail the guard -- the coverage ignore is not a blanket "
        "'.coverage' ignore"
    )


def test_b05_all_three_real_artifacts_are_reported_together_and_sorted() -> None:
    after = {"?? htmlcov/", "?? .pytest_cache/", "?? .coverage", f"?? {CI_ARTIFACT[3:]}"}
    assert guard.collection_tree_violations(set(), after) == [
        "?? .coverage",
        "?? .pytest_cache/",
        "?? htmlcov/",
    ]


def test_b05_a_file_inside_a_coverage_named_directory_is_still_a_violation() -> None:
    """``.coverage.d/leak.json`` is not the flat parallel-data class and must fail."""
    assert guard.collection_tree_violations(set(), {"?? .coverage.d/leak.json"}) == [
        "?? .coverage.d/leak.json"
    ]


def test_b05_an_ordinary_new_file_is_still_a_violation() -> None:
    assert guard.collection_tree_violations(set(), {"?? demo-out/slate.json"}) == [
        "?? demo-out/slate.json"
    ]


# --------------------------------------------------------------------------- #
# 6. pure -- no file read, no subprocess
# --------------------------------------------------------------------------- #


def test_b06_the_helper_is_pure_under_a_sabotaged_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same proof shape iter-143 behavior 4 uses for ``suite_size_problems``.

    If the helper read a file or spawned a process, replacing the module's
    ``subprocess`` handle and its path constants with invalid values would break it.
    """
    monkeypatch.setattr(guard, "subprocess", None, raising=True)
    monkeypatch.setattr(guard, "REPO", Path("/nonexistent/iter171"), raising=True)
    monkeypatch.setattr(guard, "README", Path("/nonexistent/iter171/README.md"), raising=True)

    assert guard.collection_tree_violations({CI_ARTIFACT}, set()) == []
    assert guard.collection_tree_violations(set(), {"?? .coverage"}) == ["?? .coverage"]
    assert guard.collection_tree_violations(set(), {"?? b", "?? a"}) == ["?? a", "?? b"]


def test_b06_the_helper_writes_nothing_and_mutates_neither_argument(tmp_path: Path) -> None:
    before = {CI_ARTIFACT, "?? kept"}
    after = {"?? kept", "?? .coverage"}
    snapshot_before, snapshot_after = set(before), set(after)

    assert guard.collection_tree_violations(before, after) == ["?? .coverage"]

    assert before == snapshot_before, "the helper mutated its `before` argument"
    assert after == snapshot_after, "the helper mutated its `after` argument"
    assert list(tmp_path.iterdir()) == [], "the helper wrote to the filesystem"


# --------------------------------------------------------------------------- #
# 7 + 8. the iter-143 oracle is re-keyed onto the helper
# --------------------------------------------------------------------------- #


def test_b07_the_iter143_oracle_asserts_the_helper_and_names_its_offenders() -> None:
    source = _oracle_source()
    assert "guard.collection_tree_violations(before, after)" in source, source
    assert re.search(r"assert\s+violations\s*==\s*\[\]", source), source
    assert "{violations}" in source, (
        "the failure message must interpolate the violation list, so a real defect "
        "names the offending porcelain entries"
    )


def test_b07_the_bidirectional_equality_and_its_empty_message_are_gone() -> None:
    """The two halves of the red-build defect must both be absent from that function."""
    source = _oracle_source()
    assert "assert after == before" not in source, source
    assert "sorted(after - before)" not in source, source


def test_b08_the_artifact_scan_is_keyed_on_the_violation_set_not_the_whole_after_set() -> None:
    source = _oracle_source()
    assert ".pytest_cache" in source, "the artifact scan must still exist"
    assert "for line in violations" in source, source
    assert "for line in after" not in source, (
        "the scan must not iterate the whole `after` sample -- a concurrent worker's "
        "transient artifact would fail it"
    )


# --------------------------------------------------------------------------- #
# 9 + 10. the floor half, and the constants, are untouched
# --------------------------------------------------------------------------- #


def test_b09_the_floor_and_freshness_half_of_the_oracle_is_unchanged() -> None:
    source = _oracle_source()
    assert "live = guard.collect_live_test_count()" in source, source
    assert "live >= PUBLISHED_FLOOR" in source, source
    assert "live - PUBLISHED_FLOOR < guard.SUITE_SIZE_SLACK" in source, source
    assert "guard.suite_size_problems(_real_intro(), live)" in source, source


def test_b09_the_floor_verdict_the_oracle_relies_on_still_bites(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Anti-vacuity for behavior 9: the freshness rule the oracle calls still fires.

    Synthetic counts only -- no collection subprocess is spawned here, so this costs
    nothing and cannot race a concurrent worker.
    """
    intro = guard._intro()
    assert guard.suite_size_problems(intro, 5500 + guard.SUITE_SIZE_SLACK) != [], (
        "a floor a full slack behind the live count must be reported as stale"
    )
    assert guard.suite_size_problems(intro, 5500 + 1) == [], (
        "a floor one test behind the live count must be accepted as fresh"
    )
    monkeypatch.setattr(guard, "SUITE_SIZE_SLACK", 1, raising=True)
    assert guard.suite_size_problems(intro, 5500 + 1) != [], (
        "the staleness verdict does not derive from SUITE_SIZE_SLACK"
    )


def test_b10_the_published_floor_constants_are_the_head_values() -> None:
    iter143 = ITER143.read_text(encoding="utf-8")
    assert "PUBLISHED_FLOOR = 5500" in iter143, "the published floor moved unexpectedly"
    assert 'STALE_FLOOR_TOKEN = "5,400"' in iter143, "the stale-floor token moved unexpectedly"
    assert guard.SUITE_SIZE_SLACK == 500, guard.SUITE_SIZE_SLACK


def test_b10_the_readme_still_publishes_the_same_floor_claim() -> None:
    intro = guard._intro()
    claim = guard.SUITE_CLAIM.search(intro)
    assert claim is not None, "the README lost its suite-size claim"
    assert "5,500" in claim.group(0), claim.group(0)
    assert "5,400" not in intro, "the stale floor token reappeared in the README"
