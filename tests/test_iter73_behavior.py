"""Black-box behavior tests for iteration 73 (foundry state iter-63) --- the
``pla scan --collector NAME`` allowlist flag: a repeatable, registry-validated
option that restricts WHICH collectors feed synthesis (ROADMAP row #71).

ISOLATION CONTRACT (honored): these tests were written strictly against this
iteration's public contract --- the spec's "Expected Behaviors" (``pm.md``),
``README.md``, and ``SPEC.md`` --- and drive ONLY documented public surfaces:
the module-level ``proactive_loop.cli._collect`` seam (the internal-but-importable
seam the suite already treats as public, exactly as ``tests/test_iter19_behavior.py``
does), the injection point ``proactive_loop.cli.all_collectors`` (monkeypatched
with tiny local ``Collector`` doubles), and the CLI entry
``proactive_loop.cli.main(argv) -> int`` (its exit code, stderr, and written
slate). **No file under ``src/`` was read, no engineer/reviewer notes were read,
and no ``git diff`` was consulted.** Every test is fully offline: zero network,
zero API keys; the scripted provider plus the committed ``examples`` fixtures
drive the happy path.
"""

from __future__ import annotations

import contextlib
import io
import json
import logging
from pathlib import Path

import pytest

from proactive_loop import cli
from proactive_loop.cli import main
from proactive_loop.models import ContextSignal, WorkspaceSnapshot

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "examples" / "scripted_responses.json"
_CLI_LOGGER = "proactive_loop.cli"

# The 15 live collector names (spec-pinned). Used ONLY to sanity-check the
# registry premise; the argparse *choices* assertion derives from the live
# ``all_collectors()`` so it cannot drift from a hardcoded literal.
_LIVE_NAMES = frozenset(
    {
        "recent_files", "git_activity", "git_state", "git_stash", "todos",
        "notes", "dependencies", "working_tree", "test_posture",
        "merge_conflict", "large_file", "license", "secret_file", "ci_config",
        "lockfile_drift", "syntax_error",
    }
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _proj(signals):
    """Deterministic value-only projection of a signal list. ``timestamp`` is
    ``None`` on every built-in collector, so ``model_dump`` is stable across
    repeated ``collect()`` calls."""
    return [s.model_dump() for s in signals]


def _expected_signals(workspace, only):
    """Reference orchestration: the registry-order concatenation of
    ``collect()`` for EXACTLY the collectors passing the ``only`` filter,
    honouring the SPEC 4.1 never-raise guard (a raising collector -> [])."""
    out = []
    for collector in cli.all_collectors():
        if only is not None and collector.name not in only:
            continue
        try:
            out.extend(collector.collect(workspace))
        except Exception:
            pass
    return _proj(out)


def _build_ws(tmp_path):
    """A workspace where >= 2 DISTINCT collectors fire: TodoCollector (a
    ``# TODO:`` comment) and LargeFileCollector (a sparse >= 5 MB file at the
    inclusive default threshold)."""
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "app.py").write_text(
        "# TODO: refactor this function\nx = 1\n", encoding="utf-8"
    )
    with open(ws / "bigblob.bin", "wb") as fh:
        fh.truncate(5_000_000)
    return ws


def _cli_warnings(caplog):
    return [
        r
        for r in caplog.records
        if r.name == _CLI_LOGGER and r.levelno == logging.WARNING
    ]


