"""Black-box behavior tests for foundry iteration 587 (oracle module 324).

Feature under test: ``pla trace`` WITHOUT ``--run-dir`` traces the newest run
under the state dir, where "newest" is the greatest checkpoint ``created_at``
(ties -> the lexically greatest dir name). The chosen dir is named on exactly
one stderr line, ``tracing newest run: <dir>``; an explicit ``--run-dir`` is
unchanged.

ISOLATION CONTRACT (honored): written only from the iteration spec, README.md,
SPEC.md, existing tests and the CLI's own ``--help``/output. No file under
``src/`` was read, no engineer/reviewer notes and no ``git diff`` were
consulted. Every state dir is a fresh ``tmp_path`` (never the ambient
``.pla_runs``); every checkpoint is a hand-written ``RunState`` with an explicit
``created_at`` (never mtime), so the tests are clone-safe. ROADMAP/SPEC size
pins are owned by test_iter280/308 and are deliberately not re-asserted here.
The module collects ONE item, ``test_trace_defaults_to_newest_run``, which clears every
``PLA_*`` env var and asserts ``iter587_trace_newest``'s returned check count (until
factory iter 602 it was hosted, uncollected, in test_iter317 under the 6-item binding
wall).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from proactive_loop.cli import main
from proactive_loop.loop import Checkpoint
from proactive_loop.models import CandidateGoal, RunState, RunStatus

REPO = Path(__file__).resolve().parents[1]
_TRACEBACK = "Traceback"
_NEWEST = "tracing newest run: "


def _save(state_dir: Path, name: str, created_at: datetime, title: str) -> Path:
    run_dir = state_dir / name
    run_dir.mkdir(parents=True, exist_ok=True)
    state = RunState(
        goal=CandidateGoal(title=title, suggested_first_steps=["read README.md"]),
        status=RunStatus.BUDGET_EXHAUSTED,
        iterations_used=1,
        llm_calls_used=2,
        artifacts_dir=str(run_dir / "artifacts"),
        created_at=created_at,
    )
    Checkpoint(run_dir / "checkpoint.json").save(state)
    return run_dir


def _call(capsys: pytest.CaptureFixture[str], argv: list[str]) -> tuple[int, str, str]:
    capsys.readouterr()
    try:
        rc = main(argv)
    except SystemExit as exc:  # argparse paths
        rc = exc.code if isinstance(exc.code, int) else 1
    out, err = capsys.readouterr()
    return rc, out, err


def _utc(day: int) -> datetime:
    return datetime(2026, 1, day, tzinfo=timezone.utc)


def _b1_b2_newest_by_created_at_then_by_name(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    s = tmp_path / "state"
    _save(s, "run-aaa", _utc(2), "goal alpha newer")
    _save(s, "run-zzz", _utc(1), "goal zulu older")
    rc, out, err = _call(capsys, ["trace", "--state-dir", str(s)])
    erc, eout, eerr = _call(capsys, ["trace", "--state-dir", str(s), "--run-dir", str(s / "run-aaa")])
    assert (rc, erc) == (0, 0), err
    assert out == eout and out != ""
    assert "goal alpha newer" in out and "goal zulu older" not in out
    assert err == f"{_NEWEST}{Path(s) / 'run-aaa'}\n"
    assert _NEWEST not in eerr
    # B2: identical created_at -> lexically greatest dir name, deterministic.
    s = tmp_path / "tie"
    _save(s, "run-bbb", _utc(5), "goal bravo")
    _save(s, "run-yyy", _utc(5), "goal yankee")
    _save(s, "run-ccc", _utc(5), "goal charlie")
    first = _call(capsys, ["trace", "--state-dir", str(s)])
    second = _call(capsys, ["trace", "--state-dir", str(s)])
    assert first == second
    assert first[0] == 0
    assert first[2] == f"{_NEWEST}{s / 'run-yyy'}\n"
    assert "goal yankee" in first[1]


def _b3_b4_json_is_clean_and_unreadable_runs_are_skipped(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    s = tmp_path / "state"
    _save(s, "run-old", _utc(1), "goal old")
    _save(s, "run-new", _utc(3), "goal new")
    rc, out, err = _call(capsys, ["trace", "--state-dir", str(s), "--json"])
    erc, eout, _ = _call(capsys, ["trace", "--state-dir", str(s), "--run-dir", str(s / "run-new"), "--json"])
    assert (rc, erc) == (0, 0)
    parsed = json.loads(out)
    assert isinstance(parsed, list)
    assert parsed == json.loads(eout)
    assert _NEWEST not in out
    assert err == f"{_NEWEST}{s / 'run-new'}\n"
    # B4: checkpoint-less and corrupt run-* dirs are skipped.
    s = tmp_path / "skip"
    _save(s, "run-good", _utc(1), "goal readable")
    (s / "run-zz-nockpt").mkdir()
    bad_json = s / "run-zz-badjson"
    bad_json.mkdir()
    (bad_json / "checkpoint.json").write_text("{not json", encoding="utf-8")
    bad_schema = s / "run-zz-badschema"
    bad_schema.mkdir()
    (bad_schema / "checkpoint.json").write_text(json.dumps({"goal": 7}), encoding="utf-8")
    rc, out, err = _call(capsys, ["trace", "--state-dir", str(s)])
    assert rc == 0, err
    assert err == f"{_NEWEST}{s / 'run-good'}\n"
    assert "goal readable" in out


def _b5_nothing_to_trace_is_clean_exit_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    absent = tmp_path / "absent"
    empty = tmp_path / "empty"
    empty.mkdir()
    junk = tmp_path / "junk"
    (junk / "run-nockpt").mkdir(parents=True)
    (junk / "run-bad").mkdir()
    (junk / "run-bad" / "checkpoint.json").write_text("][", encoding="utf-8")
    for s in (absent, empty, junk):
        for extra in ([], ["--json"]):
            rc, out, err = _call(capsys, ["trace", "--state-dir", str(s), *extra])
            assert (rc, out, err) == (2, "", f"error: no runs with a checkpoint under {s}\n"), (s, extra)
            assert "usage:" not in err and _TRACEBACK not in err


def _b6_b7_file_state_dir_and_explicit_run_dir(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # B6: a regular file as state dir -> the same guard line `runs` prints.
    f = tmp_path / "afile"
    f.write_text("x", encoding="utf-8")
    rc, out, err = _call(capsys, ["trace", "--state-dir", str(f)])
    rrc, _rout, rerr = _call(capsys, ["runs", "--state-dir", str(f)])
    assert rc == 2 and out == ""
    assert err == rerr and rrc == 2
    assert len(err.splitlines()) == 1 and _TRACEBACK not in err
    # B7: explicit empty --run-dir keeps its HEAD message; never a newest line.
    s = tmp_path / "state"
    _save(s, "run-real", _utc(1), "goal real")
    empty = tmp_path / "emptyrun"
    empty.mkdir()
    rc, out, err = _call(capsys, ["trace", "--state-dir", str(s), "--run-dir", str(empty)])
    assert rc == 2 and out == ""
    assert f"error: no checkpoint found in {empty}" in err
    assert _NEWEST not in err
    rc, out, err = _call(capsys, ["trace", "--run-dir", str(s / "run-real"), "--json"])
    assert rc == 0 and err == "" and isinstance(json.loads(out), list)


def _b8_docs_match_parser(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc, out, _ = _call(capsys, ["trace", "--help"])
    assert rc == 0
    assert "[--run-dir RUN_DIR]" in " ".join(out.split())
    assert "newest run" in " ".join(out.split())
    spec = (REPO / "SPEC.md").read_text(encoding="utf-8")
    assert "`pla trace [--run-dir DIR] [--json]`" in spec
    assert "`pla trace --run-dir DIR" not in spec
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    below = readme.split("PORTFOLIO INTRO", 1)[1]
    cli = below.split("## CLI", 1)[1]
    rows = [ln for ln in cli.splitlines() if ln.startswith("|") and "`trace" in ln.split("|")[1]]
    assert rows, "README ## CLI has no trace row"
    row = rows[0]
    assert "created_at" in row and "newest" in row
    assert "required" not in row.lower()


def iter587_trace_newest(capsys: pytest.CaptureFixture[str], root: Path) -> int:
    """Drive all eight spec behaviors, each on its own sub-dir of ``root``;
    returns how many behavior groups ran.

    Called by ``test_trace_defaults_to_newest_run``, this module's one collected test.
    """
    checks = (
        _b1_b2_newest_by_created_at_then_by_name,
        _b3_b4_json_is_clean_and_unreadable_runs_are_skipped,
        _b5_nothing_to_trace_is_clean_exit_2,
        _b6_b7_file_state_dir_and_explicit_run_dir,
        _b8_docs_match_parser,
    )
    for i, check in enumerate(checks):
        sub = root / f"b{i}"
        sub.mkdir(parents=True)
        check(sub, capsys)
    return len(checks)


def test_trace_defaults_to_newest_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Own collected item (no longer hosted in test_iter317), so a regression is reported
    under THIS behavior's name and cannot hide the other harnesses."""
    for key in list(os.environ):
        if key.startswith("PLA_"):
            monkeypatch.delenv(key, raising=False)
    assert iter587_trace_newest(capsys, tmp_path / "h") == 5
