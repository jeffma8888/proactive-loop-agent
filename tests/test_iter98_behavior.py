"""Black-box behavior tests for iteration 89 (commit-sequence **factory iter 98**):
``pla runs`` gains an optional ``--status STATUS`` filter --- the run inspector's
first query knob. It narrows the read-only, LLM-free run listing to runs whose
persisted status equals STATUS and composes cleanly with ``--json`` (ROADMAP #98).

Feature under test: ``pla runs`` was the one inspector with zero query knobs
(``signals`` has ``--kind``/``--min-weight``/``--collector``; ``scan`` has
``--top``/``--format``/``--collector``). This iteration adds ``--status`` whose
accepted values are EXACTLY the five live ``RunStatus`` ``.value`` strings, so
the accepted set cannot drift from the enum. The filter is a pure addition: the
default (no ``--status``) path is byte-identical to the pre-change command.

ISOLATION CONTRACT (honored): every assertion here is written strictly against
THIS iteration's public contract --- the spec's "Expected Behaviors" (``pm.md``),
``README.md``, and the product's own observable output --- and drives ONLY the
documented public surface: the ``pla`` CLI via ``proactive_loop.cli.main([...])``
(observable stdout / stderr / exit code), the public ``RunStatus`` enum, and the
public ``proactive_loop.loop.Checkpoint`` / ``proactive_loop.models.RunState``
seam to persist synthetic offline run dirs (exactly as
``tests/test_iter71_behavior.py`` and ``tests/test_iter04_behavior.py`` do). **No
file under ``src/`` was read, no engineer/reviewer notes were consulted, and no
``git diff`` was inspected** to author these assertions. Every test is fully
offline: zero network, zero API keys; run dirs are synthetic ``tmp_path`` (never
the repo's ``.pla_runs/``); the ``--status`` accepted set is DERIVED from the
live ``RunStatus`` enum, never hardcoded, so it catches a future enum add.

NOTE on the ``run_id`` seam: a run's ``run_id`` in both the human table and the
JSON array is its directory NAME (e.g. ``run-aaa``), and the listing is sorted
ascending by that name (from ``_iter_run_dirs``, preserved verbatim). Behavior 3
persists dirs OUT of sorted order to prove the name-ascending ordering survives.
"""

from __future__ import annotations

import contextlib
import io
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
_EMPTY_HUMAN = "no runs found under the state dir.\n"
_EMPTY_JSON = "[]\n"


# ---------------------------------------------------------------------------
# Helpers (the same public Checkpoint/RunState seam tests/test_iter71_behavior.py
# and tests/test_iter04_behavior.py use --- no src/ read).
# ---------------------------------------------------------------------------
def _goal(title: str) -> CandidateGoal:
    return CandidateGoal(
        title=title,
        rationale="capture next steps",
        suggested_first_steps=["draft learning_plan.md"],
    )


def _persist_run(run_dir: Path, *, status: RunStatus, title: str) -> None:
    """Persist a RunState carrying `status` via the public Checkpoint seam."""
    run_dir.mkdir(parents=True, exist_ok=True)
    state = RunState(
        goal=_goal(title),
        status=status,
        steps=[LoopStep(index=0, kind=StepKind.PLAN, output="thought: locate module")],
        iterations_used=1,
        llm_calls_used=1,
        artifacts_dir=str(run_dir / "artifacts"),
    )
    Checkpoint(run_dir / _CHECKPOINT_NAME).save(state)


def _run(argv: list[str]) -> tuple[int, str, str]:
    """Drive main(argv); return (exit_code, stdout, stderr).

    Normal path: main returns an int (0 for `runs`), normalized to the code.
    argparse usage errors (e.g. an invalid --status choice) raise SystemExit(2);
    that code is captured too, so behavior 5's parse-error path is observable.
    """
    out, err = io.StringIO(), io.StringIO()
    code: int
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rv = main(argv)
            code = rv if isinstance(rv, int) else 0
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    return code, out.getvalue(), err.getvalue()


def _human_run_ids(stdout: str) -> list[str]:
    """Extract the ordered run_ids from a human `runs` table: each data row's
    first whitespace-delimited token is the run_id (dir name `run-...`). The
    header row ('RUN ID  STATUS ...') and blank lines are skipped."""
    ids: list[str] = []
    for line in stdout.splitlines():
        if not line.strip():
            continue
        first = line.split()[0]
        if first.startswith("run-"):
            ids.append(first)
    return ids


