"""Black-box behavior tests for iteration 69 --- ``RunState`` gains a persisted,
non-negative ``parse_errors`` counter (default ``0``) that the L1 executor's
fail-safe increments once per ABSORBED malformed PLAN or CHECK, and which the
``pla dispatch`` / ``pla run`` run summary and the ``pla trace`` human header
report INLINE beside the existing ``retries`` count.

Feature under test (SPEC 4.4 + the RunState/render contract): iter-68 shipped the
*live* half of the parse-error observability story (a ``L1 degraded `` WARNING the
executor emits in real time when its fail-safe absorbs a malformed PLAN/CHECK).
That signal is un-auditable after the fact -- a finished ``BUDGET_EXHAUSTED``
checkpoint records ``retries`` (throttle pressure) yet says nothing about how many
iterations the model burned emitting garbage. This iteration closes that gap with
exact symmetry to the retries story: a persisted counter (``RunState.parse_errors``)
+ the already-shipped live log (iter-68 ``L1 degraded `` WARNING). The counter is
keyed on the parse-failure flag, NEVER on the ``done`` value, so an honest
well-formed ``done: false`` verdict is not a degradation. It is a defaulted-additive
field + two increments + two human-render tweaks: no schema change to the JSON
outputs, no new CLI verb/flag, no version bump.

ISOLATION CONTRACT (honored): these tests are written strictly against THIS
iteration's public contract --- the spec's "Expected Behaviors" (``pm.md``),
``README.md``, and ``SPEC.md`` --- and drive ONLY the documented public surface:
``proactive_loop.models.RunState``, the public
``proactive_loop.loop.executor.GoalLoop.run(...)`` seam through the scripted
provider (``ScriptedLLMClient``) with an injected no-op ``sleep`` (exactly as
``tests/test_iter68_behavior.py`` and ``tests/test_iter08_behavior.py`` drive it),
and the ``pla`` CLI via ``proactive_loop.cli.main([...])``. **No file under
``src/`` was read, no engineer/reviewer notes were read, and no ``git diff`` was
consulted** to author the assertions --- field/method names come from the public
model schema, ``SPEC.md``, and the two published reference behavior suites. Every
test is fully offline: zero network, zero API keys; the ``parse_errors`` values
asserted are DERIVED from the number of malformed replies the test itself scripts,
never hard-coded against implementation quirks. Workspaces/artifacts are synthetic
``tmp_path`` (never the repo's ``.pla_runs/``).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from proactive_loop import __version__
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
# A per-step transcript line in the human `trace` ("[<int>] kind ...").
_STEP_LINE = re.compile(r"^\s*\[\d+\]")
# Tolerant readers for the two inline counts. The `parse errors` label token is
# distinct from `retries`, so the two never cross-capture; never pinned to exact
# spacing (Expected Behaviors 9/10 fix the label token, not the column width).
_RETRIES = re.compile(r"retries\s*[:=]?\s*(\d+)", re.IGNORECASE)
_PARSE_ERRORS = re.compile(r"parse errors\s*[:=]?\s*(\d+)", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Helpers (same scripted seam tests/test_iter68_behavior.py + test_iter08 use)
# ---------------------------------------------------------------------------


def _goal(title: str = "Write a learning plan") -> CandidateGoal:
    return CandidateGoal(
        title=title,
        rationale="capture next steps",
        suggested_first_steps=["draft learning_plan.md"],
    )


def _tools(tmp_path: Path) -> ToolRegistry:
    return ToolRegistry(
        workspace_root=tmp_path / "workspace",
        artifacts_dir=tmp_path / "artifacts",
    )


def _plan(tool: str, args: dict) -> dict:
    """A scripted PLAN entry returning a well-formed action."""
    return {
        "tag": "plan",
        "text": json.dumps({"thought": "do it", "action": {"tool": tool, "args": args}}),
    }


def _bad_plan(text: str = "not json at all <<<") -> dict:
    """A scripted PLAN reply that is NOT parseable as the required PLAN JSON."""
    return {"tag": "plan", "text": text}


def _check(done: bool, reason: str = "") -> dict:
    """A scripted, well-formed CHECK entry (`{"done": bool, "reason": str}`)."""
    return {"tag": "check", "text": json.dumps({"done": done, "reason": reason})}


def _bad_check(text: str) -> dict:
    """A scripted CHECK reply that is NOT parseable as the required CHECK object
    (plain prose, or valid JSON that is not an object)."""
    return {"tag": "check", "text": text}


def _no_sleep(_: float) -> None:
    """Injected sleep spy that never waits --- keeps every path wait-free."""


def _run(argv: list[str], capsys) -> tuple[int, str, str]:
    """Invoke the CLI and return (rc, stdout, stderr), draining capsys first so
    prior setup output never leaks into the assertion window."""
    capsys.readouterr()
    rc = main(argv)
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def _reported_retries(text: str) -> int:
    m = _RETRIES.search(text)
    assert m is not None, f"expected a 'retries <int>' report; got:\n{text}"
    return int(m.group(1))


def _reported_parse_errors(text: str) -> int:
    m = _PARSE_ERRORS.search(text)
    assert m is not None, f"expected a 'parse errors: <int>' report; got:\n{text}"
    return int(m.group(1))


def _parse_error_run_script(tmp_path: Path, *, bad_plans: int = 1) -> Path:
    """Build a `pla run` scripted-responses file: the demo's synthesize response
    (auto-selects the learning goal), then N unparseable PLANs, then a real PLAN
    + a done CHECK. Only the executor loop's absorbed parse failures are counted,
    so the reported run parse-errors must equal ``bad_plans``."""
    demo = json.loads(SCRIPT.read_text())
    synth = demo["responses"][0]  # the 4-goal synthesize response (auto goal = learning)
    responses = [synth]
    responses += [_bad_plan(f"garbage plan {i} <<<") for i in range(bad_plans)]
    responses.append(_plan("write_file", {"path": "learning_plan.md", "content": "x"}))
    responses.append(_check(True, "complete"))
    path = tmp_path / "parse_error_run_script.json"
    path.write_text(json.dumps({"responses": responses}))
    return path


def _persist_run(
    run_dir: Path,
    *,
    parse_errors: int,
    retries: int = 0,
    steps: list[LoopStep] | None = None,
    status: RunStatus = RunStatus.DONE,
    iterations_used: int = 2,
    llm_calls_used: int = 4,
) -> RunState:
    """Persist a RunState (with a known parse_errors count) via the public
    Checkpoint --- the same setup path the iter-08 trace tests use."""
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
        parse_errors=parse_errors,
        artifacts_dir=str(run_dir / "artifacts"),
    )
    Checkpoint(run_dir / _CHECKPOINT_NAME).save(state)
    return state


# ===========================================================================
# Expected Behavior 1 -- field exists and defaults to 0 (real int, >= 0)
# ===========================================================================


def test_eb1_parse_errors_defaults_to_zero_and_is_a_plain_int():
    state = RunState(goal=_goal())
    assert hasattr(state, "parse_errors"), "RunState must expose a `parse_errors` field"
    assert state.parse_errors == 0, (
        f"a fresh RunState must have parse_errors == 0; got {state.parse_errors!r}"
    )
    assert isinstance(state.parse_errors, int) and not isinstance(state.parse_errors, bool), (
        f"parse_errors must be a plain int (not a bool); got {type(state.parse_errors)}"
    )
    assert state.parse_errors >= 0, "parse_errors is a non-negative counter"


# ===========================================================================
# Expected Behavior 2 -- the field serializes (to_json / model_dump)
# ===========================================================================


def test_eb2_parse_errors_serializes_with_the_state():
    state = RunState(goal=_goal())
    # model_dump() carries it as an int 0.
    dumped = state.model_dump()
    assert dumped.get("parse_errors") == 0, (
        f"model_dump() must contain parse_errors == 0; got {dumped.get('parse_errors')!r}"
    )
    # to_json() (the persisted checkpoint form) carries the key too.
    from_json = json.loads(state.to_json())
    assert from_json.get("parse_errors") == 0, (
        f"to_json() must contain parse_errors == 0; got {from_json.get('parse_errors')!r}"
    )


# ===========================================================================
# Expected Behavior 3 -- backward-compatible deserialization (non-breaking)
# ===========================================================================


def test_eb3_missing_parse_errors_key_deserializes_as_zero():
    """A pre-iter-69 checkpoint (no `parse_errors` key) loads as 0 and raises
    nothing --- built by dumping a state then deleting the key (mirrors the
    iter-08 retries backward-compat test)."""
    base = RunState(
        goal=_goal(), status=RunStatus.DONE, iterations_used=2, llm_calls_used=4, retries=1
    )
    as_dict = json.loads(base.to_json())
    assert "parse_errors" in as_dict, "precondition: a current dump contains parse_errors"
    del as_dict["parse_errors"]
    legacy_json = json.dumps(as_dict)

    restored = RunState.from_json(legacy_json)  # must not raise
    assert restored.parse_errors == 0, (
        f"a checkpoint lacking `parse_errors` must load as 0; got {restored.parse_errors!r}"
    )
    # The rest of the state still round-tripped (proves it is not a fresh object).
    assert restored.status is RunStatus.DONE
    assert restored.iterations_used == 2
    assert restored.retries == 1
    assert restored.goal.title == base.goal.title


def test_eb3_minimal_handwritten_runstate_json_loads_as_zero():
    minimal = json.dumps({"goal": json.loads(_goal().model_dump_json())})
    restored = RunState.from_json(minimal)
    assert restored.parse_errors == 0


# ===========================================================================
# Expected Behavior 4 -- a malformed PLAN increments the counter
# ===========================================================================


def test_eb4_single_malformed_plan_increments_by_one(tmp_path):
    tools = _tools(tmp_path)
    client = ScriptedLLMClient(
        [
            _bad_plan(),                                             # iter 1 (no CHECK)
            _plan("write_file", {"path": "x.md", "content": "hi"}),   # iter 2
            _check(True, "done"),
        ]
    )
    loop = GoalLoop(client, Settings(max_iterations=5), tools, sleep=_no_sleep)

    state = loop.run(_goal())

    assert state.status is RunStatus.DONE
    assert state.parse_errors == 1, (
        f"one absorbed malformed PLAN must leave parse_errors == 1; got {state.parse_errors}"
    )
    assert state.retries == 0, "no throttles => the retries counter is untouched"


def test_eb4_k_malformed_plans_increment_by_k(tmp_path):
    """The counter equals the number of malformed-PLAN iterations."""
    tools = _tools(tmp_path)
    client = ScriptedLLMClient(
        [
            _bad_plan("not json at all <<<"),                        # iter 1
            _bad_plan(json.dumps({"thought": "oops", "no_action": 1})),  # iter 2 (valid JSON, no action)
            _bad_plan("still <<< broken"),                           # iter 3
            _plan("write_file", {"path": "done.md", "content": "ok"}),  # iter 4
            _check(True, "complete"),
        ]
    )
    loop = GoalLoop(client, Settings(max_iterations=8), tools, sleep=_no_sleep)

    state = loop.run(_goal())

    assert state.status is RunStatus.DONE
    assert state.parse_errors == 3, (
        f"three absorbed malformed PLANs must leave parse_errors == 3; got {state.parse_errors}"
    )


# ===========================================================================
# Expected Behavior 5 -- a malformed CHECK increments the counter
# ===========================================================================


def test_eb5_each_malformed_check_increments_by_one(tmp_path):
    """`k` unparseable CHECKs (prose in one iter, valid-JSON-non-object in the
    next) each add exactly 1; the budget-exhausted run ends with parse_errors == k.
    Covers the spec's 'valid JSON that is not an object' case explicitly."""
    tools = _tools(tmp_path)
    client = ScriptedLLMClient(
        [
            _plan("write_file", {"path": "a.md", "content": "1"}),
            _bad_check("prose, no json here"),      # CHECK iter 1 (prose)
            _plan("write_file", {"path": "b.md", "content": "2"}),
            _bad_check("[1, 2, 3]"),                 # CHECK iter 2 (JSON, not an object)
        ]
    )
    loop = GoalLoop(client, Settings(max_iterations=2), tools, sleep=_no_sleep)

    state = loop.run(_goal())

    assert state.status is RunStatus.BUDGET_EXHAUSTED
    assert state.parse_errors == 2, (
        f"two absorbed malformed CHECKs must leave parse_errors == 2; got {state.parse_errors}"
    )
    assert state.retries == 0


