"""Black-box behavior tests for iteration 08.

Feature under test: **L0 retry telemetry** surfaced through the run state and the
CLI. ``RunState`` gains a non-negative ``retries`` counter (default ``0``); the L1
executor wires the previously-unused ``with_retry(on_retry=...)`` hook (SPEC
4.4) to increment it once per recovered backoff-retry, for **every** LLM call in
the run (PLAN and CHECK alike). The count is persisted in ``checkpoint.json``,
reported in the human run summary printed by ``dispatch`` / ``run`` / ``resume``,
and added to the ``pla trace`` human header alongside the existing
steps / iterations / llm-calls counts. The machine-readable ``trace --json``
per-step schema is left verbatim (``retries`` is run-level, not per-step).

ISOLATION CONTRACT (honored): these tests are written strictly against the
public contract -- this iteration's spec "Expected Behaviors", ``README.md``, and
``SPEC.md`` (incl. the ``RunState`` / ``with_retry`` / ``GoalLoop`` foundation
contract in SPEC.md sections 3 and 4.4) -- and drive only the documented public
surface: the ``pla`` CLI via ``proactive_loop.cli.main([...])``, the public domain
models (``CandidateGoal``, ``RunState``, ``RunStatus``, ``StepKind``,
``LoopStep``, ``GoalSlate``), the public ``proactive_loop.loop`` API
(``GoalLoop``, ``Checkpoint``, ``ScriptedLLMClient``), and the public autonomy
gate (``gate_slate``). No file under ``src/`` was read, no engineer/reviewer
notes were read, and no ``git diff`` was consulted. Field/method names were
confirmed only from the public model schema, ``SPEC.md``, and the existing
published tests (``tests/test_loop.py`` for the ``GoalLoop(..., sleep=...)`` +
throttle-recovery seam, ``tests/test_iter07_behavior.py`` for the ``trace``
render conventions), never from the implementation. Retries values are never
hard-coded against implementation quirks -- they are derived from the number of
scripted throttles the test itself injects. Every test uses a fresh ``tmp_path``
(never the repo's ``.pla_runs/``) and runs fully offline -- zero network, zero
API keys, only ``ScriptedLLMClient``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from proactive_loop.cli import main
from proactive_loop.config import RetryPolicy, Settings
from proactive_loop.llm.client import ScriptedLLMClient
from proactive_loop.loop import Checkpoint
from proactive_loop.loop.executor import GoalLoop
from proactive_loop.loop.tools import ToolRegistry
from proactive_loop.models import (
    AutonomyDecision,
    CandidateGoal,
    GoalSlate,
    LoopStep,
    RunState,
    RunStatus,
    StepKind,
)
from proactive_loop.scout import gate_slate

REPO = Path(__file__).resolve().parents[1]
# Absolute paths (runner-location-independent) to the offline fixtures.
FIXTURE = REPO / "examples" / "fixture_workspace"
SCRIPT = REPO / "examples" / "scripted_responses.json"

_CHECKPOINT_NAME = "checkpoint.json"
# Matches a per-step transcript line ("[<int>] kind ...") in the human `trace`.
_STEP_LINE = re.compile(r"^\s*\[\d+\]")
# Tolerant match for the retry-count report: a `retries` label followed by an
# integer, with any (or no) `:`/`=` separator and any surrounding whitespace.
# Never pinned to exact spacing (spec Expected Behavior 7).
_RETRIES = re.compile(r"retries\s*[:=]?\s*(\d+)", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Shared helpers (mirroring the conventions in tests/test_loop.py + iter07)
# ---------------------------------------------------------------------------


def _goal(title: str = "Write a learning plan") -> CandidateGoal:
    """A tiny deterministic goal for loop runs."""
    return CandidateGoal(
        title=title,
        rationale="capture next steps",
        suggested_first_steps=["draft learning_plan.md"],
    )


def _plan(tool: str, args: dict) -> dict:
    """A scripted PLAN entry returning a well-formed action."""
    return {
        "tag": "plan",
        "text": json.dumps({"thought": "do it", "action": {"tool": tool, "args": args}}),
    }


def _check(done: bool, reason: str = "") -> dict:
    """A scripted CHECK entry."""
    return {"tag": "check", "text": json.dumps({"done": done, "reason": reason})}


def _tools(tmp_path: Path) -> ToolRegistry:
    return ToolRegistry(
        workspace_root=tmp_path / "workspace",
        artifacts_dir=tmp_path / "artifacts",
    )


def _no_sleep(_: float) -> None:
    """Sleep spy that never waits -- keeps every loop test wall-clock-free."""


def _fast_retry_settings(**overrides) -> Settings:
    """Settings whose retry policy has deterministic, zero-jitter backoff (the
    injected ``sleep`` never really waits anyway, but a fixed sequence keeps the
    tests reasoning about counts, not timing)."""
    return Settings(
        retry=RetryPolicy(
            max_attempts=5, base_backoff_sec=1.0, backoff_factor=2.0, jitter_frac=0.0
        ),
        **overrides,
    )


def _run(argv: list[str], capsys) -> tuple[int, str, str]:
    """Invoke the CLI and return (rc, stdout, stderr), draining capsys first so
    prior setup output never leaks into the assertion window."""
    capsys.readouterr()
    rc = main(argv)
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def _reported_retries(text: str) -> int:
    """Extract the single integer reported by a `retries ...` line. Fails the
    calling test (not this helper) if the line is absent -- callers assert on
    the returned value."""
    m = _RETRIES.search(text)
    assert m is not None, f"expected a 'retries <int>' line; got:\n{text}"
    return int(m.group(1))


def _throttle_run_script(tmp_path: Path, *, throttles: int = 1) -> Path:
    """Build a `pla run` scripted-responses file: the demo's 4-goal synthesize
    response, then N throttled PLAN entries, then a real PLAN + a done CHECK.
    The synthesizer retry site is unhooked (out of scope), so only the executor
    PLAN throttles are counted -- the reported run retries must equal ``throttles``."""
    demo = json.loads(SCRIPT.read_text())
    synth = demo["responses"][0]  # the 4-goal synthesize response (auto goal = learning)
    responses = [synth]
    responses += [{"tag": "plan", "raise": "throttle"} for _ in range(throttles)]
    responses.append(_plan("write_file", {"path": "learning_plan.md", "content": "x"}))
    responses.append(_check(True, "complete"))
    path = tmp_path / "throttle_run_script.json"
    path.write_text(json.dumps({"responses": responses}))
    return path


# ===========================================================================
# Behavior 1 -- RunState exposes a `retries` field defaulting to 0
# ===========================================================================


def test_behavior1_runstate_retries_defaults_to_zero():
    state = RunState(goal=_goal())
    assert hasattr(state, "retries"), "RunState must expose a `retries` field"
    assert state.retries == 0, f"a fresh RunState must have retries == 0; got {state.retries!r}"
    assert isinstance(state.retries, int) and not isinstance(state.retries, bool), (
        f"retries must be a plain int; got {type(state.retries)}"
    )
    assert state.retries >= 0, "retries is a non-negative counter"
    # It also round-trips through the model dump (so it can be persisted).
    dumped = json.loads(state.model_dump_json())
    assert dumped.get("retries") == 0, f"retries must serialize; got {dumped.get('retries')!r}"


# ===========================================================================
# Behavior 2 -- a pre-iter-08 checkpoint (no `retries` key) loads as 0
# ===========================================================================


def test_behavior2_missing_retries_key_deserializes_as_zero():
    # Produce a valid *pre-iter-08* dump: dump a RunState, drop the retries key.
    base = RunState(goal=_goal(), status=RunStatus.DONE, iterations_used=2, llm_calls_used=4)
    as_dict = json.loads(base.model_dump_json())
    assert "retries" in as_dict, "precondition: a current dump contains retries"
    del as_dict["retries"]
    legacy_json = json.dumps(as_dict)

    # from_json must not raise, and must default the missing counter to 0.
    restored = RunState.from_json(legacy_json)
    assert restored.retries == 0, (
        f"a checkpoint written without `retries` must load as retries == 0; got {restored.retries!r}"
    )
    # The rest of the state still round-tripped (proves it is not a fresh object).
    assert restored.status is RunStatus.DONE
    assert restored.iterations_used == 2
    assert restored.goal.title == base.goal.title


def test_behavior2_minimal_handwritten_runstate_json_loads():
    """A minimal hand-written RunState JSON with no `retries` key also loads."""
    minimal = json.dumps({
        "goal": json.loads(_goal().model_dump_json()),
    })
    restored = RunState.from_json(minimal)
    assert restored.retries == 0


# ===========================================================================
# Behavior 3 -- a run that recovers from transient errors records the count
# ===========================================================================


def test_behavior3_throttle_recovery_counts_each_backoff_retry(tmp_path):
    tools = _tools(tmp_path)
    # Two throttles on the FIRST plan, then a valid plan + done check.
    client = ScriptedLLMClient([
        {"tag": "plan", "raise": "throttle"},
        {"tag": "plan", "raise": "throttle"},
        _plan("write_file", {"path": "out.md", "content": "done"}),
        _check(True, "complete"),
    ])
    sleeps: list[float] = []
    loop = GoalLoop(client, _fast_retry_settings(), tools, sleep=sleeps.append)

    state = loop.run(_goal())

    assert state.status is RunStatus.DONE, f"run must reach DONE; got {state.status}"
    assert state.retries == 2, (
        f"two recovered backoff-retries must count as retries == 2; got {state.retries}"
    )
    # Sanity that the two increments coincided with two real backoff waits.
    assert sleeps == [1.0, 2.0], f"expected two backoff sleeps; got {sleeps}"


def test_behavior3_timeout_recovery_counts_identically(tmp_path):
    """`timeout` is in the same retryable set as `throttle` and counts the same."""
    tools = _tools(tmp_path)
    client = ScriptedLLMClient([
        {"tag": "plan", "raise": "timeout"},
        {"tag": "plan", "raise": "timeout"},
        _plan("write_file", {"path": "out.md", "content": "done"}),
        _check(True, "complete"),
    ])
    loop = GoalLoop(client, _fast_retry_settings(), tools, sleep=_no_sleep)

    state = loop.run(_goal())

    assert state.status is RunStatus.DONE
    assert state.retries == 2, f"two timeout recoveries must count as 2; got {state.retries}"


# ===========================================================================
# Behavior 4 -- a clean run leaves retries == 0
# ===========================================================================


def test_behavior4_clean_run_leaves_retries_zero(tmp_path):
    tools = _tools(tmp_path)
    client = ScriptedLLMClient([
        _plan("write_file", {"path": "out.md", "content": "done"}),
        _check(True, "complete"),
    ])
    loop = GoalLoop(client, _fast_retry_settings(), tools, sleep=_no_sleep)

    state = loop.run(_goal())

    assert state.status is RunStatus.DONE
    assert state.retries == 0, f"a throttle-free run must leave retries == 0; got {state.retries}"


# ===========================================================================
# Behavior 5 -- retries persist across checkpoint round-trip and accumulate
#               across resume (never reset)
# ===========================================================================


def test_behavior5_retries_persist_and_accumulate_across_resume(tmp_path):
    ckpt_path = tmp_path / "runs" / _CHECKPOINT_NAME
    checkpoint = Checkpoint(ckpt_path)
    workspace = tmp_path / "workspace"
    artifacts = tmp_path / "artifacts"

    # Phase 1: one throttle then a plan, CHECK not done, budget=1 => stops with
    # retries == 1, checkpointed.
    tools1 = ToolRegistry(workspace_root=workspace, artifacts_dir=artifacts)
    client1 = ScriptedLLMClient([
        {"tag": "plan", "raise": "throttle"},
        _plan("write_file", {"path": "a.md", "content": "phase1"}),
        _check(False, "need another pass"),
    ])
    loop1 = GoalLoop(client1, _fast_retry_settings(max_iterations=1), tools1, checkpoint, sleep=_no_sleep)
    state1 = loop1.run(_goal())

    assert state1.retries == 1, f"phase 1 should record one retry; got {state1.retries}"
    assert ckpt_path.is_file(), "phase 1 must have checkpointed the run"

    # The retry count is physically present in the persisted checkpoint JSON.
    on_disk = json.loads(ckpt_path.read_text())
    assert "retries" in on_disk, "persisted checkpoint.json must carry the retries key"
    assert on_disk["retries"] == 1, f"persisted retries must equal 1; got {on_disk['retries']}"

    # A public Checkpoint.load() round-trip preserves it.
    loaded = checkpoint.load()
    assert loaded is not None
    assert loaded.retries == 1, f"loaded state must preserve retries == 1; got {loaded.retries}"

    # Phase 2: resume with another throttle then finish. retries must ACCUMULATE
    # (1 carried + 1 new = 2), never reset to 0.
    tools2 = ToolRegistry(workspace_root=workspace, artifacts_dir=artifacts)
    client2 = ScriptedLLMClient([
        {"tag": "plan", "raise": "throttle"},
        _plan("write_file", {"path": "b.md", "content": "phase2 final"}),
        _check(True, "finished"),
    ])
    loop2 = GoalLoop(client2, _fast_retry_settings(max_iterations=5), tools2, checkpoint, sleep=_no_sleep)
    # Capture the count BEFORE resume: the executor resumes on (and mutates) the
    # loaded state object in place, so `loaded.retries` itself advances too.
    retries_before_resume = loaded.retries
    resumed = loop2.run(_goal(), resume=loaded)

    assert resumed.status is RunStatus.DONE
    assert resumed.retries == 2, (
        f"resume must carry the prior count forward and only add: expected 2, got {resumed.retries}"
    )
    assert resumed.retries > retries_before_resume, (
        "resume must never reset the retry count to 0 -- it only accumulates"
    )

    # And the final on-disk checkpoint reflects the accumulated total.
    final = checkpoint.load()
    assert final is not None and final.retries == 2


# ===========================================================================
# Behavior 6 -- retry counting covers CHECK calls too (not just PLAN)
# ===========================================================================


def test_behavior6_throttle_on_check_also_increments_retries(tmp_path):
    tools = _tools(tmp_path)
    # A clean PLAN, then the CHECK throttles once before returning done=True.
    client = ScriptedLLMClient([
        _plan("write_file", {"path": "out.md", "content": "done"}),
        {"tag": "check", "raise": "throttle"},
        _check(True, "complete"),
    ])
    sleeps: list[float] = []
    loop = GoalLoop(client, _fast_retry_settings(), tools, sleep=sleeps.append)

    state = loop.run(_goal())

    assert state.status is RunStatus.DONE
    assert state.retries == 1, (
        f"a recovered throttle on the CHECK call must also count; got retries == {state.retries}"
    )
    assert sleeps == [1.0], f"the CHECK retry should have produced one backoff wait; got {sleeps}"


# ===========================================================================
# Behavior 7 -- dispatch / run / resume run-summary reports the retry count
# ===========================================================================


def test_behavior7_run_summary_reports_zero_for_clean_demo(tmp_path, capsys):
    """The offline scripted demo scripts no throttles -> summary reports 0, exit 0."""
    state_dir = tmp_path / "state"
    rc, out, err = _run([
        "run",
        "--workspace", str(FIXTURE),
        "--provider", "scripted",
        "--scripted-responses", str(SCRIPT),
        "--state-dir", str(state_dir),
    ], capsys)

    assert rc == 0, f"clean demo run must exit 0, got {rc}; stderr:\n{err}"
    assert _reported_retries(out) == 0, "the throttle-free demo run must report retries 0"


def test_behavior7_run_summary_reports_retries_after_throttle(tmp_path, capsys, monkeypatch):
    """A `pla run` driven with a throttle entry + near-zero backoff env reports >=1."""
    # Both are valid (ge=0.0) and make with_retry never actually sleep.
    monkeypatch.setenv("PLA_RETRY_BASE_BACKOFF_SEC", "0")
    monkeypatch.setenv("PLA_RETRY_JITTER_FRAC", "0")
    script = _throttle_run_script(tmp_path, throttles=1)
    state_dir = tmp_path / "state"

    rc, out, err = _run([
        "run",
        "--workspace", str(FIXTURE),
        "--provider", "scripted",
        "--scripted-responses", str(script),
        "--state-dir", str(state_dir),
    ], capsys)

    assert rc == 0, f"a throttle-then-recover run must still exit 0, got {rc}; stderr:\n{err}"
    assert _reported_retries(out) >= 1, (
        f"a run that recovered from a throttle must report retries >= 1; summary:\n{out}"
    )


def test_behavior7_dispatch_summary_reports_retries_after_throttle(tmp_path, capsys, monkeypatch):
    """`pla dispatch` (which routes through the same summary) also reports retries."""
    monkeypatch.setenv("PLA_RETRY_BASE_BACKOFF_SEC", "0")
    monkeypatch.setenv("PLA_RETRY_JITTER_FRAC", "0")

    # 1) scan to produce a slate (consumes the synthesize response only).
    slate_path = tmp_path / "slate.json"
    rc_scan, _, _ = _run([
        "scan",
        "--workspace", str(FIXTURE),
        "--provider", "scripted",
        "--scripted-responses", str(SCRIPT),
        "--state-dir", str(tmp_path / "scan_state"),
        "--out", str(slate_path),
    ], capsys)
    assert rc_scan == 0

    # Locate the AUTO_DISPATCH goal (dispatchable without --yes) via the public gate.
    slate = GoalSlate.model_validate_json(slate_path.read_text())
    auto = next(
        g for g in slate.goals
        if next(d for d in gate_slate(slate, Settings()) if d.goal_id == g.id).decision
        is AutonomyDecision.AUTO_DISPATCH
    )

    # 2) dispatch that goal with a throttle-then-recover plan/check script.
    dispatch_script = tmp_path / "dispatch_script.json"
    dispatch_script.write_text(json.dumps({"responses": [
        {"tag": "plan", "raise": "throttle"},
        _plan("write_file", {"path": "out.md", "content": "done"}),
        _check(True, "complete"),
    ]}))

    rc, out, err = _run([
        "dispatch",
        "--slate", str(slate_path),
        "--goal-id", auto.id,
        "--provider", "scripted",
        "--scripted-responses", str(dispatch_script),
        "--state-dir", str(tmp_path / "d_state"),
    ], capsys)

    assert rc == 0, f"dispatch of the AUTO goal must exit 0, got {rc}; stderr:\n{err}"
    assert _reported_retries(out) >= 1, f"dispatch summary must report retries >= 1; got:\n{out}"


def test_behavior7_resume_summary_reports_carried_retries(tmp_path, capsys):
    """`pla resume` reports the retry count, carrying the prior value forward."""
    run_dir = tmp_path / "state" / "run-resume-me"
    artifacts = run_dir / "artifacts"
    artifacts.mkdir(parents=True)

    # A stopped run that already recorded 2 retries.
    stopped = RunState(
        goal=_goal("Finish the scaffold"),
        status=RunStatus.BUDGET_EXHAUSTED,
        iterations_used=1,
        llm_calls_used=2,
        retries=2,
        artifacts_dir=str(artifacts),
    )
    Checkpoint(run_dir / _CHECKPOINT_NAME).save(stopped)
    (run_dir / "meta.json").write_text(json.dumps(
        {"workspace_root": str(FIXTURE), "artifacts_dir": str(artifacts)}
    ))

    # A clean finishing script (adds no further retries).
    script = tmp_path / "resume_script.json"
    script.write_text(json.dumps({"responses": [
        _plan("write_file", {"path": "scaffold.md", "content": "done"}),
        _check(True, "complete"),
    ]}))

    rc, out, err = _run([
        "resume",
        "--run-dir", str(run_dir),
        "--provider", "scripted",
        "--scripted-responses", str(script),
        "--state-dir", str(tmp_path / "state"),
    ], capsys)

    assert rc == 0, f"resume must exit 0, got {rc}; stderr:\n{err}"
    # Clean resume adds nothing, so the carried-forward count (2) is reported.
    assert _reported_retries(out) == 2, (
        f"resume must report the carried-forward retry count (2); got:\n{out}"
    )


# ===========================================================================
# Behavior 8 -- pla trace human header reports the retry count
# ===========================================================================


def _persist_run(
    run_dir: Path,
    *,
    retries: int,
    steps: list[LoopStep] | None = None,
    status: RunStatus = RunStatus.DONE,
    iterations_used: int = 2,
    llm_calls_used: int = 4,
) -> RunState:
    """Persist a RunState (with a known retry count) via the public Checkpoint,
    exactly the setup path iter-07's Tester note prescribes."""
    run_dir.mkdir(parents=True, exist_ok=True)
    state = RunState(
        goal=_goal("Inspect the retriever pipeline"),
        status=status,
        steps=steps if steps is not None else [
            LoopStep(index=0, kind=StepKind.PLAN, output="thought: locate module"),
            LoopStep(index=1, kind=StepKind.ACT, output="list_files -> a.py", artifacts=[]),
            LoopStep(index=2, kind=StepKind.CHECK, output="reason: complete", done=True),
        ],
        iterations_used=iterations_used,
        llm_calls_used=llm_calls_used,
        retries=retries,
        artifacts_dir=str(run_dir / "artifacts"),
    )
    Checkpoint(run_dir / _CHECKPOINT_NAME).save(state)
    return state


