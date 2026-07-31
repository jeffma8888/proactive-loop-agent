"""Runtime settings and retry policy.

Everything is overridable via environment variables (prefix ``PLA_``) so the
CLI, tests, and any embedding host can configure behavior without code changes.
This includes the five L0 ``RetryPolicy`` knobs -- ``PLA_RETRY_MAX_ATTEMPTS``,
``PLA_RETRY_BASE_BACKOFF_SEC``, ``PLA_RETRY_BACKOFF_FACTOR``,
``PLA_RETRY_MAX_BACKOFF_SEC``, ``PLA_RETRY_JITTER_FRAC`` -- so the product's
headline resilience surface is tunable on an unattended, throttle-resilient
deployment without editing source. The default provider is "scripted" so the
whole system runs offline.
"""

from __future__ import annotations

import math
import os
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

from .models import GoalCategory

ENV_PREFIX = "PLA_"

# The five ``PLA_RETRY_*`` env vars, each mapped to (RetryPolicy field, coercion).
# Coercion runs at read time so a non-numeric value fails with ValueError exactly
# like the MAX_ITERATIONS read; only the vars actually present are applied, which
# is what lets a partial set leave the untouched RetryPolicy fields at defaults.
_RETRY_ENV_VARS: tuple[tuple[str, str, Callable[[str], object]], ...] = (
    ("RETRY_MAX_ATTEMPTS", "max_attempts", int),
    ("RETRY_BASE_BACKOFF_SEC", "base_backoff_sec", float),
    ("RETRY_BACKOFF_FACTOR", "backoff_factor", float),
    ("RETRY_MAX_BACKOFF_SEC", "max_backoff_sec", float),
    ("RETRY_JITTER_FRAC", "jitter_frac", float),
)

DEFAULT_SENSITIVE = frozenset({GoalCategory.HEALTH_ADMIN, GoalCategory.FINANCE_LEGAL})


def _reject_non_finite(v: float) -> float:
    """Reject a non-finite float (``inf``/``-inf``/``nan``) on an upward-unbounded knob.

    Why: the ``Field(ge=...)`` bounds only fence the LOWER end, so ``+inf`` slips
    through today (``inf >= 0.0`` is ``True``) with two live harms. On
    ``auto_dispatch_min_score`` it silently DISABLES the headline autonomous path --
    every finite goal score is ``< inf``, so the gate never resolves AUTO_DISPATCH,
    yet ``pla run`` still scans, finds nothing to run, and exits ``0`` reporting
    success. On a ``RetryPolicy`` backoff knob it breaks the resilience layer with
    its own config: ``resilience._backoff_delay`` computes ``min(raw, inf) == inf``,
    so a single throttle retry calls ``sleep(inf)`` and an unattended run hangs
    forever. This is the ``+inf`` mirror of SPEC section 3's existing negative-threshold
    guard -- a finite value keeps the setting numerically usable.

    A PLAIN ``ValueError`` (not a subclass) is raised so pydantic wraps it into a
    ``ValidationError`` (itself a ``ValueError``) that names the offending field, and
    ``main()``'s existing ``except (LLMError, ValueError, OSError)`` boundary maps it
    to one ``error:`` line + exit 1 with no CLI code change. No upper bound is added:
    a large FINITE threshold merely approves less and a large finite backoff merely
    waits longer -- both safe.
    """
    if not math.isfinite(v):
        raise ValueError(f"must be a finite number, got {v}")
    return v


def _coerce_env(suffix: str, value: str, coerce: Callable[[str], object]) -> object:
    """Coerce a raw ``PLA_*`` env value, upgrading a bare coercion failure into an
    actionable one that names the offending env var and its expected type.

    Why: ``config.py`` promises every knob is env-overridable, and the product's own
    operating principle (iter-23) is that misconfiguration should be obvious, not
    cryptic. A bare ``int("abc")`` raises ``invalid literal for int()`` which tells
    the operator nothing about WHICH ``PLA_*`` var is wrong -- the first thing a
    public-repo user hits when tuning the headline L0 resilience knobs. We wrap ONLY
    the per-value ``int``/``float`` coercion so a typo fails with
    ``PLA_<NAME> must be a valid <type>, got '<value>'``; pydantic range validation
    on the constructed models is deliberately left unwrapped so its out-of-range /
    negative ``ValidationError``s continue to flow through untouched.

    A plain ``ValueError`` (not a subclass) is raised so it composes with iter-02's
    ``main()`` boundary (``except (LLMError, ValueError, OSError)``) and keeps exit
    code ``1``; the message is a single line so it renders as one clean ``error:``
    line at the CLI.
    """
    typeword = "integer" if coerce is int else "number"
    try:
        return coerce(value)
    except ValueError:
        # ``from None`` drops the builtin chain so ``str(exc)`` stays single-line.
        raise ValueError(
            f"{ENV_PREFIX}{suffix} must be a valid {typeword}, got {value!r}"
        ) from None


