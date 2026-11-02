"""Factory iter 553 (ROADMAP #342): ``watch --out-dir`` stops on a slate-persist fault.

Before this fix, ``pla watch --out-dir <read-only dir>`` logged every failed slate write as
``scan N failed: [Errno 13] ...`` -- the ride-on route meant for TRANSIENT scan faults -- and
exited 0 having persisted nothing, so a bounded CI watch could pass green while writing no
stream at all. Now a tick whose scan succeeds but whose slate write raises ``OSError`` stops
the watch with exit 1 and ONE ``error: cannot write --out-dir slate: <path>: ...`` line, while
a genuine scan fault (the scripted tape running dry on tick 3) still rides on with exit 0.

Black-box: every behaviour drives ``cli.main([...])`` in-process and asserts observable
stdout/stderr, exit codes and files on disk. ONE collected item (``make readme-headroom``
reads binding_headroom=6, so the real budget is zero;
test_iter126::test_eb6_empty_state_dir_missing was folded from 2 items to 1 to pay for this
one). Offline and deterministic: scripted provider, no subprocess, ``--interval 0``, and the
fixture workspace is a private ``tmp_path`` copy whose every mtime is stamped to one known
age (fresh-clone safe). The read-only dir is ``chmod 0o555``; root ignores mode bits, so the
test skips under euid 0, and permissions are always restored in a ``finally``.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from typing import Final

import pytest

from proactive_loop.cli import main

REPO: Final = Path(__file__).resolve().parents[1]
FIXTURE: Final = REPO / "examples" / "fixture_workspace"
SCRIPT: Final = REPO / "examples" / "scripted_responses.json"
STAMP_AGE_SEC: Final = 6 * 60 * 60
ERROR_PREFIX: Final = "error: cannot write --out-dir slate: "
HEADER_1: Final = "=== scan 1 ==="
HEADER_2: Final = "=== scan 2 ==="


def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("PLA_"):
            monkeypatch.delenv(key, raising=False)


def _workspace(root: Path) -> Path:
    dest = root / "ws"
    shutil.copytree(FIXTURE, dest)
    stamp = time.time() - STAMP_AGE_SEC
    for path in [dest, *dest.rglob("*")]:
        os.utime(path, (stamp, stamp))
    return dest


def _watch(
    capsys: pytest.CaptureFixture[str], ws: Path, state: Path, *extra: str
) -> tuple[int, str, str]:
    capsys.readouterr()
    rc = main(
        [
            "watch",
            "--workspace",
            str(ws),
            "--provider",
            "scripted",
            "--scripted-responses",
            str(SCRIPT),
            "--state-dir",
            str(state),
            "--interval",
            "0",
            *extra,
        ]
    )
    out = capsys.readouterr()
    return rc, out.out, out.err


def _read_only_dir(root: Path) -> Path:
    ro = root / "ro"
    ro.mkdir()
    ro.chmod(0o555)
    return ro


def _error_lines(err: str) -> list[str]:
    return [ln for ln in err.splitlines() if ln.startswith("error:")]


def _assert_persist_fault(rc: int, out: str, err: str, ro: Path, shape: str) -> None:
    assert rc == 1, f"watch {shape} into a read-only --out-dir must exit 1; got {rc}; err={err!r}"
    errors = _error_lines(err)
    assert len(errors) == 1, f"watch {shape}: exactly one error: line expected; stderr={err!r}"
    line = errors[0]
    assert line.startswith(ERROR_PREFIX), f"watch {shape}: wrong error line {line!r}"
    target = str(ro / "slate-001.json")
    assert target in line, f"watch {shape}: error line must name {target}; got {line!r}"
    assert f"{target}.tmp" not in line, f"watch {shape}: must name the final path, not .tmp"
    assert "failed" not in err, f"watch {shape}: a persist fault is not 'scan N failed': {err!r}"
    assert "Traceback" not in err and "Traceback" not in out, f"watch {shape}: traceback leaked"
    assert sorted(p.name for p in ro.iterdir()) == [], f"watch {shape}: RO dir must stay empty"


def _b1_one_tick_into_ro_dir_exits_1(
    capsys: pytest.CaptureFixture[str], ws: Path, root: Path
) -> None:
    ro = _read_only_dir(root)
    try:
        rc, out, err = _watch(capsys, ws, root / "state", "--max-scans", "1", "--out-dir", str(ro))
    finally:
        ro.chmod(0o755)
    _assert_persist_fault(rc, out, err, ro, "--max-scans 1")
    assert out.count(HEADER_1) == 1, f"the tick still renders before the write: {out!r}"
    assert "slate written:" not in out, f"no trailer for an unwritten slate: {out!r}"


def _b2_three_ticks_stop_after_the_first(
    capsys: pytest.CaptureFixture[str], ws: Path, root: Path
) -> None:
    ro = _read_only_dir(root)
    try:
        rc, out, err = _watch(capsys, ws, root / "state", "--max-scans", "3", "--out-dir", str(ro))
    finally:
        ro.chmod(0o755)
    _assert_persist_fault(rc, out, err, ro, "--max-scans 3")
    assert out.count(HEADER_1) == 1, f"exactly one scan-1 header expected: {out!r}"
    assert HEADER_2 not in out and HEADER_2 not in err, "the watch must stop after tick 1"
    assert not list(ro.glob("slate-*.json")) and not list(ro.glob("*.tmp"))


def _b3_json_mode_same_fault_and_tick_still_printed(
    capsys: pytest.CaptureFixture[str], ws: Path, root: Path
) -> None:
    ro = _read_only_dir(root)
    try:
        rc, out, err = _watch(
            capsys, ws, root / "state", "--max-scans", "3", "--out-dir", str(ro), "--json"
        )
    finally:
        ro.chmod(0o755)
    _assert_persist_fault(rc, out, err, ro, "--max-scans 3 --json")
    doc = json.loads(out)  # exactly one tick's document: the watch stopped after tick 1
    assert isinstance(doc, dict) and isinstance(doc.get("goals"), list) and doc["goals"], doc
    assert HEADER_2 not in out and HEADER_2 not in err, "the --json watch must stop after tick 1"


def _b4_b5_scan_fault_still_rides_on_and_healthy_dir_unchanged(
    capsys: pytest.CaptureFixture[str], ws: Path, root: Path
) -> None:
    ok = root / "ok"
    # B5: two healthy ticks write two slates with trailers.
    rc, out, err = _watch(capsys, ws, root / "state2", "--max-scans", "2", "--out-dir", str(ok))
    assert rc == 0, f"a healthy --out-dir watch must exit 0; got {rc}; err={err!r}"
    assert sorted(p.name for p in ok.iterdir()) == ["slate-001.json", "slate-002.json"]
    assert [ln for ln in out.splitlines() if ln.startswith("slate written:")] == [
        f"slate written: {ok / 'slate-001.json'}",
        f"slate written: {ok / 'slate-002.json'}",
    ], out
    assert _error_lines(err) == [], err
    # B4: the fixed-length tape runs dry on tick 3 -- a SCAN fault, which still rides on.
    ok3 = root / "ok3"
    rc, out, err = _watch(capsys, ws, root / "state3", "--max-scans", "3", "--out-dir", str(ok3))
    assert rc == 0, f"a scan fault must keep the ride-on exit 0; got {rc}; err={err!r}"
    failed = [ln for ln in err.splitlines() if ln.startswith("scan ")]
    assert len(failed) == 1 and failed[0].startswith("scan 3 failed: "), err
    assert _error_lines(err) == [], f"a scan fault prints no error: line: {err!r}"
    assert out.count("=== scan 3 ===") == 1, out
    assert sorted(p.name for p in ok3.iterdir()) == ["slate-001.json", "slate-002.json"]


def _b6_plain_watch_without_out_dir_unaffected(
    capsys: pytest.CaptureFixture[str], ws: Path, root: Path
) -> None:
    before = sorted(p.name for p in root.iterdir())
    rc, out, err = _watch(capsys, ws, root / "state4", "--max-scans", "2")
    assert rc == 0, f"plain watch must exit 0; got {rc}; err={err!r}"
    assert out.count(HEADER_1) == 1 and out.count(HEADER_2) == 1, out
    assert "slate written:" not in out and _error_lines(err) == [], (out, err)
    after = sorted(p.name for p in root.iterdir() if p.name != "state4")
    assert after == before, "plain watch must write no --out-dir stream"


def test_watch_out_dir_persist_fault_stops_with_exit_1_while_scan_faults_ride_on(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        pytest.skip("root ignores chmod 0o555, so a read-only dir cannot be simulated")
    _clean_env(monkeypatch)
    ws = _workspace(tmp_path)
    for name in ("a", "b", "c", "d", "e"):
        (tmp_path / name).mkdir()
    _b1_one_tick_into_ro_dir_exits_1(capsys, ws, tmp_path / "a")
    _b2_three_ticks_stop_after_the_first(capsys, ws, tmp_path / "b")
    _b3_json_mode_same_fault_and_tick_still_printed(capsys, ws, tmp_path / "c")
    _b4_b5_scan_fault_still_rides_on_and_healthy_dir_unchanged(capsys, ws, tmp_path / "d")
    _b6_plain_watch_without_out_dir_unaffected(capsys, ws, tmp_path / "e")
