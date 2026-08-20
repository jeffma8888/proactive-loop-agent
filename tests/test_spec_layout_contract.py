"""Drift guard for ``SPEC.md`` ``## 2. Layout`` -- the region the other spec guard cannot see.

Why this file exists
``tests/test_spec_contract.py`` binds ``SPEC.md``'s two enumerating sections (4.1
collectors, 4.5 cli) to the live registries, and its extractor is deliberately
**fence-AWARE**: ``_fence_mask`` marks every line inside a fenced block as
not-content, which is what stops a ``# base.py`` comment inside a ```` ```python ````
block from being read as a Markdown heading. That masking is correct and is pinned by
its own known-bad sample.

But ``## 2. Layout`` -- the repo's orientation map, the first thing a reader or an
automated contributor uses to find anything -- **is one fenced block**. So it is
structurally invisible to that guard, and ``tests/test_iter58_behavior.py`` pins only
the literal heading string ``"## 2. Layout"``, not one word of its content. The region
could therefore only ever rot, silently, with a green build -- and it had:

* it named **4** collector modules (``filesystem``, ``git_activity``, ``todos``,
  ``notes``) against **17** live collectors backed by 17 distinct modules;
* its ``cli.py`` comment listed **14** verbs against **16** from ``build_parser()``,
  omitting exactly ``verify`` and ``config`` -- the same pair row #215 found missing
  from 4.5 and fixed only there, 13 iterations before this file;
* its ``tests/`` comment claimed "one test module per package" against ~190
  ``test_iterNN_behavior.py`` modules plus several cross-cutting contract modules.

Three design decisions worth the reader's time:

1. **This extractor is fence-INCLUSIVE, which is the whole point.** It reuses
   ``spec_section`` from the sibling guard for the SECTION slice -- so "where does a
   section end" has exactly one definition in this suite and the two files cannot
   drift apart -- then descends INTO the fence, which the sibling never does.

2. **Counts, not a roster, and both counts are DERIVED.** The fixed section carries
   "17 collector modules" and "16 verbs" plus pointers to 4.1/4.5 rather than a
   17-line enumeration, because 4.1/4.5 are already the authoritative rosters and are
   already machine-bound; a second enumeration would be a second maintenance site.
   The two numerals are the cheap guarded part, and they are compared against
   ``all_collectors()`` / ``build_parser()`` at run time -- never against a literal.

3. **A PARTIAL roster is the failure mode, so that is what is banned.** The defect was
   never "no collectors listed", it was "4 of 17 listed", which reads as complete. So
   the roster contracts are EMPTY-or-COMPLETE: naming none is honest (the count plus a
   pointer), naming all is honest, and naming some is the shipped defect. That shape
   also means this guard does not force a future author to choose the elision style --
   it only forbids the misleading middle.

Offline and cheap by construction: reads ONE tracked file and imports the package. No
network, no subprocess, no ``tmp_path`` tree, no dependency beyond pydantic v2 +
pytest -- so it behaves identically in a fresh clone.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import pytest

from proactive_loop.cli import build_parser
from proactive_loop.collectors import all_collectors
from tests.test_spec_contract import spec_section

REPO = Path(__file__).resolve().parents[1]
SPEC = REPO / "SPEC.md"

LAYOUT_HEADING = "## 2. Layout"

# Anti-vacuity floor on the EXTRACTED fence, well below today's 1,716 chars but far
# above anything a mis-slice produces. A guard fed a truncated fence is the fail-open
# case this file exists to prevent, so the slice is range-checked before any verdict is
# drawn from it. A smoke alarm for a broken extractor, not a prose-length budget.
MIN_FENCE_CHARS = 1_000

# Landmarks every correct slice of THIS fence contains -- one per tree level, so a
# slice that caught only the opening lines cannot satisfy all three.
FENCE_LANDMARKS = ("proactive-loop-agent/", "src/proactive_loop/", "tests/")

_FENCE_MARKERS = ("```", "~~~")

# The claim this commit retired. Kept as a literal so its return is a RED build rather
# than a matter of reviewer memory.
RETIRED_PARITY_CLAIM = "one test module per package"


def layout_fence(text: str, min_chars: int = 0) -> str:
    """Return the body of the single fenced block inside ``## 2. Layout``.

    Raises ``AssertionError`` -- never returns ``""`` -- when the heading is absent
    (delegated to ``spec_section``, which names the heading), when the section holds no
    fenced block or an unbalanced/second one, when the fence is blank, or when it is
    shorter than *min_chars*. An empty return would convert a renamed section or a
    de-fenced tree into a permanently-green guard, which is strictly worse than a red
    build; see design note 1 in the module docstring.

    *min_chars* defaults to 0 so the helper stays usable on the small synthetic
    documents its own known-bad samples are built from; the live callers pass
    ``MIN_FENCE_CHARS``, because that is where a mis-slice would become a verdict.
    """
    body = spec_section(text, LAYOUT_HEADING)
    lines = body.splitlines()
    markers = [
        i for i, line in enumerate(lines) if line.lstrip().startswith(_FENCE_MARKERS)
    ]
    assert len(markers) == 2, (
        f"{LAYOUT_HEADING!r} must hold exactly one fenced block, found "
        f"{len(markers)} fence marker line(s). This section IS the orientation map and "
        "this guard reads INSIDE the fence, so a de-fenced or double-fenced tree must "
        "fail loudly rather than silently un-guard the region."
    )
    fence = "\n".join(lines[markers[0] + 1 : markers[1]])
    assert fence.strip(), f"the {LAYOUT_HEADING!r} fence is empty"
    assert len(fence) >= min_chars, (
        f"the extracted {LAYOUT_HEADING!r} fence is only {len(fence)} chars, below the "
        f"{min_chars} floor -- the extractor sliced wrongly, so any drift verdict from "
        "it would be a false alarm. Fix the extractor, do not lower the floor."
    )
    return fence


def live_collector_modules() -> set[str]:
    """The module stem of every live collector, e.g. ``{"filesystem", "license", ...}``.

    The fence names FILES, so the roster contract is over modules while the COUNT
    contract is over ``len(all_collectors())``. They agree today (17 collectors in 17
    distinct modules) and are deliberately kept separate: a second collector added to
    an existing module must move the count without inventing a phantom file.
    """
    return {type(c).__module__.rsplit(".", 1)[-1] for c in all_collectors()}


def live_verbs() -> set[str]:
    """The live ``pla`` subcommand names, straight off the parser."""
    parser = build_parser()
    subparsers = [
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    ]
    assert len(subparsers) == 1, (
        f"expected exactly one subparser action, got {len(subparsers)}"
    )
    return set(subparsers[0].choices)


def _sole_declared_int(fence: str, unit: str) -> int:
    """The one integer in *fence* immediately followed by *unit*.

    Requiring EXACTLY one occurrence is deliberate: two would mean two places to keep
    true, which is the maintenance-site problem this whole design avoids.
    """
    matches = re.findall(r"(\d+)\s+" + unit, fence)
    assert len(matches) == 1, (
        f"expected exactly one '<N> {unit}' declaration in the layout fence, found "
        f"{len(matches)}: {matches}. One declaration is one maintenance site."
    )
    return int(matches[0])


def count_drift(fence: str, unit: str, live: int) -> str | None:
    """Return a message when the fence's declared *unit* count disagrees with *live*.

    Returns ``None`` when they agree. Written as a pure total function returning a
    message rather than as an assertion so the live check and its negative control run
    the IDENTICAL code path -- a control that exercises a different path proves nothing
    about the guard that ships.
    """
    declared = _sole_declared_int(fence, unit)
    if declared == live:
        return None
    return (
        f"SPEC.md '{LAYOUT_HEADING}' declares {declared} {unit} but the live registry "
        f"has {live}. The layout tree is the orientation map every contributor reads "
        f"first; fix the numeral (and note the roster itself lives in 4.1/4.5, which "
        f"tests/test_spec_contract.py already binds)."
    )


def partial_roster(text: str, live: set[str], spelling: str) -> set[str] | None:
    """Return the omitted members when *text* names SOME of *live*, else ``None``.

    ``None`` for both honest states -- naming none (a count plus a pointer) and naming
    all. Case-sensitive, word-boundaried matching: the fence carries ``LICENSE`` for the
    MIT file, which must not be read as the ``license`` collector.

    *spelling* is a ``str.format`` template for how a member appears in *text*
    (``"{}.py"`` for collector files, ``"{}"`` for bare verb names), so one
    implementation serves both contracts instead of two that can drift.
    """
    named = {
        member
        for member in live
        if re.search(r"\b" + re.escape(spelling.format(member)) + r"\b", text)
    }
    if named in (set(), live):
        return None
    return live - named


def _spec_text() -> str:
    return SPEC.read_text(encoding="utf-8")


def _live_fence() -> str:
    """The real fence, range-checked -- the only seam the live guards read."""
    return layout_fence(_spec_text(), min_chars=MIN_FENCE_CHARS)


def _sole_line(fence: str, needle: str) -> str:
    """The one line of *fence* containing *needle*, asserted unique."""
    hits = [line for line in fence.splitlines() if needle in line]
    assert len(hits) == 1, (
        f"expected exactly one layout-fence line containing {needle!r}, found "
        f"{len(hits)}: {hits}"
    )
    return hits[0]


# --- Synthetic samples for the negative controls -------------------------------------
#
# Each is derived from the LIVE fence by one surgical edit, so a control that fires
# proves the guard reacts to THAT edit and not to an unrelated difference in a
# hand-written sample. `SPEC.md` on disk is never written by a test.

# The exact pre-fix collector block: 4 of 17 modules, which reads as complete.
SHIPPED_DEFECT_MODULES = ("filesystem", "git_activity", "todos", "notes")

# The exact pre-fix `cli.py` comment: 14 of 16 verbs, omitting `verify` and `config`.
PRE_FIX_CLI_LINE = (
    "\u2502   \u2514\u2500\u2500 cli.py                # argparse CLI: scan / dispatch / "
    "run / resume / runs / explain / trace / signals / watch / diff / policy / tools / "
    "collectors / providers"
)


def _roster_text(modules: tuple[str, ...] | set[str]) -> str:
    """A fence-shaped block naming each of *modules* as a file, one per line."""
    return "\n".join(f"    \u251c\u2500\u2500 {module}.py     # a collector" for module in sorted(modules))


# --- Behavior 1: fence extraction ---------------------------------------------------


def test_b1_extractor_returns_the_live_layout_fence() -> None:
    """The live slice is substantial, is the tree, and carries no fence marker line."""
    fence = _live_fence()
    assert len(fence) >= MIN_FENCE_CHARS
    for landmark in FENCE_LANDMARKS:
        assert landmark in fence, f"the layout fence must name {landmark!r}"
    for line in fence.splitlines():
        assert not line.lstrip().startswith(_FENCE_MARKERS), (
            f"fence marker leaked into the extracted body: {line!r}"
        )


# --- Behavior 2: the extractor is never silently empty ------------------------------


def test_b2_extractor_raises_on_a_missing_heading() -> None:
    """A renamed/removed section must fail LOUDLY, never return empty text."""
    with pytest.raises(AssertionError, match=re.escape(LAYOUT_HEADING)):
        layout_fence("# Title\n\n## 3. Other\n\nbody\n")


def test_b2_extractor_raises_when_the_section_holds_no_fence() -> None:
    """De-fencing the tree must red the build, not un-guard the region."""
    text = f"{LAYOUT_HEADING}\n\nproactive-loop-agent/ has no fence at all\n\n## 3. Next\n"
    with pytest.raises(AssertionError, match="exactly one fenced block"):
        layout_fence(text)


def test_b2_extractor_raises_on_a_blank_fence() -> None:
    """An empty fence is the fail-open shape: every roster check would pass vacuously."""
    text = f"{LAYOUT_HEADING}\n\n```\n\n```\n\n## 3. Next\n"
    with pytest.raises(AssertionError, match="empty"):
        layout_fence(text)


def test_b2_extractor_raises_below_the_anti_vacuity_floor() -> None:
    """A short-but-valid fence cannot produce a verdict when a floor is demanded."""
    text = f"{LAYOUT_HEADING}\n\n```\nproactive-loop-agent/\n```\n\n## 3. Next\n"
    assert layout_fence(text)  # fine with no floor
    with pytest.raises(AssertionError, match="below the"):
        layout_fence(text, min_chars=MIN_FENCE_CHARS)


# --- Behavior 3: the collector count is bound to the registry -----------------------


def test_b3_registries_are_non_empty() -> None:
    """Anti-vacuity: every expectation below is derived from these, so 0 would pass all."""
    assert len(all_collectors()) > 1
    assert len(live_collector_modules()) > 1
    assert len(live_verbs()) > 1


def test_b3_declared_collector_count_equals_the_registry() -> None:
    """The fence's numeral is the registry's size -- never a literal in this file."""
    assert count_drift(_live_fence(), "collector modules", len(all_collectors())) is None


def test_b3_control_a_count_one_lower_fails() -> None:
    """Two-sided proof: doctor the numeral down by one and the guard names the drift."""
    live = len(all_collectors())
    doctored = _live_fence().replace(
        f"{live} collector modules", f"{live - 1} collector modules"
    )
    message = count_drift(doctored, "collector modules", live)
    assert message is not None
    assert f"declares {live - 1}" in message and f"has {live}" in message


# --- Behavior 4: the verb count is bound to the parser ------------------------------


def test_b4_declared_verb_count_equals_the_parser() -> None:
    assert count_drift(_live_fence(), "verbs", len(live_verbs())) is None


def test_b4_control_the_pre_fix_fourteen_fails() -> None:
    """The count this commit corrected must not be able to come back green."""
    live = len(live_verbs())
    doctored = _live_fence().replace(f"{live} verbs", "14 verbs")
    message = count_drift(doctored, "verbs", live)
    assert message is not None
    assert "declares 14" in message


# --- Behavior 5: no partial collector roster ----------------------------------------


def test_b5_live_fence_holds_no_partial_collector_roster() -> None:
    assert partial_roster(_live_fence(), live_collector_modules(), "{}.py") is None


def test_b5_control_the_shipped_four_of_seventeen_fails() -> None:
    """The exact defect this commit removed: 4 named, 13 silently omitted."""
    live = live_collector_modules()
    omitted = partial_roster(_roster_text(SHIPPED_DEFECT_MODULES), live, "{}.py")
    assert omitted is not None
    assert omitted == live - set(SHIPPED_DEFECT_MODULES)
    assert len(omitted) == len(live) - len(SHIPPED_DEFECT_MODULES)


def test_b5_a_complete_roster_passes() -> None:
    """EMPTY-or-COMPLETE: a future author may enumerate all 17 instead of eliding."""
    live = live_collector_modules()
    assert partial_roster(_roster_text(live), live, "{}.py") is None


def test_b5_the_mit_license_file_is_not_the_license_collector() -> None:
    """Case sensitivity is load-bearing: the fence's ``LICENSE`` line must not count."""
    assert "license" in live_collector_modules()
    assert "LICENSE" in _live_fence()
    assert partial_roster("\u251c\u2500\u2500 LICENSE   # MIT", live_collector_modules(), "{}.py") is None


