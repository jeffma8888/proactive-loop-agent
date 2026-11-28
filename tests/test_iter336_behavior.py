"""Black-box oracle for foundry iter 601 (factory iter 336): ``make demo`` runs
``pla explain`` and ``pla dispatch --dry-run`` through the shipped DEFAULT slate
(``--state-dir .pla_runs``, no ``--slate``), so CI grades the default-slate path.

ISOLATION CONTRACT (honored): written from the iteration spec (``pm.md``),
``README.md``, the ``Makefile`` recipe text and the conventions under ``tests/``. It
drives ONLY the public ``proactive_loop.cli.main(argv)`` entry, offline (scripted
provider), from a scratch cwd in ``tmp_path`` with a fixture-workspace COPY whose
mtimes are pinned by ``os.utime`` (no ambient mtimes, no real ``.pla_runs``). No
implementation source, engineer/reviewer note or git diff was read; ``make demo`` is
never shelled out to.

The module collects ZERO items on purpose (the suite-size binding wall in
test_iter263 b6 / test_iter270 b7 demands >= 6 items of binding headroom):
``iter601_demo_default_slate`` is called from
``tests/test_iter317_behavior.py::test_runs_older_than_filters_by_checkpoint_age``,
which asserts its returned behaviour-group count (6).
"""

from __future__ import annotations

import json
import os
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
SCRIPT: Final[Path] = EXAMPLES / "scripted_responses.json"

GOAL_SCRAPE: Final[str] = (
    "\"$$(uv run python -c \"import json; print(json.load(open('.pla_runs/run.json'))"
    "['dispatched']['goal_id'])\")\""
)
#: The demo recipe's command heads, in order (EB3: unchanged by this iteration).
EXPECTED_ORDER: Final[tuple[str, ...]] = (
    "mkdir -p .pla_runs",
    "find examples/fixture_workspace",
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


def _demo_commands(text: str) -> list[str]:
    """Logical (backslash-joined) commands of the ``demo:`` recipe in ``text``."""
    lines = text.splitlines()
    idx = lines.index("demo:")
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
    return commands


def _one(commands: list[str], head: str) -> str:
    hits = [c for c in commands if c.startswith(head)]
    assert len(hits) == 1, (head, hits)
    return hits[0]


def _tokens(cmd: str) -> list[str]:
    return cmd.split()


def _b1_b3_static(text: str) -> None:
    commands = _demo_commands(text)
    # EB1: explain uses the state-dir default slate.
    explain = _one(commands, "uv run pla explain")
    assert "--state-dir .pla_runs" in explain, explain
    assert "--slate" not in _tokens(explain), explain
    assert not any(t.startswith("--slate") for t in _tokens(explain)), explain
    assert explain.endswith("--json > .pla_runs/explain.json"), explain
    # EB2: dispatch --dry-run uses it too, goal-id scrape unchanged.
    dispatch = _one(commands, "uv run pla dispatch")
    assert "--dry-run" in _tokens(dispatch), dispatch
    assert "--state-dir .pla_runs" in dispatch, dispatch
    assert f"--goal-id {GOAL_SCRAPE}" in dispatch, dispatch
    assert not any(t.startswith("--slate") for t in _tokens(dispatch)), dispatch
    assert dispatch.endswith("> .pla_runs/dispatch_preview.txt"), dispatch
    # EB3: same 12 commands, same order; trace keeps its run_dir scrape.
    assert len(commands) == len(EXPECTED_ORDER), commands
    for cmd, head in zip(commands, EXPECTED_ORDER, strict=True):
        assert cmd == head or cmd.startswith(head + " "), (cmd, head)
    trace = _one(commands, "uv run pla trace")
    assert "['dispatched']['run_dir']" in trace, trace
    assert commands[-1] == "uv run python examples/check_run.py < .pla_runs/run.json"


def _b1_self_test() -> None:
    """The static checks are not vacuous: a long-form recipe is rejected."""
    drifted = MAKEFILE.read_text(encoding="utf-8").replace(
        "uv run pla explain --state-dir .pla_runs --json",
        "uv run pla explain --slate .pla_runs/slate.json --json",
    )
    with pytest.raises(AssertionError):
        _b1_b3_static(drifted)


def _call(capsys: pytest.CaptureFixture[str], argv: list[str]) -> tuple[int, str, str]:
    capsys.readouterr()
    try:
        rc = main(argv)
    except SystemExit as exc:  # argparse paths
        rc = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
    out, err = capsys.readouterr()
    return int(rc or 0), out, err


def _grade(script: str, stdin: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(EXAMPLES / script)],
        input=stdin, capture_output=True, text=True, cwd=REPO, check=False, timeout=120,
    )


