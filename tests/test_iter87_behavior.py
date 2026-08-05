"""Black-box behavior tests for iteration 77 (ships as commit-seq **factory iter
87**) --- the synthesizer's per-kind signal cap is now WEIGHT-AWARE:
``GoalSynthesizer._build_prompt`` sorts each kind's signals by descending
``weight`` (ascending-``summary`` tie-break) BEFORE the
``[:_MAX_SIGNALS_PER_KIND]`` slice, so the cap keeps the MOST RELEVANT signals
and shows them most-relevant-first, and equal-weight signals render in a total,
input-order-INDEPENDENT order (ROADMAP row #87). ``ContextSignal.weight`` is the
documented "collector-assigned relevance weight" yet was previously IGNORED at
the one place it decides WHICH signals reach the model.

ISOLATION CONTRACT (honored): these tests were written strictly from this
iteration's public contract --- the spec's "Expected Behaviors" (``pm.md``),
``README.md``, ``ROADMAP.md`` --- and the test conventions already public under
``tests/`` (``test_scout.py``, ``test_iter15_behavior.py``,
``test_iter82_behavior.py``). They drive ONLY the public surface: the pure
function ``_build_prompt(snapshot) -> str`` plus the public model constructors
``ContextSignal(...)`` / ``WorkspaceSnapshot(...)``, and assert on the returned
context-brief string. **No file under ``src/`` was read, no engineer/reviewer
note was read, and no ``git diff`` was consulted.** Every test is fully
offline/deterministic: models are constructed in memory (no LLM, no network, no
filesystem). ``_MAX_SIGNALS_PER_KIND`` (8) and ``_MAX_SUMMARY_CHARS`` (200) are
imported from the module (never hardcoded), per the spec.
"""

from __future__ import annotations

import argparse

from proactive_loop import __version__
from proactive_loop.cli import build_parser
from proactive_loop.collectors import all_collectors
from proactive_loop.llm.providers import VALID_PROVIDERS
from proactive_loop.loop.tools import ToolRegistry
from proactive_loop.models import ContextSignal, WorkspaceSnapshot
from proactive_loop.scout.synthesizer import (
    _MAX_SIGNALS_PER_KIND,
    _MAX_SUMMARY_CHARS,
    _build_prompt,
)


# ---------------------------------------------------------------------------
# Black-box helpers (public constructors only)
# ---------------------------------------------------------------------------


def _sig(kind: str, summary: str, weight: float) -> ContextSignal:
    """A ContextSignal of a given kind/summary/weight (source/path fixed)."""
    return ContextSignal(
        source="probe", kind=kind, summary=summary, path=None, weight=weight
    )


def _brief(signals: list[ContextSignal]) -> str:
    """Render the context brief for a snapshot of the given signals."""
    return _build_prompt(WorkspaceSnapshot(root="/tmp/w", signals=signals))


def _header_line(brief: str, kind: str) -> str | None:
    """The exact ``## <kind> (...)`` header line, or None if absent."""
    prefix = f"## {kind} ("
    for line in brief.splitlines():
        if line.startswith(prefix):
            return line
    return None


def _block_lines(brief: str, kind: str) -> list[str]:
    """All ``- ...`` lines under the given kind's header (incl. any ``(+N
    more)`` remainder line), in shown order. A blank line or the next ``## ``
    header ends the block."""
    lines = brief.splitlines()
    prefix = f"## {kind} ("
    out: list[str] = []
    capturing = False
    for line in lines:
        if line.startswith("## "):
            capturing = line.startswith(prefix)
            continue
        if capturing:
            if line.startswith("- "):
                out.append(line)
            elif line.strip() == "":
                capturing = False
    return out


def _shown_summaries(brief: str, kind: str) -> list[str]:
    """The shown signal summaries under a kind (excludes the ``(+N more)``
    remainder line), in shown order."""
    out: list[str] = []
    for line in _block_lines(brief, kind):
        content = line[2:]  # strip the "- " bullet prefix
        if content.startswith("(+"):
            continue
        out.append(content)
    return out


# ---------------------------------------------------------------------------
# Behavior 1 -- the cap keeps the highest-weight signals.
# ---------------------------------------------------------------------------


