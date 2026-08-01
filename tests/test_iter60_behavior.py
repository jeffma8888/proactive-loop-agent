"""Black-box behavior tests for iteration 60 --- the L2 goal synthesizer's
``on_retry`` observability hook.

Feature under test: a recovered transient throttle/timeout on the L2 scout's
own model call (the front door of ``pla scan`` / ``pla run``) now emits the SAME
live ``L0 retry`` INFO record the L1 executor already emits for recovered
PLAN/CHECK retries --- closing the observability half of the "resilience parity
with the L1 loop" promise. The record is emitted unconditionally at the source
(module logger ``proactive_loop.scout.synthesizer``), one per RECOVERED retry,
with the executor-shaped message
``L0 retry <attempt> for synthesize (backing off <delay>s): <exc>``. Retry
BEHAVIOR (attempts/backoff/which errors are retryable) is unchanged --- only its
observability. There is no ``RunState`` in the scan path, so the hook is
log-ONLY (no ``retries`` counter added to any scan output).

ISOLATION CONTRACT (honored): these tests are written strictly against THIS
iteration's public contract --- the spec's "Expected Behaviors" (``pm.md``),
``README.md``, and ``SPEC.md`` --- and drive ONLY documented public surfaces:
the ``proactive_loop.scout`` package's ``GoalSynthesizer`` /
``SYNTHESIZE_TAG``, the ``proactive_loop.llm.client.ScriptedLLMClient`` scripted
provider seam (incl. its ``{"raise": ...}`` transient-error entries) and the
public ``LLMThrottleError`` / ``LLMTimeoutError``, ``proactive_loop.config``
(``Settings`` / ``RetryPolicy``), ``proactive_loop.models``
(``WorkspaceSnapshot`` / ``ContextSignal`` / ``GoalSlate`` / ``GoalCategory``),
the ``proactive_loop.__version__`` metadata, and the public
``proactive_loop.loop.executor.GoalLoop`` (used ONLY to cross-check that the L2
record shape mirrors the L1 executor's, per the acceptance criterion). **No file
under ``src/`` was read, no engineer/reviewer notes were read, and no ``git
diff`` was consulted.** Every test is fully offline: zero network, zero API keys,
an injected no-op ``sleep`` (never a real ``time.sleep``), and pytest ``caplog``
--- the INFO record exists at the source regardless of any log handler (the
iter-25 discipline), so no CLI is required.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import pytest

from proactive_loop import __version__
from proactive_loop.config import RetryPolicy, Settings
from proactive_loop.llm.client import (
    LLMThrottleError,
    LLMTimeoutError,
    ScriptedLLMClient,
)
from proactive_loop.loop.executor import GoalLoop
from proactive_loop.loop.tools import ToolRegistry
from proactive_loop.models import (
    CandidateGoal,
    ContextSignal,
    GoalCategory,
    GoalSlate,
    RunStatus,
    WorkspaceSnapshot,
)
from proactive_loop.scout import SYNTHESIZE_TAG, GoalSynthesizer

# The logger the recovered-retry record MUST land on (the synthesizer module).
SYNTH_LOGGER = "proactive_loop.scout.synthesizer"
# The L1 executor logger --- used only for the shape-parity cross-check.
EXEC_LOGGER = "proactive_loop.loop.executor"
RETRY_PREFIX = "L0 retry "

# The documented executor-shaped record:
#   L0 retry <attempt> for <tag> (backing off <delay>s): <exc>
# with the delay formatted to exactly two decimals.
_MSG_RE = re.compile(
    r"^L0 retry (?P<attempt>\d+) for (?P<tag>\S+) "
    r"\(backing off (?P<delay>\d+\.\d{2})s\): (?P<exc>.+)$"
)


# ---------------------------------------------------------------------------
# Helpers (public surface only)
# ---------------------------------------------------------------------------


def _no_sleep(_delay: float) -> None:
    """Injected sleep spy that never waits --- keeps every retry test wait-free
    and fully offline (no real ``time.sleep``)."""


def _snapshot() -> WorkspaceSnapshot:
    """A small, representative snapshot (shape mirrors tests/test_scout.py)."""
    return WorkspaceSnapshot(
        root="/tmp/example-workspace",
        signals=[
            ContextSignal(
                source="todos",
                kind="todo",
                summary="TODO: add retry/backoff to the LLM client",
            ),
            ContextSignal(
                source="notes",
                kind="note",
                summary="journal: want to learn more about agentic loops",
            ),
        ],
    )


def _goal_dict(title: str = "Add retry/backoff to the LLM client") -> dict:
    """One well-formed goal object (the shape the synthesizer parses)."""
    return {
        "title": title,
        "rationale": "A TODO calls it out and it de-risks throttling.",
        "category": "project",
        "impact": 5.0,
        "urgency": 4.0,
        "confidence": 0.9,
        "effort_weight": 2.0,
        "appropriate_now": True,
        "sources": ["TODO: add retry/backoff to the LLM client"],
        "suggested_first_steps": ["Write with_retry() with exp backoff"],
    }


def _valid_entry(goals: list[dict] | None = None) -> dict:
    """A scripted 'valid synthesize reply': a JSON array of goal objects."""
    payload = json.dumps(goals if goals is not None else [_goal_dict()])
    return {"tag": SYNTHESIZE_TAG, "text": payload}


def _raise_entry(kind: str) -> dict:
    """A scripted entry that raises the retryable transient error ``kind``."""
    return {"tag": SYNTHESIZE_TAG, "raise": kind}


def _synthesizer(
    client: ScriptedLLMClient, settings: Settings | None = None
) -> GoalSynthesizer:
    return GoalSynthesizer(
        client=client, settings=settings or Settings(), sleep=_no_sleep
    )


def _det_settings(max_attempts: int) -> Settings:
    """Deterministic backoff (no jitter): delay = 1.0 * 2**(attempt-1) --> the
    per-retry delays are exactly 1.0s, 2.0s, ... (verified in tests/test_loop.py)."""
    return Settings(
        retry=RetryPolicy(
            max_attempts=max_attempts,
            base_backoff_sec=1.0,
            backoff_factor=2.0,
            jitter_frac=0.0,
        )
    )


def _retry_records(caplog, logger: str = SYNTH_LOGGER) -> list[logging.LogRecord]:
    """Every INFO ``L0 retry`` record on ``logger`` captured so far."""
    return [
        r
        for r in caplog.records
        if r.name == logger
        and r.levelno == logging.INFO
        and r.getMessage().startswith(RETRY_PREFIX)
    ]


def _scripted_error_text(kind: str) -> str:
    """Probe the scripted seam (public ``.complete``) for the exact ``str()`` of
    the raised transient error, so the behavior tests assert the REAL message
    rather than a hardcoded guess."""
    client = ScriptedLLMClient([_raise_entry(kind)])
    try:
        client.complete(system="s", prompt="p", tag=SYNTHESIZE_TAG)
    except (LLMThrottleError, LLMTimeoutError) as exc:
        return str(exc)
    raise AssertionError(f"scripted {kind!r} entry did not raise a transient error")


# ===========================================================================
# Behavior 1 --- a recovered throttle emits exactly one INFO record per retry
# ===========================================================================


def test_b1_recovered_throttle_emits_one_info_per_recovered_retry(caplog):
    """Throttle twice, then a valid reply: ``.synthesize()`` RETURNS a GoalSlate
    (recovery succeeds) AND produces EXACTLY 2 INFO ``L0 retry`` records on the
    synthesizer logger --- one per recovered retry."""
    client = ScriptedLLMClient(
        [_raise_entry("throttle"), _raise_entry("throttle"), _valid_entry()]
    )
    synth = _synthesizer(client, _det_settings(max_attempts=5))

    caplog.set_level(logging.INFO, logger=SYNTH_LOGGER)
    slate = synth.synthesize(_snapshot())

    assert isinstance(slate, GoalSlate)  # recovery succeeded
    assert [g.title for g in slate.goals] == ["Add retry/backoff to the LLM client"]

    records = _retry_records(caplog)
    assert len(records) == 2, (
        "throttle-twice-then-succeed must emit exactly 2 'L0 retry' INFO "
        f"records; got {len(records)}: {[r.getMessage() for r in records]}"
    )


# ===========================================================================
# Behavior 2 --- each record matches the L1 executor's message shape
# ===========================================================================


def test_b2_records_match_executor_message_shape(caplog):
    """The two records, in order, carry the 1-based just-failed attempt numbers
    1 then 2, name the tag ``synthesize``, carry a two-decimal ``(backing off
    <delay>s):`` fragment, and include the retried exception's text --- i.e. the
    same %-format the executor's ``_count_retry`` uses."""
    exc_text = _scripted_error_text("throttle")

    client = ScriptedLLMClient(
        [_raise_entry("throttle"), _raise_entry("throttle"), _valid_entry()]
    )
    synth = _synthesizer(client, _det_settings(max_attempts=5))

    caplog.set_level(logging.INFO, logger=SYNTH_LOGGER)
    synth.synthesize(_snapshot())

    records = _retry_records(caplog)
    assert len(records) == 2, [r.getMessage() for r in records]

    expected_attempts = ["1", "2"]
    expected_delays = ["1.00", "2.00"]  # deterministic: 1.0 * 2**(n-1), no jitter
    for record, want_attempt, want_delay in zip(
        records, expected_attempts, expected_delays
    ):
        msg = record.getMessage()
        m = _MSG_RE.match(msg)
        assert m is not None, (
            f"record must follow 'L0 retry <attempt> for <tag> (backing off "
            f"<delay>s): <exc>'; got {msg!r}"
        )
        assert m.group("attempt") == want_attempt, (
            f"1-based just-failed attempt number must be {want_attempt}; got {msg!r}"
        )
        assert m.group("tag") == "synthesize", (
            f"the tag must be SYNTHESIZE_TAG ('synthesize'); got {msg!r}"
        )
        assert m.group("delay") == want_delay, (
            f"backoff delay must be {want_delay} (two decimals, deterministic "
            f"no-jitter backoff); got {msg!r}"
        )
        # The retried exception's text is carried verbatim.
        assert exc_text in msg, f"record must include the exception text {exc_text!r}; got {msg!r}"
        assert exc_text == m.group("exc")

    # Redundant human-readable spot checks on the literal prefixes the spec names.
    assert records[0].getMessage().startswith("L0 retry 1 for synthesize ")
    assert records[1].getMessage().startswith("L0 retry 2 for synthesize ")
    for record in records:
        assert "for synthesize " in record.getMessage()


