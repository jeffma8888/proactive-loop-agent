"""Black-box behavior tests for iteration 30.

Feature under test: ``Settings.from_env`` (``proactive_loop.config``) now fails a
mistyped numeric ``PLA_*`` env var with an ACTIONABLE, single-line ``ValueError``
of the shape ``PLA_<NAME> must be a valid <integer|number>, got '<value>'`` instead
of Python's field-less builtin coercion message. This applies the product's own
stated principle -- "misconfiguration should be obvious, not a cryptic error" --
uniformly to the eight numeric config knobs (the three scalar reads plus the five
``PLA_RETRY_*`` loop reads).

ISOLATION STATEMENT: these tests were written strictly against the PUBLIC contract
-- the iteration spec's "Expected Behaviors" (pm.md), ``README.md``, and ``SPEC.md``
-- and exercise only the documented public surface: ``proactive_loop.config.Settings``
and the ``pla`` CLI via ``proactive_loop.cli.main``. No file under ``src/`` was read,
no engineer/reviewer notes were consulted, and no ``git diff`` was inspected. Every
test toggles env state exclusively through ``monkeypatch.setenv`` / ``monkeypatch.delenv``
so nothing leaks across tests, and everything runs fully offline -- zero network,
zero API keys, no real SDKs. The CLI faults are raised inside ``Settings.from_env``
before any LLM client is constructed, so the scripted-provider seam is not even
needed for the error paths.
"""

from __future__ import annotations

import pytest

import proactive_loop
from proactive_loop.cli import main
from proactive_loop.config import Settings

_TRACEBACK = "Traceback (most recent call last)"

# The eight numeric env vars and their required "type word" (behaviors 1-5 table).
_INT_VARS = (
    "PLA_MAX_ITERATIONS",
    "PLA_MAX_LLM_CALLS",
    "PLA_RETRY_MAX_ATTEMPTS",
)
_FLOAT_VARS = (
    "PLA_AUTO_DISPATCH_MIN_SCORE",
    "PLA_RETRY_BASE_BACKOFF_SEC",
    "PLA_RETRY_BACKOFF_FACTOR",
    "PLA_RETRY_MAX_BACKOFF_SEC",
    "PLA_RETRY_JITTER_FRAC",
)
_ALL_NUMERIC_VARS = _INT_VARS + _FLOAT_VARS

_TYPE_WORD = {**{v: "integer" for v in _INT_VARS}, **{v: "number" for v in _FLOAT_VARS}}


def _clean_numeric_env(monkeypatch) -> None:
    """Guarantee a clean slate: none of the eight numeric knobs are set.

    Defensive against a developer's real shell exporting a ``PLA_*`` value.
    """
    for var in _ALL_NUMERIC_VARS:
        monkeypatch.delenv(var, raising=False)


def _nonempty_lines(text: str) -> list[str]:
    return [ln for ln in text.splitlines() if ln.strip()]


# ---------------------------------------------------------------------------
# The eight-var table (covers behaviors 1-5 exhaustively): a coercion failure
# on ANY numeric knob names the var + its type word + the offending repr'd value.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("var", _ALL_NUMERIC_VARS)
def test_every_numeric_var_coercion_error_is_actionable(monkeypatch, var) -> None:
    _clean_numeric_env(monkeypatch)
    monkeypatch.setenv(var, "totally-not-a-number")

    with pytest.raises(ValueError) as excinfo:
        Settings.from_env()

    msg = str(excinfo.value)
    assert var in msg, f"message must name the offending env var {var!r}; got {msg!r}"
    assert _TYPE_WORD[var] in msg, (
        f"message must name the expected type word {_TYPE_WORD[var]!r} for {var}; got {msg!r}"
    )
    assert repr("totally-not-a-number") in msg, (
        f"message must show the offending value via repr(); got {msg!r}"
    )


# ---------------------------------------------------------------------------
# Behavior 1 -- scalar int var, non-numeric value.
# ---------------------------------------------------------------------------


