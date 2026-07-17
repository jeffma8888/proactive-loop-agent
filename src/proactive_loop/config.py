"""Runtime settings and retry policy.

Everything is overridable via environment variables (prefix PLA_) so the CLI,
tests, and any embedding host can configure behavior without code changes.
The default provider is "scripted" so the whole system runs offline.
"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field

from .models import GoalCategory

ENV_PREFIX = "PLA_"

DEFAULT_SENSITIVE = frozenset({GoalCategory.HEALTH_ADMIN, GoalCategory.FINANCE_LEGAL})


class RetryPolicy(BaseModel):
    """Exponential backoff parameters for throttle/timeout retries.

    Defaults are demo-scale (seconds). A production deployment against a real
    rate-limited API would raise base_backoff_sec substantially.
    """

    max_attempts: int = Field(default=5, ge=1)
    base_backoff_sec: float = Field(default=1.0, ge=0.0)
    backoff_factor: float = Field(default=2.0, ge=1.0)
    max_backoff_sec: float = Field(default=60.0, ge=0.0)
    jitter_frac: float = Field(default=0.1, ge=0.0, le=1.0)


class Settings(BaseModel):
    """Top-level configuration for a scan/dispatch session."""

    provider: str = "scripted"                 # scripted | anthropic | openai | bedrock
    model: str | None = None
    scripted_responses_path: Path | None = None
    workspace_root: Path = Path(".")
    state_dir: Path = Path(".pla_runs")
    auto_dispatch_min_score: float = 4.0
    sensitive_categories: set[GoalCategory] = Field(
        default_factory=lambda: set(DEFAULT_SENSITIVE)
    )
    max_iterations: int = Field(default=8, ge=1)
    max_llm_calls: int = Field(default=24, ge=1)
    retry: RetryPolicy = Field(default_factory=RetryPolicy)

    @classmethod
    def from_env(cls, **overrides: object) -> "Settings":
        """Build Settings from PLA_* env vars, then apply explicit overrides.

        Explicit overrides always win over the environment so CLI flags can
        take precedence without callers having to mutate os.environ.
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
            env_values["auto_dispatch_min_score"] = float(v)
        if (v := _get("MAX_ITERATIONS")) is not None:
            env_values["max_iterations"] = int(v)
        if (v := _get("MAX_LLM_CALLS")) is not None:
            env_values["max_llm_calls"] = int(v)

        env_values.update({k: v for k, v in overrides.items() if v is not None})
        return cls(**env_values)  # type: ignore[arg-type]
