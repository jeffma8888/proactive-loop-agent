"""Drift guard binding ``README.md`` to the ``Makefile``'s ``.PHONY`` target set.

Why this file exists
The ``Makefile`` is this repo's developer entry point: nine targets, each with real
rationale in its own comment block. ``README.md`` is where a contributor -- and, on a
public portfolio repo, a reader -- actually looks for them, and nothing bound the two.
Measured at ``d4a39dc``, two of the nine occurred ZERO times in the 61 KB README under
every measurement (substring, word-boundary and ``make <target>`` form):

* ``check-matrix`` -- the second half of the local gate. README teaches ``make check``
  as THE local gate while the Makefile itself explains that ``check`` grades one
  interpreter leg and that ``check-matrix`` closes the other. "A failure reproducible
  only on the newer interpreter reaches CI unseen" is not hypothetical here; it is what
  factory iter 145 was reverted for.
* ``readme-headroom`` -- a gauge whose ONLY purpose is to keep the intro's published
  ``N,N00+ tests`` floor honest. The guard enforcing that floor is silent while green,
  so this gauge is the sole advance warning, and it was invisible to the person who
  needs it.

Both are now documented below the human-owned marker, and this module is the oracle
that reds the build when the NEXT target ships undocumented.

Four design decisions worth the reader's time
1. **The matcher is HYPHEN-aware, and that is the whole guard.** A substring matcher
   passes VACUOUSLY here, measured: ``checkpoint`` occurs 17 times in this README and
   contains ``check``, so a naive matcher reports the ``check`` target as documented on
   the strength of a word about atomic writes. A plain ``\\b`` word boundary is not
   enough either, because ``-`` is a non-word character: under ``\\bcheck\\b`` the
   string ``make check-matrix`` would document the DIFFERENT target ``check``, and
   ``mypy-check`` would document it too. So the boundary class is ``[\\w-]`` on both
   sides: a longer hyphenated target never documents its own prefix.
2. **The domain is the region BELOW the human-owned marker, and that is load-bearing.**
   Everything above it is frozen prose an automated contributor may not touch, so a
   target "documented" only up there could never be fixed by the process this guard
   steers. A synthetic case below proves the split is real rather than decorative.
3. **A missing ``.PHONY`` line, or a missing marker, RAISES.** Returning an empty set
   would read as "nothing is undocumented" -- the exact fail-open shape this repo keeps
   rediscovering. An empty domain makes every membership check pass, so both readers
   fail loudly instead, and the live check carries anti-vacuity floors.
4. **The rule is PRESENCE below the marker, not the ``make <target>`` invocation form.**
   Measured: ``setup`` and ``clean`` appear as words but never as ``make setup`` /
   ``make clean``, so an invocation-shaped rule would silently widen its own scope from
   the two genuinely-undocumented targets to four. Presence is the weaker claim and the
   honest one; a stronger form is a separate, deliberate decision.

Offline and cheap by construction: two tracked text files, one pure matcher, no product
import, no subprocess, no ``tmp_path`` tree, no network, no clock. Nothing here asserts
on indentation or docstring text, so the 3.12/3.13 matrix legs cannot diverge.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
MAKEFILE = REPO / "Makefile"
README = REPO / "README.md"

# The marker's TEXT ONLY. The live marker spells an EM DASH between the two halves
# (``PORTFOLIO INTRO -- human-owned``), so anchoring on the full phrase would red the
# build on a punctuation change this guard does not care about. Same choice
# ``test_readme_and_ci_contract.MARKER`` already makes.
MARKER = "PORTFOLIO INTRO"

# ``.PHONY: setup test cov ...``. Line-anchored so a ``.PHONY`` mentioned inside a
# comment or a recipe cannot be mistaken for a declaration.
PHONY_DECLARATION = re.compile(r"^\.PHONY:(?P<targets>.*)$", re.MULTILINE)

# Anti-vacuity floors for the LIVE check. Both sit far below today's measurements (9
# targets, 59,054 chars below the marker) and are floors rather than exact values on
# purpose: an exact pin here would red an innocent iteration for legitimately editing
# prose, while a floor only fires when the instrument itself has gone blind.
MIN_PHONY_TARGETS = 5
MIN_SECTION_CHARS = 10_000


def phony_targets(makefile_text: str) -> frozenset[str]:
    """Every target declared on the Makefile's ``.PHONY`` line(s).

    Raises rather than returning an empty set when no declaration is found: an empty
    target set makes every downstream membership check pass, so the guard would report
    perfect health precisely when it had lost its subject.
    """
    declarations = PHONY_DECLARATION.findall(makefile_text)
    assert declarations, (
        "no .PHONY declaration found in the Makefile text, so the set of developer "
        "entry points is unknown and this guard would pass vacuously. Refusing to "
        "treat 'no targets parsed' as 'nothing undocumented'."
    )
    targets = frozenset(name for declaration in declarations for name in declaration.split())
    assert targets, (
        "the Makefile's .PHONY line declares no targets at all; see the reason above"
    )
    return targets


def readme_below_marker(readme_text: str) -> str:
    """The README region automated contributors MAY edit: everything after the marker.

    The counterpart of ``test_readme_and_ci_contract._intro``, which returns the frozen
    half. Raises when the marker is gone, for the same reason as above -- and because a
    lost marker is itself a defect worth a red build.
    """
    _, separator, below = readme_text.partition(MARKER)
    assert separator, (
        f"README.md lost its {MARKER!r} marker, so the region automated contributors "
        "may edit cannot be identified and this guard has no domain"
    )
    return below


def _mention(target: str) -> re.Pattern[str]:
    """A boundary- AND hyphen-aware matcher for one target name.

    ``[\\w-]`` on both sides, not ``\\b``: see design decision 1 in the module
    docstring. ``re.escape`` because target names legitimately contain ``-``.
    """
    return re.compile(rf"(?<![\w-]){re.escape(target)}(?![\w-])")


def documents_target(section_text: str, target: str) -> bool:
    """Whether ``section_text`` mentions ``target`` as a standalone token."""
    return _mention(target).search(section_text) is not None


def undocumented_targets(section_text: str, targets: Iterable[str]) -> list[str]:
    """The sorted targets ``section_text`` never mentions.

    A pure function of ``(text, targets)`` -- no file read, no ambient state -- so the
    negative control below can be proven on planted text without mutating the repo.
    """
    return sorted(target for target in targets if not documents_target(section_text, target))


# ==========================================================================
# The live guard
# ==========================================================================


def test_readme_below_the_marker_documents_every_phony_target() -> None:
    """The binding this module exists for: no shipped ``make`` target is a secret."""
    targets = phony_targets(MAKEFILE.read_text(encoding="utf-8"))
    readme = README.read_text(encoding="utf-8")
    section = readme_below_marker(readme)

    assert len(targets) >= MIN_PHONY_TARGETS, (
        f"only {len(targets)} .PHONY targets parsed ({sorted(targets)}) -- below the "
        f"anti-vacuity floor of {MIN_PHONY_TARGETS}, so the parser has probably stopped "
        "recognizing the declaration rather than the Makefile having shrunk"
    )
    assert len(section) >= MIN_SECTION_CHARS, (
        f"only {len(section)} chars below the {MARKER!r} marker (floor "
        f"{MIN_SECTION_CHARS}) -- the domain is too small to be the real reference half, "
        "so this check would be near-vacuous"
    )
    assert len(section) < len(readme), "the marker must split the README, not open it"

    missing = undocumented_targets(section, targets)
    assert not missing, (
        f"these Makefile targets are undocumented in README.md below the {MARKER!r} "
        f"marker: {missing}. A shipped developer entry point that the README never "
        "names is invisible to every reader of this public repo -- document it in a "
        "reference section below the marker (never above it), saying what it is FOR."
    )


# ==========================================================================
# The readers fail loudly rather than returning an empty domain
# ==========================================================================


def test_the_phony_parser_fails_loudly_when_the_declaration_is_absent() -> None:
    with pytest.raises(AssertionError, match="no .PHONY declaration"):
        phony_targets("test:\n\tuv run pytest\n")


def test_the_phony_parser_ignores_a_phony_mentioned_inside_a_recipe() -> None:
    """Line-anchoring is what makes the declaration unambiguous."""
    text = "# talks about .PHONY: not-a-target\n.PHONY: test cov\ntest:\n\techo .PHONY: nope\n"
    assert phony_targets(text) == frozenset({"test", "cov"})


def test_the_marker_split_fails_loudly_when_the_marker_is_absent() -> None:
    with pytest.raises(AssertionError, match="lost its"):
        readme_below_marker("# a README with no marker at all\n")


def test_a_target_named_only_above_the_marker_is_reported_missing() -> None:
    """Proves the split is load-bearing: the frozen intro cannot document a target."""
    planted = f"# title\nRun `make check-matrix` first.\n<!-- {MARKER} -- human-owned -->\nprose\n"
    assert undocumented_targets(readme_below_marker(planted), ["check-matrix"]) == ["check-matrix"]


# ==========================================================================
# Boundary-awareness: the measured substring fail-open, both spellings
# ==========================================================================


def test_checkpoint_does_not_document_the_check_target() -> None:
    """The measured fail-open: ``checkpoint`` occurs 17 times in the live README."""
    assert undocumented_targets("an atomic checkpoint under .pla_runs/", ["check"]) == ["check"]


def test_a_longer_hyphenated_target_does_not_document_its_prefix() -> None:
    assert undocumented_targets("make check-matrix", ["check"]) == ["check"]
    assert undocumented_targets("make check-matrix", ["check-matrix"]) == []


def test_a_hyphenated_prefix_does_not_document_the_target_either() -> None:
    """``mypy-check`` is real README prose; it documents no target."""
    assert undocumented_targets("mypy-check the package", ["check"]) == ["check"]


def test_surrounding_punctuation_and_backticks_still_count_as_a_mention() -> None:
    """The boundary class must admit the forms README actually uses."""
    for text in ("`make check`", "run `check`, then ship", "(make check)", "make check\n"):
        assert undocumented_targets(text, ["check"]) == [], text


# ==========================================================================
# Two-sided negative control on planted text (no repo mutation)
# ==========================================================================


def test_the_missing_list_names_exactly_the_one_undocumented_target() -> None:
    targets = sorted(phony_targets(MAKEFILE.read_text(encoding="utf-8")))
    for omitted in targets:
        planted = " ".join(f"`make {name}`" for name in targets if name != omitted)
        assert undocumented_targets(planted, targets) == [omitted], (
            f"planting a section that documents every target except {omitted!r} must "
            "report exactly that one"
        )


def test_a_section_documenting_every_target_reports_nothing_missing() -> None:
    targets = sorted(phony_targets(MAKEFILE.read_text(encoding="utf-8")))
    planted = " ".join(f"`make {name}`" for name in targets)
    assert undocumented_targets(planted, targets) == []
