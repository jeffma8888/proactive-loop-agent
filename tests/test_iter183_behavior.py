"""Iteration 183 behavior oracle -- README <-> Makefile ``.PHONY`` documentation binding.

This iteration's deliverable has two halves:

* the CORRECTED ARTIFACT -- the two shipped-but-undocumented ``make`` targets
  (``check-matrix``, ``readme-headroom``) are now documented in ``README.md`` below the
  human-owned ``PORTFOLIO INTRO`` marker, saying what each is FOR;
* the PERMANENT GUARD -- ``tests/test_makefile_readme_contract.py`` reds the build when
  the NEXT ``.PHONY`` target ships undocumented.

This module is the iteration-scoped oracle for both. It differs from the permanent guard
on purpose, and the difference is the point: the guard carries anti-vacuity FLOORS
(``MIN_PHONY_TARGETS = 5``) so that a future iteration which legitimately adds a
documented target is not reddened by it, whereas an iteration oracle may pin the EXACT
snapshot measured today. Pinning that snapshot here is what makes the guard's floor safe
to keep loose.

Black-box: the only inputs are two tracked text files (``Makefile``, ``README.md``), the
guard module's pure helpers, and ``pyproject.toml``. No ``proactive_loop`` import, no
subprocess, no ``tmp_path``, no clock, no network. Nothing asserts on indentation or
docstring text, so the 3.12/3.13 matrix legs cannot diverge here.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# The deliverable under test. Importing the guard's pure helpers (rather than
# reimplementing the matcher) is deliberate: behaviors 5 and 6 must prove that the
# SHIPPED checker is hyphen-aware, and a private copy of the regex would prove only that
# this file is.
from tests.test_makefile_readme_contract import (
    MARKER,
    phony_targets,
    readme_below_marker,
    undocumented_targets,
)

REPO = Path(__file__).resolve().parents[1]
README = REPO / "README.md"
MAKEFILE = REPO / "Makefile"
PYPROJECT = REPO / "pyproject.toml"
GUARD_MODULE = REPO / "tests" / "test_makefile_readme_contract.py"

# Behavior 1: the exact ``.PHONY`` set, kept CURRENT rather than frozen at this
# iteration. It was nine developer entry points when this module shipped, two of which
# were undocumented before that change; factory iter 277 added ``help`` (bare ``make``
# now prints a listing instead of running a network install), so this pin moved with
# the Makefile in the same commit -- which is exactly what an exact-set pin is for.
EXPECTED_PHONY_TARGETS = frozenset(
    {
        "help",
        "setup",
        "test",
        "cov",
        "typecheck",
        "readme-headroom",
        "demo",
        "clean",
        "check",
        "check-matrix",
    }
)

# Behavior 2/3: the two targets this iteration exists to document.
NEWLY_DOCUMENTED = ("check-matrix", "readme-headroom")

# Behavior 7: verbatim anchors from the frozen portfolio intro. Prose only -- the three
# carve-out NUMBERS in the intro are excluded, because the operator directive permits an
# automated contributor to correct exactly those.
FROZEN_INTRO_ANCHORS = (
    "# proactive-loop-agent",
    "### What this project demonstrates",
    "Most agents wait for a human to hand them a goal.",
)


def _readme() -> str:
    return README.read_text(encoding="utf-8")


def _below() -> str:
    return readme_below_marker(_readme())


def _above() -> str:
    above, separator, _ = _readme().partition(MARKER)
    assert separator, f"README.md lost its {MARKER!r} marker"
    return above


def _block_introducing(section_text: str, target: str) -> str:
    """The list item (bullet plus its wrapped continuation lines) that introduces ``target``.

    Behavior 8 asks whether the documentation says something TRUE AND USEFUL rather than
    merely spelling the token, so the assertion needs the sentence around the mention, not
    the whole 59 KB section -- against which any keyword would match somewhere.
    """
    mention = re.compile(rf"(?<![\w-]){re.escape(target)}(?![\w-])")
    lines = section_text.splitlines()
    start = next((i for i, line in enumerate(lines) if mention.search(line)), None)
    assert start is not None, f"{target!r} is not mentioned below the marker at all"
    block = [lines[start]]
    for line in lines[start + 1 :]:
        if not line.strip() or line.lstrip().startswith(("- ", "* ", "#")):
            break
        block.append(line)
    return "\n".join(block)


# ==========================================================================
# Behavior 1 -- ground fact: the domain is known and non-empty
# ==========================================================================


def test_behavior_1_phony_set_is_exactly_the_measured_targets() -> None:
    parsed = phony_targets(MAKEFILE.read_text(encoding="utf-8"))
    assert parsed, "an empty .PHONY set would make every membership check below vacuous"
    assert parsed == EXPECTED_PHONY_TARGETS, (
        "the Makefile's .PHONY set moved away from this iteration's measured snapshot: "
        f"unexpected {sorted(parsed - EXPECTED_PHONY_TARGETS)}, "
        f"missing {sorted(EXPECTED_PHONY_TARGETS - parsed)}. A new target must be "
        "documented in README below the marker in the same commit that adds it."
    )


def test_behavior_1_a_missing_phony_declaration_fails_instead_of_reading_as_clean() -> None:
    """The fail-open this guard exists to prevent: no targets parsed != nothing undocumented."""
    with pytest.raises(AssertionError):
        phony_targets("test:\n\tuv run pytest\n")


# ==========================================================================
# Behaviors 2 and 3 -- both defects are fixed
# ==========================================================================


@pytest.mark.parametrize("target", NEWLY_DOCUMENTED)
def test_behaviors_2_and_3_the_two_undocumented_targets_are_now_documented(target: str) -> None:
    assert undocumented_targets(_below(), [target]) == [], (
        f"'make {target}' is a shipped developer entry point that README below the "
        f"{MARKER!r} marker never names"
    )


@pytest.mark.parametrize("target", NEWLY_DOCUMENTED)
def test_behaviors_2_and_3_the_fix_landed_below_the_marker_not_above_it(target: str) -> None:
    """The frozen intro may not carry the fix: an automated contributor could not maintain it."""
    assert undocumented_targets(_above(), [target]) == [target], (
        f"{target!r} appears ABOVE the human-owned marker, in prose automated "
        "contributors are forbidden to edit"
    )


# ==========================================================================
# Behavior 4 -- the drift guard reports the missing list, and today it is empty
# ==========================================================================


def test_behavior_4_every_phony_target_is_documented_below_the_marker() -> None:
    missing = undocumented_targets(_below(), phony_targets(MAKEFILE.read_text(encoding="utf-8")))
    assert missing == [], f"undocumented Makefile targets in README: {missing}"


def test_behavior_4_the_checker_returns_a_sorted_list_naming_what_is_missing() -> None:
    """The report shape the failure message depends on: sorted names, not a bool."""
    reported = undocumented_targets("documents nothing", ["typecheck", "clean", "demo"])
    assert reported == ["clean", "demo", "typecheck"]


# ==========================================================================
# Behavior 5 -- boundary-awareness on the two measured fail-open shapes
# ==========================================================================


def test_behavior_5_the_word_checkpoint_does_not_document_the_check_target() -> None:
    """Measured: 'checkpoint' occurs 17x in this README and contains 'check'."""
    assert undocumented_targets("an atomic checkpoint under .pla_runs/", ["check"]) == ["check"]


def test_behavior_5_a_longer_hyphenated_target_does_not_document_its_prefix() -> None:
    assert undocumented_targets("make check-matrix", ["check"]) == ["check"]


def test_behavior_5_the_hyphenated_target_still_documents_itself() -> None:
    """The other side of the same case: hyphen-awareness must not be over-strict."""
    assert undocumented_targets("make check-matrix", ["check-matrix"]) == []


def test_behavior_5_the_live_readme_documents_check_on_its_own_merits() -> None:
    """Anti-vacuity for behavior 4: 'check' must pass on a real mention, not on 'checkpoint'."""
    below = _below()
    assert "checkpoint" in below, "the substring hazard has gone -- re-derive this case"
    assert undocumented_targets(below, ["check"]) == []


# ==========================================================================
# Behavior 6 -- two-sided negative control on planted text, every member
# ==========================================================================


def test_behavior_6_omitting_any_single_target_is_reported_as_exactly_that_target() -> None:
    """Run over EVERY member, not a sample: 'omitted == check' is the only case that
    proves hyphen-awareness, because the planted text still contains 'make check-matrix'."""
    targets = sorted(EXPECTED_PHONY_TARGETS)
    for omitted in targets:
        planted = " ".join(f"`make {name}`" for name in targets if name != omitted)
        assert undocumented_targets(planted, targets) == [omitted], (
            f"a section documenting all but {omitted!r} must report exactly [{omitted!r}]"
        )


def test_behavior_6_a_section_documenting_all_of_them_reports_nothing_missing() -> None:
    targets = sorted(EXPECTED_PHONY_TARGETS)
    assert undocumented_targets(" ".join(f"`make {n}`" for n in targets), targets) == []


def test_behavior_6_deleting_the_fix_from_a_readme_copy_fires_the_guard() -> None:
    """Proves behavior 4 is not vacuous: the live text, minus the fix, is caught."""
    mutilated = re.sub(r"(?<![\w-])check-matrix(?![\w-])", "REMOVED", _below())
    assert undocumented_targets(mutilated, EXPECTED_PHONY_TARGETS) == ["check-matrix"]


# ==========================================================================
# Behavior 7 -- nothing above the human-owned marker moved
# ==========================================================================


@pytest.mark.parametrize("anchor", FROZEN_INTRO_ANCHORS)
def test_behavior_7_the_frozen_portfolio_intro_is_still_verbatim(anchor: str) -> None:
    assert anchor in _above(), (
        f"the human-owned portfolio intro lost {anchor!r}; prose above the {MARKER!r} "
        "marker must never be rewritten or restructured by an automated contributor"
    )


def test_behavior_7_the_marker_still_splits_the_readme_into_two_real_halves() -> None:
    readme = _readme()
    above, below = _above(), _below()
    assert above and below, "the marker must split the README, not open or close it"
    assert len(below) < len(readme)


# ==========================================================================
# Behavior 8 -- the documentation says something true and useful
# ==========================================================================

# (target, required keyword, alternatives of which at least one must appear).
USEFULNESS_CASES = (
    ("check-matrix", "matrix", ("3.13", "interpreter")),
    ("readme-headroom", "headroom", ("floor", "stale")),
)


@pytest.mark.parametrize(("target", "required", "alternatives"), USEFULNESS_CASES)
def test_behavior_8_the_introducing_block_explains_what_the_target_is_for(
    target: str, required: str, alternatives: tuple[str, ...]
) -> None:
    """Asserted on the LIST ITEM around the mention, not on the whole 59 KB section.

    Scope is the whole point: against the full section every one of these keywords matches
    somewhere else, so a section-wide assertion would pass vacuously. Bare-token
    documentation ("see `make check-matrix`") satisfies behaviors 2-4 while teaching a
    reader nothing, and this is the behavior that rules that out.
    """
    block = _block_introducing(_below(), target)
    assert required in block, (
        f"the README block introducing 'make {target}' never says {required!r}, so it "
        f"documents the token without saying what the target is FOR:\n{block}"
    )
    assert any(word in block for word in alternatives), (
        f"the block introducing 'make {target}' names none of {alternatives}, so a reader "
        f"cannot tell why they would run it:\n{block}"
    )


def test_behavior_8_the_block_extractor_is_scoped_to_one_list_item() -> None:
    """Negative control for the extractor: it must not swallow the NEXT bullet.

    Without this, behavior 8 could pass on keywords belonging to a neighbouring target --
    the same vacuity as asserting against the whole section, just smaller.
    """
    planted = "- `make alpha` -- does A\n  wrapped continuation\n- `make beta` -- 3.13 only\n"
    block = _block_introducing(planted, "alpha")
    assert "wrapped continuation" in block, "a wrapped continuation line belongs to the item"
    assert "beta" not in block and "3.13" not in block, (
        "the extractor leaked the next list item, so behavior 8 could pass on a "
        f"neighbour's keywords: {block!r}"
    )


# ==========================================================================
# Behavior 9 -- no runtime or dependency movement (fresh-clone-safe half)
# ==========================================================================


def test_behavior_9_the_runtime_dependency_set_is_still_pydantic_only() -> None:
    """Offline-first invariant: this iteration is docs plus tests, so nothing may be added."""
    text = PYPROJECT.read_text(encoding="utf-8")
    block = text.split("dependencies = [", 1)[1].split("]", 1)[0]
    declared = re.findall(r'"([^"]+)"', block)
    assert [d for d in declared if not d.startswith("pydantic")] == [], (
        f"runtime dependencies moved beyond pydantic: {declared}"
    )


def test_behavior_9_this_iteration_adds_no_coupling_to_the_product_package() -> None:
    """A docs-and-tests iteration must not import ``src/``; if it did, it was not one."""
    for module in (GUARD_MODULE, Path(__file__)):
        source = module.read_text(encoding="utf-8")
        assert not re.search(r"^\s*(from|import)\s+proactive_loop", source, re.MULTILINE), (
            f"{module.name} imports the product package, so this is no longer a "
            "documentation-only change"
        )