def test_behavior8_trace_header_reports_retries(tmp_path, capsys):
    run_dir = tmp_path / "run-trace"
    _persist_run(run_dir, retries=3)

    rc, out, err = _run(["trace", "--run-dir", str(run_dir)], capsys)
    assert rc == 0, f"trace must exit 0, got {rc}; stderr:\n{err}"

    # The retry count must appear in a HEADER line, not in a per-step line.
    header = "\n".join(ln for ln in out.splitlines() if not _STEP_LINE.match(ln))
    assert _reported_retries(header) == 3, (
        f"trace header must report the run's retry count (3); header:\n{header}"
    )
    # And no existing header token was removed or reworded (iter-07 contract).
    for token in ("steps", "iterations", "llm"):
        assert token in header, f"trace header must still contain the {token!r} count; got:\n{header}"


def test_behavior8_empty_steps_header_still_reports_retries(tmp_path, capsys):
    run_dir = tmp_path / "run-empty"
    _persist_run(run_dir, retries=5, steps=[], iterations_used=0, llm_calls_used=0)

    rc, out, err = _run(["trace", "--run-dir", str(run_dir)], capsys)
    assert rc == 0, f"empty-steps trace must exit 0, got {rc}"

    # Full header still renders (incl. retries) followed by the degrade line.
    assert _reported_retries(out) == 5, f"empty-steps header must still report retries; got:\n{out}"
    assert "no steps recorded" in out, f"empty steps must degrade legibly; got:\n{out}"


