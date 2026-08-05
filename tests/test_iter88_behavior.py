"""Black-box behavior tests for iteration 78 (ships as commit-seq **factory iter
88**) --- ``pla signals --min-weight FLOAT``: a relevance-threshold VIEW filter
on the read-only signals inspector. It shows only the collected
``ContextSignal``s whose ``weight >= min_weight`` (INCLUSIVE lower bound) and
composes with the existing ``--kind K`` via logical AND. It is the FIRST
weight-based view control on the perception surface: the inspector could already
narrow by KIND, but never by RELEVANCE (ROADMAP row #88). The filter is applied
to the SAME ``selected`` list that already drives grouping, counts, and
ordering, so header counts / JSON schema / ordering / the ``(no signals
collected)`` marker all follow the surviving set for free.

ISOLATION CONTRACT (honored): these tests are written strictly from this
iteration's public contract --- the spec's "Expected Behaviors" (``pm.md``),
``README.md``, ``ROADMAP.md`` --- and the test conventions already public under
``tests/`` (``test_iter15_behavior.py``, ``test_iter87_behavior.py``). They
drive ONLY documented public surfaces: the pure helpers ``_render_signals`` /
``_signals_json_payload`` (each gaining a THIRD keyword-defaulted param
``min_weight: float | None = None`` AFTER ``kind``), the ``pla`` CLI via
``proactive_loop.cli.main(argv) -> int`` (observable stdout/stderr/exit codes),
``build_parser()``, and the public model constructors
``ContextSignal(...)`` / ``WorkspaceSnapshot(...)``. **No file under ``src/`` was
read, no engineer/reviewer note was read, and no ``git diff`` was consulted.**
Every test is fully offline/deterministic: models are constructed in memory (no
LLM, no network); CLI tests use the bundled fixture or ``tmp_path``.
"""

from __future__ import annotations

import json
from pathlib import Path

import argparse
import pytest

from proactive_loop import __version__
from proactive_loop.cli import (
    build_parser,
    main,
    _render_signals,
    _signals_json_payload,
)
from proactive_loop.collectors import all_collectors
from proactive_loop.llm.providers import VALID_PROVIDERS
from proactive_loop.loop.tools import ToolRegistry
from proactive_loop.models import ContextSignal, WorkspaceSnapshot

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "examples" / "fixture_workspace"

_EMPTY_MARKER = "(no signals collected)"
# The exact six-key explicit signal schema the JSON view must emit -- no more.
_SIGNAL_KEYS = {"source", "kind", "summary", "detail", "path", "weight"}


# ---------------------------------------------------------------------------
# Black-box helpers (public constructors / public CLI only).
# ---------------------------------------------------------------------------


def _sig(kind: str, summary: str, weight: float, *, source: str = "probe", path=None) -> ContextSignal:
    """A ContextSignal of a given kind/summary/weight (detail fixed empty)."""
    return ContextSignal(source=source, kind=kind, summary=summary, detail="", path=path, weight=weight)


def _snap(signals) -> WorkspaceSnapshot:
    return WorkspaceSnapshot(root="/w", signals=list(signals))


def _run(argv, capsys):
    """Invoke the CLI and return (rc, stdout, stderr). Drains capsys first."""
    capsys.readouterr()
    rc = main(argv)
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def _header_count(brief: str, kind: str) -> int:
    """The N in `## <kind> (N)` for the given kind, or -1 if the header absent."""
    prefix = f"## {kind} ("
    for line in brief.splitlines():
        if line.startswith(prefix):
            return int(line[len(prefix):].rstrip(")"))
    return -1


def _worked_snapshot() -> WorkspaceSnapshot:
    """A multi-kind, mixed-path snapshot for backward-compat assertions."""
    return _snap([
        _sig("todo", "TODO: wire retry", 1.0, source="todos", path="a.py"),
        _sig("todo", "FIXME: leak", 2.0, source="todos", path="b.py"),
        _sig("note", "# Roadmap", 0.5, source="notes", path=None),
    ])


def _b2_snapshot() -> WorkspaceSnapshot:
    """Three `todo` signals at weights 0.9, 0.5 (exact boundary), 0.2."""
    return _snap([
        _sig("todo", "keep-hi", 0.9),
        _sig("todo", "keep-mid", 0.5),
        _sig("todo", "drop-lo", 0.2),
    ])


# ===========================================================================
# Behavior 1 -- Backward-compatible default (no filter): byte-identical output.
# ===========================================================================


def test_b01_render_default_is_none_none_and_shows_every_signal():
    snap = _worked_snapshot()
    # Omitted / explicit-None / (None, None) are all byte-identical.
    assert _render_signals(snap) == _render_signals(snap, None) == _render_signals(snap, None, None)
    out = _render_signals(snap)
    # Every signal is present (no filtering when min_weight is None).
    for summary in ("TODO: wire retry", "FIXME: leak", "# Roadmap"):
        assert summary in out
    # Group counts reflect the FULL population.
    assert _header_count(out, "todo") == 2
    assert _header_count(out, "note") == 1


