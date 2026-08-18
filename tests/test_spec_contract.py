"""Drift guards binding ``SPEC.md``'s two ENUMERATING sections to the live registries.

Why this file exists
``SPEC.md`` is the document every automated contributor to this repo is handed as
"the product VISION -- stay strictly inside it", so a surface missing from it is
invisible to the very process that extends the product. ``README.md``'s two
enumerating tables have been machine-bound to the code since factory iter 143
(``test_readme_and_ci_contract.py``); ``SPEC.md`` had **no oracle at all**, and it
had drifted in exactly the way an unguarded enumeration does:

* ``### 4.1 collectors`` named 15 of the 17 collectors in ``all_collectors()``.
  ``LicenseCollector``/``license`` and ``BrokenDocLinkCollector``/``broken_link``
  occurred ZERO times in the whole 89,267-char file.
* ``### 4.5 cli + scheduler + examples`` documented 14 of the 16 live verbs.
  ``pla config`` and ``pla verify`` occurred ZERO times in the whole file --
  ``verify`` having shipped two and three commits earlier and already being
  load-bearing in the ``run --snapshot`` -> ``verify --fail-on-unresolved`` arc.

This is the SPEC counterpart of the README guard, and it is deliberately the same
shape: one extractor, one presence helper, one table of contracts, and a negative
control per contract so each guard is known to FIRE rather than merely known to pass.

Three design decisions worth the reader's time:

1. **The extractor is FENCE-AWARE, and that is not a nicety.** ``### 4.1`` embeds
   ```` ```python ```` blocks whose first line is ``# base.py``. A naive
   "slice to the next line matching ``^#{1,3} ``" extractor therefore returns
   **11 characters** for a 20,340-char section -- measured while writing this file --
   and every collector then reports as missing. So a fence mask is what stands
   between this guard and a spectacular false alarm.

2. **A missing heading RAISES.** Returning ``""`` for a heading that no longer
   exists would make the guard report all 17 collectors missing (a false alarm) or,
   with an ``if section:`` short-circuit anywhere downstream, silently pass forever
   (a fail-open). Renaming a section is legitimate; silently un-guarding one is not.

3. **BOTH contracts pin the presence FORM the target section itself uses, never a
   bare token** -- verbs as ``pla <verb>``, collectors as ``module.py: ClassName``.
   Bare names are vacuous in two independent ways, one per contract. For collectors,
   ``### 4.1``'s bullets cross-reference each other, so a bare class or module name is
   routinely satisfied by a DIFFERENT collector's bullet: measured per collector, bare
   names left 3 of 17 whole-bullet deletions UNDETECTED, and the anchor form detects
   all 17 (see ``_collector_tokens``). For verbs, 15 of the 16 names are ordinary
   English words -- ``config``, ``diff``, ``run``, ``scan``, ``policy``, ``tools``,
   ``verify``, ``watch`` -- so a
   bare word-boundary match is near-vacuous: measured against the pre-fix section it
   reported only ``verify`` missing, while the invocation form correctly reported
   BOTH ``config`` and ``verify``. Note this is the OPPOSITE convention to
   ``test_readme_and_ci_contract.missing_verbs``, which tests the backticked bare
   token because that is README's table style; reusing it here would report all 16
   verbs missing, since ``SPEC.md`` writes ``pla diff --old A.json``. Pick the form
   the target section actually uses.

Offline and cheap by construction: reads ONE tracked file and imports the package.
No network, no subprocess, no ``tmp_path`` tree, no fixture, no dependency beyond
pydantic v2 + pytest -- so it behaves identically in a fresh clone.
"""

from __future__ import annotations

import argparse
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import pytest

from proactive_loop.cli import build_parser
from proactive_loop.collectors import all_collectors

REPO = Path(__file__).resolve().parents[1]
SPEC = REPO / "SPEC.md"

COLLECTORS_HEADING = "### 4.1 collectors"
CLI_HEADING = "### 4.5 cli + scheduler + examples"

# Anti-vacuity floors on the EXTRACTED text, well below today's sizes (20,340 and
# 31,311 chars) but far above anything a mis-slice produces. A guard fed a truncated
# section is the fail-open case this whole file exists to prevent, so the slice is
# range-checked before any verdict is drawn from it. Deliberately loose: these are
# smoke alarms for a broken extractor, not a prose-length budget.
MIN_SECTION_CHARS = 5_000


