"""Black-box oracle for factory iteration 317 (foundry state iter-569) --
``pla runs --older-than DAYS`` narrows the selection by persisted checkpoint age.

The filter keys on the checkpoint's ``created_at``: a run older than DAYS days is
selected (a naive timestamp is read as UTC), a fresh run is not, and a run with no
readable checkpoint is NEVER selected (fail closed on the only destructive path).
It applies to the listing, ``--json``, ``--summary`` and ``--prune`` alike, composes
with ``--status`` / ``--goal``, validates at parse time (exit 2), and is documented
in ``runs --help``, the README ``## CLI`` row and the SPEC usage line.

ISOLATION CONTRACT (honored): written from the iteration spec (``pm.md``),
``README.md``, ``SPEC.md`` and the conventions under ``tests/``. It drives ONLY the
public ``proactive_loop.cli.main(argv)`` entry against a PRIVATE state dir built in
``tmp_path`` (no mtimes involved -- age comes from the persisted ``created_at``).
No implementation logic was read, no engineer/reviewer note, no git diff.

ONE collected item on purpose: binding_headroom is pinned (test_iter263 /
test_iter270), so each behavior is a private ``_bN`` half.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Final

import pytest

from proactive_loop import cli
from proactive_loop.models import CandidateGoal, RunState

REPO: Final = Path(__file__).resolve().parents[1]
README: Final = REPO / "README.md"
SPEC: Final = REPO / "SPEC.md"
CHECKPOINT: Final = "checkpoint.json"
OLD: Final = ["run-naive", "run-old"]
EMPTY: Final = "no runs found under the state dir."


def _write(sd: Path, run_id: str, title: str, created_at: str | None) -> None:
    run_dir = sd / run_id
    run_dir.mkdir(parents=True)
    data = json.loads(RunState(goal=CandidateGoal(title=title), status="done").model_dump_json())
    if created_at is not None:
        data["created_at"] = created_at
    (run_dir / CHECKPOINT).write_text(json.dumps(data), encoding="utf-8")


def _state_dir(root: Path) -> Path:
    sd = root / "state"
    _write(sd, "run-old", "old goal", "2000-01-01T00:00:00Z")
    _write(sd, "run-naive", "naive goal", "2000-01-01T00:00:00")
    _write(sd, "run-new", "new goal", None)
    (sd / "run-broken").mkdir()
    (sd / "run-broken" / CHECKPOINT).write_text("{", encoding="utf-8")
    return sd


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    capsys.readouterr()
    try:
        rc = cli.main(list(argv))
    except SystemExit as exc:  # argparse parse-time exits
        rc = exc.code if isinstance(exc.code, int) else 1
    out, err = capsys.readouterr()
    return rc, out, err


def _ids(rows: object) -> list[str]:
    assert isinstance(rows, list), rows
    return [row["run_id"] for row in rows]


def _b1_b2_listing(capsys: pytest.CaptureFixture[str], sd: Path) -> None:
    rc, out, err = _run(capsys, "runs", "--older-than", "30", "--state-dir", str(sd))
    assert rc == 0, (rc, out, err)
    assert err == "", err  # B2: naive timestamp raises nothing
    assert "run-old" in out and "run-naive" in out, out
    assert "run-new" not in out and "run-broken" not in out, out
    assert out.index("run-naive") < out.index("run-old"), out
    # Same column layout as the plain listing: every filtered line appears verbatim there.
    rc0, plain, _ = _run(capsys, "runs", "--state-dir", str(sd))
    assert rc0 == 0
    plain_lines = plain.splitlines()
    for line in out.splitlines():
        assert line in plain_lines, (line, plain)
    rows = [ln for ln in out.splitlines() if "run-" in ln]
    assert len(rows) == 2, out


def _b3_json(capsys: pytest.CaptureFixture[str], sd: Path) -> None:
    rc, out, _ = _run(capsys, "runs", "--older-than", "30", "--json", "--state-dir", str(sd))
    assert rc == 0
    rows = json.loads(out)
    assert _ids(rows) == OLD, rows
    rc, plain, _ = _run(capsys, "runs", "--json", "--state-dir", str(sd))
    plain_rows = json.loads(plain)
    keys = {frozenset(r) for r in plain_rows}
    assert {frozenset(r) for r in rows} <= keys, (rows, plain_rows)
    assert len(keys) >= 1


def _b4_summary(capsys: pytest.CaptureFixture[str], sd: Path) -> None:
    rc, out, _ = _run(capsys, "runs", "--older-than", "30", "--summary", "--json", "--state-dir", str(sd))
    assert rc == 0, out
    obj = json.loads(out)
    assert obj["runs"] == 2 and obj["by_status"] == {"done": 2}, obj


def _b5_compose(capsys: pytest.CaptureFixture[str], sd: Path) -> None:
    rc, out, _ = _run(capsys, "runs", "--older-than", "30", "--status", "failed", "--state-dir", str(sd))
    assert rc == 0 and out.strip() == EMPTY, (rc, out)
    rc, out, _ = _run(capsys, "runs", "--older-than", "30", "--goal", "old", "--json", "--state-dir", str(sd))
    assert rc == 0 and _ids(json.loads(out)) == ["run-old"], out


def _b6_dry_run(capsys: pytest.CaptureFixture[str], sd: Path) -> None:
    rc, out, _ = _run(capsys, "runs", "--older-than", "30", "--prune", "--json", "--state-dir", str(sd))
    assert rc == 0, out
    obj = json.loads(out)
    assert obj["dry_run"] is True and obj["selected"] == OLD, obj
    assert obj["refused"] == [] and obj["deleted"] == 0, obj
    for rid in ("run-old", "run-naive", "run-new", "run-broken"):
        assert (sd / rid).is_dir(), rid


def _b8_validation(capsys: pytest.CaptureFixture[str], sd: Path) -> None:
    for bad in ("0", "-1", "nan", "inf", "abc"):
        rc, out, err = _run(capsys, "runs", f"--older-than={bad}", "--state-dir", str(sd))
        assert rc == 2, (bad, rc, out, err)
        assert out == "", (bad, out)
        assert "argument --older-than" in err, (bad, err)
        if bad == "0":
            assert "must be a positive number (> 0), got 0" in err, err
    rc, out, _ = _run(capsys, "runs", "--older-than", "0.5", "--json", "--state-dir", str(sd))
    assert rc == 0 and _ids(json.loads(out)) == OLD, out


def _b7_prune_yes(capsys: pytest.CaptureFixture[str], sd: Path) -> None:
    rc, out, err = _run(capsys, "runs", "--older-than", "30", "--prune", "--yes", "--state-dir", str(sd))
    assert rc == 0, (rc, out, err)
    assert out.startswith("pruned 2 run dir(s):"), out
    assert "run-naive" in out and "run-old" in out, out
    remaining = sorted(p.name for p in sd.iterdir() if p.name.startswith("run-"))
    assert remaining == ["run-broken", "run-new"], remaining


def _b10_docs(capsys: pytest.CaptureFixture[str]) -> None:
    rc, out, _ = _run(capsys, "runs", "--help")
    assert rc == 0 and "--older-than DAYS" in out, out
    readme = README.read_text(encoding="utf-8")
    row = next(ln for ln in readme.splitlines() if ln.startswith("| `runs`"))
    assert "`--older-than DAYS`" in row, row
    prune_clause = row.split("`--prune` turns", 1)[1]
    assert "--older-than" in prune_clause.split("deletes nothing", 1)[1].split("is contained", 1)[0], row
    spec = SPEC.read_text(encoding="utf-8")
    usage = next(ln for ln in spec.splitlines() if "`pla runs [" in ln)
    assert "[--older-than DAYS]" in usage, usage


def test_runs_older_than_filters_by_checkpoint_age(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    for key in list(os.environ):
        if key.startswith("PLA_"):
            monkeypatch.delenv(key, raising=False)
    sd = _state_dir(tmp_path)
    _b1_b2_listing(capsys, sd)
    _b3_json(capsys, sd)
    _b4_summary(capsys, sd)
    _b5_compose(capsys, sd)
    _b6_dry_run(capsys, sd)
    _b8_validation(capsys, sd)
    _b10_docs(capsys)
    _b7_prune_yes(capsys, sd)  # destructive: last