def _run(argv):
    """Invoke the CLI capturing stdout; return ``(rc, stdout)``."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(argv)
    return rc, buf.getvalue()


def _scan_argv(ws, out, state, *extra):
    return [
        "scan",
        "--workspace", str(ws),
        "--provider", "scripted",
        "--scripted-responses", str(SCRIPT),
        "--state-dir", str(state),
        "--out", str(out),
        *extra,
    ]


def _goals_no_id(slate_path):
    slate = json.loads(Path(slate_path).read_text(encoding="utf-8"))
    goals = [{k: v for k, v in g.items() if k != "id"} for g in slate["goals"]]
    return goals, slate


class _RaisingCollector:
    """A buggy collector that violates the 4.1 never-raise convention."""

    def __init__(self, name):
        self.name = name

    def collect(self, root):
        raise RuntimeError(f"exploded inside {self.name}")


class _WellBehavedCollector:
    """A conformant collector returning one fixed, deterministic signal."""

    def __init__(self, name, *, summary="alive"):
        self.name = name
        self._summary = summary

    def collect(self, root):
        return [ContextSignal(source=self.name, kind="note", summary=self._summary)]


# ===========================================================================
# Behavior 1 --- Default = all collectors (regression).
# ===========================================================================


def test_b01_default_equals_only_none_and_positional_call(tmp_path):
    ws = _build_ws(tmp_path)

    # The positional single-arg call (how iter-19 tests invoke it) still works.
    snap_pos = cli._collect(ws)
    snap_none = cli._collect(ws, only=None)

    assert isinstance(snap_pos, WorkspaceSnapshot)
    assert snap_pos.root == str(ws)
    # only=None is byte-equal to the positional default.
    assert _proj(snap_pos.signals) == _proj(snap_none.signals)
    # Both equal the registry-order concatenation of ALL collectors' output.
    assert _proj(snap_pos.signals) == _expected_signals(ws, None)
    # Premise: the live registry is exactly the 15 documented collectors.
    assert {c.name for c in cli.all_collectors()} == _LIVE_NAMES


# ===========================================================================
# Behavior 2 --- Allowlist filters which collectors run.
# ===========================================================================


def test_b02_allowlist_filters_to_named_collectors(tmp_path):
    ws = _build_ws(tmp_path)
    full = _proj(cli._collect(ws).signals)

    only_todos = _proj(cli._collect(ws, only={"todos"}).signals)
    only_large = _proj(cli._collect(ws, only={"large_file"}).signals)
    only_both = _proj(cli._collect(ws, only={"todos", "large_file"}).signals)

    # This workspace makes BOTH collectors fire (else the test is vacuous).
    assert len(only_todos) >= 1
    assert len(only_large) >= 1

    # Each single-name filter == exactly that collector's own contribution.
    assert only_todos == _expected_signals(ws, {"todos"})
    assert only_large == _expected_signals(ws, {"large_file"})

    # only={"todos"} carries ZERO signals from any excluded collector; in
    # particular large_file fires on this ws but is absent from the result.
    assert all(d["source"] == "todos" for d in only_todos)
    assert not any(d in only_todos for d in only_large)

    # Union == registry-order concat (todos precedes large_file in the registry)
    assert only_both == _expected_signals(ws, {"todos", "large_file"})
    assert only_both == only_todos + only_large
    # ... and equals filtering the FULL output down to those two collectors.
    assert only_both == [d for d in full if d["source"] in {"todos", "large_file"}]


# ===========================================================================
# Behavior 3 --- Empty/silent allowlist, and never-raises preserved.
# ===========================================================================


def test_b03a_empty_allowlist_runs_no_collector(tmp_path):
    ws = _build_ws(tmp_path)  # collectors WOULD fire; only=set() runs none.
    snap = cli._collect(ws, only=set())
    assert isinstance(snap, WorkspaceSnapshot)
    assert snap.signals == []


def test_b03b_named_but_silent_collector_yields_no_signals(tmp_path):
    # GitStashCollector emits nothing on a non-git directory.
    snap = cli._collect(tmp_path, only={"git_stash"})
    assert snap.signals == []


def test_b03c_ss41_isolation_and_skip_is_above_the_guard(tmp_path, monkeypatch, caplog):
    # Two raising doubles; ONLY the filtered-in one should ever execute.
    monkeypatch.setattr(
        cli,
        "all_collectors",
        lambda: [_RaisingCollector("todos"), _RaisingCollector("git_state")],
    )
    caplog.set_level(logging.WARNING, logger=_CLI_LOGGER)

    snap = cli._collect(tmp_path, only={"todos"})

    # The filtered-IN raiser is contained -> [] (never propagates) and WARNed.
    assert snap.signals == []
    warnings = _cli_warnings(caplog)
    assert len(warnings) == 1, [r.getMessage() for r in warnings]
    assert "todos" in warnings[0].getMessage()
    # The filtered-OUT raiser NEVER ran (the skip sits ABOVE the try/except),
    # so it produced no warning.
    assert "git_state" not in warnings[0].getMessage()


# ===========================================================================
# Behavior 4 --- Repeatable, registry-validated flag on `scan` ONLY.
# ===========================================================================


def test_b04a_repeatable_flag_parses_and_dispatches(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    out = tmp_path / "s.json"
    rc, _ = _run(
        _scan_argv(
            ws, out, tmp_path / "st",
            "--collector", "todos", "--collector", "git_activity",
        )
    )
    assert rc == 0
    assert out.is_file()


def test_b04b_choices_are_derived_from_the_live_registry(tmp_path, capsys):
    ws = tmp_path / "ws"
    ws.mkdir()
    with pytest.raises(SystemExit) as ei:
        main(_scan_argv(ws, tmp_path / "s.json", tmp_path / "st", "--collector", "bogus"))
    assert ei.value.code == 2
    err = capsys.readouterr().err
    # Every live collector name appears as a valid choice -> the allowlist is
    # derived from all_collectors() and cannot drift from a hardcoded literal.
    for name in sorted(c.name for c in cli.all_collectors()):
        assert f"'{name}'" in err, f"{name} missing from argparse choices: {err!r}"


def test_b04c_flag_rejected_by_run_and_watch(tmp_path, capsys):
    # SPEC change (factory iter 94): --collector was extended from scan-only to
    # scan+signals (the perception inspector); test_iter94_behavior.py proves
    # `signals` now ACCEPTS it. The SURVIVING half of the iter-73 contract is that
    # the two NON-inspector verbs -- run and watch -- STILL reject it. argparse
    # rejects the unrecognized flag at PARSE time (before the handler builds any
    # client), so no provider/scripted-responses wiring is needed here.
    ws = tmp_path / "ws"
    ws.mkdir()
    for verb in ("run", "watch"):
        with pytest.raises(SystemExit) as ei:
            main([verb, "--workspace", str(ws), "--collector", "todos"])
        assert ei.value.code == 2, f"{verb} must reject --collector (exit 2)"
        err = capsys.readouterr().err
        assert "--collector" in err, f"{verb} error should name --collector: {err!r}"


# ===========================================================================
# Behavior 5 --- Unknown collector name -> parse-time usage error (exit 2),
# side-effect-free.
# ===========================================================================


def test_b05a_unknown_name_exit2_no_side_effects(tmp_path, capsys):
    ws = tmp_path / "ws"
    ws.mkdir()
    out = tmp_path / "never.json"
    state = tmp_path / "never_state"
    with pytest.raises(SystemExit) as ei:
        main(_scan_argv(ws, out, state, "--collector", "bogus"))
    assert ei.value.code == 2
    err = capsys.readouterr().err
    assert "invalid choice: 'bogus'" in err
    assert "usage:" in err  # argparse usage error, not a handler guard
    # No client built, no collection, no artifacts written.
    assert not out.exists()
    assert not state.exists()


def test_b05b_valid_then_invalid_mix_is_exit2(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    out = tmp_path / "never.json"
    with pytest.raises(SystemExit) as ei:
        main(
            _scan_argv(
                ws, out, tmp_path / "st",
                "--collector", "todos", "--collector", "bogus",
            )
        )
    assert ei.value.code == 2
    assert not out.exists()


# ===========================================================================
# Behavior 6 --- `scan --collector` wires the filter into the pipeline.
# ===========================================================================


def test_b06_scan_passes_only_from_the_flag(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "app.py").write_text("# TODO: y\n", encoding="utf-8")

    calls = []
    orig = cli._collect

    def spy(workspace, only=None):
        calls.append(only)
        return orig(workspace, only=only)

    monkeypatch.setattr(cli, "_collect", spy)

    rc1, _ = _run(_scan_argv(ws, tmp_path / "a.json", tmp_path / "st", "--collector", "todos"))
    rc2, _ = _run(_scan_argv(ws, tmp_path / "b.json", tmp_path / "st"))

    assert rc1 == 0 and rc2 == 0
    # --collector todos -> only={"todos"}; bare scan -> only=None (all 15).
    assert calls == [{"todos"}, None], calls


# ===========================================================================
# Behavior 7 --- All other scan behaviors preserved.
# ===========================================================================


def test_b07a_collector_does_not_change_the_persisted_slate(tmp_path):
    ws = _build_ws(tmp_path)
    st = tmp_path / "st"
    rc1, _ = _run(_scan_argv(ws, tmp_path / "bare.json", st))
    rc2, _ = _run(_scan_argv(ws, tmp_path / "coll.json", st, "--collector", "todos"))
    assert rc1 == 0 and rc2 == 0

    bare_goals, bare = _goals_no_id(tmp_path / "bare.json")
    coll_goals, coll = _goals_no_id(tmp_path / "coll.json")

    # A COMPLETE slate is written in both cases (the filter changes only which
    # collectors feed synthesis, never persistence).
    assert len(bare_goals) >= 1
    assert len(coll_goals) == len(bare_goals)
    # The persisted slate is identical modulo the volatile per-run goal ``id``
    # (two bare scans differ in ``id`` too); workspace_root is preserved.
    assert coll_goals == bare_goals
    assert coll["workspace_root"] == bare["workspace_root"]


def test_b07b_collector_honors_format_json_and_top(tmp_path):
    ws = _build_ws(tmp_path)
    st = tmp_path / "st"

    # --format json: one JSON object on stdout, exit 0.
    rc_json, out = _run(
        _scan_argv(ws, tmp_path / "j.json", st, "--collector", "todos", "--format", "json")
    )
    assert rc_json == 0
    obj = json.loads(out)
    assert isinstance(obj, dict)
    assert "goals" in obj

    # --top truncates stdout but NEVER the written slate.
    full_goals, _ = _goals_no_id(tmp_path / "j.json")
    rc_top, _ = _run(_scan_argv(ws, tmp_path / "t.json", st, "--collector", "todos", "--top", "1"))
    assert rc_top == 0
    top_goals, _ = _goals_no_id(tmp_path / "t.json")
    assert len(top_goals) == len(full_goals)