def test_eb5_mixed_bad_plans_and_bad_checks_sum(tmp_path):
    """A run mixing `j` bad PLANs and `k` bad CHECKs ends with parse_errors == j + k."""
    tools = _tools(tmp_path)
    client = ScriptedLLMClient(
        [
            _bad_plan("garbage <<<"),                                # iter 1: bad PLAN (j=1)
            _plan("write_file", {"path": "a.md", "content": "1"}),    # iter 2: good PLAN...
            _bad_check("we are basically done, i think"),             # ...bad CHECK (k=1)
            _plan("write_file", {"path": "b.md", "content": "2"}),    # iter 3: good PLAN...
            _bad_check("{not-json"),                                  # ...bad CHECK (k=2)
            _plan("write_file", {"path": "c.md", "content": "3"}),    # iter 4: good PLAN...
            _check(True, "done"),                                    # ...done CHECK
        ]
    )
    loop = GoalLoop(client, Settings(max_iterations=8), tools, sleep=_no_sleep)

    state = loop.run(_goal())

    assert state.status is RunStatus.DONE
    assert state.parse_errors == 3, (
        f"j=1 bad PLAN + k=2 bad CHECKs must sum to parse_errors == 3; got {state.parse_errors}"
    )


# ===========================================================================
# Expected Behavior 6 -- a well-formed `done: false` verdict is NOT counted
# ===========================================================================


