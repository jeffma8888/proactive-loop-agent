"""Black-box oracle for factory iteration 182 (state dir ``iter-178``).

Feature under test: ``SPEC.md``'s two ENUMERATING sections -- ``### 4.1 collectors``
and ``### 4.5 cli + scheduler + examples`` -- are bound to the live registries by a
drift guard, and the 4 surfaces that binding exposed (``license``,
``broken_link``, ``pla config``, ``pla verify``) are documented.

Independence: the presence behaviors (1, 2, 3) are re-derived here from the PUBLIC
interface -- ``all_collectors()`` and ``build_parser()`` -- through this file's OWN
section extractor, so this oracle can DISAGREE with the shipped guard instead of
echoing it. The behaviors that are ABOUT the shipped guard's own properties
(fail-loud extraction, anti-vacuity, two-sidedness) necessarily drive the guard
module itself; those import from ``tests/test_spec_contract.py``, which is
established convention in this suite (``test_iter176_behavior.py`` and
``test_iter164_behavior.py`` both import a sibling guard module).

Offline by construction: reads two tracked files and imports the package. No
network, no subprocess, no ``tmp_path`` tree.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from proactive_loop.cli import build_parser
from proactive_loop.collectors import all_collectors

from tests.test_spec_contract import (  # the deliverable under test
    CLI_HEADING,
    COLLECTORS_HEADING,
    missing_mentions,
    spec_section,
)

REPO = Path(__file__).resolve().parents[1]
SPEC = REPO / "SPEC.md"
ROADMAP = REPO / "ROADMAP.md"
ROADMAP_ARCHIVE = REPO / "ROADMAP_ARCHIVE.md"


# --------------------------------------------------------------------------- #
# This oracle's OWN extractor -- deliberately not the shipped one, so behaviors
# 1-3 are measured against an independent slice of the same file.
# --------------------------------------------------------------------------- #
def _own_section(text: str, heading: str) -> str:
    """Slice *heading*'s body, ignoring headings that sit inside a fenced block.

    ``### 4.1`` embeds ```` ```python ```` blocks whose first line is ``# base.py``,
    so a fence-blind extractor returns a handful of characters for a 21,544-char
    section and every collector then reports as missing. Written independently of
    the shipped extractor on purpose: two implementations agreeing on the slice is
    evidence, one implementation agreeing with itself is not.
    """
    lines = text.splitlines()
    inside_fence = False
    body: list[str] = []
    collecting = False
    level = len(heading) - len(heading.lstrip("#"))
    for line in lines:
        stripped = line.lstrip()
        is_fence = stripped.startswith("```") or stripped.startswith("~~~")
        if not inside_fence and not is_fence:
            if line.strip() == heading:
                collecting = True
                continue
            match = re.match(r"(#{1,6}) \S", line)
            if collecting and match is not None and len(match.group(1)) <= level:
                break
        if is_fence:
            inside_fence = not inside_fence
        if collecting:
            body.append(line)
    assert collecting, f"heading {heading!r} not found in the document"
    return "\n".join(body)


def _spec_text() -> str:
    return SPEC.read_text(encoding="utf-8")


def _live_verbs() -> list[str]:
    """The live ``pla`` subcommand names, off the public parser."""
    parser = build_parser()
    choices: list[str] = []
    for action in parser._subparsers._group_actions:  # type: ignore[union-attr]
        if hasattr(action, "choices") and action.choices:
            choices.extend(action.choices)
    assert choices, "the parser exposed no subcommands -- the oracle would be vacuous"
    return choices


def _collector_names() -> list[tuple[str, str]]:
    """``(module, ClassName)`` for every collector the registry constructs."""
    pairs: list[tuple[str, str]] = []
    for collector in all_collectors():
        cls = type(collector)
        pairs.append((cls.__module__.rsplit(".", 1)[-1], cls.__name__))
    return pairs


def _boundaried(section: str, token: str) -> bool:
    """Is *token* present in *section* as a whole token, not as a prefix?

    ``pla run`` occurs inside ``pla runs``, so plain substring containment cannot
    tell "documented" from "a longer sibling happens to start the same way".
    """
    return re.search(re.escape(token) + r"(?![\w-])", section) is not None


# --------------------------------------------------------------------------- #
# Behavior 1 -- every live collector is named in section 4.1
# --------------------------------------------------------------------------- #
def test_spec_41_names_every_live_collector() -> None:
    """Class name AND module name for all 17 live collectors, incl. the 2 new ones."""
    section = _own_section(_spec_text(), COLLECTORS_HEADING)
    assert len(section) > 5_000, f"section 4.1 sliced to {len(section)} chars"

    pairs = _collector_names()
    assert len(pairs) > 1, "the collector registry is empty -- guard would be vacuous"

    missing = [
        f"{module}/{cls}"
        for module, cls in pairs
        if module not in section or cls not in section
    ]
    assert missing == [], (
        f"SPEC.md '{COLLECTORS_HEADING}' does not name these live collectors: {missing}"
    )


def test_spec_41_documents_the_two_previously_omitted_collectors() -> None:
    """The sharp end of behavior 1: both occurred ZERO times before this iteration."""
    section = _own_section(_spec_text(), COLLECTORS_HEADING)
    for token in (
        "license.py: LicenseCollector",
        "broken_link.py: BrokenDocLinkCollector",
    ):
        assert token in section, f"section 4.1 is missing the bullet anchor {token!r}"


# --------------------------------------------------------------------------- #
# Behavior 2 -- every live verb is documented in `pla <verb>` invocation form
# --------------------------------------------------------------------------- #
def test_spec_45_documents_every_live_verb_in_invocation_form() -> None:
    section = _own_section(_spec_text(), CLI_HEADING)
    assert len(section) > 20_000, f"section 4.5 sliced to {len(section)} chars"

    verbs = _live_verbs()
    assert len(verbs) > 1
    missing = [verb for verb in verbs if not _boundaried(section, f"pla {verb}")]
    assert missing == [], (
        f"SPEC.md '{CLI_HEADING}' does not document these live verbs in `pla <verb>` "
        f"form: {missing}"
    )


def test_spec_45_documents_the_two_previously_omitted_verbs() -> None:
    """`pla config` and `pla verify` occurred ZERO times in the file before this iter."""
    section = _own_section(_spec_text(), CLI_HEADING)
    for token in ("pla config", "pla verify"):
        assert token in section, f"section 4.5 is missing {token!r}"


# --------------------------------------------------------------------------- #
# Behavior 3 -- the presence FORM is pinned, because bare tokens are vacuous
# --------------------------------------------------------------------------- #
def test_bare_verb_names_are_near_vacuous_in_section_45() -> None:
    """Measured: remove a verb's invocation form and its bare name usually survives.

    14 of the 16 verb names are ordinary English words that section 4.5 uses in
    prose, so a bare-word guard would report a verb as documented after every
    ``pla <verb>`` mention of it was deleted. That is the justification for pinning
    the invocation form, expressed as an assertion rather than a comment.
    """
    section = _own_section(_spec_text(), CLI_HEADING)
    survivors = []
    for verb in _live_verbs():
        doctored = re.sub(re.escape(f"pla {verb}") + r"(?![\w-])", "", section)
        if re.search(rf"\b{re.escape(verb)}\b", doctored):
            survivors.append(verb)
    assert len(survivors) >= 10, (
        "expected the bare-token form to be demonstrably vacuous for most verbs, "
        f"but only {len(survivors)} survived removal of their invocation form: {survivors}"
    )


def test_bare_collector_names_are_vacuous_for_some_collectors() -> None:
    """Section 4.1's bullets cross-reference each other, so bare names fail open.

    Deleting a collector's WHOLE bullet leaves both its bare module name and its
    bare class name findable elsewhere in the section for at least one collector --
    which is why the shipped guard pins the ``module.py: ClassName`` anchor form.
    """
    section = _own_section(_spec_text(), COLLECTORS_HEADING)
    vacuous = []
    for module, cls in _collector_names():
        doctored = _delete_collector_bullet(section, f"{module}.py: {cls}")
        if module in doctored and cls in doctored:
            vacuous.append(f"{module}/{cls}")
    assert vacuous, (
        "expected at least one collector whose bare names survive deletion of its own "
        "bullet -- if this is empty the bare-name justification no longer holds and "
        "the anchor-form rationale in test_spec_contract should be re-measured"
    )


# --------------------------------------------------------------------------- #
# Behavior 4 -- a missing heading fails loudly, never returns empty text
# --------------------------------------------------------------------------- #
def test_shipped_extractor_raises_and_names_a_missing_heading() -> None:
    with pytest.raises(AssertionError, match=re.escape("### 4.9 does not exist")):
        spec_section(_spec_text(), "### 4.9 does not exist")


def test_shipped_extractor_raises_on_a_truncated_slice() -> None:
    """The floor is enforced, so a mis-slice cannot become a 'missing item' verdict."""
    tiny = "### 4.1 collectors\nshort body\n## 5. next\n"
    with pytest.raises(AssertionError):
        spec_section(tiny, "### 4.1 collectors", min_chars=5_000)


# --------------------------------------------------------------------------- #
# Behavior 5 -- anti-vacuity: the item universe is registry-derived and non-zero
# --------------------------------------------------------------------------- #
def test_guard_token_universe_matches_the_live_registries() -> None:
    """The shipped guard examines one token per live item -- no hardcoded count."""
    from tests.test_spec_contract import _collector_tokens, _verb_tokens

    collector_tokens = _collector_tokens()
    verb_tokens = _verb_tokens()
    assert len(collector_tokens) == len(all_collectors()) > 1
    assert len(verb_tokens) == len(_live_verbs()) > 1
    assert sorted(collector_tokens) == sorted(
        f"{module}.py: {cls}" for module, cls in _collector_names()
    )


# --------------------------------------------------------------------------- #
# Behavior 6 -- two-sided, over EVERY live item rather than a curated sample
# --------------------------------------------------------------------------- #
def _delete_collector_bullet(section: str, anchor: str) -> str:
    """Remove one collector's whole bullet -- anchor line to the next top-level one."""
    lines = section.splitlines()
    start = next(
        (i for i, line in enumerate(lines) if line.startswith("- `" + anchor)), None
    )
    assert start is not None, f"no bullet in section 4.1 opens with {anchor!r}"
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].startswith("- `"):
            end = j
            break
    return "\n".join(lines[:start] + lines[end:])