def test_b1_cap_keeps_highest_weight_signal() -> None:
    # N=10: one weight-0.99 signal whose summary sorts alphabetically LAST,
    # plus nine weight-0.10 signals whose summaries sort first.
    signals = [_sig("k", "zzz high", 0.99)]
    for i in range(1, 10):
        signals.append(_sig("k", f"aaa{i} low", 0.10))
    brief = _brief(signals)

    # The high-weight signal SURVIVES the cap (pre-fix it is dropped -- it
    # sorts last and the cap keeps the first 8 in raw emission order). This is
    # the discriminating check for the weight-aware cap.
    assert "- zzz high" in brief, (
        "the single highest-weight (0.99) signal must survive the "
        f"[:{_MAX_SIGNALS_PER_KIND}] cap; brief was:\n{brief}"
    )
    # ...and some low-weight signal was necessarily dropped (10 > 8).
    assert "- aaa8 low" not in brief and "- aaa9 low" not in brief, (
        "with 10 signals and a cap of 8, two low-weight signals must be "
        f"dropped; brief was:\n{brief}"
    )
    # Exactly _MAX_SIGNALS_PER_KIND signal lines are shown, high-weight first.
    shown = _shown_summaries(brief, "k")
    assert len(shown) == _MAX_SIGNALS_PER_KIND, (
        f"expected {_MAX_SIGNALS_PER_KIND} shown signals; got {shown}"
    )
    assert shown[0] == "zzz high", f"most-relevant signal must be first; got {shown}"


# ---------------------------------------------------------------------------
# Behavior 2 -- shown signals are ordered most-relevant-first (desc weight).
# ---------------------------------------------------------------------------


def test_b2_shown_ordered_descending_weight() -> None:
    # Distinct weights emitted OUT of weight order.
    signals = [_sig("k", "m", 0.2), _sig("k", "h", 0.9), _sig("k", "l", 0.5)]
    shown = _shown_summaries(_brief(signals), "k")
    assert shown == ["h", "l", "m"], (
        f"shown signals must be strictly descending-weight; got {shown}"
    )


# ---------------------------------------------------------------------------
# Behavior 3 -- equal-weight ties break by ascending summary,
# input-order-independently.
# ---------------------------------------------------------------------------


def test_b3_equal_weight_ties_ascending_summary() -> None:
    signals = [_sig("k", s, 0.5) for s in ["ccc", "aaa", "bbb"]]
    shown = _shown_summaries(_brief(signals), "k")
    assert shown == ["aaa", "bbb", "ccc"], (
        f"equal-weight ties must break by ASCENDING summary; got {shown}"
    )


def test_b3_input_order_independent() -> None:
    # The identical SET of tied signals in a different LIST order must yield a
    # byte-identical brief (a total, input-order-independent order).
    order_a = _brief([_sig("k", s, 0.5) for s in ["ccc", "aaa", "bbb"]])
    order_b = _brief([_sig("k", s, 0.5) for s in ["bbb", "ccc", "aaa"]])
    assert order_a == order_b, (
        "the same tied-signal set in a different list order must produce a "
        f"byte-identical brief.\n--- order_a ---\n{order_a}\n--- order_b ---\n{order_b}"
    )


# ---------------------------------------------------------------------------
# Behavior 4 -- header count and (+N more) remainder are computed from the FULL
# group and unchanged by the reorder.
# ---------------------------------------------------------------------------


def test_b4_header_count_and_remainder_use_full_group() -> None:
    signals = [_sig("k", "zzz high", 0.99)]
    for i in range(1, 10):  # nine low-weight -> N == 10
        signals.append(_sig("k", f"aaa{i} low", 0.10))
    brief = _brief(signals)

    header = _header_line(brief, "k")
    assert header == "## k (10 signal(s))", (
        f"header count must reflect the FULL group (10), not the cap; got {header!r}"
    )
    remainder = 10 - _MAX_SIGNALS_PER_KIND  # == 2
    assert f"- (+{remainder} more)" in brief, (
        f"expected exact remainder line '- (+{remainder} more)'; brief was:\n{brief}"
    )


def test_b4_no_remainder_line_when_within_cap() -> None:
    # N == _MAX_SIGNALS_PER_KIND: no signal is dropped -> no "(+... more)" line.
    signals = [_sig("k", f"s{i}", 0.5) for i in range(_MAX_SIGNALS_PER_KIND)]
    brief = _brief(signals)
    assert _header_line(brief, "k") == f"## k ({_MAX_SIGNALS_PER_KIND} signal(s))"
    assert "more)" not in brief, (
        f"no remainder line expected when N <= cap; brief was:\n{brief}"
    )