def test_behavior01_scalar_int_non_numeric(monkeypatch) -> None:
    _clean_numeric_env(monkeypatch)
    monkeypatch.setenv("PLA_MAX_ITERATIONS", "abc")

    with pytest.raises(ValueError) as excinfo:
        Settings.from_env()

    msg = str(excinfo.value)
    assert "PLA_MAX_ITERATIONS" in msg
    assert "integer" in msg
    assert "'abc'" in msg


# ---------------------------------------------------------------------------
# Behavior 2 -- scalar int var, non-integer numeric value (int("1.5") fails).
# ---------------------------------------------------------------------------


def test_behavior02_scalar_int_non_integer_numeric(monkeypatch) -> None:
    _clean_numeric_env(monkeypatch)
    monkeypatch.setenv("PLA_MAX_LLM_CALLS", "1.5")

    with pytest.raises(ValueError) as excinfo:
        Settings.from_env()

    msg = str(excinfo.value)
    assert "PLA_MAX_LLM_CALLS" in msg
    assert "integer" in msg
    assert "'1.5'" in msg


# ---------------------------------------------------------------------------
# Behavior 3 -- scalar float var, non-numeric value.
# ---------------------------------------------------------------------------


def test_behavior03_scalar_float_non_numeric(monkeypatch) -> None:
    _clean_numeric_env(monkeypatch)
    monkeypatch.setenv("PLA_AUTO_DISPATCH_MIN_SCORE", "high")

    with pytest.raises(ValueError) as excinfo:
        Settings.from_env()

    msg = str(excinfo.value)
    assert "PLA_AUTO_DISPATCH_MIN_SCORE" in msg
    assert "number" in msg
    assert "'high'" in msg


# ---------------------------------------------------------------------------
# Behavior 4 -- retry-loop int var (proves the _RETRY_ENV_VARS loop is covered).
# ---------------------------------------------------------------------------


def test_behavior04_retry_loop_int_var(monkeypatch) -> None:
    _clean_numeric_env(monkeypatch)
    monkeypatch.setenv("PLA_RETRY_MAX_ATTEMPTS", "abc")

    with pytest.raises(ValueError) as excinfo:
        Settings.from_env()

    msg = str(excinfo.value)
    assert "PLA_RETRY_MAX_ATTEMPTS" in msg
    assert "integer" in msg
    assert "'abc'" in msg


# ---------------------------------------------------------------------------
# Behavior 5 -- retry-loop float var.
# ---------------------------------------------------------------------------


def test_behavior05_retry_loop_float_var(monkeypatch) -> None:
    _clean_numeric_env(monkeypatch)
    monkeypatch.setenv("PLA_RETRY_JITTER_FRAC", "notafloat")

    with pytest.raises(ValueError) as excinfo:
        Settings.from_env()

    msg = str(excinfo.value)
    assert "PLA_RETRY_JITTER_FRAC" in msg
    assert "number" in msg
    assert "'notafloat'" in msg


# ---------------------------------------------------------------------------
# Behavior 6 -- plain ValueError + single-line message across all 5 cases.
# The spec asserts ONLY the base type (a plain ``ValueError`` is sufficient;
# no bespoke subclass may be required). The single-line check (no ``\n``) is
# what guarantees the clean one-line ``error:`` render at the CLI boundary.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "var,value",
    [
        ("PLA_MAX_ITERATIONS", "abc"),
        ("PLA_MAX_LLM_CALLS", "1.5"),
        ("PLA_AUTO_DISPATCH_MIN_SCORE", "high"),
        ("PLA_RETRY_MAX_ATTEMPTS", "abc"),
        ("PLA_RETRY_JITTER_FRAC", "notafloat"),
    ],
)
def test_behavior06_plain_valueerror_single_line(monkeypatch, var, value) -> None:
    _clean_numeric_env(monkeypatch)
    monkeypatch.setenv(var, value)

    with pytest.raises(ValueError) as excinfo:
        Settings.from_env()

    exc = excinfo.value
    assert isinstance(exc, ValueError), f"coercion fault must be a (base) ValueError, got {type(exc)!r}"
    assert "\n" not in str(exc), f"coercion message must be a single line, got {str(exc)!r}"