def test_eb6_wellformed_done_false_is_never_counted(tmp_path):
    """The load-bearing distinction: several honest ``{"done": false}`` verdicts
    followed by a final ``{"done": true}`` leave parse_errors == 0. The counter
    is keyed on the parse-failure flag, never on the `done` value."""
    tools = _tools(tmp_path)
    client = ScriptedLLMClient(
        [
            _plan("write_file", {"path": "a.md", "content": "1"}),
            _check(False, "needs another pass"),
            _plan("write_file", {"path": "b.md", "content": "2"}),
            _check(False, "still needs another pass"),
            _plan("write_file", {"path": "c.md", "content": "3"}),
            _check(True, "now complete"),
        ]
    )
    loop = GoalLoop(client, Settings(max_iterations=5), tools, sleep=_no_sleep)

    state = loop.run(_goal())

    assert state.status is RunStatus.DONE
    assert state.parse_errors == 0, (
        "well-formed done:false verdicts must NEVER be counted as parse errors; "
        f"got parse_errors == {state.parse_errors}"
    )


def test_eb6_budget_exhausted_on_honest_not_done_still_zero(tmp_path):
    """A run that exhausts its budget on honest ``done: false`` verdicts (no parse
    failure at all) still ends with parse_errors == 0."""
    tools = _tools(tmp_path)
    client = ScriptedLLMClient(
        [
            _plan("write_file", {"path": "a.md", "content": "1"}),
            _check(False, "needs another pass"),
            _plan("write_file", {"path": "b.md", "content": "2"}),
            _check(False, "still needs another pass"),
        ]
    )
    loop = GoalLoop(client, Settings(max_iterations=2), tools, sleep=_no_sleep)

    state = loop.run(_goal())

    assert state.status is RunStatus.BUDGET_EXHAUSTED
    assert state.iterations_used == 2
    assert state.parse_errors == 0