def test_b2_shape_is_uniform_with_the_l1_executor(caplog, tmp_path):
    """Acceptance cross-check: the L2 synthesizer record and the L1 executor
    record are byte-identical after swapping the tag word, so a "grep the logs
    for ``L0 retry``" story stays uniform across L1 and L2. Drives only the
    public ``GoalLoop`` / ``GoalSynthesizer`` APIs."""
    # --- L1 executor: throttle the PLAN once, then succeed. -----------------
    tools = ToolRegistry(
        workspace_root=tmp_path / "workspace", artifacts_dir=tmp_path / "artifacts"
    )
    exec_client = ScriptedLLMClient(
        [
            {"tag": "plan", "raise": "throttle"},
            {
                "tag": "plan",
                "text": json.dumps(
                    {
                        "thought": "do it",
                        "action": {
                            "tool": "write_file",
                            "args": {"path": "out.md", "content": "done"},
                        },
                    }
                ),
            },
            {"tag": "check", "text": json.dumps({"done": True, "reason": "complete"})},
        ]
    )
    loop = GoalLoop(exec_client, _det_settings(max_attempts=5), tools, sleep=_no_sleep)

    caplog.set_level(logging.INFO, logger="proactive_loop")
    state = loop.run(
        CandidateGoal(title="Write a learning plan", rationale="capture next steps")
    )
    assert state.status is RunStatus.DONE
    exec_records = _retry_records(caplog, EXEC_LOGGER)
    assert len(exec_records) == 1, [r.getMessage() for r in exec_records]
    exec_msg = exec_records[0].getMessage()

    caplog.clear()

    # --- L2 synthesizer: throttle the synthesize call once, then succeed. ---
    synth_client = ScriptedLLMClient([_raise_entry("throttle"), _valid_entry()])
    synth = _synthesizer(synth_client, _det_settings(max_attempts=5))
    synth.synthesize(_snapshot())
    synth_records = _retry_records(caplog, SYNTH_LOGGER)
    assert len(synth_records) == 1, [r.getMessage() for r in synth_records]
    synth_msg = synth_records[0].getMessage()

    # Both parse under the SAME template; canonicalize by blanking the only two
    # legitimately-varying fields (the tag word, and the exception text --- which
    # the scripted provider happens to embed the tag in). If the records share a
    # shape, the canonical forms are byte-identical, proving a uniform
    # 'grep for L0 retry' story across L1 and L2.
    def _canonical(msg: str) -> str:
        m = _MSG_RE.match(msg)
        assert m is not None, msg
        return (
            f"L0 retry {m.group('attempt')} for <TAG> "
            f"(backing off {m.group('delay')}s): <EXC>"
        )

    assert _canonical(exec_msg) == _canonical(synth_msg)
    assert _canonical(exec_msg) == "L0 retry 1 for <TAG> (backing off 1.00s): <EXC>"


