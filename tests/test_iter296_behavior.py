"""Black-box behavior tests for state-dir iteration 547 (ships as ``foundry iter 547``):
``make demo`` STAMPS THE FIXTURE'S MTIMES NOW, SO THE CI ``--baseline`` ROUND TRIP
CANNOT STRADDLE A ``recent_files`` WEIGHT EDGE.

CI run 41129475742 went red on its 3.13 leg at the round-trip step with five
``recent_file`` rows and ``count=5 budget=0``: ``weight`` is a ``--baseline``
identity key, ``recent_files`` rounds ``1 - age/14d`` to 4 dp (one step is
120.96 s, the first edge 60.48 s), and a fresh clone stamps every fixture file at
checkout, so the demo's snapshot and the round trip read seconds apart could land
either side of the edge. The fix is one ``demo`` recipe step that stamps the
fixture NOW before ``pla run`` snapshots it.

Every test here owns its mtimes on a ``tmp_path`` copy of the fixture (never the
tracked tree, whose mtimes are ambient state) and drives the CLI in-process: no
network, no ``uv``/``make`` child.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import time
from pathlib import Path

from proactive_loop.cli import main
from tests.test_iter198_behavior import _demo

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "examples" / "fixture_workspace"
STAMP_STEP = "find examples/fixture_workspace -type f -exec touch {} +"


def _copy_fixture(tmp_path: Path) -> tuple[Path, list[Path]]:
    workspace = tmp_path / "examples" / "fixture_workspace"
    shutil.copytree(FIXTURE, workspace)
    return workspace, sorted(p for p in workspace.rglob("*") if p.is_file())


def _stamp_age(files: list[Path], age_seconds: float) -> None:
    when = time.time() - age_seconds
    for path in files:
        os.utime(path, (when, when))


def _round_trip(workspace: Path, tmp_path: Path, capsys) -> tuple[Path, list[dict]]:
    """Record ``signals --json`` as a baseline file; return its path and signals."""
    capsys.readouterr()
    assert main(["signals", "--workspace", str(workspace), "--json"]) == 0
    baseline = tmp_path / "baseline.json"
    baseline.write_text(capsys.readouterr().out, encoding="utf-8")
    return baseline, json.loads(baseline.read_text(encoding="utf-8"))["signals"]


def _consume(workspace: Path, baseline: Path, capsys) -> tuple[int, str]:
    capsys.readouterr()
    rc = main(
        ["signals", "--workspace", str(workspace), "--baseline", str(baseline),
         "--fail-over", "0"]
    )
    cap = capsys.readouterr()
    return rc, cap.out + cap.err


def test_b1_demo_stamps_the_fixture_once_before_it_snapshots() -> None:
    recipe = _demo()
    stamps = [i for i, step in enumerate(recipe) if step == STAMP_STEP]
    assert len(stamps) == 1, f"exactly one {STAMP_STEP!r} step expected: {recipe!r}"
    runners = [i for i, step in enumerate(recipe) if "pla run " in step]
    assert len(runners) == 1 and "--snapshot" in recipe[runners[0]], recipe
    assert stamps[0] < runners[0], (
        f"the stamp must run BEFORE the snapshotting `pla run`: {recipe!r}"
    )
    # EB1 positions: exactly 12 logical steps, mkdir first, stamp second, run third.
    assert len(recipe) == 12, recipe
    assert recipe[0] == "mkdir -p .pla_runs", recipe[0]
    assert stamps[0] == 1 and runners[0] == 2, recipe
    assert recipe[2].endswith("--snapshot .pla_runs/snapshot.json --json > .pla_runs/run.json")
    # EB5: the WHY comments name the edge and the red run; the CI command is unchanged.
    makefile = (REPO / "Makefile").read_text(encoding="utf-8")
    head = makefile.split("\ndemo:", 1)[0].rsplit("\n\n", 1)[-1]
    assert "60.48" in head and "41129475742" in head, head
    ci = (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    trip = ("run: uv run pla signals --workspace examples/fixture_workspace "
            "--baseline .pla_runs/snapshot.json --fail-over 0")
    assert ci.count(trip) == 1, "the CI round-trip command must stay byte-identical"
    graded = [ln for ln in ci.splitlines() if ln.strip().startswith("run:")]
    assert len(graded) == 10, graded


def test_b2_the_stamp_step_makes_the_round_trip_non_vacuous_and_green(
    tmp_path: Path, capsys
) -> None:
    workspace, files = _copy_fixture(tmp_path)
    _stamp_age(files, 30 * 86_400.0)  # a warm tree: older than the 14-day window
    before = {p: p.read_bytes() for p in files}
    argv = shlex.split(STAMP_STEP)
    assert argv[0] == "find" and argv[1] == "examples/fixture_workspace", argv
    subprocess.run(argv, cwd=tmp_path, check=True, timeout=30)
    now = time.time()
    assert all(now - p.stat().st_mtime < 30 for p in files), "stamp left a file old"
    assert {p: p.read_bytes() for p in files} == before, "stamp changed file content"
    baseline, recorded = _round_trip(workspace, tmp_path, capsys)
    recent = [s for s in recorded if s["kind"] == "recent_file"]
    assert len(recent) == 5, f"control arm: 5 fresh recent_file rows expected: {recent}"
    assert {s["weight"] for s in recent} == {1.0}, recent
    rc, out = _consume(workspace, baseline, capsys)
    assert rc == 0, f"same-run round trip after the stamp must exit 0; got {rc}: {out}"


def test_b3_without_the_stamp_a_weight_edge_crossing_reds_the_round_trip(
    tmp_path: Path, capsys
) -> None:
    """The CI failure, reproduced without sleeping: record at 55 s old, consume
    at 65 s old -- either side of the 60.48 s edge -- and all five rows miss."""
    workspace, files = _copy_fixture(tmp_path)
    _stamp_age(files, 55.0)
    baseline, _recorded = _round_trip(workspace, tmp_path, capsys)
    _stamp_age(files, 65.0)
    rc, out = _consume(workspace, baseline, capsys)
    assert rc == 5, f"an edge crossing must trip the gate (exit 5); got {rc}: {out}"
    assert "count=5 budget=0" in out, out
