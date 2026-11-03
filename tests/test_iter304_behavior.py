"""Factory iter 555 (ROADMAP #344): non-finite floats are refused by pydantic's built-in bound.

``Settings.auto_dispatch_min_score``, ``Settings.max_seconds`` and ``RetryPolicy.{base_backoff_sec,
backoff_factor, max_backoff_sec}`` reject ``inf`` / ``-inf`` / ``nan`` through
``Field(allow_inf_nan=False)`` (error type ``finite_number``) instead of a home-grown validator.
Finite bounds, defaults, the env-sourced ``error:`` line and the CLI exit code are unchanged in
shape; the env message now carries pydantic's ``input should be a finite number`` reason.

Black-box: drives the public models, ``Settings.from_env()`` and ``cli.main([...])`` in-process.
ONE collected item (``make readme-headroom`` reads binding_headroom=6), paid for by folding the
vacuous ``test_iter41_behavior.py::test_behavior_07_math_is_finite_available``; the spec
behaviours live in private helpers called from it. Offline and deterministic.
"""

from __future__ import annotations

import contextlib
import io
import math
from pathlib import Path
from typing import Final

import pytest
from pydantic import ValidationError

import proactive_loop.config as config_mod
from proactive_loop.cli import main
from proactive_loop.config import RetryPolicy, Settings

REPO: Final = Path(__file__).resolve().parents[1]
CONFIG_PY: Final = REPO / "src" / "proactive_loop" / "config.py"
CLI_PY: Final = REPO / "src" / "proactive_loop" / "cli.py"
NON_FINITE: Final = (float("inf"), float("-inf"), float("nan"))
SETTINGS_FIELDS: Final = ("auto_dispatch_min_score", "max_seconds")
RETRY_FIELDS: Final = ("base_backoff_sec", "backoff_factor", "max_backoff_sec")
LEAKS: Final = ("[type=", "input_value=", "errors.pydantic.dev")


def _first_error(model: type, field: str, value: object) -> tuple[dict, str]:
    with pytest.raises(ValidationError) as exc:
        model(**{field: value})
    return exc.value.errors()[0], str(exc.value)


def _clear_pla_env(monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    for key in list(os.environ):
        if key.startswith("PLA_"):
            monkeypatch.delenv(key, raising=False)


def _b1_b3_non_finite_rejected() -> None:
    for model, fields in ((Settings, SETTINGS_FIELDS), (RetryPolicy, RETRY_FIELDS)):
        for field in fields:
            for value in NON_FINITE:
                err, text = _first_error(model, field, value)
                where = f"{model.__name__}({field}={value!r})"
                assert err["loc"] == (field,), f"{where}: loc={err['loc']!r}"
                assert err["type"] == "finite_number", f"{where}: type={err['type']!r}"
                assert "finite" in text, f"{where}: 'finite' missing from {text!r}"
    assert Settings(max_seconds=None).max_seconds is None
    assert Settings(max_seconds=30.0).max_seconds == 30.0


def _b4_finite_bounds_and_defaults() -> None:
    assert Settings(auto_dispatch_min_score=0.0).auto_dispatch_min_score == 0.0
    assert Settings(auto_dispatch_min_score=1e300).auto_dispatch_min_score == 1e300
    for model, field, value, want in (
        (Settings, "auto_dispatch_min_score", -1.0, "greater_than_equal"),
        (RetryPolicy, "backoff_factor", 0.5, "greater_than_equal"),
        (Settings, "max_seconds", 0.0, "greater_than"),
    ):
        err, _ = _first_error(model, field, value)
        assert err["type"] == want, f"{model.__name__}({field}={value}): {err['type']!r} != {want!r}"
    with pytest.raises(ValidationError):
        RetryPolicy(jitter_frac=float("inf"))
    s, r = Settings(), RetryPolicy()
    assert (s.auto_dispatch_min_score, s.max_seconds) == (4.0, None)
    assert (r.base_backoff_sec, r.backoff_factor, r.max_backoff_sec, r.jitter_frac, r.max_attempts) == (
        1.0, 2.0, 60.0, 0.1, 5,
    )


def _b5_env_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    cases = (
        ("PLA_AUTO_DISPATCH_MIN_SCORE", "inf", "auto_dispatch_min_score"),
        ("PLA_RETRY_BACKOFF_FACTOR", "inf", "backoff_factor"),
        ("PLA_MAX_SECONDS", "nan", "max_seconds"),
    )
    for var, raw, field in cases:
        _clear_pla_env(monkeypatch)
        monkeypatch.setenv(var, raw)
        with pytest.raises(ValueError) as exc:
            Settings.from_env()
        assert not isinstance(exc.value, ValidationError), f"{var}: leaked a ValidationError"
        want = f"{var}={raw!r} is out of range for {field} (input should be a finite number)"
        assert str(exc.value) == want, f"{var}: {str(exc.value)!r} != {want!r}"
    _clear_pla_env(monkeypatch)


def _b6_cli_scan_error_line(monkeypatch: pytest.MonkeyPatch, ws: Path) -> None:
    _clear_pla_env(monkeypatch)
    monkeypatch.setenv("PLA_AUTO_DISPATCH_MIN_SCORE", "inf")
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = main(["scan", "--workspace", str(ws)])
    _clear_pla_env(monkeypatch)
    assert rc == 1, f"rc={rc}; stderr={err.getvalue()!r}"
    lines = [ln for ln in err.getvalue().splitlines() if ln.strip()]
    assert len(lines) == 1, f"stderr lines: {lines!r}"
    assert lines[0].startswith("error: ") and "finite" in lines[0], lines[0]
    for leak in LEAKS:
        assert leak not in err.getvalue() and leak not in out.getvalue(), f"leaked {leak!r}"


def _b7_structure() -> None:
    for name in ("_reject_non_finite", "math"):
        assert not hasattr(config_mod, name), f"config still exposes {name!r}"
    text = CONFIG_PY.read_text(encoding="utf-8")
    for token in ("field_validator", "_reject_non_finite"):
        assert token not in text, f"config.py still mentions {token!r}"
    for model, fields in ((Settings, SETTINGS_FIELDS), (RetryPolicy, RETRY_FIELDS)):
        for field in fields:
            meta = model.model_fields[field].metadata
            assert any(getattr(m, "allow_inf_nan", None) is False for m in meta), (
                f"{model.__name__}.{field} lacks allow_inf_nan=False: {meta!r}"
            )
    assert "_finite_ceiling" not in CLI_PY.read_text(encoding="utf-8")
    assert math.isfinite(1.0) and not math.isfinite(float("nan"))  # folded iter41 premise


def test_b1_b7_non_finite_floats_use_pydantic_builtin(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    _b1_b3_non_finite_rejected()
    _b4_finite_bounds_and_defaults()
    _b5_env_messages(monkeypatch)
    _b6_cli_scan_error_line(monkeypatch, ws)
    _b7_structure()