# ---------------------------------------------------------------------------
# Behavior 7 -- CLI end-to-end, int var => exit 1, exactly one error: line,
# no traceback, no slate on stdout.
# ---------------------------------------------------------------------------


def test_behavior07_cli_int_var_single_error_line(monkeypatch, tmp_path, capsys) -> None:
    _clean_numeric_env(monkeypatch)
    monkeypatch.setenv("PLA_MAX_ITERATIONS", "abc")

    rc = main(["scan", "--workspace", str(tmp_path), "--state-dir", str(tmp_path)])
    captured = capsys.readouterr()

    assert rc == 1, f"a malformed numeric env var must exit 1, got {rc}"
    assert _TRACEBACK not in captured.err, f"stderr must NOT contain a traceback, got: {captured.err!r}"

    lines = _nonempty_lines(captured.err)
    assert len(lines) == 1, f"stderr must be exactly one non-empty line, got: {captured.err!r}"
    assert lines[0].startswith("error: "), f"the one line must start with 'error: ', got: {lines[0]!r}"
    assert "PLA_MAX_ITERATIONS" in lines[0], f"the error line must name the env var, got: {lines[0]!r}"
    assert captured.out.strip() == "", f"stdout must carry no slate output, got: {captured.out!r}"


# ---------------------------------------------------------------------------
# Behavior 8 -- CLI end-to-end, retry float var => exit 1, one error: line,
# names the var, no traceback.
# ---------------------------------------------------------------------------


def test_behavior08_cli_retry_float_var_error_line(monkeypatch, tmp_path, capsys) -> None:
    _clean_numeric_env(monkeypatch)
    monkeypatch.setenv("PLA_RETRY_BACKOFF_FACTOR", "x")

    rc = main(["scan", "--workspace", str(tmp_path), "--state-dir", str(tmp_path)])
    captured = capsys.readouterr()

    assert rc == 1, f"a malformed retry env var must exit 1, got {rc}"
    assert _TRACEBACK not in captured.err, f"stderr must NOT contain a traceback, got: {captured.err!r}"

    lines = _nonempty_lines(captured.err)
    assert len(lines) == 1, f"stderr must be a single non-empty line, got: {captured.err!r}"
    assert lines[0].startswith("error: "), f"the line must start with 'error: ', got: {lines[0]!r}"
    assert "PLA_RETRY_BACKOFF_FACTOR" in lines[0], f"the error must name the env var, got: {lines[0]!r}"


# ---------------------------------------------------------------------------
# Behavior 9 -- regression: all valid values still parse (byte-stable success).
# ---------------------------------------------------------------------------


def test_behavior09_valid_values_still_parse(monkeypatch) -> None:
    _clean_numeric_env(monkeypatch)
    monkeypatch.setenv("PLA_AUTO_DISPATCH_MIN_SCORE", "3.5")
    monkeypatch.setenv("PLA_MAX_ITERATIONS", "6")
    monkeypatch.setenv("PLA_MAX_LLM_CALLS", "12")
    monkeypatch.setenv("PLA_RETRY_MAX_ATTEMPTS", "7")
    monkeypatch.setenv("PLA_RETRY_BASE_BACKOFF_SEC", "0.5")
    monkeypatch.setenv("PLA_RETRY_BACKOFF_FACTOR", "3.0")
    monkeypatch.setenv("PLA_RETRY_MAX_BACKOFF_SEC", "90")
    monkeypatch.setenv("PLA_RETRY_JITTER_FRAC", "0.25")

    settings = Settings.from_env()

    assert settings.auto_dispatch_min_score == 3.5
    assert settings.max_iterations == 6
    assert settings.max_llm_calls == 12
    assert settings.retry.max_attempts == 7
    assert settings.retry.base_backoff_sec == 0.5
    assert settings.retry.backoff_factor == 3.0
    assert settings.retry.max_backoff_sec == 90.0
    assert settings.retry.jitter_frac == 0.25


