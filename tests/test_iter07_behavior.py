"""Black-box behavior tests for iteration 07.

Feature under test: ``pla trace --run-dir DIR [--json]`` -- a read-only,
LLM-free CLI verb that renders one dispatched run's persisted PLAN->ACT->CHECK
step transcript (``RunState.steps``) from its ``checkpoint.json``. It completes
the run-lifecycle triad **runs (find) -> trace (inspect) -> resume (continue)**
and the auditability pair **explain (why it decided) + trace (what it did)**,
making the L1 loop's own step-by-step reasoning trail inspectable offline.

ISOLATION CONTRACT (honored): these tests are written strictly against the
public contract -- this iteration's spec "Expected Behaviors", ``README.md``,
and ``SPEC.md`` (the public design contract, incl. the ``RunState`` /
``LoopStep`` / ``StepKind`` / ``RunStatus`` foundation contract in SPEC.md
sections 3 and 4.4) -- and drive only the documented public surface: the
``pla`` CLI via ``proactive_loop.cli.main([...])``, the public domain models
(``CandidateGoal``, ``RunState``, ``LoopStep``, ``StepKind``, ``RunStatus``)
used to construct + persist a run exactly as the spec's Tester setup note
prescribes, and the public ``proactive_loop.loop.Checkpoint`` persister. No
file under ``src/`` was read, no engineer/reviewer notes were read, and no
``git diff`` was consulted. Model field names were confirmed only from the
public model schema and from existing published tests, never from the ``trace``
implementation. Fixture-coupled goal ids are never hard-coded: where a real run
is produced via the demo (behavior 9) the run dir is located by globbing
``run-*`` and the id is read back from disk. Every test uses a fresh
``tmp_path`` (never the repo's ``.pla_runs/``) and runs fully offline -- zero
network, zero API keys.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from proactive_loop.cli import main
from proactive_loop.loop import Checkpoint
from proactive_loop.models import (
    CandidateGoal,
    LoopStep,
    RunState,
    RunStatus,
    StepKind,
)

REPO = Path(__file__).resolve().parents[1]
# Absolute paths (runner-location-independent) to the offline fixtures.
FIXTURE = REPO / "examples" / "fixture_workspace"
SCRIPT = REPO / "examples" / "scripted_responses.json"

_CHECKPOINT_NAME = "checkpoint.json"
_TRACEBACK = "Traceback (most recent call last)"
# Matches a per-step transcript line: leading "[<int>]" (implementation sketch
# renders each step as "[{index}] {kind} ...").
_STEP_LINE = re.compile(r"^\s*\[\d+\]")


# ---------------------------------------------------------------------------
# Setup helpers (the spec's prescribed setup convention)
# ---------------------------------------------------------------------------


def _transcript_steps() -> list[LoopStep]:
    """A realistic 6-step PLAN->ACT->CHECK transcript (two loop iterations).

    Deliberately exercises every behavior-relevant shape:
      - all three ``StepKind`` values (plan / act / check),
      - a CHECK with ``done=False`` (index 2) AND one with ``done=True`` (5),
      - an ``output`` that contains an embedded newline (index 1) -- proves the
        human render collapses it to a single line (behavior 3) and that
        ``--json`` preserves it verbatim (behavior 5),
      - a step carrying a non-empty ``artifacts`` list (index 4).
    """
    return [
        LoopStep(index=0, kind=StepKind.PLAN, output="thought: locate the retriever module"),
        LoopStep(index=1, kind=StepKind.ACT, output="list_files -> src/retriever.py\nsrc/index.py", artifacts=[]),
        LoopStep(index=2, kind=StepKind.CHECK, output="reason: not yet, need to read the file", done=False),
        LoopStep(index=3, kind=StepKind.PLAN, output="thought: write the summary artifact"),
        LoopStep(index=4, kind=StepKind.ACT, output="write_file -> summary.md", artifacts=["summary.md"]),
        LoopStep(index=5, kind=StepKind.CHECK, output="reason: artifact present, complete", done=True),
    ]


def _persist_run(
    run_dir: Path,
    *,
    goal_title: str = "Inspect the retriever pipeline",
    status: RunStatus = RunStatus.BUDGET_EXHAUSTED,
    steps: list[LoopStep] | None = None,
    iterations_used: int = 2,
    llm_calls_used: int = 4,
) -> RunState:
    """Construct a ``RunState`` via the public models and persist it to
    ``run_dir/checkpoint.json`` with the public ``Checkpoint`` -- exactly the
    setup path the spec's Tester note prescribes (option (a)). Returns the
    in-memory state so callers can derive expected values from it.

    NOTE: the default status is BUDGET_EXHAUSTED so ``status.value``
    (``"budget_exhausted"``) is an UNAMBIGUOUS render token -- it can never
    collide with the ``done=...`` verdict tokens that CHECK steps also print.
    """
    run_dir.mkdir(parents=True, exist_ok=True)
    goal = CandidateGoal(
        title=goal_title,
        rationale="verify the retriever wiring end to end",
        suggested_first_steps=["read src/retriever.py"],
    )
    state = RunState(
        goal=goal,
        status=status,
        steps=steps if steps is not None else _transcript_steps(),
        iterations_used=iterations_used,
        llm_calls_used=llm_calls_used,
        artifacts_dir=str(run_dir / "artifacts"),
    )
    Checkpoint(run_dir / _CHECKPOINT_NAME).save(state)
    return state


def _produce_demo_run(state_dir: Path) -> Path:
    """Produce ONE real completed run under ``state_dir`` via the offline demo
    path (the spec's prescribed setup convention for behavior 9). Returns the
    ``run-<goal_id>`` dir, located by globbing (never a hard-coded id)."""
    rc = main([
        "run",
        "--workspace", str(FIXTURE),
        "--provider", "scripted",
        "--scripted-responses", str(SCRIPT),
        "--state-dir", str(state_dir),
    ])
    assert rc == 0, f"demo `run` setup must exit 0, got {rc}"
    run_dirs = sorted(state_dir.glob("run-*"))
    assert len(run_dirs) == 1, f"demo must dispatch exactly one run, got {run_dirs}"
    return run_dirs[0]


def _run(argv: list[str], capsys) -> tuple[int, str, str]:
    """Invoke the CLI and return (rc, stdout, stderr). Drains capsys first so
    setup output never leaks into the assertion window."""
    capsys.readouterr()
    rc = main(argv)
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


# ---------------------------------------------------------------------------
# Behavior 1 -- renders the transcript (human form): title, status, kind tokens
# ---------------------------------------------------------------------------


def test_behavior1_renders_transcript_human_form(tmp_path, capsys):
    run_dir = tmp_path / "run-inspect"
    state = _persist_run(run_dir, status=RunStatus.BUDGET_EXHAUSTED)

    # NO --provider and NO --scripted-responses: the omission IS the assertion
    # that `trace` builds no LLMClient (a scripted verb with no script would
    # fault; this succeeds LLM-free).
    rc, out, err = _run(["trace", "--run-dir", str(run_dir)], capsys)

    assert rc == 0, f"trace on a populated run must exit 0, got {rc}; stderr:\n{err}"
    assert state.goal.title in out, f"human render must show the goal title; got:\n{out}"
    # status.value is unambiguous here (budget_exhausted != any done=... token).
    assert state.status.value in out, (
        f"human render must show state.status.value ({state.status.value!r}); got:\n{out}"
    )
    # Every recorded StepKind value must appear as a literal lowercase token.
    for token in ("plan", "act", "check"):
        assert token in out, f"human render must contain the kind token {token!r}; got:\n{out}"


def test_behavior1_llm_free_bogus_scripted_path_still_succeeds(tmp_path, capsys):
    """A bogus --scripted-responses path would fault ANY verb that constructs a
    scripted LLMClient. trace exiting 0 here proves it builds none (belt-and-
    braces alongside the flag-omission assertion above)."""
    run_dir = tmp_path / "run-llmfree"
    state = _persist_run(run_dir)

    rc, out, err = _run([
        "trace", "--run-dir", str(run_dir),
        "--scripted-responses", "/no/such/file.json",
    ], capsys)

    assert rc == 0, (
        f"trace must exit 0 even with a bogus --scripted-responses path "
        f"(proves no LLMClient constructed), got {rc}; stderr:\n{err}"
    )
    assert state.goal.title in out, f"the transcript must still render; got:\n{out}"


# ---------------------------------------------------------------------------
# Behavior 2 -- CHECK steps show their done verdict (done=true / done=false)
# ---------------------------------------------------------------------------


def test_behavior2_check_steps_show_done_verdict(tmp_path, capsys):
    run_dir = tmp_path / "run-verdict"
    state = _persist_run(run_dir)
    # Sanity: the fixture has both a done=False and a done=True CHECK step.
    check_dones = {s.done for s in state.steps if s.kind is StepKind.CHECK}
    assert check_dones == {True, False}, "fixture must have both CHECK verdicts"

    rc, out, err = _run(["trace", "--run-dir", str(run_dir)], capsys)
    assert rc == 0, f"trace must exit 0, got {rc}"
    assert "done=false" in out, f"a done=False CHECK must render 'done=false'; got:\n{out}"
    assert "done=true" in out, f"a done=True CHECK must render 'done=true'; got:\n{out}"


# ---------------------------------------------------------------------------
# Behavior 3 -- one transcript line per step; embedded newlines collapsed
# ---------------------------------------------------------------------------


def test_behavior3_one_line_per_step_newlines_collapsed(tmp_path, capsys):
    run_dir = tmp_path / "run-oneline"
    state = _persist_run(run_dir)
    # Precondition: at least one step's output contains an embedded newline.
    assert any("\n" in s.output for s in state.steps), (
        "fixture must include a step whose output has an embedded newline"
    )

    rc, out, err = _run(["trace", "--run-dir", str(run_dir)], capsys)
    assert rc == 0, f"trace must exit 0, got {rc}"

    step_lines = [ln for ln in out.splitlines() if _STEP_LINE.match(ln)]
    assert len(step_lines) == len(state.steps), (
        f"each step must contribute exactly one transcript line: expected "
        f"{len(state.steps)}, got {len(step_lines)}; lines:\n{step_lines}"
    )


# ---------------------------------------------------------------------------
# Behavior 4 -- long output truncated in human render, complete in --json
# ---------------------------------------------------------------------------


def test_behavior4_long_output_truncated_human_complete_json(tmp_path, capsys):
    run_dir = tmp_path / "run-long"
    long_output = "A" * 500  # single-line, no embedded newline
    steps = [LoopStep(index=0, kind=StepKind.ACT, output=long_output)]
    _persist_run(run_dir, steps=steps)

    # Human render: the step's line is truncated well under 500 chars, and the
    # full 500-char run never appears verbatim.
    rc, out, err = _run(["trace", "--run-dir", str(run_dir)], capsys)
    assert rc == 0, f"human trace must exit 0, got {rc}"
    step_lines = [ln for ln in out.splitlines() if _STEP_LINE.match(ln)]
    assert len(step_lines) == 1, f"expected exactly one step line; got:\n{out}"
    assert len(step_lines[0]) < 500, (
        f"human render must truncate the 500-char output to a shorter line; "
        f"got a line of length {len(step_lines[0])}"
    )
    assert long_output not in out, "the full 500-char output must NOT appear in the human render"

    # --json: the same step's output is emitted verbatim and complete.
    rc, out, err = _run(["trace", "--run-dir", str(run_dir), "--json"], capsys)
    assert rc == 0, f"trace --json must exit 0, got {rc}"
    parsed = json.loads(out)
    assert len(parsed) == 1
    assert parsed[0]["output"] == long_output, (
        "--json must emit the full untruncated 500-char output verbatim"
    )
    assert len(parsed[0]["output"]) == 500


# ---------------------------------------------------------------------------
# Behavior 5 -- --json shape: array of typed objects, exact keys, ordered
# ---------------------------------------------------------------------------


def test_behavior5_json_shape_exact_keys_and_order(tmp_path, capsys):
    run_dir = tmp_path / "run-json"
    _persist_run(run_dir)
    # Re-load from disk (public Checkpoint) so expectations are coupled to the
    # actually-persisted state, never to the in-memory fixture object.
    state = Checkpoint(run_dir / _CHECKPOINT_NAME).load()
    assert state is not None and state.steps, "setup must persist a non-empty run"

    # NO --provider flag (LLM-free).
    rc, out, err = _run(["trace", "--run-dir", str(run_dir), "--json"], capsys)
    assert rc == 0, f"trace --json must exit 0, got {rc}; stderr:\n{err}"

    parsed = json.loads(out)  # ENTIRE stdout must parse as one JSON array
    assert isinstance(parsed, list), f"--json must emit a JSON array; got {type(parsed)}"
    assert len(parsed) == len(state.steps), (
        f"array length must equal len(state.steps) ({len(state.steps)}); got {len(parsed)}"
    )

    exact_keys = {"index", "kind", "output", "done", "artifacts"}
    for elem, step in zip(parsed, state.steps):
        assert isinstance(elem, dict), f"each element must be an object; got {elem!r}"
        assert set(elem.keys()) == exact_keys, (
            f"each element must have EXACTLY {exact_keys}; got {set(elem.keys())}"
        )
        assert isinstance(elem["index"], int) and elem["index"] == step.index, (
            f"index must be the step's int index; got {elem['index']!r}"
        )
        assert isinstance(elem["kind"], str) and elem["kind"] == step.kind.value, (
            f"kind must be the plain string {step.kind.value!r}; got {elem['kind']!r}"
        )
        assert elem["kind"] in {"plan", "act", "check"}
        assert isinstance(elem["output"], str) and elem["output"] == step.output, (
            "output must be the full untruncated step output string"
        )
        assert isinstance(elem["done"], bool) and elem["done"] == step.done, (
            f"done must be the step's bool; got {elem['done']!r}"
        )
        assert isinstance(elem["artifacts"], list) and elem["artifacts"] == list(step.artifacts), (
            f"artifacts must be the step's list of strings; got {elem['artifacts']!r}"
        )
        assert all(isinstance(a, str) for a in elem["artifacts"])


# ---------------------------------------------------------------------------
# Behavior 6 -- empty steps degrade legibly (human) / "[]" only (json)
# ---------------------------------------------------------------------------


def test_behavior6_empty_steps_human_degrades_legibly(tmp_path, capsys):
    run_dir = tmp_path / "run-empty"
    state = _persist_run(run_dir, status=RunStatus.DONE, steps=[], iterations_used=0, llm_calls_used=0)

    rc, out, err = _run(["trace", "--run-dir", str(run_dir)], capsys)
    assert rc == 0, f"empty-steps human trace must exit 0, got {rc}"
    # Header still printed (goal title + status).
    assert state.goal.title in out, f"header (goal title) must still print; got:\n{out}"
    assert state.status.value in out, f"header (status) must still print; got:\n{out}"
    assert "no steps recorded" in out, (
        f"empty steps must include the legible 'no steps recorded' line; got:\n{out}"
    )


def test_behavior6_empty_steps_json_is_bare_empty_array(tmp_path, capsys):
    run_dir = tmp_path / "run-empty-json"
    _persist_run(run_dir, status=RunStatus.DONE, steps=[], iterations_used=0, llm_calls_used=0)

    rc, out, err = _run(["trace", "--run-dir", str(run_dir), "--json"], capsys)
    assert rc == 0, f"empty-steps --json must exit 0, got {rc}"
    assert json.loads(out) == [], f"empty steps --json must parse to []; got:\n{out!r}"
    assert out.strip() == "[]", f"empty --json must emit ONLY '[]' (no prose); got:\n{out!r}"


# ---------------------------------------------------------------------------
# Behavior 7 -- missing checkpoint -> exit 2, legible stderr, no stdout
# ---------------------------------------------------------------------------


def test_behavior7_dir_exists_without_checkpoint_exit_2(tmp_path, capsys):
    run_dir = tmp_path / "run-nockpt"
    run_dir.mkdir()
    assert not (run_dir / _CHECKPOINT_NAME).exists()

    rc, out, err = _run(["trace", "--run-dir", str(run_dir)], capsys)
    assert rc == 2, f"a run dir with no checkpoint must exit 2, got {rc}"
    assert out == "", f"nothing must be printed to stdout; got:\n{out!r}"
    err_lines = [ln for ln in err.splitlines() if ln.strip()]
    assert len(err_lines) == 1, f"exactly one stderr line expected; got:\n{err!r}"
    assert err_lines[0].startswith("error:"), f"stderr must begin with 'error:'; got:\n{err!r}"
    assert "checkpoint" in err.lower(), f"stderr must mention the missing checkpoint; got:\n{err!r}"
    assert str(run_dir) in err, f"stderr must name the run dir; got:\n{err!r}"
    assert _TRACEBACK not in err, f"must not print a traceback; got:\n{err!r}"


def test_behavior7_nonexistent_dir_exit_2(tmp_path, capsys):
    run_dir = tmp_path / "does_not_exist"
    assert not run_dir.exists()

    rc, out, err = _run(["trace", "--run-dir", str(run_dir)], capsys)
    assert rc == 2, f"a nonexistent run dir must exit 2, got {rc}"
    assert out == "", f"nothing must be printed to stdout; got:\n{out!r}"
    err_lines = [ln for ln in err.splitlines() if ln.strip()]
    assert err_lines and err_lines[0].startswith("error:"), (
        f"stderr must begin with 'error:'; got:\n{err!r}"
    )
    assert _TRACEBACK not in err, f"must not print a traceback; got:\n{err!r}"


# ---------------------------------------------------------------------------
# Behavior 8 -- corrupt checkpoint -> exit 1 via the main() boundary
# ---------------------------------------------------------------------------


def test_behavior8_invalid_json_checkpoint_exit_1(tmp_path, capsys):
    run_dir = tmp_path / "run-badjson"
    run_dir.mkdir()
    (run_dir / _CHECKPOINT_NAME).write_text("{ not json")

    rc, out, err = _run(["trace", "--run-dir", str(run_dir)], capsys)
    assert rc == 1, f"an invalid-JSON checkpoint must exit 1 via the boundary, got {rc}"
    assert out == "", f"nothing must be printed to stdout; got:\n{out!r}"
    err_lines = [ln for ln in err.splitlines() if ln.strip()]
    assert err_lines and err_lines[0].startswith("error:"), (
        f"stderr's first line must begin with 'error:'; got:\n{err!r}"
    )
    assert _TRACEBACK not in err, f"corrupt checkpoint must NOT print a traceback; got:\n{err!r}"


def test_behavior8_valid_json_failing_validation_exit_1(tmp_path, capsys):
    run_dir = tmp_path / "run-badmodel"
    run_dir.mkdir()
    # Valid JSON, but not a valid RunState (missing the required `goal` field).
    (run_dir / _CHECKPOINT_NAME).write_text(json.dumps({"foo": "bar"}))

    rc, out, err = _run(["trace", "--run-dir", str(run_dir)], capsys)
    assert rc == 1, f"a validation-failing checkpoint must exit 1, got {rc}"
    assert out == "", f"nothing must be printed to stdout; got:\n{out!r}"
    err_lines = [ln for ln in err.splitlines() if ln.strip()]
    assert err_lines and err_lines[0].startswith("error:"), (
        f"stderr's first line must begin with 'error:'; got:\n{err!r}"
    )
    assert _TRACEBACK not in err, f"must NOT print a traceback; got:\n{err!r}"


# ---------------------------------------------------------------------------
# Behavior 9 -- end-to-end over a real demo run (no provider flags)
# ---------------------------------------------------------------------------


def test_behavior9_end_to_end_over_real_demo_run(tmp_path, capsys):
    state_dir = tmp_path / "state"
    run_dir = _produce_demo_run(state_dir)  # locates run-<goal_id> by globbing
    capsys.readouterr()  # drain the demo run's own output

    # trace with NO provider flags over the REAL persisted checkpoint.
    rc, out, err = _run(["trace", "--run-dir", str(run_dir)], capsys)
    assert rc == 0, f"trace over a real demo run must exit 0, got {rc}; stderr:\n{err}"
    for token in ("plan", "act", "check"):
        assert token in out, (
            f"a real multi-iteration run's transcript must contain {token!r}; got:\n{out}"
        )


# ---------------------------------------------------------------------------
# Behavior 10 -- missing required --run-dir -> argparse usage error (exit 2)
# ---------------------------------------------------------------------------


def test_behavior10_missing_run_dir_is_argparse_usage_error(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["trace"])
    assert excinfo.value.code == 2, (
        f"missing --run-dir must raise SystemExit(2) (argparse usage code), "
        f"got {excinfo.value.code!r}"
    )
    err = capsys.readouterr().err
    assert "usage:" in err, f"missing --run-dir must print usage to stderr; got:\n{err}"
    assert _TRACEBACK not in err, f"argparse error must not traceback; got:\n{err}"


def test_behavior10_trace_help_documents_options(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["trace", "--help"])
    assert excinfo.value.code == 0, "`pla trace --help` must exit 0"
    out = capsys.readouterr().out
    assert "--run-dir" in out, f"trace --help must document --run-dir; got:\n{out}"
    assert "--json" in out, f"trace --help must document --json; got:\n{out}"


# ---------------------------------------------------------------------------
# Behavior 11 -- no regression to existing verbs / --version / demo
# ---------------------------------------------------------------------------


def test_behavior11a_top_help_lists_all_seven_verbs(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["--help"])
    assert excinfo.value.code == 0, "`pla --help` must exit 0"
    out = capsys.readouterr().out
    for verb in ("scan", "dispatch", "run", "resume", "runs", "explain", "trace"):
        assert verb in out, f"top-level help must list the {verb!r} subcommand; got:\n{out}"


def test_behavior11b_version_unchanged(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0, "`pla --version` must still exit 0"
    out = capsys.readouterr().out
    assert "pla 0.1.1" in out, f"`pla --version` must still print 'pla 0.1.1'; got:\n{out!r}"


def test_behavior11c_existing_verbs_unchanged(tmp_path, capsys):
    # scan still exits 0 and writes the slate, dispatching nothing.
    scan_state = tmp_path / "scan_state"
    out_path = tmp_path / "slate.json"
    rc_scan = main([
        "scan",
        "--workspace", str(FIXTURE),
        "--provider", "scripted",
        "--scripted-responses", str(SCRIPT),
        "--state-dir", str(scan_state),
        "--out", str(out_path),
    ])
    assert rc_scan == 0, f"scan must still exit 0, got {rc_scan}"
    assert out_path.is_file(), "scan must still write the slate JSON"
    assert not list(scan_state.glob("run-*")), "scan alone must still dispatch nothing"
    capsys.readouterr()

    # runs on an empty state dir still exits 0 (iter-04 contract).
    empty = tmp_path / "empty_state"
    empty.mkdir()
    assert main(["runs", "--state-dir", str(empty)]) == 0, "runs must still exit 0"
    capsys.readouterr()

    # explain on a demo slate goal still exits 0 (iter-06 contract).
    from proactive_loop.models import GoalSlate
    slate = GoalSlate.model_validate_json(out_path.read_text())
    assert slate.goals, "demo slate must contain goals"
    rc_explain = main(["explain", "--slate", str(out_path), "--goal-id", slate.goals[0].id])
    assert rc_explain == 0, f"explain must still exit 0, got {rc_explain}"
    capsys.readouterr()

    # dispatch on an unknown goal id still exits 2 (its documented code).
    rc_bad = main([
        "dispatch",
        "--slate", str(out_path),
        "--goal-id", "does-not-exist",
        "--provider", "scripted",
        "--scripted-responses", str(SCRIPT),
        "--state-dir", str(tmp_path / "d_state"),
    ])
    assert rc_bad == 2, f"dispatch unknown goal-id must still exit 2, got {rc_bad}"


def test_behavior11d_demo_run_unchanged_and_trace_not_a_side_effect(tmp_path, capsys):
    # The exact vector `make demo` uses still exits 0 and writes both artifacts
    # + a done checkpoint -- adding `trace` did not perturb it.
    state_dir = tmp_path / "run_state"
    run_dir = _produce_demo_run(state_dir)
    assert (run_dir / "artifacts" / "learning_plan.md").is_file()
    assert (run_dir / "artifacts" / "project_scaffold.md").is_file()
    capsys.readouterr()

    # `trace` output must never appear as a side effect of another verb: `runs`
    # over the same populated state must NOT emit the trace-only markers.
    rc, out, err = _run(["runs", "--state-dir", str(state_dir)], capsys)
    assert rc == 0
    assert "no steps recorded" not in out, "the `runs` verb must not emit trace's step-block markers"
    assert not [ln for ln in out.splitlines() if _STEP_LINE.match(ln)], (
        "the `runs` verb must not emit trace's per-step '[i] ...' lines"
    )
