"""L0 resilience: retry-with-backoff and atomic, resumable checkpoints.

WHY these two primitives live together: they are the loop's defense against the
two failure modes of an unattended run -- transient provider throttling/timeouts
(handled by ``with_retry``) and abrupt process death mid-run (handled by an
atomic ``Checkpoint`` that lets ``GoalLoop.run(resume=...)`` pick up exactly
where it stopped).
"""

from __future__ import annotations

import random
import time
from pathlib import Path
from typing import Callable, TypeVar

from pydantic import ValidationError

from proactive_loop.config import RetryPolicy
from proactive_loop.llm.client import LLMThrottleError, LLMTimeoutError
from proactive_loop.models import RunState, atomic_write_text, sanitize_validation_error

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
        """Persist *state* atomically, creating the parent dir if needed.

        Mechanism (identical to the slate writer's, deliberately -- both now
        delegate to :func:`~proactive_loop.models.atomic_write_text`): write a
        SIBLING temp file, then one ``os.replace`` onto the target. Sibling
        placement is what keeps the rename inside a single filesystem, where
        ``os.replace`` is atomic, so a reader sees either the previous snapshot
        or the complete new one -- never a half-written prefix.

        WHY the ``finally``: this is the product's highest-frequency writer (one
        save per step), so a raising swap would otherwise leave a stray
        ``<name>.tmp`` in a run directory that is a documented, user-visible
        surface. Cleanup is best-effort and swallows its own ``OSError`` so the
        caller keeps seeing the PRIMARY failure, never a secondary error raised
        while tidying up. After a successful replace the temp name is already
        gone, so one ``finally`` covers both paths.
        """
        atomic_write_text(self.path, state.to_json())

    def load(self) -> RunState | None:
        """Return the checkpointed state, or None if none has been saved.

        A present-but-corrupt checkpoint (schema-invalid OR malformed JSON) is
        mapped to one dependency-opaque ``ValueError`` (via
        ``sanitize_validation_error``) so the CLI ``error:`` boundary that
        ``trace``/``resume`` funnel through never leaks pydantic's multi-line dump
        (model class name, ``[type=...]`` taxonomy, ``errors.pydantic.dev/<ver>``
        URL, or the raw ``input_value=`` echo of the checkpoint bytes). An ABSENT
        file still returns ``None`` (unchanged), and ``_run_row`` still catches the
        resulting ``ValueError`` to degrade a bad run to ``(no checkpoint)``.
        """
        if not self.path.is_file():
            return None
        try:
            return RunState.from_json(self.path.read_text())
        except ValidationError as exc:
            raise ValueError(
                sanitize_validation_error("checkpoint", self.path, exc)
            ) from None
