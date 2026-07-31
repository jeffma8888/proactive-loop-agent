"""Command-line entry point (L2 orchestration surface).

WHY a thin CLI over the library layers: every capability the CLI exposes already
lives in a tested module (collectors, scout, loop). This file only *wires* them
into eleven verbs a person actually runs -- scan, dispatch, run, resume, the
read-only runs lister, the read-only explain auditor, the read-only trace
transcript renderer, the read-only signals perception inspector, the periodic
watch loop, the read-only diff slate-delta inspector, and the read-only policy
autonomy-contract catalog -- and owns
the two things a library must not: argument
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
import csv
import io
import json
import logging
import math
import sys
from pathlib import Path

from pydantic import ValidationError

from . import __version__
from .config import Settings
from .collectors import all_collectors
from .llm import LLMError
from .llm.providers import create_client
from .loop import Checkpoint, GoalLoop, ToolRegistry
from .models import (
    AutonomyDecision,
    CandidateGoal,
    ContextSignal,
    DispatchDecision,
    GoalCategory,
    GoalSlate,
    LoopStep,
    RunState,
    RunStatus,
    StepKind,
    WorkspaceSnapshot,
    ensure_dir,
    sanitize_validation_error,
)
from .scheduler import run_periodic
from .scout import GoalSynthesizer, gate, gate_slate

# Module logger for the orchestration layer. WHY only obtain a logger (never
# configure handlers/levels here): a library must leave global logging policy to
# its caller (or pytest's caplog); this file only emits records. Its name
# resolves to "proactive_loop.cli".
_LOG = logging.getLogger(__name__)

_META_NAME = "meta.json"
_CHECKPOINT_NAME = "checkpoint.json"
_ARTIFACTS_NAME = "artifacts"
_SLATE_NAME = "slate.json"
# Verbatim status marker shown by the runs lister for a run dir with no loadable
# checkpoint; the black-box behavior contract depends on this exact text, so it
# lives as a named constant rather than an inline literal.
_NO_CHECKPOINT = "(no checkpoint)"
# Max chars of a step's (newline-collapsed) output shown in the HUMAN trace
# render. Kept well under the behavior contract's 500-char probe so a long tool
# observation is always visibly truncated in the block form; the untruncated
# text is only ever surfaced via `trace --json`. A named constant (not an inline
# literal) so the truncation policy has one home.
_TRACE_OUTPUT_WIDTH = 80


# ---------------------------------------------------------------------------
# logging setup
# ---------------------------------------------------------------------------


class _CliLogHandler(logging.StreamHandler):
    """The single stderr handler the CLI attaches under ``-v``/``-vv``.

    WHY a dedicated subclass and not a bare ``StreamHandler``: it lets
    ``_configure_logging`` recognise *its own* handler by type and stay strictly
    idempotent -- re-invoking ``main()`` within one process (as the test suite
    does hundreds of times) must reuse this handler, never stack a second one on
    the package logger.
    """


def _verbosity_to_level(count: int) -> int:
    """Map a ``-v`` repeat *count* to a stdlib logging level. Pure, no side effects.

    ``count <= 0`` -> ``WARNING`` (the library default; level-0 is a deliberate
    no-op so default output stays byte-identical). ``count == 1`` -> ``INFO``,
    ``count >= 2`` -> ``DEBUG``. Reads no logger and mutates no global state, so
    it is trivially unit-testable and safe to call on every invocation.
    """
    if count <= 0:
        return logging.WARNING
    if count == 1:
        return logging.INFO
    return logging.DEBUG


def _configure_logging(level: int) -> None:
    """Attach one guarded stderr handler to the ``proactive_loop`` package logger.

    WHY level-0 (``WARNING``) is a STRICT no-op -- attach nothing, change no
    level: the library never configures logging for itself, and the only default
    emit site (the iter-19 ``_collect`` WARNING) rides Python last-resort
    handler; attaching any handler here would divert that record and change
    default output. So we configure only when the operator asked for more
    (``-v``/``-vv``, i.e. ``level < WARNING``).

    Idempotent by design: it finds an existing :class:`_CliLogHandler` and reuses
    it (refreshing the stream to the *current* ``sys.stderr`` so it stays correct
    under repeated calls or captured streams) rather than adding a second handler.
    It touches ONLY the ``proactive_loop`` logger -- never the root logger, never
    ``logging.basicConfig`` -- so it cannot perturb the caller global logging.
    """
    if level >= logging.WARNING:
        return
    logger = logging.getLogger("proactive_loop")
    handler = next(
        (h for h in logger.handlers if isinstance(h, _CliLogHandler)), None
    )
    if handler is None:
        handler = _CliLogHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(name)s: %(message)s"))
        logger.addHandler(handler)
    else:
        # Re-point at the live stderr (pytest capsys / redirection swap it) so a
        # reused handler never writes to a stale, possibly-closed stream.
        handler.setStream(sys.stderr)
    logger.setLevel(level)


# ---------------------------------------------------------------------------
# argument parsing
# ---------------------------------------------------------------------------


def _positive_int(raw: str) -> int:
    """argparse ``type=`` validator: parse a STRICTLY-positive integer.

    WHY it lives on the argument's ``type=`` and not inside ``main()``: like
    ``--format``'s ``choices=``, it fires at PARSE time -- BEFORE any LLM client
    is built, any collector runs, or any slate is written -- so a bad ``--top`` is
    a ``SystemExit(2)`` usage error with zero side effects (no partial slate file).
    ``int(raw)`` lets a non-integer (e.g. ``abc``) raise ``ValueError``, which
    argparse itself converts into the exit-2 usage error; a parsed value ``< 1``
    (``0``, ``-1``) raises ``ArgumentTypeError`` because zero rendered rows is a
    degenerate view, not a use case.
    """
    value = int(raw)
    if value < 1:
        raise argparse.ArgumentTypeError(f"must be a positive integer (>= 1), got {value}")
    return value


def _non_negative_float(raw: str) -> float:
    """argparse ``type=`` validator: parse a FINITE, NON-negative float (``>= 0``).

    Mirrors ``_positive_int`` for ``watch``'s ``--interval``: it fires at PARSE
    time -- BEFORE any LLM client is built, any collector runs, or any tick is
    rendered -- so a bad ``--interval`` is a ``SystemExit(2)`` usage error with
    zero side effects, never a half-completed run that emits scan #1 then dies on
    the 2nd tick's ``time.sleep`` leaking its builtin ``sleep length must be
    non-negative`` errno string. ``float(raw)`` lets a non-number (e.g. ``abc``)
    raise ``ValueError``, which argparse itself converts into the exit-2 usage
    error; a NON-finite value (``nan``/``inf``/``-inf``) or a parsed
    ``value < 0.0`` raises ``ArgumentTypeError``. The finite check runs BEFORE the
    ``< 0.0`` check, so ``-inf`` is reported as non-finite, not merely negative.

    WHY reject non-finite (iter-40): ``float("nan") < 0.0`` and ``float("inf") <
    0.0`` are BOTH ``False``, so a fat-fingered ``--interval nan``/``inf`` slipped
    the ``< 0.0`` guard and detonated downstream in ``scheduler.run_periodic``'s
    ``time.sleep`` -- rendering scan #1 (a side effect) then leaking a raw builtin
    (``Invalid value NaN`` / ``OverflowError: timestamp out of range``). Rejecting
    non-finite at parse time closes that gap and honors this validator's own
    zero-side-effects contract on the namesake ``watch`` verb.

    WHY ``>= 0.0`` and NOT ``> 0.0`` (do NOT "tighten" this): ``--interval 0`` is a
    LOAD-BEARING legal value pinned by SPEC §4.5 so the offline test-suite can
    drive ``watch`` with a bounded ``--max-scans`` and NO real ``sleep`` wait. A
    zero interval is a supported test-drive knob, not a degenerate input. This is
    ORTHOGONAL to the non-finite rejection above: rejecting ``nan``/``inf`` does
    not touch the ``0``-is-legal rule -- ``0.0`` is finite and ``>= 0.0``.
    """
    value = float(raw)
    if not math.isfinite(value):
        raise argparse.ArgumentTypeError(f"must be a finite number, got {value}")
    if value < 0.0:
        raise argparse.ArgumentTypeError(
            f"must be a non-negative number (>= 0), got {value}"
        )
    return value


def build_parser() -> argparse.ArgumentParser:
    """Assemble the ``pla`` parser with eleven subcommands and shared globals.

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
        help="LLM provider: scripted (default, offline) | anthropic | openai | bedrock | ollama",
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
    # Repeatable verbosity dial, on the SHARED globals parent so it is accepted
    # AFTER any subcommand (like --provider). count-action: absent -> 0, -v -> 1,
    # -vv -> 2, ... WHY it lives here and NOT on the top-level parser (where
    # --version is): --version must short-circuit with no subcommand, but -v is a
    # per-run knob every verb inherits. No collision with --version -- that is a
    # long option on the top-level parser only; -v is a short option on the
    # subparsers, and argparse abbreviation applies to long options, never short.
    globals_.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help=(
            "Increase runtime log verbosity on stderr (-v INFO, -vv DEBUG); "
            "surfaces the L0 retry/backoff self-healing as it happens. "
            "Default (absent) is silent and leaves stdout untouched."
        ),
    )

    sub = parser.add_subparsers(dest="command", required=True)

    p_scan = sub.add_parser(
        "scan", parents=[globals_], help="Scan a workspace and print a ranked goal slate."
    )
    p_scan.add_argument("--workspace", required=True, help="Workspace root to scan.")
    p_scan.add_argument(
        "--out", default=None, help="Where to write the slate JSON (default <state_dir>/slate.json)."
    )
    # choices makes argparse reject an unknown format at PARSE time (outside the
    # main() try), so an invalid value is a SystemExit(2) usage error naming the
    # bad choice -- no client built, no collection run, no slate written. Default
    # table keeps every existing scan invocation byte-for-byte unchanged.
    p_scan.add_argument(
        "--format",
        choices=["table", "json", "markdown", "csv"],
        default="table",
        help=(
            "stdout rendering: table (default, human) | json (one JSON object, no "
            "trailer, pipes cleanly into jq) | markdown (paste-ready GFM table + trailer) "
            "| csv (RFC-4180 data stream, no trailer, opens in Excel / pandas.read_csv)."
        ),
    )
    # A stdout-view cap on the number of ranked goals printed; the persisted slate
    # is ALWAYS complete (the file is the record, stdout is the view). default=None
    # means "show all", byte-identical to no flag. type=_positive_int rejects
    # --top 0/-1/abc as a PARSE-time usage error (exit 2), mirroring --format choices=
    # fail-fast discipline -- no client, no collection, no slate write.
    p_scan.add_argument(
        "--top",
        type=_positive_int,
        default=None,
        help=(
            "Print only the top-N ranked goals; the written slate is always "
            "complete. A non-positive or non-integer value is a usage error "
            "(exit 2). Default (absent) shows all goals."
        ),
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
    # Mirrors runs/trace/signals: a default-off boolean that swaps the human audit
    # block for one JSON object (the 12-key gate-audit schema). It is applied AFTER
    # the exit-2/exit-1 guards in _cmd_explain, so it selects a rendering only and
    # never perturbs the exit-code contract.
    p_explain.add_argument(
        "--json",
        action="store_true",
        help="Emit the gate audit as one JSON object instead of the human block.",
    )
    p_explain.set_defaults(func=_cmd_explain)

    # `trace` renders ONE dispatched run's persisted PLAN->ACT->CHECK transcript
    # from its checkpoint. Like `runs`/`explain` it inherits the globals so
    # --provider/--scripted-responses are accepted but inert -- it builds no
    # LLMClient, so a fresh clone can inspect what a finished run did with zero
    # provider config. --run-dir is required (mirrors `resume`); --json swaps the
    # truncated human transcript for a full, machine-parseable array of steps.
    p_trace = sub.add_parser(
        "trace",
        parents=[globals_],
        help="Render one run's PLAN/ACT/CHECK step transcript from its checkpoint (read-only, LLM-free).",
    )
    p_trace.add_argument("--run-dir", required=True, help="A run-<id> directory to trace.")
    p_trace.add_argument(
        "--json",
        action="store_true",
        help="Emit the step transcript as a JSON array (full, untruncated output) instead of the human block.",
    )
    p_trace.set_defaults(func=_cmd_trace)

    # `signals` prints the raw ContextSignals the collectors perceive for a
    # workspace -- the FIRST stage of the pipeline, which every other verb hides
    # behind a synthesize call. Like `runs`/`explain`/`trace` it inherits the
    # globals so --provider/--scripted-responses/--state-dir are accepted but
    # INERT: the handler builds no LLMClient, so a fresh clone can inspect what
    # the scout sees with zero provider wiring and without paying for an LLM call.
    # --workspace is required (mirrors scan/run); --json swaps the grouped human
    # view for one machine-parseable object; --kind narrows to one collector kind.
    p_signals = sub.add_parser(
        "signals",
        parents=[globals_],
        help="Print the raw context signals the collectors perceive (read-only, LLM-free).",
    )
    p_signals.add_argument("--workspace", required=True, help="Workspace root to inspect.")
    p_signals.add_argument(
        "--json",
        action="store_true",
        help="Emit the signals as one JSON object instead of the grouped human view.",
    )
    p_signals.add_argument(
        "--kind",
        default=None,
        help="Show only signals of this collector-defined kind (e.g. todo|note|git_commit).",
    )
    p_signals.set_defaults(func=_cmd_signals)

    # `watch` wires scheduler.run_periodic into a user-facing verb: it re-runs the
    # SAME collect->synthesize->gate->render body every --interval seconds,
    # re-printing the ranked, gated slate as the workspace changes -- the
    # proactive-monitoring loop the product is named for. Unlike `scan` it is a
    # LIVE view: it writes NO slate file and prints no `slate written:` trailer (a
    # monitor tick's output is ephemeral, not an artifact a later `dispatch`
    # reads). --max-scans bounds the run (default None = run until Ctrl-C, the
    # production case); --interval accepts 0 so the offline tests drive it with a
    # bounded --max-scans and no real waiting.
    #
    # Both numeric knobs are guarded at PARSE time, matching --top's fail-fast
    # discipline: --interval is a _non_negative_float (>= 0; 0 stays legal per
    # SPEC §4.5) and --max-scans reuses --top's _positive_int (>= 1). A bad value
    # is a SystemExit(2) usage error BEFORE any client/collect/render -- so the
    # namesake watch loop can never half-run a scan then leak time.sleep's builtin
    # "sleep length must be non-negative" on a negative interval, nor silently
    # succeed on a zero/negative --max-scans (a degenerate no-op that reported
    # exit 0). Non-string argparse defaults (3600.0 / None) bypass type= entirely,
    # so the "run forever, hourly" production default is untouched.
    p_watch = sub.add_parser(
        "watch",
        parents=[globals_],
        help="Repeatedly scan a workspace on an interval (proactive watch loop).",
    )
    p_watch.add_argument("--workspace", required=True, help="Workspace root to watch.")
    p_watch.add_argument(
        "--interval",
        type=_non_negative_float,
        default=3600.0,
        help=(
            "Seconds to wait between scans (default 3600). Non-negative (>= 0; 0 is "
            "legal for offline test-drives); a negative or non-numeric value is a "
            "usage error (exit 2)."
        ),
    )
    p_watch.add_argument(
        "--max-scans",
        type=_positive_int,
        default=None,
        help=(
            "Stop after N scans (default: run until interrupted with Ctrl-C). A "
            "non-positive or non-integer value is a usage error (exit 2)."
        ),
    )
    p_watch.set_defaults(func=_cmd_watch)

    # `diff` compares TWO saved slates and classifies goals as added/removed/
    # changed/unchanged -- the comparative companion to `watch`, turning a stream
    # of point-in-time slates into a change feed. Like runs/explain/trace/signals
    # it inherits the globals so --provider/--scripted-responses/--state-dir are
    # accepted but INERT: the handler builds no LLMClient, runs no collector, and
    # writes no file. --old and --new are both required; --json swaps the human
    # sections for one machine-parseable object. It matches goals by NORMALIZED
    # TITLE, never the random per-scan id (an id-match reports 100% churn per scan).
    p_diff = sub.add_parser(
        "diff",
        parents=[globals_],
        help="Compare two saved slates and classify goals as added/removed/changed (read-only, LLM-free).",
    )
    p_diff.add_argument("--old", required=True, help="Path to the OLDER slate JSON from `scan`.")
    p_diff.add_argument("--new", required=True, help="Path to the NEWER slate JSON from `scan`.")
    p_diff.add_argument(
        "--json",
        action="store_true",
        help="Emit the diff as one JSON object instead of the human sections.",
    )
    p_diff.set_defaults(func=_cmd_diff)

    # `policy` prints the STANDING autonomy contract itself -- the product's
    # headline safety mechanism -- with zero input: no --workspace, no slate, no
    # LLM. It inherits the globals so --provider/--scripted-responses/--state-dir
    # are accepted but INERT (the handler builds no LLMClient, runs no collector,
    # touches no filesystem); it exists precisely so a reviewer of this public repo
    # can answer "how does it decide what to auto-run vs. gate for approval?"
    # WITHOUT first running a scan against an LLM-configured workspace. It is the
    # top of the decision arc: policy (the rules) -> scan (proposals) -> explain
    # (why THIS goal) -> trace (what it did). --json swaps the human catalog for one
    # explicit-allowlist object; the threshold is resolved through the shared
    # _settings seam, so a PLA_AUTO_DISPATCH_MIN_SCORE override shows the EFFECTIVE
    # contract. Deliberately NO --workspace: the contract is context-free.
    p_policy = sub.add_parser(
        "policy",
        parents=[globals_],
        help="Print the standing autonomy contract: gate rules, auto-dispatch threshold, and sensitive categories (read-only, LLM-free).",
    )
    p_policy.add_argument(
        "--json",
        action="store_true",
        help="Emit the autonomy contract as one JSON object instead of the human catalog.",
    )
    p_policy.set_defaults(func=_cmd_policy)

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
    # Configure package-logger verbosity ONCE, before dispatch, from the shared
    # -v/--verbose count. Level 0 (no -v) is a strict no-op, so default runs stay
    # byte-identical; -v/-vv route the executor L0-retry INFO/DEBUG records to
    # stderr as the run backs off, leaving every verb stdout untouched.
    _configure_logging(_verbosity_to_level(getattr(args, "verbose", 0)))
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


def _load_slate(path: Path) -> GoalSlate:
    """Load + validate a slate JSON file, mapping pydantic's ``ValidationError``
    to one dependency-opaque ``ValueError`` (see ``sanitize_validation_error``).

    Shared by every slate-load verb (``explain``/``dispatch``/``diff``) so the
    failure path is uniform: on a corrupt (malformed-JSON) OR schema-invalid slate
    the ``main()`` boundary prints ONE ``error: invalid slate file '<path>': <N>
    validation error[s][; first at <loc>]`` line -- never the vendor's multi-line
    dump (model class name, ``[type=...]`` taxonomy, ``errors.pydantic.dev/<ver>``
    URL, or the raw ``input_value=`` echo of the user's file bytes). The happy path
    is byte-identical to a bare ``model_validate_json`` -- the sanitizer only
    intercepts the failure; a ``read_text`` ``OSError`` still surfaces to ``main()``
    unchanged (the callers' ``is_file`` guard runs first anyway).
    """
    try:
        return GoalSlate.model_validate_json(path.read_text())
    except ValidationError as exc:
        raise ValueError(sanitize_validation_error("slate", path, exc)) from None


def _collect(workspace: Path) -> WorkspaceSnapshot:
    """Run every collector over *workspace* into one snapshot.

    The §4.1 contract is that collectors never raise (they degrade to ``[]``).
    This loop ENFORCES that invariant at the one orchestration seam behind every
    front-door verb (``scan``/``run``/``signals``/``watch``) rather than merely
    trusting it: each ``collect()`` call is isolated so a single collector that
    raises is logged at WARNING and contributes ``[]``, leaving the surviving
    collectors' signals intact instead of aborting the whole scan. A missing dir
    or absent git therefore still simply yields fewer signals.
    """
    signals = []
    for collector in all_collectors():
        try:
            signals.extend(collector.collect(workspace))
        except Exception as exc:  # noqa: BLE001 - deliberate: contain a buggy collector
            # A raising collector VIOLATES the §4.1 "never raises -> []" contract,
            # so it is a bug IN THAT COLLECTOR. The orchestration layer's job is to
            # contain-and-surface it (log + skip), never propagate it and take down
            # every verb that shares this seam. Broad by design: any exception a
            # collector leaks must be isolated, not just a known subset.
            _LOG.warning("collector %r raised, skipping: %s", collector.name, exc)
    return WorkspaceSnapshot(root=str(workspace), signals=signals)


def _write_slate(slate: GoalSlate, out: Path) -> None:
    """Persist the slate as pretty JSON, creating parent dirs as needed."""
    ensure_dir(out.parent)
    out.write_text(slate.model_dump_json(indent=2))


def _state_dir_guard(state_dir: Path) -> str | None:
    """Reject a ``--state-dir`` that exists but is not a directory (message-or-``None``).

    WHY a fail-fast structural check, not a permission probe: ``scan``/``run``/
    ``dispatch`` later create ``state_dir`` on demand (``ensure_dir``) and write
    the slate + run directory UNDER it, so an EXISTING non-directory (a regular
    file, a device) makes those writes raise a raw OS errno (``[Errno 17] File
    exists`` / ``[Errno 20] Not a directory``) AFTER the expensive
    collect->synthesize pipeline already ran and printed a success-looking table.
    Catching it up front -- the mirror image of the ``--workspace`` INPUT guard --
    turns that late, leaked errno into one clean actionable line and spares a live
    provider's LLM budget. An ABSENT state-dir is legal (made on demand); only an
    existing non-directory is rejected. Structural typing only -- no ``os.access``
    write-permission pre-detection (out of scope, keeps the guard deterministic).
    """
    if state_dir.exists() and not state_dir.is_dir():
        return f"--state-dir is not a directory: {state_dir}"
    return None


def _out_target_guard(out: Path) -> str | None:
    """Reject a ``--out`` slate target that cannot become a writable file (message-or-``None``).

    Pre-detects the two STRUCTURAL failures that otherwise surface only at the
    real write -- after the whole pipeline renders a success-looking table --
    leaking a raw OS errno (the mirror image of the ``--workspace`` INPUT guard):
      * ``out`` is itself a directory -> a text write raises
        ``[Errno 21] Is a directory``.
      * an EXISTING component of ``out``'s parent chain is a NON-directory (a file
        sitting where a directory must be) -> parent creation / write raises
        ``[Errno 20] Not a directory``.
    A fully-absent parent chain is LEGAL: ``_write_slate`` makes parents on demand,
    so the deepest existing ancestor of an all-new path is a directory and the
    guard allows it. The ancestor walk provably terminates: the filesystem root
    (``/``) and ``.`` both always ``exists()``, so it always reaches an existing
    node. Structural typing only -- no ``os.access`` / write-permission /
    read-only-mount pre-detection (a correctly-typed but unwritable path still
    surfaces its real error at the write via ``main()``), keeping the guard
    deterministic and side-effect-free.
    """
    if out.is_dir():
        return f"--out is a directory: {out}"
    anc = out.parent
    while not anc.exists():
        anc = anc.parent
    if not anc.is_dir():
        return f"--out parent is not a directory: {anc}"
    return None


def _render_table(
    slate: GoalSlate, decisions: list[DispatchDecision], top: int | None = None
) -> str:
    """Render the ranked slate + gate outcome as a plain-text table.

    Rows are in ranked() order so the top actionable (AUTO_DISPATCH) goal is the
    first such row -- matching the order the gate decisions were computed in.

    ``top`` caps the printed data rows to the first N ranked ``(goal, decision)``
    pairs. ``None`` (the default, and the only value a bare ``scan`` ever passes)
    is byte-identical to the pre-flag render. Slicing NEVER re-orders -- it takes
    the first N of the EXISTING ranked pairs, so shown rows are ranks
    ``1..min(N, M)``, highest score first. The ``(no candidate goals)`` marker
    keeps keying off the FULL ``slate.goals``, so it fires iff the WHOLE slate is
    empty, independent of ``top``.
    """
    header = f"{'#':>2}  {'DECISION':<14} {'SCORE':>7}  {'CATEGORY':<13} TITLE"
    lines = [header, "-" * max(len(header), 60)]
    pairs = list(zip(slate.ranked(), decisions))
    if top is not None:
        pairs = pairs[:top]
    for rank, (goal, decision) in enumerate(pairs, start=1):
        lines.append(
            f"{rank:>2}  {decision.decision.value:<14} {goal.score:>7.2f}  "
            f"{goal.category.value:<13} {goal.title}"
        )
    if not slate.goals:
        lines.append("(no candidate goals)")
    return "\n".join(lines)


def _md_cell(text: str) -> str:
    """Sanitize one string for a GitHub-flavored Markdown table cell.

    Two hazards can break a GFM table layout, and this collapses both so every
    goal renders as exactly one physical row with a constant number of ``|``
    delimiters no matter what the synthesizer put in a title: (1) an embedded
    newline or whitespace run -- ``" ".join(text.split())`` flattens ANY
    whitespace (incl. ``\n``/``\t``) to single spaces; (2) a literal ``|`` inside
    the value -- escaped to ``\\|`` AFTER the collapse so the delimiter count the
    renderer emits is the only unescaped ``|`` on the line.
    """
    return " ".join(text.split()).replace("|", "\\|")


def _render_markdown(
    slate: GoalSlate, decisions: list[DispatchDecision], top: int | None = None
) -> str:
    """Render the ranked slate + gate outcome as a paste-ready GFM table.

    A pure, disk-free function of ``(slate, decisions)`` -- like ``_render_table``
    it consumes the SAME ``zip(slate.ranked(), decisions)``, so the markdown, the
    json payload, and the human table can never disagree on order or gate outcome.
    Fixed 5-column shape ``| # | decision | score | category | title |``; every
    text cell is routed through ``_md_cell`` (behavior 8) and the score cell is
    ``:.2f`` (matching the table). An empty slate degrades to the same
    ``(no candidate goals)`` marker ``_render_table`` uses, after the header rows.

    ``top`` caps the printed data rows to the first N ranked pairs (identical
    slice discipline to ``_render_table``); ``None`` is byte-identical to the
    pre-flag render and the ``(no candidate goals)`` marker still keys off the
    FULL slate, so it is independent of ``top``.
    """
    lines = [
        "| # | decision | score | category | title |",
        "| --- | --- | --- | --- | --- |",
    ]
    pairs = list(zip(slate.ranked(), decisions))
    if top is not None:
        pairs = pairs[:top]
    for rank, (goal, decision) in enumerate(pairs, start=1):
        lines.append(
            f"| {rank} | {_md_cell(decision.decision.value)} | {goal.score:.2f} "
            f"| {_md_cell(goal.category.value)} | {_md_cell(goal.title)} |"
        )
    if not slate.goals:
        lines.append("(no candidate goals)")
    return "\n".join(lines)


def _scan_json_payload(
    slate: GoalSlate, decisions: list[DispatchDecision], top: int | None = None
) -> dict:
    """Build the ``scan --format json`` document as a pure function of inputs.

    Exactly two top-level keys -- ``workspace_root`` (the scanned path) and
    ``goals`` (an array in ``slate.ranked()`` order, the SAME ``zip`` the table and
    markdown use, so all three agree on order and gate outcome). Each goal is an
    explicit dict of exactly the seven contract keys, with ``category``/``decision``
    emitted as their str-Enum ``.value`` (never a ``GoalCategory.``/``AutonomyDecision.``
    repr) -- mirroring ``_run_row`` and ``trace --json``. Kept pure/disk-free so it
    is unit-testable without touching a workspace or a client.

    ``top`` caps the ``goals`` array to the first N ranked pairs (the SAME slice
    the table/markdown renderers apply, so the three stay consistent). The wire
    schema is UNCHANGED -- still exactly the two keys ``workspace_root`` and
    ``goals`` -- ``top`` only SHORTENS the array; it never adds a count field.
    ``None`` yields the full array (byte-identical to the pre-flag payload).
    """
    pairs = list(zip(slate.ranked(), decisions))
    if top is not None:
        pairs = pairs[:top]
    return {
        "workspace_root": slate.workspace_root,
        "goals": [
            {
                "id": goal.id,
                "title": goal.title,
                "category": goal.category.value,
                "score": goal.score,
                "appropriate_now": goal.appropriate_now,
                "decision": decision.decision.value,
                "reason": decision.reason,
            }
            for goal, decision in pairs
        ],
    }


def _render_csv(
    slate: GoalSlate, decisions: list[DispatchDecision], top: int | None = None
) -> str:
    """Render the ranked slate + gate outcome as an RFC-4180 CSV data stream.

    A pure, disk-free function of ``(slate, decisions)`` -- like ``_render_table`` /
    ``_render_markdown`` / ``_scan_json_payload`` it consumes the SAME
    ``zip(slate.ranked(), decisions)``, so the csv can never disagree with the
    human table, the markdown table, or the json payload on order, score, or gate
    outcome. Five columns exactly: ``rank, decision, score, category, title`` (the
    same column set as ``markdown``/``table`` -- an ``id`` column is deliberately out
    of scope for cross-format consistency).

    WHY the stdlib ``csv`` module and NOT a manual comma-join: RFC-4180 quoting
    *preserves* commas, double-quotes, AND embedded newlines inside a field, so a
    consumer (Excel / Google Sheets / ``pandas.read_csv`` / ``csvkit``) recovers the
    EXACT ``title`` string. ``_render_markdown``'s ``_md_cell`` deliberately does the
    OPPOSITE -- it collapses every whitespace run (incl. ``\n``) to a single space and
    escapes ``|`` so a title always renders as one physical GFM row -- so markdown
    provably cannot round-trip such a title. The two formats target different
    consumers (a spreadsheet vs a GitHub comment) with different escaping.

    ``QUOTE_MINIMAL`` (the default dialect) quotes a field ONLY when it contains the
    delimiter, a quote, or a line terminator, so the common case stays unquoted and
    diff-friendly. Titles are written VERBATIM (the raw string); the score cell is
    ``f"{score:.2f}"`` (byte-identical to the markdown/table score cell for the same
    inputs) and enums render as their ``.value`` strings.

    An empty slate yields the HEADER ROW ONLY -- a valid empty CSV table -- with NO
    ``(no candidate goals)`` prose marker (that would corrupt the data stream). This
    differs deliberately from ``table``/``markdown``, which append that marker.

    ``top`` caps the emitted data rows to the first N ranked pairs (identical slice
    discipline to the other renderers); ``None`` shows all. The persisted slate file
    is always the COMPLETE record regardless of ``top`` (that write is ``_cmd_scan``'s
    job, not this pure renderer's).

    Returns the full CSV document as a string (the stdlib writer uses ``\r\n`` row
    terminators, including after the final row, per RFC-4180). The caller emits it
    with NO extra trailing newline so ``csv.reader`` over the stdout yields exactly
    the header + data rows and no spurious blank row.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer)  # default = RFC-4180, QUOTE_MINIMAL
    writer.writerow(["rank", "decision", "score", "category", "title"])
    pairs = list(zip(slate.ranked(), decisions))
    if top is not None:
        pairs = pairs[:top]
    for rank, (goal, decision) in enumerate(pairs, start=1):
        writer.writerow(
            [
                str(rank),
                decision.decision.value,
                f"{goal.score:.2f}",
                goal.category.value,
                goal.title,
            ]
        )
    return buffer.getvalue()


def _render_run_summary(
    goal: CandidateGoal, state: RunState, run_dir: Path, tools: ToolRegistry
) -> str:
    """Human summary of a finished loop run: status, budget use, retries, artifacts.

    The ``retries`` line makes the product's headline "resilient by design"
    observable: it reports how many transient throttle/timeout blips the L0 layer
    silently recovered from during the run (0 for a clean run).
    """
    lines = [
        "",
        f"dispatched : {goal.title}  (id={goal.id})",
        f"status     : {state.status.value}",
        f"iterations : {state.iterations_used}    llm calls: {state.llm_calls_used}",
        f"retries    : {state.retries}",
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


def _trace_step_line(step: LoopStep) -> str:
    """One single-line transcript entry for *step* in the human trace render.

    Embedded newlines (and any other whitespace runs) in a step's ``output`` are
    collapsed to single spaces BEFORE width-truncation, so the block invariant
    "exactly one printed line per recorded step" holds no matter what a tool
    observation contained -- a multi-line ACT observation can never break the
    layout. The line always begins ``[{index}] {kind}`` (``kind`` is a str-Enum,
    so ``.value`` -> ``plan``/``act``/``check``), which lets a reader count
    per-step lines by that prefix; a ``check`` step appends its verdict
    (``done=true``/``done=false``) since ``done`` is only meaningful there.
    """
    # str.split() with no args splits on ANY whitespace run and drops empties, so
    # this both flattens newlines to a single line and normalizes internal spacing.
    text = " ".join(step.output.split())
    if len(text) > _TRACE_OUTPUT_WIDTH:
        # Reserve one column for the ellipsis so the shown text never exceeds the
        # configured width; the full text is only available via `trace --json`.
        text = text[: _TRACE_OUTPUT_WIDTH - 1] + "\u2026"
    line = f"[{step.index}] {step.kind.value}"
    if text:
        line += f" {text}"
    if step.kind is StepKind.CHECK:
        line += f"  done={str(step.done).lower()}"
    return line


def _render_trace(state: RunState, run_dir: Path) -> str:
    """Render one run's persisted PLAN->ACT->CHECK transcript as plain text.

    A pure, disk-free, deterministic function of ``(state, run_dir)`` -- like
    ``_render_runs`` / ``_render_run_summary`` / ``_render_explain`` it opens no
    files. The transcript is fully derivable from the loaded checkpoint alone, so
    this verb deliberately never reads ``meta.json`` (dropping a corrupt-meta
    failure edge) and builds NO ``LLMClient``: inspecting what a finished run did
    needs zero provider config. ``StepKind`` / ``RunStatus`` are str-Enums, so
    their ``.value`` is printed (``plan`` / ``done``), never the ``.PLAN`` repr.
    Header lines start with a word, per-step lines with ``[{index}]``, so the two
    are unambiguously distinguishable; an empty ``steps`` list still prints the
    header plus a legible ``(no steps recorded)`` line rather than a bare header.
    """
    header = [
        f"run dir    : {run_dir.name}",
        f"goal       : {state.goal.title}  (id={state.goal.id})",
        f"status     : {state.status.value}",
        f"steps      : {len(state.steps)}    iterations: {state.iterations_used}"
        f"    llm calls: {state.llm_calls_used}    retries: {state.retries}",
    ]
    if not state.steps:
        return "\n".join([*header, "(no steps recorded)"])
    return "\n".join([*header, *(_trace_step_line(step) for step in state.steps)])


def _render_signals(snapshot: WorkspaceSnapshot, kind: str | None = None) -> str:
    """Render the raw collector signals grouped by kind as plain text.

    A pure, disk-free, deterministic function of ``(snapshot, kind)`` -- like
    ``_render_runs`` / ``_render_trace`` it opens no files and builds no client, so
    the exact human view is reproducible from a synthetic snapshot alone. The
    optional ``kind`` narrows the view to one collector-defined kind; an empty
    selection (zero signals, or a ``kind`` matching none) degrades to a single
    ``(no signals collected)`` marker rather than a bare or blank block. Kind
    headers ``## <kind> (<count>)`` appear in ascending lexicographic order, and
    within each section signals are ordered by ``(source, summary, path or "")``
    so two renders of the same snapshot are byte-identical. ``weight`` is shown as
    ``w<value:.2f>`` (the JSON view keeps it a raw number); a signal's ``path`` is
    echoed verbatim after `` -> `` ONLY when present, so a path-less note carries
    no arrow. Header lines start with ``## `` and signal lines with two spaces, so
    the two are unambiguously distinguishable (a caller can count kinds by ``## ``).
    """
    selected = [s for s in snapshot.signals if kind is None or s.kind == kind]
    if not selected:
        return "(no signals collected)"
    grouped: dict[str, list[ContextSignal]] = {}
    for signal in selected:
        grouped.setdefault(signal.kind, []).append(signal)
    lines: list[str] = []
    for group_kind in sorted(grouped):
        section = grouped[group_kind]
        lines.append(f"## {group_kind} ({len(section)})")
        for signal in sorted(section, key=lambda s: (s.source, s.summary, s.path or "")):
            line = f"  {signal.source}  w{signal.weight:.2f}  {signal.summary}"
            if signal.path is not None:
                line += f" -> {signal.path}"
            lines.append(line)
    return "\n".join(lines)


def _signals_json_payload(snapshot: WorkspaceSnapshot, kind: str | None = None) -> dict:
    """Build the ``signals --json`` document as a pure function of inputs.

    Exactly two top-level keys -- ``workspace_root`` (== ``snapshot.root``) and
    ``signals`` (a FLAT array ordered by ``(kind, source, summary, path or "")``).
    Each signal is an EXPLICIT dict of exactly the six contract keys ``source,
    kind, summary, detail, path, weight`` -- never ``model_dump`` (the iter-08
    schema-leak lesson): the model's ``timestamp`` (and any field added later) is
    deliberately excluded so the wire schema stays a small, stable contract a
    ``jq`` pipeline can rely on. ``path`` is echoed as-is (JSON ``null`` when
    ``None``); ``weight`` stays a raw JSON number (the human view renders it
    ``w<value:.2f>``). A ``kind`` matching nothing degrades to ``signals == []``
    (NOT the human ``(no signals collected)`` marker), so the JSON is always one
    object -- an empty array, never prose. Mirrors the ``_scan_json_payload`` /
    ``_run_row`` explicit-dict convention; kept pure/disk-free so it is
    unit-testable without touching a workspace or a client.
    """
    selected = [s for s in snapshot.signals if kind is None or s.kind == kind]
    selected.sort(key=lambda s: (s.kind, s.source, s.summary, s.path or ""))
    return {
        "workspace_root": snapshot.root,
        "signals": [
            {
                "source": s.source,
                "kind": s.kind,
                "summary": s.summary,
                "detail": s.detail,
                "path": s.path,
                "weight": s.weight,
            }
            for s in selected
        ],
    }


def _explain_json_payload(
    goal: CandidateGoal, decision: DispatchDecision, settings: Settings
) -> dict:
    """Build the ``explain --json`` document as a pure function of inputs.

    The machine-readable twin of ``_render_explain``: one object of EXACTLY the
    12 contract keys, built from an EXPLICIT allowlist -- never ``goal.model_dump()``
    (the iter-08 schema-leak discipline that ``_scan_json_payload`` /
    ``_signals_json_payload`` follow): a field added later to ``CandidateGoal`` /
    ``Settings`` / ``DispatchDecision`` (a ``timestamp``-style addition) must NOT
    silently leak onto this wire schema, which a ``jq``/CI pipeline asserts on.

    ``category`` and ``decision`` emit their str-Enum ``.value`` (``"learning"`` /
    ``"auto_dispatch"``), never a ``GoalCategory.``/``AutonomyDecision.`` repr.
    ``score`` ECHOES the computed field (``goal.score``) rather than recomputing it,
    exactly as ``_render_explain`` does, so the JSON audit can never disagree with
    the value that drives ranking; ``score_components`` carries the four raw
    operands so a consumer can re-derive it. ``decision``/``reason`` come from the
    SAME ``gate(goal, settings)`` object the human path and a later ``dispatch``
    act on, and ``auto_dispatch_threshold`` echoes ``settings.auto_dispatch_min_score``
    (resolved via the ``_settings(args)`` seam every verb shares). ``sources`` and
    ``suggested_first_steps`` are plain lists -> JSON arrays (``[]`` when empty, NOT
    the human ``(none)`` marker). Kept pure/disk-free and client-free so it is
    unit-testable without a workspace, a slate file, or an ``LLMClient``.
    """
    return {
        "id": goal.id,
        "title": goal.title,
        "category": goal.category.value,
        "score": goal.score,
        "score_components": {
            "impact": goal.impact,
            "urgency": goal.urgency,
            "confidence": goal.confidence,
            "effort_weight": goal.effort_weight,
        },
        "auto_dispatch_threshold": settings.auto_dispatch_min_score,
        "decision": decision.decision.value,
        "reason": decision.reason,
        "appropriate_now": goal.appropriate_now,
        "rationale": goal.rationale,
        "sources": list(goal.sources),
        "suggested_first_steps": list(goal.suggested_first_steps),
    }


_DIFF_EPSILON = 1e-9


def _normalize_title(title: str) -> str:
    """The synthesizer's own dedup key: ``title.strip().lower()``.

    Matching two slates by this -- NEVER by ``CandidateGoal.id`` (a random
    per-scan ``default_factory``) -- is the load-bearing correctness contract of
    ``diff``: an id-based match would report every goal as both added and removed
    on every scan, since a fresh scan mints fresh ids for identical titles.
    """
    return title.strip().lower()


def _index_by_title(slate: GoalSlate) -> dict[str, CandidateGoal]:
    """Map normalized title -> goal, FIRST occurrence wins.

    Mirrors the synthesizer's own first-wins dedup: if two goals in one slate
    share a normalized title, the earlier one is kept and later duplicates are
    ignored (``setdefault``), so a single slate contributes at most one goal per
    normalized title to the comparison.
    """
    index: dict[str, CandidateGoal] = {}
    for goal in slate.goals:
        index.setdefault(_normalize_title(goal.title), goal)
    return index


def _compute_diff(old: GoalSlate, new: GoalSlate, settings: Settings) -> dict:
    """Classify goals across two slates into added / removed / changed / unchanged.

    A pure function of ``(old, new, settings)`` -- builds no client, runs nothing,
    touches no disk (like every other ``_render_*``/``_*_json_payload`` helper), so
    it is unit-testable from two in-memory slates alone. Goals are matched by
    NORMALIZED TITLE (``_index_by_title``), NEVER by the random per-scan ``id``
    (behavior 3). Both sides are re-gated LIVE with the SAME ``settings`` via the
    caller's shared ``_settings(args)`` seam, so a decision flip in the ``changed``
    bucket reflects the goal's OWN score/appropriateness/category change, never a
    settings difference -- and proves ``diff`` re-gates rather than comparing stored
    decisions (a slate persists none). A matched goal lands in ``changed`` iff its
    score moved by more than ``_DIFF_EPSILON`` OR its live gate decision flipped
    (behaviors 6, 8); otherwise it only bumps ``unchanged_count`` (behavior 7).
    Every bucket is built in normalized-title-ascending order (behaviors 10-12) by
    iterating the ``sorted`` key sets. Each row is an EXPLICIT dict of exactly its
    contract keys (never ``model_dump`` -- the iter-08 schema-leak discipline), so
    the same structure feeds both the human render and the ``--json`` payload
    without leaking a later-added model field onto the wire. ``title`` follows the
    new-vs-old source rule (behavior 11): the NEW slate's title for added/changed
    rows, the OLD slate's for removed rows.
    """
    old_index = _index_by_title(old)
    new_index = _index_by_title(new)

    added: list[dict] = []
    for key in sorted(new_index.keys() - old_index.keys()):
        goal = new_index[key]
        added.append(
            {
                "title": goal.title,
                "score": goal.score,
                "decision": gate(goal, settings).decision.value,
            }
        )

    removed: list[dict] = []
    for key in sorted(old_index.keys() - new_index.keys()):
        goal = old_index[key]
        removed.append(
            {
                "title": goal.title,
                "score": goal.score,
                "decision": gate(goal, settings).decision.value,
            }
        )

    changed: list[dict] = []
    unchanged_count = 0
    for key in sorted(old_index.keys() & new_index.keys()):
        old_goal = old_index[key]
        new_goal = new_index[key]
        old_decision = gate(old_goal, settings).decision.value
        new_decision = gate(new_goal, settings).decision.value
        score_moved = abs(new_goal.score - old_goal.score) > _DIFF_EPSILON
        if score_moved or old_decision != new_decision:
            changed.append(
                {
                    "title": new_goal.title,  # matched rows use the NEW title
                    "old_score": old_goal.score,
                    "new_score": new_goal.score,
                    "old_decision": old_decision,
                    "new_decision": new_decision,
                }
            )
        else:
            unchanged_count += 1

    return {
        "added": added,
        "removed": removed,
        "changed": changed,
        "unchanged_count": unchanged_count,
    }


def _render_diff(result: dict) -> str:
    """Render a slate diff as plain text (behaviors 9-11).

    A pure, disk-free function of the ``_compute_diff`` result -- like every other
    ``_render_*`` helper it opens no files and builds no client. When the three
    delta buckets are ALL empty (identical slates, or two empty slates) it degrades
    to the single ``(no differences)`` line regardless of how many goals were
    unchanged (behavior 9). Otherwise it prints ONLY the non-empty sections in the
    fixed order added -> removed -> changed, each a header line followed by one
    title-ascending indented row per goal, then ALWAYS the ``unchanged: <N>``
    trailer (behavior 10). Scores are ``:.2f`` (matching ``_render_table`` /
    ``_render_markdown``); decisions are the gate ``.value`` string already stored
    on each row.
    """
    added = result["added"]
    removed = result["removed"]
    changed = result["changed"]
    if not added and not removed and not changed:
        return "(no differences)"
    lines: list[str] = []
    if added:
        lines.append(f"+ added ({len(added)})")
        lines.extend(
            f"    {row['title']}  score={row['score']:.2f}  {row['decision']}"
            for row in added
        )
    if removed:
        lines.append(f"- removed ({len(removed)})")
        lines.extend(
            f"    {row['title']}  score={row['score']:.2f}  {row['decision']}"
            for row in removed
        )
    if changed:
        lines.append(f"~ changed ({len(changed)})")
        lines.extend(
            f"    {row['title']}  score {row['old_score']:.2f} -> {row['new_score']:.2f}"
            f"  decision {row['old_decision']} -> {row['new_decision']}"
            for row in changed
        )
    lines.append(f"unchanged: {result['unchanged_count']}")
    return "\n".join(lines)


def _diff_json_payload(old_path: str, new_path: str, result: dict) -> dict:
    """Build the ``diff --json`` document: one object of EXACTLY six top-level keys.

    An explicit allowlist (never ``model_dump`` -- the iter-08 schema-leak
    discipline ``_scan_json_payload`` / ``_signals_json_payload`` /
    ``_explain_json_payload`` all follow): ``old``/``new`` echo the ``--old``/``--new``
    path strings EXACTLY as passed (not a re-``str``'d ``Path``, which would drop a
    leading ``./``); ``added``/``removed`` are the ``_compute_diff`` rows
    (``{title, score, decision}``); ``changed`` is its rows
    (``{title, old_score, new_score, old_decision, new_decision}``);
    ``unchanged_count`` is a non-negative int. All three arrays are ALWAYS present,
    ordered by normalized title ascending, and emit ``[]`` (never the human
    ``(no differences)`` marker) when empty. Scores are the raw numeric
    ``goal.score`` computed field (JSON numbers, not the ``:.2f`` human strings);
    decisions are the gate ``.value`` string. Kept pure/disk-free and client-free
    so it is unit-testable without a slate file or an ``LLMClient``.
    """
    return {
        "old": old_path,
        "new": new_path,
        "added": result["added"],
        "removed": result["removed"],
        "changed": result["changed"],
        "unchanged_count": result["unchanged_count"],
    }


# The four ordered gate rules narrated in plain English, in EXACTLY the
# first-match-wins order `policy.gate` evaluates them. This is a small,
# hand-maintained ordered list -- the one deliberate, acknowledged doc-vs-code
# coupling of the `policy` verb (per the iter-39 spec): we do NOT reflect over
# `gate()`'s body to derive these strings. Only the ENUMERABLE parts of the
# contract (the category set, the threshold, the sensitive flags) are
# source-driven from `list(GoalCategory)` / `Settings`, so a new category can
# never silently drop out (the iter-37/38 completeness-trap discipline); the
# rule NARRATION is prose a human keeps in step with `scout/policy.py`.
# Each string is tied by comment to its `gate()` branch so the coupling is
# visible at the one place it lives.
_POLICY_RULES: tuple[str, ...] = (
    # gate branch 1: `goal.category in settings.sensitive_categories` -> NEEDS_APPROVAL
    "A goal in a sensitive category always needs human approval, even at a maximal score.",
    # gate branch 2: `not goal.appropriate_now` -> BLOCKED
    "Otherwise, a goal that is not appropriate right now is blocked.",
    # gate branch 3: `goal.score >= settings.auto_dispatch_min_score` -> AUTO_DISPATCH
    "Otherwise, a goal whose score meets the auto-dispatch threshold is auto-dispatched.",
    # gate branch 4: else -> NEEDS_APPROVAL
    "Otherwise, the goal needs human approval before it runs.",
)


def _policy_json_payload(settings: Settings) -> dict:
    """Build the ``policy --json`` document as a pure function of ``settings``.

    One object of EXACTLY the four contract keys
    ``{auto_dispatch_min_score, sensitive_categories, categories, rules}``, built
    from an EXPLICIT allowlist -- never ``settings.model_dump()`` (the iter-08
    schema-leak discipline every ``*_json_payload`` follows): a field added later
    to ``Settings`` (a ``model``/``retry``-style addition) must NOT silently leak
    onto this wire schema, which a ``jq``/CI pipeline asserts on.

    ``auto_dispatch_min_score`` ECHOES the resolved ``settings`` threshold (a raw
    JSON number, not the ``:.2f`` human string), so a ``PLA_AUTO_DISPATCH_MIN_SCORE``
    override surfaces the EFFECTIVE contract through the shared ``_settings`` seam.
    ``categories`` is driven straight from ``list(GoalCategory)`` (sorted by
    ``.value``) so a future category cannot silently drop out; each item is an
    EXPLICIT ``{category, sensitive}`` dict emitting the enum ``.value`` (never a
    ``GoalCategory.`` repr) with ``sensitive`` computed against
    ``settings.sensitive_categories``. ``sensitive_categories`` is that same set as
    a sorted list of ``.value`` strings. ``rules`` is the module-level
    ``_POLICY_RULES`` narration (copied to a fresh list so a caller cannot mutate
    the shared tuple). Kept pure/disk-free and client-free so it is unit-testable
    without a workspace, a slate file, or an ``LLMClient``.
    """
    return {
        "auto_dispatch_min_score": settings.auto_dispatch_min_score,
        "sensitive_categories": sorted(
            cat.value for cat in settings.sensitive_categories
        ),
        "categories": [
            {
                "category": cat.value,
                "sensitive": cat in settings.sensitive_categories,
            }
            for cat in sorted(GoalCategory, key=lambda c: c.value)
        ],
        "rules": list(_POLICY_RULES),
    }


def _render_policy(settings: Settings) -> str:
    """Render the standing autonomy contract as plain text (read-only, LLM-free).

    A pure, disk-free, deterministic function of ``settings`` -- like
    ``_render_runs`` / ``_render_signals`` it opens no file and builds no client,
    so the exact human view is reproducible from a ``Settings`` alone. It surfaces
    the headline safety mechanism as a STANDING catalog (no workspace, no slate,
    no LLM): the resolved auto-dispatch threshold, every ``GoalCategory`` tagged
    sensitive vs. auto-eligible, and the four ordered ``policy.gate`` rules in
    first-match-wins order.

    The threshold uses ``:.2f`` so a default renders ``4.00`` and a
    ``PLA_AUTO_DISPATCH_MIN_SCORE`` override renders ``6.50`` -- proving the
    EFFECTIVE contract, resolved through the shared ``_settings`` seam, is what is
    shown. Categories are driven straight from ``list(GoalCategory)`` (sorted by
    ``.value``) so a future category cannot silently drop out (the iter-37/38
    completeness-trap discipline); each carries a ``(sensitive)`` annotation IFF it
    is in ``settings.sensitive_categories`` -- so the four non-sensitive category
    lines never carry that word. Rules are numbered 1-4 in gate order.
    """
    lines = [
        "autonomy contract",
        f"  auto-dispatch threshold (min score): {settings.auto_dispatch_min_score:.2f}",
        "",
        "categories:",
    ]
    for cat in sorted(GoalCategory, key=lambda c: c.value):
        # The (sensitive) marker is the ONLY place the word appears on a category
        # line, so a line carrying a non-sensitive category value never contains it.
        annotation = "  (sensitive)" if cat in settings.sensitive_categories else ""
        lines.append(f"  - {cat.value}{annotation}")
    lines.append("")
    lines.append("gate rules (first match wins):")
    lines.extend(f"  {i}. {rule}" for i, rule in enumerate(_POLICY_RULES, start=1))
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
    """scan: collect -> synthesize -> gate -> render (table|json|markdown|csv) -> write slate JSON.

    ``--format`` selects the STDOUT rendering only; every format writes the
    identical slate file to ``--out`` (behavior 10), so a later
    ``dispatch``/``explain``/``trace`` behaves the same regardless of which format
    printed it. ``json`` and ``csv`` are the pure data-stream formats that suppress
    the ``slate written:`` trailer (and the ``--top`` truncation note) so their whole
    stdout is a single machine-parseable document -- ``json`` pipes cleanly into
    ``jq``, ``csv`` loads with ``pandas.read_csv`` / a spreadsheet; ``table`` (the
    default) and ``markdown`` keep the human trailer. The ``table`` branch is the
    pre-existing code path verbatim, so a bare ``scan`` and ``scan --format table``
    are byte-for-byte identical (behaviors 1-2).
    """
    workspace = Path(args.workspace)
    # Front-door guard: a mistyped/nonexistent workspace would otherwise degrade
    # to an empty slate + exit 0 (every collector tolerates a missing dir, SPEC
    # 4.1), silently hiding the real problem -- the path -- on the very first
    # thing a new user tries. Fail fast BEFORE building a client/collecting, so
    # the exit-2 missing-input contract matches dispatch/resume/runs/trace. This
    # runs before any format handling, so it holds for every --format value
    # (behavior 12); an invalid --format was already rejected by argparse upstream.
    if not workspace.is_dir():
        print(f"error: workspace not found: {workspace}", file=sys.stderr)
        return 2
    settings = _settings(args, workspace_root=workspace)
    # Symmetric OUTPUT-path guard (the mirror image of the --workspace INPUT
    # guard above): fail fast BEFORE building a client / collecting / rendering,
    # so a bad slate target never runs the whole pipeline and prints a
    # success-looking table only to die on a leaked OS errno. When --out is
    # given the slate goes THERE and state_dir is untouched for the slate, so we
    # guard ONLY --out; otherwise the default slate lives under state_dir, so we
    # guard state_dir. Computed ONCE here and reused by every format branch below.
    out = Path(args.out) if args.out else settings.state_dir / _SLATE_NAME
    msg = _out_target_guard(out) if args.out else _state_dir_guard(settings.state_dir)
    if msg is not None:
        print(f"error: {msg}", file=sys.stderr)
        return 2
    client = create_client(settings)

    snapshot = _collect(workspace)
    slate = GoalSynthesizer(client, settings).synthesize(snapshot)
    decisions = gate_slate(slate, settings)

    if args.format == "json":
        # Suppress the trailer so the ENTIRE stdout is one JSON document -- a
        # `pla scan --format json | jq` pipeline sees a single object and nothing
        # else. The slate file is still written identically (behavior 10).
        # --top caps only the goals array; NO note/trailer, so the jq pipe stays
        # a pure single {workspace_root, goals} object even when capped.
        print(json.dumps(_scan_json_payload(slate, decisions, top=args.top), indent=2))
        _write_slate(slate, out)
        return 0
    if args.format == "csv":
        # A pure RFC-4180 data stream (json-style purity): NO `slate written:`
        # trailer and NO `... showing top N of M` truncation note, so the ENTIRE
        # stdout is a single valid CSV document that `pandas.read_csv` / a
        # spreadsheet consumes directly. WHY `sys.stdout.write` with NO trailing
        # newline (not `print`): the csv module already terminates every row
        # (incl. the last) with `\r\n`, so `print` would append a spurious blank
        # row that `csv.reader` might surface. `--top` caps the emitted rows while
        # `_write_slate` still persists the COMPLETE slate (behaviors 5, 6).
        sys.stdout.write(_render_csv(slate, decisions, top=args.top))
        _write_slate(slate, out)
        return 0
    # table (default) and markdown share the human trailer; only the renderer
    # differs. The table branch is the original code path unchanged (behaviors 1-2).
    render = _render_markdown if args.format == "markdown" else _render_table
    print(render(slate, decisions, top=args.top))
    # `_write_slate` persists the FULL slate regardless of --top (the load-bearing
    # invariant: stdout is a view, the file is the complete record).
    _write_slate(slate, out)
    # Human truncation note (table + markdown only) -- printed ONLY when the cap
    # actually hides goals (N < M), on its own line AFTER the render and BEFORE the
    # trailer. A cap that hides nothing (top None, or top >= M) prints no note, so
    # such an invocation stays byte-identical to bare `scan`.
    if args.top is not None and args.top < len(slate.goals):
        print(f"... showing top {args.top} of {len(slate.goals)}")
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

    slate = _load_slate(slate_path)
    workspace_root = Path(slate.workspace_root) if slate.workspace_root else Path(".")
    settings = _settings(args, workspace_root=workspace_root)

    # Fail-fast state-dir guard: dispatch writes the run directory under
    # state_dir, so an existing non-directory state_dir fails late at run-write.
    # Placed AFTER the slate load + settings (so slate-not-found still wins) but
    # BEFORE the goal lookup / gate / client (so a bad state-dir wins over a
    # bogus goal-id) -- keeping both single-fault exit-2 contracts intact.
    msg = _state_dir_guard(settings.state_dir)
    if msg is not None:
        print(f"error: {msg}", file=sys.stderr)
        return 2

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
    # Same front-door guard as scan (run == scan + auto-dispatch): reject a
    # missing/non-directory workspace with exit 2 before any client/collect,
    # so a bad path never produces an empty slate + a no-op auto-dispatch.
    if not workspace.is_dir():
        print(f"error: workspace not found: {workspace}", file=sys.stderr)
        return 2
    settings = _settings(args, workspace_root=workspace)
    # Same fail-fast OUTPUT guard as scan: run writes the slate AND the run
    # directory under state_dir, so an existing non-directory state_dir would
    # spend the LLM budget then leak a raw errno at the first write. Reject
    # before create_client so nothing expensive runs on a doomed target.
    msg = _state_dir_guard(settings.state_dir)
    if msg is not None:
        print(f"error: {msg}", file=sys.stderr)
        return 2
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
    ``--json`` swaps the human audit block for one machine-parseable object
    (``_explain_json_payload``) AFTER those guards, so the exit contract is
    ``--json``-independent -- rendering selection only, like ``runs``/``trace``/``signals``.
    """
    slate_path = Path(args.slate)
    if not slate_path.is_file():
        print(f"error: slate file not found: {slate_path}", file=sys.stderr)
        return 2

    slate = _load_slate(slate_path)

    goal = slate.get(args.goal_id)
    if goal is None:
        print(f"error: goal id {args.goal_id!r} not found in slate", file=sys.stderr)
        return 2

    settings = _settings(args)
    decision = gate(goal, settings)
    if args.json:
        # The ENTIRE stdout must parse as one JSON object; no human trailer. Both
        # guards above (exit 2 / exit 1) already ran, so --json selects a rendering
        # only and leaves the exit-code contract untouched.
        print(json.dumps(_explain_json_payload(goal, decision, settings), indent=2))
    else:
        print(_render_explain(goal, decision, settings))
    return 0


def _cmd_trace(args: argparse.Namespace) -> int:
    """trace: render ONE run's persisted PLAN->ACT->CHECK transcript (read-only).

    WHY it builds no LLMClient (like ``runs``/``explain``): the transcript is a
    pure read of the ``RunState`` the loop already checkpointed after every step,
    so a fresh clone can audit exactly what a finished run *did* with zero
    provider wiring -- completing the run-lifecycle triad runs (find) -> trace
    (inspect) -> resume (continue). Exit codes mirror ``resume``'s
    missing-checkpoint contract and the shared ``main()`` error boundary: a run
    dir with no ``checkpoint.json`` (or a dir that does not exist) loads to
    ``None`` and returns ``2`` explicitly before any exception; a checkpoint that
    exists but fails ``RunState`` validation raises a ``ValueError``
    (``ValidationError`` / ``JSONDecodeError``) that the ``main()`` boundary maps
    to a single legible ``error:`` line at exit ``1`` -- no bespoke swallow, no
    traceback. Human form truncates long output for legibility; ``--json`` emits
    every step's full, untruncated output as a parseable array.
    """
    run_dir = Path(args.run_dir)
    state = Checkpoint(run_dir / _CHECKPOINT_NAME).load()
    if state is None:
        print(f"error: no checkpoint found in {run_dir}", file=sys.stderr)
        return 2
    if args.json:
        # The ENTIRE stdout must parse as one JSON array (empty -> []); no prose.
        # Each dict is built explicitly so `kind` serializes as a plain string
        # (its str-Enum .value) and the key set is exactly the contract's five --
        # mirroring _run_row's explicit-dict convention.
        rows = [
            {
                "index": step.index,
                "kind": step.kind.value,
                "output": step.output,
                "done": step.done,
                "artifacts": list(step.artifacts),
            }
            for step in state.steps
        ]
        print(json.dumps(rows, indent=2))
    else:
        print(_render_trace(state, run_dir))
    return 0


def _cmd_signals(args: argparse.Namespace) -> int:
    """signals: print the raw ContextSignals the collectors perceive (read-only).

    WHY it builds no LLMClient (like ``runs``/``explain``/``trace``): it stops at
    the FIRST pipeline stage -- ``_collect`` alone -- and never synthesizes, so a
    developer can see exactly what the scout perceives for a workspace with zero
    provider wiring and without paying for an LLM call, completing the
    transparency arc signals (what it sees) -> scan (what it proposes) -> explain
    (why it gated) -> trace (what it did). It reuses the verbatim iter-10
    ``--workspace`` ``is_dir()`` guard so a missing/non-dir path fails fast with
    ``error: workspace not found: <path>`` on stderr + exit 2 BEFORE any
    collection (never degrading to an empty inspector), matching
    scan/run/resume/runs/trace's missing-input contract. ``--json`` swaps the
    grouped human view for one machine-parseable object; ``--kind`` narrows to one
    collector-defined kind (an unrecognized kind is simply an empty selection, not
    an error -- kinds are dynamic, so there is no fixed enum to validate against).
    """
    workspace = Path(args.workspace)
    if not workspace.is_dir():
        print(f"error: workspace not found: {workspace}", file=sys.stderr)
        return 2
    snapshot = _collect(workspace)
    kind = getattr(args, "kind", None)
    if args.json:
        # The ENTIRE stdout must parse as one JSON object; no human trailer.
        print(json.dumps(_signals_json_payload(snapshot, kind), indent=2))
    else:
        print(_render_signals(snapshot, kind))
    return 0


def _cmd_watch(args: argparse.Namespace) -> int:
    """watch: re-run the scan pipeline every --interval seconds (proactive loop).

    This is the product's namesake capability finally wired to a verb: it reuses
    ``scan``'s collect -> synthesize -> gate -> render body verbatim, on a timer,
    so a live workspace's ranked, gated slate is re-printed as its context
    changes. Two deliberate departures from ``scan``: (1) it is a LIVE monitor, so
    it writes NO slate file and prints no ``slate written:`` trailer -- a watch
    tick's output is ephemeral, not an artifact a later ``dispatch`` consumes;
    (2) the LLM client is built ONCE, before the loop, and reused across ticks
    (the provider never changes between scans, and rebuilding it per-tick would be
    pointless work for a long-lived watcher).

    Bounded runs (``--max-scans N``) exist for tests and one-offs; the production
    case is ``--max-scans`` omitted (``None``) -> run forever, exited with Ctrl-C,
    exactly as ``run_periodic``'s docstring frames it. We explicitly ``return 0``
    and NOT ``run_periodic``'s scan count -- returning the count would wrongly
    surface as a nonzero exit code (e.g. 2 for a 2-scan run) through ``main()``'s
    ``int()`` cast.
    """
    workspace = Path(args.workspace)
    # Same front-door guard as scan/run/signals (verbatim iter-10): reject a
    # missing/non-directory workspace with exit 2 BEFORE building a client or
    # collecting, so a mistyped path is reported as the problem instead of
    # degrading to an empty slate looping over nothing. Runs first, so it never
    # consumes a scripted response and does not depend on --interval/--max-scans.
    if not workspace.is_dir():
        print(f"error: workspace not found: {workspace}", file=sys.stderr)
        return 2
    settings = _settings(args, workspace_root=workspace)
    client = create_client(settings)  # built once, reused every tick

    count = 0

    def scan_once() -> None:
        # run_periodic owns the timer; this closure owns one tick: a 1-based
        # header then the SAME scan body scan/run use (minus the slate-file write),
        # so `watch` and `scan` can never disagree on what a scan produces.
        nonlocal count
        count += 1
        print(f"=== scan {count} ===")
        snapshot = _collect(workspace)
        slate = GoalSynthesizer(client, settings).synthesize(snapshot)
        decisions = gate_slate(slate, settings)
        print(_render_table(slate, decisions))

    run_periodic(scan_once, args.interval, iterations=args.max_scans)
    return 0


def _cmd_diff(args: argparse.Namespace) -> int:
    """diff: classify goals across two saved slates (read-only, LLM-free).

    WHY it builds no ``LLMClient`` (like ``runs``/``explain``/``trace``/``signals``):
    it is a pure comparison of two persisted slates -- the comparative companion to
    ``watch``, turning a stream of point-in-time slates into a change feed. It
    re-gates each goal through the SAME ``gate(goal, settings)`` the ``dispatch``
    verb uses (via the shared ``_settings`` seam), matches by NORMALIZED TITLE (never
    the random per-scan ``id``), and classifies added/removed/changed + an unchanged
    count. It synthesizes nothing, runs no collector/subprocess, and writes no file.
    Exit codes mirror ``dispatch``/``explain``: a missing/non-file ``--old`` (checked
    FIRST) or ``--new`` returns ``2`` explicitly, before any exception; a corrupt or
    schema-invalid slate raises ``ValidationError``/``JSONDecodeError`` (a
    ``ValueError``) that the top-level ``main()`` boundary maps to one legible
    ``error:`` line at exit ``1`` -- no bespoke catch, no traceback. ``--json`` swaps
    the human sections for one machine-parseable object AFTER those guards, so the
    exit contract is ``--json``-independent -- rendering selection only.
    """
    old_path = Path(args.old)
    if not old_path.is_file():
        print(f"error: slate file not found: {old_path}", file=sys.stderr)
        return 2
    new_path = Path(args.new)
    if not new_path.is_file():
        print(f"error: slate file not found: {new_path}", file=sys.stderr)
        return 2

    old_slate = _load_slate(old_path)
    new_slate = _load_slate(new_path)

    settings = _settings(args)
    result = _compute_diff(old_slate, new_slate, settings)
    if args.json:
        # The ENTIRE stdout must parse as one JSON object; no human trailer. Both
        # guards above (exit 2 / exit 1) already ran, so --json selects a rendering
        # only and leaves the exit-code contract untouched. `old`/`new` echo the
        # raw arg strings (behavior 12), not the normalized Path.
        print(json.dumps(_diff_json_payload(args.old, args.new, result), indent=2))
    else:
        print(_render_diff(result))
    return 0


def _cmd_policy(args: argparse.Namespace) -> int:
    """policy: print the STANDING autonomy contract (read-only, LLM-free, zero-input).

    WHY it builds no ``LLMClient`` and reads no workspace (like
    ``runs``/``explain``/``trace``/``signals``/``diff``): the autonomy contract is
    the headline safety claim, yet today it is only inspectable REACTIVELY --
    ``explain`` shows ONE gated goal, ``scan`` shows a whole gated slate, and both
    demand a synthesized slate (an LLM call + a workspace). ``policy`` is the
    standing "what ARE the rules?" window: a zero-input, zero-LLM, zero-workspace
    catalog of the gate itself -- the top of the decision arc policy (rules) ->
    scan (proposals) -> explain (why THIS goal) -> trace (what it did).

    It builds ``settings`` through the SHARED ``_settings(args)`` seam so a
    ``PLA_AUTO_DISPATCH_MIN_SCORE`` override surfaces the EFFECTIVE threshold, and
    NOTHING else: no ``create_client`` (so an inert/bad ``--scripted-responses``
    path is simply never opened -- exit 0, not the eager-load exit 1 a
    client-building verb would give), no collector, no filesystem, no gate
    mutation. So it structurally cannot regress any existing behavior. It always
    returns 0; ``--json`` swaps the human catalog for one explicit-allowlist object
    (rendering selection only -- there is no input to fail on).
    """
    settings = _settings(args)
    if args.json:
        # The ENTIRE stdout must parse as one JSON object; no human trailer.
        print(json.dumps(_policy_json_payload(settings), indent=2))
    else:
        print(_render_policy(settings))
    return 0


if __name__ == "__main__":  # pragma: no cover - module entry convenience
    raise SystemExit(main())
