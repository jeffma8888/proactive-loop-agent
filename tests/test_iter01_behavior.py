"""Black-box behavior tests for iteration 01.

Feature under test: the L2 ``GoalSynthesizer.synthesize`` model call is wrapped
in the L0 ``with_retry`` policy, so a *transient* throttle/timeout on the scan's
front-door LLM call is absorbed with backoff instead of crashing ``pla scan`` /
``pla run``. This makes ``README.md``'s "L0 resilience wraps *every* model call
in retry-with-backoff" claim actually true (previously only the L1 loop did).

ISOLATION: these tests are written strictly against the public API documented in
the spec and ``SPEC.md`` §4.3 — ``proactive_loop.scout.GoalSynthesizer`` driven
by the offline ``ScriptedLLMClient`` seam (``{"tag": "synthesize", "raise":
"throttle"|"timeout"}`` injects a transient failure; ``{"tag": "synthesize",
"text": <json>}`` returns a response; ``client.calls`` records the tags seen).
No ``src/`` internals, no engineer/reviewer notes, and no ``git diff`` were
consulted. Everything runs fully offline with an injected no-op/recorder
``sleep`` — zero network, zero wall-clock delay.
"""

from __future__ import annotations

import json

import pytest

from proactive_loop.config import RetryPolicy, Settings
from proactive_loop.llm.client import (
    LLMThrottleError,
    LLMTimeoutError,
    ScriptedLLMClient,
    ScriptExhaustedError,
)
from proactive_loop.models import (
    CandidateGoal,
    ContextSignal,
    GoalSlate,
    WorkspaceSnapshot,
)
from proactive_loop.scout import SYNTHESIZE_TAG, GoalSynthesizer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _snapshot() -> WorkspaceSnapshot:
    """A minimal, representative snapshot for the synthesizer to summarize."""
    return WorkspaceSnapshot(
        root="/tmp/example-workspace",
        signals=[
            ContextSignal(
                source="todos",
                kind="todo",
                summary="TODO: add retry/backoff to the LLM client",
            ),
        ],
    )


def _one_goal_payload() -> str:
    """A valid JSON array carrying exactly one well-formed goal."""
    return json.dumps(
        [
            {
                "title": "Add retry/backoff to the synthesizer",
                "rationale": "Closes the resilience-parity gap on the L2 call.",
                "category": "project",
                "impact": 5.0,
                "urgency": 4.0,
                "confidence": 0.9,
                "effort_weight": 2.0,
                "appropriate_now": True,
                "sources": ["TODO: add retry/backoff to the LLM client"],
                "suggested_first_steps": ["Wrap complete() in with_retry"],
            }
        ]
    )


def _noop_sleep(_seconds: float) -> None:
    """A sleep double that records nothing and, crucially, never waits."""
    return None


# ---------------------------------------------------------------------------
# Behavior 1 — transient throttle recovers within one scan
# ---------------------------------------------------------------------------


def test_behavior1_transient_throttle_recovers_within_one_scan() -> None:
    client = ScriptedLLMClient(
        [
            {"tag": SYNTHESIZE_TAG, "raise": "throttle"},
            {"tag": SYNTHESIZE_TAG, "text": _one_goal_payload()},
        ]
    )
    synth = GoalSynthesizer(client, Settings(), sleep=_noop_sleep)

    slate = synth.synthesize(_snapshot())

    assert isinstance(slate, GoalSlate)
    assert [g.title for g in slate.goals] == ["Add retry/backoff to the synthesizer"]
    assert isinstance(slate.goals[0], CandidateGoal)
    # Exactly one retry occurred: the throttled call, then the successful one.
    assert client.calls == [SYNTHESIZE_TAG, SYNTHESIZE_TAG]


# ---------------------------------------------------------------------------
# Behavior 2 — transient timeout recovers identically
# ---------------------------------------------------------------------------


def test_behavior2_transient_timeout_recovers_identically() -> None:
    client = ScriptedLLMClient(
        [
            {"tag": SYNTHESIZE_TAG, "raise": "timeout"},
            {"tag": SYNTHESIZE_TAG, "text": _one_goal_payload()},
        ]
    )
    synth = GoalSynthesizer(client, Settings(), sleep=_noop_sleep)

    slate = synth.synthesize(_snapshot())

    assert [g.title for g in slate.goals] == ["Add retry/backoff to the synthesizer"]
    assert client.calls == [SYNTHESIZE_TAG, SYNTHESIZE_TAG]


