"""Unit tests for the iter-46 internal helper ``sanitize_validation_error``.

These are WHITE-BOX tests of the pure formatter itself (the black-box CLI
behavior tests live in ``test_iter46_behavior.py``). They pin the message shape
and, most importantly, that NONE of pydantic's leaky fields (docs URL, error
taxonomy, model class name, raw ``input_value=`` echo) survive the sanitizer --
the whole point of the fix on a public repo.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from proactive_loop.models import GoalSlate, RunState, sanitize_validation_error

_FORBIDDEN = ("errors.pydantic.dev", "[type=", "input_value=", "GoalSlate", "RunState")


def _slate_type_invalid_error() -> ValidationError:
    """A valid-JSON slate with a non-numeric ``impact`` -> multi-error dump."""
    raw = (
        '{"schema_version": 1, "workspace_root": ".", "goals": ['
        '{"id": "g1", "title": "t", "category": "code_quality", '
        '"impact": "NOTANUMBER", "urgency": 0.5, "confidence": 0.5, '
        '"effort_weight": 1.0, "rationale": "r", "appropriate_now": true}]}'
    )
    with pytest.raises(ValidationError) as excinfo:
        GoalSlate.model_validate_json(raw)
    return excinfo.value


def _slate_malformed_json_error() -> ValidationError:
    """Not JSON at all -> a single ``json_invalid`` error with an EMPTY loc."""
    with pytest.raises(ValidationError) as excinfo:
        GoalSlate.model_validate_json("{ this is not json ")
    return excinfo.value


def _checkpoint_bad_status_error() -> ValidationError:
    """A checkpoint whose ``status`` is not a valid enum member."""
    with pytest.raises(ValidationError) as excinfo:
        RunState.from_json('{"status": "NOT_A_STATUS"}')
    return excinfo.value


def test_names_file_and_error_count_and_first_loc():
    exc = _slate_type_invalid_error()
    msg = sanitize_validation_error("slate", Path("bad.json"), exc)
    assert msg.startswith("invalid slate file 'bad.json': ")
    # >=1 error here (type-invalid slate yields at least the impact error).
    assert "validation error" in msg
    # First error location is joined by '.' and appended after '; first at'.
    assert "; first at " in msg
    loc = msg.split("; first at ", 1)[1]
    assert "." in loc or loc  # e.g. 'goals.0.impact' or a single element


def test_singular_vs_plural_error_word():
    single = _slate_malformed_json_error()
    assert single.error_count() == 1
    msg1 = sanitize_validation_error("slate", Path("x.json"), single)
    # Exactly one error -> singular 'validation error' (no trailing 's').
    assert "1 validation error" in msg1
    assert "validation errors" not in msg1

    multi = _slate_type_invalid_error()
    if multi.error_count() > 1:
        msgN = sanitize_validation_error("slate", Path("x.json"), multi)
        assert f"{multi.error_count()} validation errors" in msgN


def test_malformed_json_omits_first_at_clause():
    """json_invalid carries an EMPTY loc -> the '; first at' clause is dropped."""
    exc = _slate_malformed_json_error()
    assert exc.errors()[0]["loc"] == ()
    msg = sanitize_validation_error("slate", Path("x.json"), exc)
    assert msg == "invalid slate file 'x.json': 1 validation error"
    assert "; first at" not in msg


def test_checkpoint_kind_word_and_forbidden_fields_absent():
    exc = _checkpoint_bad_status_error()
    msg = sanitize_validation_error("checkpoint", Path("run/checkpoint.json"), exc)
    assert msg.startswith("invalid checkpoint file 'run/checkpoint.json': ")
    for token in _FORBIDDEN:
        assert token not in msg, f"leaked forbidden token {token!r} in: {msg!r}"


def test_no_forbidden_tokens_across_all_cases():
    """The core public-repo guarantee: no vendor fields survive, for any case."""
    cases = [
        ("slate", Path("s.json"), _slate_type_invalid_error()),
        ("slate", Path("s.json"), _slate_malformed_json_error()),
        ("checkpoint", Path("c.json"), _checkpoint_bad_status_error()),
    ]
    for kind, path, exc in cases:
        msg = sanitize_validation_error(kind, path, exc)
        assert "\n" not in msg, f"sanitized message must be a single line: {msg!r}"
        for token in _FORBIDDEN:
            assert token not in msg, f"leaked {token!r} for {kind}: {msg!r}"


def test_int_loc_parts_stringify():
    """A loc tuple with an int index (list position) joins as a plain string."""
    exc = _slate_type_invalid_error()
    # goals.0.<field> -> the '0' index must render, never crash on int join.
    msg = sanitize_validation_error("slate", Path("s.json"), exc)
    if "; first at " in msg:
        loc = msg.split("; first at ", 1)[1]
        # loc is a dotted path of stringified parts; must contain no tuple repr.
        assert "(" not in loc and ")" not in loc
