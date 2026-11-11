"""Black-box oracle for factory iteration 318 (foundry state iter-570) --
``pla watch --interval S`` rejects ``S > threading.TIMEOUT_MAX`` at parse time.

A finite interval above the platform sleep limit used to slip past the parse-time
validator, render scan #1 and then crash in the sleep with an ``OverflowError``
traceback (exit 1). It is now an argparse usage error: exit 2, NOTHING on stdout
(no scan ran), and a ``must be at most <N> seconds`` message where ``N`` is
``int(threading.TIMEOUT_MAX)`` on the RUNNING interpreter -- derived here, never
hard-coded. The bound is inclusive, the pre-existing finite / negative / numeric
checks keep their messages (and run first), and ``watch --help`` plus the README
``watch`` prose state the ~9.2e9 limit.

ISOLATION CONTRACT (honored): written from the iteration spec (``pm.md``),
``README.md`` and the conventions under ``tests/``. It drives ONLY the public CLI
in a subprocess (``python -m proactive_loop``, PYTHONPATH=<repo>/src) so a crash
traceback on stderr is observable. No implementation source, engineer/reviewer
note or git diff was read.

ONE collected item on purpose: binding_headroom is pinned (test_iter263 /
test_iter270), so each behavior is a private ``_bN`` half.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Final

REPO: Final = Path(__file__).resolve().parents[1]
README: Final = REPO / "README.md"
WORKSPACE: Final = REPO / "examples" / "fixture_workspace"
RESPONSES: Final = REPO / "examples" / "scripted_responses.json"
LIMIT: Final = int(threading.TIMEOUT_MAX)
PREFIX: Final = "pla watch: error: argument --interval: "


def _watch(tmp: Path, interval: str, max_scans: int) -> tuple[int, str, str]:
    """Run ``pla watch`` offline with the scripted provider; return (rc, out, err)."""
    env = {**os.environ, "PYTHONPATH": str(REPO / "src")}
    for knob in [k for k in env if k.startswith("PLA_")]:
        env.pop(knob)
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "proactive_loop",
            "watch",
            "--workspace",
            str(WORKSPACE),
            f"--interval={interval}",
            "--max-scans",
            str(max_scans),
            "--provider",
            "scripted",
            "--scripted-responses",
            str(RESPONSES),
            "--out-dir",
            str(tmp / "out"),
        ],
        cwd=tmp,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _last(err: str) -> str:
    lines = [ln for ln in err.splitlines() if ln.strip()]
    return lines[-1] if lines else ""


def _rejected(tmp: Path, interval: str, got: str) -> None:
    rc, out, err = _watch(tmp, interval, 2)
    assert rc == 2, (interval, rc, err)
    assert out == "", (interval, out[:200])
    assert "Traceback" not in err, (interval, err)
    assert _last(err) == f"{PREFIX}must be at most {LIMIT} seconds, got {got}", (
        interval,
        err,
    )


def _b1(tmp: Path) -> None:
    _rejected(tmp / "b1", "1e10", "10000000000.0")


def _b2(tmp: Path) -> None:
    _rejected(tmp / "b2a", "1e300", "1e+300")
    _rejected(tmp / "b2b", str(LIMIT + 1), str(float(LIMIT + 1)))


def _b3(tmp: Path) -> None:
    for name, interval in (("b3a", str(LIMIT)), ("b3b", "9.2e9")):
        rc, out, err = _watch(tmp / name, interval, 1)
        assert rc == 0, (interval, rc, err)
        assert "=== scan 1 ===" in out, (interval, out[:300])
        assert "=== scan 2 ===" not in out, interval
        assert "Traceback" not in err, (interval, err)


def _b4(tmp: Path) -> None:
    rc, out, err = _watch(tmp / "b4zero", "0", 2)
    assert rc == 0, err
    assert "=== scan 1 ===" in out and "=== scan 2 ===" in out, out[:300]
    rc, out, err = _watch(tmp / "b4neg", "-1", 2)
    assert (rc, out) == (2, ""), err
    assert _last(err) == f"{PREFIX}must be a non-negative number (>= 0), got -1.0"
    for value in ("nan", "inf", "-inf"):
        rc, out, err = _watch(tmp / f"b4{value}", value, 2)
        assert (rc, out) == (2, ""), (value, err)
        last = _last(err)
        assert last.startswith(f"{PREFIX}must be a finite number, got "), (value, err)
        assert "at most" not in last, (value, err)
    rc, out, err = _watch(tmp / "b4abc", "abc", 2)
    assert (rc, out) == (2, ""), err
    assert _last(err).startswith(PREFIX), err
    assert "Traceback" not in err


def _b5(tmp: Path) -> None:
    env = {**os.environ, "PYTHONPATH": str(REPO / "src")}
    proc = subprocess.run(
        [sys.executable, "-m", "proactive_loop", "watch", "--help"],
        cwd=tmp,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "9.2e9" in " ".join(proc.stdout.split()), proc.stdout
    text = README.read_text(encoding="utf-8")
    marker = text.index("PORTFOLIO INTRO")
    below = " ".join(text[marker:].split())
    assert "guarded at parse time" in below
    assert "at most ~9.2e9 seconds" in below


def test_watch_interval_above_sleep_limit_is_a_parse_time_usage_error(
    tmp_path: Path,
) -> None:
    for sub in ("b1", "b2a", "b2b", "b3a", "b3b"):
        (tmp_path / sub).mkdir()
    for sub in ("b4zero", "b4neg", "b4nan", "b4inf", "b4-inf", "b4abc"):
        (tmp_path / sub).mkdir()
    _b1(tmp_path)
    _b2(tmp_path)
    _b3(tmp_path)
    _b4(tmp_path)
    _b5(tmp_path)
