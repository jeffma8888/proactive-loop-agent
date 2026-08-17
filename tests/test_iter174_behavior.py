"""Black-box behavior tests for state-dir iteration 170 (ships as ``factory iter 174``).

Feature under test: ``examples/check_run.py`` (roadmap #208) -- the first
COMMITTED consumer of the machine-readable document that ``pla run --json``,
``pla dispatch --json`` and ``pla resume --json`` all publish. It reads the
document on stdin, prints one summary line, and exits 0 only when the dispatched
run reached the terminal success status; 1 when the document parsed and the run
did not succeed; 2 when the input is malformed.

WHY THE SENTINEL IS DERIVED, NEVER TYPED
The spec records that the first draft of this consumer gated on
``status == "completed"`` and one offline run disproved it -- the sentinel is
``"done"``. So this module never spells that string as the gate value either: it
imports ``RunStatus`` and asks for ``RunStatus.DONE.value``, and behavior 4
ITERATES the live enum instead of hand-listing the four non-success members.
Rename or re-value a member and these tests move with it, which is the whole
point of the feature.

WHY THE SYNTHETIC DOCUMENTS ARE TIED TO A REAL ONE
Behavior 3 feeds a hand-built nine-key document, so it could drift away from
what the product actually publishes. It does not: the expected key set is read
OUT of the real ``run --json`` document produced by this module's fixture and
compared against the synthetic one, so a transcription error reds the build
instead of quietly testing a shape nothing emits.

SUBPROCESS BUDGET: EXACTLY ONE PRODUCER INVOCATION. Behaviors 1, 2, 3 and 8 all
read the SAME real ``pla run --json`` document, produced once in a module-scoped
fixture; behaviors 4-7 need no product invocation at all and build their
documents as dicts. The ``tester`` stage is measured near the 600s cap and a
tester timeout reverts the engineer's work too, so the cost is held down
deliberately. Every consumer invocation is a real subprocess because the claims
under test are about EXIT CODES and the SEPARATION of stdout from stderr, which
an in-process call cannot falsify honestly.

The producer runs against a PRIVATE COPY of ``examples/fixture_workspace`` under
``tmp_path_factory`` and writes its state there (the iter-142 shared-mutable-tree
hazard); nothing is written inside the product repo, and this module never
samples ``git status`` (rows #176/#204/#205).

ISOLATION CONTRACT (honored): every assertion is written against this
iteration's spec ("Expected Behaviors" in ``pm.md``), the repo's own ``tests/``
conventions, and the product's OBSERVABLE output obtained by RUNNING it. **No
file under ``src/`` was read, no ``examples/check_run.py`` source was read, no
engineer's or reviewer's note was consulted, and no ``git diff`` was inspected.**
Fully offline and deterministic: the bundled scripted provider only, no network,
no API key.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from proactive_loop.models import RunStatus

REPO = Path(__file__).resolve().parents[1]
CONSUMER = REPO / "examples" / "check_run.py"
FIXTURE = REPO / "examples" / "fixture_workspace"
SCRIPT = REPO / "examples" / "scripted_responses.json"

# DERIVED, never typed: the one value that means success. See the module docstring.
DONE = RunStatus.DONE.value

# Behavior 4's cases come from the LIVE enum, not from a hand-written list.
NON_SUCCESS_STATUSES: tuple[str, ...] = tuple(
    sorted(member.value for member in RunStatus if member.value != DONE)
)


# ---------------------------------------------------------------------------
# Helpers (iter-114 / iter-152 / iter-163 / iter-173 console-script convention)
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
    """A private copy of the offline fixture workspace under ``root``."""
    dest = root / "workspace"
    shutil.copytree(FIXTURE, dest)
    return dest


def _offline(state_dir: Path) -> list[str]:
    """The flags that pin every invocation to the bundled offline provider."""
    return [
        "--provider",
        "scripted",
        "--scripted-responses",
        str(SCRIPT),
        "--state-dir",
        str(state_dir),
    ]


def _consume(payload: str) -> subprocess.CompletedProcess[str]:
    """Run the committed consumer with ``payload`` on STDIN."""
    return subprocess.run(
        [sys.executable, str(CONSUMER)],
        input=payload,
        cwd=str(REPO),
        capture_output=True,
        text=True,
        timeout=120,
    )


def _sole_line(stream: str, label: str) -> str:
    """The one and only line on ``stream``, or a failure naming what came out."""
    lines = stream.splitlines()
    assert len(lines) == 1, f"{label}: expected exactly one line, got {lines!r}"
    return lines[0]


def _dispatched_document(status: str, keys: frozenset[str]) -> dict[str, object]:
    """A top-level dispatched-run document carrying exactly ``keys``.

    ``keys`` is read off the REAL producer by the fixture, so this synthetic
    document cannot drift away from the published shape.
    """
    values: dict[str, object] = {
        "goal_id": "goal-abc123",
        "run_id": "run-abc123",
        "status": status,
        "run_dir": "/tmp/does-not-need-to-exist/run-abc123",
        "artifacts": ["notes.md", "plan.md"],
        "iterations_used": 3,
        "llm_calls_used": 6,
        "retries": 0,
        "parse_errors": 0,
    }
    assert keys == frozenset(values), (
        "the real producer's dispatched-run key set has changed; update this "
        f"synthetic document: produced={sorted(keys)} synthetic={sorted(values)}"
    )
    return values


# ---------------------------------------------------------------------------
# The single real producer invocation, shared by behaviors 1, 2, 3 and 8.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def run_json(tmp_path_factory: pytest.TempPathFactory) -> tuple[str, dict]:
    """``(raw_stdout, parsed_document)`` from ONE real ``pla run --json``."""
    root = tmp_path_factory.mktemp("iter174-run")
    workspace = _isolated_workspace(root)
    proc = _run(
        "run",
        "--workspace",
        str(workspace),
        *_offline(root / "state"),
        "--json",
        cwd=REPO,
    )
    assert proc.returncode == 0, (
        f"the producer must succeed before its document can be consumed; "
        f"rc={proc.returncode}\nstderr:\n{proc.stderr}"
    )
    document = json.loads(proc.stdout)
    assert isinstance(document, dict), type(document).__name__
    return proc.stdout, document


# ---------------------------------------------------------------------------
# Behavior 1 -- real producer, success path.
# ---------------------------------------------------------------------------


def test_b1_real_run_json_document_is_accepted_and_exits_zero(
    run_json: tuple[str, dict],
) -> None:
    raw, document = run_json
    assert document["dispatched"] is not None, (
        "this fixture must dispatch a run, or behavior 1 is vacuous"
    )
    proc = _consume(raw)
    assert proc.returncode == 0, (
        f"a successful real `pla run --json` document must exit 0; "
        f"rc={proc.returncode}\nstdout:{proc.stdout!r}\nstderr:{proc.stderr!r}"
    )


# ---------------------------------------------------------------------------
# Behavior 2 -- success output shape.
# ---------------------------------------------------------------------------


def test_b2_success_prints_one_ok_line_naming_the_run_and_status(
    run_json: tuple[str, dict],
) -> None:
    raw, document = run_json
    run_id = document["dispatched"]["run_id"]
    proc = _consume(raw)
    line = _sole_line(proc.stdout, "stdout")
    assert line.startswith("ok: "), line
    assert run_id in line, (
        f"the summary must carry the document's own run_id {run_id!r}: {line!r}"
    )
    assert f"status={DONE}" in line, line
    assert proc.stderr == "", f"a successful consume must be silent on stderr: {proc.stderr!r}"


# ---------------------------------------------------------------------------
# Behavior 3 -- the same consumer serves the top-level document shape that
# `dispatch --json` and `resume --json` publish.
# ---------------------------------------------------------------------------


def test_b3_top_level_dispatched_document_is_accepted_too(
    run_json: tuple[str, dict],
) -> None:
    _, document = run_json
    keys = frozenset(document["dispatched"])
    payload = _dispatched_document(DONE, keys)
    proc = _consume(json.dumps(payload))
    assert proc.returncode == 0, (
        f"the nine-key document at TOP level is what `dispatch --json` and "
        f"`resume --json` publish and must be accepted; rc={proc.returncode}\n"
        f"stdout:{proc.stdout!r}\nstderr:{proc.stderr!r}"
    )
    line = _sole_line(proc.stdout, "stdout")
    assert line.startswith("ok: "), line
    assert str(payload["run_id"]) in line, line
    assert f"status={DONE}" in line, line
    assert proc.stderr == "", proc.stderr


# ---------------------------------------------------------------------------
# Behavior 4 -- every non-success status in the LIVE enum vocabulary fails.
# ---------------------------------------------------------------------------


def test_b4_vocabulary_is_derived_and_non_empty() -> None:
    """Anti-vacuity: the parametrization below must have real cases to run."""
    assert NON_SUCCESS_STATUSES, (
        "no non-success RunStatus member was found, so behavior 4 would assert "
        "nothing at all"
    )
    assert DONE not in NON_SUCCESS_STATUSES, NON_SUCCESS_STATUSES


@pytest.mark.parametrize("status", NON_SUCCESS_STATUSES)
def test_b4_non_success_status_exits_one_and_names_the_status(
    status: str, run_json: tuple[str, dict]
) -> None:
    _, document = run_json
    keys = frozenset(document["dispatched"])
    proc = _consume(json.dumps(_dispatched_document(status, keys)))
    assert proc.returncode == 1, (
        f"status={status!r} parsed fine but did not succeed, which is exit 1; "
        f"rc={proc.returncode}\nstderr:{proc.stderr!r}"
    )
    assert proc.stdout == "", f"a failing run must print no summary: {proc.stdout!r}"
    line = _sole_line(proc.stderr, "stderr")
    assert line.startswith("fail: "), line
    assert status in line, f"the diagnosis must name the status {status!r}: {line!r}"


# ---------------------------------------------------------------------------
# Behavior 5 -- nothing dispatched (explicit null, and the key absent).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("shape", ["explicit-null", "key-absent"])
def test_b5_nothing_dispatched_exits_one_and_says_so(shape: str) -> None:
    payload: dict[str, object] = {
        "goal_count": 2,
        "needs_approval": True,
        "slate_path": "/tmp/slate.json",
        "top_goal": "Draft a learning plan",
        "workspace_root": "/tmp/workspace",
    }
    if shape == "explicit-null":
        payload["dispatched"] = None
    proc = _consume(json.dumps(payload))
    assert proc.returncode == 1, (
        f"{shape}: a parsed document with no dispatched run is exit 1, not a "
        f"malformed-input 2; rc={proc.returncode}\nstderr:{proc.stderr!r}"
    )
    assert proc.stdout == "", proc.stdout
    line = _sole_line(proc.stderr, "stderr")
    assert line.startswith("fail: "), line
    assert "dispatch" in line.lower(), (
        f"{shape}: the diagnosis must say that no run was dispatched: {line!r}"
    )


# ---------------------------------------------------------------------------
# Behavior 6 -- not JSON at all.
# ---------------------------------------------------------------------------


def test_b6_input_that_is_not_json_exits_two() -> None:
    proc = _consume("not json")
    assert proc.returncode == 2, (
        f"malformed input is exit 2, kept distinct from a failed run's 1; "
        f"rc={proc.returncode}\nstderr:{proc.stderr!r}"
    )
    assert proc.stdout == "", proc.stdout
    assert _sole_line(proc.stderr, "stderr").startswith("error: "), proc.stderr


# ---------------------------------------------------------------------------
# Behavior 7 -- valid JSON that is not an object (the `runs --json` array).
# ---------------------------------------------------------------------------


def test_b7_json_array_exits_two_not_one() -> None:
    payload = json.dumps([{"run_id": "run-abc123", "status": DONE}])
    proc = _consume(payload)
    assert proc.returncode == 2, (
        "a JSON array is the shape `runs --json` emits, not a run document; it "
        f"is malformed INPUT (2), not a failed run (1); rc={proc.returncode}\n"
        f"stderr:{proc.stderr!r}"
    )
    assert proc.stdout == "", proc.stdout
    assert _sole_line(proc.stderr, "stderr").startswith("error: "), proc.stderr


# ---------------------------------------------------------------------------
# Behavior 8 -- the shape discriminator is sound against the live producer.
# ---------------------------------------------------------------------------


def test_b8_run_json_publishes_no_top_level_status_key(
    run_json: tuple[str, dict],
) -> None:
    """A top-level ``status`` must mean "this IS the dispatched document".

    If a future iteration adds a top-level ``status`` to ``run --json``, the
    consumer's discriminator becomes ambiguous and it may read the wrong object.
    This test reds the build at that moment instead of letting the branch change
    silently.
    """
    _, document = run_json
    assert "status" not in document, (
        "`pla run --json` grew a top-level `status` key, so "
        "\"a top-level status means this IS the dispatched document\" is no "
        f"longer a sound discriminator; top level is now {sorted(document)}"
    )
    assert "dispatched" in document, (
        f"`pla run --json` must still wrap its run under `dispatched`: "
        f"{sorted(document)}"
    )
