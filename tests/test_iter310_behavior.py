"""Factory iter 562 (ROADMAP #350): ``run --skip-done`` / ``runs --prune`` decide from checkpoints alone.

The two history-read selection paths -- ``_done_runs_by_title`` (``run --skip-done``) and
``_select_prunable`` (``runs --prune --status/--goal``) -- used to build a full ``_run_row`` per
run dir, so every decision also parsed ``meta.json`` and walked ``artifacts/``. They now share one
tolerant checkpoint loader with ``_run_row`` via ``_run_status_goal`` and read each checkpoint at
most once, with NO change to any output.

Black-box: the private helpers named by the spec are called directly, ``pla run`` and
``pla runs`` are driven in-process through ``cli.main``, and the "never touches meta/artifacts"
claim is proven by monkeypatching ``cli._read_meta`` / ``cli._count_artifacts`` to stubs that
raise. ONE collected item (``make readme-headroom`` reads binding_headroom=6), funded by the
test_iter145 parametrize fold. Offline and deterministic: scripted provider, no subprocess, and
the fixture workspace is a private ``tmp_path`` copy stamped to one known age (fresh-clone safe).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
from pathlib import Path
from typing import Final

import pytest

from proactive_loop import cli
from proactive_loop.loop import Checkpoint
from proactive_loop.models import CandidateGoal, RunState, RunStatus

REPO: Final = Path(__file__).resolve().parents[1]
CLI_SRC: Final = REPO / "src" / "proactive_loop" / "cli.py"
FIXTURE: Final = REPO / "examples" / "fixture_workspace"
SCRIPT: Final = REPO / "examples" / "scripted_responses.json"
CHECKPOINT: Final = "checkpoint.json"
NO_CHECKPOINT: Final = ("(no checkpoint)", "")
TOP: Final = "Draft a learning plan and project scaffold for the agentic-loop project"
OTHER: Final = "Write an eval checklist for the agentic-loop harness"
SKIP_PREFIX: Final = "skipped (already done): "
HEX_ID: Final = re.compile(r"\b[0-9a-f]{12}\b")
STAMP_AGE_SEC: Final = 6 * 60 * 60
CHECKPOINT_CTOR_AT_HEAD: Final = 4
GOAL_SUB: Final = "LEARNING PLAN"  # substring of a done title, in the other case


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


def _persist(run_dir: Path, status: RunStatus, title: str) -> None:
    run_dir.mkdir(parents=True)
    state = RunState(
        goal=CandidateGoal(title=title, rationale="r", suggested_first_steps=["draft notes.md"]),
        status=status,
        artifacts_dir=str(run_dir / "artifacts"),
    )
    Checkpoint(run_dir / CHECKPOINT).save(state)
    (run_dir / "meta.json").write_text(json.dumps({"workspace_root": "/w", "note": "planted"}), encoding="utf-8")
    nested = run_dir / "artifacts" / "sub"
    nested.mkdir(parents=True)
    (nested / "file.txt").write_text("x", encoding="utf-8")


def _state_dir(root: Path) -> Path:
    """The behavior-3 fixture: 2 case/padding-variant done runs, 1 failed, 1 corrupt, 1 empty, 1 file."""
    sd = root / "state"
    _persist(sd / "run-a", RunStatus.DONE, TOP)
    _persist(sd / "run-b", RunStatus.DONE, "  " + TOP.upper() + " ")
    _persist(sd / "run-c", RunStatus.FAILED, OTHER)
    (sd / "run-d").mkdir()
    (sd / "run-d" / CHECKPOINT).write_text('{"goal": {"title": "trunc', encoding="utf-8")
    (sd / "run-e").mkdir()
    (sd / "run-x").write_text("not a run dir", encoding="utf-8")
    return sd


def _boom(*_a: object, **_k: object) -> object:
    raise AssertionError("selection path touched meta.json / artifacts/")


def _run(capsys: pytest.CaptureFixture[str], ws: Path, sd: Path) -> tuple[int, str, str]:
    (sd / "slate.json").unlink(missing_ok=True)
    capsys.readouterr()
    rc = cli.main(
        [
            "run", "--workspace", str(ws), "--provider", "scripted", "--scripted-responses", str(SCRIPT),
            "--state-dir", str(sd), "--skip-done", "--dry-run",
        ]
    )
    out = capsys.readouterr()
    return rc, HEX_ID.sub("<id>", out.out), HEX_ID.sub("<id>", out.err)


def _names(result: tuple[list[Path], list[str]]) -> tuple[list[str], list[str]]:
    selected, refused = result
    return [p.name for p in selected], list(refused)


def test_b01_to_b07_skip_done_and_prune_decide_from_checkpoints_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _clean_env(monkeypatch)
    sd = _state_dir(tmp_path)
    ws = _workspace(tmp_path)
    run_dirs = sorted(p for p in sd.glob("run-*") if p.is_dir())

    # B1: the tolerant loader returns (status, title) or the shared no-checkpoint marker; never raises.
    assert cli._run_status_goal(sd / "run-a") == ("done", TOP)
    assert cli._run_status_goal(sd / "run-c") == ("failed", OTHER)
    assert cli._run_status_goal(sd / "run-d") == NO_CHECKPOINT, "corrupt checkpoint"
    assert cli._run_status_goal(sd / "run-e") == NO_CHECKPOINT, "missing checkpoint"
    assert cli._run_status_goal(sd / "run-missing") == NO_CHECKPOINT, "missing run dir"

    # B2: _run_row agrees with the loader for every run dir; `runs --json` still carries meta/artifacts.
    rows = {d.name: cli._run_row(d) for d in run_dirs}
    for d in run_dirs:
        assert (rows[d.name]["status"], rows[d.name]["goal"]) == cli._run_status_goal(d), d.name
    assert rows["run-a"]["artifacts"] == 1 and rows["run-a"]["workspace"] == "/w", rows["run-a"]
    capsys.readouterr()
    assert cli.main(["runs", "--state-dir", str(sd), "--json"]) == 0
    listed = json.loads(capsys.readouterr().out)
    listed_rows = listed if isinstance(listed, list) else listed["runs"]
    assert {r["run_id"]: r for r in listed_rows} == rows, "runs --json must be the _run_row dicts"

    # B3: only done titles, keyed by _normalize_title; the name-sorted first run id wins.
    expected_done = {cli._normalize_title(TOP): "run-a"}
    assert cli._normalize_title("  " + TOP.upper() + " ") == cli._normalize_title(TOP)
    assert cli._done_runs_by_title(sd) == expected_done

    # Baselines without stubs (B4 CLI output, B5 prune results).
    base_cli = _run(capsys, ws, sd)
    assert base_cli[0] == 0, base_cli
    assert f"{SKIP_PREFIX}{TOP} -> run-a" in base_cli[1], base_cli[1]
    combos: list[tuple[str | None, str | None]] = [(None, None), ("done", None), (None, GOAL_SUB), ("done", GOAL_SUB)]
    link = sd / "run-z"
    link.symlink_to(sd / "run-a", target_is_directory=True)
    base_prune = {c: _names(cli._select_prunable(sd, c[0], c[1])) for c in combos}
    assert base_prune == {
        (None, None): (["run-a", "run-b", "run-c", "run-d", "run-e"], ["run-z"]),
        ("done", None): (["run-a", "run-b"], ["run-z"]),
        (None, GOAL_SUB): (["run-a", "run-b"], ["run-z"]),
        ("done", GOAL_SUB): (["run-a", "run-b"], ["run-z"]),
    }, base_prune
    link.unlink()

    # B4/B5: with meta + artifact readers raising, skip-done and prune give identical results.
    with monkeypatch.context() as m:
        m.setattr(cli, "_read_meta", _boom)
        m.setattr(cli, "_count_artifacts", _boom)
        assert cli._done_runs_by_title(sd) == expected_done
        assert _run(capsys, ws, sd) == base_cli, "run --skip-done --dry-run output changed under stubs"
        link.symlink_to(sd / "run-a", target_is_directory=True)
        for c in combos:
            assert _names(cli._select_prunable(sd, c[0], c[1])) == base_prune[c], c

        # B6: both filters set -> Checkpoint.load at most once per candidate run dir.
        calls: list[str] = []
        real_load = Checkpoint.load

        def counting_load(self: Checkpoint) -> RunState:
            calls.append(str(getattr(self, "path", id(self))))
            return real_load(self)

        m.setattr(cli.Checkpoint, "load", counting_load)
        assert _names(cli._select_prunable(sd, "done", GOAL_SUB)) == base_prune[("done", GOAL_SUB)]
        assert calls, "the prune filters must read checkpoints through Checkpoint.load"
        repeats = sorted({c for c in calls if calls.count(c) > 1})
        assert not repeats, f"checkpoint read more than once per candidate: {repeats}"
    link.unlink()

    # B7: no second checkpoint parser, and docstrings name the shared loader, not _run_row.
    assert CLI_SRC.read_text(encoding="utf-8").count("Checkpoint(") <= CHECKPOINT_CTOR_AT_HEAD
    for fn, stale in ((cli._done_runs_by_title, "Built on `_run_row`"), (cli._select_prunable, "reuses `_run_row`")):
        doc = " ".join((fn.__doc__ or "").split())
        assert doc, fn.__name__
        assert stale not in doc, (fn.__name__, doc)
        assert "_run_status_goal" in doc or "loader" in doc, (fn.__name__, doc)