def _fence_mask(lines: list[str]) -> list[bool]:
    """Return, per line, whether it sits INSIDE a fenced code block.

    Both ``` and ``~~~`` fences count, and the opening fence line itself is marked
    as inside, so a ```` ```python ```` opener can never be read as content. Written
    as an explicit toggle rather than a regex over the whole text because a fence is
    a line-level construct and the mask is what the caller needs anyway.
    """
    inside = False
    mask: list[bool] = []
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            mask.append(True)
            inside = not inside
            continue
        mask.append(inside)
    return mask


def spec_section(text: str, heading: str, min_chars: int = 0) -> str:
    """Return the body of *heading* in *text*, up to the next same-or-higher heading.

    Raises ``AssertionError`` naming *heading* when it is absent, and when the
    resulting slice is shorter than *min_chars* -- see design note 2 in the module
    docstring: an empty return would convert a renamed section into either a false
    alarm or a permanently-green guard, and both are worse than a red build.

    *min_chars* defaults to 0 so the extractor stays usable on the small synthetic
    documents its own known-bad samples are built from; every caller reading the real
    ``SPEC.md`` passes ``MIN_SECTION_CHARS``, because that is where a mis-slice would
    silently become a verdict.
    """
    lines = text.splitlines()
    mask = _fence_mask(lines)

    starts = [
        i
        for i, line in enumerate(lines)
        if not mask[i] and line.strip() == heading
    ]
    assert len(starts) == 1, (
        f"SPEC.md must hold exactly one {heading!r} heading outside a code fence, "
        f"found {len(starts)}. If the section was deliberately renamed, update this "
        "guard's heading constant in the SAME commit -- do not leave the enumeration "
        "un-guarded."
    )
    start = starts[0]

    level = len(heading) - len(heading.lstrip("#"))
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if mask[i]:
            continue  # A '# base.py' comment inside a ```python block is not a heading.
        match = re.match(r"(#{1,6}) \S", lines[i])
        if match is not None and len(match.group(1)) <= level:
            end = i
            break

    body = "\n".join(lines[start + 1 : end])
    assert len(body) >= min_chars, (
        f"the extracted {heading!r} body is only {len(body)} chars, below the "
        f"{min_chars} floor -- the extractor sliced wrongly (a fence-aware "
        "bug returns ~11 chars here), so any 'missing item' verdict from it would be "
        "a false alarm. Fix the extractor, do not lower the floor."
    )
    return body


def missing_mentions(section: str, tokens: Iterable[str]) -> list[str]:
    """Return the *tokens* absent from *section*, in the order given.

    Presence is tested with a TRAILING WORD BOUNDARY, not plain containment. Every
    token here is a multi-word anchor form -- ``module.py: ClassName`` or
    ``pla <verb>`` -- so it cannot occur as an accidental fragment of ordinary prose,
    and (unlike a bare name) cannot be satisfied by a passing cross-reference in a
    DIFFERENT item bullet. One thing an anchor form does NOT rule out, and containment
    could not see: a token that is a PREFIX of a sibling token. ``pla run`` occurs
    inside ``pla runs``, so under containment the ``runs`` verb's documentation
    satisfied ``run``'s presence check -- measured on the live section, every
    boundaried ``pla run`` mention could be deleted and this guard stayed green, i.e.
    the fail-open case for the product's most central verb.

    ``(?![\\w-])`` closes it, and only the TRAILING side is needed: a leading boundary
    would guard against a token that is a SUFFIX of a sibling, and no live token is
    (measured over both registries). Should one ever appear, the exhaustive per-item
    negative controls in ``test_iter182_behavior.py`` turn RED with the token named --
    which is why the one-sided boundary is a measurement here, not an assumption.
    Measured under this form: all 33 live tokens still present in their own sections
    (no false alarm), 16/16 verb-mention removals and 17/17 collector-bullet deletions
    detected.
    """
    return [
        token
        for token in tokens
        if re.search(re.escape(token) + r"(?![\w-])", section) is None
    ]


def _live_verbs() -> list[str]:
    """The live ``pla`` subcommand names, straight off the parser.

    Reuses the seam ``test_readme_and_ci_contract`` established rather than
    re-deriving argparse internals; cross-test import of a registry seam is
    established convention in this suite.
    """
    parser = build_parser()
    subparsers = [
        action
        for action in parser._subparsers._group_actions
        if isinstance(action, argparse._SubParsersAction)
    ]
    assert len(subparsers) == 1, (
        f"expected exactly one subparser action, got {len(subparsers)}"
    )
    return list(subparsers[0].choices)