# ===========================================================================
# Behavior 3 --- timeouts route through the same hook, identically
# ===========================================================================


def test_b3_timeout_routes_through_the_same_hook(caplog):
    """A recovered TIMEOUT emits exactly 1 ``L0 retry`` INFO record on the
    synthesizer logger, attempt 1, tag ``synthesize`` --- both retryable kinds
    (throttle and timeout) are logged the same way."""
    exc_text = _scripted_error_text("timeout")

    client = ScriptedLLMClient([_raise_entry("timeout"), _valid_entry()])
    synth = _synthesizer(client, _det_settings(max_attempts=2))

    caplog.set_level(logging.INFO, logger=SYNTH_LOGGER)
    slate = synth.synthesize(_snapshot())

    assert isinstance(slate, GoalSlate)
    assert [g.title for g in slate.goals] == ["Add retry/backoff to the LLM client"]

    records = _retry_records(caplog)
    assert len(records) == 1, (
        "timeout-once-then-succeed must emit exactly 1 'L0 retry' record; got "
        f"{len(records)}: {[r.getMessage() for r in records]}"
    )
    msg = records[0].getMessage()
    m = _MSG_RE.match(msg)
    assert m is not None, msg
    assert m.group("attempt") == "1"
    assert m.group("tag") == "synthesize"
    assert "for synthesize " in msg
    assert exc_text in msg


