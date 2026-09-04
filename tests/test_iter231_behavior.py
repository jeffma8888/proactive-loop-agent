"""Iteration 253 behavior oracle -- the README/Makefile drift guard adopts the
``make <target>`` INVOCATION form, and ``make setup`` / ``make clean`` are documented.

The deliverable has two halves, and this module grades both:

* the TIGHTENED PREDICATE -- ``tests/test_makefile_readme_contract.documents_target``
  now counts a target as documented only when README below the human-owned marker names
  it in ``make <target>`` invocation form. Mere presence of the word was the previous
  rule and was MEASURED vacuous for two of the nine targets: below the marker,
  ``setup``'s only occurrence was the phrase ``argparse setup.`` and ``clean``'s only
  two were ``sees one clean document`` -- documentation by accidental English.
* the CORRECTED ARTIFACT -- ``make setup`` and ``make clean`` are now taught below the
  marker in the house bullet style, each saying what the target is FOR, which is what
  keeps the tightened live check green on purpose rather than by luck.

Black-box: the inputs are two tracked text files (``README.md``, ``Makefile``), the
guard module's own pure helpers, and the guard module's source text. No
``proactive_loop`` import, no subprocess, no ``tmp_path`` tree, no network, no clock, no
gitignored path -- so this passes identically in a fresh clone.

Two deliberate choices in how the artifact half is graded, because each is a place a
lazier oracle would pass vacuously:

* Behaviors 5 and 6 locate a target's documentation block by the INVOCATION form, never
  by the bare word. Locating ``setup`` by its bare token would have found the phrase
  ``argparse setup.`` -- the very fail-open this iteration closes -- and graded the
  wrong paragraph.
* Behavior 7 pins the frozen intro with verbatim PROSE anchors rather than diffing it
  against ``git show HEAD:README.md``. A ``HEAD`` diff is the letter of "byte-identical
  at HEAD" but reds any FUTURE iteration during its own pre-commit stages, and it would
  also red the operator's standing carve-out permitting exactly three NUMBERS in the
  intro to be corrected. The anchors carry no carve-out number. This substitution is
  noted as PM feedback in ``tester.md``.

Nothing here asserts on indentation or on docstring formatting, so the CI 3.12/3.13
matrix legs cannot diverge.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# The shipped deliverable. Importing the guard's own helpers -- rather than
# reimplementing the matcher -- is the point: these behaviors are claims about the
# SHIPPED predicate, and a private copy of the regex would only prove this file works.
from tests.test_makefile_readme_contract import (
    MARKER,
    documents_target,
    phony_targets,
    readme_below_marker,
    undocumented_targets,
)

REPO = Path(__file__).resolve().parents[1]
README = REPO / "README.md"
MAKEFILE = REPO / "Makefile"
GUARD_MODULE = REPO / "tests" / "test_makefile_readme_contract.py"

# Behavior 4: the ``.PHONY`` snapshot, kept CURRENT rather than frozen at this
# iteration. It added no target itself, so the count was nine here; factory iter 277
# added ``help`` (bare ``make`` now prints a listing instead of running a network
# install) and moved this pin -- and the count below -- to ten in the same commit as
# the Makefile. An oracle may pin the exact set where the permanent guard
# (``test_makefile_readme_contract``) deliberately keeps a loose floor.
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

# Behaviors 5, 6 and 7: the two targets this iteration documents for real.
NEWLY_DOCUMENTED = ("setup", "clean")

# Behavior 3: the live README's ONLY sub-marker mentions of those two words before this
# change, planted verbatim. Planted rather than read from the file on purpose -- the
# README is fixed in this same commit, so a live read would stop exercising the defect
# the moment it was repaired, and the regression would become invisible.
ACCIDENTAL_ENGLISH = {
    "setup": "importing the library costs no argparse setup.",
    "clean": "`pla scan ... --format json | jq` sees one clean document.",
}

# Behavior 7: verbatim prose anchors from the frozen portfolio intro. Prose only -- the
# three carve-out NUMBERS (collector count, CLI-verb count, tests floor) are excluded,
# because the operator directive REQUIRES an automated contributor to correct those.
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


def _invocation_count(text: str, target: str) -> int:
    """How many ``make <target>`` invocations ``text`` contains.

    A local copy of the accepted spelling is correct HERE and only here: behavior 7 is a
    claim about WHERE the invocations live (below the marker, never above), which needs a
    count, while the shipped helper answers a boolean. Behaviors 1-4 grade the shipped
    predicate itself.
    """
    return len(re.findall(rf"(?<![\w-])make[ \t]+{re.escape(target)}(?![\w-])", text))


def _block_introducing_invocation(section_text: str, target: str) -> str:
    """The list item (bullet plus wrapped continuation lines) introducing ``make <target>``.

    Located by the INVOCATION form deliberately: locating ``setup`` by its bare token
    would land on ``argparse setup.``, the accidental-English phrase this iteration
    exists to stop crediting, and would then grade prose that documents nothing.

    Behaviors 5 and 6 ask whether the new documentation says something TRUE AND USEFUL,
    so the assertion needs the sentence around the mention rather than the whole 69 KB
    section, against which any keyword would match somewhere.
    """
    pattern = re.compile(rf"(?<![\w-])make[ \t]+{re.escape(target)}(?![\w-])")
    lines = section_text.splitlines()
    start = next((i for i, line in enumerate(lines) if pattern.search(line)), None)
    assert start is not None, (
        f"'make {target}' does not appear below the {MARKER!r} marker at all, so there "
        "is no documentation block to grade"
    )
    block = [lines[start]]
    for line in lines[start + 1 :]:
        if not line.strip() or line.lstrip().startswith(("- ", "* ", "#")):
            break
        block.append(line)
    return "\n".join(block)


# ==========================================================================
# Behavior 1 -- the matcher requires the invocation form
# ==========================================================================


@pytest.mark.parametrize(
    "text",
    ["`make check`", "(make check)", "make check\n", "make check", "run `make check`, then ship"],
)
def test_b1_the_invocation_form_is_admitted_through_surrounding_punctuation(text: str) -> None:
    """The boundary classes must still admit every invocation spelling README uses."""
    assert documents_target(text, "check") is True, text


@pytest.mark.parametrize(
    "text",
    [
        "run `check`, then ship",
        "the check target",
        "check",
        "make\ncheck",
        "cmake check",
    ],
)
def test_b1_a_bare_token_or_broken_invocation_does_not_document_the_target(text: str) -> None:
    """No ``make``, no adjacency, no credit.

    ``run `check`, then ship`` was ADMITTED by the previous presence rule and is now
    rejected: it teaches a reader no runnable command. ``make\\ncheck`` is the wrapped
    spelling a reader cannot copy, and ``cmake check`` is why the boundary BEFORE
    ``make`` is load-bearing.
    """
    assert documents_target(text, "check") is False, text


def test_b1_documents_target_returns_a_bool_not_a_match_object() -> None:
    """The report shape callers depend on."""
    assert documents_target("make check", "check") is True
    assert documents_target("nothing here", "check") is False


# ==========================================================================
# Behavior 2 -- hyphen-awareness survives the tightening, both directions
# ==========================================================================


def test_b2_a_longer_hyphenated_target_does_not_document_its_prefix() -> None:
    assert undocumented_targets("make check-matrix", ["check"]) == ["check"]


def test_b2_the_hyphenated_target_still_documents_itself() -> None:
    """The other side of the same case: hyphen-awareness must not be over-strict."""
    assert undocumented_targets("make check-matrix", ["check-matrix"]) == []


def test_b2_a_hyphenated_prefix_does_not_document_the_target() -> None:
    """``mypy-check`` is real README prose; it documents no target."""
    assert undocumented_targets("mypy-check the package", ["check"]) == ["check"]


def test_b2_the_measured_substring_fail_open_is_still_closed() -> None:
    """``checkpoint`` occurs many times in this README and contains ``check``."""
    assert undocumented_targets("an atomic checkpoint under .pla_runs/", ["check"]) == ["check"]


# ==========================================================================
# Behavior 3 -- the two accidental-English mentions no longer credit their target
# ==========================================================================


@pytest.mark.parametrize("target", NEWLY_DOCUMENTED)
def test_b3_accidental_english_no_longer_documents_its_target(target: str) -> None:
    """The measured defect, on planted text so it stays exercised after the README fix."""
    text = ACCIDENTAL_ENGLISH[target]
    assert undocumented_targets(text, [target]) == [target], (
        f"{text!r} must not credit the {target!r} target: it names no runnable command, "
        "and crediting it is the fail-open this iteration closes"
    )


@pytest.mark.parametrize("target", NEWLY_DOCUMENTED)
def test_b3_the_planted_text_really_contains_the_bare_word(target: str) -> None:
    """Anti-vacuity for the case above: the string must still exhibit the hazard.

    If the word were absent, the assertion would pass for the wrong reason -- it would
    prove nothing about the ``make`` anchor.
    """
    text = ACCIDENTAL_ENGLISH[target]
    assert re.search(rf"(?<![\w-]){re.escape(target)}(?![\w-])", text), text


# ==========================================================================
# Behavior 4 -- the live check is green under the stronger rule
# ==========================================================================


def test_b4_the_phony_set_is_exactly_the_measured_targets() -> None:
    parsed = phony_targets(MAKEFILE.read_text(encoding="utf-8"))
    assert parsed == EXPECTED_PHONY_TARGETS, (
        "the Makefile's .PHONY set moved away from this iteration's measured snapshot: "
        f"unexpected {sorted(parsed - EXPECTED_PHONY_TARGETS)}, "
        f"missing {sorted(EXPECTED_PHONY_TARGETS - parsed)}. A new target must be "
        "documented below the README marker in invocation form in the same commit."
    )
    assert len(parsed) == 10


def test_b4_every_phony_target_is_documented_in_invocation_form_below_the_marker() -> None:
    missing = undocumented_targets(_below(), phony_targets(MAKEFILE.read_text(encoding="utf-8")))
    assert missing == [], (
        f"undocumented Makefile targets in README below the {MARKER!r} marker: {missing}"
    )


def test_b4_the_live_section_is_the_large_reference_half_not_a_sliver() -> None:
    """Anti-vacuity: an empty or tiny domain would make the check above pass for free."""
    readme = _readme()
    below = readme_below_marker(readme)
    assert len(below) > 10_000
    assert len(below) < len(readme), "the marker must split the README, not open it"


# ==========================================================================
# Behavior 5 -- ``make setup`` is documented AND says what it is FOR
# ==========================================================================


def test_b5_the_make_setup_block_explains_the_locked_ci_equivalent_install() -> None:
    block = _block_introducing_invocation(_below(), "setup")
    assert "locked" in block, block
    assert ("CI" in block) or ("clone" in block), (
        "the `make setup` bullet must say what the target is FOR -- that it installs the "
        f"locked set CI installs, so a clone matches CI. Block was:\n{block}"
    )


def test_b5_the_make_setup_block_is_a_bullet_in_the_house_style() -> None:
    block = _block_introducing_invocation(_below(), "setup")
    assert block.lstrip().startswith("- "), block
    assert "`make setup`" in block, block


# ==========================================================================
# Behavior 6 -- ``make clean`` is documented AND says what it is FOR
# ==========================================================================


def test_b6_the_make_clean_block_names_the_run_state_and_the_generated_artifacts() -> None:
    block = _block_introducing_invocation(_below(), "clean")
    assert ".pla_runs" in block, block
    assert ("coverage" in block) or ("cache" in block), (
        "the `make clean` bullet must say what the target is FOR -- recovering a tree "
        f"dirtied by a run. Block was:\n{block}"
    )


def test_b6_the_make_clean_block_is_a_bullet_in_the_house_style() -> None:
    block = _block_introducing_invocation(_below(), "clean")
    assert block.lstrip().startswith("- "), block
    assert "`make clean`" in block, block


# ==========================================================================
# Behavior 7 -- the additions landed below the marker only
# ==========================================================================


@pytest.mark.parametrize("target", NEWLY_DOCUMENTED)
def test_b7_the_invocation_occurs_below_the_marker(target: str) -> None:
    assert _invocation_count(_below(), target) >= 1, (
        f"'make {target}' must be taught below the {MARKER!r} marker"
    )


@pytest.mark.parametrize("target", NEWLY_DOCUMENTED)
def test_b7_the_invocation_never_occurs_above_the_marker(target: str) -> None:
    """The frozen intro may not carry the fix: an automated contributor may not maintain it."""
    assert _invocation_count(_above(), target) == 0, (
        f"'make {target}' appears ABOVE the human-owned marker, in prose automated "
        "contributors are forbidden to restructure"
    )


def test_b7_the_frozen_portfolio_intro_prose_is_intact() -> None:
    """The stand-in for a byte diff against HEAD -- see this module's docstring.

    Each anchor must occur exactly once and above the marker, so neither a rewrite of the
    intro nor a copy of it into the editable half can pass.
    """
    above = _above()
    for anchor in FROZEN_INTRO_ANCHORS:
        assert above.count(anchor) == 1, f"frozen intro anchor changed or duplicated: {anchor!r}"


def test_b7_the_new_documentation_did_not_grow_the_frozen_half() -> None:
    """A second, size-shaped read on the same claim, insensitive to the number carve-out.

    The three numbers an automated contributor MAY correct are at most a few chars each,
    so a generous ceiling still catches a bullet block landing in the wrong half.
    """
    assert len(_above()) < 4_000, (
        "the region above the marker grew unexpectedly -- new reference prose belongs "
        "BELOW the marker"
    )


# ==========================================================================
# Behavior 8 -- the guard no longer carries the stale cost claim
# ==========================================================================


def test_b8_the_stale_four_target_price_is_gone_from_the_guard() -> None:
    source = GUARD_MODULE.read_text(encoding="utf-8")
    assert "to four" not in source, (
        "the guard's design decision 4 still prices the tightening at four newly-missing "
        "targets. That was re-measured as exactly ['clean', 'setup'] and the rule is now "
        "in force, so the module would contradict itself."
    )


def test_b8_the_guard_docstring_names_the_invocation_form_as_the_rule_in_force() -> None:
    source = GUARD_MODULE.read_text(encoding="utf-8")
    assert "INVOCATION" in source, source[:200]
    assert "['clean', 'setup']" in source, (
        "the guard must record the MEASURED set that made the tightening cheap, so the "
        "next reader does not re-derive it"
    )


def test_b8_the_old_presence_only_helper_name_is_gone() -> None:
    """The rename is part of the claim: the helper is an invocation matcher now."""
    source = GUARD_MODULE.read_text(encoding="utf-8")
    assert "def _invocation(" in source
    assert "def _mention(" not in source


# ==========================================================================
# Behavior 9 -- two-sided negative control over the live target set
# ==========================================================================


def test_b9_a_section_documenting_all_but_one_target_reports_exactly_that_one() -> None:
    targets = sorted(phony_targets(MAKEFILE.read_text(encoding="utf-8")))
    for omitted in targets:
        planted = " ".join(f"`make {name}`" for name in targets if name != omitted)
        assert undocumented_targets(planted, targets) == [omitted], (
            f"planting a section that documents every target except {omitted!r} in "
            "invocation form must report exactly that one"
        )


def test_b9_a_section_documenting_every_target_reports_nothing_missing() -> None:
    targets = sorted(phony_targets(MAKEFILE.read_text(encoding="utf-8")))
    planted = " ".join(f"`make {name}`" for name in targets)
    assert undocumented_targets(planted, targets) == []


def test_b9_a_section_documenting_the_words_but_never_the_commands_reports_them_all() -> None:
    """The tightening's whole point, stated over the live target set.

    Every target name is present as a bare token and NOT ONE is credited.
    """
    targets = sorted(phony_targets(MAKEFILE.read_text(encoding="utf-8")))
    planted = " ".join(f"the `{name}` step" for name in targets)
    assert undocumented_targets(planted, targets) == targets
