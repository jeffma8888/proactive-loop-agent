"""Tests for the L1 goal loop (tools, resilience, executor).

Coverage maps to SPEC 4.4:
- a 2-iteration scripted run reaches DONE and leaves an artifact on disk;
- the tool sandbox rejects '..' traversal and absolute paths (write and read);
- with_retry backs off correctly (throttle twice then succeed, exact sleep
  sequence via an injected spy) and re-raises after max_attempts, but never
  retries a non-retryable error;
- GoalLoop wraps its LLM calls in with_retry (throttle-then-recover in a run);
- the loop stops with BUDGET_EXHAUSTED at max_iterations;
- an unparseable PLAN is fed back and the run continues;
- Checkpoint save -> load -> resume round-trips and accumulates state.

Everything is offline: the only LLM is ScriptedLLMClient.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from proactive_loop.config import RetryPolicy, Settings
from proactive_loop.llm.client import (
    LLMThrottleError,
    LLMTimeoutError,
    ScriptedLLMClient,
)
from proactive_loop.loop.executor import GoalLoop
from proactive_loop.loop.resilience import Checkpoint, with_retry
from proactive_loop.loop.tools import ToolRegistry
from proactive_loop.models import CandidateGoal, RunState, RunStatus, StepKind


# --- shared fixtures -------------------------------------------------------


def _goal() -> CandidateGoal:
    """A tiny deterministic goal for loop runs."""
    return CandidateGoal(
        title="Write a learning plan",
        rationale="capture next steps",
        suggested_first_steps=["draft learning_plan.md"],
    )


def _plan(tool: str, args: dict) -> dict:
    """A scripted PLAN entry returning a well-formed action."""
    return {"tag": "plan", "text": json.dumps({"thought": "do it", "action": {"tool": tool, "args": args}})}


def _check(done: bool, reason: str = "") -> dict:
    """A scripted CHECK entry."""
    return {"tag": "check", "text": json.dumps({"done": done, "reason": reason})}


def _tools(tmp_path: Path) -> ToolRegistry:
    return ToolRegistry(
        workspace_root=tmp_path / "workspace",
        artifacts_dir=tmp_path / "artifacts",
    )


def _no_sleep(_: float) -> None:
    """Sleep spy that never waits (used where timing is irrelevant)."""


# --- 2-iteration run reaches DONE with an artifact -------------------------


def test_two_iteration_run_reaches_done_with_artifact(tmp_path: Path) -> None:
    """First iter writes a file (not done), second iter confirms done."""
    tools = _tools(tmp_path)
    client = ScriptedLLMClient(
        [
            _plan("write_file", {"path": "learning_plan.md", "content": "step 1\nstep 2\n"}),
            _check(False, "written, verifying"),
            _plan("read_file", {"path": "learning_plan.md"}),
            _check(True, "artifact present"),
        ]
    )
    loop = GoalLoop(client, Settings(), tools, sleep=_no_sleep)

    state = loop.run(_goal())

    assert state.status is RunStatus.DONE
    assert state.iterations_used == 2
    # write + read = one artifact tracked, and physically on disk.
    assert "learning_plan.md" in tools.artifacts()
    written = tmp_path / "artifacts" / "learning_plan.md"
    assert written.is_file()
    assert written.read_text() == "step 1\nstep 2\n"
    # 2 iterations * (plan + check) = 4 model calls.
    assert state.llm_calls_used == 4
    # plan, act, check, plan, act, check
    assert [s.kind for s in state.steps] == [
        StepKind.PLAN, StepKind.ACT, StepKind.CHECK,
        StepKind.PLAN, StepKind.ACT, StepKind.CHECK,
    ]


# --- sandbox rejects traversal and absolute paths --------------------------


def test_sandbox_rejects_parent_traversal(tmp_path: Path) -> None:
    """write_file('../evil', ...) is refused and nothing escapes the sandbox."""
    tools = _tools(tmp_path)

    obs = tools.execute("write_file", {"path": "../evil", "content": "pwn"})

    assert obs.startswith("error:")
    assert "traversal" in obs
    assert tools.artifacts() == []
    # The escape target must NOT exist anywhere near the sandbox parent.
    assert not (tmp_path / "evil").exists()
    assert not (tmp_path / "artifacts").joinpath("..", "evil").exists()


def test_sandbox_rejects_absolute_and_reads(tmp_path: Path) -> None:
    """Absolute writes are refused; reads reject traversal too."""
    tools = _tools(tmp_path)

    write_abs = tools.execute("write_file", {"path": "/etc/passwd", "content": "x"})
    read_up = tools.execute("read_file", {"path": "../../secret"})

    assert write_abs.startswith("error:") and "absolute" in write_abs
    assert read_up.startswith("error:") and "traversal" in read_up
    assert tools.artifacts() == []


def test_unknown_tool_returns_error_observation(tmp_path: Path) -> None:
    """An unknown tool never raises; it yields an 'error:' observation."""
    tools = _tools(tmp_path)

    obs = tools.execute("format_hard_drive", {})

    assert obs.startswith("error:")
    assert "unknown tool" in obs


# --- with_retry backoff behavior ------------------------------------------


def test_with_retry_backoff_sequence_throttle_twice_then_succeed() -> None:
    """Throttle twice, succeed on the third call; assert the exact backoff."""
    policy = RetryPolicy(
        max_attempts=5, base_backoff_sec=1.0, backoff_factor=2.0, jitter_frac=0.0
    )
    attempts = {"n": 0}

    def flaky() -> str:
        attempts["n"] += 1
        if attempts["n"] <= 2:
            raise LLMThrottleError("429")
        return "ok"

    sleeps: list[float] = []
    retries: list[tuple[int, float]] = []

    result = with_retry(
        flaky,
        policy,
        sleep=sleeps.append,
        on_retry=lambda attempt, delay, exc: retries.append((attempt, delay)),
    )

    assert result == "ok"
    assert attempts["n"] == 3
    # min(1*2**0, 60)=1.0 then min(1*2**1, 60)=2.0.
    assert sleeps == [1.0, 2.0]
    assert retries == [(1, 1.0), (2, 2.0)]


def test_with_retry_reraises_after_max_attempts() -> None:
    """A persistently-throttled call re-raises after max_attempts."""
    policy = RetryPolicy(
        max_attempts=3, base_backoff_sec=1.0, backoff_factor=2.0, jitter_frac=0.0
    )
    sleeps: list[float] = []

    def always_timeout() -> str:
        raise LLMTimeoutError("slow")

    with pytest.raises(LLMTimeoutError):
        with_retry(always_timeout, policy, sleep=sleeps.append)

    # 3 attempts -> 2 backoff sleeps between them.
    assert sleeps == [1.0, 2.0]


def test_with_retry_does_not_retry_non_retryable() -> None:
    """A non-throttle/timeout error propagates immediately with no sleeping."""
    policy = RetryPolicy(max_attempts=5, jitter_frac=0.0)
    sleeps: list[float] = []

    def boom() -> str:
        raise ValueError("not retryable")

    with pytest.raises(ValueError):
        with_retry(boom, policy, sleep=sleeps.append)

    assert sleeps == []


def test_with_retry_backoff_is_capped_at_max() -> None:
    """Delays never exceed max_backoff_sec even as the exponent grows."""
    policy = RetryPolicy(
        max_attempts=6,
        base_backoff_sec=1.0,
        backoff_factor=10.0,
        max_backoff_sec=5.0,
        jitter_frac=0.0,
    )
    sleeps: list[float] = []

    def always_throttle() -> str:
        raise LLMThrottleError("429")

    with pytest.raises(LLMThrottleError):
        with_retry(always_throttle, policy, sleep=sleeps.append)

    # 1.0, then capped at 5.0 thereafter.
    assert sleeps == [1.0, 5.0, 5.0, 5.0, 5.0]


# --- GoalLoop wraps LLM calls in with_retry --------------------------------


def test_goalloop_recovers_from_throttle_within_a_run(tmp_path: Path) -> None:
    """A throttled PLAN retries with backoff, then the run completes."""
    tools = _tools(tmp_path)
    client = ScriptedLLMClient(
        [
            {"tag": "plan", "raise": "throttle"},
            {"tag": "plan", "raise": "throttle"},
            _plan("write_file", {"path": "out.md", "content": "done"}),
            _check(True, "complete"),
        ]
    )
    settings = Settings(
        retry=RetryPolicy(
            max_attempts=5, base_backoff_sec=1.0, backoff_factor=2.0, jitter_frac=0.0
        )
    )
    sleeps: list[float] = []
    loop = GoalLoop(client, settings, tools, sleep=sleeps.append)

    state = loop.run(_goal())

    assert state.status is RunStatus.DONE
    # Two throttles on the first PLAN => two backoff sleeps of 1.0 and 2.0.
    assert sleeps == [1.0, 2.0]
    assert (tmp_path / "artifacts" / "out.md").read_text() == "done"


# --- budget exhaustion -----------------------------------------------------


def test_budget_exhaustion_stops_at_max_iterations(tmp_path: Path) -> None:
    """When CHECK never reports done, the loop stops at max_iterations."""
    tools = _tools(tmp_path)
    client = ScriptedLLMClient(
        [
            _plan("write_file", {"path": "a.md", "content": "1"}),
            _check(False, "not yet"),
            _plan("write_file", {"path": "b.md", "content": "2"}),
            _check(False, "still not"),
        ]
    )
    settings = Settings(max_iterations=2)
    loop = GoalLoop(client, settings, tools, sleep=_no_sleep)

    state = loop.run(_goal())

    assert state.status is RunStatus.BUDGET_EXHAUSTED
    assert state.iterations_used == 2
    assert state.llm_calls_used == 4


# --- unparseable PLAN is fed back and the run continues --------------------


def test_unparseable_plan_is_fed_back_then_run_continues(tmp_path: Path) -> None:
    """A garbage PLAN counts as an iteration and yields an error observation."""
    tools = _tools(tmp_path)
    client = ScriptedLLMClient(
        [
            {"tag": "plan", "text": "not json at all <<<"},
            _plan("write_file", {"path": "c.md", "content": "ok"}),
            _check(True, "done now"),
        ]
    )
    settings = Settings(max_iterations=5)
    loop = GoalLoop(client, settings, tools, sleep=_no_sleep)

    state = loop.run(_goal())

    assert state.status is RunStatus.DONE
    assert state.iterations_used == 2  # the bad plan counted as an iteration
    # First iteration recorded PLAN then an ACT error observation (no CHECK).
    assert state.steps[0].kind is StepKind.PLAN
    assert state.steps[1].kind is StepKind.ACT
    assert state.steps[1].output.startswith("error:")
    assert (tmp_path / "artifacts" / "c.md").is_file()


# --- checkpoint save -> load -> resume round-trip --------------------------


def test_checkpoint_save_load_resume_round_trip(tmp_path: Path) -> None:
    """Interrupt after one iteration, reload the checkpoint, resume to DONE."""
    artifacts_dir = tmp_path / "artifacts"
    workspace = tmp_path / "workspace"
    ckpt_path = tmp_path / "runs" / "state.json"
    checkpoint = Checkpoint(ckpt_path)

    # Phase 1: budget=1 iteration, CHECK not done => BUDGET_EXHAUSTED, saved.
    tools1 = ToolRegistry(workspace_root=workspace, artifacts_dir=artifacts_dir)
    client1 = ScriptedLLMClient(
        [
            _plan("write_file", {"path": "plan.md", "content": "phase1"}),
            _check(False, "need another pass"),
        ]
    )
    loop1 = GoalLoop(client1, Settings(max_iterations=1), tools1, checkpoint, sleep=_no_sleep)
    state1 = loop1.run(_goal())

    assert state1.status is RunStatus.BUDGET_EXHAUSTED
    assert state1.iterations_used == 1
    assert ckpt_path.is_file()

    # Load from disk and confirm the round-trip preserved everything.
    loaded = checkpoint.load()
    assert loaded is not None
    assert loaded.run_id == state1.run_id
    assert loaded.iterations_used == 1
    assert loaded.llm_calls_used == 2
    assert len(loaded.steps) == 3
    assert loaded.goal.title == "Write a learning plan"

    # Phase 2: resume with a fresh client + higher budget; run to DONE.
    tools2 = ToolRegistry(workspace_root=workspace, artifacts_dir=artifacts_dir)
    client2 = ScriptedLLMClient(
        [
            _plan("write_file", {"path": "plan.md", "content": "phase2 final"}),
            _check(True, "finished"),
        ]
    )
    loop2 = GoalLoop(client2, Settings(max_iterations=5), tools2, checkpoint, sleep=_no_sleep)
    resumed = loop2.run(_goal(), resume=loaded)

    assert resumed.status is RunStatus.DONE
    # 1 (phase 1) + 1 (phase 2) iterations; steps accumulated, not reset.
    assert resumed.iterations_used == 2
    assert resumed.run_id == state1.run_id
    assert len(resumed.steps) == 6
    assert resumed.llm_calls_used == 4
    assert (artifacts_dir / "plan.md").read_text() == "phase2 final"

    # The final checkpoint on disk reflects the resumed, completed run.
    final_on_disk = checkpoint.load()
    assert final_on_disk is not None
    assert final_on_disk.status is RunStatus.DONE
    assert final_on_disk.iterations_used == 2


def test_checkpoint_load_missing_returns_none(tmp_path: Path) -> None:
    """Loading a never-written checkpoint returns None, not an error."""
    assert Checkpoint(tmp_path / "nope.json").load() is None


def test_checkpoint_save_is_atomic_no_tmp_left_behind(tmp_path: Path) -> None:
    """After save, only the final file exists (temp swapped away)."""
    ckpt_path = tmp_path / "runs" / "state.json"
    checkpoint = Checkpoint(ckpt_path)
    state = RunState(goal=_goal(), artifacts_dir=str(tmp_path))

    checkpoint.save(state)

    assert ckpt_path.is_file()
    leftovers = list(ckpt_path.parent.glob("*.tmp"))
    assert leftovers == []
    # Reloaded state equals what we saved.
    assert checkpoint.load().run_id == state.run_id  # type: ignore[union-attr]
