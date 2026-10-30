"""Black-box behavior tests for a re-runnable ``make demo`` (foundry iter 291).

Defect under test: the ``demo:`` recipe traced ``.pla_runs/run-*/`` -- a shell glob that
expands to 2 args as soon as a second ``run-<id>`` dir exists, so the SECOND ``make demo`` in
one checkout exited 2 (``unrecognized arguments``). The fix: ``trace`` reads the exact run dir
THIS run dispatched into from ``dispatched.run_dir`` in ``.pla_runs/run.json``.

WHAT THIS MODULE GRADES (TWO collected items -- ``make readme-headroom`` read
``binding_headroom=11`` before this module and the spec caps it at <= 3 items):
(1) EB3-4, static: the ``demo:`` recipe passes no glob to ``--run-dir``, its ``trace`` line
reads ``dispatched.run_dir`` through the same ``$$(uv run python -c "import json; ...")`` idiom
as the ``dispatch`` line's ``goal_id``, the command order is unchanged with
``examples/check_run.py`` LAST, no ``rm -rf`` was added, and a WHY comment above ``demo:``
names the glob growing to 2 args;
(2) EB1-2, in-process: two ``pla run --json`` calls into ONE tmp state dir both exit 0 and
leave 2 ``run-*`` dirs (the state a glob cannot survive), and ``trace --run-dir`` on the
SECOND run's ``dispatched.run_dir`` exits 0 with a non-empty JSON array that
``examples/check_trace.py`` grades 0.

Fully offline and deterministic: scripted provider, ``tmp_path`` state, a fixture-workspace
COPY whose mtimes are pinned with ``os.utime`` (never ambient mtimes or ``.pla_runs``), and
``make demo`` is never shelled out to.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Final

import pytest

from proactive_loop.cli import main

REPO: Final[Path] = Path(__file__).resolve().parents[1]
MAKEFILE: Final[Path] = REPO / "Makefile"
EXAMPLES: Final[Path] = REPO / "examples"

#: The demo recipe's command heads, in order -- byte-for-byte the pre-fix sequence.
EXPECTED_ORDER: Final[tuple[str, ...]] = (
    "mkdir -p .pla_runs",
    "uv run pla run",
    "uv run pla explain",
    "uv run python examples/check_autonomy.py",
    "uv run pla trace",
    "uv run python examples/check_trace.py",
    "uv run pla runs",
    "uv run python examples/check_runs_summary.py",
    "uv run pla dispatch",
    "uv run python examples/check_dispatch.py",
    "uv run python examples/check_run.py",
)


def _demo_block() -> tuple[list[str], list[str]]:
    """Return (comment lines directly above ``demo:``, logical recipe commands)."""
    lines = MAKEFILE.read_text(encoding="utf-8").splitlines()
    idx = lines.index("demo:")
    comments: list[str] = []
    j = idx - 1
    while j >= 0 and (lines[j].startswith("#") or lines[j] == ""):
        comments.insert(0, lines[j])
        j -= 1
    commands: list[str] = []
    buf = ""
    for raw in lines[idx + 1 :]:
        if not raw.startswith("\t"):
            break
        part = raw.strip()
        if part.endswith("\\"):
            buf += part[:-1].strip() + " "
            continue
        commands.append(buf + part)
        buf = ""
    return comments, commands


def test_b1_demo_recipe_reads_run_dir_from_run_json_not_a_glob() -> None:
    comments, commands = _demo_block()
    assert commands, "demo: recipe parsed empty"

    # EB3: no --run-dir value carries a shell glob.
    for cmd in commands:
        for m in re.finditer(r"--run-dir\s+(\S+)", cmd):
            assert "*" not in m.group(1), f"glob passed to --run-dir: {cmd!r}"
    trace = [c for c in commands if c.startswith("uv run pla trace")]
    assert len(trace) == 1, trace
    assert "['dispatched']['run_dir']" in trace[0], trace[0]
    assert "open('.pla_runs/run.json')" in trace[0], trace[0]
    assert '"$$(uv run python -c "import json;' in trace[0], trace[0]
    assert "*" not in trace[0], trace[0]
    dispatch = [c for c in commands if c.startswith("uv run pla dispatch")]
    assert len(dispatch) == 1 and "['dispatched']['goal_id']" in dispatch[0], dispatch

    # EB4: same commands, same order, check_run.py LAST, no cleanup added.
    assert len(commands) == len(EXPECTED_ORDER), commands
    for cmd, head in zip(commands, EXPECTED_ORDER, strict=True):
        assert cmd == head or cmd.startswith(head + " "), (cmd, head)
    assert commands[-1] == "uv run python examples/check_run.py < .pla_runs/run.json"
    assert not any("rm -rf" in c or "rm " in c for c in commands), commands
    assert trace[0].endswith("--json > .pla_runs/trace.json"), trace[0]

    # EB4: a WHY comment above demo: names the glob growing to 2 args.
    why = " ".join(comments).lower()
    assert "glob" in why and "2 args" in why and "run_dir" in why, why


def _pin_mtimes(root: Path, when: float) -> None:
    for path in [root, *root.rglob("*")]:
        os.utime(path, (when, when))


def _call(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    capsys.readouterr()
    try:
        rc = main(argv)
    except SystemExit as exc:  # argparse paths
        rc = int(exc.code or 0)
    return int(rc or 0), capsys.readouterr().out


def test_b2_second_run_accumulates_and_its_run_dir_traces_green(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = tmp_path / "ws"
    shutil.copytree(EXAMPLES / "fixture_workspace", workspace)
    _pin_mtimes(workspace, time.time() - 86_400)
    state = tmp_path / "state"
    state.mkdir()
    argv = [
        "run",
        "--workspace", str(workspace),
        "--provider", "scripted",
        "--scripted-responses", str(EXAMPLES / "scripted_responses.json"),
        "--state-dir", str(state),
        "--json",
    ]

    docs: list[dict[str, object]] = []
    for _ in range(2):  # EB1: a re-run into the SAME state dir, no cleaning between
        rc, out = _call(argv, capsys)
        assert rc == 0, out
        docs.append(json.loads(out))
    run_dirs = sorted(p for p in state.iterdir() if p.is_dir() and p.name.startswith("run-"))
    assert len(run_dirs) == 2, run_dirs  # the exact state a `run-*/` glob expands to 2 args on

    dispatched = docs[-1]["dispatched"]
    assert isinstance(dispatched, dict)
    run_dir = Path(str(dispatched["run_dir"]))
    if not run_dir.is_absolute():
        run_dir = Path.cwd() / run_dir
    assert run_dir.resolve() in {p.resolve() for p in run_dirs}, (run_dir, run_dirs)

    # EB2: trace on THAT dir is a non-empty array, deterministic, and the demo's grader takes it.
    rc, trace_out = _call(["trace", "--run-dir", str(run_dir), "--json"], capsys)
    assert rc == 0, trace_out
    trace = json.loads(trace_out)
    assert isinstance(trace, list) and trace, trace_out
    rc2, again = _call(["trace", "--run-dir", str(run_dir), "--json"], capsys)
    assert (rc2, again) == (0, trace_out)
    graded = subprocess.run(
        [sys.executable, str(EXAMPLES / "check_trace.py")],
        input=trace_out, capture_output=True, text=True, cwd=REPO, check=False, timeout=120,
    )
    assert graded.returncode == 0, graded.stdout + graded.stderr

    # The pre-fix invocation really breaks here: two dirs are two positional args.
    rc_glob, _ = _call(["trace", "--run-dir", *[str(p) for p in run_dirs], "--json"], capsys)
    assert rc_glob == 2
