"""Black-box behavior tests for iteration 68 --- the L1 executor emits a live
``WARNING`` (message prefix ``L1 degraded ``) on its module logger whenever the
loop's fail-safe ABSORBS a malformed (unparseable) PLAN or CHECK.

Feature under test (SPEC 4.4): the crown-jewel fail-safe that swallows model
misbehaviour used to be silent --- an unparseable PLAN (recorded as the
``_PLAN_PARSE_ERROR`` observation) or an unparseable CHECK (read as not-done)
was absorbed, counted, and the loop continued with NO live log record, so a run
degrading to ``BUDGET_EXHAUSTED`` because the model emits garbage looked
identical to a run legitimately running out of budget. This iteration closes
that operability gap --- the degradation twin of the iter-25 ``L0 retry `` INFO
record --- by emitting exactly one ``WARNING`` per absorbed parse failure on the
executor's module logger ``proactive_loop.loop.executor``, message prefix
``L1 degraded `` carrying the 1-based iteration index. It is an
observability-only, behaviour-preserving add: no schema, stdout, exit-code, or
control-flow change.

ISOLATION CONTRACT (honored): these tests are written strictly against THIS
iteration's public contract --- the spec's "Expected Behaviors" (``pm.md``),
``README.md``, and ``SPEC.md`` section 4.4 --- and drive ONLY the documented
public ``proactive_loop.loop.executor.GoalLoop`` API through the scripted
provider seam (``ScriptedLLMClient``) with an injected no-op ``sleep``, observing
records via the standard-library logging capture on the executor's module logger
exactly as the iter-25 behavior tests do. **No file under ``src/`` was read, no
engineer/reviewer notes were read, and no ``git diff`` was consulted.** Every
test is fully offline: zero network, zero API keys; workspaces/artifacts are
synthetic ``tmp_path``.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import pytest

from proactive_loop import __version__
from proactive_loop.config import RetryPolicy, Settings
from proactive_loop.llm.client import ScriptedLLMClient
from proactive_loop.loop.executor import GoalLoop
from proactive_loop.loop.tools import ToolRegistry
from proactive_loop.models import CandidateGoal, RunStatus, StepKind

_EXEC_LOGGER = "proactive_loop.loop.executor"
_DEGRADED_PREFIX = "L1 degraded "
_L0_RETRY_PREFIX = "L0 retry "


# ---------------------------------------------------------------------------
# Helpers (same scripted seam the iter-25 suite + tests/test_loop.py use)
# ---------------------------------------------------------------------------


def _goal() -> CandidateGoal:
    return CandidateGoal(
        title="Write a learning plan",
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
    """A scripted CHECK reply that is NOT parseable as the required CHECK JSON
    (plain prose, or valid JSON that is not an object)."""
    return {"tag": "check", "text": text}


def _no_sleep(_: float) -> None:
    """Injected sleep spy that never waits --- keeps retry paths wait-free."""


def _degraded_records(caplog) -> list[logging.LogRecord]:
    """All ``L1 degraded `` WARNING records on the executor module logger."""
    return [
        r
        for r in caplog.records
        if r.name == _EXEC_LOGGER
        and r.levelno == logging.WARNING
        and r.getMessage().startswith(_DEGRADED_PREFIX)
    ]


def _l0_retry_records(caplog) -> list[logging.LogRecord]:
    """All ``L0 retry `` records (the iter-25 INFO channel) on any logger."""
    return [r for r in caplog.records if r.getMessage().startswith(_L0_RETRY_PREFIX)]


def _iteration_index(message: str) -> int:
    """Extract the 1-based iteration index carried by a degraded WARNING.

    The index is parsed from AFTER the ``L1 degraded `` prefix so the ``1`` in
    the ``L1`` prefix is never mistaken for the index (same technique the
    iter-25 suite uses to read the ``L0 retry`` attempt number)."""
    remainder = message[len(_DEGRADED_PREFIX):]
    m = re.search(r"\d+", remainder)
    assert m is not None, f"degraded WARNING must carry an iteration index; got {message!r}"
    return int(m.group())


# ===========================================================================
# Behavior 1 --- a malformed PLAN emits one degraded WARNING per bad iteration
# ===========================================================================


def test_b1_malformed_plan_emits_one_degraded_warning_per_bad_iteration(tmp_path, caplog):
    """Two consecutive unparseable PLANs, then a clean plan->check(done) run to
    completion: EXACTLY two degraded WARNINGs, carrying the token ``PLAN`` and
    the 1-based indices 1 and 2 of the iterations that degraded."""
    tools = _tools(tmp_path)
    client = ScriptedLLMClient(
        [
            _bad_plan("not json at all <<<"),                     # iter 1 (no CHECK)
            _bad_plan(json.dumps({"thought": "oops", "no_action": 1})),  # iter 2 (no CHECK)
            _plan("write_file", {"path": "done.md", "content": "ok"}),   # iter 3
            _check(True, "complete"),
        ]
    )
    loop = GoalLoop(client, Settings(max_iterations=5), tools, sleep=_no_sleep)

    caplog.set_level(logging.WARNING, logger=_EXEC_LOGGER)
    state = loop.run(_goal())

    assert state.status is RunStatus.DONE

    degraded = _degraded_records(caplog)
    assert len(degraded) == 2, (
        "two malformed-PLAN iterations must emit exactly two degraded WARNINGs; "
        f"got {len(degraded)}: {[r.getMessage() for r in degraded]}"
    )
    for r in degraded:
        assert "PLAN" in r.getMessage(), (
            f"a malformed-PLAN degraded WARNING must contain the token 'PLAN'; got {r.getMessage()!r}"
        )
    indices = sorted(_iteration_index(r.getMessage()) for r in degraded)
    assert indices == [1, 2], (
        f"degraded WARNINGs must carry the 1-based indices of the degraded iterations; got {indices}"
    )


def test_b1_single_malformed_plan_emits_exactly_one_warning(tmp_path, caplog):
    """The count of degraded WARNINGs equals the number of malformed-PLAN
    iterations --- one bad plan => exactly one WARNING (index 1)."""
    tools = _tools(tmp_path)
    client = ScriptedLLMClient(
        [
            _bad_plan(),                                            # iter 1
            _plan("write_file", {"path": "x.md", "content": "hi"}),  # iter 2
            _check(True, "done"),
        ]
    )
    loop = GoalLoop(client, Settings(max_iterations=5), tools, sleep=_no_sleep)

    caplog.set_level(logging.WARNING, logger=_EXEC_LOGGER)
    state = loop.run(_goal())

    assert state.status is RunStatus.DONE
    degraded = _degraded_records(caplog)
    assert len(degraded) == 1
    assert "PLAN" in degraded[0].getMessage()
    assert _iteration_index(degraded[0].getMessage()) == 1


# ===========================================================================
# Behavior 2 --- a malformed CHECK emits one degraded WARNING per bad iteration
# ===========================================================================


def test_b2_malformed_check_emits_one_degraded_warning_per_bad_iteration(tmp_path, caplog):
    """A valid PLAN executes (so an action runs) but the CHECK reply is not
    parseable --- prose in iter 1, valid-JSON-but-not-an-object in iter 2. The
    run exhausts its 2-iteration budget and emits EXACTLY two degraded WARNINGs
    carrying the token ``CHECK`` and the indices 1 and 2."""
    tools = _tools(tmp_path)
    client = ScriptedLLMClient(
        [
            _plan("write_file", {"path": "a.md", "content": "1"}),
            _bad_check("we are basically done here, i think"),   # prose (iter 1)
            _plan("write_file", {"path": "b.md", "content": "2"}),
            _bad_check("[1, 2, 3]"),                              # JSON, not an object (iter 2)
        ]
    )
    loop = GoalLoop(client, Settings(max_iterations=2), tools, sleep=_no_sleep)

    caplog.set_level(logging.WARNING, logger=_EXEC_LOGGER)
    state = loop.run(_goal())

    assert state.status is RunStatus.BUDGET_EXHAUSTED

    degraded = _degraded_records(caplog)
    assert len(degraded) == 2, (
        "two malformed-CHECK iterations must emit exactly two degraded WARNINGs; "
        f"got {len(degraded)}: {[r.getMessage() for r in degraded]}"
    )
    for r in degraded:
        assert "CHECK" in r.getMessage(), (
            f"a malformed-CHECK degraded WARNING must contain the token 'CHECK'; got {r.getMessage()!r}"
        )
        # It must NOT masquerade as the PLAN case.
        assert "PLAN" not in r.getMessage()
    indices = sorted(_iteration_index(r.getMessage()) for r in degraded)
    assert indices == [1, 2], (
        f"degraded WARNINGs must carry the 1-based indices of the degraded iterations; got {indices}"
    )


# ===========================================================================
# Behavior 3 --- a clean run emits ZERO degraded WARNINGs
# ===========================================================================


def test_b3_clean_run_emits_zero_degraded_warnings(tmp_path, caplog):
    """A fully valid PLAN -> ACT -> CHECK(done=true) run reaches DONE and emits
    ZERO ``L1 degraded `` records."""
    tools = _tools(tmp_path)
    client = ScriptedLLMClient(
        [
            _plan("write_file", {"path": "clean.md", "content": "hi"}),
            _check(True, "artifact present"),
        ]
    )
    loop = GoalLoop(client, Settings(), tools, sleep=_no_sleep)

    caplog.set_level(logging.WARNING, logger=_EXEC_LOGGER)
    state = loop.run(_goal())

    assert state.status is RunStatus.DONE
    assert _degraded_records(caplog) == []


# ===========================================================================
# Behavior 4 --- a legitimate not-done CHECK is NOT a degradation
# ===========================================================================


def test_b4_wellformed_done_false_is_not_a_degradation(tmp_path, caplog):
    """A run whose CHECK is well-formed JSON reporting a genuine not-yet verdict
    (`{"done": false, "reason": ...}`) that then exhausts its iteration budget
    emits ZERO ``L1 degraded `` records --- the WARNING fires ONLY on a PARSE
    failure, never on a correct ``done: false``."""
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

    caplog.set_level(logging.WARNING, logger=_EXEC_LOGGER)
    state = loop.run(_goal())

    assert state.status is RunStatus.BUDGET_EXHAUSTED
    assert state.iterations_used == 2
    assert _degraded_records(caplog) == [], (
        "a well-formed done:false verdict must never emit a degraded WARNING"
    )


# ===========================================================================
# Behavior 5 --- the L1-degraded and L0-retry channels are disjoint/independent
# ===========================================================================


def test_b5_recovered_retries_emit_l0_retry_not_l1_degraded(tmp_path, caplog):
    """A run that recovers k=2 throttle retries but has NO parse failures emits
    exactly 2 records beginning ``L0 retry `` and ZERO beginning ``L1 degraded ``;
    ``RunState.retries`` (iter-08 counter) is unchanged == 2."""
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
    loop = GoalLoop(client, settings, tools, sleep=_no_sleep)

    # INFO level so any L0-retry INFO record is captured too (proving there are
    # exactly 2 of them and zero degraded WARNINGs, not merely "not captured").
    caplog.set_level(logging.INFO, logger=_EXEC_LOGGER)
    state = loop.run(_goal())

    assert state.status is RunStatus.DONE
    assert state.retries == 2
    assert len(_l0_retry_records(caplog)) == 2
    assert _degraded_records(caplog) == []


def test_b5_parse_failures_emit_l1_degraded_not_l0_retry(tmp_path, caplog):
    """A run with m=2 malformed PLAN/CHECK iterations but NO throttles emits 2
    records beginning ``L1 degraded `` and ZERO beginning ``L0 retry ``; no
    degraded message begins with the ``L0 retry `` prefix and ``RunState.retries``
    stays 0."""
    tools = _tools(tmp_path)
    client = ScriptedLLMClient(
        [
            _bad_plan("garbage <<<"),                              # iter 1 (bad PLAN)
            _plan("write_file", {"path": "a.md", "content": "1"}),  # iter 2 PLAN ok...
            _bad_check("prose, not json"),                         # ...but bad CHECK (iter 2)
            _plan("write_file", {"path": "b.md", "content": "2"}),  # iter 3
            _check(True, "done"),
        ]
    )
    loop = GoalLoop(client, Settings(max_iterations=5), tools, sleep=_no_sleep)

    caplog.set_level(logging.INFO, logger=_EXEC_LOGGER)
    state = loop.run(_goal())

    assert state.status is RunStatus.DONE
    assert state.retries == 0
    degraded = _degraded_records(caplog)
    assert len(degraded) == 2
    for r in degraded:
        assert not r.getMessage().startswith(_L0_RETRY_PREFIX)
    assert _l0_retry_records(caplog) == []


# ===========================================================================
# Behavior 6 --- the fail-safe BEHAVIOR is preserved (observability-only add)
# ===========================================================================


def test_b6_failsafe_control_flow_is_byte_for_byte_preserved(tmp_path, caplog):
    """Regression anchor: an unparseable PLAN still records the parse-error
    observation as that iteration's ACT step, still counts the iteration, and
    still continues to DONE --- identical to the pre-existing
    ``test_unparseable_plan_is_fed_back_then_run_continues`` --- while the new
    add contributes exactly one degraded WARNING and nothing else."""
    tools = _tools(tmp_path)
    client = ScriptedLLMClient(
        [
            _bad_plan("not json at all <<<"),
            _plan("write_file", {"path": "c.md", "content": "ok"}),
            _check(True, "done now"),
        ]
    )
    loop = GoalLoop(client, Settings(max_iterations=5), tools, sleep=_no_sleep)

    caplog.set_level(logging.WARNING, logger=_EXEC_LOGGER)
    state = loop.run(_goal())

    # Control flow / state identical to before the observability add.
    assert state.status is RunStatus.DONE
    assert state.iterations_used == 2  # the bad plan counted as an iteration
    assert state.steps[0].kind is StepKind.PLAN
    assert state.steps[1].kind is StepKind.ACT
    assert state.steps[1].output.startswith("error:")
    assert (tmp_path / "artifacts" / "c.md").is_file()
    # The bad-plan iteration emits no CHECK step (the loop skips CHECK on a
    # parse failure) --- so its first two steps are exactly PLAN, ACT.
    kinds = [s.kind for s in state.steps]
    assert kinds[:2] == [StepKind.PLAN, StepKind.ACT]

    # The only observable addition: exactly one degraded WARNING for iteration 1.
    degraded = _degraded_records(caplog)
    assert len(degraded) == 1
    assert _iteration_index(degraded[0].getMessage()) == 1


def test_b6_version_is_not_bumped_observability_only():
    """The feature is behaviour-preserving --- no ``__version__`` bump."""
    assert __version__ == "0.1.1"
