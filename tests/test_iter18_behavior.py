"""Black-box behavior tests for iteration 18 --- the ``pla watch`` verb.

Feature under test: ``pla watch --workspace W [--interval S] [--max-scans N]`` ---
a new CLI verb that repeatedly runs the existing scan pipeline every
``--interval`` seconds via ``scheduler.run_periodic``, prefixing each tick with a
1-based ``=== scan <n> ===`` header and re-printing the ranked, gated slate
table. Unlike ``pla scan`` it is a LIVE monitor: it writes NO slate file and
prints no ``slate written:`` trailer. A missing/non-directory ``--workspace``
fails fast with ``error: workspace not found: <path>`` on stderr + exit 2 (the
verbatim iter-10 guard), before any client/collect and before consuming a
scripted response. ``--interval`` defaults to ``3600.0`` (float); ``--max-scans``
defaults to ``None`` (run until Ctrl-C). The handler explicitly returns 0 (never
``run_periodic``'s scan count).

ISOLATION CONTRACT (honored): these tests are written strictly against the
public contract for this iteration --- the spec's "Expected Behaviors"
(``pm.md``), ``README.md``, and ``SPEC.md`` sections 4.5/3 --- and drive ONLY
documented public surfaces: the ``pla`` CLI via ``proactive_loop.cli.main(argv)
-> int`` (its observable stdout / stderr / exit codes / on-disk artifacts) and
the public ``build_parser()`` for the parser-level default / shared-flag asserts
the spec authorizes. **No file under ``src/`` was read, no engineer/reviewer
notes were read, and no ``git diff`` was consulted.** Every test is fully
offline: zero network, zero API keys, driven through the scripted provider seam.
Synthetic ``tmp_path`` workspaces are used throughout (never the in-repo tree),
so the git_activity / working_tree / test_posture collectors cannot leak repo
state (iter-15 lesson), and no ``watch`` is ever invoked without a small
``--max-scans`` (an unbounded run would hang the suite).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from proactive_loop.cli import build_parser, main

_GUARD_MSG = "error: workspace not found"


# ---------------------------------------------------------------------------
# Helpers --- all black-box: build a synthetic workspace + scripted script,
# drive main(), read back stdout / stderr / exit code / on-disk artifacts.
# ---------------------------------------------------------------------------


def _workspace(tmp_path: Path) -> Path:
    """A minimal, real, synthetic workspace directory (one source file)."""
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "foo.py").write_text("print('hi')\n", encoding="utf-8")
    return ws


def _goal_dict(title: str, *, impact: float = 5.0, urgency: float = 5.0) -> dict:
    """One goal dict matching the documented synthesize JSON contract
    (examples/scripted_responses.json shape); ``learning`` is non-sensitive so
    it renders cleanly in the gated table."""
    return {
        "title": title,
        "rationale": "black-box watch probe",
        "category": "learning",
        "impact": impact,
        "urgency": urgency,
        "confidence": 1.0,
        "effort_weight": 1.0,
        "appropriate_now": True,
        "sources": ["foo.py"],
        "suggested_first_steps": ["do a thing"],
    }


def _script(tmp_path: Path, titles: list[str], *, name: str = "script.json") -> Path:
    """Write a scripted-responses file with one ``synthesize`` response per
    title (the scout consumes exactly one synthesize response per scan, so a
    ``--max-scans N`` run needs N of them). Each body is a 1-goal JSON array."""
    responses = [
        {"tag": "synthesize", "text": json.dumps([_goal_dict(t)])} for t in titles
    ]
    path = tmp_path / name
    path.write_text(json.dumps({"responses": responses}), encoding="utf-8")
    return path


def _run(argv: list[str], capsys) -> tuple[int, str, str]:
    """Drive main() and return (exit_code, stdout, stderr)."""
    rc = main(argv)
    captured = capsys.readouterr()
    return rc, captured.out, captured.err


def _watch_argv(
    ws: Path,
    script: Path,
    *,
    state_dir: Path | None = None,
    interval: str = "0",
    max_scans: str | None = "1",
) -> list[str]:
    argv = [
        "watch",
        "--workspace", str(ws),
        "--provider", "scripted",
        "--scripted-responses", str(script),
        "--interval", interval,
    ]
    if max_scans is not None:
        argv += ["--max-scans", max_scans]
    if state_dir is not None:
        argv += ["--state-dir", str(state_dir)]
    return argv


# ===========================================================================
# Behavior 1 --- Single bounded scan -> exit 0, exactly one slate printed.
# ===========================================================================


def test_b01_single_bounded_scan_exit0_one_slate(tmp_path, capsys):
    ws = _workspace(tmp_path)
    script = _script(tmp_path, ["Watch probe goal one"])

    rc, out, err = _run(
        _watch_argv(ws, script, state_dir=tmp_path / "state", interval="0", max_scans="1"),
        capsys,
    )

    assert rc == 0, f"single bounded scan must exit 0; stderr={err!r}"
    # The tick header appears exactly once, and there is no second scan.
    assert out.count("=== scan 1 ===") == 1, out
    assert "=== scan 2 ===" not in out, out
    # The ranked-slate table (same render `pla scan` uses) is printed for the tick.
    for col in ("DECISION", "SCORE", "CATEGORY", "TITLE"):
        assert col in out, f"table column {col!r} missing from watch output:\n{out}"
    # ...and at least one goal title from the script surfaces in that table.
    assert "Watch probe goal one" in out, out
    # A live monitor prints no persisted-slate trailer.
    assert "slate written:" not in out, out


# ===========================================================================
# Behavior 2 --- Multi-scan run re-ticks the loop -> N ordered slates.
# ===========================================================================


def test_b02_multi_scan_reticks_in_order(tmp_path, capsys):
    ws = _workspace(tmp_path)
    # Two synthesize responses -> two scans, distinct titles to prove each ran.
    script = _script(tmp_path, ["Watch probe goal one", "Watch probe goal two"])

    rc, out, err = _run(
        _watch_argv(ws, script, state_dir=tmp_path / "state", interval="0", max_scans="2"),
        capsys,
    )

    assert rc == 0, f"two-scan run must exit 0 (not the scan count); stderr={err!r}"
    # Both headers present, and scan 1 strictly precedes scan 2.
    assert "=== scan 1 ===" in out and "=== scan 2 ===" in out, out
    assert out.index("=== scan 1 ===") < out.index("=== scan 2 ==="), out
    # The header prefix occurs exactly twice -> the loop really re-ran the
    # whole scan pipeline, it did not just print once.
    assert out.count("=== scan ") == 2, out
    # A full slate table render follows EACH header (one DECISION header per tick).
    assert out.count("DECISION") == 2, out
    # Each scan surfaced its own goal (proves the pipeline re-ran per tick).
    assert "Watch probe goal one" in out and "Watch probe goal two" in out, out
    # Still a live monitor: no persisted-slate trailer.
    assert "slate written:" not in out, out


# ===========================================================================
# Behavior 3 --- watch writes NO slate file (live view only).
# ===========================================================================


def test_b03_watch_writes_no_slate_file(tmp_path, capsys):
    ws = _workspace(tmp_path)
    script = _script(tmp_path, ["Watch probe goal one"])
    state_dir = tmp_path / "fresh_state"  # deliberately fresh + empty (never created)

    rc, out, err = _run(
        _watch_argv(ws, script, state_dir=state_dir, interval="0", max_scans="1"),
        capsys,
    )

    assert rc == 0, f"stderr={err!r}"
    # No file named slate.json exists anywhere under the state dir (recursively).
    slates = list(state_dir.rglob("slate.json")) if state_dir.exists() else []
    assert slates == [], f"watch must not persist a slate; found {slates}"
    # And it never prints the scan-only trailer.
    assert "slate written:" not in out, out


# ===========================================================================
# Behavior 4 --- Missing / non-directory --workspace fails fast -> exit 2.
# ===========================================================================


def test_b04_missing_workspace_fails_fast(tmp_path, capsys):
    missing = tmp_path / "no_such_workspace"
    assert not missing.exists()
    script = _script(tmp_path, ["Watch probe goal one"])

    rc, out, err = _run(
        # No --state-dir / --interval needed: the guard fires before all of that.
        [
            "watch",
            "--workspace", str(missing),
            "--provider", "scripted",
            "--scripted-responses", str(script),
            "--max-scans", "1",
        ],
        capsys,
    )

    assert rc == 2, f"missing workspace must exit 2; got {rc}"
    assert err.strip() == f"{_GUARD_MSG}: {missing}", repr(err)
    # Fires before any synthesis -> nothing rendered to stdout.
    assert out == "", repr(out)


def test_b04_file_as_workspace_fails_fast(tmp_path, capsys):
    a_file = tmp_path / "not_a_dir.txt"
    a_file.write_text("i am a file, not a workspace\n", encoding="utf-8")
    script = _script(tmp_path, ["Watch probe goal one"])

    rc, out, err = _run(
        [
            "watch",
            "--workspace", str(a_file),
            "--provider", "scripted",
            "--scripted-responses", str(script),
            "--max-scans", "1",
        ],
        capsys,
    )

    # An existing regular file is treated identically to a missing dir.
    assert rc == 2, f"file-as-workspace must exit 2; got {rc}"
    assert err.strip() == f"{_GUARD_MSG}: {a_file}", repr(err)
    assert out == "", repr(out)


# ===========================================================================
# Behavior 5 --- Parser defaults: --max-scans -> None, --interval -> 3600.0,
# and the watch subcommand binds its own handler (verified structurally, never
# by running an unbounded loop).
# ===========================================================================


def test_b05_parser_defaults_unbounded_and_hourly():
    parser = build_parser()
    args = parser.parse_args(["watch", "--workspace", ".", "--provider", "scripted"])

    # Omitted --max-scans -> unbounded (run until interrupted).
    assert args.max_scans is None
    # Omitted --interval -> hourly, as a float.
    assert args.interval == 3600.0
    assert isinstance(args.interval, float)
    # watch binds a callable handler...
    assert hasattr(args, "func") and callable(args.func)
    # ...and it is a DISTINCT handler from `scan` (own entry point, black-box:
    # compares the bound funcs rather than hardcoding a private name).
    scan_args = parser.parse_args(["scan", "--workspace", "."])
    assert args.func is not scan_args.func


# ===========================================================================
# Behavior 6 --- Invalid numeric argument is an argparse usage error -> exit 2.
# ===========================================================================


def test_b06_invalid_max_scans_is_argparse_systemexit_2(tmp_path):
    ws = _workspace(tmp_path)
    script = _script(tmp_path, ["Watch probe goal one"])

    with pytest.raises(SystemExit) as excinfo:
        main([
            "watch",
            "--workspace", str(ws),
            "--max-scans", "not-an-int",
            "--provider", "scripted",
            "--scripted-responses", str(script),
        ])
    # argparse rejects the non-int at parse time, outside main()'s try-boundary.
    assert excinfo.value.code == 2


# ===========================================================================
# Behavior 7 --- watch inherits the shared global flags (provider / scripted-
# responses / state-dir) from the globals_ parent parser.
# ===========================================================================


def test_b07_watch_inherits_shared_global_flags():
    parser = build_parser()

    # provider + state-dir populate; scripted_responses is present (default None).
    a = parser.parse_args(
        ["watch", "--workspace", ".", "--state-dir", "/x", "--provider", "scripted"]
    )
    assert a.provider == "scripted"
    assert a.state_dir == "/x"
    assert hasattr(a, "scripted_responses")
    assert a.scripted_responses is None

    # And --scripted-responses is accepted and captured when supplied.
    b = parser.parse_args(
        [
            "watch", "--workspace", ".",
            "--provider", "scripted",
            "--scripted-responses", "s.json",
            "--state-dir", "/y",
        ]
    )
    assert b.provider == "scripted"
    assert b.scripted_responses == "s.json"
    assert b.state_dir == "/y"


# ===========================================================================
# Acceptance-criterion coverage --- `pla watch --help` self-documents its flags,
# and the top-level `--help` lists the verb (SystemExit(0), argparse convention).
# ===========================================================================


def test_ac_watch_help_lists_flags(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["watch", "--help"])
    assert excinfo.value.code == 0
    help_out = capsys.readouterr().out
    for flag in ("--workspace", "--interval", "--max-scans"):
        assert flag in help_out, f"watch --help must advertise {flag}; got:\n{help_out}"


def test_ac_top_level_help_lists_watch(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["--help"])
    assert excinfo.value.code == 0
    help_out = capsys.readouterr().out
    assert "watch" in help_out, f"`watch` must appear in --help; got:\n{help_out}"
