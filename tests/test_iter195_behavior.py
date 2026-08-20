"""Behavior oracle for the ``SPEC.md`` ``## 2. Layout`` orientation map.

Independently derived from this iteration's spec (Expected Behaviors 1-8), black-box:
it reads one tracked document and drives the two LIVE registries through their public
entry points (``all_collectors()``, ``build_parser()``). No implementation module is
imported beyond those two published surfaces.

Why this file exists, in one line: section 2's fenced tree is the first thing any
reader -- human or automated contributor -- uses to orient in this repo, and it is the
one enumerating region ``tests/test_spec_contract.py`` cannot see, because that guard's
extractor is deliberately fence-AWARE (``### 4.1`` embeds ``python`` code blocks whose
first line is a ``# base.py`` comment) while section 2 *is* one fence. An unguardable
enumeration can only rot.

Two properties this module is built around:

1. **Every numeral is derived, never hardcoded.** ``17`` and ``16`` are today's values;
   the assertions compare the document against ``len(all_collectors())`` and the live
   subparser choices, so adding collector 18 or verb 17 reds this build rather than
   silently widening the drift.
2. **Every content check is proven two-sided by MUTATING THE LIVE FENCE.** A synthetic
   fixture can pass while the guard is blind to the shipped defect, so each negative
   control is the live fence with exactly one line replaced by the real pre-fix text
   (recovered from the document's own history while writing this file) and asserts the
   same predicate FAILS. Each control also asserts the mutation actually changed the
   text, so a fence reshaped later cannot leave a control silently vacuous.

Offline and cheap by construction: one tracked file read, one package import, no
network, no subprocess, no tmp tree -- identical behavior in a fresh clone.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import pytest

from proactive_loop.cli import build_parser
from proactive_loop.collectors import all_collectors

REPO = Path(__file__).resolve().parents[1]
SPEC = REPO / "SPEC.md"
GUARD = REPO / "tests" / "test_spec_layout_contract.py"

LAYOUT_HEADING = "## 2. Layout"

# Anti-vacuity floor on the EXTRACTED fence: today's is 1,901 chars, and a mis-slice
# produces a handful. A smoke alarm for a broken extractor, not a size budget.
MIN_FENCE_CHARS = 1_000

# The verbatim pre-fix lines of this very fence, used as negative controls. Kept as
# literals (not read from git) so the controls behave identically in a fresh clone.
PREFIX_COLLECTOR_LINES = [
    "\u2502   \u2502   \u251c\u2500\u2500 filesystem.py     # RecentFilesCollector",
    "\u2502   \u2502   \u251c\u2500\u2500 git_activity.py   # GitActivityCollector",
    "\u2502   \u2502   \u251c\u2500\u2500 todos.py          # TodoCollector",
    "\u2502   \u2502   \u2514\u2500\u2500 notes.py          # NotesCollector",
]
PREFIX_CLI_LINE = (
    "\u2502   \u2514\u2500\u2500 cli.py                # argparse CLI: scan / dispatch / run / "
    "resume / runs / explain / trace / signals / watch / diff / policy / tools / "
    "collectors / providers"
)
PREFIX_TESTS_LINE = "\u2514\u2500\u2500 tests/                    # one test module per package"


# --------------------------------------------------------------------------- #
# extractor
# --------------------------------------------------------------------------- #
def _fence_mask(lines: list[str]) -> list[bool]:
    """Per line, whether it sits inside a fenced block; marker lines count as inside."""
    inside = False
    mask: list[bool] = []
    for line in lines:
        if _is_fence_marker(line):
            mask.append(True)
            inside = not inside
            continue
        mask.append(inside)
    return mask


def _is_fence_marker(line: str) -> bool:
    stripped = line.lstrip()
    return stripped.startswith("```") or stripped.startswith("~~~")


def layout_fence(text: str) -> str:
    """Return the single fenced block inside *text*'s ``## 2. Layout`` section.

    Fence marker lines are stripped; the returned string is the block's content only.
    RAISES ``AssertionError`` when the heading is absent or duplicated, when the
    section holds no fenced block, and when a fence is left unterminated -- never
    returns ``""``, because an empty return converts a renamed section into either a
    false alarm or a permanently-green guard.
    """
    lines = text.splitlines()
    mask = _fence_mask(lines)

    starts = [
        i for i, line in enumerate(lines) if not mask[i] and line.strip() == LAYOUT_HEADING
    ]
    assert len(starts) == 1, (
        f"SPEC.md must hold exactly one {LAYOUT_HEADING!r} heading outside a code "
        f"fence, found {len(starts)}. A deliberate rename must update this guard in "
        "the SAME commit -- do not leave the orientation map un-guarded."
    )
    start = starts[0]

    end = len(lines)
    for i in range(start + 1, len(lines)):
        if not mask[i] and re.match(r"#{1,6} \S", lines[i]):
            end = i
            break

    blocks: list[str] = []
    current: list[str] = []
    open_block = False
    for i in range(start + 1, end):
        line = lines[i]
        if _is_fence_marker(line):
            if open_block:
                blocks.append("\n".join(current))
                current = []
                open_block = False
            else:
                open_block = True
            continue
        if open_block:
            current.append(line)
    assert not open_block, f"unterminated code fence inside {LAYOUT_HEADING!r}"
    assert len(blocks) == 1, (
        f"{LAYOUT_HEADING!r} must hold exactly one fenced block (the layout tree), "
        f"found {len(blocks)}"
    )
    return blocks[0]


# --------------------------------------------------------------------------- #
# live registries + per-line predicates (shared by live text and every control)
# --------------------------------------------------------------------------- #
def live_collector_modules() -> set[str]:
    return {type(c).__module__.rsplit(".", 1)[-1] for c in all_collectors()}


def live_verbs() -> set[str]:
    for action in build_parser()._actions:
        if isinstance(action, argparse._SubParsersAction):
            return set(action.choices)
    raise AssertionError("build_parser() exposes no subparsers")


def _sole_line(fence: str, needle: str) -> str:
    hits = [line for line in fence.splitlines() if needle in line]
    assert len(hits) == 1, f"expected exactly one line containing {needle!r}, found {len(hits)}"
    return hits[0]


def declared_collector_count(fence: str) -> int:
    hits = re.findall(r"(\d+)\s+collector modules", fence)
    assert len(hits) == 1, (
        "the fence must declare exactly one '<N> collector modules' count, found "
        f"{len(hits)}: {hits}"
    )
    return int(hits[0])


def declared_verb_count(fence: str) -> int:
    hits = re.findall(r"(\d+)\s+verbs", fence)
    assert len(hits) == 1, (
        f"the fence must declare exactly one '<N> verbs' count, found {len(hits)}: {hits}"
    )
    return int(hits[0])


def named_collector_modules(fence: str) -> set[str]:
    """Live collector module stems spelled as ``<stem>.py`` anywhere in *fence*."""
    return {
        stem
        for stem in live_collector_modules()
        if re.search(rf"\b{re.escape(stem)}\.py\b", fence)
    }


def named_verbs(line: str) -> set[str]:
    return {verb for verb in live_verbs() if re.search(rf"\b{re.escape(verb)}\b", line)}


def _replace_line(fence: str, needle: str, replacement: list[str]) -> str:
    """Swap the sole line containing *needle* for *replacement*; assert it changed."""
    lines = fence.splitlines()
    idx = [i for i, line in enumerate(lines) if needle in line]
    assert len(idx) == 1, f"control needs exactly one {needle!r} line, found {len(idx)}"
    mutated = "\n".join(lines[: idx[0]] + replacement + lines[idx[0] + 1 :])
    assert mutated != fence, f"negative control for {needle!r} did not change the fence"
    return mutated


@pytest.fixture(scope="module")
def spec_text() -> str:
    return SPEC.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def fence(spec_text: str) -> str:
    return layout_fence(spec_text)


# --------------------------------------------------------------------------- #
# Behavior 1 -- fence extraction on the LIVE document
# --------------------------------------------------------------------------- #
def test_behavior_1_layout_fence_extracts_the_live_tree(fence: str) -> None:
    assert len(fence) >= MIN_FENCE_CHARS, (
        f"extracted fence is {len(fence)} chars, below the {MIN_FENCE_CHARS}-char "
        "anti-vacuity floor -- the extractor is mis-slicing, so no verdict below it "
        "would mean anything"
    )
    for anchor in ("proactive-loop-agent/", "src/proactive_loop/", "tests/"):
        assert anchor in fence, f"layout tree lost its {anchor!r} anchor"
    assert not any(_is_fence_marker(line) for line in fence.splitlines()), (
        "extracted fence still contains a fence marker line -- markers must be stripped"
    )


# --------------------------------------------------------------------------- #
# Behavior 2 -- the extractor is never silently empty
# --------------------------------------------------------------------------- #
def test_behavior_2_missing_heading_raises() -> None:
    with pytest.raises((AssertionError, ValueError)):
        layout_fence("# Title\n\n## 3. Something else\n\ntext\n")


def test_behavior_2_section_without_a_fence_raises() -> None:
    with pytest.raises((AssertionError, ValueError)):
        layout_fence(f"# Title\n\n{LAYOUT_HEADING}\n\njust prose, no fence\n\n## 3. Next\n")


def test_behavior_2_duplicate_heading_raises(spec_text: str) -> None:
    with pytest.raises((AssertionError, ValueError)):
        layout_fence(spec_text + f"\n{LAYOUT_HEADING}\n\n```\ntree\n```\n")


# --------------------------------------------------------------------------- #
# Behavior 3 -- collector count is bound to the registry
# --------------------------------------------------------------------------- #
def test_behavior_3_collector_count_matches_registry(fence: str) -> None:
    live = len(all_collectors())
    assert declared_collector_count(fence) == live, (
        f"SPEC.md section 2 declares {declared_collector_count(fence)} collector "
        f"modules but all_collectors() returns {live}"
    )


def test_behavior_3_negative_control_off_by_one_count_fails(fence: str) -> None:
    live = len(all_collectors())
    control = fence.replace(f"{live} collector modules", f"{live - 1} collector modules")
    assert control != fence, "negative control did not change the collector count"
    assert declared_collector_count(control) != live


# --------------------------------------------------------------------------- #
# Behavior 4 -- verb count is bound to the parser
# --------------------------------------------------------------------------- #
def test_behavior_4_verb_count_matches_parser(fence: str) -> None:
    live = len(live_verbs())
    assert declared_verb_count(fence) == live, (
        f"SPEC.md section 2 declares {declared_verb_count(fence)} verbs but "
        f"build_parser() exposes {live}"
    )


def test_behavior_4_negative_control_stale_verb_count_fails(fence: str) -> None:
    live = len(live_verbs())
    control = fence.replace(f"{live} verbs", "14 verbs")
    assert control != fence, "negative control did not change the verb count"
    assert declared_verb_count(control) != live


def test_behavior_4_negative_control_prefix_cli_line_has_no_count(fence: str) -> None:
    """The shipped defect declared no count at all -- a bare 14-name list."""
    control = _replace_line(fence, "cli.py", [PREFIX_CLI_LINE])
    with pytest.raises(AssertionError):
        declared_verb_count(control)


# --------------------------------------------------------------------------- #
# Behavior 5 -- no PARTIAL collector roster
# --------------------------------------------------------------------------- #
def test_behavior_5_collector_roster_is_empty_or_complete(fence: str) -> None:
    named = named_collector_modules(fence)
    live = live_collector_modules()
    assert named in (set(), live), (
        "section 2 names a PARTIAL collector roster "
        f"({len(named)} of {len(live)}): {sorted(named)}. Name all of them or none -- "
        "4.1 is the authoritative roster."
    )


def test_behavior_5_negative_control_four_module_roster_fails(fence: str) -> None:
    control = _replace_line(fence, "collector modules", PREFIX_COLLECTOR_LINES)
    named = named_collector_modules(control)
    live = live_collector_modules()
    assert named == {"filesystem", "git_activity", "todos", "notes"}, sorted(named)
    assert named not in (set(), live), "the shipped 4-of-17 defect must FAIL this check"


def test_behavior_5_complete_roster_passes(fence: str) -> None:
    live = sorted(live_collector_modules())
    control = _replace_line(
        fence,
        "collector modules",
        [f"\u2502   \u2502   \u251c\u2500\u2500 {stem}.py" for stem in live],
    )
    assert named_collector_modules(control) == set(live)


# --------------------------------------------------------------------------- #
# Behavior 6 -- no partial verb roster, and the reader is routed
# --------------------------------------------------------------------------- #
def test_behavior_6_cli_line_holds_no_partial_verb_roster(fence: str) -> None:
    line = _sole_line(fence, "cli.py")
    named = named_verbs(line)
    live = live_verbs()
    assert named in (set(), live), (
        f"the cli.py line names a PARTIAL verb roster ({len(named)} of {len(live)}): "
        f"{sorted(named)}"
    )


def test_behavior_6_cli_line_routes_to_section_4_5(fence: str) -> None:
    line = _sole_line(fence, "cli.py")
    assert "4.5" in line, f"cli.py line must route the reader to 4.5, got: {line!r}"


def test_behavior_6_collector_elision_routes_to_section_4_1(fence: str) -> None:
    line = _sole_line(fence, "collector modules")
    assert "4.1" in line, f"collector count line must route to 4.1, got: {line!r}"


def test_behavior_6_negative_control_prefix_verb_list_fails(fence: str) -> None:
    control = _replace_line(fence, "cli.py", [PREFIX_CLI_LINE])
    line = _sole_line(control, "cli.py")
    named = named_verbs(line)
    live = live_verbs()
    assert named not in (set(), live), (
        f"the shipped 14-of-16 verb list must FAIL this check; matched {sorted(named)}"
    )
    assert "4.5" not in line


# --------------------------------------------------------------------------- #
# Behavior 7 -- the false parity claim is retired, and cannot churn
# --------------------------------------------------------------------------- #
def test_behavior_7_false_parity_claim_is_gone(fence: str) -> None:
    assert "one test module per package" not in fence, (
        "section 2 still claims 'one test module per package', which the tree "
        "contradicted long ago"
    )


def test_behavior_7_tests_line_carries_no_digit(fence: str) -> None:
    line = _sole_line(fence, "tests/")
    digits = [ch for ch in line if ch.isdigit()]
    assert not digits, (
        f"the tests/ line must carry no digit (a per-iteration count would churn "
        f"every commit), found {digits} in: {line!r}"
    )


def test_behavior_7_negative_control_prefix_tests_line_fails(fence: str) -> None:
    control = _replace_line(fence, "tests/", [PREFIX_TESTS_LINE])
    assert "one test module per package" in control


# --------------------------------------------------------------------------- #
# Behavior 8 -- the heading itself survives verbatim
# --------------------------------------------------------------------------- #
def test_behavior_8_layout_heading_survives_verbatim(spec_text: str) -> None:
    headings = [line for line in spec_text.splitlines() if line.strip() == LAYOUT_HEADING]
    assert len(headings) == 1, (
        f"SPEC.md must still hold exactly one {LAYOUT_HEADING!r} heading, found "
        f"{len(headings)} -- test_iter58_behavior.py pins this string too"
    )


# --------------------------------------------------------------------------- #
# Deliverable check -- the shipped guard exists and is bound to the live registries
# --------------------------------------------------------------------------- #
def test_shipped_layout_guard_binds_to_the_live_registries() -> None:
    assert GUARD.is_file(), f"this iteration's guard is missing: {GUARD}"
    source = GUARD.read_text(encoding="utf-8")
    for surface in ("all_collectors", "build_parser"):
        assert surface in source, (
            f"{GUARD.name} must derive its counts from {surface}() rather than "
            "hardcoding today's numerals"
        )
