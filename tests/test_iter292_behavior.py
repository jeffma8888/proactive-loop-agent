"""Black-box behavior tests for factory iteration 541 (ROADMAP #332).

``pla resume`` reports every artifact the run HOLDS on disk, not only the files
written by the resuming process. Before this, ``ToolRegistry`` started empty in
each process, so ``resume --json`` on a ``done`` run printed ``"artifacts": []``
while ``runs --json`` counted the same run's files -- two shipped machine
surfaces disagreeing about one run. Offline and deterministic: every run is a
hand-built checkpoint in ``tmp_path`` driven by a scripted provider.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from proactive_loop.cli import main
from proactive_loop.loop import Checkpoint
from proactive_loop.loop.tools import ToolRegistry
from proactive_loop.models import CandidateGoal, RunState, RunStatus
from tests.test_iter158_behavior import DISPATCHED_RUN_KEYS as RESUME_KEYS
from tests.test_iter158_behavior import _TOP_KEYS as RUN_KEYS

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "examples" / "fixture_workspace"
SCRIPT = REPO / "examples" / "scripted_responses.json"


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    capsys.readouterr()
    rc = main(argv)
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def _make_run(tmp_path: Path, status: RunStatus) -> tuple[Path, Path]:
    """A run dir whose artifacts/ already holds two files (one nested)."""
    run_dir = tmp_path / "state" / "run-held"
    artifacts = run_dir / "artifacts"
    (artifacts / "notes").mkdir(parents=True)
    (artifacts / "plan.md").write_text("plan")
    (artifacts / "notes" / "a.md").write_text("note")
    state = RunState(
        goal=CandidateGoal(title="Finish the scaffold", rationale="next steps"),
        status=status,
        iterations_used=1,
        llm_calls_used=2,
        artifacts_dir=str(artifacts),
    )
    Checkpoint(run_dir / "checkpoint.json").save(state)
    (run_dir / "meta.json").write_text(
        json.dumps({"workspace_root": str(FIXTURE), "artifacts_dir": str(artifacts)})
    )
    return run_dir, artifacts


def _plan(tool: str, args: dict[str, Any]) -> dict[str, str]:
    action = {"thought": "do it", "action": {"tool": tool, "args": args}}
    return {"tag": "plan", "text": json.dumps(action)}


def test_b1_done_run_resume_lists_on_disk_artifacts_and_agrees_with_runs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    for var in ("PLA_PROVIDER", "PLA_SCRIPTED_RESPONSES"):
        monkeypatch.delenv(var, raising=False)
    run_dir, artifacts = _make_run(tmp_path, RunStatus.DONE)
    expected = [str(artifacts / "notes" / "a.md"), str(artifacts / "plan.md")]

    ckpt = run_dir / "checkpoint.json"
    before = ckpt.read_bytes()
    rc, out, err = _run(["resume", "--run-dir", str(run_dir), "--json"], capsys)
    assert rc == 0, err
    doc = json.loads(out)
    assert set(doc) == RESUME_KEYS, "the --json key set is unchanged"
    assert doc["status"] == "done"
    assert (doc["iterations_used"], doc["llm_calls_used"]) == (1, 2), "0 new LLM calls"
    assert ckpt.read_bytes() == before, "a done no-op resume must not rewrite the checkpoint"
    assert doc["artifacts"] == expected, "sorted POSIX relpaths, nested files included"
    assert "artifacts  : (none)" not in err
    assert all(f"  - {path}" in err.splitlines() for path in expected), err

    rc, out, _ = _run(["resume", "--run-dir", str(run_dir)], capsys)
    assert rc == 0
    assert "artifacts  : (none)" not in out
    assert all(f"  - {path}" in out.splitlines() for path in expected), out
    assert "artifacts  :" in out.splitlines(), out
    assert ckpt.read_bytes() == before

    rc, out, err = _run(["runs", "--state-dir", str(tmp_path / "state"), "--json"], capsys)
    assert rc == 0, err
    rows = json.loads(out)
    rows = rows["runs"] if isinstance(rows, dict) else rows
    (row,) = [r for r in rows if r["run_id"] == run_dir.name]
    assert row["artifacts"] == len(doc["artifacts"]) == 2


def test_b2_mid_run_resume_keeps_earlier_artifacts_then_appends_new_ones(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run_dir, artifacts = _make_run(tmp_path, RunStatus.BUDGET_EXHAUSTED)
    script = tmp_path / "script.json"
    script.write_text(json.dumps({"responses": [
        _plan("write_file", {"path": "plan.md", "content": "rewritten"}),
        {"tag": "check", "text": json.dumps({"done": False, "reason": "more"})},
        _plan("write_file", {"path": "zz_new.md", "content": "new"}),
        {"tag": "check", "text": json.dumps({"done": True, "reason": "complete"})},
    ]}))
    rc, out, err = _run([
        "resume", "--run-dir", str(run_dir), "--json",
        "--provider", "scripted", "--scripted-responses", str(script),
    ], capsys)
    assert rc == 0, err
    doc = json.loads(out)
    assert doc["artifacts"] == [
        str(artifacts / "notes" / "a.md"),
        str(artifacts / "plan.md"),
        str(artifacts / "zz_new.md"),
    ], "earlier files first (sorted), a rewrite is not duplicated, new files appended"
    assert (artifacts / "plan.md").read_text() == "rewritten"

    # Behavior 7: `run` still creates a fresh run dir; its --json shape is unchanged
    # and its artifacts are exactly the files that fresh run wrote.
    state = tmp_path / "fresh"
    rc, out, err = _run([
        "run", "--workspace", str(FIXTURE), "--state-dir", str(state),
        "--scripted-responses", str(SCRIPT), "--json",
    ], capsys)
    assert rc == 0, err
    run_doc = json.loads(out)
    assert set(run_doc) == RUN_KEYS
    dispatched = run_doc["dispatched"]
    assert set(dispatched) == RESUME_KEYS
    fresh_art = Path(dispatched["run_dir"]) / "artifacts"
    on_disk = sorted(str(p) for p in fresh_art.rglob("*") if p.is_file())
    assert on_disk and sorted(dispatched["artifacts"]) == on_disk
    assert len(dispatched["artifacts"]) == len(set(dispatched["artifacts"]))


def test_b3_adopt_existing_artifacts_is_idempotent_and_skips_directories(
    tmp_path: Path,
) -> None:
    tools = ToolRegistry(workspace_root=FIXTURE, artifacts_dir=tmp_path / "artifacts")
    tools.adopt_existing_artifacts()
    assert tools.artifacts() == [], "an empty sandbox adopts nothing"
    (tmp_path / "artifacts" / "b" / "empty_dir").mkdir(parents=True)
    (tmp_path / "artifacts" / "b" / "x.md").write_text("x")
    (tmp_path / "artifacts" / "a.md").write_text("a")
    tools.adopt_existing_artifacts()
    tools.adopt_existing_artifacts()
    assert tools.artifacts() == ["a.md", "b/x.md"]
