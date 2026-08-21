"""Black-box behavior tests for state-dir iteration 198 (ships as ``factory iter 200``).

Feature under test: ``pla dispatch --dry-run`` -- a preview of dispatching ONE
approved goal that returns 0 BEFORE any LLM client, run directory or loop
iteration exists. It reports the gate decision and reason, the resolved
workspace root, the state dir / run dir the run would be written under, and a
paste-ready real command.

MODULE NAME -- DERIVED FROM THE REPO, NEVER FROM A COUNTER. Three repo-facing
counters disagree this iteration: the state dir is ``iter-198``, the newest
commit is ``factory iter 199`` (so this ships as 200), and the highest tracked
``tests/test_iterNN_behavior.py`` is already 202. Naming a module after either
iteration counter would SILENTLY OVERWRITE a shipped green oracle (the iter-172
/ iter-186 destroyed-oracle failures). So the name is derived: highest tracked
module 202 + 1 = 203, and ``git cat-file -e HEAD:tests/test_iter203_behavior.py``
was proved to FAIL before a byte was written.

ISOLATION CONTRACT (honored): every assertion is written against this
iteration's spec ("Expected Behaviors" in ``pm.md``), the published ``README.md``
CLI reference, the repo's own ``tests/`` conventions, and the product's
OBSERVABLE output obtained by RUNNING it. **No file under ``src/`` was read, no
engineer's or reviewer's note was consulted, and no ``git diff`` was inspected.**

WHY REAL SUBPROCESSES. Most behaviors here are claims about the SEPARATION of
two streams paired with an exit code ("stdout is EMPTY on every refusal", exit
3 / 4 / 2 / 1 / 0). An in-process ``capsys`` run cannot falsify those honestly,
so this module spends real ``pla`` console-script invocations (the
iter-114 / iter-152 / iter-158 / iter-202 convention). Cost is bounded: the slate
fixture and the gate-decision probe are module-scoped, and only ONE test runs a
real dispatch (behavior 9's "unchanged" clause, ~0.3s with the bundled scripted
provider).

NO DECISION IS TRANSCRIBED FROM THE AUTONOMY CONTRACT. Each fixture goal is
meant to land on a particular gate decision, and that decision plus its reason
are CONFIRMED per test by the product's own read-only ``pla explain`` rather
than assumed from ``policy`` prose -- so a contract change reds these tests
loudly instead of making them vacuous.

Offline and deterministic: no network, no API key. Every preview path needs no
provider at all; the single real dispatch uses the bundled offline scripted
provider. Everything is written under a per-test ``tmp_path`` -- nothing is
written inside the product repo, and no run is rooted at the in-repo fixture
workspace (the iter-142 shared-mutable-tree hazard).
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from proactive_loop.cli import build_parser
from proactive_loop.models import CandidateGoal, GoalSlate

REPO = Path(__file__).resolve().parents[1]
README = REPO / "README.md"
SCRIPT = REPO / "examples" / "scripted_responses.json"

_MARKER = "PORTFOLIO INTRO"
_PREVIEW_MARKER = "[dry-run]"
_PASTE_PREFIX = "pla dispatch"

# The nine always-present keys of the published `dispatch --json` document
# (behavior 9's "unchanged" clause).
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


# ---------------------------------------------------------------------------
# Helpers -- drive the public CLI, read back exit code / stdout / stderr / disk
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
        timeout=180,
    )


def _goal(
    title: str,
    *,
    category: str = "learning",
    appropriate_now: bool = True,
    impact: float = 5.0,
    urgency: float = 5.0,
) -> CandidateGoal:
    """One goal built through the public model."""
    return CandidateGoal(
        title=title,
        rationale="black-box dispatch --dry-run probe",
        category=category,
        impact=impact,
        urgency=urgency,
        confidence=0.9,
        effort_weight=1.0,
        appropriate_now=appropriate_now,
        sources=["foo.py"],
        suggested_first_steps=["do a thing"],
    )


@dataclass(frozen=True)
class _Env:
    """A slate on disk plus the goal ids of its four gate outcomes."""

    root: Path
    workspace: Path
    slate_path: Path
    auto: str
    blocked: str
    low: str
    sensitive: str


@pytest.fixture(scope="module")
def env(tmp_path_factory: pytest.TempPathFactory) -> _Env:
    """One hand-written slate carrying every gate outcome, built once.

    Read-only for every test: each test passes its OWN ``--state-dir`` under its
    own ``tmp_path``, so nothing here is mutated across tests.
    """
    root = tmp_path_factory.mktemp("iter203")
    workspace = root / "ws"
    workspace.mkdir()
    (workspace / "foo.py").write_text("print('hi')\n", encoding="utf-8")

    auto = _goal("Draft the linear-foot rate note")
    blocked = _goal("Rewrite history at 3am", appropriate_now=False)
    low = _goal("Skim one tangential blog post", impact=1.0, urgency=1.0)
    sensitive = _goal("Reconcile the escrow statement", category="finance_legal")

    slate = GoalSlate(
        workspace_root=str(workspace),
        goals=[auto, blocked, low, sensitive],
    )
    slate_path = root / "slate.json"
    slate_path.write_text(slate.model_dump_json(indent=2), encoding="utf-8")
    return _Env(
        root=root,
        workspace=workspace,
        slate_path=slate_path,
        auto=auto.id,
        blocked=blocked.id,
        low=low.id,
        sensitive=sensitive.id,
    )


def _dispatch(
    env: _Env, *extra: str, goal_id: str | None = None, state_dir: Path
) -> subprocess.CompletedProcess[str]:
    return _run(
        "dispatch",
        "--slate",
        str(env.slate_path),
        "--goal-id",
        goal_id or env.auto,
        "--state-dir",
        str(state_dir),
        *extra,
        cwd=env.root,
    )


_DECISION_RE = re.compile(r"decision\s*:\s*([A-Za-z_]+)\s*\(([^)]*)\)")


def _gate(env: _Env, goal_id: str) -> tuple[str, str]:
    """The gate's OWN decision + reason for one goal, via read-only ``explain``.

    Keeps the fixtures honest: no decision word or reason string in this module
    is transcribed from the autonomy contract, they are read back from the
    product.
    """
    proc = _run(
        "explain",
        "--slate",
        str(env.slate_path),
        "--goal-id",
        goal_id,
        cwd=env.root,
    )
    assert proc.returncode == 0, (
        f"`explain --goal-id` must succeed for a goal in the slate; got "
        f"{proc.returncode}\nstderr:\n{proc.stderr}"
    )
    match = _DECISION_RE.search(proc.stdout)
    assert match is not None, (
        "`explain` must report `decision : <word>  (<reason>)` so this module can "
        f"confirm its fixtures; got:\n{proc.stdout}"
    )
    return match.group(1).upper(), match.group(2).strip()


def _paste_line(stdout: str) -> str:
    """The single paste-ready `pla dispatch ...` command line in a preview."""
    lines = [ln.strip() for ln in stdout.splitlines() if ln.strip().startswith(_PASTE_PREFIX)]
    assert len(lines) == 1, (
        "a preview must offer EXACTLY ONE paste-ready `pla dispatch ...` command; "
        f"got {len(lines)}:\n{stdout}"
    )
    return lines[0]


def _tree(root: Path) -> set[str]:
    """Every path under ``root`` as POSIX-relative strings (empty if absent)."""
    if not root.exists():
        return set()
    return {p.relative_to(root).as_posix() for p in root.rglob("*")}


def _readme_split() -> tuple[str, str]:
    """(above, below) the human-owned PORTFOLIO INTRO marker."""
    text = README.read_text(encoding="utf-8")
    idx = text.find(_MARKER)
    assert idx != -1, f"README must carry the human-owned {_MARKER!r} marker"
    return text[:idx], text[idx:]


# ===========================================================================
# Behavior 1 -- `dispatch --help` lists --dry-run and states what it does NOT do
# ===========================================================================


def test_b01_help_documents_dry_run_as_non_executing(env: _Env) -> None:
    proc = _run("dispatch", "--help", cwd=env.root)
    assert proc.returncode == 0, f"`dispatch --help` must exit 0; got {proc.returncode}"
    assert "--dry-run" in proc.stdout, (
        f"`dispatch --help` must list --dry-run; got:\n{proc.stdout}"
    )
    # argparse hard-wraps help text, so collapse whitespace before matching.
    flat = " ".join(proc.stdout.split()).lower()
    assert "not executed" in flat, (
        "the --dry-run help must state that the goal is NOT executed; "
        f"got:\n{proc.stdout}"
    )
    assert re.search(r"no run director", flat), (
        "the --dry-run help must state that no run directory is created; "
        f"got:\n{proc.stdout}"
    )


# ===========================================================================
# Behavior 2 -- --dry-run defaults OFF, so no existing invocation changes
# ===========================================================================


def test_b02_dry_run_defaults_off() -> None:
    args = build_parser().parse_args(["dispatch", "--slate", "s.json", "--goal-id", "g1"])
    assert args.dry_run is False, (
        f"`dispatch` without --dry-run must yield dry_run is False; got {args.dry_run!r}"
    )
    assert args.json is False, (
        "sanity: --json also defaults off, so behavior 9's pairing is opt-in on both sides; "
        f"got {args.json!r}"
    )


# ===========================================================================
# Behavior 3 -- an AUTO_DISPATCH goal previews on stdout and exits 0
# ===========================================================================


def test_b03_auto_dispatch_preview_reports_every_published_field(
    env: _Env, tmp_path: Path
) -> None:
    decision, _reason = _gate(env, env.auto)
    assert decision == "AUTO_DISPATCH", (
        f"fixture precondition: this goal must gate AUTO_DISPATCH; got {decision}"
    )

    state_dir = tmp_path / "state"
    proc = _dispatch(env, "--dry-run", state_dir=state_dir)
    assert proc.returncode == 0, (
        f"`dispatch --dry-run` on an auto-dispatchable goal must exit 0; got "
        f"{proc.returncode}\nstderr:\n{proc.stderr}"
    )
    out = proc.stdout
    assert _PREVIEW_MARKER in out, (
        f"the preview must mark itself as a dry run; got:\n{out}"
    )
    for label, needle in (
        ("goal id", env.auto),
        ("goal title", "Draft the linear-foot rate note"),
        ("decision word", "AUTO_DISPATCH"),
        ("resolved workspace root", str(env.workspace)),
        ("state dir the run would be written under", str(state_dir)),
    ):
        assert needle in out, f"the preview must report the {label} ({needle!r}); got:\n{out}"

    paste = _paste_line(out)
    assert f"--slate {env.slate_path}" in paste, (
        f"the paste-ready command must carry this slate; got {paste!r}"
    )
    assert f"--goal-id {env.auto}" in paste, (
        f"the paste-ready command must carry this goal id; got {paste!r}"
    )
    assert "--dry-run" not in paste, (
        f"the paste-ready command is the REAL run, so it must not re-preview; got {paste!r}"
    )


# ===========================================================================
# Behavior 4 -- the preview writes nothing: no run-* dir, tree unchanged
# ===========================================================================


def test_b04_preview_creates_no_run_dir_and_leaves_the_tree_unchanged(
    env: _Env, tmp_path: Path
) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "sentinel.txt").write_text("pre-existing\n", encoding="utf-8")
    (state_dir / "nested").mkdir()
    before = _tree(state_dir)
    assert before, "precondition: the state dir starts non-empty"

    proc = _dispatch(env, "--dry-run", state_dir=state_dir)
    assert proc.returncode == 0, f"precondition: the preview succeeded; got {proc.returncode}"

    after = _tree(state_dir)
    assert after == before, (
        "a preview must not touch the state dir; "
        f"added={sorted(after - before)} removed={sorted(before - after)}"
    )
    assert not [p for p in after if p.startswith("run-")], (
        f"a preview must create no run-* directory; got {sorted(after)}"
    )


def test_b04b_preview_does_not_even_create_an_absent_state_dir(
    env: _Env, tmp_path: Path
) -> None:
    state_dir = tmp_path / "never_created"
    assert not state_dir.exists(), "precondition: the state dir does not exist yet"
    proc = _dispatch(env, "--dry-run", state_dir=state_dir)
    assert proc.returncode == 0, f"precondition: the preview succeeded; got {proc.returncode}"
    assert not state_dir.exists(), (
        f"a preview must not materialize the state dir; found {sorted(_tree(state_dir))}"
    )


# ===========================================================================
# Behavior 5 -- the preview returns BEFORE any LLM client is constructed
# ===========================================================================


def test_b05_preview_precedes_client_construction_two_sided(
    env: _Env, tmp_path: Path
) -> None:
    """Two-sided on the SAME argv: an unknown provider is fatal without
    --dry-run and irrelevant with it. A one-sided pass would be satisfied by a
    preview that builds a client and discards it."""
    bad = ("--provider", "no-such-provider")

    without = _dispatch(env, *bad, state_dir=tmp_path / "s1")
    assert without.returncode == 1, (
        "known-bad side: without --dry-run an unknown provider must be an operational "
        f"fault (exit 1); got {without.returncode}\nstderr:\n{without.stderr}"
    )
    assert "error: unknown provider" in without.stderr, (
        f"the fault must be reported as one `error: unknown provider` line; got:\n{without.stderr}"
    )
    assert without.stdout == "", (
        f"a failing dispatch writes nothing to stdout; got {without.stdout!r}"
    )

    with_dry = _dispatch(env, *bad, "--dry-run", state_dir=tmp_path / "s2")
    assert with_dry.returncode == 0, (
        "known-good side: --dry-run must return BEFORE the client exists, so an unknown "
        f"provider cannot matter; got {with_dry.returncode}\nstderr:\n{with_dry.stderr}"
    )
    assert _PREVIEW_MARKER in with_dry.stdout, (
        f"the preview must still be printed; got:\n{with_dry.stdout}"
    )
    assert "unknown provider" not in with_dry.stderr, (
        f"--dry-run must not report a provider fault at all; got:\n{with_dry.stderr}"
    )


# ===========================================================================
# Behavior 6 -- BLOCKED outranks the preview
# ===========================================================================


def test_b06_blocked_outranks_the_preview(env: _Env, tmp_path: Path) -> None:
    decision, _reason = _gate(env, env.blocked)
    assert decision == "BLOCKED", (
        f"fixture precondition: this goal must gate BLOCKED; got {decision}"
    )

    proc = _dispatch(env, "--dry-run", goal_id=env.blocked, state_dir=tmp_path / "state")
    assert proc.returncode == 3, (
        f"a BLOCKED goal must still exit 3 under --dry-run; got {proc.returncode}\n"
        f"stderr:\n{proc.stderr}"
    )
    assert proc.stdout == "", (
        f"a refusal keeps stdout EMPTY, preview or not; got {proc.stdout!r}"
    )
    assert "Rewrite history at 3am" in proc.stderr, (
        f"the refusal must name the goal on stderr; got:\n{proc.stderr}"
    )


# ===========================================================================
# Behavior 7 -- NEEDS_APPROVAL outranks the preview; --yes unlocks it
# ===========================================================================


def test_b07_needs_approval_without_yes_is_still_exit_4(env: _Env, tmp_path: Path) -> None:
    decision, _reason = _gate(env, env.low)
    assert decision == "NEEDS_APPROVAL", (
        f"fixture precondition: this goal must gate NEEDS_APPROVAL; got {decision}"
    )

    proc = _dispatch(env, "--dry-run", goal_id=env.low, state_dir=tmp_path / "state")
    assert proc.returncode == 4, (
        f"a goal needing approval must still exit 4 under --dry-run; got {proc.returncode}\n"
        f"stderr:\n{proc.stderr}"
    )
    assert proc.stdout == "", (
        f"a refusal keeps stdout EMPTY, preview or not; got {proc.stdout!r}"
    )
    assert "Skim one tangential blog post" in proc.stderr, (
        f"the refusal must name the goal on stderr; got:\n{proc.stderr}"
    )


@pytest.mark.parametrize("which", ["low", "sensitive"])
def test_b07b_yes_plus_dry_run_previews_with_decision_reason_and_yes(
    env: _Env, tmp_path: Path, which: str
) -> None:
    """Both NEEDS_APPROVAL routes are covered: below-threshold and sensitive
    category. The reason is not transcribed here -- it is read back from
    ``explain`` and must appear verbatim in the preview."""
    goal_id = env.low if which == "low" else env.sensitive
    decision, reason = _gate(env, goal_id)
    assert decision == "NEEDS_APPROVAL", (
        f"fixture precondition ({which}): must gate NEEDS_APPROVAL; got {decision}"
    )
    assert reason, "precondition: the gate publishes a reason for this decision"

    proc = _dispatch(
        env, "--yes", "--dry-run", goal_id=goal_id, state_dir=tmp_path / "state"
    )
    assert proc.returncode == 0, (
        f"`--yes --dry-run` must preview an approved goal; got {proc.returncode}\n"
        f"stderr:\n{proc.stderr}"
    )
    assert "NEEDS_APPROVAL" in proc.stdout, (
        f"the preview must report the gate decision it previews; got:\n{proc.stdout}"
    )
    assert reason in proc.stdout, (
        f"the preview must carry the gate's own reason {reason!r}; got:\n{proc.stdout}"
    )
    paste = _paste_line(proc.stdout)
    assert "--yes" in paste, (
        "the paste-ready command must keep the approval this goal requires; "
        f"got {paste!r}"
    )
    assert "--dry-run" not in paste, f"the paste-ready command is the real run; got {paste!r}"


# ===========================================================================
# Behavior 8 -- every earlier exit-2 fault outranks the preview
# ===========================================================================


def test_b08_earlier_exit_2_faults_outrank_the_preview(env: _Env, tmp_path: Path) -> None:
    missing = tmp_path / "no_such_slate.json"
    assert not missing.exists(), "precondition: the slate path is not a file"
    proc = _run(
        "dispatch",
        "--slate",
        str(missing),
        "--goal-id",
        env.auto,
        "--state-dir",
        str(tmp_path / "s1"),
        "--dry-run",
        cwd=env.root,
    )
    assert proc.returncode == 2, (
        f"a --slate path that is not a file must exit 2 under --dry-run; got {proc.returncode}\n"
        f"stderr:\n{proc.stderr}"
    )
    assert proc.stdout == "", f"a fault keeps stdout EMPTY; got {proc.stdout!r}"

    unknown = _dispatch(
        env, "--dry-run", goal_id="zzzz-not-in-this-slate", state_dir=tmp_path / "s2"
    )
    assert unknown.returncode == 2, (
        f"a --goal-id absent from the slate must exit 2 under --dry-run; got "
        f"{unknown.returncode}\nstderr:\n{unknown.stderr}"
    )
    assert unknown.stdout == "", f"a fault keeps stdout EMPTY; got {unknown.stdout!r}"


# ===========================================================================
# Behavior 9 -- --dry-run with --json is a usage error; --json alone unchanged
# ===========================================================================


def test_b09_dry_run_with_json_is_a_usage_error_naming_both_flags(
    env: _Env, tmp_path: Path
) -> None:
    proc = _dispatch(env, "--dry-run", "--json", state_dir=tmp_path / "state")
    assert proc.returncode == 2, (
        f"--dry-run with --json must be a usage error (exit 2); got {proc.returncode}\n"
        f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
    assert proc.stdout == "", (
        f"a usage error writes nothing to stdout, so no half-document leaks; got {proc.stdout!r}"
    )
    for flag in ("--dry-run", "--json"):
        assert flag in proc.stderr, (
            f"the usage error must name {flag} so the operator can see the conflict; "
            f"got:\n{proc.stderr}"
        )


def test_b09b_dispatch_json_without_dry_run_still_publishes_its_nine_keys(
    env: _Env, tmp_path: Path
) -> None:
    """The refused pairing must not have disturbed the shipped `--json`
    document. One real dispatch, offline scripted provider."""
    assert SCRIPT.is_file(), f"precondition: the bundled scripted responses exist at {SCRIPT}"
    proc = _dispatch(
        env,
        "--json",
        "--provider",
        "scripted",
        "--scripted-responses",
        str(SCRIPT),
        state_dir=tmp_path / "state",
    )
    assert proc.returncode == 0, (
        f"`dispatch --json` must still succeed; got {proc.returncode}\nstderr:\n{proc.stderr}"
    )
    payload = json.loads(proc.stdout)
    assert isinstance(payload, dict), f"stdout must be ONE JSON object; got {type(payload)}"
    assert set(payload) == set(_DISPATCH_KEYS), (
        "`dispatch --json` must still publish exactly its nine guaranteed keys; "
        f"missing={sorted(_DISPATCH_KEYS - set(payload))} "
        f"extra={sorted(set(payload) - _DISPATCH_KEYS)}"
    )
    assert payload["goal_id"] == env.auto, (
        f"the document must describe the dispatched goal; got {payload['goal_id']!r}"
    )
    assert _PREVIEW_MARKER not in proc.stdout, (
        "a real dispatch must not emit preview text; got:\n" + proc.stdout
    )


# ===========================================================================
# Behavior 10 -- --dry-run did not leak onto any other verb
# ===========================================================================


def test_b10_only_dispatch_and_run_accept_dry_run(env: _Env, tmp_path: Path) -> None:
    parser = build_parser()
    subs = [
        a
        for a in parser._subparsers._group_actions  # noqa: SLF001 -- repo convention
        if isinstance(a, argparse._SubParsersAction)
    ]
    assert len(subs) == 1, f"expected exactly one subparser action, got {len(subs)}"
    owners = {
        verb
        for verb, sub in subs[0].choices.items()
        if any("--dry-run" in (a.option_strings or []) for a in sub._actions)  # noqa: SLF001
    }
    assert owners == {"dispatch", "run"}, (
        "--dry-run must belong to exactly the two gated-execution verbs; "
        f"got {sorted(owners)}"
    )

    # Known-bad side: a verb that does NOT own the flag still rejects it, and the
    # workspace is supplied so exit 2 is attributable to --dry-run alone.
    rejected = _run(
        "scan", "--workspace", str(env.workspace), "--dry-run", cwd=tmp_path
    )
    assert rejected.returncode == 2, (
        f"`scan --dry-run` must still be a usage error; got {rejected.returncode}\n"
        f"stderr:\n{rejected.stderr}"
    )
    assert "--dry-run" in rejected.stderr, (
        f"argparse must name the unrecognized flag; got:\n{rejected.stderr}"
    )
    assert rejected.stdout == "", f"a usage error writes nothing to stdout; got {rejected.stdout!r}"


# ===========================================================================
# Behavior 11 -- the README documents it BELOW the human-owned marker
# ===========================================================================


def test_b11_readme_documents_dry_run_only_below_the_marker() -> None:
    above, below = _readme_split()
    # Select on the row's FIRST CELL, not on a substring: other rows in the CLI
    # reference legitimately mention `dispatch` in their prose.
    dispatch_rows = [
        ln
        for ln in below.splitlines()
        if ln.startswith("|") and ln.split("|")[1].strip() == "`dispatch`"
    ]
    assert len(dispatch_rows) == 1, (
        f"the CLI reference must carry exactly one `dispatch` row; got {len(dispatch_rows)}"
    )
    row = dispatch_rows[0]
    assert "--dry-run" in row, f"the `dispatch` row must document --dry-run; got:\n{row}"
    for token in ("--slate", "--goal-id", "required"):
        assert token in row, (
            f"the `dispatch` row must still state that {token} applies; got:\n{row}"
        )
    assert "--dry-run" not in above, (
        "the human-owned portfolio intro is not the place to document a flag; "
        "--dry-run must appear only BELOW the marker"
    )