# ===========================================================================
# Behavior 4 --- silent on the happy path (nothing to heal -> no output)
# ===========================================================================


def test_b4_happy_path_emits_zero_retry_records(caplog):
    """A first-entry-valid script recovers nothing, so ``.synthesize()`` RETURNS
    the slate AND produces ZERO ``L0 retry`` records on the synthesizer logger."""
    client = ScriptedLLMClient([_valid_entry()])
    synth = _synthesizer(client)  # default Settings

    caplog.set_level(logging.INFO, logger=SYNTH_LOGGER)
    slate = synth.synthesize(_snapshot())

    assert isinstance(slate, GoalSlate)
    assert [g.title for g in slate.goals] == ["Add retry/backoff to the LLM client"]
    assert _retry_records(caplog) == []


# ===========================================================================
# Behavior 5 --- the budget-exhausting final attempt is NOT logged, and the
# transient error still propagates
# ===========================================================================


def test_b5_exhausted_budget_reraises_and_logs_only_recovered_retries(caplog):
    """With ``max_attempts == 2`` and a throttle that persists past the budget,
    ``.synthesize()`` RE-RAISES ``LLMThrottleError`` (the transient error
    surfaces unchanged) AND produces EXACTLY 1 ``L0 retry`` record (attempt 1
    only) --- ``on_retry`` fires only before a retry that actually follows, so
    the final budget-exhausting attempt emits no record."""
    client = ScriptedLLMClient([_raise_entry("throttle"), _raise_entry("throttle")])
    synth = _synthesizer(client, _det_settings(max_attempts=2))

    caplog.set_level(logging.INFO, logger=SYNTH_LOGGER)
    with pytest.raises(LLMThrottleError) as excinfo:
        synth.synthesize(_snapshot())

    records = _retry_records(caplog)
    assert len(records) == 1, (
        "a persisting throttle with max_attempts==2 must log exactly 1 recovered "
        f"retry (attempt 1); got {len(records)}: {[r.getMessage() for r in records]}"
    )
    m = _MSG_RE.match(records[0].getMessage())
    assert m is not None and m.group("attempt") == "1", records[0].getMessage()
    # The propagated exception's text is the same one carried in the record.
    assert str(excinfo.value) in records[0].getMessage()