def _mixed_state_dir(root: Path) -> Path:
    """A state dir with two distinct real statuses (1 done, 2 failed) + a
    pending run + a degraded (missing checkpoint) run + a degraded (corrupt
    checkpoint) run. Dirs are created OUT of sorted order to exercise ordering."""
    sd = root / "state"
    _persist_run(sd / "run-ccc", status=RunStatus.FAILED, title="goal failed one")
    _persist_run(sd / "run-aaa", status=RunStatus.DONE, title="goal done")
    _persist_run(sd / "run-bbb", status=RunStatus.FAILED, title="goal failed two")
    _persist_run(sd / "run-ddd", status=RunStatus.PENDING, title="goal pending")
    (sd / "run-miss").mkdir(parents=True)  # degraded: no checkpoint.json
    corrupt = sd / "run-corr"
    corrupt.mkdir(parents=True)
    (corrupt / _CHECKPOINT_NAME).write_text("{not valid json at all")  # degraded
    return sd


# ===========================================================================
# Behavior 1 -- filter to one status (human view): the matching run_id is
# shown, a non-matching run_id is not; exit 0.
# ===========================================================================
def test_b01_filter_one_status_human(tmp_path):
    sd = _mixed_state_dir(tmp_path)
    code, out, err = _run(["runs", "--state-dir", str(sd), "--status", "done"])
    assert code == 0, f"human --status done must exit 0; got {code}; stderr:\n{err}"
    ids = _human_run_ids(out)
    assert "run-aaa" in ids, f"the done run must appear; got rows {ids}\n{out}"
    for absent in ("run-bbb", "run-ccc", "run-ddd"):
        assert absent not in ids, (
            f"a non-done run {absent!r} must be filtered out; got rows {ids}\n{out}"
        )
    assert _NO_CHECKPOINT not in out  # not the empty-listing / degraded shape


# ===========================================================================
# Behavior 2 -- filter with --json: every element's status == the requested
# value, the non-matching run is absent, len == number of matching runs.
# ===========================================================================
def test_b02_filter_json_only_matching(tmp_path):
    sd = _mixed_state_dir(tmp_path)
    code, out, err = _run(
        ["runs", "--state-dir", str(sd), "--status", "failed", "--json"]
    )
    assert code == 0, f"--status failed --json must exit 0; got {code}; stderr:\n{err}"
    arr = json.loads(out)  # entire stdout parses as one JSON array
    assert isinstance(arr, list)
    assert all(r["status"] == "failed" for r in arr), (
        f"every element must have status 'failed'; got {[r['status'] for r in arr]}"
    )
    got_ids = {r["run_id"] for r in arr}
    assert got_ids == {"run-bbb", "run-ccc"}, f"exactly the two failed runs; got {got_ids}"
    assert "run-aaa" not in got_ids, "the done run must be absent from a failed filter"
    assert len(arr) == 2, f"len(array) must equal the number of failed runs (2); got {len(arr)}"


# ===========================================================================
# Behavior 3 -- omitted flag is backward-compatible: bare `runs` lists ALL
# run-* dirs in ascending-run_id order (a pure addition, no default change),
# and the filtered result is a strict subset of the unfiltered listing.
# ===========================================================================
def test_b03_omitted_flag_lists_all_in_name_order(tmp_path):
    sd = _mixed_state_dir(tmp_path)
    n_dirs = sum(1 for p in sd.iterdir() if p.is_dir())
    code, out, err = _run(["runs", "--state-dir", str(sd)])
    assert code == 0, f"bare runs must exit 0; got {code}; stderr:\n{err}"
    ids = _human_run_ids(out)
    # every run dir appears, including both statuses and both degraded rows
    assert set(ids) == {"run-aaa", "run-bbb", "run-ccc", "run-ddd", "run-miss", "run-corr"}
    # printed data-row count equals the number of run dirs (nothing filtered)
    assert len(ids) == n_dirs == 6, f"row count must equal run-dir count; got {len(ids)} vs {n_dirs}"
    # name-ascending order is preserved verbatim (dirs were created out of order)
    assert ids == sorted(ids), f"rows must be name-ascending; got {ids}"


def test_b03_filtered_is_subset_of_unfiltered(tmp_path):
    sd = _mixed_state_dir(tmp_path)
    _, full, _ = _run(["runs", "--state-dir", str(sd)])
    _, filtered, _ = _run(["runs", "--state-dir", str(sd), "--status", "done"])
    assert set(_human_run_ids(filtered)).issubset(set(_human_run_ids(full))), (
        "the filtered listing must be a subset of the unfiltered listing (pure addition)"
    )


# ===========================================================================
# Behavior 4 -- no match -> clean empty answer, exit 0; the existing
# empty-listing message / [] is reused VERBATIM (not a filter-aware rephrase).
# ===========================================================================
def test_b04_no_match_human_is_verbatim_empty_line(tmp_path):
    sd = _mixed_state_dir(tmp_path)  # has runs, but NONE budget_exhausted
    code, out, err = _run(["runs", "--state-dir", str(sd), "--status", "budget_exhausted"])
    assert code == 0, f"no-match human must exit 0; got {code}; stderr:\n{err}"
    assert out == _EMPTY_HUMAN, f"must reuse the verbatim empty line; got {out!r}"