# ===========================================================================
# Expected Behavior 7 -- a fully clean run reports 0 (state + persisted checkpoint)
# ===========================================================================


def test_eb7_clean_run_leaves_zero_and_checkpoint_records_zero(tmp_path):
    ckpt_path = tmp_path / "runs" / _CHECKPOINT_NAME
    checkpoint = Checkpoint(ckpt_path)
    tools = _tools(tmp_path)
    client = ScriptedLLMClient(
        [
            _plan("write_file", {"path": "clean.md", "content": "hi"}),
            _check(True, "artifact present"),
        ]
    )
    loop = GoalLoop(client, Settings(), tools, checkpoint, sleep=_no_sleep)

    state = loop.run(_goal())

    assert state.status is RunStatus.DONE
    assert state.parse_errors == 0
    # The persisted checkpoint carries the key with value 0.
    assert ckpt_path.is_file()
    on_disk = json.loads(ckpt_path.read_text())
    assert "parse_errors" in on_disk, "persisted checkpoint.json must carry the parse_errors key"
    assert on_disk["parse_errors"] == 0, (
        f"a clean run's persisted checkpoint must record parse_errors == 0; got {on_disk['parse_errors']}"
    )


# ===========================================================================
# Expected Behavior 8 -- the counter persists and is monotonic across resume
# ===========================================================================