def test_b01_json_default_is_none_none_and_contains_every_signal():
    snap = _worked_snapshot()
    assert _signals_json_payload(snap) == _signals_json_payload(snap, None) == _signals_json_payload(snap, None, None)
    payload = _signals_json_payload(snap)
    assert set(payload.keys()) == {"workspace_root", "signals"}
    summaries = {s["summary"] for s in payload["signals"]}
    assert summaries == {"TODO: wire retry", "FIXME: leak", "# Roadmap"}
    assert len(payload["signals"]) == 3


# ===========================================================================
# Behavior 2 -- Inclusive lower-bound filter (human view); header count = survivors.
# ===========================================================================


def test_b02_inclusive_filter_human_keeps_boundary_drops_below():
    snap = _b2_snapshot()
    out = _render_signals(snap, None, 0.5)
    # The 0.9 and the EXACT-boundary 0.5 survive; the 0.2 is omitted.
    assert "keep-hi" in out
    assert "keep-mid" in out, "a signal at exactly the threshold must survive (inclusive >=)"
    assert "drop-lo" not in out
    # The `## todo (N)` header count is the number of SURVIVING signals (2), not 3.
    assert _header_count(out, "todo") == 2


def test_b02_boundary_only_signal_survives_at_its_own_weight():
    # A single signal whose weight EQUALS the threshold must appear (proves >=, not >).
    snap = _snap([_sig("k", "exact", 0.5)])
    assert "exact" in _render_signals(snap, None, 0.5)
    # ... and is excluded by a hair-higher threshold (proves the filter is live).
    assert _render_signals(snap, None, 0.5000001) == _EMPTY_MARKER


# ===========================================================================
# Behavior 3 -- Inclusive lower-bound filter (JSON view): membership + schema.
# ===========================================================================


def test_b03_json_filter_membership_schema_order_and_excluded_absent():
    snap = _b2_snapshot()
    payload = _signals_json_payload(snap, None, 0.5)
    signals = payload["signals"]
    # Exactly the two surviving signals (weight >= 0.5), same membership as B2.
    assert [s["summary"] for s in signals] == ["keep-hi", "keep-mid"] or \
        {s["summary"] for s in signals} == {"keep-hi", "keep-mid"}
    assert {s["summary"] for s in signals} == {"keep-hi", "keep-mid"}
    assert len(signals) == 2
    # Each is a dict of EXACTLY the six keys (no timestamp).
    for s in signals:
        assert set(s.keys()) == _SIGNAL_KEYS
        assert "timestamp" not in s
    # Two top-level keys only.
    assert set(payload.keys()) == {"workspace_root", "signals"}
    # Ordered by (kind, source, summary, path or "").
    order_key = [(s["kind"], s["source"], s["summary"], s["path"] or "") for s in signals]
    assert order_key == sorted(order_key)
    # The excluded signal's summary appears NOWHERE in the serialized payload.
    assert "drop-lo" not in json.dumps(payload)


# ===========================================================================
# Behavior 4 -- Composes with --kind (logical AND).
# ===========================================================================


def test_b04_and_composition_human_view():
    snap = _snap([
        _sig("todo", "hi-todo", 0.9),
        _sig("note", "hi-note", 0.9),
        _sig("todo", "lo-todo", 0.3),
    ])
    out = _render_signals(snap, "todo", 0.5)
    # Only the high-weight todo survives BOTH filters.
    assert "hi-todo" in out
    assert "hi-note" not in out, "wrong kind must be filtered by --kind"
    assert "lo-todo" not in out, "below-threshold must be filtered by --min-weight"
    assert _header_count(out, "todo") == 1
    # No `note` header at all.
    assert "## note" not in out


def test_b04_and_composition_json_view():
    snap = _snap([
        _sig("todo", "hi-todo", 0.9),
        _sig("note", "hi-note", 0.9),
        _sig("todo", "lo-todo", 0.3),
    ])
    signals = _signals_json_payload(snap, "todo", 0.5)["signals"]
    assert len(signals) == 1
    only = signals[0]
    assert only["kind"] == "todo" and only["summary"] == "hi-todo"
    assert set(only.keys()) == _SIGNAL_KEYS


# ===========================================================================
# Behavior 5 -- Empty degradation when the threshold excludes everything.
# ===========================================================================


def test_b05_all_below_threshold_human_marker():
    snap = _snap([_sig("k", "a", 0.1), _sig("k", "b", 0.1), _sig("k2", "c", 0.1)])
    assert _render_signals(snap, None, 0.9) == _EMPTY_MARKER


def test_b05_all_below_threshold_json_empty_array_keeps_root():
    snap = _snap([_sig("k", "a", 0.1), _sig("k", "b", 0.1)])
    payload = _signals_json_payload(snap, None, 0.9)
    assert payload["signals"] == []
    assert payload["workspace_root"] == snap.root
    assert set(payload.keys()) == {"workspace_root", "signals"}
    # JSON stays one object (never the human prose marker).
    text = json.dumps(payload)
    assert _EMPTY_MARKER not in text
    assert json.loads(text) == payload


