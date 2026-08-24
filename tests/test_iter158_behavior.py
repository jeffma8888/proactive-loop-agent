"""Black-box behavior tests for state-dir iteration 152 (ships as ``factory iter 158``).

Feature under test: ``pla run --json`` -- a machine-readable result for the one
verb that acts autonomously. Under ``--json`` the ENTIRE stdout becomes exactly
one JSON object describing what the invocation produced (workspace, slate path,
goal counts, the goals held for approval, the selected top goal, and the
dispatched run's id / status / run dir / artifact paths), while the human
progress rendering moves to STDERR unchanged. The default (no ``--json``) path,
the exit codes, and ``dispatch`` / ``resume`` are untouched.

WHY EVERY PROCESS-LEVEL BEHAVIOR HERE IS DRIVEN THROUGH A REAL SUBPROCESS
Behaviors 1, 5 and 8 are claims about the SEPARATION of two output streams (one
document on stdout, all human text on stderr, empty stdout on the failure path).
An in-process ``capsys`` run cannot falsify them honestly: a stream-redirect
implemented against ``sys.__stdout__`` would bypass ``capsys`` entirely and a
broken split could still read green. So this module spends real ``pla`` console
script invocations (the iter-114/157 convention) and reads the actual file
descriptors. Cost is bounded by module-scoped fixtures: FOUR product runs in
all, shared across the nine behaviors.

ISOLATION CONTRACT (honored): every assertion is written against this
iteration's spec ("Expected Behaviors" in ``pm.md``), the published ``README.md``
CLI table, the repo's own ``tests/`` conventions, and the product's OBSERVABLE
output obtained by RUNNING it. **No file under ``src/`` was read, no engineer's
or reviewer's note was consulted, and no ``git diff`` was inspected.** Fully
offline and deterministic: the bundled scripted provider only, no network, no
API key. Every run is rooted at a PRIVATE COPY of ``examples/fixture_workspace``
made under ``tmp_path`` and writes its state into ``tmp_path`` -- nothing is
written inside the product repo, and no run is rooted at the in-repo fixture
(the iter-142 shared-mutable-tree hazard). No count is transcribed from a
fixture: ``goal_count`` is checked against the slate the run itself wrote, and
the run id / status against the checkpoint the run itself persisted.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "examples" / "fixture_workspace"
SCRIPT = REPO / "examples" / "scripted_responses.json"
README = REPO / "README.md"

# The published result schema (spec behaviors 2 and 3).
_TOP_KEYS = frozenset(
    {
        "workspace_root",
        "slate_path",
        "goal_count",
        "needs_approval",
        "top_goal",
        "dispatched",
        "deferred",
    }
)
_DISPATCH_KEYS = frozenset(
    {
        "goal_id",
        "run_id",
        "status",
        "run_dir",
        "artifacts",
        "iterations_used",
        "llm_calls_used",
        "retries",
        "parse_errors",
    }
)
_GOAL_REF_KEYS = frozenset({"id", "title"})

# Two human lines the non-`--json` path prints today (spec behavior 5/7).
_AUTO_MARKER = "auto-dispatching top goal:"
_SUMMARY_MARKER = "dispatched :"

_MARKER = "PORTFOLIO INTRO"


# ---------------------------------------------------------------------------
# Helpers (iter-114 / iter-157 console-script convention)
# ---------------------------------------------------------------------------


def _console_script() -> Path:
    """The installed ``pla`` console script."""
    bindir = Path(sys.executable).parent
    candidates = [bindir / "pla", bindir / "pla.exe"]
    which = shutil.which("pla")
    if which:
        candidates.append(Path(which))
    script = next((c for c in candidates if c.is_file()), None)
    assert script is not None, (
        "the `pla` console script must be installed (declared in pyproject and "
        f"installed by `uv sync`); searched {[str(c) for c in candidates]}"
    )
    return script


def _run(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Invoke the real CLI in its own process so stdout/stderr are real fds."""
    return subprocess.run(
        [str(_console_script()), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=120,
    )


def _isolated_workspace(root: Path) -> Path:
    """A private copy of the offline fixture workspace under ``root``.

    Never run the product against the in-repo fixture: it carries no ``.git`` of
    its own, so git-family collectors resolve upward into this repo and a
    sibling xdist worker can flip what they report mid-test.
    """
    dest = root / "workspace"
    shutil.copytree(FIXTURE, dest)
    return dest


def _run_argv(workspace: Path, state_dir: Path, *extra: str) -> list[str]:
    return [
        "run",
        "--workspace",
        str(workspace),
        "--provider",
        "scripted",
        "--scripted-responses",
        str(SCRIPT),
        "--state-dir",
        str(state_dir),
        *extra,
    ]


def _one_json_object(stdout: str, label: str) -> dict:
    """Parse stdout as EXACTLY one JSON object, or fail with the raw text.

    ``json.loads`` rejects trailing content, so a successful parse is itself the
    proof that no prose and no second document accompany the object.
    """
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:  # pragma: no cover - failure reporting
        pytest.fail(f"{label}: stdout must be exactly one JSON object; {exc}\nstdout:\n{stdout!r}")
    assert isinstance(payload, dict), f"{label}: the document must be an object, got {type(payload)}"
    return payload


_HEXID = re.compile(r"\b[0-9a-f]{12}\b")


def _normalize(text: str, state_dir: Path) -> list[str]:
    """Human lines with this invocation's own state-dir path and its generated
    ids folded away, so two runs are comparable line by line.

    Two folds are needed and both were MEASURED, not assumed: the state-dir path
    differs by construction (each run gets its own), and the 12-hex goal / run
    ids are derived per invocation, so the `pla dispatch ...` hint lines, the
    `(id=...)` summary line, the run dir and the artifact paths all differ
    between two otherwise identical runs. Folding both leaves the STRUCTURE of
    every line, which is what "verbatim" can mean across two invocations.
    """
    folded = text.replace(str(state_dir.resolve()), "<SD>").replace(str(state_dir), "<SD>")
    folded = _HEXID.sub("<ID>", folded)
    return [line.rstrip() for line in folded.splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# Module-scoped product runs (four in total)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def workspace(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """ONE private copy of the fixture workspace, shared by the three runs.

    Sharing it is deliberate: a goal id is derived per invocation from the
    workspace it was synthesized over, so two runs rooted at two DIFFERENT
    copies produce different ids and behavior 5's line-for-line comparison
    would be comparing two unrelated slates. No run writes into the workspace
    (artifacts land in the state dir), so the tree stays immutable.
    """
    return _isolated_workspace(tmp_path_factory.mktemp("i158_ws"))


@pytest.fixture(scope="module")
def json_run(
    tmp_path_factory: pytest.TempPathFactory, workspace: Path
) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
    """One `--json` auto-dispatch run. Returns (proc, state_dir, workspace)."""
    root = tmp_path_factory.mktemp("i158_json")
    sd = root / "state"
    proc = _run(*_run_argv(workspace, sd, "--json"), cwd=root)
    return proc, sd, workspace


@pytest.fixture(scope="module")
def plain_run(
    tmp_path_factory: pytest.TempPathFactory, workspace: Path
) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
    """The same invocation WITHOUT `--json` -- the unchanged default path."""
    root = tmp_path_factory.mktemp("i158_plain")
    sd = root / "state"
    proc = _run(*_run_argv(workspace, sd), cwd=root)
    return proc, sd, workspace


@pytest.fixture(scope="module")
def dry_json_run(
    tmp_path_factory: pytest.TempPathFactory, workspace: Path
) -> tuple[subprocess.CompletedProcess[str], Path]:
    """`--json --dry-run`: the preview branch of the schema."""
    root = tmp_path_factory.mktemp("i158_dry")
    sd = root / "state"
    proc = _run(*_run_argv(workspace, sd, "--json", "--dry-run"), cwd=root)
    return proc, sd


# ===========================================================================
# Behavior 1 -- exit 0 and the ENTIRE stdout is exactly one JSON object
# ===========================================================================


def test_b01_json_run_exits_zero_and_stdout_is_one_json_object(json_run) -> None:
    proc, _sd, _ws = json_run
    assert proc.returncode == 0, (
        f"`run --json` must exit 0 on a successful auto-dispatch; "
        f"got {proc.returncode}\nstderr:\n{proc.stderr}"
    )
    payload = _one_json_object(proc.stdout, "run --json")
    # No prose before or after the object: the raw text starts `{` and ends `}`.
    stripped = proc.stdout.strip()
    assert stripped.startswith("{") and stripped.endswith("}"), (
        f"stdout must contain nothing but the object; got {proc.stdout!r}"
    )
    assert payload, "the result object must not be empty"


# ===========================================================================
# Behavior 2 -- exactly seven top-level keys, with the published types
# ===========================================================================


def test_b02_top_level_schema_is_exactly_the_seven_published_keys(json_run) -> None:
    proc, _sd, ws = json_run
    payload = _one_json_object(proc.stdout, "run --json")

    assert set(payload) == set(_TOP_KEYS), (
        "the result object must carry exactly the seven published keys; "
        f"missing={sorted(_TOP_KEYS - set(payload))} extra={sorted(set(payload) - _TOP_KEYS)}"
    )
    assert isinstance(payload["workspace_root"], str), "workspace_root must be a str"
    assert Path(payload["workspace_root"]).resolve() == ws.resolve(), (
        f"workspace_root must name the scanned workspace; got {payload['workspace_root']!r}"
    )
    assert isinstance(payload["slate_path"], str), "slate_path must be a str"

    count = payload["goal_count"]
    assert isinstance(count, int) and not isinstance(count, bool), (
        f"goal_count must be a plain int (never a list -- `scan --format json` already "
        f"publishes `goals` as a list); got {type(count)}"
    )
    assert count > 0, f"the fixture workspace must yield at least one goal; got {count}"

    approval = payload["needs_approval"]
    assert isinstance(approval, list), f"needs_approval must be a list; got {type(approval)}"
    for entry in approval:
        assert isinstance(entry, dict), f"each needs_approval entry must be an object; got {entry!r}"
        assert set(entry) == set(_GOAL_REF_KEYS), (
            f"a needs_approval entry publishes exactly id + title; got {sorted(entry)}"
        )
        assert isinstance(entry["id"], str) and entry["id"], "a goal id must be a non-empty str"
        assert isinstance(entry["title"], str) and entry["title"], "a goal title must be non-empty"

    top = payload["top_goal"]
    assert top is None or isinstance(top, dict), "top_goal must be an object or null"
    if isinstance(top, dict):
        assert set(top) == set(_GOAL_REF_KEYS), (
            f"top_goal publishes exactly id + title; got {sorted(top)}"
        )
    dispatched = payload["dispatched"]
    assert dispatched is None or isinstance(dispatched, dict), (
        "dispatched must be an object or null"
    )


# ===========================================================================
# Behavior 3 -- the dispatched sub-object's nine keys
# ===========================================================================


def test_b03_dispatched_object_publishes_its_nine_keys(json_run) -> None:
    proc, _sd, _ws = json_run
    payload = _one_json_object(proc.stdout, "run --json")

    top = payload["top_goal"]
    assert isinstance(top, dict), (
        "a successful auto-dispatch must name the dispatched goal in top_goal; got null"
    )
    dispatched = payload["dispatched"]
    assert isinstance(dispatched, dict), (
        f"a successful auto-dispatch must publish a `dispatched` object; got {dispatched!r}"
    )
    assert set(dispatched) == set(_DISPATCH_KEYS), (
        "dispatched must carry exactly the nine published keys; "
        f"missing={sorted(_DISPATCH_KEYS - set(dispatched))} "
        f"extra={sorted(set(dispatched) - _DISPATCH_KEYS)}"
    )
    assert dispatched["goal_id"] == top["id"], (
        f"dispatched.goal_id must be the top goal's id; {dispatched['goal_id']!r} != {top['id']!r}"
    )
    for key in ("goal_id", "run_id", "status", "run_dir"):
        assert isinstance(dispatched[key], str) and dispatched[key], (
            f"dispatched.{key} must be a non-empty str; got {dispatched[key]!r}"
        )
    artifacts = dispatched["artifacts"]
    assert isinstance(artifacts, list) and artifacts, (
        f"dispatched.artifacts must be a non-empty list for a run that wrote files; got {artifacts!r}"
    )
    assert all(isinstance(a, str) for a in artifacts), "every artifact entry must be a str"
    for key in ("iterations_used", "llm_calls_used", "retries", "parse_errors"):
        value = dispatched[key]
        assert isinstance(value, int) and not isinstance(value, bool), (
            f"dispatched.{key} must be a plain int; got {type(value)}"
        )
        assert value >= 0, f"dispatched.{key} is a non-negative counter; got {value}"


# ===========================================================================
# Behavior 4 -- the reported paths and status are TRUE ON DISK
# ===========================================================================


def test_b04_reported_paths_and_status_are_true_on_disk(json_run) -> None:
    proc, sd, _ws = json_run
    payload = _one_json_object(proc.stdout, "run --json")

    slate = Path(payload["slate_path"])
    assert slate.is_file(), f"slate_path must name an existing file; {slate} is not a file"
    slate_doc = json.loads(slate.read_text())
    assert isinstance(slate_doc.get("goals"), list), "the written slate must carry a goals list"
    assert payload["goal_count"] == len(slate_doc["goals"]), (
        f"goal_count must equal the number of goals in the slate it names; "
        f"reported {payload['goal_count']}, slate holds {len(slate_doc['goals'])}"
    )

    dispatched = payload["dispatched"]
    assert isinstance(dispatched, dict), "precondition: this run auto-dispatched"
    run_dir = Path(dispatched["run_dir"])
    assert run_dir.is_dir(), f"dispatched.run_dir must be an existing directory; got {run_dir}"
    # ...and it must live under the state dir this invocation was given.
    run_dir.resolve().relative_to(sd.resolve())

    checkpoint = run_dir / "checkpoint.json"
    assert checkpoint.is_file(), f"the run dir must hold a checkpoint.json; {checkpoint} missing"
    saved = json.loads(checkpoint.read_text())
    assert dispatched["run_id"] == saved["run_id"], (
        f"dispatched.run_id must equal the persisted run id; "
        f"{dispatched['run_id']!r} != {saved['run_id']!r}"
    )
    assert dispatched["status"] == saved["status"], (
        f"dispatched.status must equal the persisted status (a plain string, not a repr); "
        f"{dispatched['status']!r} != {saved['status']!r}"
    )
    for artifact in dispatched["artifacts"]:
        assert Path(artifact).is_file(), f"every reported artifact must exist; {artifact} missing"


# ===========================================================================
# Behavior 5 -- human text is not lost; it moves to stderr verbatim
# ===========================================================================


def test_b05_human_rendering_moves_to_stderr_verbatim(json_run, plain_run) -> None:
    jproc, jsd, _jws = json_run
    pproc, psd, _pws = plain_run
    assert pproc.returncode == 0, f"precondition: the plain run succeeds\n{pproc.stderr}"

    plain_lines = _normalize(pproc.stdout, psd)
    json_err_lines = _normalize(jproc.stderr, jsd)
    assert plain_lines, "precondition: the default path prints a human rendering on stdout"

    missing = [line for line in plain_lines if line not in json_err_lines]
    assert not missing, (
        "under --json every line the default path prints to stdout must appear on stderr "
        f"verbatim; {len(missing)} missing, first 5: {missing[:5]}\n"
        f"--json stderr was:\n{jproc.stderr}"
    )
    for marker in (_AUTO_MARKER, _SUMMARY_MARKER):
        assert marker in jproc.stderr, (
            f"the --json run's stderr must still carry {marker!r}; got:\n{jproc.stderr}"
        )
        assert marker not in jproc.stdout, (
            f"{marker!r} must never reach stdout under --json; got:\n{jproc.stdout}"
        )


# ===========================================================================
# Behavior 6 -- --json --dry-run previews without dispatching
# ===========================================================================


def test_b06_dry_run_json_previews_with_null_dispatched_and_no_run_dir(dry_json_run) -> None:
    proc, sd = dry_json_run
    assert proc.returncode == 0, (
        f"`run --json --dry-run` must exit 0; got {proc.returncode}\nstderr:\n{proc.stderr}"
    )
    payload = _one_json_object(proc.stdout, "run --json --dry-run")
    assert set(payload) == set(_TOP_KEYS), (
        f"the preview publishes the same seven keys; got {sorted(payload)}"
    )
    top = payload["top_goal"]
    assert isinstance(top, dict) and top["title"], (
        f"--dry-run must still name the goal it WOULD dispatch; got {top!r}"
    )
    assert payload["dispatched"] is None, (
        f"--dry-run must not dispatch, so `dispatched` must be null; got {payload['dispatched']!r}"
    )
    assert Path(payload["slate_path"]).is_file(), "--dry-run still writes the slate"
    assert list(sd.glob("run-*")) == [], (
        f"--dry-run must create no run dir; found {[p.name for p in sd.glob('run-*')]}"
    )


# ===========================================================================
# Behavior 7 -- the default path (and `dispatch` / `resume`) are unchanged
# ===========================================================================


def test_b07_default_path_stdout_is_the_human_rendering(plain_run) -> None:
    proc, _sd, _ws = plain_run
    assert proc.returncode == 0, f"the default `run` must still exit 0; got {proc.returncode}"
    for marker in (_AUTO_MARKER, _SUMMARY_MARKER):
        assert marker in proc.stdout, (
            f"without --json, {marker!r} must still print on stdout; got:\n{proc.stdout}"
        )
    with pytest.raises(json.JSONDecodeError):
        json.loads(proc.stdout)


def test_b07_json_is_declared_on_the_execution_verbs(tmp_path: Path) -> None:
    """`resume` now DECLARES `--json`, and `--json` alone is still a usage error.

    History, kept because the reasoning is the durable part. This guard was first
    written as ("dispatch", "resume") must REJECT `--json`, then narrowed to
    `resume` alone when `dispatch --json` shipped, on the ground that `resume` was
    "different in kind, not in schedule -- it has no slate and no gate, so its
    machine surface would be a smaller, differently-shaped document".

    That ground was measured and REFUTED by roadmap #196 (factory iter 173):
    `_cmd_resume` ends holding precisely the `(RunState, run_dir, ToolRegistry)`
    triple `_dispatched_json_payload` already consumes, so the document is not
    smaller and not differently shaped --- it is the identical nine keys, published
    from a third call site of one shared builder. So the flag is correct on all
    three execution verbs, and what survives from the original guard is the
    still-true half: `--json` does not excuse the REQUIRED `--run-dir`, so the
    flag on its own is an argparse usage error that writes nothing to stdout.
    """
    verb = "resume"
    helped = _run(verb, "--help", cwd=tmp_path)
    assert helped.returncode == 0, f"`{verb} --help` must exit 0"
    assert "--json" in helped.stdout, (
        f"`{verb}` is the recovery verb a script re-invokes, so its result must be "
        f"machine-readable: it must declare --json. Got:\n{helped.stdout}"
    )
    rejected = _run(verb, "--json", cwd=tmp_path)
    assert rejected.returncode == 2, (
        f"`{verb} --json` without the required --run-dir must still be a usage error "
        f"(exit 2); got {rejected.returncode}"
    )
    assert rejected.stdout == "", f"a usage error writes nothing to stdout; got {rejected.stdout!r}"


def test_b07_dispatch_human_summary_is_unchanged(plain_run, tmp_path: Path) -> None:
    """`dispatch` shares the helper this change refactors, so re-dispatching a
    goal from the plain run's own slate must still print today's summary."""
    _proc, sd, _ws = plain_run
    slate = sd / "slate.json"
    assert slate.is_file(), f"precondition: the plain run wrote {slate}"
    goals = json.loads(slate.read_text())["goals"]
    goal_id = goals[0]["id"]

    out_dir = tmp_path / "dispatch_state"
    proc = _run(
        "dispatch",
        "--slate",
        str(slate),
        "--goal-id",
        str(goal_id),
        "--yes",
        "--provider",
        "scripted",
        "--scripted-responses",
        str(SCRIPT),
        "--state-dir",
        str(out_dir),
        cwd=tmp_path,
    )
    assert proc.returncode == 0, (
        f"`dispatch --yes` must still succeed; got {proc.returncode}\nstderr:\n{proc.stderr}"
    )
    assert _SUMMARY_MARKER in proc.stdout, (
        f"`dispatch` must still print its run summary on STDOUT; got:\n{proc.stdout}"
    )
    for label in ("status", "run dir", "artifacts"):
        assert label in proc.stdout, f"`dispatch` summary must still report {label!r}"


# ===========================================================================
# Behavior 8 -- the failure path keeps its contract and emits no JSON
# ===========================================================================


def test_b08_missing_workspace_exits_2_with_empty_stdout(tmp_path: Path) -> None:
    missing = tmp_path / "no_such_workspace"
    assert not missing.exists(), "precondition: the workspace path does not exist"
    proc = _run(*_run_argv(missing, tmp_path / "state", "--json"), cwd=tmp_path)
    assert proc.returncode == 2, (
        f"a missing --workspace must still exit 2 under --json; got {proc.returncode}"
    )
    assert "error: workspace not found:" in proc.stderr, (
        f"the existing stderr contract must be unchanged; got:\n{proc.stderr}"
    )
    assert proc.stdout == "", (
        f"a failing --json run must emit NO JSON at all; stdout was {proc.stdout!r}"
    )


# ===========================================================================
# Behavior 9 -- the flag is documented in --help and in the README CLI table
# ===========================================================================


def test_b09_run_help_documents_json(tmp_path: Path) -> None:
    proc = _run("run", "--help", cwd=tmp_path)
    assert proc.returncode == 0, "`run --help` must exit 0"
    assert "--json" in proc.stdout, f"`run --help` must list --json; got:\n{proc.stdout}"
    # The help entry says what the flag does: one JSON object, human text on stderr.
    text = " ".join(proc.stdout.split())
    # The first "--json" is the usage line's optional-args summary; the flag's
    # help prose sits at the LAST occurrence, inside the options block.
    idx = text.rindex("--json")
    entry = text[idx : idx + 240].lower()
    assert "json" in entry and "stderr" in entry, (
        f"the --json help string must say the human output moves to stderr; got {entry!r}"
    )


def test_b09_readme_run_row_documents_json_below_the_human_marker() -> None:
    lines = README.read_text().splitlines()
    marker_idx = next((i for i, line in enumerate(lines) if _MARKER in line), None)
    assert marker_idx is not None, "README must still carry the human-owned portfolio marker"

    rows = [
        (i, line)
        for i, line in enumerate(lines)
        if line.startswith("| `run`") or line.startswith("|`run`")
    ]
    assert rows, "README's CLI table must still carry a `run` row"
    for i, row in rows:
        assert i > marker_idx, (
            f"the documented `run` row must live BELOW the human-owned marker "
            f"(row at line {i + 1}, marker at line {marker_idx + 1})"
        )
        assert "--json" in row, f"the README `run` row must document --json; got:\n{row}"
