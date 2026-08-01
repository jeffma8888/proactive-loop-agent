"""Black-box behavior tests for iteration 71 --- ``pla runs --json`` rows now
surface the two persisted resilience counters ``retries`` and ``parse_errors``,
so a CI/monitoring script can flag throttle- or garbage-pressured runs across a
whole fleet in one machine-readable call (ROADMAP #72, scoped to ``runs --json``).

Feature under test (SPEC 4.5 ``pla runs [--json]``): iters 08/25/60/68/69 built
the "resilient by design" observability arc --- ``RunState.retries`` (L0 throttle
self-healing) and ``RunState.parse_errors`` (L1 malformed-PLAN/CHECK fail-safe)
are now persisted on every checkpoint and rendered in the human ``run summary``
and the human ``trace`` header. This iteration lands the last-mile: the one
MACHINE-READABLE run inventory, ``pla runs --json``, gains both counters on every
row (previously it emitted only the six keys
``{run_id, status, goal, iterations, artifacts, workspace}``). It is a
defaulted-additive change to a documented-tolerant JSON surface (the iter-04
contract is ``required.issubset(row.keys())``): the human ``runs`` table is
byte-stable, ``trace --json`` is untouched, and there is no version bump.

ISOLATION CONTRACT (honored): every assertion here is written strictly against
THIS iteration's public contract --- the spec's "Expected Behaviors" (``pm.md``),
``README.md``, and ``SPEC.md`` --- and drives ONLY the documented public surface:
the ``pla`` CLI via ``proactive_loop.cli.main([...])``, plus the public
``proactive_loop.loop.Checkpoint`` / ``proactive_loop.models.RunState`` seam to
persist offline run dirs (exactly as ``tests/test_iter69_behavior.py`` and
``tests/test_iter04_behavior.py`` do). **No file under ``src/`` was read, no
engineer/reviewer notes were read, and no ``git diff`` was consulted** to author
these assertions --- field/method names come from the public model schema,
``SPEC.md``, and the two published reference suites. Every test is fully offline:
zero network, zero API keys; run dirs are synthetic ``tmp_path`` (never the
repo's ``.pla_runs/``), and asserted counter values are DERIVED from the values
the test itself persists, never hard-coded against implementation quirks.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from proactive_loop import __version__
from proactive_loop.cli import main
from proactive_loop.loop import Checkpoint
from proactive_loop.models import (
    CandidateGoal,
    LoopStep,
    RunState,
    RunStatus,
    StepKind,
)

_CHECKPOINT_NAME = "checkpoint.json"
_NO_CHECKPOINT = "(no checkpoint)"
# The exact documented per-row key set AFTER this iteration (Behavior 4): the six
# pre-existing keys + the two new resilience counters, nothing else.
_EXPECTED_ROW_KEYS = {
    "run_id",
    "status",
    "goal",
    "iterations",
    "artifacts",
    "workspace",
    "retries",
    "parse_errors",
}


# ---------------------------------------------------------------------------
# Helpers (same public Checkpoint/RunState seam tests/test_iter69_behavior.py
# and tests/test_iter04_behavior.py use --- no src/ read).
# ---------------------------------------------------------------------------


def _goal(title: str = "Inspect the retriever pipeline") -> CandidateGoal:
    return CandidateGoal(
        title=title,
        rationale="capture next steps",
        suggested_first_steps=["draft learning_plan.md"],
    )


def _run(argv: list[str], capsys) -> tuple[int, str, str]:
    """Invoke the CLI and return (rc, stdout, stderr), draining capsys first so
    prior setup output never leaks into the assertion window."""
    capsys.readouterr()
    rc = main(argv)
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def _persist_run(
    run_dir: Path,
    *,
    retries: int,
    parse_errors: int,
    status: RunStatus = RunStatus.DONE,
    iterations_used: int = 2,
    llm_calls_used: int = 4,
    title: str = "Inspect the retriever pipeline",
) -> RunState:
    """Persist a RunState (with known retries/parse_errors counts) via the public
    Checkpoint --- the same setup path the iter-04/08/69 tests use. No network."""
    run_dir.mkdir(parents=True, exist_ok=True)
    state = RunState(
        goal=_goal(title),
        status=status,
        steps=[
            LoopStep(index=0, kind=StepKind.PLAN, output="thought: locate module"),
            LoopStep(index=1, kind=StepKind.ACT, output="list_files -> a.py", artifacts=[]),
            LoopStep(index=2, kind=StepKind.CHECK, output="reason: complete", done=True),
        ],
        iterations_used=iterations_used,
        llm_calls_used=llm_calls_used,
        retries=retries,
        parse_errors=parse_errors,
        artifacts_dir=str(run_dir / "artifacts"),
    )
    Checkpoint(run_dir / _CHECKPOINT_NAME).save(state)
    return state


def _rows(state_dir: Path, capsys) -> list[dict]:
    """`pla runs --state-dir <dir> --json` -> parsed JSON array (asserts exit 0
    and that the ENTIRE stdout is one JSON list)."""
    rc, out, err = _run(["runs", "--state-dir", str(state_dir), "--json"], capsys)
    assert rc == 0, f"runs --json must exit 0, got {rc}; stderr:\n{err}"
    parsed = json.loads(out)  # entire stdout must parse as one JSON array
    assert isinstance(parsed, list), f"runs --json must emit a JSON list; got {type(parsed)}"
    return parsed


# ===========================================================================
# Expected Behavior 1 --- both counters appear with their real (nonzero) values
# ===========================================================================


def test_eb1_both_counters_appear_with_real_values(tmp_path, capsys):
    state_dir = tmp_path / "state"
    _persist_run(state_dir / "run-alpha", retries=2, parse_errors=1)

    rows = _rows(state_dir, capsys)
    assert len(rows) == 1
    row = rows[0]
    assert row["run_id"] == "run-alpha"
    assert "retries" in row and "parse_errors" in row, (
        f"runs --json rows must surface both resilience counters; got keys {set(row.keys())}"
    )
    assert row["retries"] == 2, f"retries must equal the persisted 2; got {row['retries']!r}"
    assert row["parse_errors"] == 1, (
        f"parse_errors must equal the persisted 1; got {row['parse_errors']!r}"
    )
    # Integers, not stringified.
    assert isinstance(row["retries"], int) and not isinstance(row["retries"], bool)
    assert isinstance(row["parse_errors"], int) and not isinstance(row["parse_errors"], bool)


# ===========================================================================
# Expected Behavior 2 --- zero counters are still emitted (present, integer 0)
# ===========================================================================


def test_eb2_zero_counters_still_emitted_as_zero(tmp_path, capsys):
    state_dir = tmp_path / "state"
    _persist_run(state_dir / "run-zero", retries=0, parse_errors=0)

    rows = _rows(state_dir, capsys)
    assert len(rows) == 1
    row = rows[0]
    assert "retries" in row and "parse_errors" in row, (
        "both keys must be PRESENT even when zero (not omitted); "
        f"got keys {set(row.keys())}"
    )
    assert row["retries"] == 0 and isinstance(row["retries"], int)
    assert row["parse_errors"] == 0 and isinstance(row["parse_errors"], int)


# ===========================================================================
# Expected Behavior 3 --- degraded (no/corrupt checkpoint) rows report 0 for both
# ===========================================================================


def test_eb3_missing_checkpoint_row_reports_zero_counters(tmp_path, capsys):
    state_dir = tmp_path / "state"
    (state_dir / "run-nockpt").mkdir(parents=True)  # bare dir, NO checkpoint.json

    rows = _rows(state_dir, capsys)
    assert len(rows) == 1
    row = rows[0]
    assert row["run_id"] == "run-nockpt"
    assert row["status"] == _NO_CHECKPOINT, (
        f"a checkpoint-less run must degrade to the '{_NO_CHECKPOINT}' status; got {row['status']!r}"
    )
    # Degraded rows mirror the existing "iterations": 0 contract for the new keys.
    assert row["iterations"] == 0
    assert row["retries"] == 0 and isinstance(row["retries"], int)
    assert row["parse_errors"] == 0 and isinstance(row["parse_errors"], int)


def test_eb3_corrupt_checkpoint_row_reports_zero_and_does_not_raise(tmp_path, capsys):
    state_dir = tmp_path / "state"
    corrupt = state_dir / "run-corrupt"
    corrupt.mkdir(parents=True)
    # A truncated / unreadable checkpoint so .load() raises and _run_row degrades.
    (corrupt / _CHECKPOINT_NAME).write_text('{"goal": {"title": "x", "rationale"')

    rows = _rows(state_dir, capsys)  # asserts exit 0 (does not raise / abort)
    assert len(rows) == 1
    row = rows[0]
    assert row["run_id"] == "run-corrupt"
    assert row["status"] == _NO_CHECKPOINT, (
        f"a corrupt/unreadable checkpoint must degrade to '{_NO_CHECKPOINT}'; got {row['status']!r}"
    )
    assert row["iterations"] == 0
    assert row["retries"] == 0 and isinstance(row["retries"], int)
    assert row["parse_errors"] == 0 and isinstance(row["parse_errors"], int)


# ===========================================================================
# Expected Behavior 4 --- exact key set = the six existing + the two new keys
# ===========================================================================


def test_eb4_row_key_set_is_exactly_the_eight_documented_keys(tmp_path, capsys):
    state_dir = tmp_path / "state"
    # One healthy nonzero-counter row, one zero-counter row, one degraded row ---
    # every row's key set must be identical and complete.
    _persist_run(state_dir / "run-a", retries=5, parse_errors=3)
    _persist_run(state_dir / "run-b", retries=0, parse_errors=0)
    (state_dir / "run-c").mkdir(parents=True)  # degraded, no checkpoint

    rows = _rows(state_dir, capsys)
    assert len(rows) == 3
    for row in rows:
        assert set(row.keys()) == _EXPECTED_ROW_KEYS, (
            f"each row key set must be EXACTLY {_EXPECTED_ROW_KEYS} "
            f"(six pre-existing + two new, nothing dropped, nothing extra); "
            f"got {set(row.keys())} for {row.get('run_id')!r}"
        )


# ===========================================================================
# Expected Behavior 5 --- the HUMAN `pla runs` table is unchanged (no counters)
# ===========================================================================


def test_eb5_human_runs_table_has_no_counter_columns(tmp_path, capsys):
    state_dir = tmp_path / "state"
    # Nonzero counters must NOT leak into the human table at all.
    _persist_run(state_dir / "run-alpha", retries=7, parse_errors=4)
    _persist_run(state_dir / "run-beta", retries=0, parse_errors=0)

    rc, out, err = _run(["runs", "--state-dir", str(state_dir)], capsys)
    assert rc == 0, f"human runs must exit 0, got {rc}; stderr:\n{err}"

    lines = [ln for ln in out.splitlines() if ln.strip()]
    header = lines[0]
    # The documented five-column header, order-exact, spacing-agnostic.
    assert header.split() == ["RUN", "ID", "STATUS", "ITERS", "ARTIFACTS", "GOAL"], (
        f"human header must be the five documented columns "
        f"'RUN ID / STATUS / ITERS / ARTIFACTS / GOAL' and nothing else; got:\n{header!r}"
    )
    # No retries/parse_errors column or value anywhere in the human table.
    lowered = out.lower()
    assert "retries" not in lowered, f"human table must NOT mention 'retries'; got:\n{out}"
    assert "parse_errors" not in lowered and "parse errors" not in lowered, (
        f"human table must NOT mention 'parse errors'; got:\n{out}"
    )
    # Both runs are still listed (the table still works).
    assert "run-alpha" in out and "run-beta" in out


# ===========================================================================
# Expected Behavior 6 --- empty / absent state dir still emits exactly [] , exit 0
# ===========================================================================


def test_eb6_empty_state_dir_json_is_empty_list(tmp_path, capsys):
    empty = tmp_path / "empty_state"
    empty.mkdir()
    rc, out, err = _run(["runs", "--state-dir", str(empty), "--json"], capsys)
    assert rc == 0, f"runs --json on an empty dir must exit 0, got {rc}; stderr:\n{err}"
    assert json.loads(out) == [], f"empty state dir --json must be exactly []; got:\n{out}"


def test_eb6_absent_state_dir_json_is_empty_list(tmp_path, capsys):
    missing = tmp_path / "does_not_exist"
    assert not missing.exists()
    rc, out, err = _run(["runs", "--state-dir", str(missing), "--json"], capsys)
    assert rc == 0, f"runs --json on a missing dir must exit 0, got {rc}; stderr:\n{err}"
    assert json.loads(out) == [], f"absent state dir --json must be exactly []; got:\n{out}"


# ===========================================================================
# Expected Behavior 7 --- `pla trace --json` is UNCHANGED (hard scope guard)
# ===========================================================================


def test_eb7_trace_json_step_schema_gains_no_counters(tmp_path, capsys):
    """`pla trace --run-dir <dir> --json` stays a bare array of step objects with
    EXACTLY {index, kind, output, done, artifacts} and NO retries / parse_errors
    --- even when the run's checkpoint carries nonzero counters. This feature does
    NOT touch trace --json (no run-level object to hang metadata on)."""
    run_dir = tmp_path / "run-trace"
    state = _persist_run(run_dir, retries=9, parse_errors=6)  # nonzero run-level counts

    rc, out, err = _run(["trace", "--run-dir", str(run_dir), "--json"], capsys)
    assert rc == 0, f"trace --json must exit 0, got {rc}; stderr:\n{err}"

    parsed = json.loads(out)  # the ENTIRE stdout must be one JSON array
    assert isinstance(parsed, list), "trace --json must remain a bare JSON array"
    assert len(parsed) == len(state.steps)

    exact_step_keys = {"index", "kind", "output", "done", "artifacts"}
    for elem in parsed:
        assert set(elem.keys()) == exact_step_keys, (
            f"each trace --json step object must keep EXACTLY {exact_step_keys}; got {set(elem.keys())}"
        )
        assert "retries" not in elem, "retries must never leak into a trace --json step object"
        assert "parse_errors" not in elem, "parse_errors must never leak into a trace --json step object"


# ===========================================================================
# Expected Behavior 8 --- no version bump
# ===========================================================================


def test_eb8_module_version_is_not_bumped():
    assert __version__ == "0.1.1", (
        "surfacing already-persisted counters on a tolerant machine-readable "
        f"output must NOT bump the version; got {__version__!r}"
    )


def test_eb8_cli_version_still_reports_0_1_1(capsys):
    capsys.readouterr()
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "pla 0.1.1" in out, f"`pla --version` must report 'pla 0.1.1'; got:\n{out!r}"