def test_eb8_parse_errors_accumulate_across_resume_never_reset(tmp_path):
    ckpt_path = tmp_path / "runs" / _CHECKPOINT_NAME
    checkpoint = Checkpoint(ckpt_path)
    workspace = tmp_path / "workspace"
    artifacts = tmp_path / "artifacts"

    # A stopped run that already absorbed 5 parse failures, persisted via the
    # public Checkpoint.
    stopped = RunState(
        goal=_goal("Finish the scaffold"),
        status=RunStatus.BUDGET_EXHAUSTED,
        iterations_used=0,
        llm_calls_used=0,
        parse_errors=5,
        artifacts_dir=str(artifacts),
    )
    checkpoint.save(stopped)

    loaded = checkpoint.load()
    assert loaded is not None
    assert loaded.parse_errors == 5, (
        f"loaded checkpoint must preserve parse_errors == 5; got {loaded.parse_errors}"
    )
    parse_errors_before_resume = loaded.parse_errors

    # Resume: one further bad parse => 6 (the counter carries forward and only
    # adds; it never resets to 0 on resume).
    tools = ToolRegistry(workspace_root=workspace, artifacts_dir=artifacts)
    client = ScriptedLLMClient(
        [
            _bad_plan("garbage on resume <<<"),
            _plan("write_file", {"path": "scaffold.md", "content": "done"}),
            _check(True, "finished"),
        ]
    )
    loop = GoalLoop(client, Settings(max_iterations=5), tools, checkpoint, sleep=_no_sleep)
    resumed = loop.run(_goal("Finish the scaffold"), resume=loaded)

    assert resumed.status is RunStatus.DONE
    assert resumed.parse_errors == 6, (
        f"resume must carry the prior count forward and only add: expected 6, got {resumed.parse_errors}"
    )
    assert resumed.parse_errors > parse_errors_before_resume, (
        "resume must never reset the parse-errors count -- it only accumulates"
    )
    # The final on-disk checkpoint reflects the accumulated total.
    final = checkpoint.load()
    assert final is not None and final.parse_errors == 6


# ===========================================================================
# Expected Behavior 9 -- run summary reports it inline beside `retries` (CLI)
# ===========================================================================


