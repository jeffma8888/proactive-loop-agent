"""Black-box behavior tests for iteration 14 --- range-guarding the autonomy-gate
threshold ``Settings.auto_dispatch_min_score`` (ROADMAP #22).

Feature under test: ``Settings.auto_dispatch_min_score`` becomes a non-negative
float (``Field(default=4.0, ge=0.0)``). This closes a real autonomy-bypass: every
score operand is bounded ``>= 0`` so ``CandidateGoal.score`` is always ``>= 0``;
a *negative* threshold would make the L2 gate's ``score >= threshold`` rule
trivially true for **every** non-sensitive, appropriate goal, silently
auto-dispatching the whole slate with zero human approval. A negative value must
now be rejected at construction (and, via the existing ``float`` coercion in
``from_env`` + the ``main()`` error boundary, surface as an ``error:`` line +
exit 1 at the CLI). Zero stays legal (``ge`` not ``gt``); the default is
unchanged at ``4.0``; there is no upper bound.

ISOLATION CONTRACT (honored): these tests are written strictly against the public
contract for this iteration --- the iteration's PM "Expected Behaviors",
``README.md``, and ``SPEC.md`` (§3 "Foundation contracts → Key invariants" and
§4.3 gate rule) --- and drive ONLY the documented public surface:
``proactive_loop.config.Settings`` / ``Settings.from_env`` and the ``pla`` CLI
via ``proactive_loop.cli.main(argv) -> int`` with captured stdout/stderr and
observed exit codes. No file under ``src/`` was read, the engineer's and
reviewer's notes were not read, and no ``git diff`` was consulted. Every test
runs fully offline: zero network, zero API keys. The CLI behaviors deliberately
pass NO ``--provider`` / ``--scripted-responses`` because ``Settings`` are built
before any LLM client, so the config validation fails fast, offline, regardless
of provider. Env state is toggled exclusively through
``monkeypatch.setenv`` / ``monkeypatch.delenv`` so nothing leaks across tests.

Spec-wording note (PM feedback, see tester.md): Behavior 11 describes "a single
line beginning ``error:``" but the raw ``pydantic.ValidationError`` string
surfaced by the iter-02 error boundary is inherently multi-line --- its first
line begins ``error:`` and the ``auto_dispatch_min_score`` substring appears on a
later line. The Acceptance Criteria confirm the raw pydantic string is the
intended, asserted-against output, so these tests assert the substantive,
observable contract (stderr begins ``error:``, the stderr *output* contains
``auto_dispatch_min_score``, no Python traceback, error on stderr not stdout,
exit code exactly 1) rather than a literal one-line constraint.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pydantic = pytest.importorskip("pydantic")
from pydantic import ValidationError  # noqa: E402

from proactive_loop.cli import main  # noqa: E402
from proactive_loop.config import Settings  # noqa: E402

_ENV_VAR = "PLA_AUTO_DISPATCH_MIN_SCORE"
_FIELD = "auto_dispatch_min_score"
_TRACEBACK = "Traceback (most recent call last)"


def _clear_env(monkeypatch) -> None:
    """Guarantee the knob is unset (defensive vs. the ambient shell)."""
    monkeypatch.delenv(_ENV_VAR, raising=False)


# ===========================================================================
# Model-level (pure ``Settings`` construction)
# ===========================================================================


# Behavior 1 --- a negative threshold is rejected at construction (the fix)
def test_behavior_01_negative_one_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(auto_dispatch_min_score=-1.0)


# Behavior 2 --- any strictly-negative value is rejected (boundary just below 0)
def test_behavior_02_tiny_negative_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(auto_dispatch_min_score=-0.0001)


# Behavior 3 --- zero is a legitimate "auto-dispatch every scored goal" setting
#                (the bound is ``ge=0.0``, NOT ``gt=0.0``)
def test_behavior_03_zero_allowed() -> None:
    s = Settings(auto_dispatch_min_score=0.0)
    assert s.auto_dispatch_min_score == 0.0


# Behavior 4 --- the default value round-trips through explicit construction
def test_behavior_04_four_point_zero_allowed() -> None:
    s = Settings(auto_dispatch_min_score=4.0)
    assert s.auto_dispatch_min_score == 4.0


# Behavior 5 --- any non-negative float above the default is accepted (no upper bound)
def test_behavior_05_above_default_allowed_no_upper_bound() -> None:
    s = Settings(auto_dispatch_min_score=12.5)
    assert s.auto_dispatch_min_score == 12.5


# Behavior 6 --- the no-argument default is unchanged at 4.0
def test_behavior_06_default_unchanged() -> None:
    assert Settings().auto_dispatch_min_score == 4.0


# ===========================================================================
# Env-var-level (``Settings.from_env``, offline)
# ===========================================================================


# Behavior 7 --- a negative env override raises ValidationError via from_env
def test_behavior_07_from_env_negative_rejected(monkeypatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv(_ENV_VAR, "-1")
    with pytest.raises(ValidationError):
        Settings.from_env()


# Behavior 8 --- a zero env override succeeds with value 0.0
def test_behavior_08_from_env_zero_ok(monkeypatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv(_ENV_VAR, "0")
    s = Settings.from_env()
    assert s.auto_dispatch_min_score == 0.0


# Behavior 9 --- an in-range float env override still coerces & applies
def test_behavior_09_from_env_in_range_float_ok(monkeypatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv(_ENV_VAR, "2.5")
    s = Settings.from_env()
    assert s.auto_dispatch_min_score == 2.5


# Behavior 9b (regression guard) --- with the knob UNSET, from_env keeps the 4.0
# default; this proves the negative-rejection above is caused by the override,
# not by an unrelated ambient value.
def test_behavior_09b_from_env_unset_keeps_default(monkeypatch) -> None:
    _clear_env(monkeypatch)
    s = Settings.from_env()
    assert s.auto_dispatch_min_score == 4.0


# Behavior 10 --- ValidationError is a subclass of ValueError. This is what
# routes the fault into the CLI's ``except (LLMError, ValueError, OSError)``
# boundary in behaviors 11-12; asserting it explicitly means a future pydantic
# bump cannot silently break the CLI exit-1 contract.
def test_behavior_10_validation_error_is_value_error() -> None:
    assert issubclass(ValidationError, ValueError)


# ===========================================================================
# CLI-level (``pla`` / ``main([...])``, offline, exit codes)
# ===========================================================================


# Behavior 11 --- scan against an EXISTING directory with a negative threshold in
# the env fails fast at Settings construction: exit code exactly 1 (NOT 2, NOT
# 0), an ``error:``-prefixed message on stderr containing ``auto_dispatch_min_score``,
# no Python traceback, and nothing on stdout. No provider/scripted file is passed
# because settings are built before any LLM client.
def test_behavior_11_cli_negative_config_exits_one(tmp_path, capsys, monkeypatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv(_ENV_VAR, "-1")
    existing_dir = tmp_path  # pytest's tmp_path is a real, existing directory

    rc = main(["scan", "--workspace", str(existing_dir)])
    captured = capsys.readouterr()

    # Exit code is exactly 1 -- the reserved config/LLM/OS fault class.
    assert rc == 1, f"expected exit 1, got {rc}"
    assert rc != 2, "must not use the workspace-guard exit-2 class"
    assert rc != 0, "must not succeed"

    # Error goes to stderr, begins with 'error:', and names the offending field.
    err = captured.err
    assert err.strip() != "", "expected an error message on stderr"
    assert err.lstrip().startswith("error:"), f"stderr must begin with 'error:':\n{err}"
    assert _FIELD in err, f"stderr must name {_FIELD!r}:\n{err}"

    # No raw Python traceback leaks to the user (either stream).
    assert _TRACEBACK not in err, f"traceback leaked to stderr:\n{err}"
    assert _TRACEBACK not in captured.out, f"traceback leaked to stdout:\n{captured.out}"

    # Nothing printed to stdout: no ranked table, and the error is NOT on stdout.
    assert "DECISION" not in captured.out, f"unexpected ranked table on stdout:\n{captured.out}"
    assert "error:" not in captured.out, f"error message leaked to stdout:\n{captured.out}"

    # Prove this is the CONFIG validation fault firing fast, not a
    # provider/credential/scripted-file error (settings built before the client).
    low = err.lower()
    assert "api key" not in low, err
    assert "credential" not in low, err
    assert "exhausted" not in low, err
    assert "workspace not found" not in low, err


# Behavior 12 --- with the SAME negative threshold set, scan against a
# MISSING/non-dir path still hits the pre-existing front-door workspace guard
# FIRST: exit code exactly 2 (not 1), with ``error: workspace not found: <path>``
# on stderr. The guard runs before Settings construction, so its exit-2 contract
# is unchanged (no regression, no ordering change).
def test_behavior_12_cli_missing_workspace_still_exits_two(tmp_path, capsys, monkeypatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv(_ENV_VAR, "-1")
    missing = tmp_path / "no_such_workspace"
    assert not missing.exists()

    rc = main(["scan", "--workspace", str(missing)])
    captured = capsys.readouterr()

    # The workspace guard wins the ordering: exit 2, not the config exit 1.
    assert rc == 2, f"expected exit 2 from the workspace guard, got {rc}"
    assert rc != 1, "config validation must not preempt the front-door workspace guard"

    # The exact front-door message, unchanged.
    assert f"error: workspace not found: {missing}" in captured.err, captured.err
    # And crucially it is the WORKSPACE error, not the config error -- proving the
    # guard runs before Settings construction (no ordering regression).
    assert _FIELD not in captured.err, (
        f"config validation should not have run yet for a missing workspace:\n{captured.err}"
    )
    assert _TRACEBACK not in captured.err, captured.err


# Behavior 12b (companion) --- an existing regular FILE (not a directory) also
# trips the exit-2 workspace guard before config validation, mirroring the
# iter-10 is_dir() contract.
def test_behavior_12b_cli_non_dir_still_exits_two(tmp_path, capsys, monkeypatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv(_ENV_VAR, "-1")
    a_file = tmp_path / "not_a_dir.txt"
    a_file.write_text("i am a file, not a workspace\n", encoding="utf-8")

    rc = main(["scan", "--workspace", str(a_file)])
    captured = capsys.readouterr()

    assert rc == 2, f"expected exit 2 from the workspace guard, got {rc}"
    assert f"error: workspace not found: {a_file}" in captured.err, captured.err
    assert _FIELD not in captured.err, captured.err
