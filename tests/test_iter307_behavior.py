"""Factory iter 558 (ROADMAP #347): persisted state files are read and written as UTF-8.

Every persisted-state file (slate, snapshot/signals document, checkpoint, meta, scripted
responses) is written and read as UTF-8 explicitly, so a non-ASCII goal title round-trips
under ANY locale. Before the fix, under ``LC_ALL=C PYTHONCOERCECLOCALE=0 PYTHONUTF8=0``
(US-ASCII default encoding), ``scan``/``explain``/``trace`` exited 1 with
``'ascii' codec can't decode byte 0xc3``.

Black-box: every behaviour spawns the real CLI (``python -m proactive_loop``) under a
hostile C locale and asserts only exit codes, file BYTES and ``--json`` stdout (which is
``ensure_ascii``); human-table stdout is out of scope. ONE collected item (the
``make readme-headroom`` budget reads binding_headroom=6), paid for by folding a 2-item
parametrize elsewhere; the spec behaviours live in private ``_bN_`` helpers.
Offline and deterministic: scripted provider only, every spawn carries ``timeout=``, and
the fixture workspace is a private ``tmp_path`` copy whose every mtime is stamped to a
known age with ``os.utime`` (fresh-clone safe).
"""

from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Final

REPO: Final = Path(__file__).resolve().parents[1]
SRC: Final = REPO / "src" / "proactive_loop"
FIXTURE: Final = REPO / "examples" / "fixture_workspace"
SCRIPT: Final = REPO / "examples" / "scripted_responses.json"
OLD_TITLE: Final = "Draft a learning plan"
NEW_TITLE: Final = "Draft a caf\u00e9 learning plan"
FULL_TITLE: Final = NEW_TITLE + " and project scaffold for the agentic-loop project"
CAFE_UTF8: Final = "caf\u00e9".encode("utf-8")
TIMEOUT_SEC: Final = 120
STAMP_AGE_SEC: Final = 60 * 60
CENSUS_FILES: Final = ("models.py", "loop/resilience.py", "llm/client.py", "cli.py")


def _c_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("PLA_")}
    env.pop("PYTHONIOENCODING", None)
    env.update({"LC_ALL": "C", "LANG": "C", "PYTHONCOERCECLOCALE": "0", "PYTHONUTF8": "0"})
    return env


def _utf8_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("PLA_")}
    env.pop("PYTHONIOENCODING", None)
    env.update({"LC_ALL": "en_US.UTF-8", "LANG": "en_US.UTF-8", "PYTHONUTF8": "1"})
    return env


def _pla(args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "proactive_loop", *args],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=TIMEOUT_SEC,
        check=False,
    )


def _setup(root: Path) -> tuple[Path, Path]:
    ws = root / "ws"
    shutil.copytree(FIXTURE, ws)
    stamp = time.time() - STAMP_AGE_SEC
    for p in [ws, *ws.rglob("*")]:
        os.utime(p, (stamp, stamp))
    raw = SCRIPT.read_text(encoding="utf-8")
    assert OLD_TITLE in raw, "precondition: bundled script carries the title being localised"
    script = root / "cafe_script.json"
    script.write_bytes(raw.replace(OLD_TITLE, NEW_TITLE).encode("utf-8"))
    assert CAFE_UTF8 in script.read_bytes()
    return ws, script


def _b1_scan_writes_utf8_slate_under_c_locale(root: Path) -> None:
    ws, script = _setup(root)
    slate = root / "slate.json"
    cp = _pla(
        ["scan", "--scripted-responses", str(script), "--workspace", str(ws),
         "--state-dir", str(root / "S"), "--out", str(slate), "--json"],
        _c_env(),
    )
    assert cp.returncode == 0, f"B1 scan under C locale rc={cp.returncode}: {cp.stderr[-400:]}"
    assert "codec can't decode" not in cp.stderr
    data = slate.read_bytes()
    assert CAFE_UTF8 in data, "B1: slate must hold the UTF-8 bytes c3 a9 for 'caf\u00e9'"
    assert FULL_TITLE in data.decode("utf-8")


def _b2_explain_reads_utf8_slate_under_c_locale(root: Path) -> None:
    ws, script = _setup(root)
    slate = root / "slate.json"
    made = _pla(
        ["scan", "--scripted-responses", str(script), "--workspace", str(ws),
         "--state-dir", str(root / "S"), "--out", str(slate), "--json"],
        _utf8_env(),
    )
    assert made.returncode == 0, f"B2 precondition: UTF-8 scan rc={made.returncode}: {made.stderr[-400:]}"
    assert CAFE_UTF8 in slate.read_bytes()
    cp = _pla(["explain", "--slate", str(slate), "--json"], _c_env())
    assert cp.returncode == 0, f"B2 explain under C locale rc={cp.returncode}: {cp.stderr[-400:]}"
    doc = json.loads(cp.stdout)
    goals = doc if isinstance(doc, list) else doc.get("goals", [])
    titles = [g["title"] for g in goals]
    assert FULL_TITLE in titles, f"B2: decoded titles {titles!r}"
    assert any(t.startswith(NEW_TITLE) for t in titles)


