"""Black-box behavior tests for iteration 05.

Feature under test: a top-level ``pla --version`` flag that prints the single
source of truth (``proactive_loop.__version__``) and exits 0, plus a durable
version-consistency guard (``pyproject.toml [project].version`` == the module's
``__version__``) and the removal of the stale ``SPEC.md`` ``0.1.0`` literal so
the design contract can never re-drift from the code. This closes the only
remaining 30-second-falsifiable docs-vs-code contradiction on a public
portfolio repo.

ISOLATION CONTRACT (honored): these tests are written strictly against the
public contract -- this iteration's spec "Expected Behaviors", ``README.md``,
and ``SPEC.md`` -- and drive only the documented public surface: the ``pla``
CLI via ``proactive_loop.cli.main([...])`` and the public attribute
``proactive_loop.__version__``. No file under ``src/`` was read, no
engineer/reviewer notes were read, and no ``git diff`` was consulted. The
version literal is NEVER hard-coded in an assertion (it is imported), so the
tests survive future version bumps; ``pyproject.toml`` and ``SPEC.md`` are read
only as public artifacts. Every side-effecting test uses a fresh ``tmp_path``
state dir (never the repo's ``.pla_runs/``) and runs fully offline -- zero
network, zero API keys.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from proactive_loop import __version__ as PKG_VERSION
from proactive_loop.cli import main

REPO = Path(__file__).resolve().parents[1]
# Absolute paths (runner-location-independent) to the offline fixtures.
FIXTURE = REPO / "examples" / "fixture_workspace"
SCRIPT = REPO / "examples" / "scripted_responses.json"

_TRACEBACK = "Traceback (most recent call last)"
_SUBCOMMANDS = ("scan", "dispatch", "run", "resume", "runs")


# ---------------------------------------------------------------------------
# Behavior 1 -- `pla --version` prints and exits 0 (argparse `version` action)
# ---------------------------------------------------------------------------


def test_behavior1_version_flag_exits_zero(capsys):
    # The `version` action prints then raises SystemExit -- it does NOT return
    # an int through main(). Mirror the iter-02 SystemExit idiom.
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0, (
        f"`pla --version` must exit 0, got code {excinfo.value.code!r}"
    )
    # Sanity: something was actually printed.
    assert capsys.readouterr().out.strip(), "`--version` must print a version line"


# ---------------------------------------------------------------------------
# Behavior 2 -- the printed version is the single source of truth (stdout)
# ---------------------------------------------------------------------------


def test_behavior2_printed_version_is_single_source_of_truth(capsys):
    with pytest.raises(SystemExit):
        main(["--version"])
    captured = capsys.readouterr()

    # It goes to stdout, not stderr.
    assert captured.err.strip() == "", (
        f"`--version` must not write to stderr; got: {captured.err!r}"
    )
    out = captured.out
    lines = [ln for ln in out.splitlines() if ln.strip()]
    assert len(lines) == 1, f"`--version` must print a single line; got {lines!r}"
    line = lines[0]
    assert line.startswith("pla "), f"version line must start with 'pla '; got {line!r}"
    # NEVER hard-code the literal: assert against the imported source of truth so
    # this survives future bumps.
    assert PKG_VERSION in line, (
        f"version line must contain proactive_loop.__version__ ({PKG_VERSION!r}); "
        f"got {line!r}"
    )


# ---------------------------------------------------------------------------
# Behavior 3 -- `--version` short-circuits before the required subcommand
# ---------------------------------------------------------------------------


def test_behavior3_version_short_circuits_missing_subcommand(capsys):
    # No subcommand present: the version action must fire during parsing, BEFORE
    # argparse's required-subparser validation -- so no usage error, no
    # traceback.
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0, "no-subcommand `--version` must still exit 0"

    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "error:" not in combined, (
        f"`--version` must not emit a usage 'error:'; got: {combined!r}"
    )
    assert _TRACEBACK not in combined, (
        f"`--version` must not print a traceback; got: {combined!r}"
    )
    # It must NOT complain about a missing/required command argument.
    assert "required" not in captured.err, (
        f"`--version` must not raise the missing-command usage error; "
        f"got stderr: {captured.err!r}"
    )


# ---------------------------------------------------------------------------
# Behavior 4 -- the existing CLI surface is unchanged
# ---------------------------------------------------------------------------


def test_behavior4a_scan_still_returns_zero_and_writes_slate(tmp_path, capsys):
    out_path = tmp_path / "slate.json"
    rc = main([
        "scan",
        "--workspace", str(FIXTURE),
        "--provider", "scripted",
        "--scripted-responses", str(SCRIPT),
        "--state-dir", str(tmp_path / "scan_state"),
        "--out", str(out_path),
    ])
    assert rc == 0, f"scan must still exit 0, got {rc}"
    assert out_path.is_file(), "scan must still write a slate JSON artifact"


def test_behavior4b_runs_still_returns_zero(tmp_path, capsys):
    # `runs` on an existing but empty state dir is a complete, valid invocation
    # (unchanged from iter-04) and stays LLM-free.
    empty = tmp_path / "state"
    empty.mkdir()
    rc = main(["runs", "--state-dir", str(empty)])
    assert rc == 0, f"runs must still exit 0, got {rc}"


def test_behavior4c_no_args_still_errors_on_missing_subcommand(capsys):
    # With `--version` ABSENT, argparse behavior is unchanged: a missing required
    # subcommand is a usage error (nonzero SystemExit), NOT a success and NOT a
    # traceback.
    with pytest.raises(SystemExit) as excinfo:
        main([])
    code = excinfo.value.code
    assert code not in (0, None), (
        f"no-args invocation must stay a nonzero usage error, got {code!r}"
    )
    err = capsys.readouterr().err
    assert _TRACEBACK not in err, f"missing-subcommand must not traceback; got {err!r}"


# ---------------------------------------------------------------------------
# Behavior 5 -- `pla --help` advertises the flag AND all five subcommands
# ---------------------------------------------------------------------------


def test_behavior5_help_advertises_version_and_all_subcommands(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["--help"])
    assert excinfo.value.code == 0, "`--help` must exit 0"

    out = capsys.readouterr().out
    assert "--version" in out, (
        f"top-level help must list the --version option; got:\n{out}"
    )
    for sub in _SUBCOMMANDS:
        assert sub in out, (
            f"top-level help must still list the '{sub}' subcommand; got:\n{out}"
        )


# ---------------------------------------------------------------------------
# Behavior 6 -- version-consistency guard (durable anti-drift invariant)
# ---------------------------------------------------------------------------


def test_behavior6_pyproject_version_matches_module_version():
    # Locate pyproject.toml relative to this file (never CWD) so the guard is
    # runner-location-independent. tomllib requires binary mode.
    pyproject = REPO / "pyproject.toml"
    assert pyproject.is_file(), f"pyproject.toml must exist at {pyproject}"
    with pyproject.open("rb") as fh:
        data = tomllib.load(fh)
    declared = data["project"]["version"]
    assert declared == PKG_VERSION, (
        "version drift detected: pyproject.toml [project].version "
        f"({declared!r}) != proactive_loop.__version__ ({PKG_VERSION!r})"
    )


# ---------------------------------------------------------------------------
# Behavior 7 -- no stale version literal survives in the design contract
# ---------------------------------------------------------------------------


def test_behavior7_no_stale_0_1_0_literal_in_spec():
    spec = REPO / "SPEC.md"
    assert spec.is_file(), f"SPEC.md must exist at {spec}"
    text = spec.read_text(encoding="utf-8")
    assert "0.1.0" not in text, (
        "SPEC.md must contain NO hardcoded '0.1.0' literal (the single version "
        "source of truth is proactive_loop.__version__); found one still present"
    )


# ---------------------------------------------------------------------------
# Behavior 8 -- README documents the `pla --version` capability (doc-sync)
# ---------------------------------------------------------------------------


def test_behavior8_readme_documents_version_flag():
    readme = REPO / "README.md"
    assert readme.is_file(), f"README.md must exist at {readme}"
    text = readme.read_text(encoding="utf-8")
    assert "pla --version" in text, (
        "README.md must document the `pla --version` capability so the "
        "documented public surface stays in sync with the code"
    )
