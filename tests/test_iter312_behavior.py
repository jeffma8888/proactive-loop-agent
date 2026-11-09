"""Factory iter 564 (ROADMAP #352): an undecodable slate or checkpoint names its file.

A ``--slate`` file (``explain``, ``dispatch``, ``diff --old/--new``) or a run's
``checkpoint.json`` (``trace``, ``resume``) that is not valid UTF-8 must exit 1 with the ONE
line ``error: invalid <kind> file '<path>': not valid UTF-8 text at byte <N>`` -- the path as
the CLI was given it and the first bad byte offset -- instead of the bare codec message.
``runs`` still degrades the corrupt checkpoint to ``(no checkpoint)`` and exits 0.

Black-box: the CLI is driven through ``python -m proactive_loop`` subprocesses and only exit
codes, stdout and stderr are asserted; goal ids are read from the written slate, never
hardcoded. ONE collected item (``make readme-headroom`` reads binding_headroom=6, pinned >= 6 by
test_iter263/270), funded by folding the 2-item test_iter139::test_b04 ``spelling`` parametrize;
each behavior is a private ``_bN_`` half on its own ``tmp_path/<sub>``. Offline and
deterministic: scripted provider, every state dir under ``tmp_path``, and the fixture workspace
is a private copy stamped to one known age (fresh-clone safe).
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

REPO: Final = Path(__file__).resolve().parents[1]
EXAMPLES: Final = REPO / "examples"
STAMP_AGE_SEC: Final = 6 * 60 * 60

Result = tuple[int, str, str]


def _env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("PLA_")}
    src = str(REPO / "src")
    env["PYTHONPATH"] = src + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    return env


def _pla(cwd: Path, *argv: str) -> Result:
    proc = subprocess.run(
        [sys.executable, "-m", "proactive_loop", *argv],
        cwd=cwd,
        env=_env(),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _stamp(root: Path) -> None:
    when = time.time() - STAMP_AGE_SEC
    for dirpath, dirnames, filenames in os.walk(root):
        for name in [*dirnames, *filenames]:
            os.utime(Path(dirpath) / name, (when, when), follow_symlinks=False)
    os.utime(root, (when, when))


def _setup(root: Path) -> tuple[Path, Path, Path, list[dict[str, object]]]:
    """Copy examples/, scan to a slate; return (examples copy, state dir, slate, goals)."""
    ex = root / "examples"
    shutil.copytree(EXAMPLES, ex, symlinks=True)
    _stamp(ex)
    state = root / "state"
    slate = state / "slate.json"
    rc, out, err = _pla(
        root,
        "scan", "--workspace", str(ex / "fixture_workspace"),
        "--provider", "scripted", "--scripted-responses", str(ex / "scripted_responses.json"),
        "--out", str(slate), "--state-dir", str(state),
    )
    assert rc == 0, f"fixture precondition: scan failed rc={rc}\n{out}\n{err}"
    goals = json.loads(slate.read_text(encoding="utf-8"))["goals"]
    assert isinstance(goals, list) and len(goals) >= 2, goals
    return ex, state, slate, goals


def _one_line(err: str, expected: str, label: str) -> None:
    assert "Traceback" not in err, f"[{label}] traceback leaked:\n{err}"
    assert "codec can't decode" not in err, f"[{label}] bare codec message:\n{err}"
    assert err == expected + "\n", f"[{label}] stderr={err!r}, expected {expected!r}"


def _run_dirs(state: Path) -> set[Path]:
    return {p.parent for p in state.rglob("checkpoint.json")}


def _b1_b2_slate(root: Path) -> None:
    root.mkdir()
    _ex, state, slate, _goals = _setup(root)
    (root / "bad.json").write_bytes(b"\xff")
    bad2 = b'{"goals": \xff]'
    assert bad2.index(b"\xff") == 10
    (root / "bad2.json").write_bytes(bad2)
    msg1 = "error: invalid slate file 'bad.json': not valid UTF-8 text at byte 0"

    # B1: explain on a one-byte \xff slate, path given relative.
    rc, out, err = _pla(root, "explain", "--slate", "bad.json")
    assert rc == 1, f"[B1 explain] rc={rc} err={err!r}"
    assert out == "", f"[B1 explain] stdout must be empty: {out!r}"
    _one_line(err, msg1, "B1 explain")

    # B2: diff names the broken file (--new), not the good one; and the other order too.
    rc, out, err = _pla(root, "diff", "--old", str(slate), "--new", "bad2.json")
    assert rc == 1, f"[B2 diff] rc={rc} err={err!r}"
    _one_line(err, "error: invalid slate file 'bad2.json': not valid UTF-8 text at byte 10", "B2 diff")
    assert str(slate) not in err
    rc, out, err = _pla(root, "diff", "--old", "bad2.json", "--new", str(slate))
    assert rc == 1, f"[B2 diff reversed] rc={rc} err={err!r}"
    _one_line(err, "error: invalid slate file 'bad2.json': not valid UTF-8 text at byte 10", "B2 diff rev")

    # B2: dispatch --dry-run on the bad slate: same message, no run dir created.
    before = _run_dirs(state)
    rc, out, err = _pla(root, "dispatch", "--slate", "bad.json", "--goal-id", "x", "--dry-run",
                        "--state-dir", str(state))
    assert rc == 1, f"[B2 dispatch] rc={rc} err={err!r}"
    _one_line(err, msg1, "B2 dispatch")
    assert _run_dirs(state) == before, "dispatch on an undecodable slate created a run dir"


def _b3_b4_checkpoint(root: Path) -> None:
    root.mkdir()
    ex, state, slate, goals = _setup(root)
    gid = str(goals[1]["id"])
    rc, out, err = _pla(
        root, "dispatch", "--slate", str(slate), "--goal-id", gid, "--yes", "--state-dir", str(state),
        "--provider", "scripted", "--scripted-responses", str(ex / "scripted_responses.json"),
    )
    assert rc == 0, f"fixture precondition: dispatch failed rc={rc}\n{out}\n{err}"
    runs = sorted(_run_dirs(state))
    assert len(runs) == 1, f"fixture precondition: expected one run dir, got {runs}"
    run = runs[0]
    (run / "checkpoint.json").write_bytes(b"ab\xffcd")
    rel = os.path.relpath(run, root)

    # B3: trace and resume name the checkpoint, with --run-dir as given (absolute and relative).
    for given in (str(run), rel):
        expected = f"error: invalid checkpoint file '{given}/checkpoint.json': not valid UTF-8 text at byte 2"
        rc, out, err = _pla(root, "trace", "--run-dir", given)
        assert rc == 1, f"[B3 trace {given}] rc={rc} err={err!r}"
        _one_line(err, expected, f"B3 trace {given}")
        rc, out, err = _pla(root, "resume", "--run-dir", given, "--state-dir", str(state))
        assert rc == 1, f"[B3 resume {given}] rc={rc} err={err!r}"
        _one_line(err, expected, f"B3 resume {given}")

    # B4: runs still degrades, never raises.
    rc, out, err = _pla(root, "runs", "--state-dir", str(state))
    assert rc == 0, f"[B4 runs] rc={rc} err={err!r}"
    assert "(no checkpoint)" in out, f"[B4 runs] corrupt run not degraded:\n{out}"
    assert "Traceback" not in err
    rc, out, err = _pla(root, "runs", "--state-dir", str(state), "--json")
    assert rc == 0, f"[B4 runs --json] rc={rc} err={err!r}"
    json.loads(out)


def test_undecodable_slate_and_checkpoint_name_their_file(tmp_path: Path) -> None:
    _b1_b2_slate(tmp_path / "slate")
    _b3_b4_checkpoint(tmp_path / "checkpoint")
