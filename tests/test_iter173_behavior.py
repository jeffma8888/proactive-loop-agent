"""Black-box behavior tests for state-dir iteration 169 (ships as ``factory iter 173``).

Feature under test: ``pla resume --json`` (roadmap #196) -- the RECOVERY verb
becomes machine-readable. Under ``--json`` the entire stdout of a successful
resume is exactly one JSON object holding the same nine keys ``dispatch --json``
publishes (one shared document, not a second dialect), the human run summary
moves to STDERR unchanged, and the no-checkpoint refusal still exits 2 with an
exactly-empty stdout.

WHY EVERY BEHAVIOR HERE IS DRIVEN THROUGH A REAL SUBPROCESS
Behaviors 1, 4, 5 and 8 are claims about the SEPARATION of two output streams
(exactly one document on stdout, all human text on stderr, an exactly-empty
stdout on the refusal). An in-process ``capsys`` run cannot falsify them
honestly, so this module spends real ``pla`` console-script invocations (the
iter-114 / iter-152 / iter-163 convention) and reads the actual file
descriptors. Cost is bounded by module-scoped fixtures: three executing runs
plus one scan and one dispatch, all against the bundled scripted provider, each
measured at ~0.2s.

NOTHING IS TRANSCRIBED FROM THE FIXTURE. A run dir is read out of the
``run --json`` document that created it, never composed from a goal id -- goal
ids are NOT stable across two scans of the same workspace (measured: two runs
over one immutable workspace copy produced ``2c58f8d7596e`` and
``66c9a699a623``), so a hand-built ``run-<id>`` path is a broken test. The key
set of behavior 3 is obtained by RUNNING ``dispatch --json`` in the same build,
not compared to a stored list.

EVERY RESUME GETS ITS OWN RUN. ``resume`` MUTATES the checkpoint it resumes
(measured: a finished run at ``iterations_used=3`` reported 6 after one resume
and 8 -- ``budget_exhausted`` -- after a second), so two resumes sharing one run
dir would be order-dependent and would flake under ``-n auto``. The fixtures
therefore never share a run dir.

ISOLATION CONTRACT (honored): every assertion is written against this
iteration's spec ("Expected Behaviors" in ``pm.md``), the repo's own ``tests/``
conventions, and the product's OBSERVABLE output obtained by RUNNING it. **No
file under ``src/`` was read, no engineer's or reviewer's note was consulted,
and no ``git diff`` was inspected.** Fully offline and deterministic: the
bundled scripted provider only, no network, no API key. Every invocation is
rooted at a PRIVATE COPY of ``examples/fixture_workspace`` under a
``tmp_path_factory`` dir and writes its state there -- nothing is written inside
the product repo, and no run is rooted at the in-repo fixture (the iter-142
shared-mutable-tree hazard).
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

# The published dispatched-run document (spec behavior 2). Spelled out because
# behavior 2 is an EXACT key-set claim; behavior 3 then re-derives the same set
# by running `dispatch --json`, so a drift in either direction is caught.
_DOCUMENT_KEYS = frozenset(
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

# The human summary marker the dispatch/resume path prints (spec behaviors 4-5).
_SUMMARY_MARKER = "dispatched :"

# Spec behavior 9: the LIVE verb count. iter-173 itself added a flag, not a verb, but the
# constant tracks the live parser, so a later ADDITIVE verb bumps this one literal here
# (iter-197 added `trend`) rather than leaving a test whose NAME encodes a decaying number.
_EXPECTED_VERB_COUNT = 17


# ---------------------------------------------------------------------------
# Helpers (iter-114 / iter-152 / iter-163 console-script convention)
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


def _one_json_object(stdout: str, label: str) -> dict:
    """Parse stdout as EXACTLY one JSON object, or fail with the raw text.

    ``json.loads`` rejects trailing content, so a successful parse is itself the
    proof that no prose and no second document accompany the object.
    """
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:  # pragma: no cover - failure reporting
        pytest.fail(
            f"{label}: stdout must be exactly one JSON value; {exc}\nstdout:\n{stdout!r}"
        )
    assert isinstance(payload, dict), (
        f"{label}: the document must be a JSON object (dict), got {type(payload).__name__}"
    )
    return payload


_FLAG = re.compile(r"--[a-z][a-z0-9-]*")


def _declared_flags(help_text: str) -> set[str]:
    """Every long option a verb's ``--help`` mentions.

    Enumerated rather than membership-tested so an ABSENCE claim is evidence
    (here is the whole set, X is not in it) instead of a silent non-match.
    """
    return set(_FLAG.findall(help_text))


_HEXID = re.compile(r"\b[0-9a-f]{12}\b")


def _normalize(text: str, *state_dirs: Path) -> list[str]:
    """Human lines with per-invocation paths and generated ids folded away.

    Both folds are structural, not cosmetic: each invocation gets its own state
    dir by construction and the 12-hex run/goal ids are minted per invocation,
    so two otherwise identical summaries differ in those tokens alone. Folding
    them leaves the STRUCTURE of every line, which is what "the same summary,
    moved to the other stream" can mean across two processes.
    """
    folded = text
    for sd in state_dirs:
        folded = folded.replace(str(sd.resolve()), "<SD>").replace(str(sd), "<SD>")
    folded = _HEXID.sub("<ID>", folded)
    return [line.rstrip() for line in folded.splitlines() if line.strip()]


def _executing_run(root: Path, workspace: Path) -> tuple[dict, Path, Path]:
    """One offline ``run --json``. Returns (dispatched document, run dir, state dir).

    The run dir is READ from the document the run itself published, never
    composed from a goal id.
    """
    sd = root / "state"
    proc = _run("run", "--workspace", str(workspace), *_offline(sd), "--json", cwd=root)
    assert proc.returncode == 0, (
        f"the setup `run --json` must exit 0; got {proc.returncode}\nstderr:\n{proc.stderr}"
    )
    document = _one_json_object(proc.stdout, "setup `run --json`")
    dispatched = document.get("dispatched")
    assert isinstance(dispatched, dict), (
        "the setup `run --json` must have auto-dispatched a goal (its `dispatched` "
        f"sub-object is the resumable run); document keys: {sorted(document)}"
    )
    run_dir = Path(str(dispatched["run_dir"]))
    assert (run_dir / "checkpoint.json").is_file(), (
        f"the setup run must leave a resumable checkpoint in {run_dir}; "
        f"it holds {sorted(p.name for p in run_dir.iterdir())}"
    )
    return dispatched, run_dir, sd


# ---------------------------------------------------------------------------
# Module-scoped product invocations
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def workspace(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """ONE private, immutable copy of the fixture workspace (artifacts land in state dirs)."""
    return _isolated_workspace(tmp_path_factory.mktemp("i173_ws"))


@pytest.fixture(scope="module")
def json_resume(
    tmp_path_factory: pytest.TempPathFactory, workspace: Path
) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
    """A fresh run, then ``resume --run-dir DIR --json``.

    Returns (resume proc, run dir, state dir).
    """
    root = tmp_path_factory.mktemp("i173_json")
    _, run_dir, sd = _executing_run(root, workspace)
    proc = _run("resume", "--run-dir", str(run_dir), *_offline(sd), "--json", cwd=root)
    return proc, run_dir, sd


@pytest.fixture(scope="module")
def plain_resume(
    tmp_path_factory: pytest.TempPathFactory, workspace: Path
) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
    """The same recovery WITHOUT ``--json`` -- the unchanged default path (behavior 5).

    Its own run, because ``resume`` mutates the checkpoint it resumes.
    """
    root = tmp_path_factory.mktemp("i173_plain")
    _, run_dir, sd = _executing_run(root, workspace)
    proc = _run("resume", "--run-dir", str(run_dir), *_offline(sd), cwd=root)
    return proc, run_dir, sd


@pytest.fixture(scope="module")
def dispatch_document(tmp_path_factory: pytest.TempPathFactory, workspace: Path) -> dict:
    """The top-level document of a real ``dispatch --json``, for behavior 3.

    Behavior 3 is an equality between two LIVE surfaces, so the comparand is
    produced by running the other verb in this same build rather than stored.
    """
    root = tmp_path_factory.mktemp("i173_dispatch")
    sd = root / "state"
    scan = _run(
        "scan", "--workspace", str(workspace), *_offline(sd), "--format", "json", cwd=root
    )
    assert scan.returncode == 0, f"the setup `scan` must exit 0; stderr:\n{scan.stderr}"
    slate = sd / "slate.json"
    assert slate.is_file(), f"`scan` must write {slate}; state dir holds {list(sd.iterdir())}"

    goals = json.loads(slate.read_text())["goals"]
    dispatchable = sorted(
        (g for g in goals if g.get("appropriate_now", True)),
        key=lambda g: g["score"],
        reverse=True,
    )
    assert dispatchable, f"the fixture slate must hold a dispatchable goal; got {len(goals)}"
    proc = _run(
        "dispatch",
        "--slate",
        str(slate),
        "--goal-id",
        str(dispatchable[0]["id"]),
        *_offline(sd),
        "--json",
        "--yes",
        cwd=root,
    )
    assert proc.returncode == 0, (
        f"the setup `dispatch --json --yes` must exit 0; got {proc.returncode}"
        f"\nstderr:\n{proc.stderr}"
    )
    return _one_json_object(proc.stdout, "setup `dispatch --json`")


# ===========================================================================
# Behavior 1 -- `resume --json` exits 0 and stdout is exactly one JSON object
# ===========================================================================


def test_b01_resume_json_exits_zero_with_one_json_object_on_stdout(
    json_resume: tuple[subprocess.CompletedProcess[str], Path, Path],
) -> None:
    proc, run_dir, _ = json_resume
    assert proc.returncode == 0, (
        f"`resume --json` on a loadable checkpoint ({run_dir}) must exit 0; "
        f"got {proc.returncode}\nstderr:\n{proc.stderr}"
    )
    payload = _one_json_object(proc.stdout, "`resume --json`")
    assert payload, "the resumed-run document must not be empty"


# ===========================================================================
# Behavior 2 -- the key set is EXACTLY the nine published keys
# ===========================================================================


def test_b02_document_key_set_is_exactly_the_nine_published_keys(
    json_resume: tuple[subprocess.CompletedProcess[str], Path, Path],
) -> None:
    payload = _one_json_object(json_resume[0].stdout, "`resume --json`")
    keys = frozenset(payload)
    assert keys == _DOCUMENT_KEYS, (
        "`resume --json` must publish exactly the nine dispatched-run keys.\n"
        f"missing: {sorted(_DOCUMENT_KEYS - keys)}\nunexpected: {sorted(keys - _DOCUMENT_KEYS)}"
    )


# ===========================================================================
# Behavior 3 -- one shared document: the key set EQUALS `dispatch --json`'s
# ===========================================================================


def test_b03_key_set_equals_dispatch_json_top_level(
    json_resume: tuple[subprocess.CompletedProcess[str], Path, Path],
    dispatch_document: dict,
) -> None:
    resumed = frozenset(_one_json_object(json_resume[0].stdout, "`resume --json`"))
    dispatched = frozenset(dispatch_document)
    assert resumed == dispatched, (
        "one CLI must not grow two dialects of one document: `resume --json` and "
        "`dispatch --json` must publish the SAME key set.\n"
        f"only in resume: {sorted(resumed - dispatched)}\n"
        f"only in dispatch: {sorted(dispatched - resumed)}"
    )


# ===========================================================================
# Behavior 4 -- the human summary is on STDERR; no line of it is on stdout
# ===========================================================================


def test_b04_human_summary_moves_to_stderr_and_stdout_carries_no_prose(
    json_resume: tuple[subprocess.CompletedProcess[str], Path, Path],
) -> None:
    proc, _, _ = json_resume
    assert _SUMMARY_MARKER in proc.stderr, (
        f"the human run summary must still be printed, on stderr, under --json; "
        f"stderr:\n{proc.stderr!r}"
    )
    assert _SUMMARY_MARKER not in proc.stdout, (
        "stdout under --json carries the document only; found the human summary "
        f"marker {_SUMMARY_MARKER!r} in stdout:\n{proc.stdout!r}"
    )
    # The label lines are the summary's own shape: `status     : done` etc. None
    # may appear on stdout. Derived from the stderr text rather than hardcoded,
    # so a reworded summary cannot make this check vacuous.
    labels = [
        line.split(":", 1)[0]
        for line in proc.stderr.splitlines()
        if re.match(r"^[a-z][a-z ]*\s*:", line)
    ]
    assert labels, f"the summary must be label-shaped lines; stderr:\n{proc.stderr!r}"
    for label in labels:
        assert f"{label}:" not in proc.stdout, (
            f"the summary line {label.strip()!r} must not appear on stdout under --json;"
            f"\nstdout:\n{proc.stdout!r}"
        )


# ===========================================================================
# Behavior 5 -- additive-flag regression guard: the default path is unchanged
# ===========================================================================


def test_b05_plain_resume_prints_the_summary_on_stdout_and_nothing_on_stderr(
    plain_resume: tuple[subprocess.CompletedProcess[str], Path, Path],
) -> None:
    proc, run_dir, _ = plain_resume
    assert proc.returncode == 0, (
        f"`resume` without --json must still exit 0 on {run_dir}; got {proc.returncode}"
        f"\nstderr:\n{proc.stderr}"
    )
    assert _SUMMARY_MARKER in proc.stdout, (
        "without --json the human summary stays on STDOUT (that is the pre-change "
        f"contract); stdout:\n{proc.stdout!r}"
    )
    assert proc.stderr == "", (
        f"without --json `resume` must write NOTHING to stderr; got {proc.stderr!r}"
    )


def test_b05_the_default_summary_is_the_same_text_merely_relocated(
    plain_resume: tuple[subprocess.CompletedProcess[str], Path, Path],
    json_resume: tuple[subprocess.CompletedProcess[str], Path, Path],
) -> None:
    """The strongest available reading of "byte-identical to the pre-change build".

    This build cannot execute its own predecessor, so the falsifiable claim is
    that the summary the default path prints on stdout is the SAME summary
    ``--json`` prints on stderr -- same lines, same order, same counters -- with
    only the per-invocation state dir and 12-hex ids folded away. If `--json`
    had rewritten, trimmed or re-ordered the human text, this reds.
    """
    plain, _, plain_sd = plain_resume
    jsonp, _, json_sd = json_resume
    assert _normalize(plain.stdout, plain_sd) == _normalize(jsonp.stderr, json_sd), (
        "--json must MOVE the summary, not rewrite it.\n"
        f"default stdout:\n{plain.stdout}\n--json stderr:\n{jsonp.stderr}"
    )


# ===========================================================================
# Behavior 6 -- `status` is a plain lower-case string equal to the checkpoint's
# ===========================================================================


def test_b06_status_is_a_plain_lowercase_string_matching_the_checkpoint(
    json_resume: tuple[subprocess.CompletedProcess[str], Path, Path],
) -> None:
    proc, run_dir, _ = json_resume
    payload = _one_json_object(proc.stdout, "`resume --json`")
    status = payload["status"]
    assert isinstance(status, str), (
        f"`status` must be a JSON string, got {type(status).__name__}: {status!r}"
    )
    assert "RunStatus" not in status and "." not in status, (
        f"`status` must be the plain value, never an enum repr; got {status!r}"
    )
    assert status == status.lower() and status.strip() == status, (
        f"`status` must be plain lower-case with no padding; got {status!r}"
    )
    checkpoint = json.loads((run_dir / "checkpoint.json").read_text())
    assert status == checkpoint["status"], (
        "the published status must be the status this run actually recorded; "
        f"document {status!r} vs checkpoint.json {checkpoint['status']!r}"
    )


# ===========================================================================
# Behavior 7 -- `artifacts` is an array of strings naming files that exist
# ===========================================================================


def test_b07_artifacts_is_an_array_of_existing_file_paths(
    json_resume: tuple[subprocess.CompletedProcess[str], Path, Path],
) -> None:
    payload = _one_json_object(json_resume[0].stdout, "`resume --json`")
    artifacts = payload["artifacts"]
    assert isinstance(artifacts, list), (
        f"`artifacts` must be a JSON array, got {type(artifacts).__name__}: {artifacts!r}"
    )
    assert artifacts, (
        "the resumed fixture run produces artifacts, so an empty array would mean the "
        "document lost them"
    )
    for entry in artifacts:
        assert isinstance(entry, str), (
            f"every `artifacts` entry must be a string path, got {type(entry).__name__}: {entry!r}"
        )
        assert Path(entry).is_file(), (
            f"`artifacts` must name files that exist on disk; {entry!r} is not a file"
        )


# ===========================================================================
# Behavior 8 -- no loadable checkpoint: exit 2, one error line, EMPTY stdout
# ===========================================================================


def test_b08_no_checkpoint_exits_two_with_one_error_line_and_empty_stdout(
    tmp_path: Path,
) -> None:
    empty = tmp_path / "not-a-run"
    empty.mkdir()
    proc = _run("resume", "--run-dir", str(empty), *_offline(tmp_path / "state"), "--json",
                cwd=tmp_path)
    assert proc.returncode == 2, (
        f"`resume --json` on a dir with no checkpoint must exit 2; got {proc.returncode}"
        f"\nstdout:\n{proc.stdout!r}\nstderr:\n{proc.stderr!r}"
    )
    assert proc.stdout == "", (
        "the refusal must leave stdout COMPLETELY empty -- not `{}`, not a newline -- so a "
        f"caller's `json.loads` fails loudly instead of reading a fake result; got {proc.stdout!r}"
    )
    lines = [line for line in proc.stderr.splitlines() if line.strip()]
    assert len(lines) == 1, (
        f"the refusal must be exactly one stderr line; got {len(lines)}:\n{proc.stderr!r}"
    )
    accepted = {
        f"error: no checkpoint found in {empty}",
        f"error: no checkpoint found in {empty.resolve()}",
    }
    assert lines[0].strip() in accepted, (
        f"the refusal line must name the dir it looked in; got {lines[0]!r}, "
        f"expected one of {sorted(accepted)}"
    )


# ===========================================================================
# Behavior 9 -- `resume --help` lists --json; `pla --help` lists every live verb
# ===========================================================================


def test_b09_resume_help_declares_json(tmp_path: Path) -> None:
    proc = _run("resume", "--help", cwd=tmp_path)
    assert proc.returncode == 0, (
        f"`resume --help` must exit 0; got {proc.returncode}\nstderr:\n{proc.stderr}"
    )
    flags = _declared_flags(proc.stdout)
    assert "--json" in flags, (
        "`resume` is the verb a supervising script re-invokes after a failure, so it "
        f"must declare --json. It declares {sorted(flags)}"
    )


def test_b09_top_level_help_lists_every_live_verb(tmp_path: Path) -> None:
    """`--help` must list every live verb -- the count is the module constant.

    This iteration added a FLAG, not a verb, so it did not move the count itself;
    the constant tracks the live parser so a LATER additive verb updates one literal
    here rather than leaving a test whose NAME encodes a decaying number.
    """
    proc = _run("--help", cwd=tmp_path)
    assert proc.returncode == 0, (
        f"`pla --help` must exit 0; got {proc.returncode}\nstderr:\n{proc.stderr}"
    )
    match = re.search(r"\{([a-z][a-z,]+)\}", proc.stdout)
    assert match is not None, (
        f"`pla --help` must list its verbs in a choice group; stdout:\n{proc.stdout}"
    )
    verbs = [v for v in match.group(1).split(",") if v]
    assert len(verbs) == _EXPECTED_VERB_COUNT, (
        f"`pla --help` must list every live verb: expected {_EXPECTED_VERB_COUNT}, "
        f"got {len(verbs)}: {verbs}"
    )