class RetryPolicy(BaseModel):
    """Exponential backoff parameters for throttle/timeout retries.

    Defaults are demo-scale (seconds). A production deployment against a real
    rate-limited API would raise base_backoff_sec substantially -- set it (and
    the other four knobs) via the ``PLA_RETRY_*`` env vars, no code change needed.
    """

    max_attempts: int = Field(default=5, ge=1)
    base_backoff_sec: float = Field(default=1.0, ge=0.0)
    backoff_factor: float = Field(default=2.0, ge=1.0)
    max_backoff_sec: float = Field(default=60.0, ge=0.0)
    jitter_frac: float = Field(default=0.1, ge=0.0, le=1.0)

    # mode="after" so the ``ge`` bounds run first: ``-inf``/``nan`` are caught by the
    # range constraint, leaving only ``+inf`` for this guard to reject. ``jitter_frac``
    # is deliberately excluded -- its ``le=1.0`` already rejects every non-finite value.
    @field_validator("base_backoff_sec", "backoff_factor", "max_backoff_sec", mode="after")
    @classmethod
    def _finite_backoff(cls, v: float) -> float:
        return _reject_non_finite(v)


class Settings(BaseModel):
    """Top-level configuration for a scan/dispatch session."""

    provider: str = "scripted"                 # scripted | anthropic | openai | bedrock
    model: str | None = None
    scripted_responses_path: Path | None = None
    workspace_root: Path = Path(".")
    state_dir: Path = Path(".pla_runs")
    # A negative threshold would make ``score >= threshold`` trivially true for
    # every non-sensitive, appropriate goal (all score operands are bounded
    # ``>= 0``), silently auto-dispatching the whole slate with zero human
    # approval -- the single worst misconfiguration for a gate-sensitive-work
    # agent. Bound it ``ge=0.0`` (NOT ``gt``) because ``0.0`` is a legitimate,
    # deliberate "auto-dispatch every scored goal" setting; no upper bound
    # because a large threshold just approves less, which is safe.
    auto_dispatch_min_score: float = Field(default=4.0, ge=0.0)
    sensitive_categories: set[GoalCategory] = Field(
        default_factory=lambda: set(DEFAULT_SENSITIVE)
    )
    max_iterations: int = Field(default=8, ge=1)
    max_llm_calls: int = Field(default=24, ge=1)
    retry: RetryPolicy = Field(default_factory=RetryPolicy)

    # mode="after" so the ``ge=0.0`` bound runs first (rejecting ``-inf``/``nan``),
    # leaving only ``+inf`` -- the mirror of the negative-threshold guard above.
    @field_validator("auto_dispatch_min_score", mode="after")
    @classmethod
    def _finite_threshold(cls, v: float) -> float:
        return _reject_non_finite(v)

    @classmethod
    def from_env(cls, **overrides: object) -> "Settings":
        """Build Settings from PLA_* env vars, then apply explicit overrides.

        Explicit overrides always win over the environment so CLI flags can
        take precedence without callers having to mutate os.environ.

        A malformed numeric env var (e.g. ``PLA_MAX_ITERATIONS=abc``) fails fast
        with an actionable ``PLA_<NAME> must be a valid <integer|number>`` message
        naming the offending var and its expected type, instead of a cryptic
        Python coercion error. Out-of-range values still surface via pydantic.
        """
        env_values: dict[str, object] = {}

        def _get(name: str) -> str | None:
            value = os.environ.get(ENV_PREFIX + name)
            return value if value not in (None, "") else None

        if (v := _get("PROVIDER")) is not None:
            env_values["provider"] = v
        if (v := _get("MODEL")) is not None:
            env_values["model"] = v
        if (v := _get("SCRIPTED_RESPONSES")) is not None:
            env_values["scripted_responses_path"] = Path(v)
        if (v := _get("WORKSPACE_ROOT")) is not None:
            env_values["workspace_root"] = Path(v)
        if (v := _get("STATE_DIR")) is not None:
            env_values["state_dir"] = Path(v)
        if (v := _get("AUTO_DISPATCH_MIN_SCORE")) is not None:
            env_values["auto_dispatch_min_score"] = _coerce_env(
                "AUTO_DISPATCH_MIN_SCORE", v, float
            )
        if (v := _get("MAX_ITERATIONS")) is not None:
            env_values["max_iterations"] = _coerce_env("MAX_ITERATIONS", v, int)
        if (v := _get("MAX_LLM_CALLS")) is not None:
            env_values["max_llm_calls"] = _coerce_env("MAX_LLM_CALLS", v, int)

        # Merge present-only PLA_RETRY_* overrides onto RetryPolicy() defaults.
        # Building from only the vars that are set (rather than a fully specified
        # policy) keeps unspecified fields at their defaults, and only touches
        # .retry at all when at least one knob is provided -- so an environment
        # with no PLA_RETRY_* vars yields the unchanged default RetryPolicy.
        retry_overrides: dict[str, object] = {}
        for suffix, field, coerce in _RETRY_ENV_VARS:
            if (v := _get(suffix)) is not None:
                retry_overrides[field] = _coerce_env(suffix, v, coerce)
        if retry_overrides:
            env_values["retry"] = RetryPolicy(**retry_overrides)  # type: ignore[arg-type]

        env_values.update({k: v for k, v in overrides.items() if v is not None})
        return cls(**env_values)  # type: ignore[arg-type]