def _collector_tokens() -> list[str]:
    """Each collector in the anchor form its own bullet opens with.

    That form is ``module.py: ClassName`` -- the section's own bullet prefix.

    Carries both names a reader needs -- the file AND the type the registry
    constructs -- in the single anchor form every bullet in the section already opens
    with, so it pins the presence FORM rather than two bare tokens (design note 3
    applies to this contract exactly as it does to the verbs).

    Two bare names were measurably fail-open here: the bullets in ``### 4.1``
    cross-reference each other, so a bare class or module name is routinely satisfied
    by a DIFFERENT collector's bullet. Measured by deleting each collector's own bullet
    from an in-memory copy of the live section: with bare names 3 of 17 deletions went
    UNDETECTED (``RecentFilesCollector``, ``DependencyCollector``,
    ``LargeFileCollector`` -- the whole bullet could be removed and the guard stayed
    green); with this anchor form all 17 deletions are detected.
    """
    tokens: list[str] = []
    for collector in all_collectors():
        cls = type(collector)
        module = cls.__module__.rsplit(".", 1)[-1]
        tokens.append(f"{module}.py: {cls.__name__}")
    return tokens


def _verb_tokens() -> list[str]:
    """Every live verb in the invocation form the section actually uses."""
    return [f"pla {verb}" for verb in _live_verbs()]


@dataclass(frozen=True)
class SpecContract:
    """One (section, live-registry) enumeration contract.

    The two checks differ only in which section they read and which registry names
    the items, so they are one table-driven shape rather than two parallel
    implementations that can drift apart.
    """

    label: str
    heading: str
    tokens: tuple[str, ...]
    remedy: str


def _contracts() -> list[SpecContract]:
    return [
        SpecContract(
            label="collectors",
            heading=COLLECTORS_HEADING,
            tokens=tuple(_collector_tokens()),
            remedy=(
                "add one terse bullet per collector in the section's existing "
                "`module.py: ClassName(name=..., ...)` -- description style"
            ),
        ),
        SpecContract(
            label="cli",
            heading=CLI_HEADING,
            tokens=tuple(_verb_tokens()),
            remedy="add one `pla <verb> ...` bullet in the section's existing verb style",
        ),
    ]


CONTRACTS = _contracts()
CONTRACT_IDS = [contract.label for contract in CONTRACTS]

# Representative tokens for the negative controls: one NEWLY-documented item plus one
# long-standing one per contract, so the control proves the guard fires on both.
#
# Curated rather than "every token", because deletion is not surgical for a token that
# PREFIXES another: removing every ``pla run`` also destroys ``pla runs``, so an
# all-tokens control would report 2 missing and fail on a healthy file. The curated
# picks are proven prefix-free by ``test_negative_control_tokens_are_collision_free``,
# so this list cannot quietly become a place where a colliding token hides.
CONTROL_TOKENS: dict[str, tuple[str, ...]] = {
    "collectors": (
        "license.py: LicenseCollector",
        "broken_link.py: BrokenDocLinkCollector",
    ),
    "cli": ("pla verify", "pla config"),
}


def _spec_text() -> str:
    return SPEC.read_text(encoding="utf-8")


def _live_section(contract: SpecContract) -> str:
    """The real section, range-checked -- the only seam the live guards read."""
    return spec_section(_spec_text(), contract.heading, min_chars=MIN_SECTION_CHARS)


@pytest.mark.parametrize("contract", CONTRACTS, ids=CONTRACT_IDS)
def test_spec_section_names_every_live_item(contract: SpecContract) -> None:
    """Every item in the live registry is findable in its SPEC section."""
    section = _live_section(contract)

    # Anti-vacuity: the item universe is DERIVED from the registry at run time and
    # must be non-empty, so an import that silently returned [] cannot pass this.
    assert contract.tokens, (
        f"the {contract.label} registry yielded no items -- the guard would be "
        "vacuously green"
    )

    absent = missing_mentions(section, contract.tokens)
    assert absent == [], (
        f"SPEC.md '{contract.heading}' does not mention these live {contract.label} "
        f"names: {absent}. The section is an ENUMERATION handed to every contributor "
        f"as fixed intent, so a shipped surface missing from it is invisible to the "
        f"process that extends the product. Remedy: {contract.remedy}."
    )


