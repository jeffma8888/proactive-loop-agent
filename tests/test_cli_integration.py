"""End-to-end CLI integration tests (fully offline via the scripted provider).

These exercise the real wiring the demo uses -- collectors -> synthesizer ->
autonomy gate -> resilient loop -> checkpoint/artifacts -- through ``main([...])``
with no network and no API keys. The central safety property under test:
``pla run`` auto-dispatches ONLY the single top AUTO_DISPATCH goal and NEVER a
sensitive-category goal, even when that sensitive goal ranks first by score.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from proactive_loop.cli import main
from proactive_loop.config import Settings
from proactive_loop.loop import Checkpoint
from proactive_loop.models import (
    AutonomyDecision,
    GoalCategory,
    GoalSlate,
    RunStatus,
)
from proactive_loop.scout import gate_slate

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "examples" / "fixture_workspace"
SCRIPT = REPO / "examples" / "scripted_responses.json"

_SENSITIVE = {GoalCategory.FINANCE_LEGAL, GoalCategory.HEALTH_ADMIN}


def _run_args(state_dir: Path) -> list[str]:
    """The exact argument vector `make demo` uses, but into a tmp state dir."""
    return [
        "run",
        "--workspace", str(FIXTURE),
        "--provider", "scripted",
        "--scripted-responses", str(SCRIPT),
        "--state-dir", str(state_dir),
    ]


def test_run_demo_end_to_end(tmp_path, capsys):
    """The bundled demo run exits 0, writes a slate, and produces both artifacts."""
    state_dir = tmp_path / "pla_runs"

    rc = main(_run_args(state_dir))
    assert rc == 0

    # A slate JSON was written and holds exactly the four scripted goals.
    slate_path = state_dir / "slate.json"
    assert slate_path.is_file(), "run must persist the slate it acted on"
    slate = GoalSlate.model_validate_json(slate_path.read_text())
    assert len(slate.goals) == 4

    # Exactly one goal was auto-dispatched -> exactly one run dir exists.
    run_dirs = sorted(state_dir.glob("run-*"))
    assert len(run_dirs) == 1, "run must dispatch exactly one (the top AUTO) goal"
    run_dir = run_dirs[0]

    # Its loop wrote both expected artifacts under the sandboxed artifacts dir.
    artifacts = run_dir / "artifacts"
    assert (artifacts / "learning_plan.md").is_file()
    assert (artifacts / "project_scaffold.md").is_file()

    # The checkpoint round-trips and shows the run reached DONE.
    state = Checkpoint(run_dir / "checkpoint.json").load()
    assert state is not None
    assert state.status == RunStatus.DONE
    assert state.iterations_used == 3  # the 3-iteration scripted loop

    # Output surfaced the ranked table and the dispatch line.
    out = capsys.readouterr().out
    assert "DECISION" in out
    assert "auto-dispatching top goal" in out


def test_run_never_auto_runs_the_sensitive_goal(tmp_path):
    """A sensitive-category goal must NOT be executed even though it ranks first."""
    state_dir = tmp_path / "pla_runs"
    assert main(_run_args(state_dir)) == 0

    slate = GoalSlate.model_validate_json((state_dir / "slate.json").read_text())

    sensitive = [g for g in slate.goals if g.category in _SENSITIVE]
    assert sensitive, "fixture script must contain a sensitive goal to be meaningful"
    sens = sensitive[0]

    # The sensitive goal ranks first by score yet was gated to NEEDS_APPROVAL...
    decisions = {d.goal_id: d for d in gate_slate(slate, Settings())}
    assert decisions[sens.id].decision == AutonomyDecision.NEEDS_APPROVAL
    assert slate.ranked()[0].id == sens.id

    # ...and no run directory / checkpoint / artifacts were created for it.
    assert not (state_dir / f"run-{sens.id}").exists()

    # The single dispatched run is the AUTO_DISPATCH learning goal, not the
    # sensitive one.
    (run_dir,) = list(state_dir.glob("run-*"))
    assert run_dir.name != f"run-{sens.id}"
    dispatched_id = run_dir.name[len("run-"):]
    assert decisions[dispatched_id].decision == AutonomyDecision.AUTO_DISPATCH


def test_scan_writes_slate_and_gates(tmp_path, capsys):
    """`scan` prints a gated table and writes the slate to the chosen path."""
    out_path = tmp_path / "slate.json"
    rc = main([
        "scan",
        "--workspace", str(FIXTURE),
        "--provider", "scripted",
        "--scripted-responses", str(SCRIPT),
        "--state-dir", str(tmp_path / "state"),
        "--out", str(out_path),
    ])
    assert rc == 0
    assert out_path.is_file()
    slate = GoalSlate.model_validate_json(out_path.read_text())
    assert len(slate.goals) == 4
    # scan alone must not dispatch anything.
    assert not list((tmp_path / "state").glob("run-*"))


def test_dispatch_refuses_blocked_and_unapproved(tmp_path):
    """dispatch refuses a BLOCKED goal, and needs --yes for a NEEDS_APPROVAL one."""
    # First produce a slate to dispatch from.
    slate_path = tmp_path / "slate.json"
    assert main([
        "scan",
        "--workspace", str(FIXTURE),
        "--provider", "scripted",
        "--scripted-responses", str(SCRIPT),
        "--out", str(slate_path),
    ]) == 0
    slate = GoalSlate.model_validate_json(slate_path.read_text())

    blocked = next(g for g in slate.goals if not g.appropriate_now)
    sensitive = next(g for g in slate.goals if g.category in _SENSITIVE)

    def _dispatch(goal_id: str, *, yes: bool) -> int:
        argv = [
            "dispatch",
            "--slate", str(slate_path),
            "--goal-id", goal_id,
            "--provider", "scripted",
            "--scripted-responses", str(SCRIPT),
            "--state-dir", str(tmp_path / "state"),
        ]
        if yes:
            argv.append("--yes")
        return main(argv)

    # BLOCKED goal is refused even with --yes.
    assert _dispatch(blocked.id, yes=True) == 3
    # Sensitive goal needs approval; without --yes it is refused.
    assert _dispatch(sensitive.id, yes=False) == 4
    # No run dirs were created by refusals.
    assert not list((tmp_path / "state").glob("run-*"))


def test_dispatch_with_yes_runs_sensitive_goal(tmp_path):
    """With explicit --yes, a NEEDS_APPROVAL (sensitive) goal can be dispatched."""
    slate_path = tmp_path / "slate.json"
    assert main([
        "scan",
        "--workspace", str(FIXTURE),
        "--provider", "scripted",
        "--scripted-responses", str(SCRIPT),
        "--out", str(slate_path),
    ]) == 0
    slate = GoalSlate.model_validate_json(slate_path.read_text())
    sensitive = next(g for g in slate.goals if g.category in _SENSITIVE)

    rc = main([
        "dispatch",
        "--slate", str(slate_path),
        "--goal-id", sensitive.id,
        "--yes",
        "--provider", "scripted",
        "--scripted-responses", str(SCRIPT),
        "--state-dir", str(tmp_path / "state"),
    ])
    assert rc == 0
    # Now a run dir for the sensitive goal exists (human approved it explicitly).
    assert (tmp_path / "state" / f"run-{sensitive.id}").exists()


def test_unknown_goal_id_errors(tmp_path):
    """Dispatching a goal id absent from the slate is a clear error, not a crash."""
    slate_path = tmp_path / "slate.json"
    GoalSlate(workspace_root=str(FIXTURE)).model_dump_json()
    slate_path.write_text(GoalSlate(workspace_root=str(FIXTURE)).model_dump_json())
    rc = main([
        "dispatch",
        "--slate", str(slate_path),
        "--goal-id", "does-not-exist",
        "--provider", "scripted",
        "--scripted-responses", str(SCRIPT),
    ])
    assert rc == 2


def test_resume_continues_from_checkpoint(tmp_path):
    """`resume` reloads a stopped run and drives it to DONE with a fresh script."""
    import json as _json

    from proactive_loop.models import CandidateGoal, RunState

    run_dir = tmp_path / "state" / "run-resume-me"
    artifacts = run_dir / "artifacts"
    artifacts.mkdir(parents=True)

    # A run that stopped after one iteration (e.g. budget exhausted), to resume.
    goal = CandidateGoal(title="Finish the scaffold", suggested_first_steps=["write scaffold"])
    stopped = RunState(
        goal=goal,
        status=RunStatus.BUDGET_EXHAUSTED,
        iterations_used=1,
        llm_calls_used=2,
        artifacts_dir=str(artifacts),
    )
    Checkpoint(run_dir / "checkpoint.json").save(stopped)
    (run_dir / "meta.json").write_text(
        _json.dumps({"workspace_root": str(FIXTURE), "artifacts_dir": str(artifacts)})
    )

    # Exactly one more plan/check pair finishes the run.
    script = tmp_path / "resume_script.json"
    script.write_text(
        _json.dumps({
            "responses": [
                {"tag": "plan", "text": _json.dumps({
                    "thought": "finish the scaffold",
                    "action": {"tool": "write_file", "args": {"path": "scaffold.md", "content": "done"}},
                })},
                {"tag": "check", "text": _json.dumps({"done": True, "reason": "complete"})},
            ]
        })
    )

    rc = main([
        "resume",
        "--run-dir", str(run_dir),
        "--provider", "scripted",
        "--scripted-responses", str(script),
        "--state-dir", str(tmp_path / "state"),
    ])
    assert rc == 0

    final = Checkpoint(run_dir / "checkpoint.json").load()
    assert final is not None
    assert final.status == RunStatus.DONE
    assert final.iterations_used == 2  # one carried over + one new
    assert (artifacts / "scaffold.md").is_file()