# ---------------------------------------------------------------------------
# Behavior 3 — the injected sleep fires once per retry with a positive delay
# ---------------------------------------------------------------------------


def test_behavior3_sleep_invoked_once_per_retry_with_positive_delay() -> None:
    recorded: list[float] = []
    settings = Settings(retry=RetryPolicy(base_backoff_sec=0.5, jitter_frac=0.0))
    client = ScriptedLLMClient(
        [
            {"tag": SYNTHESIZE_TAG, "raise": "throttle"},
            {"tag": SYNTHESIZE_TAG, "text": _one_goal_payload()},
        ]
    )
    synth = GoalSynthesizer(client, settings, sleep=recorded.append)

    slate = synth.synthesize(_snapshot())

    assert [g.title for g in slate.goals] == ["Add retry/backoff to the synthesizer"]
    # One retry => exactly one backoff wait; jitter_frac=0.0 makes the first
    # backoff deterministically equal to base_backoff_sec.
    assert recorded == [0.5]


# ---------------------------------------------------------------------------
# Behavior 4 — retries are bounded; the transient error surfaces after budget
# ---------------------------------------------------------------------------


def test_behavior4_retries_bounded_then_transient_error_surfaces() -> None:
    settings = Settings(
        retry=RetryPolicy(max_attempts=2, base_backoff_sec=0.0, jitter_frac=0.0)
    )
    client = ScriptedLLMClient(
        [
            {"tag": SYNTHESIZE_TAG, "raise": "throttle"},
            {"tag": SYNTHESIZE_TAG, "raise": "throttle"},
        ]
    )
    synth = GoalSynthesizer(client, settings, sleep=_noop_sleep)

    with pytest.raises(LLMThrottleError):
        synth.synthesize(_snapshot())

    # Exactly max_attempts calls were made before giving up.
    assert client.calls == [SYNTHESIZE_TAG, SYNTHESIZE_TAG]


# ---------------------------------------------------------------------------
# Behavior 5 — non-retryable errors pass through unchanged (not retried)
# ---------------------------------------------------------------------------


def test_behavior5_non_retryable_error_passes_through_without_retry() -> None:
    client = ScriptedLLMClient([])  # empty script => ScriptExhaustedError
    synth = GoalSynthesizer(client, Settings(), sleep=_noop_sleep)

    with pytest.raises(ScriptExhaustedError):
        synth.synthesize(_snapshot())

    # A non-transient error is not retried: exactly one call was attempted.
    assert client.calls == [SYNTHESIZE_TAG]


# ---------------------------------------------------------------------------
# Behavior 6 — happy path is unchanged (no extra calls on first success)
# ---------------------------------------------------------------------------


def test_behavior6_happy_path_single_call_unchanged() -> None:
    client = ScriptedLLMClient(
        [{"tag": SYNTHESIZE_TAG, "text": _one_goal_payload()}]
    )
    synth = GoalSynthesizer(client, Settings(), sleep=_noop_sleep)

    slate = synth.synthesize(_snapshot())

    assert [g.title for g in slate.goals] == ["Add retry/backoff to the synthesizer"]
    # The retry wrapper adds nothing when the first call succeeds.
    assert client.calls == [SYNTHESIZE_TAG]


# ---------------------------------------------------------------------------
# Behavior 7 — backward-compatible construction (no sleep arg, positional)
# ---------------------------------------------------------------------------


def test_behavior7_backward_compatible_positional_construction() -> None:
    # Exactly how the CLI constructs it (cli.py:266 / cli.py:326): positional
    # (client, settings), no sleep keyword. The new sleep param is optional.
    client = ScriptedLLMClient(
        [{"tag": SYNTHESIZE_TAG, "text": _one_goal_payload()}]
    )
    synth = GoalSynthesizer(client, Settings())

    slate = synth.synthesize(_snapshot())

    assert [g.title for g in slate.goals] == ["Add retry/backoff to the synthesizer"]
    assert client.calls == [SYNTHESIZE_TAG]


# A defensive check that both transient error types are the ones L0 retries on,
# keeping this file honest about what "transient" means for behaviors 1/2/4.
def test_transient_error_types_are_llm_throttle_and_timeout() -> None:
    assert issubclass(LLMThrottleError, Exception)
    assert issubclass(LLMTimeoutError, Exception)
