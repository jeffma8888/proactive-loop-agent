"""Black-box behavior tests for iteration 04.

Feature under test: ``pla runs`` -- a read-only, LLM-free CLI verb that lists
and inspects past dispatched runs under the state dir (one row per
``run-<goal_id>/``), with a ``--json`` array mode. It makes the L0
"resumable, checkpointed runs" machinery visible and turns the advertised
``resume --run-dir DIR`` verb's opaque argument into something discoverable.

ISOLATION CONTRACT (honored): these tests are written strictly against the
public contract -- this iteration's spec "Expected Behaviors", ``README.md``,
and ``SPEC.md`` (§4.5) -- and drive only the documented public surface: the
``pla`` CLI via ``proactive_loop.cli.main([...])`` and the public
``proactive_loop.models.GoalSlate`` model (used solely to look up the
dispatched goal's title from the persisted ``slate.json`` artifact, never to
reach into the ``runs`` implementation). No file under ``src/`` was read, no
engineer/reviewer notes were read, and no ``git diff`` was consulted. Every
test uses a fresh ``tmp_path`` state dir (never the repo's ``.pla_runs/``) and
runs fully offline -- zero network, zero API keys.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from proactive_loop.cli import main
from proactive_loop.models import GoalSlate

REPO = Path(__file__).resolve().parents[1]
# Absolute paths (equivalent to the spec's relative examples) so setup does not
# depend on the pytest cwd.
FIXTURE = REPO / "examples" / "fixture_workspace"
SCRIPT = REPO / "examples" / "scripted_responses.json"

_NO_CHECKPOINT = "(no checkpoint)"


# ---------------------------------------------------------------------------
# Setup helpers
# ---------------------------------------------------------------------------


def _produce_demo_run(state_dir: Path) -> None:
    """Produce ONE real completed run under ``state_dir`` via the offline demo
    path (the spec's prescribed setup convention). Drives the scripted provider
    so it is fully deterministic and network-free."""
    rc = main([
        "run",
        "--workspace", str(FIXTURE),
        "--provider", "scripted",
        "--scripted-responses", str(SCRIPT),
        "--state-dir", str(state_dir),
    ])
    assert rc == 0, f"demo `run` setup must exit 0, got {rc}"


def _dispatched_goal_title(state_dir: Path) -> str:
    """The title of the single AUTO_DISPATCH goal the demo actually ran.

    Derived black-box from the two public artifacts the run persisted -- the
    ``run-<goal_id>/`` dir name and the ``slate.json`` it acted on -- so the
    expected title is never hard-coded and stays coupled to the real fixture.
    """
    run_dirs = sorted(state_dir.glob("run-*"))
    assert len(run_dirs) == 1, f"demo must dispatch exactly one run, got {run_dirs}"
    goal_id = run_dirs[0].name[len("run-"):]
    slate = GoalSlate.model_validate_json((state_dir / "slate.json").read_text())
    dispatched = next(g for g in slate.goals if g.id == goal_id)
    return dispatched.title


def _make_run_dir(
    state_dir: Path,
    name: str,
    *,
    meta: dict | None = None,
    artifact_files: list[str] | None = None,
    make_artifacts_dir: bool = True,
) -> Path:
    """Fabricate a bare ``run-*`` dir with a ``meta.json`` and (optionally) an
    ``artifacts/`` tree but NO ``checkpoint.json`` -- the partial/corrupt-run
    shape that must degrade gracefully."""
    run_dir = state_dir / name
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "meta.json").write_text(json.dumps(meta or {}))
    if make_artifacts_dir:
        artifacts = run_dir / "artifacts"
        artifacts.mkdir(exist_ok=True)
        for rel in artifact_files or []:
            fp = artifacts / rel
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text("x")
    return run_dir


# ---------------------------------------------------------------------------
# Behavior 1 -- lists a completed run (human table)
# ---------------------------------------------------------------------------


def test_behavior1_lists_completed_run_human_table(tmp_path, capsys):
    state_dir = tmp_path / "state"
    _produce_demo_run(state_dir)
    title = _dispatched_goal_title(state_dir)
    capsys.readouterr()  # drain the demo's output

    rc = main(["runs", "--state-dir", str(state_dir)])
    out = capsys.readouterr().out

    assert rc == 0, f"runs must exit 0 on a populated state dir, got {rc}"
    assert title in out, f"human table must show the run's goal title; got:\n{out}"
    assert "done" in out, f"human table must show the `done` status token; got:\n{out}"


# ---------------------------------------------------------------------------
# Behavior 2 -- zero-config / LLM-free (no provider/script flags needed)
# ---------------------------------------------------------------------------


def test_behavior2_zero_config_llm_free(tmp_path, capsys):
    state_dir = tmp_path / "state"
    _produce_demo_run(state_dir)
    title = _dispatched_goal_title(state_dir)
    capsys.readouterr()  # drain the demo's output

    # NOTE: no --provider and no --scripted-responses. If `runs` constructed an
    # LLMClient, the scripted provider would demand a script file and fault.
    rc = main(["runs", "--state-dir", str(state_dir)])
    captured = capsys.readouterr()

    assert rc == 0, f"runs must run LLM-free with no provider flags, got rc={rc}"
    assert title in captured.out, f"run table must still print; got:\n{captured.out}"
    err_lines = [ln for ln in captured.err.splitlines() if ln.strip()]
    offending = [ln for ln in err_lines if ln.startswith("error:")]
    assert not offending, f"no stderr line may begin with 'error:'; got: {offending}"


# ---------------------------------------------------------------------------
# Behavior 3 -- nonexistent state dir -> clean "no runs", never crashes
# ---------------------------------------------------------------------------


def test_behavior3_nonexistent_state_dir_clean_no_runs(tmp_path, capsys):
    missing = tmp_path / "does_not_exist"
    assert not missing.exists()

    rc = main(["runs", "--state-dir", str(missing)])
    captured = capsys.readouterr()

    assert rc == 0, f"a missing state dir must exit 0, got {rc}"
    assert "no runs" in captured.out, f"stdout must say 'no runs'; got:\n{captured.out}"
    assert "Traceback" not in (captured.out + captured.err), (
        f"a missing state dir must never print a traceback; got:\n"
        f"OUT={captured.out!r}\nERR={captured.err!r}"
    )


# ---------------------------------------------------------------------------
# Behavior 4 -- empty (but existing) state dir -> clean "no runs"
# ---------------------------------------------------------------------------


def test_behavior4_empty_state_dir_clean_no_runs(tmp_path, capsys):
    empty = tmp_path / "empty_state"
    empty.mkdir()
    assert not list(empty.glob("run-*"))

    rc = main(["runs", "--state-dir", str(empty)])
    out = capsys.readouterr().out

    assert rc == 0, f"an empty state dir must exit 0, got {rc}"
    assert "no runs" in out, f"stdout must say 'no runs'; got:\n{out}"


# ---------------------------------------------------------------------------
# Behavior 5 -- a run dir missing its checkpoint is still listed, not fatal
# ---------------------------------------------------------------------------


def test_behavior5_missing_checkpoint_is_listed_not_fatal(tmp_path, capsys):
    state_dir = tmp_path / "state"
    _make_run_dir(state_dir, "run-abc", meta={"workspace_root": "/somewhere"})

    rc = main(["runs", "--state-dir", str(state_dir)])
    out = capsys.readouterr().out

    assert rc == 0, f"a checkpoint-less run must not abort the listing, got {rc}"
    assert "run-abc" in out, f"the partial run must still be listed; got:\n{out}"
    assert _NO_CHECKPOINT in out, (
        f"a checkpoint-less run must show the verbatim '{_NO_CHECKPOINT}' status; "
        f"got:\n{out}"
    )


# ---------------------------------------------------------------------------
# Behavior 6 -- --json emits a parseable array with the required keys
# ---------------------------------------------------------------------------


def test_behavior6_json_array_with_required_keys(tmp_path, capsys):
    state_dir = tmp_path / "state"
    _produce_demo_run(state_dir)
    title = _dispatched_goal_title(state_dir)
    capsys.readouterr()  # drain the demo's output

    rc = main(["runs", "--state-dir", str(state_dir), "--json"])
    out = capsys.readouterr().out

    assert rc == 0, f"runs --json must exit 0, got {rc}"

    # The ENTIRE stdout must be valid JSON parsing to a list.
    parsed = json.loads(out)
    assert isinstance(parsed, list), f"--json must emit a JSON list; got {type(parsed)}"

    required = {"run_id", "status", "goal", "iterations", "artifacts", "workspace"}
    for elem in parsed:
        assert isinstance(elem, dict), f"each element must be an object; got {elem!r}"
        assert required.issubset(elem.keys()), (
            f"element missing required keys {required - set(elem)}; got {elem!r}"
        )

    done = [e for e in parsed if e["status"] == "done"]
    assert len(done) == 1, f"exactly one element must be status=='done'; got {done}"
    row = done[0]
    assert row["goal"] == title, f"goal must equal the dispatched title; got {row['goal']!r}"
    assert isinstance(row["iterations"], int) and row["iterations"] >= 1, (
        f"iterations must be an int >= 1; got {row['iterations']!r}"
    )
    assert isinstance(row["artifacts"], int) and row["artifacts"] >= 1, (
        f"artifacts must be an int >= 1; got {row['artifacts']!r}"
    )


# ---------------------------------------------------------------------------
# Behavior 7 -- --json on an empty/absent state dir -> []
# ---------------------------------------------------------------------------


def test_behavior7_json_empty_state_dir_is_empty_list(tmp_path, capsys):
    empty = tmp_path / "empty_state"
    empty.mkdir()

    rc = main(["runs", "--state-dir", str(empty), "--json"])
    out = capsys.readouterr().out

    assert rc == 0, f"runs --json on empty dir must exit 0, got {rc}"
    assert json.loads(out) == [], f"empty state dir --json must be []; got:\n{out}"


def test_behavior7_json_absent_state_dir_is_empty_list(tmp_path, capsys):
    missing = tmp_path / "does_not_exist"
    assert not missing.exists()

    rc = main(["runs", "--state-dir", str(missing), "--json"])
    out = capsys.readouterr().out

    assert rc == 0, f"runs --json on a missing dir must exit 0, got {rc}"
    assert json.loads(out) == [], f"absent state dir --json must be []; got:\n{out}"


# ---------------------------------------------------------------------------
# Behavior 8 -- deterministic id-sorted ordering + byte-identical repeats
# ---------------------------------------------------------------------------


def test_behavior8_deterministic_id_sorted_ordering(tmp_path, capsys):
    state_dir = tmp_path / "state"
    # Create in NON-sorted order to prove the command sorts, not chance.
    for name in ("run-ccc", "run-aaa", "run-bbb"):
        _make_run_dir(state_dir, name, meta={"workspace_root": f"/w/{name}"})

    # --json order is ascending by run id.
    rc = main(["runs", "--state-dir", str(state_dir), "--json"])
    json_out_1 = capsys.readouterr().out
    assert rc == 0
    ids = [e["run_id"] for e in json.loads(json_out_1)]
    assert ids == ["run-aaa", "run-bbb", "run-ccc"], f"rows must be id-sorted; got {ids}"

    # Human rows also appear ascending by run id.
    rc = main(["runs", "--state-dir", str(state_dir)])
    human_out_1 = capsys.readouterr().out
    assert rc == 0
    positions = [human_out_1.index(name) for name in ("run-aaa", "run-bbb", "run-ccc")]
    assert positions == sorted(positions), f"human rows must be id-sorted; got:\n{human_out_1}"

    # Two invocations against the same unchanged state dir are byte-identical.
    assert main(["runs", "--state-dir", str(state_dir), "--json"]) == 0
    json_out_2 = capsys.readouterr().out
    assert json_out_2 == json_out_1, "repeated --json output must be byte-identical"

    assert main(["runs", "--state-dir", str(state_dir)]) == 0
    human_out_2 = capsys.readouterr().out
    assert human_out_2 == human_out_1, "repeated human output must be byte-identical"


# ---------------------------------------------------------------------------
# Behavior 9 -- artifacts count reflects files on disk (recursive; 0 if absent)
# ---------------------------------------------------------------------------


def test_behavior9_artifacts_count_reflects_files_recursively(tmp_path, capsys):
    state_dir = tmp_path / "state"
    # run-files: three regular files, one of them nested one level deep.
    _make_run_dir(
        state_dir,
        "run-files",
        meta={},
        artifact_files=["a.txt", "b.txt", "sub/c.txt"],
    )
    # run-noart: NO artifacts/ dir at all -> must count as 0, not crash.
    _make_run_dir(state_dir, "run-noart", meta={}, make_artifacts_dir=False)

    rc = main(["runs", "--state-dir", str(state_dir), "--json"])
    out = capsys.readouterr().out
    assert rc == 0

    rows = {e["run_id"]: e for e in json.loads(out)}
    assert rows["run-files"]["artifacts"] == 3, (
        f"artifacts must count regular files recursively (2 top + 1 nested = 3); "
        f"got {rows['run-files']['artifacts']}"
    )
    assert rows["run-noart"]["artifacts"] == 0, (
        f"a run with no artifacts/ dir must report 0; got {rows['run-noart']['artifacts']}"
    )


# ---------------------------------------------------------------------------
# Behavior 10 -- backward compatibility (existing verbs unchanged; no new dep)
# ---------------------------------------------------------------------------


def test_behavior10_existing_verbs_unchanged(tmp_path, capsys):
    # `scan` still works with its existing flags and no new required flag.
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

    # `run` (the exact vector `make demo` uses) still exits 0 and produces both
    # artifacts + a done checkpoint -- adding `runs` did not perturb it.
    run_state = tmp_path / "run_state"
    _produce_demo_run(run_state)
    (run_dir,) = list(run_state.glob("run-*"))
    assert (run_dir / "artifacts" / "learning_plan.md").is_file()
    assert (run_dir / "artifacts" / "project_scaffold.md").is_file()
    capsys.readouterr()

    # `dispatch` on an unknown goal id still exits 2 (its documented code).
    empty_slate = tmp_path / "empty_slate.json"
    empty_slate.write_text(GoalSlate(workspace_root=str(FIXTURE)).model_dump_json())
    rc_bad = main([
        "dispatch",
        "--slate", str(empty_slate),
        "--goal-id", "does-not-exist",
        "--provider", "scripted",
        "--scripted-responses", str(SCRIPT),
        "--state-dir", str(tmp_path / "d_state"),
    ])
    assert rc_bad == 2, f"unknown goal-id must still exit 2, got {rc_bad}"


def test_behavior10_runs_needs_no_provider_or_script(tmp_path, capsys):
    """`runs` introduces no new *required* flag: bare `runs --state-dir DIR`
    (no --provider, no --scripted-responses, no --json) is a complete, valid
    invocation."""
    state_dir = tmp_path / "state"
    _make_run_dir(state_dir, "run-abc", meta={})

    rc = main(["runs", "--state-dir", str(state_dir)])
    out = capsys.readouterr().out

    assert rc == 0, f"bare `runs --state-dir` must be a complete invocation, got {rc}"
    assert "run-abc" in out