@pytest.mark.parametrize("contract", CONTRACTS, ids=CONTRACT_IDS)
def test_guard_examines_the_whole_live_registry(contract: SpecContract) -> None:
    """The examined count is registry-derived and non-trivial, never hardcoded.

    Pinning the counts to ``len(all_collectors())`` and ``len(choices)`` rather than
    to 17 and 16 is the point: a literal would be a second place to update on every
    new collector or verb, and a guard whose expectation is a stale literal fails for
    the wrong reason.
    """
    if contract.label == "collectors":
        expected = len(all_collectors())  # one `module.py: ClassName` anchor each
    else:
        expected = len(_live_verbs())
    assert len(contract.tokens) == expected
    assert expected > 1, "an enumeration guard over 0 or 1 items proves nothing"


@pytest.mark.parametrize("contract", CONTRACTS, ids=CONTRACT_IDS)
def test_extracted_section_is_substantial(contract: SpecContract) -> None:
    """A truncated slice must not be able to produce a verdict (see design note 1)."""
    section = _live_section(contract)
    assert len(section) >= MIN_SECTION_CHARS


@pytest.mark.parametrize(
    ("label", "token"),
    [(label, token) for label, tokens in CONTROL_TOKENS.items() for token in tokens],
    ids=[
        f"{label}-{token.replace(' ', '_')}"
        for label, tokens in CONTROL_TOKENS.items()
        for token in tokens
    ],
)
def test_guard_fires_when_one_live_item_goes_undocumented(label: str, token: str) -> None:
    """Two-sided proof: doctor ONE mention out and the guard names exactly it.

    The doctoring is in memory -- ``SPEC.md`` on disk is never written by a test.
    Without this control the guards above are only known to PASS; a presence check
    that can never fail is decoration, and this suite's own history records
    fail-open guards costing more than no guard at all.
    """
    contract = next(c for c in CONTRACTS if c.label == label)
    section = _live_section(contract)
    assert token in section, f"control token {token!r} is not in the live section"

    doctored = section.replace(token, "")
    assert missing_mentions(doctored, contract.tokens) == [token]


def test_negative_control_tokens_are_collision_free() -> None:
    """No control token is a substring of another token in the same contract.

    This is what licenses the curated ``CONTROL_TOKENS`` list: removing a token that
    prefixes a sibling (``pla run`` inside ``pla runs``) deletes two mentions, so the
    control would fail on a healthy file. Adding a colliding token to the list turns
    THIS test red with the reason, instead of the control failing mysteriously.
    """
    for label, tokens in CONTROL_TOKENS.items():
        contract = next(c for c in CONTRACTS if c.label == label)
        for token in tokens:
            others = [t for t in contract.tokens if t != token]
            collisions = [other for other in others if token in other]
            assert collisions == [], (
                f"control token {token!r} is a substring of {collisions} in the "
                f"{label} contract, so deleting it is not surgical -- pick another"
            )


def test_extractor_raises_on_a_missing_heading() -> None:
    """A renamed/removed heading must fail LOUDLY, never return empty text."""
    with pytest.raises(AssertionError, match=re.escape("### 4.9 nope")):
        spec_section(_spec_text(), "### 4.9 nope")


def test_extractor_ignores_headings_inside_fenced_code() -> None:
    """The measured false-alarm case: a ``# base.py`` comment inside a fence.

    Known-bad sample, so the fence mask is proven to be load-bearing rather than
    assumed: without it this returns the 1-line preamble instead of the body.
    """
    text = "\n".join(
        [
            "### 4.1 collectors",
            "preamble",
            "```python",
            "# base.py",
            "class Collector: ...",
            "```",
            "- `license.py: LicenseCollector(name=\"license\")` -- real content",
            "### 4.2 next",
            "not mine",
        ]
    )
    body = spec_section(text, "### 4.1 collectors")
    assert "real content" in body
    assert "not mine" not in body
    assert "# base.py" in body  # inside the section, just not treated as a boundary


def test_extractor_stops_at_a_higher_level_heading() -> None:
    """``### 4.5`` ends at ``## 5.``, a HIGHER level -- not only at a sibling ``###``."""
    text = "\n".join(
        [
            "### 4.5 cli",
            "mine",
            "## 5. Non-negotiables",
            "theirs",
        ]
    )
    body = spec_section(text, "### 4.5 cli")
    assert body.strip() == "mine"
