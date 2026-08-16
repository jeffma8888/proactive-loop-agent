"""Black-box behavior tests for state-dir iteration 157 (ships as ``factory iter 163``).

Feature under test: ``pla dispatch --json`` -- the approval-gated execution path
becomes scriptable. Under ``--json`` the ENTIRE stdout of a successful dispatch
is exactly one JSON object describing the run it just performed (the same
document ``run --json`` nests under ``dispatched``), the human summary moves to
STDERR unchanged, and every exit code plus the empty-stdout rule on a refusal is
preserved. ``resume`` rejected the flag when this module shipped; behavior 8
was INVERTED in factory iter 173 when ``resume --json`` shipped (roadmap
#196) -- see ``test_b08_resume_declares_json``.

WHY EVERY PROCESS-LEVEL BEHAVIOR HERE IS DRIVEN THROUGH A REAL SUBPROCESS
Behaviors 2, 5, 6 and 7 are claims about the SEPARATION of two output streams
(one document on stdout, all human text on stderr, an exactly-empty stdout on
each refusal). An in-process ``capsys`` run cannot falsify them honestly: a
redirect implemented against ``sys.__stdout__`` would bypass ``capsys`` and a
broken split could still read green. So this module spends real ``pla`` console
script invocations (the iter-114 / iter-152 convention) and reads the actual
file descriptors. Cost is bounded by module-scoped fixtures: ONE scan plus four
executing runs, shared across every behavior; the six refusal invocations never
enter the loop.

NOTHING IS TRANSCRIBED FROM THE FIXTURE. The four goal ids are read out of the
slate this module's own ``scan`` wrote, and the gate roles (auto-eligible,
sensitive, below-threshold, BLOCKED) are DERIVED from that slate's fields
(``category`` / ``appropriate_now`` / ``score``) rather than hardcoded, so a
change to the example workspace cannot silently repoint a behavior at the wrong
goal. The ``run --json`` key set of behavior 3 is obtained by RUNNING that verb
in the same build and compared to ``dispatch --json``'s, not to a stored list.

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

# The published dispatched-run document (spec behavior 3).
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

# Human markers the dispatch path prints today (spec behaviors 5 and 6).
_SUMMARY_MARKER = "dispatched :"
_APPROVAL_MARKER = "needs approval"
_YES_HINT = "re-run with --yes"
_BLOCKED_MARKER = "BLOCKED"

_SENSITIVE_CATEGORY = "finance_legal"


# ---------------------------------------------------------------------------
# Helpers (iter-114 / iter-152 console-script convention)
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


def _dispatch_argv(slate: Path, goal_id: str, state_dir: Path, *extra: str) -> list[str]:
    return [
        "dispatch",
        "--slate",
        str(slate),
        "--goal-id",
        goal_id,
        *_offline(state_dir),
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
        pytest.fail(
            f"{label}: stdout must be exactly one JSON object; {exc}\nstdout:\n{stdout!r}"
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

    Both folds are needed and both are structural, not cosmetic: each run gets
    its own state dir by construction, and the 12-hex run id is minted per
    invocation, so the run dir and every artifact path differ between two
    otherwise identical dispatches. Folding both leaves the STRUCTURE of every
    line, which is what "prints in full, unchanged" can mean across two runs.
    """
    folded = text
    for sd in state_dirs:
        folded = folded.replace(str(sd.resolve()), "<SD>").replace(str(sd), "<SD>")
    folded = _HEXID.sub("<ID>", folded)
    return [line.rstrip() for line in folded.splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# Module-scoped product invocations
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def workspace(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """ONE private copy of the fixture workspace, shared by every invocation.

    Sharing it is deliberate: a goal id is derived from the workspace it was
    synthesized over, so a slate scanned from a different copy would carry ids
    that no other run in this module could dispatch. Nothing writes into the
    workspace (artifacts land in a state dir), so the tree stays immutable.
    """
    return _isolated_workspace(tmp_path_factory.mktemp("i163_ws"))


@pytest.fixture(scope="module")
def slate(tmp_path_factory: pytest.TempPathFactory, workspace: Path) -> Path:
    """The slate every dispatch in this module reads -- written by a real scan."""
    root = tmp_path_factory.mktemp("i163_scan")
    sd = root / "state"
    proc = _run(
        "scan", "--workspace", str(workspace), *_offline(sd), "--format", "json", cwd=root
    )
    assert proc.returncode == 0, f"the setup `scan` must exit 0; stderr:\n{proc.stderr}"
    path = sd / "slate.json"
    assert path.is_file(), f"`scan` must write {path}; state dir holds {list(sd.iterdir())}"
    return path


@pytest.fixture(scope="module")
def goal_ids(slate: Path) -> dict[str, str]:
    """The four gate roles, DERIVED from the slate rather than transcribed.

    ``sensitive`` and ``blocked`` come from the goal's own fields. The
    auto-eligible pick is the highest-scoring goal that is neither, and the
    below-threshold pick is the lowest-scoring such goal -- the same ordering
    the gate itself uses, so the roles follow the slate if the example
    workspace ever changes.
    """
    goals = json.loads(slate.read_text())["goals"]
    assert len(goals) >= 4, f"the fixture slate must hold >=4 goals; got {len(goals)}"

    blocked = [g for g in goals if not g.get("appropriate_now", True)]
    sensitive = [
        g
        for g in goals
        if g.get("category") == _SENSITIVE_CATEGORY and g.get("appropriate_now", True)
    ]
    plain = sorted(
        (
            g
            for g in goals
            if g.get("appropriate_now", True) and g.get("category") != _SENSITIVE_CATEGORY
        ),
        key=lambda g: g["score"],
        reverse=True,
    )
    assert blocked, "the fixture slate must hold one goal the gate BLOCKS"
    assert sensitive, f"the fixture slate must hold one {_SENSITIVE_CATEGORY} goal"
    assert len(plain) >= 2, (
        "the fixture slate must hold one auto-eligible goal and one below the "
        f"auto-dispatch threshold; got {len(plain)} unblocked non-sensitive goals"
    )
    return {
        "auto": plain[0]["id"],
        "below_threshold": plain[-1]["id"],
        "sensitive": sensitive[0]["id"],
        "blocked": blocked[0]["id"],
    }


@pytest.fixture(scope="module")
def json_dispatch(
    tmp_path_factory: pytest.TempPathFactory, slate: Path, goal_ids: dict[str, str]
) -> tuple[subprocess.CompletedProcess[str], Path]:
    """`dispatch --json` on the auto-eligible goal. Returns (proc, state_dir)."""
    root = tmp_path_factory.mktemp("i163_json")
    sd = root / "state"
    proc = _run(*_dispatch_argv(slate, goal_ids["auto"], sd, "--json"), cwd=root)
    return proc, sd


@pytest.fixture(scope="module")
def plain_dispatch(
    tmp_path_factory: pytest.TempPathFactory, slate: Path, goal_ids: dict[str, str]
) -> tuple[subprocess.CompletedProcess[str], Path]:
    """The same dispatch WITHOUT `--json` -- the unchanged default path."""
    root = tmp_path_factory.mktemp("i163_plain")
    sd = root / "state"
    proc = _run(*_dispatch_argv(slate, goal_ids["auto"], sd), cwd=root)
    return proc, sd


@pytest.fixture(scope="module")
def approved_dispatch(
    tmp_path_factory: pytest.TempPathFactory, slate: Path, goal_ids: dict[str, str]
) -> tuple[subprocess.CompletedProcess[str], Path]:
    """`dispatch --json --yes` on the sensitive goal: the human-approved path.

    This is the invocation the feature exists for -- an orchestrator executing
    exactly the goal a human just approved -- so it is covered as well as the
    auto-eligible one.
    """
    root = tmp_path_factory.mktemp("i163_yes")
    sd = root / "state"
    proc = _run(*_dispatch_argv(slate, goal_ids["sensitive"], sd, "--json", "--yes"), cwd=root)
    return proc, sd


@pytest.fixture(scope="module")
def run_json(
    tmp_path_factory: pytest.TempPathFactory, workspace: Path
) -> subprocess.CompletedProcess[str]:
    """One `run --json`, whose `dispatched` sub-object behavior 3 compares against."""
    root = tmp_path_factory.mktemp("i163_runjson")
    sd = root / "state"
    proc = _run("run", "--workspace", str(workspace), *_offline(sd), "--json", cwd=root)
    return proc


# ===========================================================================
# Behavior 1 -- `dispatch --help` exits 0 and declares --json
# ===========================================================================


def test_b01_dispatch_help_declares_json(tmp_path: Path) -> None:
    proc = _run("dispatch", "--help", cwd=tmp_path)
    assert proc.returncode == 0, (
        f"`dispatch --help` must exit 0; got {proc.returncode}\nstderr:\n{proc.stderr}"
    )
    flags = _declared_flags(proc.stdout)
    assert "--json" in flags, (
        f"`dispatch --help` must list --json; the flags it declares are {sorted(flags)}"
    )


# ===========================================================================
# Behavior 2 -- exit 0 and the ENTIRE stdout is exactly one JSON object
# ===========================================================================


def test_b02_json_dispatch_exits_zero_and_stdout_is_one_json_object(json_dispatch) -> None:
    proc, _sd = json_dispatch
    assert proc.returncode == 0, (
        f"`dispatch --json` must exit 0 on a gate-allowed goal; got {proc.returncode}"
        f"\nstderr:\n{proc.stderr}"
    )
    _one_json_object(proc.stdout, "dispatch --json")


def test_b02_approved_dispatch_exits_zero_and_stdout_is_one_json_object(
    approved_dispatch, goal_ids
) -> None:
    """The `--yes` half of behavior 2: a NEEDS_APPROVAL goal a human approved."""
    proc, _sd = approved_dispatch
    assert proc.returncode == 0, (
        f"`dispatch --json --yes` must exit 0 on an approved sensitive goal; "
        f"got {proc.returncode}\nstderr:\n{proc.stderr}"
    )
    payload = _one_json_object(proc.stdout, "dispatch --json --yes")
    assert payload["goal_id"] == goal_ids["sensitive"], (
        "the document must describe the goal that was approved; "
        f"asked for {goal_ids['sensitive']!r}, got {payload['goal_id']!r}"
    )


# ===========================================================================
# Behavior 3 -- exactly the 9 dispatched keys, and NO DRIFT from `run --json`
# ===========================================================================


def test_b03_document_carries_exactly_the_nine_dispatched_keys(json_dispatch) -> None:
    proc, _sd = json_dispatch
    payload = _one_json_object(proc.stdout, "dispatch --json")
    assert set(payload) == set(_DISPATCH_KEYS), (
        "the dispatched document's key set must be exactly the 9 published keys; "
        f"missing {sorted(_DISPATCH_KEYS - set(payload))}, "
        f"unexpected {sorted(set(payload) - _DISPATCH_KEYS)}"
    )


def test_b03_key_set_equals_run_json_dispatched_sub_object(json_dispatch, run_json) -> None:
    """Measured non-drift: BOTH key sets come from RUNNING the two verbs in this
    same build and are compared to each other, never to a stored list. That is
    what makes it a drift guard -- it would still fail if the document had been
    copied into a second dict literal rather than built once and shared.
    """
    dproc, _sd = json_dispatch
    assert run_json.returncode == 0, (
        f"`run --json` must exit 0 to supply the comparison; got {run_json.returncode}"
        f"\nstderr:\n{run_json.stderr}"
    )
    run_payload = _one_json_object(run_json.stdout, "run --json")
    nested = run_payload.get("dispatched")
    assert isinstance(nested, dict), (
        "`run --json` must have auto-dispatched so its `dispatched` sub-object is "
        f"available for comparison; got {nested!r}"
    )
    dispatch_payload = _one_json_object(dproc.stdout, "dispatch --json")
    assert set(dispatch_payload) == set(nested), (
        "`dispatch --json` must publish the SAME document `run --json` nests under "
        f"`dispatched`; dispatch-only keys {sorted(set(dispatch_payload) - set(nested))}, "
        f"run-only keys {sorted(set(nested) - set(dispatch_payload))}"
    )


# ===========================================================================
# Behavior 4 -- the values agree with what the run wrote to disk
# ===========================================================================


def test_b04_values_agree_with_the_checkpoint_the_run_wrote(json_dispatch, goal_ids) -> None:
    proc, _sd = json_dispatch
    payload = _one_json_object(proc.stdout, "dispatch --json")

    assert payload["goal_id"] == goal_ids["auto"], (
        f"`goal_id` must echo the --goal-id passed ({goal_ids['auto']!r}); "
        f"got {payload['goal_id']!r}"
    )

    run_dir = Path(payload["run_dir"])
    assert run_dir.is_dir(), f"`run_dir` must be an existing directory; got {run_dir!s}"

    checkpoint = run_dir / "checkpoint.json"
    assert checkpoint.is_file(), (
        f"the run must have persisted {checkpoint.name}; run dir holds "
        f"{sorted(p.name for p in run_dir.iterdir())}"
    )
    saved = json.loads(checkpoint.read_text())
    assert payload["run_id"] == saved["run_id"], (
        f"`run_id` must equal the checkpoint's ({saved['run_id']!r}); "
        f"got {payload['run_id']!r}"
    )
    assert payload["status"] == saved["status"], (
        f"`status` must equal the checkpoint's ({saved['status']!r}); "
        f"got {payload['status']!r}"
    )

    artifacts = payload["artifacts"]
    assert isinstance(artifacts, list), f"`artifacts` must be a list; got {type(artifacts)}"
    for entry in artifacts:
        assert Path(entry).is_file(), f"every artifact path must exist and be a file; {entry!r} does not"


def test_b04_counters_are_non_negative_integers(json_dispatch) -> None:
    proc, _sd = json_dispatch
    payload = _one_json_object(proc.stdout, "dispatch --json")
    for key in ("iterations_used", "llm_calls_used", "retries", "parse_errors"):
        value = payload[key]
        assert isinstance(value, int) and not isinstance(value, bool), (
            f"`{key}` must be an integer for a machine reader; got {value!r}"
        )
        assert value >= 0, f"`{key}` must not be negative; got {value!r}"


# ===========================================================================
# Behavior 5 -- the human summary still prints IN FULL, but on STDERR
# ===========================================================================


def test_b05_human_summary_moves_to_stderr_and_never_reaches_stdout(json_dispatch) -> None:
    proc, _sd = json_dispatch
    assert _SUMMARY_MARKER in proc.stderr, (
        f"under --json the human summary must still print; stderr must carry "
        f"{_SUMMARY_MARKER!r}, got:\n{proc.stderr}"
    )
    assert _SUMMARY_MARKER not in proc.stdout, (
        f"{_SUMMARY_MARKER!r} must never reach stdout under --json; got:\n{proc.stdout}"
    )


def test_b05_stderr_carries_every_line_the_default_path_prints(
    json_dispatch, plain_dispatch
) -> None:
    """"In full" is measured, not asserted: every normalized line the default
    path writes to stdout must appear in the --json run's stderr."""
    jproc, jsd = json_dispatch
    pproc, psd = plain_dispatch
    expected = _normalize(pproc.stdout, psd, jsd)
    assert expected, f"the default dispatch must print a human summary; got:\n{pproc.stdout!r}"
    actual = _normalize(jproc.stderr, psd, jsd)
    missing = [line for line in expected if line not in actual]
    assert not missing, (
        "under --json every line the default path prints to stdout must appear on "
        f"stderr; missing {missing}\n--json stderr was:\n{jproc.stderr}"
    )


# ===========================================================================
# Behavior 6 -- without --json, dispatch is unchanged
# ===========================================================================


def test_b06_default_path_prints_the_human_summary_on_stdout(plain_dispatch) -> None:
    proc, _sd = plain_dispatch
    assert proc.returncode == 0, (
        f"the default `dispatch` must still exit 0; got {proc.returncode}\nstderr:\n{proc.stderr}"
    )
    assert _SUMMARY_MARKER in proc.stdout, (
        f"without --json, {_SUMMARY_MARKER!r} must still print on stdout; got:\n{proc.stdout}"
    )


def test_b06_default_path_stdout_is_not_json(plain_dispatch) -> None:
    proc, _sd = plain_dispatch
    with pytest.raises(json.JSONDecodeError):
        json.loads(proc.stdout)


# ===========================================================================
# Behavior 7 -- refusals keep their exit codes AND the empty-stdout rule
# ===========================================================================


@pytest.mark.parametrize(
    "role, expected_code, markers",
    [
        ("blocked", 3, (_BLOCKED_MARKER, "refusing to dispatch")),
        ("sensitive", 4, (_APPROVAL_MARKER, _YES_HINT)),
        ("below_threshold", 4, (_APPROVAL_MARKER, _YES_HINT)),
    ],
)
def test_b07_refusals_are_unchanged_under_json(
    tmp_path: Path, slate: Path, goal_ids, role: str, expected_code: int, markers
) -> None:
    """The two exit-4 reasons are exercised SEPARATELY: one exit code can have
    two causes (sensitive category vs below the auto-dispatch threshold) and
    only one of them may be wired, so testing a single goal would report half
    the contract as whole.
    """
    sd = tmp_path / "state"
    proc = _run(*_dispatch_argv(slate, goal_ids[role], sd, "--json"), cwd=tmp_path)
    assert proc.returncode == expected_code, (
        f"the {role} goal must still exit {expected_code} under --json; "
        f"got {proc.returncode}\nstderr:\n{proc.stderr}"
    )
    assert proc.stdout == "", (
        f"stdout must be exactly empty when the gate refuses; got {proc.stdout!r}"
    )
    for marker in markers:
        assert marker in proc.stderr, (
            f"the {role} refusal must still print {marker!r} on stderr; got:\n{proc.stderr}"
        )


@pytest.mark.parametrize("role", ["blocked", "sensitive", "below_threshold"])
def test_b07_refusal_stderr_is_byte_identical_with_and_without_json(
    tmp_path: Path, slate: Path, goal_ids, role: str
) -> None:
    """"Today's message still prints" is verified by comparing two live runs to
    each other, not by matching a transcribed substring."""
    plain_sd = tmp_path / "plain"
    json_sd = tmp_path / "json"
    plain = _run(*_dispatch_argv(slate, goal_ids[role], plain_sd), cwd=tmp_path)
    jsonp = _run(*_dispatch_argv(slate, goal_ids[role], json_sd, "--json"), cwd=tmp_path)
    assert plain.returncode == jsonp.returncode, (
        f"--json must not change the {role} exit code; "
        f"plain {plain.returncode} vs --json {jsonp.returncode}"
    )
    assert _normalize(jsonp.stderr, json_sd, plain_sd) == _normalize(
        plain.stderr, json_sd, plain_sd
    ), (
        f"the {role} refusal message must be unchanged by --json;\n"
        f"plain stderr:\n{plain.stderr}\n--json stderr:\n{jsonp.stderr}"
    )
    assert plain.stdout == "" and jsonp.stdout == "", (
        "a refusal prints nothing on stdout on either path; "
        f"plain {plain.stdout!r}, --json {jsonp.stdout!r}"
    )


# ===========================================================================
# Behavior 8 -- INVERTED in factory iter 173: `resume` now DECLARES --json;
# the flag alone is still a usage error
# ===========================================================================


def test_b08_resume_declares_json(tmp_path: Path) -> None:
    """INVERTED when `resume --json` shipped (roadmap #196, factory iter 173).

    This assertion used to require the OPPOSITE, on the stated ground that
    `resume` "has no slate and no gate, so its document is a different one".
    That premise was measured and refuted: `_cmd_resume` terminates holding the
    exact `(RunState, run_dir, ToolRegistry)` triple `_dispatched_json_payload`
    consumes, so `resume`'s document is not a different shape at all --- it is the
    SAME nine keys `dispatch --json` publishes, from a third call site of that one
    builder. The fence was a real design question, not a schedule; it is answered
    now, so the guard is kept and pointed the other way rather than deleted.
    """
    proc = _run("resume", "--help", cwd=tmp_path)
    assert proc.returncode == 0, (
        f"`resume --help` must exit 0; got {proc.returncode}\nstderr:\n{proc.stderr}"
    )
    flags = _declared_flags(proc.stdout)
    assert "--json" in flags, (
        "`resume` is the verb a supervising script re-invokes after a failure, so its "
        f"result must be machine-readable: it must declare --json. It declares {sorted(flags)}"
    )


def test_b08_resume_json_is_a_usage_error_with_empty_stdout(tmp_path: Path) -> None:
    proc = _run("resume", "--json", cwd=tmp_path)
    assert proc.returncode == 2, (
        f"`resume --json` must be an argparse usage error (exit 2); got {proc.returncode}"
        f"\nstderr:\n{proc.stderr}"
    )
    assert proc.stdout == "", f"a usage error must print nothing on stdout; got {proc.stdout!r}"