def test_b04_no_match_json_is_empty_array(tmp_path):
    sd = _mixed_state_dir(tmp_path)
    code, out, err = _run(
        ["runs", "--state-dir", str(sd), "--status", "budget_exhausted", "--json"]
    )
    assert code == 0, f"no-match --json must exit 0; got {code}; stderr:\n{err}"
    assert out == _EMPTY_JSON, f"no-match --json must be exactly '[]'; got {out!r}"
    assert json.loads(out) == [], "and it must parse as an empty JSON array"


# ===========================================================================
# Behavior 5 -- unknown status is a parse-time usage error: exit 2, NOTHING on
# stdout, stderr names the invalid choice; the accepted choices are EXACTLY the
# five live RunStatus values (derived from the enum, cannot drift).
# ===========================================================================
def test_b05_unknown_status_is_exit2_usage_error(tmp_path):
    sd = _mixed_state_dir(tmp_path)
    code, out, err = _run(["runs", "--state-dir", str(sd), "--status", "bogus"])
    assert code == 2, f"an invalid --status choice must exit 2; got {code}"
    assert out == "", f"a parse error must write NOTHING to stdout; got {out!r}"
    assert "bogus" in err, f"stderr must name the invalid choice 'bogus'; got:\n{err}"


def test_b05_choices_are_exactly_the_live_runstatus_values():
    import argparse

    from proactive_loop.cli import build_parser

    parser = build_parser()
    subparsers = [
        a for a in parser._actions if isinstance(a, argparse._SubParsersAction)
    ][0]
    runs = subparsers.choices["runs"]
    status_act = [a for a in runs._actions if a.dest == "status"][0]
    expected = sorted(s.value for s in RunStatus)
    assert list(status_act.choices) == expected, (
        f"--status choices must be exactly the five live RunStatus values "
        f"{expected}; got {list(status_act.choices)}"
    )
    assert status_act.default is None, f"--status default must be None; got {status_act.default!r}"
    # anchor the current enum so a silent enum change is visible here too
    assert expected == ["budget_exhausted", "done", "failed", "pending", "running"]


# ===========================================================================
# Behavior 6 -- degraded (missing OR corrupt checkpoint) runs render as
# '(no checkpoint)': excluded by ANY --status filter, but shown when unfiltered.
# ===========================================================================
@pytest.mark.parametrize("status", sorted(s.value for s in RunStatus))
def test_b06_degraded_excluded_by_any_filter(tmp_path, status):
    sd = _mixed_state_dir(tmp_path)
    _, out, _ = _run(["runs", "--state-dir", str(sd), "--status", status, "--json"])
    ids = {r["run_id"] for r in json.loads(out)}
    assert "run-miss" not in ids, f"missing-checkpoint run must not match --status {status}"
    assert "run-corr" not in ids, f"corrupt-checkpoint run must not match --status {status}"


def test_b06_degraded_shown_when_unfiltered(tmp_path):
    sd = _mixed_state_dir(tmp_path)
    code, out, err = _run(["runs", "--state-dir", str(sd), "--json"])
    assert code == 0, f"bare runs --json must exit 0; got {code}; stderr:\n{err}"
    rows = {r["run_id"]: r["status"] for r in json.loads(out)}
    assert rows.get("run-miss") == _NO_CHECKPOINT, (
        f"missing-checkpoint run must show status '{_NO_CHECKPOINT}'; got {rows.get('run-miss')!r}"
    )
    assert rows.get("run-corr") == _NO_CHECKPOINT, (
        f"corrupt-checkpoint run must show status '{_NO_CHECKPOINT}'; got {rows.get('run-corr')!r}"
    )


# ===========================================================================
# Behavior 7 -- read-only / LLM-free envelope preserved: --status alongside a
# NONEXISTENT --scripted-responses path still exits 0 and prints the filtered
# table (no LLMClient built, no scripted-responses file opened).
# ===========================================================================
def test_b07_readonly_llm_free_envelope_preserved(tmp_path):
    sd = _mixed_state_dir(tmp_path)
    code, out, err = _run(
        [
            "runs",
            "--state-dir",
            str(sd),
            "--status",
            "done",
            "--scripted-responses",
            "/nonexistent/path.json",
        ]
    )
    assert code == 0, (
        "runs --status done must exit 0 even with a bogus --scripted-responses "
        f"path (the file is never opened, no LLMClient is built); got {code}; stderr:\n{err}"
    )
    ids = _human_run_ids(out)
    assert "run-aaa" in ids and "run-bbb" not in ids, (
        f"the filtered table must still print (done only); got rows {ids}\n{out}"
    )


# ===========================================================================
# Anchor -- a flag add, not a verb/version change: __version__ stays 0.1.1.
# ===========================================================================
def test_b08_version_constant_unchanged():
    assert __version__ == "0.1.1", (
        f"adding an optional flag must NOT bump the version; got {__version__!r}"
    )
