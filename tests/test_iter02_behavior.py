"""Black-box behavior tests for iteration 02.

Feature under test: a narrow top-level error boundary in ``cli.py:main()`` so
every *foreseeable* operator/environment fault becomes a single ``error:
<message>`` line on **stderr** with exit code ``1`` instead of a raw Python
traceback -- while the existing not-found / refusal exit codes (2 / 3 / 4), the
success path (0), and interpreter control-flow exceptions (``SystemExit`` from
argparse ``--help`` / usage errors) are all left untouched. This backs the
product's "resilient by design" thesis on its loudest public surface (the CLI).

ISOLATION: these tests are written strictly against the public contract -- the
iteration spec's "Expected Behaviors", ``README.md``, and ``SPEC.md`` (§4.5) --
and exercise only the documented public entrypoint
``proactive_loop.cli.main(argv) -> int`` (equivalently the ``pla`` console
script), asserting observable exit codes and captured stderr. No ``src/``
internals, no engineer/reviewer notes, and no ``git diff`` were consulted.
Everything runs fully offline via the scripted-provider seam -- zero network,
zero API keys.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from proactive_loop.cli import main

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "examples" / "fixture_workspace"
SCRIPT = REPO / "examples" / "scripted_responses.json"

_TRACEBACK = "Traceback (most recent call last)"


def _assert_legible_fault(rc: int, err: str) -> None:
    """The shared contract of behaviors 1-6: exit 1, an ``error:`` line, no dump."""
    assert rc == 1, f"a foreseeable fault must exit 1, got {rc}"
    assert "error:" in err, f"stderr must carry an 'error:' line, got: {err!r}"
    assert _TRACEBACK not in err, f"stderr must NOT contain a traceback, got: {err!r}"


# ---------------------------------------------------------------------------
# Behavior 1 -- unknown provider is legible, not a traceback
# ---------------------------------------------------------------------------


def test_behavior1_unknown_provider_is_legible(tmp_path, capsys) -> None:
    rc = main([
        "scan",
        "--workspace", str(FIXTURE),
        "--provider", "bogus",
        "--state-dir", str(tmp_path),
    ])
    err = capsys.readouterr().err
    _assert_legible_fault(rc, err)
    # The message must be self-service: it names a valid provider.
    assert "scripted" in err, f"error should mention a valid provider, got: {err!r}"


# ---------------------------------------------------------------------------
# Behavior 2 -- missing scripted-responses file is legible
# ---------------------------------------------------------------------------


def test_behavior2_missing_scripted_responses_file_is_legible(tmp_path, capsys) -> None:
    missing = tmp_path / "nope.json"
    assert not missing.exists()
    rc = main([
        "scan",
        "--workspace", str(FIXTURE),
        "--provider", "scripted",
        "--scripted-responses", str(missing),
        "--state-dir", str(tmp_path),
    ])
    _assert_legible_fault(rc, capsys.readouterr().err)


# ---------------------------------------------------------------------------
# Behavior 3 -- malformed scripted-responses JSON is legible
# ---------------------------------------------------------------------------


def test_behavior3_malformed_scripted_responses_json_is_legible(tmp_path, capsys) -> None:
    bad = tmp_path / "bad_script.json"
    bad.write_text("{ not json")  # invalid JSON -> json.JSONDecodeError (a ValueError)
    rc = main([
        "scan",
        "--workspace", str(FIXTURE),
        "--provider", "scripted",
        "--scripted-responses", str(bad),
        "--state-dir", str(tmp_path),
    ])
    _assert_legible_fault(rc, capsys.readouterr().err)


# ---------------------------------------------------------------------------
# Behavior 4 -- corrupted slate JSON on dispatch is legible
# ---------------------------------------------------------------------------


def test_behavior4_corrupted_slate_on_dispatch_is_legible(tmp_path, capsys) -> None:
    bad_slate = tmp_path / "slate.json"
    bad_slate.write_text("{ not json")  # -> pydantic/json ValueError at model_validate_json
    rc = main([
        "dispatch",
        "--slate", str(bad_slate),
        "--goal-id", "any-id",
    ])
    _assert_legible_fault(rc, capsys.readouterr().err)


# ---------------------------------------------------------------------------
# Behavior 5 -- a model-boundary failure during a scan is legible
# (empty script = valid but exhausted; synthesize raises an LLMError, not retried)
# ---------------------------------------------------------------------------


def test_behavior5_model_boundary_failure_during_scan_is_legible(tmp_path, capsys) -> None:
    exhausted = tmp_path / "empty_script.json"
    exhausted.write_text("[]")  # valid JSON, but no responses -> ScriptExhaustedError (LLMError)
    rc = main([
        "scan",
        "--workspace", str(FIXTURE),
        "--provider", "scripted",
        "--scripted-responses", str(exhausted),
        "--state-dir", str(tmp_path),
    ])
    _assert_legible_fault(rc, capsys.readouterr().err)


# ---------------------------------------------------------------------------
# Behavior 6 -- an unconfigured scripted provider during a scan is legible
# ---------------------------------------------------------------------------


def test_behavior6_unconfigured_scripted_provider_is_legible(tmp_path, capsys, monkeypatch) -> None:
    # No path via flag and none via env: the scripted client fails at first call.
    monkeypatch.delenv("PLA_SCRIPTED_RESPONSES", raising=False)
    rc = main([
        "scan",
        "--workspace", str(FIXTURE),
        "--provider", "scripted",
        "--state-dir", str(tmp_path),
    ])
    _assert_legible_fault(rc, capsys.readouterr().err)


# ---------------------------------------------------------------------------
# Behavior 7 -- happy path is unchanged (the boundary must not break success)
# ---------------------------------------------------------------------------


def test_behavior7_happy_path_run_still_succeeds(tmp_path) -> None:
    state_dir = tmp_path / "pla_runs"
    rc = main([
        "run",
        "--workspace", str(FIXTURE),
        "--provider", "scripted",
        "--scripted-responses", str(SCRIPT),
        "--state-dir", str(state_dir),
    ])
    assert rc == 0, "the demo run must still exit 0 with the boundary in place"
    # The success side effects the demo promises are intact.
    assert (state_dir / "slate.json").is_file()
    assert len(list(state_dir.glob("run-*"))) == 1


# ---------------------------------------------------------------------------
# Behavior 8 -- existing not-found exit codes are preserved (NOT collapsed to 1)
# ---------------------------------------------------------------------------


def _write_valid_slate(tmp_path) -> Path:
    """Produce a real slate via `scan` and return its path (exit 0 expected)."""
    slate_path = tmp_path / "slate.json"
    rc = main([
        "scan",
        "--workspace", str(FIXTURE),
        "--provider", "scripted",
        "--scripted-responses", str(SCRIPT),
        "--state-dir", str(tmp_path / "scan_state"),
        "--out", str(slate_path),
    ])
    assert rc == 0
    assert slate_path.is_file()
    return slate_path


def test_behavior8a_unknown_goal_id_stays_exit_2(tmp_path, capsys) -> None:
    slate_path = _write_valid_slate(tmp_path)
    capsys.readouterr()  # drop the scan's output
    rc = main([
        "dispatch",
        "--slate", str(slate_path),
        "--goal-id", "does-not-exist",
        "--provider", "scripted",
        "--scripted-responses", str(SCRIPT),
        "--state-dir", str(tmp_path / "state"),
    ])
    assert rc == 2, f"unknown goal-id must stay exit 2 (not collapse to 1), got {rc}"
    err = capsys.readouterr().err
    # The boundary must not turn this into a traceback either.
    assert _TRACEBACK not in err


def test_behavior8b_resume_no_checkpoint_stays_exit_2(tmp_path, capsys) -> None:
    empty_run_dir = tmp_path / "empty_run"
    empty_run_dir.mkdir()
    rc = main([
        "resume",
        "--run-dir", str(empty_run_dir),
        "--provider", "scripted",
        "--scripted-responses", str(SCRIPT),
        "--state-dir", str(tmp_path / "state"),
    ])
    assert rc == 2, f"resume with no checkpoint must stay exit 2 (not 1), got {rc}"
    assert _TRACEBACK not in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Behavior 9 -- interpreter/CLI control-flow exceptions are NOT swallowed
# ---------------------------------------------------------------------------


def test_behavior9a_help_raises_systemexit_zero(capsys) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--help"])
    # argparse prints help and exits 0; the boundary must NOT convert this to return 1.
    assert excinfo.value.code == 0


def test_behavior9b_unknown_subcommand_raises_systemexit_nonzero(capsys) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["no-such-subcommand"])
    # argparse usage error exits nonzero; the boundary must NOT catch SystemExit.
    code = excinfo.value.code
    assert code not in (0, None), f"usage error must exit nonzero, got {code!r}"