def test_guard_detects_every_collector_bullet_deletion() -> None:
    """Exhaustive negative control: all 17, not a 2-token sample."""
    from tests.test_spec_contract import _collector_tokens

    section = _own_section(_spec_text(), COLLECTORS_HEADING)
    tokens = _collector_tokens()
    undetected = [
        token
        for token in tokens
        if token not in missing_mentions(_delete_collector_bullet(section, token), tokens)
    ]
    assert undetected == [], (
        f"the collectors guard stays GREEN after the whole bullet for {undetected} is "
        "deleted, so those collectors are undocumentable-without-notice"
    )


def test_guard_detects_every_verb_mention_removal() -> None:
    """Exhaustive negative control for the verb half -- all 16, not a 2-token sample.

    Removes every ``pla <verb>`` mention of one verb (boundaried, so removing
    ``pla run`` does not also destroy ``pla runs``) and asks the shipped guard which
    verbs it now reports missing. A verb absent from that report is a verb whose
    documentation can be deleted with the guard staying green.
    """
    from tests.test_spec_contract import _verb_tokens

    section = _own_section(_spec_text(), CLI_HEADING)
    tokens = _verb_tokens()
    undetected = []
    for verb in _live_verbs():
        token = f"pla {verb}"
        doctored = re.sub(re.escape(token) + r"(?![\w-])", "", section)
        if token not in missing_mentions(doctored, tokens):
            undetected.append(token)
    assert undetected == [], (
        f"the cli guard stays GREEN after every mention of {undetected} is removed. "
        "Cause: `missing_mentions` uses plain substring containment, and these tokens "
        "are PREFIXES of a sibling verb token (`pla run` occurs inside `pla runs`), so "
        "a longer verb's documentation satisfies the shorter verb's presence check. "
        "Fix, measured green on today's tree: test presence with a trailing-boundary "
        "guard -- re.search(re.escape(token) + r'(?![\\w-])', section) -- which keeps "
        "all 33 live tokens PRESENT today and detects 17/17 collector and 16/16 verb "
        "deletions."
    )


