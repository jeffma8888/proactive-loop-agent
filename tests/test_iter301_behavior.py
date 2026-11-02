"""Factory iter 552 (ROADMAP #341): ``pla runs`` refuses an existing non-directory ``--state-dir``.

Before this fix, ``runs`` (and ``--json``, ``--summary --json``, ``--prune``) against a
``--state-dir`` that is a regular FILE exited 0 and certified "no runs" -- a wrong answer that
CI's ``check_runs_summary.py`` would read as ``runs: 0``. The producing verb (``run``) already
refused the same path with exit 2. Now ``runs`` refuses too, with the SAME stderr line, while an
ABSENT state dir stays legal (exit 0, "no runs") and a real state dir lists as before.

Black-box: every behaviour drives ``cli.main([...])`` in-process and asserts observable
stdout/stderr, exit codes and files on disk. ONE collected item (``make readme-headroom``
reads binding_headroom=6, so the real budget is zero; test_iter126::test_eb6_empty_no_run_dirs
was folded from 2 items to 1 to pay for this one). Offline and deterministic: scripted
provider, no subprocess, and the fixture workspace is a private ``tmp_path`` copy whose every
mtime is stamped to one known age (fresh-clone safe).
"""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from typing import Final

import pytest

from proactive_loop import cli
from proactive_loop.cli import main

REPO: Final = Path(__file__).resolve().parents[1]
FIXTURE: Final = REPO / "examples" / "fixture_workspace"
SCRIPT: Final = REPO / "examples" / "scripted_responses.json"
STAMP_AGE_SEC: Final = 6 * 60 * 60
NO_RUNS: Final = "no runs found under the state dir."
SUMMARY_PRUNE: Final = "error: --summary cannot be combined with --prune"
FILE_BYTES: Final = b"not a state dir\n"
SHAPES: Final[tuple[tuple[str, ...], ...]] = (
    (),
    ("--json",),
    ("--summary",),
    ("--summary", "--json"),
    ("--status", "done"),
    ("--goal", "x"),
)
PRUNE_SHAPES: Final[tuple[tuple[str, ...], ...]] = (("--prune",), ("--prune", "--yes"))


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


def _main(capsys: pytest.CaptureFixture[str], argv: list[str]) -> tuple[int, str, str]:
    capsys.readouterr()
    rc = main(argv)
    out = capsys.readouterr()
    return rc, out.out, out.err


def _run(
    capsys: pytest.CaptureFixture[str], ws: Path, state: Path, *extra: str
) -> tuple[int, str, str]:
    return _main(
        capsys,
        [
            "run",
            "--workspace",
            str(ws),
            "--provider",
            "scripted",
            "--scripted-responses",
            str(SCRIPT),
            "--state-dir",
            str(state),
            *extra,
        ],
    )


def _runs(capsys: pytest.CaptureFixture[str], state: Path, *extra: str) -> tuple[int, str, str]:
    return _main(capsys, ["runs", *extra, "--state-dir", str(state)])


def _refusal_line(path: Path) -> str:
    return f"error: --state-dir is not a directory: {path}"


def _assert_refused(rc: int, out: str, err: str, path: Path, shape: tuple[str, ...]) -> None:
    assert rc == 2, f"runs {shape} on a file --state-dir must exit 2; got {rc}; out={out!r}"
    assert out == "", f"runs {shape} on a file --state-dir must print nothing on stdout: {out!r}"
    assert _refusal_line(path) in err.splitlines(), f"runs {shape}: stderr {err!r}"


def _b1_bare_runs_refuses_with_run_s_own_line(
    capsys: pytest.CaptureFixture[str], ws: Path, bad: Path
) -> None:
    rc, out, err = _runs(capsys, bad)
    _assert_refused(rc, out, err, bad, ())
    # Same text the producing verb prints for the same path.
    rc_run, out_run, err_run = _run(capsys, ws, bad)
    assert rc_run == 2, f"run --state-dir <file> must still exit 2; got {rc_run}"
    assert _refusal_line(bad) in err_run.splitlines(), err_run
    assert [ln for ln in err.splitlines() if ln.startswith("error:")] == [
        ln for ln in err_run.splitlines() if ln.startswith("error:")
    ], "runs and run must refuse a file --state-dir with byte-identical error lines"


def _b2_every_read_shape_refuses(capsys: pytest.CaptureFixture[str], bad: Path) -> None:
    assert len(SHAPES) == 6
    for shape in SHAPES:
        rc, out, err = _runs(capsys, bad, *shape)
        _assert_refused(rc, out, err, bad, shape)
        assert NO_RUNS not in out + err, f"runs {shape} must not certify 'no runs'"
        assert '"runs": 0' not in out, f"runs {shape} must not emit a runs:0 document"


