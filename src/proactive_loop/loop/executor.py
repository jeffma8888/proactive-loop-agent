"""L1 goal loop: the resilient PLAN -> ACT -> CHECK executor.

WHY this shape: an agent that must run unattended needs (a) a bounded loop so it
can never spin forever, (b) every model call wrapped in retry/backoff so a
throttle blip doesn't kill the run, and (c) a checkpoint after *every* step so a
crash loses at most the in-flight step. This module wires those three together;
the model itself only ever sees the PLAN and CHECK prompts.
"""

from __future__ import annotations

import logging
import time
from typing import Callable

from proactive_loop.config import Settings
from proactive_loop.llm.client import LLMClient, parse_json_block
from proactive_loop.loop.resilience import Checkpoint, with_retry
from proactive_loop.loop.tools import ToolRegistry
from proactive_loop.models import (
    CandidateGoal,
    LoopStep,
    RunState,
    RunStatus,
    StepKind,
)

# Observation text substituted when the model's JSON cannot be parsed. WHY feed
# it back instead of failing: a malformed turn is recoverable -- the model sees
# its own mistake on the next prompt and can correct it.
_PLAN_PARSE_ERROR = (
    "error: your last PLAN was not valid JSON. Reply with exactly "
    '{"thought": "...", "action": {"tool": "...", "args": {...}}}'
)
_CHECK_PARSE_ERROR = (
    "error: your last CHECK was not valid JSON; treating the goal as not done"
)

# Module logger (name resolves to "proactive_loop.loop.executor"). WHY only
# obtain a logger, never configure it: this layer just EMITS the L0 self-healing
# record; whether it reaches stderr is the CLI -v/-vv decision (or pytest caplog).
_LOG = logging.getLogger(__name__)


