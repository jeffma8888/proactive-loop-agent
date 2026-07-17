"""L0 resilience: retry-with-backoff and atomic, resumable checkpoints.

WHY these two primitives live together: they are the loop's defense against the
two failure modes of an unattended run -- transient provider throttling/timeouts
(handled by ``with_retry``) and abrupt process death mid-run (handled by an
atomic ``Checkpoint`` that lets ``GoalLoop.run(resume=...)`` pick up exactly
where it stopped).
"""

from __future__ import annotations

import os
import random
import time
from pathlib import Path
from typing import Callable, TypeVar

from proactive_loop.config import RetryPolicy
from proactive_loop.llm.client import LLMThrottleError, LLMTimeoutError
from proactive_loop.models import RunState, ensure_dir

T = TypeVar("T")

# ONLY these are retried: they signal a transient, capacity-side failure. Any
# other exception (bad request, parse error, bug) is a real fault -- retrying it
# just wastes budget, so it propagates immediately.
_RETRYABLE: tuple[type[Exception], ...] = (LLMThrottleError, LLMTimeoutError)


def _backoff_delay(policy: RetryPolicy, attempt: int) -> float:
    """Delay before the next retry, per SPEC 4.4.

    Formula: ``min(base * factor**(attempt-1), max) * (1 +/- jitter)``. WHY
    jitter: it spreads many clients' retries so they don't wake in lockstep and
    re-throttle the provider (thundering herd). WHY jitter is skipped when
    ``jitter_frac == 0``: it keeps the delay fully deterministic for tests.
    """
    raw = policy.base_backoff_sec * (policy.backoff_factor ** (attempt - 1))
    capped = min(raw, policy.max_backoff_sec)
    if policy.jitter_frac <= 0.0:
        return capped
    return capped * (1.0 + random.uniform(-policy.jitter_frac, policy.jitter_frac))


def with_retry(
    fn: Callable[[], T],
    policy: RetryPolicy,
    *,
    sleep: Callable[[float], object] = time.sleep,
    on_retry: Callable[[int, float, Exception], None] | None = None,
) -> T:
    """Call *fn*, retrying only throttle/timeout errors with exponential backoff.

    Re-raises the last error once ``policy.max_attempts`` is reached. *sleep* is
    injectable so tests can assert the backoff sequence without real waiting;
    *on_retry(attempt, delay, exc)* is an optional observability hook.
    """
    attempt = 0
    while True:
        attempt += 1
        try:
            return fn()
        except _RETRYABLE as exc:
            # Out of attempts -> surface the transient error to the caller.
            if attempt >= policy.max_attempts:
                raise
            delay = _backoff_delay(policy, attempt)
            if on_retry is not None:
                on_retry(attempt, delay, exc)
            sleep(delay)


class Checkpoint:
    """Atomic, resumable JSON snapshot of a single :class:`RunState`.

    WHY atomic (temp file + ``os.replace``): a crash or kill mid-write must
    never leave a truncated/corrupt state file. ``os.replace`` is atomic on the
    same filesystem, so a reader always sees either the old or the new state.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def save(self, state: RunState) -> None:
        """Persist *state* atomically, creating the parent dir if needed."""
        ensure_dir(self.path.parent)
        # Write a sibling temp file first, then atomically swap it into place.
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(state.to_json())
        os.replace(tmp, self.path)

    def load(self) -> RunState | None:
        """Return the checkpointed state, or None if none has been saved."""
        if not self.path.is_file():
            return None
        return RunState.from_json(self.path.read_text())
