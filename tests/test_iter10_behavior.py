"""Black-box behavior tests for iteration 10.

Feature under test: a **front-door workspace guard** on the two most-used verbs,
``pla scan`` and ``pla run``. A missing or non-directory ``--workspace`` must
fail fast with ``error: workspace not found: <path>`` on stderr and exit code
**2**, instead of silently degrading every collector to ``[]`` and producing an
empty slate with exit 0. This closes a genuine self-inconsistency: ``dispatch``,
``resume``, ``runs`` and ``trace`` already reject bad input paths with exit 2;
``scan``/``run`` were the exceptions.

ISOLATION CONTRACT (honored): these tests are written strictly against the
public contract for this iteration -- the spec's "Expected Behaviors",
``README.md``, and ``SPEC.md`` section 4.5 -- and drive ONLY the documented
public entrypoint ``proactive_loop.cli.main(argv) -> int`` with captured
stdout/stderr and observed exit codes / on-disk artifacts. No file under
``src/`` was read, the engineer's and reviewer's notes were not read, and no
``git diff`` was consulted. The valid-path fixtures reused here
(``examples/fixture_workspace`` + ``examples/scripted_responses.json``) are the
same public artifacts the existing ``tests/test_cli_integration.py`` drives.
Every test runs fully offline: zero network, zero API keys. Behaviors that
prove a *bad* path exercise the ``scripted`` provider only for realism, and the
fast-fail behavior (B4) deliberately uses the ``anthropic`` provider with NO key
and NO scripted file to prove the guard short-circuits before any provider work.
"""

from __future__ import annotations

from pathlib import Path

from proactive_loop.cli import main

REPO = Path(__file__).resolve().parents[1]
# Runner-location-independent paths to the public offline demo artifacts.
FIXTURE = REPO / "examples" / "fixture_workspace"
SCRIPT = REPO / "examples" / "scripted_responses.json"

_MSG = "error: workspace not found"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _missing(tmp_path: Path) -> Path:
    """A path under tmp_path that is guaranteed not to exist."""
    return tmp_path / "no_such_workspace"


def _scan_bad(ws: Path, tmp_path: Path, *, out: Path | None = None) -> list[str]:
    """`scan` argv against a bad workspace, wired through the scripted provider."""
    out = out if out is not None else (tmp_path / "slate.json")
    return [
        "scan",
        "--workspace", str(ws),
        "--provider", "scripted",
        "--scripted-responses", str(SCRIPT),
        "--state-dir", str(tmp_path / "state"),
        "--out", str(out),
    ]


def _run_bad(ws: Path, tmp_path: Path) -> list[str]:
    """`run` argv against a bad workspace, wired through the scripted provider."""
    return [
        "run",
        "--workspace", str(ws),
        "--provider", "scripted",
        "--scripted-responses", str(SCRIPT),
        "--state-dir", str(tmp_path / "state"),
    ]


# ---------------------------------------------------------------------------
# Behavior 1 -- `scan` rejects a missing workspace
# ---------------------------------------------------------------------------


def test_b1_scan_rejects_missing_workspace(tmp_path, capsys):
    missing = _missing(tmp_path)
    out_path = tmp_path / "slate.json"

    rc = main(_scan_bad(missing, tmp_path, out=out_path))
    captured = capsys.readouterr()

    assert rc == 2
    assert f"{_MSG}: {missing}" in captured.err
    # No ranked table printed to stdout...
    assert "DECISION" not in captured.out
    # ...and no slate JSON file written to disk.
    assert not out_path.exists()


# ---------------------------------------------------------------------------
# Behavior 2 -- `run` rejects a missing workspace
# ---------------------------------------------------------------------------


def test_b2_run_rejects_missing_workspace(tmp_path, capsys):
    missing = _missing(tmp_path)
    state_dir = tmp_path / "state"

    rc = main(_run_bad(missing, tmp_path))
    captured = capsys.readouterr()

    assert rc == 2
    assert f"{_MSG}: {missing}" in captured.err
    # No slate JSON written and no run-* directory created under the state dir.
    assert not (state_dir / "slate.json").exists()
    assert list(state_dir.glob("run-*")) == []


# ---------------------------------------------------------------------------
# Behavior 3 -- an existing regular file (not a directory) is also rejected
# ---------------------------------------------------------------------------


def test_b3_scan_rejects_regular_file(tmp_path, capsys):
    a_file = tmp_path / "not_a_dir.txt"
    a_file.write_text("i am a file, not a workspace\n", encoding="utf-8")

    rc = main(_scan_bad(a_file, tmp_path))
    captured = capsys.readouterr()

    # Same single is_dir() guard covers both the missing and not-a-dir cases.
    assert rc == 2
    assert f"{_MSG}: {a_file}" in captured.err
    assert "DECISION" not in captured.out


def test_b3_run_rejects_regular_file(tmp_path, capsys):
    a_file = tmp_path / "not_a_dir.txt"
    a_file.write_text("i am a file, not a workspace\n", encoding="utf-8")

    rc = main(_run_bad(a_file, tmp_path))
    captured = capsys.readouterr()

    assert rc == 2
    assert f"{_MSG}: {a_file}" in captured.err