# --- Behavior 6: no partial verb roster, and the reader is routed -------------------


def test_b6_cli_line_holds_no_partial_verb_roster_and_cites_the_roster() -> None:
    line = _sole_line(_live_fence(), "cli.py")
    assert partial_roster(line, live_verbs(), "{}") is None
    assert "4.5" in line, (
        "the cli.py line must route the reader to the authoritative verb roster in "
        "SPEC.md 4.5, which tests/test_spec_contract.py binds to build_parser()"
    )


def test_b6_control_the_pre_fix_fourteen_verb_line_fails() -> None:
    """The shipped defect: a 14-verb list that reads as the complete set."""
    omitted = partial_roster(PRE_FIX_CLI_LINE, live_verbs(), "{}")
    assert omitted == {"verify", "config"}


def test_b6_collectors_subtree_cites_the_collector_roster() -> None:
    line = _sole_line(_live_fence(), "collector modules")
    assert "4.1" in line, (
        "the elided collectors/ sub-tree must route the reader to SPEC.md 4.1"
    )


# --- Behavior 7: the false parity claim is retired ----------------------------------


def test_b7_the_test_parity_claim_is_gone() -> None:
    """~190 behavior modules plus contract modules is not "one per package"."""
    assert RETIRED_PARITY_CLAIM not in _live_fence()


def test_b7_the_tests_line_carries_no_count() -> None:
    """A per-iteration-churning numeral here would be stale on the next commit."""
    line = _sole_line(_live_fence(), "tests/")
    assert re.search(r"\d", line) is None, (
        f"the tests/ line must carry no digit -- the module count changes every "
        f"iteration, so a numeral there is stale on the next commit: {line!r}"
    )


# --- Behavior 8: the heading contract of test_iter58 is untouched -------------------


def test_b8_layout_heading_survives_verbatim() -> None:
    """This edit is inside the fence only; the pinned heading is byte-unchanged."""
    lines = _spec_text().splitlines()
    assert lines.count(LAYOUT_HEADING) == 1