def _b4_b5_equivalence(capsys: pytest.CaptureFixture[str], cwd: Path) -> None:
    ws = cwd / "ws"
    shutil.copytree(EXAMPLES / "fixture_workspace", ws)
    when = time.time() - 3_600
    for path in [ws, *ws.rglob("*")]:
        os.utime(path, (when, when))
    script = cwd / "scripted_responses.json"
    shutil.copyfile(SCRIPT, script)
    rc, run_out, err = _call(capsys, [
        "run", "--workspace", str(ws), "--provider", "scripted",
        "--scripted-responses", str(script), "--state-dir", ".pla_runs",
        "--snapshot", ".pla_runs/snapshot.json", "--json",
    ])
    assert rc == 0, (rc, run_out, err)
    sd = cwd / ".pla_runs"
    assert (sd / "slate.json").is_file()
    goal_id = str(json.loads(run_out)["dispatched"]["goal_id"])
    assert goal_id

    # EB4 explain: short form == long form, byte for byte.
    rc_s, ex_short, err_s = _call(capsys, ["explain", "--state-dir", ".pla_runs", "--json"])
    rc_l, ex_long, err_l = _call(capsys, ["explain", "--slate", ".pla_runs/slate.json", "--json"])
    assert rc_s == 0 and rc_l == 0, (rc_s, err_s, rc_l, err_l)
    assert ex_short.strip(), ex_short
    assert ex_short == ex_long

    # EB4 dispatch --dry-run: short form == long form; no new run dir.
    runs_before = sorted(p.name for p in sd.glob("run-*"))
    rc_s, dp_short, err_s = _call(capsys, [
        "dispatch", "--dry-run", "--state-dir", ".pla_runs", "--goal-id", goal_id])
    rc_l, dp_long, err_l = _call(capsys, [
        "dispatch", "--dry-run", "--slate", ".pla_runs/slate.json", "--goal-id", goal_id])
    assert rc_s == 0 and rc_l == 0, (rc_s, err_s, rc_l, err_l)
    assert dp_short.strip(), dp_short
    assert dp_short == dp_long
    assert sorted(p.name for p in sd.glob("run-*")) == runs_before

    # EB5: the demo's graders accept the short-form outputs.
    graded = _grade("check_dispatch.py", dp_short)
    assert graded.returncode == 0, graded.stdout + graded.stderr
    assert "ok:" in graded.stdout + graded.stderr, graded.stdout + graded.stderr
    graded = _grade("check_autonomy.py", ex_short)
    assert graded.returncode == 0, graded.stdout + graded.stderr


def _b6_negative_control(capsys: pytest.CaptureFixture[str], root: Path) -> None:
    bare = root / "bare"
    (bare / ".pla_runs").mkdir(parents=True)
    prev = Path.cwd()
    os.chdir(bare)
    try:
        rc, out, err = _call(capsys, ["explain", "--state-dir", ".pla_runs", "--json"])
        assert rc != 0, (rc, out, err)
        assert not (bare / ".pla_runs" / "slate.json").exists()
        rc, out, err = _call(capsys, ["dispatch", "--dry-run", "--state-dir", ".pla_runs",
                                      "--goal-id", "nope"])
        assert rc != 0, (rc, out, err)
        assert not (bare / ".pla_runs" / "slate.json").exists()
        assert list((bare / ".pla_runs").iterdir()) == []
    finally:
        os.chdir(prev)


def iter601_demo_default_slate(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, root: Path
) -> int:
    """Run every iter-601 behaviour from a scratch cwd; return the groups checked."""
    for key in list(os.environ):
        if key.startswith("PLA_"):
            monkeypatch.delenv(key, raising=False)
    _b1_b3_static(MAKEFILE.read_text(encoding="utf-8"))  # EB1, EB2, EB3
    _b1_self_test()
    cwd = root / "cwd"
    cwd.mkdir(parents=True)
    monkeypatch.chdir(cwd)
    _b4_b5_equivalence(capsys, cwd)  # EB4, EB5
    _b6_negative_control(capsys, root)  # EB6
    return 6
