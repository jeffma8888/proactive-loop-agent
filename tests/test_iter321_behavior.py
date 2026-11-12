"""Black-box oracle for iteration 321 (foundry iter 574, ROADMAP #361).

Feature under test: ``pla runs`` counts each run's artifacts with one ``os.scandir``
recursion instead of ``Path.rglob("*") + is_file()``; every output byte is unchanged.

ISOLATION CONTRACT (honored): written against this iteration's spec "Expected Behaviors"
only -- the spec-named ``cli._count_artifacts(run_dir) -> int`` is called directly and
``pla run`` / ``pla runs`` are driven in-process through ``cli.main``. The implementation
source was not read. The expected counts are literals pinned by the spec (4 for the
matrix), never derived from HEAD.

ONE collected item on purpose: ``make readme-headroom`` read ``binding_headroom=7``
before this module, and ``test_iter263::test_b6`` pins >= 6. Offline and deterministic:
scripted provider, no subprocess, and the fixture workspace is a private ``tmp_path``
copy stamped to one known age (fresh-clone safe).
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import sys
import time
from pathlib import Path
from typing import Final

import pytest

from proactive_loop import cli

REPO: Final = Path(__file__).resolve().parents[1]
FIXTURE: Final = REPO / "examples" / "fixture_workspace"
SCRIPT: Final = REPO / "examples" / "scripted_responses.json"
STAMP_AGE_SEC: Final = 6 * 60 * 60
MATRIX_COUNT: Final = 4  # f, sub/.h, sub/deeper/g.txt, fl (file symlink)


def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("PLA_"):
            monkeypatch.delenv(key, raising=False)


def _matrix(root: Path) -> Path:
    """Behavior-1 tree: <root>/run/artifacts/{f, sub/.h, sub/deeper/g.txt, fl, dl, bl}."""
    run = root / "run"
    art = run / "artifacts"
    (art / "sub" / "deeper").mkdir(parents=True)
    (art / "f").write_text("f", encoding="utf-8")
    (art / "sub" / ".h").write_text("h", encoding="utf-8")
    (art / "sub" / "deeper" / "g.txt").write_text("g", encoding="utf-8")
    out = root / "out"
    out.mkdir()
    (out / "o1").write_text("o", encoding="utf-8")
    (out / "o2").write_text("o", encoding="utf-8")
    (art / "fl").symlink_to("f")
    (art / "dl").symlink_to(Path("..") / ".." / "out", target_is_directory=True)
    (art / "bl").symlink_to("nope")
    # Guard against a vacuous fixture: the dir symlink must really resolve to ``out/``.
    assert (art / "dl").is_dir() and (art / "dl" / "o1").is_file()
    assert (art / "fl").is_file() and not (art / "bl").exists()
    return run


def _workspace(root: Path) -> Path:
    dest = root / "ws"
    shutil.copytree(FIXTURE, dest)
    stamp = time.time() - STAMP_AGE_SEC
    for path in [dest, *dest.rglob("*")]:
        os.utime(path, (stamp, stamp))
    return dest


def _walk_count(art: Path) -> int:
    return sum(
        1 for dirpath, _dirs, files in os.walk(art) for name in files if (Path(dirpath) / name).is_file()
    )


def test_b01_to_b05_count_artifacts_scandir_semantics_and_runs_e2e(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _clean_env(monkeypatch)

    # B1: the counting matrix -> exactly 4 (file symlink counts; dir symlink neither
    # counted nor recursed; broken symlink not counted).
    run = _matrix(tmp_path / "m")
    assert cli._count_artifacts(run) == MATRIX_COUNT

    # B2: no artifacts/, artifacts as a regular FILE, empty artifacts/ -> 0.
    absent = tmp_path / "absent"
    absent.mkdir()
    assert cli._count_artifacts(absent) == 0
    as_file = tmp_path / "asfile"
    as_file.mkdir()
    (as_file / "artifacts").write_text("not a dir", encoding="utf-8")
    assert cli._count_artifacts(as_file) == 0
    empty = tmp_path / "empty"
    (empty / "artifacts").mkdir(parents=True)
    assert cli._count_artifacts(empty) == 0

    # B3: an unreadable nested subdir contributes 0, no raise, the rest still counted.
    locked_run = _matrix(tmp_path / "lk")
    locked = locked_run / "artifacts" / "sub" / "deeper"
    locked.chmod(0)
    try:
        effective = sys.platform != "win32" and os.geteuid() != 0 and not os.access(locked, os.R_OK)
        if effective:
            assert cli._count_artifacts(locked_run) == MATRIX_COUNT - 1
    finally:
        locked.chmod(0o755)
    assert cli._count_artifacts(locked_run) == MATRIX_COUNT

    # B4: the count no longer goes through Path.rglob.
    def _no_rglob(*_a: object, **_k: object) -> object:
        raise AssertionError("_count_artifacts called Path.rglob")

    with monkeypatch.context() as mp:
        mp.setattr(pathlib.Path, "rglob", _no_rglob)
        assert cli._count_artifacts(run) == MATRIX_COUNT

    # B5: end to end -- one scripted run, then runs --json / runs --summary --json.
    ws = _workspace(tmp_path)
    sd = tmp_path / "state"
    capsys.readouterr()
    rc = cli.main(
        [
            "run", "--workspace", str(ws), "--provider", "scripted", "--scripted-responses", str(SCRIPT),
            "--state-dir", str(sd),
        ]
    )
    capsys.readouterr()
    assert rc == 0
    run_dirs = [p for p in sd.iterdir() if (p / "artifacts").is_dir()]
    assert len(run_dirs) == 1
    expected = _walk_count(run_dirs[0] / "artifacts")
    assert expected > 0, "vacuous e2e: the scripted run wrote no artifacts"

    assert cli.main(["runs", "--state-dir", str(sd), "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert [row["artifacts"] for row in rows] == [expected]

    assert cli.main(["runs", "--state-dir", str(sd), "--summary", "--json"]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["artifacts"] == expected
