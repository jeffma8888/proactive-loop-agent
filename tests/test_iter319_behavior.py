"""Black-box behavior tests for iteration 319 (foundry iter 327).

Feature under test: ``pla runs --json`` rows carry ``created_at`` -- the run
checkpoint's creation timestamp as an ISO-8601 string (exactly
``RunState.created_at.isoformat()``), or JSON ``null`` when the run has no readable
checkpoint. It is the field ``runs --older-than`` already filters on. The human table
and ``--summary`` are unchanged.

ISOLATION CONTRACT (honored): written strictly against this iteration's spec
"Expected Behaviors" and ``README.md``; drives only the public ``pla`` CLI via
``proactive_loop.cli.main([...])``. No file under ``src/`` was read, no
engineer/reviewer notes were read, no ``git diff`` was consulted. Every state dir is a
fresh ``tmp_path``; the only non-fabricated run comes from the offline scripted
provider. Ages come from the persisted ``created_at`` (never from mtimes), so a fresh
clone sees the same tree.

ONE collected item on purpose: the README suite-size gauge sat at
``binding_headroom=6`` (the floor ``test_iter263::test_b6`` pins), so this module is
paired with a net-zero fold elsewhere and keeps every behavior as a helper.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

import pytest

from proactive_loop import cli
from proactive_loop.models import CandidateGoal, RunState
from tests.test_iter04_behavior import _make_run_dir, _produce_demo_run

REPO: Final = Path(__file__).resolve().parents[1]
README: Final = REPO / "README.md"
MARKER: Final = "PORTFOLIO INTRO \u2014 human-owned"
CHECKPOINT: Final = "checkpoint.json"
ROW_KEYS: Final = {
    "run_id", "status", "goal", "iterations", "artifacts", "workspace", "retries",
    "parse_errors", "created_at",
}
SUMMARY_KEYS: Final = {"runs", "by_status", "iterations", "artifacts", "retries", "parse_errors"}
NOW: Final = datetime.now(UTC).replace(microsecond=0)
OLD_AT: Final = NOW - timedelta(days=30)
NEW_AT: Final = NOW - timedelta(minutes=5)


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    capsys.readouterr()
    try:
        rc = cli.main(list(argv))
    except SystemExit as exc:  # argparse parse-time exits
        rc = exc.code if isinstance(exc.code, int) else 1
    out, err = capsys.readouterr()
    return rc, out, err


def _plant(sd: Path, run_id: str, title: str, status: str, created_at: datetime) -> None:
    run_dir = sd / run_id
    run_dir.mkdir(parents=True)
    state = RunState(goal=CandidateGoal(title=title), status=status, created_at=created_at)
    (run_dir / CHECKPOINT).write_text(state.model_dump_json(), encoding="utf-8")


def _state_dir(root: Path) -> Path:
    sd = root / "state"
    sd.mkdir()
    _produce_demo_run(sd)
    _plant(sd, "run-old", "ancient archival goal", "done", OLD_AT)
    _plant(sd, "run-new", "fresh archival goal", "failed", NEW_AT)
    _make_run_dir(sd, "run-nocheckpoint", artifact_files=["a.txt"])
    (sd / "run-broken").mkdir()
    (sd / "run-broken" / CHECKPOINT).write_text("{", encoding="utf-8")
    return sd


def _rows(capsys: pytest.CaptureFixture[str], sd: Path, *extra: str) -> list[dict]:
    rc, out, err = _run(capsys, "runs", "--state-dir", str(sd), "--json", *extra)
    assert rc == 0, (rc, out, err)
    rows = json.loads(out)
    assert isinstance(rows, list), out
    return rows


def _persisted(sd: Path, run_id: str) -> RunState:
    return RunState.model_validate_json((sd / run_id / CHECKPOINT).read_text(encoding="utf-8"))


def _b1_b2_b3(capsys: pytest.CaptureFixture[str], sd: Path) -> None:
    rows = {row["run_id"]: row for row in _rows(capsys, sd)}
    degraded = {"run-nocheckpoint", "run-broken"}
    healthy = sorted(p.name for p in sd.glob("run-*") if p.name not in degraded)
    assert len(healthy) == 3, healthy  # demo run + run-old + run-new
    assert set(rows) == set(healthy) | degraded, sorted(rows)
    for run_id in healthy:
        row, state = rows[run_id], _persisted(sd, run_id)
        value = row["created_at"]
        assert isinstance(value, str), (run_id, row)
        assert value == state.created_at.isoformat(), (run_id, value)
        assert datetime.fromisoformat(value) == state.created_at, (run_id, value)
        assert datetime.fromisoformat(value).tzinfo is not None, value
        # B3: the pre-existing values still describe the same persisted run.
        assert row["status"] == state.status, (run_id, row)
        assert row["goal"] == state.goal.title, (run_id, row)
    assert datetime.fromisoformat(rows["run-old"]["created_at"]) == OLD_AT
    assert datetime.fromisoformat(rows["run-new"]["created_at"]) == NEW_AT
    for run_id in ("run-nocheckpoint", "run-broken"):
        assert rows[run_id]["created_at"] is None, rows[run_id]
        assert "created_at" in rows[run_id], rows[run_id]
    for run_id, row in rows.items():
        assert set(row) == ROW_KEYS, (run_id, sorted(row))
    assert rows["run-nocheckpoint"]["artifacts"] == 1, rows["run-nocheckpoint"]


def _b4_compose(capsys: pytest.CaptureFixture[str], sd: Path) -> None:
    old = _rows(capsys, sd, "--older-than", "7")
    assert [row["run_id"] for row in old] == ["run-old"], old
    assert datetime.fromisoformat(old[0]["created_at"]) == OLD_AT, old
    assert set(old[0]) == ROW_KEYS, old
    failed = _rows(capsys, sd, "--status", "failed")
    assert [row["run_id"] for row in failed] == ["run-new"], failed
    assert datetime.fromisoformat(failed[0]["created_at"]) == NEW_AT, failed
    archival = _rows(capsys, sd, "--goal", "ARCHIVAL")
    assert sorted(row["run_id"] for row in archival) == ["run-new", "run-old"], archival
    assert _rows(capsys, sd, "--goal", "archival", "--older-than", "7", "--status", "failed") == []


def _b5_human_table(capsys: pytest.CaptureFixture[str], sd: Path) -> None:
    rc, out, err = _run(capsys, "runs", "--state-dir", str(sd))
    assert rc == 0, (rc, out, err)
    assert "run-old" in out and "run-broken" in out, out
    assert "created_at" not in out, out
    for run_id in ("run-old", "run-new"):
        stamp = _persisted(sd, run_id).created_at.isoformat()
        assert stamp not in out, (stamp, out)
        assert stamp[:19] not in out, (stamp, out)


def _b6_summary(capsys: pytest.CaptureFixture[str], sd: Path) -> None:
    rc, out, err = _run(capsys, "runs", "--state-dir", str(sd), "--summary", "--json")
    assert rc == 0, (rc, out, err)
    payload = json.loads(out)
    assert isinstance(payload, dict), out
    assert set(payload) == SUMMARY_KEYS, sorted(payload)
    assert payload["runs"] == 5, payload
    assert "created_at" not in out, out


def _b7_determinism(capsys: pytest.CaptureFixture[str], sd: Path) -> None:
    first = _run(capsys, "runs", "--state-dir", str(sd), "--json")
    second = _run(capsys, "runs", "--state-dir", str(sd), "--json")
    assert first[0] == 0, first
    assert first == second, (first, second)


def _b8_readme() -> None:
    text = README.read_text(encoding="utf-8")
    assert MARKER in text
    below = text.split(MARKER, 1)[1]
    rows = [line for line in below.splitlines() if line.startswith("| `runs`")]
    assert len(rows) == 1, rows
    row = rows[0]
    assert "rows carry `created_at`" in row, row
    clause = row.split("rows carry `created_at`", 1)[1]
    assert "ISO-8601" in clause and "--older-than" in clause and "null" in clause, clause


def test_runs_json_rows_carry_created_at(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """Behaviors 1-8: `runs --json` rows publish `created_at` (ISO-8601 or null),
    with an exact 9-key row, unchanged composition, human table and summary,
    byte-stable output and a README row that documents it."""
    sd = _state_dir(tmp_path)
    _b1_b2_b3(capsys, sd)
    _b4_compose(capsys, sd)
    _b5_human_table(capsys, sd)
    _b6_summary(capsys, sd)
    _b7_determinism(capsys, sd)
    _b8_readme()