# --------------------------------------------------------------------------- #
# Behavior 7 -- offline and deterministic
# --------------------------------------------------------------------------- #
def test_guard_module_is_offline_and_subprocess_free() -> None:
    source = (REPO / "tests" / "test_spec_contract.py").read_text(encoding="utf-8")
    for banned in ("subprocess", "socket", "urllib", "requests", "http.client"):
        assert f"import {banned}" not in source, (
            f"the SPEC guard must stay offline; found an import of {banned}"
        )


def test_guard_is_deterministic_across_repeated_reads() -> None:
    from tests.test_spec_contract import _collector_tokens

    first = (_own_section(_spec_text(), COLLECTORS_HEADING), tuple(_collector_tokens()))
    second = (_own_section(_spec_text(), COLLECTORS_HEADING), tuple(_collector_tokens()))
    assert first == second


# --------------------------------------------------------------------------- #
# Behavior 10 -- the iteration's own record lands in this commit
# --------------------------------------------------------------------------- #
def test_iteration_record_landed_in_both_roadmap_files() -> None:
    roadmap = ROADMAP.read_text(encoding="utf-8")
    rows = [
        line
        for line in roadmap.splitlines()
        if line.startswith("- ") and "(iter 178, factory iter 182)" in line
    ]
    assert len(rows) == 1, f"expected exactly one iter-178 Done-ledger row, got {rows}"
    assert len(rows[0]) <= 120, f"ledger row is {len(rows[0])} chars, ceiling is 120"

    archive = ROADMAP_ARCHIVE.read_text(encoding="utf-8")
    assert "factory iter 182" in archive, (
        "ROADMAP_ARCHIVE.md carries no detail bullet for this iteration"
    )

# NOTE: this oracle deliberately does NOT restate ROADMAP.md's 40,000-char ceiling.
# tests/test_iter172_behavior.py enforces a MEMBERSHIP brake -- the set of modules that
# apply len() to a roadmap-named producer inside an assert must equal its
# SIZE_BOUND_ALLOWLIST -- and the owner's oracle (tests/test_iter168_behavior.py) already
# asserts that ceiling. A second opinion here would red the build the moment this file
# becomes tracked, so behavior 10's ceiling clause is covered by the owner, not restated.