def test_eb9_run_summary_reports_zero_for_clean_demo(tmp_path, capsys):
    """The offline scripted demo scripts no parse failures -> the summary's
    retries line ALSO reports `parse errors: 0`, exit 0."""
    state_dir = tmp_path / "state"
    rc, out, err = _run([
        "run",
        "--workspace", str(FIXTURE),
        "--provider", "scripted",
        "--scripted-responses", str(SCRIPT),
        "--state-dir", str(state_dir),
    ], capsys)

    assert rc == 0, f"clean demo run must exit 0, got {rc}; stderr:\n{err}"
    assert _reported_parse_errors(out) == 0, "the clean demo run must report parse errors 0"
    # The pre-existing retries report on the same line is unchanged (still 0).
    assert _reported_retries(out) == 0, "the clean demo run's retries report must stay 0"


def test_eb9_run_summary_reports_parse_errors_after_bad_plans(tmp_path, capsys):
    """A `pla run` whose script absorbs 2 malformed PLANs reports `parse errors: 2`
    inline, while the retries report stays 0 (no throttles)."""
    script = _parse_error_run_script(tmp_path, bad_plans=2)
    state_dir = tmp_path / "state"

    rc, out, err = _run([
        "run",
        "--workspace", str(FIXTURE),
        "--provider", "scripted",
        "--scripted-responses", str(script),
        "--state-dir", str(state_dir),
    ], capsys)

    assert rc == 0, f"a bad-plan-then-recover run must still exit 0, got {rc}; stderr:\n{err}"
    assert _reported_parse_errors(out) == 2, (
        f"a run that absorbed 2 malformed PLANs must report parse errors 2; summary:\n{out}"
    )
    assert _reported_retries(out) == 0, "parse errors and retries are independent; retries stays 0"