# ===========================================================================
# Behavior 9 -- pla trace --json step-array schema is UNCHANGED (no `retries`)
# ===========================================================================


def test_behavior9_trace_json_step_schema_unchanged(tmp_path, capsys):
    run_dir = tmp_path / "run-json"
    _persist_run(run_dir, retries=7)  # a nonzero run-level retry count...
    # Re-load from disk so expectations couple to the persisted state.
    state = Checkpoint(run_dir / _CHECKPOINT_NAME).load()
    assert state is not None and state.steps

    rc, out, err = _run(["trace", "--run-dir", str(run_dir), "--json"], capsys)
    assert rc == 0, f"trace --json must exit 0, got {rc}; stderr:\n{err}"

    parsed = json.loads(out)  # the ENTIRE stdout must be one JSON array
    assert isinstance(parsed, list)
    assert len(parsed) == len(state.steps)

    exact_keys = {"index", "kind", "output", "done", "artifacts"}
    for elem in parsed:
        assert set(elem.keys()) == exact_keys, (
            f"each step object must keep EXACTLY {exact_keys} (iter-07 contract); got {set(elem.keys())}"
        )
        # ...which must NOT leak into per-step objects (retries is run-level).
        assert "retries" not in elem, "retries must never appear in a trace --json step object"


def test_behavior9_trace_json_empty_is_bare_empty_array(tmp_path, capsys):
    """An empty-steps run's --json is still exactly '[]' (no run-level retries leak)."""
    run_dir = tmp_path / "run-empty-json"
    _persist_run(run_dir, retries=9, steps=[], iterations_used=0, llm_calls_used=0)

    rc, out, err = _run(["trace", "--run-dir", str(run_dir), "--json"], capsys)
    assert rc == 0
    assert out.strip() == "[]", f"empty --json must emit ONLY '[]'; got:\n{out!r}"