# ===========================================================================
# Behavior 6 --- no public-surface / return-value change; log-only, no counter
# ===========================================================================


def test_b6_return_value_unchanged_for_a_given_input(caplog):
    """The observability wiring does not change ``.synthesize()``'s parsed/deduped
    return: for a valid two-goal reply the returned slate carries the same goals,
    scores, categories, ranking, and workspace_root as before."""
    goals = [
        _goal_dict("Add retry/backoff to the LLM client"),
        {
            "title": "Study agentic loop patterns",
            "category": "learning",
            "impact": 3.0,
            "urgency": 2.0,
            "confidence": 0.5,
            "effort_weight": 1.0,
            "appropriate_now": True,
        },
    ]
    client = ScriptedLLMClient([_valid_entry(goals)])
    synth = _synthesizer(client)

    caplog.set_level(logging.INFO, logger=SYNTH_LOGGER)
    slate = synth.synthesize(_snapshot())

    assert isinstance(slate, GoalSlate)
    assert slate.workspace_root == "/tmp/example-workspace"
    assert [g.title for g in slate.goals] == [
        "Add retry/backoff to the LLM client",
        "Study agentic loop patterns",
    ]
    # Computed score is unchanged: impact * urgency * confidence / effort_weight.
    assert slate.goals[0].score == 5.0 * 4.0 * 0.9 / 2.0
    assert slate.goals[1].score == 3.0 * 2.0 * 0.5 / 1.0
    assert slate.goals[0].category is GoalCategory.PROJECT
    assert slate.goals[1].category is GoalCategory.LEARNING
    # No goal object gained a scan-path 'retries' counter (log-only feature).
    for goal in slate.goals:
        assert not hasattr(goal, "retries")
    assert not hasattr(slate, "retries")


def test_b6_record_goes_only_to_the_synthesizer_package_logger(caplog):
    """The new record is a ``proactive_loop.scout.synthesizer`` INFO record and
    nothing else: capturing the WHOLE ``proactive_loop`` subtree, the only
    ``L0 retry`` records seen for a scout-only run are on the synthesizer
    logger (they never appear on the L1 executor logger, and never on stdout)."""
    client = ScriptedLLMClient(
        [_raise_entry("throttle"), _raise_entry("throttle"), _valid_entry()]
    )
    synth = _synthesizer(client, _det_settings(max_attempts=5))

    caplog.set_level(logging.INFO, logger="proactive_loop")
    synth.synthesize(_snapshot())

    pkg_retry_records = [
        r
        for r in caplog.records
        if r.getMessage().startswith(RETRY_PREFIX) and r.levelno == logging.INFO
    ]
    assert len(pkg_retry_records) == 2
    assert {r.name for r in pkg_retry_records} == {SYNTH_LOGGER}
    # No executor record was produced by a pure scout run.
    assert _retry_records(caplog, EXEC_LOGGER) == []


def test_b6_version_stays_pinned():
    """Additive observability wiring is not a versioned contract change."""
    assert __version__ == "0.1.1"