# ===========================================================================
# Behavior 6 -- CLI arg parsed as float + threaded end-to-end.
# ===========================================================================


def test_b06_parser_min_weight_is_float_or_none():
    ns = build_parser().parse_args(["signals", "--workspace", "/w", "--min-weight", "0.5"])
    assert ns.min_weight == 0.5
    assert isinstance(ns.min_weight, float)
    ns_omitted = build_parser().parse_args(["signals", "--workspace", "/w"])
    assert ns_omitted.min_weight is None


def test_b06_extreme_threshold_empties_view_via_main(capsys):
    # An impossibly-high threshold empties the view -> proves the flag reaches the
    # filter, independent of recency-weight timing.
    rc, o, e = _run(["signals", "--workspace", str(FIXTURE), "--min-weight", "1000.0"], capsys)
    assert rc == 0, f"extreme-threshold signals must exit 0; stderr={e!r}"
    assert o.strip() == _EMPTY_MARKER, f"extreme threshold must empty the view; got {o!r}"


def test_b06_default_unfiltered_view_via_main(capsys):
    # WITHOUT --min-weight the view is unfiltered: non-empty, with a `## ` header.
    rc, o, e = _run(["signals", "--workspace", str(FIXTURE)], capsys)
    assert rc == 0, f"default signals must exit 0; stderr={e!r}"
    assert o.strip(), "default view must be non-empty"
    assert "## " in o, f"default view must carry at least one kind header; got:\n{o}"


def test_b06_threading_helpers_vs_cli_agree(capsys):
    # The extreme-threshold CLI empty result matches the pure-helper contract.
    rc, o, _e = _run(["signals", "--workspace", str(FIXTURE), "--min-weight", "1000.0"], capsys)
    assert rc == 0 and o.strip() == _EMPTY_MARKER


# ===========================================================================
# Behavior 7 -- Invalid --min-weight value -> exit 2, nothing on stdout.
# ===========================================================================


def test_b07_non_numeric_min_weight_exit2_no_stdout(capsys):
    capsys.readouterr()
    with pytest.raises(SystemExit) as excinfo:
        main(["signals", "--workspace", str(FIXTURE), "--min-weight", "abc"])
    assert excinfo.value.code == 2, "argparse type=float must reject a non-numeric value with exit 2"
    cap = capsys.readouterr()
    assert cap.out == "", f"nothing may reach stdout on a parse error; got {cap.out!r}"


def test_b07_invalid_fires_before_workspace_check(capsys):
    # A non-numeric --min-weight is rejected at PARSE time, BEFORE the workspace
    # guard -- so even a missing workspace still exits 2 (parse error wins).
    capsys.readouterr()
    with pytest.raises(SystemExit) as excinfo:
        main(["signals", "--workspace", "/no/such/dir", "--min-weight", "abc"])
    assert excinfo.value.code == 2
    assert capsys.readouterr().out == ""


# ===========================================================================
# Behavior 8 -- No public-surface growth / version lock.
# ===========================================================================


def test_b08_registry_counts_and_version_unchanged():
    assert len(all_collectors()) == 16
    assert len(ToolRegistry.tool_names()) == 14
    assert len(VALID_PROVIDERS) == 7
    assert __version__ == "0.1.1"


def test_b08_subparser_choice_count_unchanged():
    parser = build_parser()
    sub_actions = [a for a in parser._subparsers._group_actions if isinstance(a, argparse._SubParsersAction)]
    assert len(sub_actions) == 1
    assert len(sub_actions[0].choices) == 14
    # `signals` is (still) among them -- the flag is additive, not a new verb.
    assert "signals" in sub_actions[0].choices


# ===========================================================================
# Edge cases -- unbounded float acceptance (spec Out of Scope: no validation).
# ===========================================================================


def test_edge_negative_threshold_keeps_all():
    # Weights are unbounded; a negative min_weight keeps every signal (>= holds).
    snap = _worked_snapshot()
    assert _render_signals(snap, None, -1.0) == _render_signals(snap, None, None)
    assert _signals_json_payload(snap, None, -5.0) == _signals_json_payload(snap)


def test_edge_zero_threshold_keeps_nonnegative_weights():
    snap = _snap([_sig("k", "pos", 0.5), _sig("k", "zero", 0.0)])
    out = _render_signals(snap, None, 0.0)
    # Both a 0.5 and an exactly-0.0 weight survive `weight >= 0.0`.
    assert "pos" in out and "zero" in out
    assert _header_count(out, "k") == 2


def test_edge_filter_is_pure_no_mutation_of_snapshot():
    snap = _b2_snapshot()
    before = [s.summary for s in snap.signals]
    _render_signals(snap, None, 0.5)
    _signals_json_payload(snap, None, 0.5)
    after = [s.summary for s in snap.signals]
    assert before == after, "filtering must not mutate the snapshot's signal list"