# ---------------------------------------------------------------------------
# Behavior 5 -- per-summary truncation / strip is preserved.
# ---------------------------------------------------------------------------


def test_b5_long_summary_truncated_to_max_chars() -> None:
    long_summary = "X" * (_MAX_SUMMARY_CHARS + 50)
    signals = [_sig("k", long_summary, 0.9), _sig("k", "short", 0.8)]
    brief = _brief(signals)
    truncated = "X" * _MAX_SUMMARY_CHARS
    assert f"- {truncated}" in brief, (
        f"summary must be truncated to {_MAX_SUMMARY_CHARS} chars; brief was:\n{brief}"
    )
    # Not truncated to something SHORTER, and the untruncated form is absent.
    assert f"- {long_summary}" not in brief


def test_b5_whitespace_summary_stripped() -> None:
    signals = [_sig("k", "   trimmed me   ", 0.9)]
    shown = _shown_summaries(_brief(signals), "k")
    assert shown == ["trimmed me"], (
        f"leading/trailing whitespace must be stripped; got {shown}"
    )


# ---------------------------------------------------------------------------
# Behavior 6 -- kind grouping and the empty case are unchanged (the fix
# reorders only WITHIN a kind).
# ---------------------------------------------------------------------------


def test_b6_empty_snapshot() -> None:
    brief = _brief([])
    assert "(no signals collected)" in brief, (
        f"an empty snapshot must render '(no signals collected)'; brief was:\n{brief}"
    )


def test_b6_outer_kind_order_follows_insertion_order() -> None:
    # by_kind() preserves first-seen (insertion) kind order; the fix must NOT
    # reorder the SET of kinds. Emit 'zeta' before 'alpha' -> headers in that
    # order (a buggy sort-of-kinds would put 'alpha' first).
    signals = [_sig("zeta", "z1", 0.1), _sig("alpha", "a1", 0.1)]
    brief = _brief(signals)
    kind_headers = [line for line in brief.splitlines() if line.startswith("## ")]
    assert kind_headers == ["## zeta (1 signal(s))", "## alpha (1 signal(s))"], (
        f"outer kind order must follow by_kind() insertion order; got {kind_headers}"
    )
    # Every kind header still ends with 'signal(s))'.
    for header in kind_headers:
        assert header.endswith("signal(s))"), f"malformed header {header!r}"


def test_b6_within_kind_reorder_does_not_leak_across_kinds() -> None:
    # Two kinds each with their own weights; the reorder is per-kind.
    signals = [
        _sig("kA", "a_low", 0.1),
        _sig("kA", "a_high", 0.9),
        _sig("kB", "b_low", 0.2),
        _sig("kB", "b_high", 0.8),
    ]
    brief = _brief(signals)
    assert _shown_summaries(brief, "kA") == ["a_high", "a_low"]
    assert _shown_summaries(brief, "kB") == ["b_high", "b_low"]


# ---------------------------------------------------------------------------
# Behavior 7 -- registry / version lock (a behavior-only change adds NO public
# surface): 15 collectors, 14 tools, 7 providers, 14 CLI subcommands, version
# frozen at 0.1.1.
# ---------------------------------------------------------------------------


def test_b7_collector_count_unchanged() -> None:
    assert len(all_collectors()) == 16, (
        f"a weight-aware cap fix must add NO collector; got {len(all_collectors())}"
    )


def test_b7_tool_count_unchanged() -> None:
    assert len(ToolRegistry.tool_names()) == 14, (
        f"tool registry count must stay 14; got {len(ToolRegistry.tool_names())}"
    )


def test_b7_provider_count_unchanged() -> None:
    assert len(VALID_PROVIDERS) == 7, (
        f"provider count must stay 7; got {len(VALID_PROVIDERS)}"
    )


def test_b7_cli_subcommand_count_unchanged() -> None:
    parser = build_parser()
    subactions = [
        a for a in parser._actions if isinstance(a, argparse._SubParsersAction)
    ]
    assert len(subactions) == 1, "expected exactly one subparsers action"
    assert len(subactions[0].choices) == 14, (
        f"CLI subcommand count must stay 14; got {len(subactions[0].choices)}"
    )


def test_b7_version_frozen() -> None:
    assert __version__ == "0.1.1", (
        f"a behavior-only synthesizer fix must NOT bump the version; got {__version__!r}"
    )