def test_eb9_dispatch_summary_reports_parse_errors_inline(tmp_path, capsys):
    """`pla dispatch` (same summary path) reports the parse-error count on the
    SAME line as retries, in the form `retries    : {R}    parse errors: {P}`."""
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

    # 2) dispatch that goal with a one-bad-plan-then-recover script.
    dispatch_script = tmp_path / "dispatch_script.json"
    dispatch_script.write_text(json.dumps({"responses": [
        _bad_plan("dispatch garbage <<<"),
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
    assert _reported_parse_errors(out) == 1, f"dispatch summary must report parse errors 1; got:\n{out}"
    # Both counts live on ONE line with the retries token first, then parse errors.
    summary_line = next(
        (ln for ln in out.splitlines() if "parse errors" in ln), ""
    )
    assert "retries" in summary_line, (
        f"parse errors must render on the SAME line as retries; got line:\n{summary_line!r}"
    )
    assert summary_line.index("retries") < summary_line.index("parse errors"), (
        "the `retries` token must precede `parse errors` on the shared line"
    )


# ===========================================================================
# Expected Behavior 10 -- trace header reports it inline beside `retries` (CLI)
# ===========================================================================


def test_eb10_trace_header_reports_parse_errors_inline(tmp_path, capsys):
    run_dir = tmp_path / "run-trace"
    _persist_run(run_dir, parse_errors=4, retries=3)

    rc, out, err = _run(["trace", "--run-dir", str(run_dir)], capsys)
    assert rc == 0, f"trace must exit 0, got {rc}; stderr:\n{err}"

    # The parse-error count must appear in a HEADER line, not in a per-step line.
    header = "\n".join(ln for ln in out.splitlines() if not _STEP_LINE.match(ln))
    assert _reported_parse_errors(header) == 4, (
        f"trace header must report the run's parse-error count (4); header:\n{header}"
    )
    # The pre-existing steps/iterations/llm/retries portion is unchanged.
    assert _reported_retries(header) == 3, "the header's retries count must still be reported (3)"
    for token in ("steps", "iterations", "llm"):
        assert token in header, f"trace header must still contain the {token!r} count; got:\n{header}"
    # retries and parse errors share the stat line, retries first.
    stat_line = next((ln for ln in header.splitlines() if "parse errors" in ln), "")
    assert "retries" in stat_line and stat_line.index("retries") < stat_line.index("parse errors"), (
        f"trace stat line must end `... retries: {{R}}    parse errors: {{P}}`; got:\n{stat_line!r}"
    )


def test_eb10_empty_steps_header_still_reports_parse_errors(tmp_path, capsys):
    run_dir = tmp_path / "run-empty"
    _persist_run(run_dir, parse_errors=6, retries=1, steps=[], iterations_used=0, llm_calls_used=0)

    rc, out, err = _run(["trace", "--run-dir", str(run_dir)], capsys)
    assert rc == 0, f"empty-steps trace must exit 0, got {rc}"

    assert _reported_parse_errors(out) == 6, f"empty-steps header must still report parse errors; got:\n{out}"
    assert "no steps recorded" in out, f"empty steps must degrade legibly; got:\n{out}"


# ===========================================================================
# Expected Behavior 11 -- JSON outputs are UNCHANGED (scope guard)
# ===========================================================================


def test_eb11_trace_json_step_schema_gains_no_parse_errors(tmp_path, capsys):
    run_dir = tmp_path / "run-json"
    _persist_run(run_dir, parse_errors=7, retries=2)  # nonzero run-level counts...
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
            f"each step object must keep EXACTLY {exact_keys}; got {set(elem.keys())}"
        )
        assert "parse_errors" not in elem, "parse_errors must never leak into a trace --json step object"


def test_eb11_runs_json_rows_gain_retries_and_parse_errors(tmp_path, capsys):
    """`pla runs --json` rows now DO surface both persisted resilience counters.

    iter-71 lands ROADMAP #72, deliberately INVERTING this guard: iter-69 pinned
    ``parse_errors not in row`` here purely as an explicit "JSON exposure deferred
    to #72" placeholder. Now that #72 has shipped, the row must carry the two
    counters with their real values (a sanctioned reversal of a self-imposed
    scope marker, NOT a broken public contract --- the runs --json row contract
    tolerates added keys). The sibling ``trace --json`` guard above stays
    UNCHANGED (that scope boundary holds --- counters never enter the bare step
    array)."""
    state_dir = tmp_path / "state"
    # Two persisted runs under the state dir, one with nonzero counters.
    _persist_run(state_dir / "run-alpha", parse_errors=3, retries=1)
    _persist_run(state_dir / "run-beta", parse_errors=0, retries=0)

    rc, out, err = _run(["runs", "--state-dir", str(state_dir), "--json"], capsys)
    assert rc == 0, f"runs --json must exit 0, got {rc}; stderr:\n{err}"

    rows = json.loads(out)  # the ENTIRE stdout must parse as one JSON array
    assert isinstance(rows, list) and len(rows) == 2
    for row in rows:
        assert "retries" in row and "parse_errors" in row, (
            "runs --json rows must now surface both resilience counters; "
            f"got keys {set(row.keys())}"
        )
    by_id = {row["run_id"]: row for row in rows}
    assert by_id["run-alpha"]["retries"] == 1
    assert by_id["run-alpha"]["parse_errors"] == 3
    assert by_id["run-beta"]["retries"] == 0
    assert by_id["run-beta"]["parse_errors"] == 0


# ===========================================================================
# Expected Behavior 12 -- no version bump
# ===========================================================================


def test_eb12_version_is_not_bumped():
    assert __version__ == "0.1.1", (
        f"a defaulted-additive field + human-render-only change must NOT bump the version; got {__version__!r}"
    )


def test_eb12_cli_version_still_reports_0_1_1(capsys):
    """`pla --version` still prints `pla 0.1.1` (argparse short-circuits with a
    clean SystemExit(0))."""
    capsys.readouterr()
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "0.1.1" in out, f"`pla --version` must report 0.1.1; got:\n{out!r}"