# ---------------------------------------------------------------------------
# Behavior 10 -- regression: out-of-range value path UNCHANGED (pydantic range
# validation, NOT reshaped into a coercion-style message, NOT swallowed).
# ---------------------------------------------------------------------------


def test_behavior10_out_of_range_still_pydantic_valueerror(monkeypatch) -> None:
    _clean_numeric_env(monkeypatch)
    monkeypatch.setenv("PLA_RETRY_JITTER_FRAC", "2.0")  # float() ok, but > le=1.0 bound

    with pytest.raises(ValueError) as excinfo:
        Settings.from_env()

    msg = str(excinfo.value)
    # The value coerces fine, so the coercion guard must NOT fire: the fault flows
    # from pydantic range validation untouched, so it must NOT be reshaped into the
    # new coercion-style "must be a valid <type>" message.
    assert "must be a valid" not in msg, (
        f"an out-of-range (coercible) value must go through pydantic, not the coercion "
        f"guard; got {msg!r}"
    )


def test_behavior10_cli_out_of_range_is_legible_fault(monkeypatch, tmp_path, capsys) -> None:
    _clean_numeric_env(monkeypatch)
    monkeypatch.setenv("PLA_RETRY_JITTER_FRAC", "2.0")

    rc = main(["scan", "--workspace", str(tmp_path), "--state-dir", str(tmp_path)])
    captured = capsys.readouterr()

    assert rc == 1, f"an out-of-range env value must still exit 1, got {rc}"
    assert _TRACEBACK not in captured.err, f"stderr must NOT contain a traceback, got: {captured.err!r}"
    lines = _nonempty_lines(captured.err)
    assert lines, f"stderr must carry an error message, got: {captured.err!r}"
    assert lines[0].startswith("error:"), f"the fault must lead with an 'error:' line, got: {captured.err!r}"
    # Byte-identical to before this iteration: this range path is NOT reshaped into
    # the new coercion phrasing (pydantic names the field, not the PLA_ env var).
    assert "must be a valid" not in captured.err, (
        f"the range fault must not be reshaped into the coercion message, got: {captured.err!r}"
    )


# ---------------------------------------------------------------------------
# Behavior 11 -- regression: negative value path UNCHANGED (pydantic ge bound).
# ---------------------------------------------------------------------------


def test_behavior11_negative_still_pydantic_valueerror(monkeypatch) -> None:
    _clean_numeric_env(monkeypatch)
    monkeypatch.setenv("PLA_AUTO_DISPATCH_MIN_SCORE", "-1")  # float() ok, but < ge=0.0

    with pytest.raises(ValueError) as excinfo:
        Settings.from_env()

    msg = str(excinfo.value)
    assert "must be a valid" not in msg, (
        f"a negative (coercible) value must be rejected by pydantic, not the coercion "
        f"guard; got {msg!r}"
    )


# ---------------------------------------------------------------------------
# Behavior 12 -- regression: empty string is treated as unset (default used).
# ---------------------------------------------------------------------------


def test_behavior12_empty_string_is_unset(monkeypatch) -> None:
    _clean_numeric_env(monkeypatch)
    monkeypatch.setenv("PLA_MAX_ITERATIONS", "")  # empty -> treated as unset

    settings = Settings.from_env()

    assert settings.max_iterations == 8, (
        f"an empty PLA_MAX_ITERATIONS must fall back to the default 8, got {settings.max_iterations}"
    )


def test_behavior12_unset_uses_default(monkeypatch) -> None:
    _clean_numeric_env(monkeypatch)  # completely unset

    settings = Settings.from_env()

    assert settings.max_iterations == 8


# ---------------------------------------------------------------------------
# Behavior 13 -- version unchanged (purely additive failure-path change).
# ---------------------------------------------------------------------------


def test_behavior13_version_unchanged(monkeypatch) -> None:
    _clean_numeric_env(monkeypatch)
    assert proactive_loop.__version__ == "0.1.1", proactive_loop.__version__