def _b3_run_checkpoint_utf8_and_trace_under_c_locale(root: Path) -> None:
    ws, script = _setup(root)
    state = root / "S"
    cp = _pla(
        ["run", "--scripted-responses", str(script), "--workspace", str(ws),
         "--state-dir", str(state), "--json"],
        _c_env(),
    )
    assert cp.returncode == 0, f"B3 run under C locale rc={cp.returncode}: {cp.stderr[-400:]}"
    runs = sorted(p for p in state.glob("run-*") if p.is_dir())
    assert len(runs) == 1, f"B3: expected one run dir, got {runs!r}"
    ckpt = (runs[0] / "checkpoint.json").read_bytes()
    text = ckpt.decode("utf-8")
    json.loads(text)
    assert CAFE_UTF8 in ckpt, "B3: checkpoint must carry the UTF-8 bytes of the dispatched title"
    tr = _pla(["trace", "--run-dir", str(runs[0]), "--json"], _c_env())
    assert tr.returncode == 0, f"B3 trace under C locale rc={tr.returncode}: {tr.stderr[-400:]}"
    json.loads(tr.stdout)
    assert "codec can't decode" not in tr.stderr

    # A checkpoint written under a UTF-8 locale must also be traceable under C.
    state2 = root / "S2"
    made = _pla(
        ["run", "--scripted-responses", str(script), "--workspace", str(ws),
         "--state-dir", str(state2), "--json"],
        _utf8_env(),
    )
    assert made.returncode == 0, made.stderr[-400:]
    runs2 = sorted(p for p in state2.glob("run-*") if p.is_dir())
    assert len(runs2) == 1
    assert CAFE_UTF8 in (runs2[0] / "checkpoint.json").read_bytes()
    tr2 = _pla(["trace", "--run-dir", str(runs2[0]), "--json"], _c_env())
    assert tr2.returncode == 0, f"B3 trace of UTF-8 checkpoint rc={tr2.returncode}: {tr2.stderr[-400:]}"


def _b4_atomic_write_text_is_utf8_under_c_locale(root: Path) -> None:
    target = root / "atomic.json"
    code = (
        "import sys, pathlib\n"
        "from proactive_loop.models import atomic_write_text\n"
        "atomic_write_text(pathlib.Path(sys.argv[1]), '{\"title\": \"caf\\u00e9\"}')\n"
    )
    cp = subprocess.run(
        [sys.executable, "-c", code, str(target)],
        env=_c_env(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=TIMEOUT_SEC,
        check=False,
    )
    assert cp.returncode == 0, f"B4 atomic_write_text under C locale rc={cp.returncode}: {cp.stderr[-400:]}"
    assert target.read_bytes() == '{"title": "caf\u00e9"}'.encode("utf-8")


def _b5_source_census_every_state_io_call_names_encoding() -> None:
    offenders: list[str] = []
    seen = 0
    for rel in CENSUS_FILES:
        path = SRC / rel
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            if node.func.attr not in {"read_text", "write_text"}:
                continue
            owner = node.func.value
            if isinstance(owner, ast.Name) and owner.id == "text_source":
                continue
            seen += 1
            if not any(kw.arg == "encoding" for kw in node.keywords):
                offenders.append(f"{rel}:{node.lineno} .{node.func.attr}(...)")
    assert seen >= 6, f"B5 precondition: census found only {seen} read_text/write_text calls"
    assert offenders == [], f"B5: state I/O without encoding=: {offenders}"


def test_state_files_round_trip_utf8_under_c_locale(tmp_path: Path) -> None:
    """B1-B5 in one collected item; B6 (default-env behaviour unchanged) is the full suite."""
    for name, check in (
        ("b1", _b1_scan_writes_utf8_slate_under_c_locale),
        ("b2", _b2_explain_reads_utf8_slate_under_c_locale),
        ("b3", _b3_run_checkpoint_utf8_and_trace_under_c_locale),
        ("b4", _b4_atomic_write_text_is_utf8_under_c_locale),
    ):
        sub = tmp_path / name
        sub.mkdir()
        check(sub)
    _b5_source_census_every_state_io_call_names_encoding()