# ---------------------------------------------------------------------------
# Behavior 4 -- fast-fail BEFORE any client/provider construction
# ---------------------------------------------------------------------------
# Uses a non-scripted provider with NO API key and NO scripted-responses file.
# If the guard did not fire first, we'd see a provider-import / credential /
# exhausted-script error instead of the workspace error. Runs fully offline.


def test_b4_scan_fastfails_before_client(tmp_path, capsys):
    missing = _missing(tmp_path)

    rc = main(["scan", "--workspace", str(missing), "--provider", "anthropic"])
    captured = capsys.readouterr()

    assert rc == 2
    assert _MSG in captured.err
    # Prove it is the WORKSPACE error, not a provider/credential/script error.
    low = captured.err.lower()
    assert "api key" not in low
    assert "credential" not in low
    assert "exhausted" not in low


def test_b4_run_fastfails_before_client(tmp_path, capsys):
    missing = _missing(tmp_path)

    rc = main(["run", "--workspace", str(missing), "--provider", "anthropic"])
    captured = capsys.readouterr()

    assert rc == 2
    assert _MSG in captured.err
    low = captured.err.lower()
    assert "api key" not in low
    assert "credential" not in low
    assert "exhausted" not in low


# ---------------------------------------------------------------------------
# Behavior 5 -- the error goes to stderr, NOT stdout
# ---------------------------------------------------------------------------


def test_b5_error_is_on_stderr_not_stdout(tmp_path, capsys):
    missing = _missing(tmp_path)

    # scan (scripted) ...
    main(_scan_bad(missing, tmp_path))
    scan_out = capsys.readouterr().out
    assert _MSG not in scan_out

    # ... run (scripted) ...
    main(_run_bad(missing, tmp_path))
    run_out = capsys.readouterr().out
    assert _MSG not in run_out

    # ... and the fast-fail (anthropic) path too.
    main(["scan", "--workspace", str(missing), "--provider", "anthropic"])
    fastfail_out = capsys.readouterr().out
    assert _MSG not in fastfail_out


# ---------------------------------------------------------------------------
# Behavior 6 -- exit code is exactly 2, never 1
# ---------------------------------------------------------------------------


def test_b6_exit_code_is_exactly_two_never_one(tmp_path, capsys):
    missing = _missing(tmp_path)
    a_file = tmp_path / "f.txt"
    a_file.write_text("x\n", encoding="utf-8")

    for argv in (
        _scan_bad(missing, tmp_path),
        _run_bad(missing, tmp_path),
        _scan_bad(a_file, tmp_path),
        ["scan", "--workspace", str(missing), "--provider", "anthropic"],
        ["run", "--workspace", str(missing), "--provider", "anthropic"],
    ):
        capsys.readouterr()  # drain
        rc = main(argv)
        assert rc == 2, f"argv {argv!r} did not exit 2"
        assert rc != 1, f"argv {argv!r} used the reserved exit-1 class"


# ---------------------------------------------------------------------------
# Behavior 7 -- a VALID workspace is unaffected (backward compatibility)
# ---------------------------------------------------------------------------


def test_b7_scan_valid_dir_unaffected(tmp_path, capsys):
    """`scan` against a real directory still exits 0, prints the table, writes the slate."""
    out_path = tmp_path / "slate.json"
    rc = main([
        "scan",
        "--workspace", str(FIXTURE),
        "--provider", "scripted",
        "--scripted-responses", str(SCRIPT),
        "--state-dir", str(tmp_path / "state"),
        "--out", str(out_path),
    ])
    captured = capsys.readouterr()

    assert rc == 0
    assert "DECISION" in captured.out           # ranked table printed
    assert out_path.is_file()                    # slate JSON written
    assert _MSG not in captured.err              # no false rejection


def test_b7_scan_valid_fresh_empty_dir_unaffected(tmp_path, capsys):
    """Any real directory passes the guard -- even an empty fresh tmp dir."""
    ws = tmp_path / "fresh_ws"
    ws.mkdir()
    out_path = tmp_path / "slate.json"
    rc = main([
        "scan",
        "--workspace", str(ws),
        "--provider", "scripted",
        "--scripted-responses", str(SCRIPT),
        "--state-dir", str(tmp_path / "state"),
        "--out", str(out_path),
    ])
    captured = capsys.readouterr()

    assert rc == 0
    assert out_path.is_file()
    assert _MSG not in captured.err


def test_b7_run_valid_dir_auto_dispatches(tmp_path, capsys):
    """`run` against the fixture still exits 0 and auto-dispatches the top AUTO goal."""
    state_dir = tmp_path / "state"
    rc = main([
        "run",
        "--workspace", str(FIXTURE),
        "--provider", "scripted",
        "--scripted-responses", str(SCRIPT),
        "--state-dir", str(state_dir),
    ])
    captured = capsys.readouterr()

    assert rc == 0
    assert _MSG not in captured.err
    # The slate was written and exactly one AUTO goal was dispatched, as before.
    assert (state_dir / "slate.json").is_file()
    run_dirs = list(state_dir.glob("run-*"))
    assert len(run_dirs) == 1, "run must still auto-dispatch exactly the top AUTO goal"