class GoalLoop:
    """Drive a :class:`CandidateGoal` through iterations of PLAN, ACT, CHECK.

    Every LLM call is retried via :func:`with_retry`; every step is appended to
    a :class:`RunState` that is checkpointed immediately, so the run is both
    throttle-resilient and resumable. *sleep* is injectable purely so tests can
    assert backoff timing without waiting on the wall clock.
    """

    PLAN_TAG: str = "plan"
    CHECK_TAG: str = "check"

    _SYSTEM = (
        "You are a focused execution agent. Work toward the goal one step at a "
        "time using the available tools, and stop as soon as it is satisfied."
    )

    def __init__(
        self,
        client: LLMClient,
        settings: Settings,
        tools: ToolRegistry,
        checkpoint: Checkpoint | None = None,
        *,
        sleep: Callable[[float], object] = time.sleep,
    ) -> None:
        self._client = client
        self._settings = settings
        self._tools = tools
        self._checkpoint = checkpoint
        # Injected into with_retry so tests can assert backoff without waiting.
        self._sleep = sleep

    def run(self, goal: CandidateGoal, *, resume: RunState | None = None) -> RunState:
        """Execute *goal* to DONE or budget exhaustion; return the final state.

        Pass *resume* to continue a previously checkpointed run: its iteration
        count, step history, and artifacts carry over untouched.
        """
        state = self._init_state(goal, resume)

        while not self._budget_exhausted(state):
            plan_raw = self._llm(self.PLAN_TAG, self._plan_prompt(state), state)
            self._record(state, StepKind.PLAN, plan_raw)

            action = self._parse_action(plan_raw)
            if action is None:
                # No executable action: record the parse error as this
                # iteration's observation, count the iteration, try again.
                self._record(state, StepKind.ACT, _PLAN_PARSE_ERROR)
                state.iterations_used += 1
                self._save(state)
                continue

            observation = self._tools.execute(action["tool"], action["args"])
            self._record(
                state, StepKind.ACT, observation, artifacts=self._tools.artifacts()
            )

            check_raw = self._llm(
                self.CHECK_TAG, self._check_prompt(state, observation), state
            )
            done, reason = self._parse_check(check_raw)
            self._record(state, StepKind.CHECK, reason, done=done)

            state.iterations_used += 1
            self._save(state)

            if done:
                state.status = RunStatus.DONE
                self._save(state)
                return state

        state.status = RunStatus.BUDGET_EXHAUSTED
        self._save(state)
        return state

    # --- lifecycle helpers ----------------------------------------------

    def _init_state(self, goal: CandidateGoal, resume: RunState | None) -> RunState:
        """Start a fresh run or adopt a resumed one, marking it RUNNING."""
        state = resume if resume is not None else RunState(
            goal=goal, artifacts_dir=str(self._tools.artifacts_dir)
        )
        state.status = RunStatus.RUNNING
        self._save(state)
        return state

    def _budget_exhausted(self, state: RunState) -> bool:
        """True once the iteration cap or the LLM-call cap is reached."""
        return (
            state.iterations_used >= self._settings.max_iterations
            or state.llm_calls_used >= self._settings.max_llm_calls
        )

    def _llm(self, tag: str, prompt: str, state: RunState) -> str:
        """Make one retried model call for *tag* and count it against budget."""

        def _call() -> str:
            return self._client.complete(
                system=self._SYSTEM, prompt=prompt, tag=tag
            ).text

        def _count_retry(attempt: int, delay: float, exc: Exception) -> None:
            # Record each recovered backoff-retry on the run so the L0
            # self-healing is observable rather than silently absorbed. This
            # runs for EVERY LLM call the executor makes -- PLAN and CHECK
            # alike, since both route through this one method -- so the counter
            # covers the whole run, not just planning.
            state.retries += 1
            # Emit the SAME event as a live INFO record so the headline "resilient
            # by design" story is visible DURING the run (the checkpoint counter
            # only surfaces it after). Emitted UNCONDITIONALLY at the source: the
            # -v/-vv flag decides whether a handler forwards it to stderr, but the
            # record exists regardless, so caplog can capture it with no CLI. The
            # 1-based *attempt* is the just-failed try that is being retried.
            _LOG.info(
                "L0 retry %d for %s (backing off %.2fs): %s",
                attempt,
                tag,
                delay,
                exc,
            )

        text = with_retry(
            _call, self._settings.retry, sleep=self._sleep, on_retry=_count_retry
        )
        state.llm_calls_used += 1
        return text

    def _record(
        self,
        state: RunState,
        kind: StepKind,
        output: str,
        *,
        done: bool = False,
        artifacts: list[str] | None = None,
    ) -> None:
        """Append one step and checkpoint immediately (crash-loses-at-most-one)."""
        state.steps.append(
            LoopStep(
                index=state.next_step_index(),
                kind=kind,
                output=output,
                done=done,
                artifacts=list(artifacts or []),
            )
        )
        self._save(state)

    def _save(self, state: RunState) -> None:
        """Persist the current state if a checkpoint sink is configured."""
        if self._checkpoint is not None:
            self._checkpoint.save(state)

    # --- parsing --------------------------------------------------------

    @staticmethod
    def _parse_action(plan_raw: str) -> dict | None:
        """Extract ``{"tool", "args"}`` from a PLAN reply, or None if malformed."""
        try:
            data = parse_json_block(plan_raw)
        except ValueError:
            return None
        if not isinstance(data, dict):
            return None
        action = data.get("action")
        if not isinstance(action, dict):
            return None
        tool = action.get("tool")
        if not isinstance(tool, str) or not tool:
            return None
        args = action.get("args", {})
        return {"tool": tool, "args": args if isinstance(args, dict) else {}}

    @staticmethod
    def _parse_check(check_raw: str) -> tuple[bool, str]:
        """Extract ``(done, reason)`` from a CHECK reply.

        An unparseable CHECK is deliberately read as *not done* with an error
        reason, so a garbled verdict never falsely completes the run.
        """
        try:
            data = parse_json_block(check_raw)
        except ValueError:
            return False, _CHECK_PARSE_ERROR
        if not isinstance(data, dict):
            return False, _CHECK_PARSE_ERROR
        return bool(data.get("done", False)), str(data.get("reason", ""))

    # --- prompt rendering -----------------------------------------------

    def _plan_prompt(self, state: RunState) -> str:
        """Build the PLAN prompt: goal, tools, and the recent transcript."""
        goal = state.goal
        first_steps = "; ".join(goal.suggested_first_steps) or "(none)"
        return (
            f"GOAL: {goal.title}\n"
            f"WHY: {goal.rationale}\n"
            f"SUGGESTED FIRST STEPS: {first_steps}\n\n"
            "TOOLS: write_file(path, content) [writes under artifacts/], "
            "append_file(path, content) [appends under artifacts/], "
            "read_file(path), list_files(path), search_files(query, path), "
            "find_files(pattern, path) [glob file discovery by name], "
            "stat_file(path) [describe one path: type/bytes/lines/ext], "
            "head_file(path, max_lines) [first N lines of a file; N default 40], "
            "remove_file(path) [deletes a file under artifacts/], "
            "move_file(src, dst) [rename/relocate a file under artifacts/]\n\n"
            f"{self._transcript(state)}\n"
            'Reply with JSON: {"thought": "...", '
            '"action": {"tool": "...", "args": {...}}}'
        )

    def _check_prompt(self, state: RunState, observation: str) -> str:
        """Build the CHECK prompt: goal plus the latest tool observation."""
        return (
            f"GOAL: {state.goal.title}\n"
            f"LATEST OBSERVATION:\n{observation}\n\n"
            'Is the goal complete? Reply with JSON: '
            '{"done": true|false, "reason": "..."}'
        )

    @staticmethod
    def _transcript(state: RunState, limit: int = 6) -> str:
        """Render the last few steps so the model sees recent progress/errors."""
        recent = state.steps[-limit:]
        if not recent:
            return "TRANSCRIPT: (empty)\n"
        lines = [f"- {s.kind.value}: {s.output[:200]}" for s in recent]
        return "TRANSCRIPT (recent steps):\n" + "\n".join(lines) + "\n"
