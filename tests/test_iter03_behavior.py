"""Black-box behavior tests for iteration 03.

Feature under test: ``Settings.from_env`` reads the five ``PLA_RETRY_*``
environment variables and builds the L0 ``RetryPolicy`` from present-only
overrides merged onto the ``RetryPolicy`` defaults -- making ``config.py``'s
"everything overridable via environment variables (prefix PLA_)" promise true
for the product's headline resilience knobs. This retires the iter-02 footgun
where the throttle path could not be exercised wait-free from configuration.

ISOLATION: these tests are written strictly against the public contract -- the
iteration spec's "Expected Behaviors", ``README.md``, and ``SPEC.md`` (§3, §4.5)
-- and exercise only the documented public surface
(``proactive_loop.config.Settings`` / ``RetryPolicy`` and the ``pla`` CLI via
``proactive_loop.cli.main``). No ``src/`` internals, no engineer/reviewer notes,
and no ``git diff`` were consulted. Every test toggles env state exclusively
through ``monkeypatch.setenv`` / ``monkeypatch.delenv`` so no env leaks across
tests, and everything runs fully offline -- zero network, zero API keys.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from proactive_loop.config import RetryPolicy, Settings

REPO = Path(__file__).resolve().parents[1]
# Absolute path (equivalent to the spec's ``examples/fixture_workspace``) so the
# CLI-composition test in behavior 13 does not depend on the pytest cwd.
FIXTURE = REPO / "examples" / "fixture_workspace"

_TRACEBACK = "Traceback (most recent call last)"

# The five retry knobs, kept in one place so every test can guarantee a clean
# slate regardless of the ambient environment.
_RETRY_VARS = (
    "PLA_RETRY_MAX_ATTEMPTS",
    "PLA_RETRY_BASE_BACKOFF_SEC",
    "PLA_RETRY_BACKOFF_FACTOR",
    "PLA_RETRY_MAX_BACKOFF_SEC",
    "PLA_RETRY_JITTER_FRAC",
)


def _clear_retry_env(monkeypatch) -> None:
    """Guarantee none of the five knobs are set (defensive vs. the real shell)."""
    for var in _RETRY_VARS:
        monkeypatch.delenv(var, raising=False)


# ---------------------------------------------------------------------------
# Behavior 1 -- no retry env set => defaults are untouched (regression guard)
# ---------------------------------------------------------------------------


def test_behavior1_no_retry_env_keeps_defaults(monkeypatch) -> None:
    _clear_retry_env(monkeypatch)

    retry = Settings.from_env().retry

    default = RetryPolicy()
    assert retry.max_attempts == default.max_attempts == 5
    assert retry.base_backoff_sec == default.base_backoff_sec == 1.0
    assert retry.backoff_factor == default.backoff_factor == 2.0
    assert retry.max_backoff_sec == default.max_backoff_sec == 60.0
    assert retry.jitter_frac == default.jitter_frac == 0.1


# ---------------------------------------------------------------------------
# Behaviors 2-6 -- each knob is read and coerced to the documented type
# ---------------------------------------------------------------------------


def test_behavior2_max_attempts_int_coerced(monkeypatch) -> None:
    _clear_retry_env(monkeypatch)
    monkeypatch.setenv("PLA_RETRY_MAX_ATTEMPTS", "7")

    value = Settings.from_env().retry.max_attempts

    assert value == 7
    assert isinstance(value, int)


def test_behavior3_base_backoff_sec_float_coerced(monkeypatch) -> None:
    _clear_retry_env(monkeypatch)
    monkeypatch.setenv("PLA_RETRY_BASE_BACKOFF_SEC", "0.5")

    value = Settings.from_env().retry.base_backoff_sec

    assert value == 0.5
    assert isinstance(value, float)


def test_behavior4_backoff_factor_float_coerced(monkeypatch) -> None:
    _clear_retry_env(monkeypatch)
    monkeypatch.setenv("PLA_RETRY_BACKOFF_FACTOR", "3.0")

    value = Settings.from_env().retry.backoff_factor

    assert value == 3.0
    assert isinstance(value, float)


def test_behavior5_max_backoff_sec_integer_string_becomes_float(monkeypatch) -> None:
    _clear_retry_env(monkeypatch)
    monkeypatch.setenv("PLA_RETRY_MAX_BACKOFF_SEC", "120")

    value = Settings.from_env().retry.max_backoff_sec

    # An integer-looking string coerces to a float per the documented mapping.
    assert value == 120.0
    assert isinstance(value, float)


def test_behavior6_jitter_frac_float_coerced(monkeypatch) -> None:
    _clear_retry_env(monkeypatch)
    monkeypatch.setenv("PLA_RETRY_JITTER_FRAC", "0.25")

    value = Settings.from_env().retry.jitter_frac

    assert value == 0.25
    assert isinstance(value, float)


# ---------------------------------------------------------------------------
# Behavior 7 -- a partial set overrides only the present knobs; rest = defaults
# ---------------------------------------------------------------------------


def test_behavior7_partial_set_leaves_the_rest_at_defaults(monkeypatch) -> None:
    _clear_retry_env(monkeypatch)
    monkeypatch.setenv("PLA_RETRY_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("PLA_RETRY_BASE_BACKOFF_SEC", "0")

    retry = Settings.from_env().retry

    # The two that were set:
    assert retry.max_attempts == 3
    assert retry.base_backoff_sec == 0.0
    # The three that were NOT set keep the model defaults:
    assert retry.backoff_factor == 2.0
    assert retry.max_backoff_sec == 60.0
    assert retry.jitter_frac == 0.1


# ---------------------------------------------------------------------------
# Behavior 8 -- wait-free throttle configuration is now reachable via env
# ---------------------------------------------------------------------------


def test_behavior8_wait_free_throttle_config_is_reachable(monkeypatch) -> None:
    _clear_retry_env(monkeypatch)
    monkeypatch.setenv("PLA_RETRY_MAX_ATTEMPTS", "1")
    monkeypatch.setenv("PLA_RETRY_BASE_BACKOFF_SEC", "0")

    retry = Settings.from_env().retry

    # A caller can now configure the retry policy to exercise a throttle path
    # with no real sleep -- assert on the policy values, not live timing.
    assert retry.max_attempts == 1
    assert retry.base_backoff_sec == 0.0


# ---------------------------------------------------------------------------
# Behavior 9 -- an explicit retry= override beats the environment
# ---------------------------------------------------------------------------


def test_behavior9_explicit_retry_override_beats_env(monkeypatch) -> None:
    _clear_retry_env(monkeypatch)
    monkeypatch.setenv("PLA_RETRY_MAX_ATTEMPTS", "7")

    settings = Settings.from_env(retry=RetryPolicy(max_attempts=2))

    # Explicit override wins over the env, per the env_values.update(overrides)
    # contract documented for from_env.
    assert settings.retry.max_attempts == 2


# ---------------------------------------------------------------------------
# Behavior 10 -- out-of-range values raise ValueError (pydantic bounds)
# ---------------------------------------------------------------------------


def test_behavior10_jitter_frac_above_bound_raises_valueerror(monkeypatch) -> None:
    _clear_retry_env(monkeypatch)
    monkeypatch.setenv("PLA_RETRY_JITTER_FRAC", "2.0")  # le=1.0 violated

    with pytest.raises(ValueError):
        Settings.from_env()


def test_behavior10_max_attempts_below_bound_raises_valueerror(monkeypatch) -> None:
    _clear_retry_env(monkeypatch)
    monkeypatch.setenv("PLA_RETRY_MAX_ATTEMPTS", "0")  # ge=1 violated

    with pytest.raises(ValueError):
        Settings.from_env()


# ---------------------------------------------------------------------------
# Behavior 11 -- a non-numeric value raises ValueError (coercion fails)
# ---------------------------------------------------------------------------


def test_behavior11_non_numeric_value_raises_valueerror(monkeypatch) -> None:
    _clear_retry_env(monkeypatch)
    monkeypatch.setenv("PLA_RETRY_MAX_ATTEMPTS", "abc")  # int("abc") fails

    with pytest.raises(ValueError):
        Settings.from_env()


# ---------------------------------------------------------------------------
# Behavior 12 -- no regression to the other PLA_* reads
# ---------------------------------------------------------------------------


def test_behavior12_no_regression_to_other_pla_reads(monkeypatch) -> None:
    _clear_retry_env(monkeypatch)
    monkeypatch.setenv("PLA_RETRY_MAX_ATTEMPTS", "9")
    monkeypatch.setenv("PLA_MAX_ITERATIONS", "3")

    settings = Settings.from_env()

    assert settings.retry.max_attempts == 9
    assert settings.max_iterations == 3


# ---------------------------------------------------------------------------
# Behavior 13 -- CLI composition with iter-02's error boundary
# ---------------------------------------------------------------------------


def test_behavior13_cli_out_of_range_env_is_legible_fault(monkeypatch, tmp_path, capsys) -> None:
    _clear_retry_env(monkeypatch)
    monkeypatch.setenv("PLA_RETRY_JITTER_FRAC", "2.0")  # out of range -> ValidationError

    from proactive_loop.cli import main

    # No --provider / --scripted-responses: the ValidationError is raised inside
    # the scan command before any LLM client is created, so the fault is fully
    # offline and caught by iter-02's top-level boundary.
    rc = main([
        "scan",
        "--workspace", str(FIXTURE),
        "--state-dir", str(tmp_path),
    ])
    err = capsys.readouterr().err

    assert rc == 1, f"an out-of-range env value must exit 1, got {rc}"
    assert _TRACEBACK not in err, f"stderr must NOT contain a traceback, got: {err!r}"

    lines = [ln for ln in err.splitlines() if ln.strip()]
    assert lines, f"stderr must carry an error message, got: {err!r}"
    # The fault is reported through iter-02's boundary as a leading ``error:``
    # line (not a raw traceback), and it is self-service -- it names the offending
    # field so an operator can fix their env without reading source.
    assert lines[0].startswith("error:"), (
        f"the fault must be reported as a line beginning 'error:', got: {err!r}"
    )
    assert "jitter_frac" in err, (
        f"the error should name the offending knob to be self-service, got: {err!r}"
    )
    # NOTE (PM feedback): the spec's behavior 13 says the boundary prints "a
    # single line". A pydantic ``ValidationError`` str is inherently multi-line,
    # and iter-02's boundary emits ``str(exc)`` verbatim, so this input yields a
    # 4-line message (incl. a pydantic.dev URL). Flattening it to one line would
    # change the CLI boundary -- explicitly OUT OF SCOPE for iter-03 ("No change
    # to ... any CLI verb's behavior"). We therefore assert the boundary's real,
    # in-scope contract (exit 1 + leading ``error:`` line + no traceback) and log
    # the single-line wording gap in tester.md / LEARNINGS for the PM.
