"""Command-line entry point (L2 orchestration surface).

WHY a thin CLI over the library layers: every capability the CLI exposes already
lives in a tested module (collectors, scout, loop). This file only *wires* them
into six verbs a person actually runs -- scan, dispatch, run, resume, the
read-only runs lister, and the read-only explain auditor -- and owns the two
things a library must not: argument
parsing and where run artifacts land on disk. Keeping that policy here (never
inside the loop) means the autonomy contract has exactly one enforcement point
per verb.

Layout of a dispatched run under ``state_dir``::

    <state_dir>/
      slate.json                 # last scan's ranked slate (scan / run)
      run-<goal_id>/
        meta.json                # workspace_root + artifacts_dir, for `resume`
        checkpoint.json          # atomic RunState snapshot after every step
        artifacts/               # everything the loop's write_file tool produced
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .config import Settings
from .collectors import all_collectors
from .llm import LLMError
from .llm.providers import create_client
from .loop import Checkpoint, GoalLoop, ToolRegistry
from .models import (
    AutonomyDecision,
    CandidateGoal,
    DispatchDecision,
    GoalSlate,
    RunState,
    RunStatus,
    WorkspaceSnapshot,
    ensure_dir,
)
from .scout import GoalSynthesizer, gate, gate_slate

_META_NAME = "meta.json"
_CHECKPOINT_NAME = "checkpoint.json"
_ARTIFACTS_NAME = "artifacts"
_SLATE_NAME = "slate.json"
# Verbatim status marker shown by the runs lister for a run dir with no loadable
# checkpoint; the black-box behavior contract depends on this exact text, so it
# lives as a named constant rather than an inline literal.
_NO_CHECKPOINT = "(no checkpoint)"


# ---------------------------------------------------------------------------
# argument parsing
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Assemble the ``pla`` parser with six subcommands and shared globals.

    The provider/scripting/state-dir flags are attached via a parent parser so
    they are accepted AFTER the subcommand (e.g. ``pla run --provider ...``),
    which is how the bundled demo invokes the tool.
    """
    parser = argparse.ArgumentParser(
        prog="pla",
        description=(
            "Proactive loop agent: scan a workspace, synthesize a ranked goal "
            "slate, gate it for autonomy, and dispatch approved goals into a "
            "resilient plan->act->check loop."
        ),
    )
    # Top-level --version short-circuits parsing (argparse's built-in version
    # action prints then raises SystemExit(0)) so it works with NO subcommand,
    # ahead of the required-subparser check below. It lives on the top-level
    # parser -- NOT on globals_ -- so it stays out of every subcommand's help.
    # The version string is sourced once from proactive_loop.__version__ (the
    # single source of truth), never a second hardcoded literal that could drift.
    parser.add_argument("--version", action="version", version=f"pla {__version__}")

    globals_ = argparse.ArgumentParser(add_help=False)
    globals_.add_argument(
        "--provider",
        default=None,
        help="LLM provider: scripted (default, offline) | anthropic | openai | bedrock",
    )
    globals_.add_argument(
        "--scripted-responses",
        default=None,
        help="Path to a JSON script driving the offline scripted provider.",
    )
    globals_.add_argument(
        "--state-dir",
        default=None,
        help="Directory for slates, checkpoints, and run artifacts (default .pla_runs).",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    p_scan = sub.add_parser(
        "scan", parents=[globals_], help="Scan a workspace and print a ranked goal slate."
    )
    p_scan.add_argument("--workspace", required=True, help="Workspace root to scan.")
    p_scan.add_argument(
        "--out", default=None, help="Where to write the slate JSON (default <state_dir>/slate.json)."
    )
    p_scan.set_defaults(func=_cmd_scan)

    p_dispatch = sub.add_parser(
        "dispatch", parents=[globals_], help="Dispatch one goal from a saved slate."
    )
    p_dispatch.add_argument("--slate", required=True, help="Path to a slate JSON from `scan`.")
    p_dispatch.add_argument("--goal-id", required=True, help="Id of the goal to dispatch.")
    p_dispatch.add_argument(
        "--yes",
        action="store_true",
        help="Confirm dispatch of a goal that needs approval (never overrides BLOCKED).",
    )
    p_dispatch.set_defaults(func=_cmd_dispatch)

    p_run = sub.add_parser(
        "run",
        parents=[globals_],
        help="Scan then auto-dispatch only the single top AUTO_DISPATCH goal.",
    )
    p_run.add_argument("--workspace", required=True, help="Workspace root to scan.")
    p_run.set_defaults(func=_cmd_run)

    p_resume = sub.add_parser(
        "resume", parents=[globals_], help="Resume a checkpointed run from its run dir."
    )
    p_resume.add_argument("--run-dir", required=True, help="A run-<id> directory to resume.")
    p_resume.set_defaults(func=_cmd_resume)

    # `runs` inherits the same globals (parents=[globals_]) so it accepts
    # --state-dir; --provider/--scripted-responses are accepted but inert (the
    # handler builds no LLMClient). This is what makes it a zero-config,
    # LLM-free lister that also surfaces the --run-dir value `resume` needs.
    p_runs = sub.add_parser(
        "runs",
        parents=[globals_],
        help="List past dispatched runs under the state dir (read-only, LLM-free).",
    )
    p_runs.add_argument(
        "--json",
        action="store_true",
        help="Emit the run list as a JSON array instead of the human table.",
    )
    p_runs.set_defaults(func=_cmd_runs)

    # `explain` mirrors `dispatch`'s slate + goal-id inputs but runs nothing: it
    # inherits the globals (so `--provider`/`--scripted-responses` are accepted
    # but inert -- it builds no LLMClient) and prints one goal's full decision
    # audit. Making --slate and --goal-id required (one goal per invocation) keeps
    # the verb unambiguous -- there is no implicit "explain the top goal" default.
    p_explain = sub.add_parser(
        "explain",
        parents=[globals_],
        help="Explain one goal's score math, gate decision, and provenance (read-only, LLM-free).",
    )
    p_explain.add_argument("--slate", required=True, help="Path to a slate JSON from `scan`.")
    p_explain.add_argument("--goal-id", required=True, help="Id of the goal to explain.")
    p_explain.set_defaults(func=_cmd_explain)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Parse *argv* and dispatch to the selected subcommand handler.

    Exit-code contract (a caller -- or the ``pla`` console script -- can tell a
    deliberate refusal apart from a fault):

    * ``0`` -- success.
    * ``1`` -- operational fault: a foreseeable operator/environment error
      (bad ``--provider``, missing/malformed input file, or a model-boundary
      failure once the retry budget is spent). Reported as one ``error: ...``
      line on stderr, never a raw traceback.
    * ``2`` -- not-found / no-checkpoint (a handler returned it explicitly).
    * ``3`` -- BLOCKED by the autonomy contract.
    * ``4`` -- needs-approval (re-run with ``--yes``).

    WHY the top-level guard is a *narrow* tuple and not bare ``except``:
    ``LLMError`` covers a persistent throttle/timeout that escapes the L0 retry
    budget; ``ValueError`` transitively covers ``json.JSONDecodeError`` and
    pydantic ``ValidationError`` (a hand-corrupted script or slate) plus an
    unknown provider; ``OSError`` covers a missing ``--scripted-responses``
    file (``FileNotFoundError``). A "resilient by design" layer must fail
    legibly on its loudest surface -- the CLI -- rather than dumping a
    stacktrace on foreseeable input. ``SystemExit`` and ``KeyboardInterrupt``
    subclass ``BaseException`` (not ``Exception``), so they are outside the
    tuple: argparse ``--help``/usage exits and Ctrl-C propagate unchanged. The
    handlers' own codes 2/3/4 are ``return``ed before any exception fires, so
    they pass through the boundary untouched.
    """
    parser = build_parser()
    args = parser.parse_args(argv)  # argparse SystemExit (help/usage) stays outside the guard
    try:
        return int(args.func(args))
    except (LLMError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


# ---------------------------------------------------------------------------
# settings + shared helpers
# ---------------------------------------------------------------------------


def _settings(args: argparse.Namespace, *, workspace_root: Path | None = None) -> Settings:
    """Fold CLI flags over PLA_* env defaults; flags win, unset flags fall back.

    ``Settings.from_env`` drops ``None`` overrides, so an unspecified flag never
    clobbers an environment value or the built-in default.
    """
    scripted = getattr(args, "scripted_responses", None)
    state_dir = getattr(args, "state_dir", None)
    return Settings.from_env(
        provider=getattr(args, "provider", None),
        scripted_responses_path=Path(scripted) if scripted else None,
        state_dir=Path(state_dir) if state_dir else None,
        workspace_root=workspace_root,
    )


def _collect(workspace: Path) -> WorkspaceSnapshot:
    """Run every collector over *workspace* into one snapshot.

    Collectors never raise (they degrade to ``[]``), so a missing dir or absent
    git simply yields fewer signals rather than aborting the scan.
    """
    signals = []
    for collector in all_collectors():
        signals.extend(collector.collect(workspace))
    return WorkspaceSnapshot(root=str(workspace), signals=signals)


def _write_slate(slate: GoalSlate, out: Path) -> None:
    """Persist the slate as pretty JSON, creating parent dirs as needed."""
    ensure_dir(out.parent)
    out.write_text(slate.model_dump_json(indent=2))


def _render_table(slate: GoalSlate, decisions: list[DispatchDecision]) -> str:
    """Render the ranked slate + gate outcome as a plain-text table.

    Rows are in ranked() order so the top actionable (AUTO_DISPATCH) goal is the
    first such row -- matching the order the gate decisions were computed in.
    """
    header = f"{'#':>2}  {'DECISION':<14} {'SCORE':>7}  {'CATEGORY':<13} TITLE"
    lines = [header, "-" * max(len(header), 60)]
    for rank, (goal, decision) in enumerate(zip(slate.ranked(), decisions), start=1):
        lines.append(
            f"{rank:>2}  {decision.decision.value:<14} {goal.score:>7.2f}  "
            f"{goal.category.value:<13} {goal.title}"
        )
    if not slate.goals:
        lines.append("(no candidate goals)")
    return "\n".join(lines)


def _render_run_summary(
    goal: CandidateGoal, state: RunState, run_dir: Path, tools: ToolRegistry
) -> str:
    """Human summary of a finished loop run: status, budget use, artifact paths."""
    lines = [
        "",
        f"dispatched : {goal.title}  (id={goal.id})",
        f"status     : {state.status.value}",
        f"iterations : {state.iterations_used}    llm calls: {state.llm_calls_used}",
        f"run dir    : {run_dir}",
    ]
    artifacts = tools.artifacts()
    if artifacts:
        lines.append("artifacts  :")
        lines.extend(f"  - {tools.artifacts_dir / rel}" for rel in artifacts)
    else:
        lines.append("artifacts  : (none)")
    return "\n".join(lines)


def _write_meta(run_dir: Path, workspace_root: Path, artifacts_dir: Path) -> None:
    """Record the roots a `resume` needs (RunState alone lacks workspace_root)."""
    (run_dir / _META_NAME).write_text(
        json.dumps(
            {"workspace_root": str(workspace_root), "artifacts_dir": str(artifacts_dir)},
            indent=2,
        )
    )


def _read_meta(run_dir: Path) -> dict:
    """Load run metadata, or ``{}`` if none was written."""
    path = run_dir / _META_NAME
    return json.loads(path.read_text()) if path.is_file() else {}


def _iter_run_dirs(state_dir: Path) -> list[Path]:
    """Return *state_dir*'s ``run-*`` subdirs, sorted ascending by ``.name``.

    A missing or non-directory *state_dir* yields ``[]`` so ``runs`` degrades to
    a clean "no runs" line instead of raising -- the same tolerant posture the
    rest of the run machinery already takes. Sorting by name (not mtime) makes
    the listing deterministic: two invocations against an unchanged state dir
    produce byte-identical output.
    """
    if not state_dir.is_dir():
        return []
    return sorted(
        (p for p in state_dir.iterdir() if p.is_dir() and p.name.startswith("run-")),
        key=lambda p: p.name,
    )


def _count_artifacts(run_dir: Path) -> int:
    """Count regular files under *run_dir*'s ``artifacts/`` (recursive); 0 if absent."""
    artifacts_dir = run_dir / _ARTIFACTS_NAME
    if not artifacts_dir.is_dir():
        return 0
    return sum(1 for p in artifacts_dir.rglob("*") if p.is_file())


def _run_row(run_dir: Path) -> dict:
    """Summarize one run dir into a plain, JSON-serializable row.

    Tolerant by construction: a run dir whose ``checkpoint.json`` is missing OR
    unreadable (truncated/corrupt) still produces a legible row whose status is
    the verbatim ``(no checkpoint)`` marker -- one bad run must never abort the
    whole listing or raise out of the handler. ``RunStatus`` is a str-Enum, so a
    loaded status is emitted as ``state.status.value`` (e.g. ``done``), never the
    ``RunStatus.DONE`` repr. ``run_id`` is the dir name (``run-<goal_id>``) -- the
    exact value a person feeds ``resume --run-dir``, which is the point of listing.
    """
    try:
        state = Checkpoint(run_dir / _CHECKPOINT_NAME).load()
    except (ValueError, OSError):
        state = None  # corrupt/truncated checkpoint -> degrade, never crash the listing
    try:
        meta = _read_meta(run_dir)
    except (ValueError, OSError):
        meta = {}
    if state is not None:
        status = state.status.value
        goal = state.goal.title
        iterations = state.iterations_used
    else:
        status, goal, iterations = _NO_CHECKPOINT, "", 0
    return {
        "run_id": run_dir.name,
        "status": status,
        "goal": goal,
        "iterations": iterations,
        "artifacts": _count_artifacts(run_dir),
        "workspace": meta.get("workspace_root", ""),
    }


def _render_runs(rows: list[dict]) -> str:
    """Render run rows as a plain-text table, or a legible "no runs" line.

    A pure function of its (already id-sorted) input rows -- mirrors the
    _render_table / _render_run_summary convention so the output is deterministic
    and unit-testable without touching disk.
    """
    if not rows:
        return "no runs found under the state dir."
    header = f"{'RUN ID':<26} {'STATUS':<16} {'ITERS':>5} {'ARTIFACTS':>9}  GOAL"
    lines = [header, "-" * max(len(header), 60)]
    for row in rows:
        lines.append(
            f"{row['run_id']:<26} {row['status']:<16} {row['iterations']:>5} "
            f"{row['artifacts']:>9}  {row['goal']}"
        )
    return "\n".join(lines)


def _render_explain(
    goal: CandidateGoal, decision: DispatchDecision, settings: Settings
) -> str:
    """Render one goal's full decision audit: score math, gate outcome, sources.

    A pure function of ``(goal, decision, settings)`` -- like ``_render_table`` /
    ``_render_runs`` it touches no disk, so the same block is reproducible from a
    loaded slate alone (behavior 10). The score line's right-hand side is
    ``goal.score`` *echoed*, never recomputed here, so the printed arithmetic can
    never disagree with the computed field that actually drives ranking. Numeric
    operands use ``:g`` (drop trailing zeros: ``4.0`` -> ``4``, ``0.9`` -> ``0.9``)
    so the math reads the way the model authored the weights; the threshold uses
    plain float form (``4.0``) so it echoes ``settings.auto_dispatch_min_score`` as
    stored. The gate outcome + reason surface verbatim from ``decision`` -- the
    same object ``dispatch`` acts on -- so explain and a later dispatch agree.
    """
    # Substituted arithmetic mirrors CandidateGoal.score's formula exactly; the
    # right-hand {score} is the model's own computed field, echoed verbatim so the
    # printed result can never drift from the value that drives ranking.
    arithmetic = (
        f"{goal.impact:g} * {goal.urgency:g} * {goal.confidence:g} "
        f"/ {goal.effort_weight:g} = {goal.score:g}"
    )
    lines = [
        f"goal        : {goal.title}  (id={goal.id})",
        f"category    : {goal.category.value}",
        "score       : impact * urgency * confidence / effort_weight",
        f"              {arithmetic}   "
        f"(auto-dispatch threshold: {settings.auto_dispatch_min_score})",
        f"decision    : {decision.decision.value}  ({decision.reason})",
        f"appropriate now: {str(goal.appropriate_now).lower()}",
        f"rationale   : {goal.rationale}",
    ]
    # A (none) marker (not an omitted section) keeps the block shape stable
    # whether or not the synthesizer attached any provenance to the goal.
    lines.append("sources     :")
    if goal.sources:
        lines.extend(f"  - {src}" for src in goal.sources)
    else:
        lines.append("  (none)")
    lines.append("suggested first steps:")
    if goal.suggested_first_steps:
        lines.extend(f"  - {step}" for step in goal.suggested_first_steps)
    else:
        lines.append("  (none)")
    return "\n".join(lines)


def _dispatch_goal(
    goal: CandidateGoal, workspace_root: Path, settings: Settings, client
) -> int:
    """Execute one already-approved goal through a checkpointed GoalLoop.

    Callers MUST gate *goal* before calling this -- the sandbox and the autonomy
    contract are enforced upstream (in the verb handlers); this helper only runs
    what it is handed.
    """
    run_dir = settings.state_dir / f"run-{goal.id}"
    artifacts_dir = run_dir / _ARTIFACTS_NAME
    ensure_dir(run_dir)
    _write_meta(run_dir, workspace_root, artifacts_dir)

    tools = ToolRegistry(workspace_root=workspace_root, artifacts_dir=artifacts_dir)
    checkpoint = Checkpoint(run_dir / _CHECKPOINT_NAME)
    loop = GoalLoop(client, settings, tools, checkpoint)
    state = loop.run(goal)

    print(_render_run_summary(goal, state, run_dir, tools))
    # DONE and BUDGET_EXHAUSTED are both valid loop terminations, not CLI faults.
    return 0


# ---------------------------------------------------------------------------
# subcommand handlers
# ---------------------------------------------------------------------------


def _cmd_scan(args: argparse.Namespace) -> int:
    """scan: collect -> synthesize -> gate -> print table -> write slate JSON."""
    workspace = Path(args.workspace)
    settings = _settings(args, workspace_root=workspace)
    client = create_client(settings)

    snapshot = _collect(workspace)
    slate = GoalSynthesizer(client, settings).synthesize(snapshot)
    decisions = gate_slate(slate, settings)

    print(_render_table(slate, decisions))
    out = Path(args.out) if args.out else settings.state_dir / _SLATE_NAME
    _write_slate(slate, out)
    print(f"\nslate written: {out}")
    return 0


def _cmd_dispatch(args: argparse.Namespace) -> int:
    """dispatch: re-gate a saved goal, then run it if the gate (and --yes) allow.

    Re-gating on dispatch (not trusting the slate's earlier decision) keeps the
    autonomy contract authoritative even if the slate file was hand-edited.
    """
    slate_path = Path(args.slate)
    if not slate_path.is_file():
        print(f"error: slate file not found: {slate_path}", file=sys.stderr)
        return 2

    slate = GoalSlate.model_validate_json(slate_path.read_text())
    workspace_root = Path(slate.workspace_root) if slate.workspace_root else Path(".")
    settings = _settings(args, workspace_root=workspace_root)

    goal = slate.get(args.goal_id)
    if goal is None:
        print(f"error: goal id {args.goal_id!r} not found in slate", file=sys.stderr)
        return 2

    decision = gate(goal, settings)
    if decision.decision == AutonomyDecision.BLOCKED:
        print(
            f"refusing to dispatch {goal.title!r}: {decision.reason} (BLOCKED)",
            file=sys.stderr,
        )
        return 3
    if decision.decision == AutonomyDecision.NEEDS_APPROVAL and not args.yes:
        print(
            f"{goal.title!r} needs approval ({decision.reason}); "
            "re-run with --yes to dispatch.",
            file=sys.stderr,
        )
        return 4

    client = create_client(settings)
    return _dispatch_goal(goal, workspace_root, settings, client)


def _cmd_run(args: argparse.Namespace) -> int:
    """run: scan, then auto-dispatch ONLY the single top AUTO_DISPATCH goal.

    Approval-gated goals are listed for the user with a ready-to-paste dispatch
    command but are NEVER auto-run -- that is the whole point of the L2 gate.
    """
    workspace = Path(args.workspace)
    settings = _settings(args, workspace_root=workspace)
    client = create_client(settings)

    snapshot = _collect(workspace)
    slate = GoalSynthesizer(client, settings).synthesize(snapshot)
    decisions = gate_slate(slate, settings)

    print(_render_table(slate, decisions))
    slate_path = settings.state_dir / _SLATE_NAME
    _write_slate(slate, slate_path)

    ranked = slate.ranked()
    top: CandidateGoal | None = None
    needs_approval: list[CandidateGoal] = []
    for goal, decision in zip(ranked, decisions):
        if decision.decision == AutonomyDecision.AUTO_DISPATCH and top is None:
            top = goal
        elif decision.decision == AutonomyDecision.NEEDS_APPROVAL:
            needs_approval.append(goal)

    if needs_approval:
        print(f"\n{len(needs_approval)} goal(s) need approval and were NOT auto-run:")
        for goal in needs_approval:
            print(
                f"  - {goal.title}\n"
                f"      pla dispatch --slate {slate_path} --goal-id {goal.id} --yes"
            )

    if top is None:
        print("\nno auto-dispatchable goal in this slate; nothing to run.")
        return 0

    print(f"\nauto-dispatching top goal: {top.title}")
    return _dispatch_goal(top, workspace, settings, client)


def _cmd_resume(args: argparse.Namespace) -> int:
    """resume: load a checkpoint and continue its GoalLoop to termination."""
    run_dir = Path(args.run_dir)
    checkpoint = Checkpoint(run_dir / _CHECKPOINT_NAME)
    state = checkpoint.load()
    if state is None:
        print(f"error: no checkpoint found in {run_dir}", file=sys.stderr)
        return 2

    settings = _settings(args)
    meta = _read_meta(run_dir)
    workspace_root = Path(meta.get("workspace_root", "."))
    artifacts_dir = (
        Path(state.artifacts_dir) if state.artifacts_dir else run_dir / _ARTIFACTS_NAME
    )

    client = create_client(settings)
    tools = ToolRegistry(workspace_root=workspace_root, artifacts_dir=artifacts_dir)
    loop = GoalLoop(client, settings, tools, checkpoint)
    final = loop.run(state.goal, resume=state)

    print(_render_run_summary(state.goal, final, run_dir, tools))
    return 0


def _cmd_runs(args: argparse.Namespace) -> int:
    """runs: list past dispatched runs under the state dir (read-only, LLM-free).

    WHY it builds no LLMClient: it is a pure, tolerant read over the run state
    dispatch/run/resume already persist, so a fresh clone can enumerate and
    inspect every past run with zero provider wiring. It also repairs resume's
    usability -- the run_id column is exactly the --run-dir value resume wants,
    so discovering a run no longer means hand-hunting an opaque path. Always
    exits 0: an absent or empty state dir is a legitimate "no runs" answer, not
    a fault.
    """
    settings = _settings(args)
    rows = [_run_row(d) for d in _iter_run_dirs(settings.state_dir)]
    if args.json:
        # The ENTIRE stdout must parse as one JSON array (empty -> []); no prose.
        print(json.dumps(rows, indent=2))
    else:
        print(_render_runs(rows))
    return 0


def _cmd_explain(args: argparse.Namespace) -> int:
    """explain: print one goal's full, LLM-free decision audit from a saved slate.

    WHY it builds no LLMClient (like ``runs``): it is a pure read over a persisted
    slate. It re-gates the goal through the SAME ``gate(goal, settings)`` the
    ``dispatch`` verb uses -- so an ``explain`` and a subsequent ``dispatch`` can
    never disagree -- and renders the score arithmetic, the autonomy rule that
    fired, and the goal's rationale/sources/first-steps. It runs nothing and
    re-scores nothing. Exit codes mirror ``dispatch``: ``2`` for a missing slate
    file or an unknown goal id (returned explicitly, before any exception); a
    corrupt slate raises ``ValidationError`` (a ``ValueError``) and is mapped to
    ``1`` by the top-level ``main()`` boundary as one legible ``error:`` line.
    """
    slate_path = Path(args.slate)
    if not slate_path.is_file():
        print(f"error: slate file not found: {slate_path}", file=sys.stderr)
        return 2

    slate = GoalSlate.model_validate_json(slate_path.read_text())

    goal = slate.get(args.goal_id)
    if goal is None:
        print(f"error: goal id {args.goal_id!r} not found in slate", file=sys.stderr)
        return 2

    settings = _settings(args)
    decision = gate(goal, settings)
    print(_render_explain(goal, decision, settings))
    return 0


if __name__ == "__main__":  # pragma: no cover - module entry convenience
    raise SystemExit(main())