def _b3_prune_refuses_and_leaves_the_file(capsys: pytest.CaptureFixture[str], bad: Path) -> None:
    assert len(PRUNE_SHAPES) == 2
    for shape in PRUNE_SHAPES:
        rc, out, err = _runs(capsys, bad, *shape)
        _assert_refused(rc, out, err, bad, shape)
        assert bad.is_file(), f"runs {shape} must not remove the file --state-dir"
        assert bad.read_bytes() == FILE_BYTES, f"runs {shape} must not touch the file's bytes"


def _b4_argv_shape_refusal_comes_first(capsys: pytest.CaptureFixture[str], bad: Path) -> None:
    rc, out, err = _runs(capsys, bad, "--summary", "--prune")
    assert rc == 2, f"--summary --prune must exit 2; got {rc}"
    assert out == ""
    assert SUMMARY_PRUNE in err.splitlines(), f"argv refusal must win; stderr {err!r}"
    assert _refusal_line(bad) not in err, f"the state-dir line must not appear first/also: {err!r}"
    assert bad.read_bytes() == FILE_BYTES


def _b5_absent_state_dir_is_still_legal(capsys: pytest.CaptureFixture[str], missing: Path) -> None:
    rc, out, err = _runs(capsys, missing)
    assert rc == 0, f"absent state dir must exit 0; got {rc}; err={err!r}"
    assert NO_RUNS in out.splitlines(), out
    rc, out, err = _runs(capsys, missing, "--json")
    assert rc == 0, err
    assert json.loads(out) == []
    rc, out, err = _runs(capsys, missing, "--summary", "--json")
    assert rc == 0, err
    doc = json.loads(out)
    assert doc["runs"] == 0, doc
    assert "error" not in err
    assert not missing.exists(), "runs must not create an absent --state-dir"


def _b6_real_state_dir_lists_its_run(capsys: pytest.CaptureFixture[str], ws: Path, real: Path) -> str:
    rc, _out, err = _run(capsys, ws, real)
    assert rc == 0, f"seed run failed: {err}"
    run_dirs = sorted(p for p in real.glob("run-*") if p.is_dir())
    assert len(run_dirs) == 1, run_dirs
    run_id = run_dirs[0].name

    rc, out, err = _runs(capsys, real)
    assert rc == 0, err
    rows = [ln for ln in out.splitlines() if ln.startswith("run-")]
    assert len(rows) == 1, f"expected exactly one run row: {out!r}"
    assert run_id in rows[0]
    assert NO_RUNS not in out

    rc, out, err = _runs(capsys, real, "--json")
    assert rc == 0, err
    data = json.loads(out)
    assert isinstance(data, list) and len(data) == 1, data
    assert data[0]["run_id"] == run_id
    assert data[0]["status"] == "done"

    rc, out, err = _runs(capsys, real, "--summary", "--json")
    assert rc == 0, err
    assert json.loads(out)["runs"] == 1
    return run_id


def _b7_skip_done_and_iter_run_dirs_unaffected(
    capsys: pytest.CaptureFixture[str], ws: Path, real: Path, bad: Path, run_id: str
) -> None:
    rc, out, err = _run(capsys, ws, real, "--skip-done")
    assert rc == 0, err
    skip = [ln.strip() for ln in out.splitlines() if ln.strip().startswith("skipped (already done): ")]
    assert len(skip) == 1 and skip[0].endswith(f"-> {run_id}"), f"--skip-done must still skip: {out!r}"
    assert len([p for p in real.glob("run-*") if p.is_dir()]) == 1, "--skip-done must not re-dispatch"
    # The guard lives in the runs verb; the tolerant directory iterator still yields nothing.
    assert list(cli._iter_run_dirs(bad)) == []
    assert bad.read_bytes() == FILE_BYTES


def test_runs_refuses_non_directory_state_dir_b1_through_b7(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _clean_env(monkeypatch)
    ws = _workspace(tmp_path)
    bad = tmp_path / "file"
    bad.write_bytes(FILE_BYTES)
    missing = tmp_path / "missing"
    real = tmp_path / "real"

    _b1_bare_runs_refuses_with_run_s_own_line(capsys, ws, bad)
    _b2_every_read_shape_refuses(capsys, bad)
    _b3_prune_refuses_and_leaves_the_file(capsys, bad)
    _b4_argv_shape_refusal_comes_first(capsys, bad)
    _b5_absent_state_dir_is_still_legal(capsys, missing)
    run_id = _b6_real_state_dir_lists_its_run(capsys, ws, real)
    _b7_skip_done_and_iter_run_dirs_unaffected(capsys, ws, real, bad, run_id)
