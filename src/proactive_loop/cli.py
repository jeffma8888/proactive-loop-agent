"""Command-line entry point (L2 orchestration surface).

WHY a thin CLI over the library layers: every capability the CLI exposes already
lives in a tested module (collectors, scout, loop). This file only *wires* them
into fifteen verbs a person actually runs -- scan, dispatch, run, resume, the
runs lister (read-only except on its opt-in ``--prune --yes`` retention
path), the read-only explain auditor, the read-only trace
transcript renderer, the read-only signals perception inspector, the periodic
watch loop, the read-only diff slate-delta inspector, the read-only policy
autonomy-contract catalog, the read-only tools sandbox-surface catalog, the
read-only collectors L2-perception catalog, the read-only providers
LLM-backend catalog, and the read-only config resolved-settings inspector --
and owns
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
import fnmatch
import html
import io
import json
import logging
import math
import os
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any, TextIO

from pydantic import ValidationError

from . import __version__
from .config import Settings
from .collectors import SIGNAL_KINDS, all_collectors
from .collectors import text_source
from .llm import LLMClient, LLMError
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
# The `watch --out-dir` slate-STREAM filename convention, defined here ONCE and
# nowhere else. WHY one definition instead of an inline f-string at the write
# site: the stream now has two sides -- `watch --out-dir` PRODUCES it and
# `diff --dir` CONSUMES it -- and a writer/reader disagreement about the prefix,
# the zero-pad width or the suffix would not raise anything: the reader would
# simply find no stream files and report an empty directory, the worst kind of
# silent drift. So the shape (`slate-001.json`: 1-based tick index, zero-padded
# to 3 so up to 999 ticks also sort lexicographically) lives in these three
# constants, and the only consumers are the two helpers directly below them --
# `_stream_slate_name` for the producer and `_stream_slate_index` for the reader.
_STREAM_SLATE_PREFIX = "slate-"
_STREAM_SLATE_PAD = 3
_STREAM_SLATE_SUFFIX = ".json"


def _stream_slate_name(index: int) -> str:
    """Format a 1-based tick *index* as its stream filename (the PRODUCER side).

    The single formatting site for the convention above, so `watch --out-dir`
    never restates the prefix/pad/suffix inline. Pure and total: an index wider
    than the pad simply renders unpadded (``1000`` -> ``slate-1000.json``), which
    stays readable by `_stream_slate_index` because that parses an integer of any
    width rather than a fixed-width field.
    """
    return f"{_STREAM_SLATE_PREFIX}{index:0{_STREAM_SLATE_PAD}d}{_STREAM_SLATE_SUFFIX}"


def _stream_slate_index(name: str) -> int | None:
    """Parse a stream filename back to its tick index, or ``None`` (the READER side).

    The exact inverse of `_stream_slate_name` over the same three constants, so
    the reader cannot recognise a shape the writer does not emit. Returns ``None``
    -- never raises -- for anything that is not a stream file, because a stream
    directory legitimately holds other entries (a plain ``slate.json`` from
    ``scan --out``, editor backups, notes) and those must be SKIPPED, not treated
    as errors.

    WHY ``isascii()`` guards ``isdigit()``: ``str.isdigit()`` is true for unicode
    digits, and ``int()`` then raises ``ValueError`` on some of them -- so the
    ASCII check is what keeps this total. It also rejects an empty body, since
    ``"".isdigit()`` is ``False``.
    """
    if not name.startswith(_STREAM_SLATE_PREFIX) or not name.endswith(_STREAM_SLATE_SUFFIX):
        return None
    body = name[len(_STREAM_SLATE_PREFIX) : -len(_STREAM_SLATE_SUFFIX)]
    if not (body.isascii() and body.isdigit()):
        return None
    return int(body)


# ---------------------------------------------------------------------------
# logging setup
# ---------------------------------------------------------------------------


class _CliLogHandler(logging.StreamHandler[TextIO]):
    """The single stderr handler the CLI attaches under ``-v``/``-vv``.

    WHY a dedicated subclass and not a bare ``StreamHandler``: it lets
    ``_configure_logging`` recognise *its own* handler by type and stay strictly
    idempotent -- re-invoking ``main()`` within one process (as the test suite
    does hundreds of times) must reuse this handler, never stack a second one on
    the package logger.

    WHY the base class carries an explicit ``[TextIO]`` parameter: under full
    ``strict`` mypy a bare generic base class is an error, and this handler only
    ever wraps ``sys.stderr`` (see ``_configure_logging``). It is also the ONE
    annotation in this file Python evaluates EAGERLY -- a base-class expression,
    not a lazily-stringified annotation -- so ``TextIO`` is a real runtime
    import; the subscript is verified to import on both CI Pythons (3.12, 3.13).
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


def _non_negative_int(raw: str) -> int:
    """argparse ``type=`` validator: parse a NON-negative integer (``>= 0``).

    The integer sibling of ``_non_negative_float``, written for the ``signals``
    verb and its ``--fail-over N`` count budget. Like both neighbours it fires at
    PARSE time -- BEFORE the workspace is walked or any collector runs -- so a bad
    budget is a ``SystemExit(2)`` usage error with zero side effects: nothing is
    scanned and stdout stays empty, rather than a full listing followed by a late
    complaint. ``int(raw)`` lets a non-integer (e.g. ``abc``, or the float-shaped
    ``1.5``) raise ``ValueError``, which argparse itself converts into the exit-2
    usage error; a parsed ``value < 0`` raises ``ArgumentTypeError`` because a
    negative budget is unsatisfiable in the wrong direction -- no count can ever
    fall below it, so the gate would be armed and permanently red.

    WHY this exists instead of reusing ``_positive_int``: that validator rejects
    ``0``, and ``--fail-over 0`` is a legitimate STRICT mode ("fail if anything at
    all is reported"), not a degenerate view. WHY no non-finite guard -- the one
    thing ``_non_negative_float`` adds: ``int()`` cannot produce ``nan``/``inf`` at
    all (``int("nan")`` raises ``ValueError``), so the hole that validator was
    widened to close does not exist for integers.
    """
    value = int(raw)
    if value < 0:
        raise argparse.ArgumentTypeError(f"must be a non-negative integer (>= 0), got {value}")
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


def _finite_float(raw: str) -> float:
    """argparse ``type=`` validator: parse a FINITE float (any sign, any magnitude).

    Guards the ``--min-weight`` argument of the ``signals`` verb -- the LAST numeric
    CLI arg still declared with a bare ``type=float``. Like its siblings
    (``_positive_int``, ``_non_negative_float``) it fires at PARSE time -- BEFORE any
    collector runs -- so a bad value is a ``SystemExit(2)`` usage error with zero
    side effects. ``float(raw)`` lets a non-number (e.g. ``abc``) raise
    ``ValueError``, which argparse converts into the exit-2 usage error; a NON-finite
    value (``nan``/``inf``/``-inf``) raises ``ArgumentTypeError``.

    WHY reject non-finite (the CLI twin of the iter-40 ``--interval`` guard): every
    signal-weight comparison ``s.weight >= float("nan")`` and ``>= float("inf")`` is
    ``False``, so a fat-fingered ``--min-weight nan``/``inf`` silently filtered OUT
    every signal and printed ``(no signals collected)`` at exit 0 -- a degenerate
    empty result masquerading as success on a workspace that HAS signals. Rejecting
    non-finite at parse time turns that silent no-op into an honest usage error.

    WHY finite-ONLY and NOT range-guarded (contrast ``_non_negative_float``): unlike
    ``--interval`` (a negative sleep is nonsensical), a finite NEGATIVE
    ``--min-weight`` is a legitimate loose lower bound (a "show all" threshold) and a
    finite ``> 1.0`` value is a legitimate impossibly-high bound (an intentionally
    empty view), both accepted per SPEC §4.5. So this returns EVERY finite float
    unchanged -- negatives and large values included -- rejecting only the
    non-finite trio.
    """
    value = float(raw)
    if not math.isfinite(value):
        raise argparse.ArgumentTypeError(f"must be a finite number, got {value}")
    return value


def _nonempty_glob(raw: str) -> str:
    """argparse ``type=`` validator: a path glob that is not empty or whitespace-only.

    Guards the ``--exclude-path`` argument of the ``signals`` verb, and is the
    non-numeric sibling of ``_finite_float`` / ``_positive_int``: it fires at PARSE
    time -- BEFORE any collector runs -- so a bad pattern is a ``SystemExit(2)``
    usage error with zero side effects.

    WHY reject empty/whitespace-only rather than accept it as a no-op: an exclusion
    pattern's effect is not statically knowable in general (unlike ``--kind K`` paired
    with a different ``--fail-on-kind V``, which can be proven unreachable), so this
    validator can only catch the ONE case that is provably inert.
    ``fnmatch.fnmatchcase(anything, "")`` is ``False`` for every non-empty path, and a
    whitespace-only pattern cannot match a relpath either, so ``--exclude-path ''``
    would silently exclude NOTHING while reading -- in a hook or a CI step -- exactly
    like an armed filter. A shell that expands an unset variable
    (``--exclude-path "$VENDOR_DIR"``) produces precisely that, and the user would
    inherit a permanently un-narrowed view with no signal that anything was wrong.
    Returning the pattern UNCHANGED (no strip, no normalization) keeps the matcher's
    input verbatim: leading/trailing spaces are legal INSIDE a pattern that also has
    non-space characters, because a filename may legitimately contain them.
    """
    if not raw.strip():
        raise argparse.ArgumentTypeError(
            "must be a non-empty path glob (an empty or whitespace-only pattern "
            "could never match, so it would silently exclude nothing)"
        )
    return raw


def build_parser() -> argparse.ArgumentParser:
    """Assemble the ``pla`` parser with fifteen subcommands and shared globals.

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
        help="LLM provider: scripted (default, offline) | anthropic | openai | bedrock | ollama | groq | together",
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
        choices=["table", "json", "markdown", "csv", "html"],
        default="table",
        help=(
            "stdout rendering: table (default, human) | json (one JSON object, no "
            "trailer, pipes cleanly into jq) | markdown (paste-ready GFM table + trailer) "
            "| csv (RFC-4180 data stream, no trailer, opens in Excel / pandas.read_csv) "
            "| html (self-contained escaped HTML table, no trailer, opens in a browser)."
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
    # An UPSTREAM allowlist on WHICH collectors feed synthesis -- the perception
    # INPUT knob, complementing --top/--format (which shape the OUTPUT view only).
    # Repeatable (action="append"); absent (default None) = all collectors, so a
    # bare scan is byte-identical to no flag. choices are derived from the LIVE
    # registry via all_collectors() (NOT a hardcoded literal) so the allowlist can
    # never drift from the collector set; an unknown name is a PARSE-time usage
    # error (exit 2) naming the bad choice and listing valid ones -- no client
    # built, no collection run, no slate written -- mirroring the --format/--top
    # fail-fast discipline. scan-only (run/signals/watch are unchanged).
    p_scan.add_argument(
        "--collector",
        action="append",
        default=None,
        choices=sorted(c.name for c in all_collectors()),
        dest="collector",
        metavar="NAME",
        help=(
            "Restrict synthesis to only the named collector(s); repeatable "
            "(--collector todos --collector git_state). Accepted values are the "
            "live collector names; an unknown name is a usage error (exit 2). "
            "Default (absent) runs all collectors."
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
    p_run.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Preview only: scan + gate + write the slate, print the single goal "
            "`run` WOULD auto-dispatch (with a paste-ready `pla dispatch` command), "
            "then STOP before executing the loop -- no run dir, no loop iteration."
        ),
    )
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
        help=(
            "List past dispatched runs under the state dir (LLM-free; read-only "
            "unless you opt into --prune --yes, which deletes the runs it lists)."
        ),
    )
    p_runs.add_argument(
        "--json",
        action="store_true",
        help="Emit the run list as a JSON array instead of the human table.",
    )
    p_runs.add_argument(
        "--status",
        default=None,
        dest="status",
        metavar="STATUS",
        # Choices are derived from the LIVE RunStatus enum (not a hardcoded
        # literal) so they can never drift from the statuses runs actually persist.
        choices=sorted(s.value for s in RunStatus),
        help=(
            "Narrow the listing to runs whose persisted status equals STATUS "
            "(one of the RunStatus values). Composes with --json, --prune."
        ),
    )
    # The product's first retention operation (ROADMAP #123), and its first
    # destructive path outside the L1 sandbox -- so it is a FLAG on the existing
    # lister, not a new verb: `--prune` deletes exactly the set `runs` would have
    # listed, reusing --status as its selector, which makes "what will be deleted"
    # answerable by a read-only command the user already knows.
    p_runs.add_argument(
        "--prune",
        action="store_true",
        help=(
            "Delete the selected run dirs instead of listing them. DRY RUN BY "
            "DEFAULT: without --yes it reports what it WOULD remove, deletes "
            "nothing, and exits 0. Selection is the listing's own -- --status "
            "narrows it identically -- and composes with --json."
        ),
    )
    # Same "opt in to the consequential action" idiom as `dispatch --yes`, and
    # deliberately inert on its own: `runs --yes` without --prune still just lists.
    p_runs.add_argument(
        "--yes",
        action="store_true",
        help="Confirm the deletion for --prune (inert without it); mirrors dispatch --yes.",
    )
    p_runs.set_defaults(func=_cmd_runs)

    # `explain` mirrors `dispatch`'s slate input but runs nothing: it inherits the
    # globals (so `--provider`/`--scripted-responses` are accepted but inert -- it
    # builds no LLMClient) and prints a full, LLM-free gate-decision audit. WITH
    # `--goal-id` it audits ONE goal; OMIT `--goal-id` and it audits the WHOLE slate
    # in ranked order (one block per goal / a JSON array), so a script or CI can
    # answer the slate-level safety question in one call. Only `--slate` is required;
    # `--goal-id` is optional (there is still no implicit "explain the top goal").
    p_explain = sub.add_parser(
        "explain",
        parents=[globals_],
        help="Audit gate decisions from a saved slate: one goal (--goal-id) or the whole slate (read-only, LLM-free).",
    )
    p_explain.add_argument("--slate", required=True, help="Path to a slate JSON from `scan`.")
    p_explain.add_argument(
        "--goal-id",
        required=False,
        default=None,
        help="Id of the goal to explain; omit --goal-id to audit every ranked goal in the slate.",
    )
    # Mirrors runs/trace/signals: a default-off boolean that swaps the human audit
    # block(s) for JSON. It is applied AFTER the exit-2/exit-1 guards in
    # _cmd_explain, so it selects a rendering only and never perturbs the exit-code
    # contract. Single-goal --json is ONE object; whole-slate --json is a JSON ARRAY.
    p_explain.add_argument(
        "--json",
        action="store_true",
        help="Emit the gate audit as JSON: one object for --goal-id, or a JSON array for the whole slate.",
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
    # view for one machine-parseable object; --kind narrows to one collector kind
    # (registry-validated, see below).
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
    # --kind is VALIDATED against the live signal-kind registry rather than left
    # free-form. Before this, an unknown kind was byte-identical to a genuinely
    # quiet workspace -- exit 0 plus `(no signals collected)` in the human view,
    # `[]` under --json, `total 0` under --summary -- so a typo read as "nothing
    # to see here" on the one surface whose entire job is reporting what was
    # perceived. `todos` is the natural typo, not a contrived one: the COLLECTOR
    # is named `todos` while the KIND is `todo` (same near-miss for notes/note,
    # git_activity/git_commit, filesystem/recent_file). choices= turns that into
    # a PARSE-time usage error (exit 2) that names the rejected value and lists
    # every accepted kind, before any collection runs, and it makes `signals
    # --help` enumerate the vocabulary -- which until now was learnable only by
    # reading src/. This also makes --kind consistent with --collector, the only
    # other value-taking filter here, which has always validated this way.
    # Deliberately NO metavar: the enumerated choices in --help ARE the reference.
    p_signals.add_argument(
        "--kind",
        default=None,
        choices=SIGNAL_KINDS,
        help=(
            "Show only signals of this collector-defined kind. Accepted values "
            "are exactly the live signal kinds (argparse enumerates them in "
            "braces); an "
            "unknown kind is a usage error (exit 2) at PARSE time, before any "
            "collection runs -- never a silently empty listing. Composes as a "
            "logical AND with --collector/--min-weight. This is an UPSTREAM "
            "filter like --collector, not a display-only one: only the "
            "collector that emits this kind is run, so --timings shows one "
            "row and the scan costs what that one collector costs. Default "
            "(absent) shows every kind."
        ),
    )
    p_signals.add_argument(
        "--min-weight",
        type=_finite_float,
        default=None,
        help=(
            "Show only signals whose relevance weight is >= this value (inclusive "
            "lower bound). Composes with --kind as a logical AND; omit for no "
            "threshold. The value must be FINITE: nan/inf/-inf are a usage error "
            "(exit 2), but a finite negative or > 1.0 value is accepted. A "
            "non-numeric value is also an argparse usage error (exit 2)."
        ),
    )
    # An UPSTREAM allowlist on WHICH collectors are inspected -- the perception
    # INPUT knob, complementing --kind/--min-weight (which narrow the OUTPUT view).
    # Repeatable (action="append"); absent (default None) = all collectors, so a
    # bare `signals` is byte-identical to no flag. choices are derived from the LIVE
    # registry via all_collectors() (NOT a hardcoded literal) so the allowlist can
    # never drift from the collector set; an unknown name is a PARSE-time usage
    # error (exit 2) naming the bad choice and listing valid ones -- no collection
    # runs. Verbatim structure of the scan --collector arg (row #71); this extends
    # the same knob to the perception inspector. run/watch still reject it.
    p_signals.add_argument(
        "--collector",
        action="append",
        default=None,
        choices=sorted(c.name for c in all_collectors()),
        dest="collector",
        metavar="NAME",
        help=(
            "Restrict inspection to only the named collector(s); repeatable "
            "(--collector todos --collector git_state). Accepted values are the "
            "live collector names; an unknown name is a usage error (exit 2). "
            "Composes as a logical AND with --kind/--min-weight. "
            "Default (absent) inspects all collectors."
        ),
    )
    # An AGGREGATE view knob (default off): the three prior knobs
    # (--kind/--min-weight/--collector) all FILTER the per-signal listing, but
    # there was no way to ask "how many of each KIND is this workspace
    # surfacing?" without eyeballing a long list. --summary swaps the listing
    # for a per-kind COUNT rollup (kind -> count + a trailing total) over the
    # SAME selected list, so it composes as a logical AND with the filters and
    # never changes WHICH signals are selected -- only how they are rendered.
    p_signals.add_argument(
        "--summary",
        action="store_true",
        help=(
            "Print a per-kind COUNT rollup (kind -> count, plus a trailing "
            "total) of the selected signals instead of the per-signal listing. "
            "Composes with --kind/--min-weight/--collector (same selection). "
            "With --json emits one {workspace_root, summary, total} object; "
            "otherwise a human count table (kinds ascending, 'total N' last)."
        ),
    )
    # The product's FIRST enforcement knob, and the reason it lives here: every
    # other flag on this verb changes WHAT IS PRINTED, so `signals` could report a
    # committed `.env` and still exit 0 -- byte-identical, to a pre-commit hook or a
    # CI step, to a pristine tree. Exit status is the only channel those callers can
    # read, so gating had to be an exit-code change, not a rendering change.
    # Repeatable (action="append") with OR semantics; choices come from the LIVE
    # SIGNAL_KINDS registry (never a literal) so an unknown kind is a PARSE-time
    # usage error (exit 2) before any collection runs -- the same contract --kind
    # already has, and deliberately NO metavar so the enumerated choices in --help
    # ARE the reference. The gate reads the SELECTED signals (post
    # --kind/--min-weight/--collector narrowing), so the exit status can never
    # disagree with the listing the user just read, and its one report line goes to
    # STDERR (the --timings precedent): stdout stays byte-identical with and without
    # the flag, so a --json pipeline keeps parsing as exactly one object.
    p_signals.add_argument(
        "--fail-on-kind",
        action="append",
        default=None,
        choices=SIGNAL_KINDS,
        dest="fail_on_kind",
        help=(
            "Exit 5 instead of 0 when the REPORTED signals include at least one "
            "signal of this kind -- the gate for a pre-commit hook or a CI step. "
            "Repeatable, and trips if ANY named kind is present (--fail-on-kind "
            "secret_file --fail-on-kind todo). Accepted values are exactly the "
            "live signal kinds (argparse enumerates them in braces); an unknown "
            "kind is a usage error (exit 2) at PARSE time, before any collection "
            "runs. It gates on what the view REPORTS, so --kind/--min-weight/"
            "--collector narrowing that removes every signal of the named kind "
            "exits 0; combining --kind K with a different --fail-on-kind V is a "
            "usage error (exit 2), since that gate could never fire. STDOUT is "
            "byte-identical with and without this flag -- the only added output "
            "is one 'gate: fail-on-kind tripped -- <kind>=<count>' line on STDERR."
        ),
    )
    # The THIRD ratchet, and the only one that structurally cannot rot. --fail-on-kind
    # gates on kind PRESENCE, so it is red on the first invocation of any repo that
    # already has findings -- every kind whose correct value is not zero (todo,
    # git_commit, note, ...) -- and the only escape so far, --baseline, needs a
    # COMMITTED snapshot whose refresh rule nobody owns, so the file quietly decays
    # into a blindfold. A count budget is one integer in a Makefile or a hook: no
    # file, no snapshot, no refresh rule, and it is the shape a user reaches for
    # first ("do not let the TODO count exceed 30").
    #
    # STRICTLY greater than, deliberately: N is the budget the caller is allowed to
    # spend, so count == N is inside it and only N+1 fails. Typed with
    # _non_negative_int rather than _positive_int because --fail-over 0 is a real
    # STRICT mode, not a degenerate one. Counted DOWNSTREAM over the shared
    # _select_signals predicate like every other surface, so it changes what is
    # REPORTED and never what RUNS (--timings rows are untouched) and the exit status
    # can never contradict the listing.
    #
    # Declared immediately after its SIBLING GATE and well before --timings, for two
    # reasons. The two exit gates now read as a pair, ahead of the two display
    # filters and the cost knob (the same grouping rule the --exclude-path comment
    # below states). And the slot between --baseline and --timings is TAKEN: the
    # shipped tests/test_iter138_behavior.py asserts the literal
    # "[--baseline FILE] [--timings]" in the rendered usage line, so any flag
    # inserted there splits a pinned pair -- a new selection knob goes ABOVE
    # --baseline, never between it and --timings.
    p_signals.add_argument(
        "--fail-over",
        default=None,
        type=_non_negative_int,
        metavar="N",
        dest="fail_over",
        help=(
            "Exit 5 instead of 0 when the number of REPORTED signals is STRICTLY "
            "GREATER than N -- the count budget that makes a gate usable on a repo "
            "that already has findings, with no snapshot file to keep fresh "
            "(--fail-over 30 stays green at 30 TODOs and fails the 31st). The "
            "boundary is strict, so a count EQUAL to N exits 0. N must be a "
            "non-negative integer: 0 is the legitimate strict mode (any reported "
            "signal fails), while a negative or non-integer budget is a usage "
            "error (exit 2) at PARSE time, before anything is scanned. It counts "
            "what the view REPORTS, so it composes as a logical AND with "
            "--kind/--min-weight/--collector/--exclude-path/--baseline and a "
            "filter that hides signals lowers the count. Unlike --fail-on-kind, "
            "pairing --kind K with --fail-over N is NOT a usage error: an "
            "unreachable KIND gate is statically provable, an unreachable COUNT "
            "budget is not, so there is nothing to refuse -- the gate simply reads "
            "the narrowed count. STDOUT is byte-identical with and without this "
            "flag; the only added output is one 'gate: fail-over tripped -- "
            "count=<count> budget=<N>' line on STDERR, and when the --fail-on-kind "
            "gate trips as well only that line prints, because it names WHICH kind."
        ),
    )
    # Declared BEFORE --timings on purpose: argparse renders the choices brace-list
    # into the usage line, and tests/test_iter112_behavior.py reads a fixed-width
    # window of `signals --help` starting at the first `--timings` token, so a long
    # enumeration inserted after it pushes the text that guard looks for out of
    # range. Grouping also reads better: this is a selection-driven knob like
    # --kind/--min-weight, while --timings (the cost instrument) stays last.
    # The verb's FIRST location-aware selection axis: every knob above selects by
    # KIND, COLLECTOR or WEIGHT, so on a stranger's repo one vendored, generated or
    # fixture tree could dominate the listing with no remedy but re-running at a
    # narrower --workspace -- which also throws away every repo-level signal (those
    # carry path "."). It is also the missing half of --fail-on-kind: that gate is
    # all-or-nothing per REPOSITORY, so one committed .env inside a test fixture makes
    # an exit-5 pre-commit hook permanently red and the only escape was dropping the
    # whole kind, i.e. turning the gate off. Exclusion is the narrow escape hatch that
    # keeps the gate armed everywhere else.
    #
    # EXCLUSION-only, deliberately NOT a matched --path/--exclude-path pair:
    # include-scoping is already served by --workspace. Repeatable (action="append")
    # with OR semantics, and applied DOWNSTREAM inside the shared _select_signals
    # predicate -- never upstream in _collect -- so it changes what is REPORTED and
    # never what RUNS (--timings rows stay identical) and the exit gate can never
    # contradict the listing.
    p_signals.add_argument(
        "--exclude-path",
        action="append",
        default=None,
        type=_nonempty_glob,
        metavar="GLOB",
        dest="exclude_path",
        help=(
            "Hide signals whose path matches this glob -- the escape hatch for a "
            "vendored, generated or fixture tree. Repeatable with OR semantics "
            "(--exclude-path 'vendor/*' --exclude-path '*.min.js'). Matching is "
            "CASE-INSENSITIVE on both sides, is anchored at the START of the path, "
            "and '*' CROSSES '/', so 'sub/*' hides the whole sub/ subtree but not "
            "top/sub/b.py -- an any-depth exclusion needs a leading '*' "
            "(--exclude-path '*node_modules/*'). A trailing ':LINE' suffix does not "
            "defeat the match, so 'notes.md', '*.md' and 'notes.md:12' all hide a "
            "TODO reported at notes.md:12. A signal with NO path (repo-level "
            "perception) is NEVER excluded, not even by '*'. Composes as a logical "
            "AND with --kind/--min-weight/--collector and narrows every surface "
            "identically (listing, --json, --summary, --summary --json) INCLUDING "
            "the --fail-on-kind exit gate; it is a display-side filter, so the "
            "--timings rows are untouched. An empty pattern is a usage error "
            "(exit 2)."
        ),
    )
    # The RATCHET knob, and the flag that makes --fail-on-kind usable on a repo that
    # already has findings. Every gated kind whose correct value is not zero
    # (todo, recent_file, git_commit, note, ...) is RED on its first invocation and
    # stays red, so the gate above could only be armed for the three kinds a healthy
    # workspace never emits -- the classic linter adoption wall, whose standard answer
    # is a baseline: record today, then fail only on what is NEW.
    #
    # CONSUME-ONLY on purpose: the user produces the file with `pla signals --json >
    # base.json` (the bring-your-own-file shape `dispatch --slate` already has), so
    # `signals` stays strictly read-only -- no --write-baseline, no state-dir cache.
    # It is the INSTANCE-suppression complement of --exclude-path's LOCATION
    # suppression, and neither substitutes for the other: one hides a vendored tree,
    # the other hides the 30 TODOs that were already there so the 31st is visible.
    # Applied DOWNSTREAM inside the shared _select_signals predicate, so it changes
    # what is REPORTED and never what RUNS (--timings rows are untouched) and the exit
    # gate can never contradict the listing. A malformed document is a usage error
    # BEFORE any collection (exit 2), not a silent "suppress nothing" -- a typo'd path
    # must not buy a green build. Declared BEFORE --timings for the same help-window
    # reason --exclude-path is (see that comment).
    p_signals.add_argument(
        "--baseline",
        default=None,
        metavar="FILE",
        dest="baseline",
        help=(
            "Hide every signal already recorded in FILE, a document you saved "
            "earlier with `pla signals --json` -- so the listing and the "
            "--fail-on-kind gate report only what is NEW since that snapshot. A "
            "signal's identity is the six published keys (source, kind, summary, "
            "detail, path, weight); extra keys are ignored, and differing in ANY "
            "one key (including weight) makes it a different signal. Suppression "
            "is set-based, so one baseline entry hides every live signal matching "
            "it. It narrows every surface identically (listing, --json, --summary, "
            "--summary --json) INCLUDING the exit gate, and composes as a logical "
            "AND with --kind/--min-weight/--collector/--exclude-path; being a "
            "display-side filter it leaves --timings untouched. STALENESS FAILS "
            "TOWARD REPORTING: a baseline entry that no longer matches produces "
            "noise, never a missed finding. An empty signals array is valid and "
            "suppresses nothing. A missing or malformed baseline "
            "(not JSON, not an object, no 'signals' array -- what a "
            "--summary --json document looks like -- or an entry missing one of "
            "the six keys) is a usage error (exit 2) reported before anything is "
            "scanned. Default (absent) hides nothing."
        ),
    )
    # A COST knob, and the only one here that writes to stderr. Everything else on
    # this verb answers "what did the collectors see?"; --timings answers "what did
    # looking cost, and which collector spent it?" -- the one dimension the product
    # had no instrument for, which mattered because `watch` re-runs this exact
    # collect on every tick. Opt-in (default off) and stderr-only BY DESIGN: a
    # duration is non-deterministic, so it must never enter the stdout contracts
    # (human listing / --summary rollup / --json object) that tests and jq
    # pipelines compare byte for byte. It is added to `signals` alone, not to
    # scan/run/watch: `signals` builds no LLMClient, so what it measures is pure
    # perception cost, unpolluted by synthesizer time -- while _collect's sink is
    # already general enough for those verbs to adopt later.
    p_signals.add_argument(
        "--timings",
        action="store_true",
        help=(
            "Also print a per-collector wall-clock cost table to STDERR (name, "
            "elapsed ms, signal count, plus a TOTAL row) in registry order. "
            "Opt-in; stdout is byte-identical with and without this flag, so it "
            "is safe to add to a piped or --json invocation. Rows reflect which "
            "collectors RAN, so the UPSTREAM filters shrink the row set "
            "(--collector directly, --kind through the collector that emits "
            "that kind) while the display-only filters (--min-weight, "
            "--summary) leave it untouched."
        ),
    )
    p_signals.set_defaults(func=_cmd_signals)

    # `watch` wires scheduler.run_periodic into a user-facing verb: it re-runs the
    # SAME collect->synthesize->gate->render body every --interval seconds,
    # re-printing the ranked, gated slate as the workspace changes -- the
    # proactive-monitoring loop the product is named for. Unlike `scan` it is a
    # LIVE view BY DEFAULT: with --out-dir absent it writes NO slate file and
    # prints no `slate written:` trailer (a monitor tick's output is ephemeral,
    # not an artifact a later `dispatch` reads). --out-dir opts INTO persistence,
    # one file per tick, which is what makes the documented `watch` -> `diff`
    # change feed producible without hand-rolling two `scan --out` runs.
    # --max-scans bounds the run (default None = run until Ctrl-C, the
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
    p_watch.add_argument(
        "--out-dir",
        default=None,
        help=(
            "Persist each tick's slate as <DIR>/slate-<NNN>.json (1-based tick "
            "index, zero-padded to 3) and print a `slate written:` trailer per "
            "tick. Omitted (the default) keeps the live monitor ephemeral: no "
            "file, no trailer. Missing parents are created; an existing "
            "non-directory at DIR (or on its path) is a usage error (exit 2) "
            "before the first scan. Only a tick whose scan completed writes a "
            "file, so the stream feeds `pla diff --old ... --new ...` directly."
        ),
    )
    p_watch.set_defaults(func=_cmd_watch)

    # `diff` compares TWO saved slates and classifies goals as added/removed/
    # changed/unchanged -- the comparative companion to `watch`, turning a stream
    # of point-in-time slates into a change feed. Like runs/explain/trace/signals
    # it inherits the globals so --provider/--scripted-responses/--state-dir are
    # accepted but INERT: the handler builds no LLMClient, runs no collector, and
    # writes no file. TWO mutually exclusive selector modes: explicit paths (both
    # --old and --new) or --dir DIR, which resolves the two newest slates in a
    # `watch --out-dir` stream directory so the producer and this consumer compose
    # with no filename arithmetic. Neither --old/--new is argparse-`required`
    # (that would forbid --dir); the handler enforces "exactly one mode" itself so
    # a missing or conflicting selector is one `error:` line, still exit 2.
    # --json swaps the human sections for one machine-parseable object. It matches
    # goals by NORMALIZED TITLE, never the random per-scan id (an id-match reports
    # 100% churn per scan).
    p_diff = sub.add_parser(
        "diff",
        parents=[globals_],
        help="Compare two saved slates and classify goals as added/removed/changed (read-only, LLM-free).",
    )
    p_diff.add_argument(
        "--old",
        default=None,
        help="Path to the OLDER slate JSON from `scan`. Required unless --dir is given.",
    )
    p_diff.add_argument(
        "--new",
        default=None,
        help="Path to the NEWER slate JSON from `scan`. Required unless --dir is given.",
    )
    p_diff.add_argument(
        "--dir",
        default=None,
        help=(
            "Diff the two newest slates in a `pla watch --out-dir DIR` stream "
            "directory instead of naming paths: --new binds to the highest "
            "slate-<NNN>.json tick index present and --old to the second-highest "
            "(compared as integers, so 1000 beats 999). Entries that are not "
            "stream files are ignored. Mutually exclusive with --old/--new; fewer "
            "than two stream slates, or a DIR that is not an existing directory, "
            "is a usage error (exit 2)."
        ),
    )
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

    # `tools` prints the L1 ACT sandbox's action surface -- every registered tool,
    # its access class, and the read/write sandbox invariant -- with zero input:
    # no --workspace, no slate, no LLM. It is the L1 analogue of `policy`: where
    # `policy` catalogs the autonomy RULES, `tools` catalogs what a dispatched goal
    # can DO to the disk. It inherits the globals so --provider/--scripted-responses/
    # --state-dir are ACCEPTED but INERT (the handler builds no LLMClient, runs no
    # collector, opens no file -- the tool surface is static and context-free), so a
    # reviewer of this public repo can answer "what can a dispatched goal touch?"
    # WITHOUT running anything. It completes the transparency arc one layer at a
    # time: policy (autonomy rules) -> signals (L2 perception) -> tools (L1 action
    # surface) -> explain (why THIS goal) -> trace (what a run did). --json swaps the
    # human catalog for one explicit-allowlist object. Deliberately NO --workspace
    # and no positional argument.
    p_tools = sub.add_parser(
        "tools",
        parents=[globals_],
        help="Print the L1 sandbox tool surface: every tool, its access class, and the sandbox read/write invariant (read-only, LLM-free, no workspace).",
    )
    p_tools.add_argument(
        "--json",
        action="store_true",
        help="Emit the tool catalog as one JSON object instead of the human catalog.",
    )
    p_tools.set_defaults(func=_cmd_tools)

    # `collectors` prints the L2 PERCEPTION surface -- every registered context
    # collector plus a one-line description of what it perceives -- with zero
    # input: no --workspace, no signals, no LLM. It is the L2 analogue of `tools`
    # (the L1 action surface) and `policy` (the autonomy rules): where `signals`
    # REQUIRES a --workspace and only enumerates the signals that fired THERE,
    # `collectors` answers the prior, context-free question "what perceivers even
    # exist?" against the static collector SET. It inherits the globals so
    # --provider/--scripted-responses/--state-dir are ACCEPTED but INERT (the
    # handler builds no LLMClient, runs no collector, opens no file -- the catalog
    # is static and context-free), so a portfolio reader can answer "what does the
    # proactivity layer look at?" WITHOUT a workspace or an LLM. It is the FRONT
    # DOOR of the transparency arc: collectors (what perceivers exist) -> signals
    # (raw output for a workspace) -> scan (proposals) -> explain (why THIS goal)
    # -> trace (what a run did). --json swaps the human catalog for one
    # explicit-allowlist object. Deliberately NO --workspace and no positional arg.
    p_collectors = sub.add_parser(
        "collectors",
        parents=[globals_],
        help="Print the L2 perception surface: every registered context collector and a one-line description of what it perceives (read-only, LLM-free, no workspace).",
    )
    p_collectors.add_argument(
        "--json",
        action="store_true",
        help="Emit the collector catalog as one JSON object instead of the human catalog.",
    )
    # --kind is the REVERSE lookup of the newly published kind column: "which
    # collector emits this signal kind?". Its vocabulary is `SIGNAL_KINDS`, the
    # SAME closed set `signals --kind` validates against, so the two verbs accept
    # exactly one token vocabulary and an unknown value is a PARSE-time usage error
    # (exit 2) that enumerates the accepted kinds. Deliberately NOT widened to also
    # accept collector NAMES: names are already the leading column, and admitting
    # both vocabularies here would teach the very name/kind conflation this row
    # exists to fix. Because name <-> kind is a bijection onto `SIGNAL_KINDS`, a
    # validated value always selects exactly one collector -- never an empty list.
    # Deliberately NO metavar: the enumerated choices in --help ARE the reference.
    p_collectors.add_argument(
        "--kind",
        default=None,
        choices=SIGNAL_KINDS,
        help=(
            "Show only the collector that emits this signal kind (the reverse of "
            "the kind column). Accepted values are exactly the live signal kinds "
            "(argparse enumerates them in braces) -- the same vocabulary "
            "`signals --kind` takes, so an unknown kind is a usage error (exit 2) "
            "at PARSE time. Note a collector NAME is not always a kind (`todos` "
            "emits `todo`). Default (absent) lists every collector."
        ),
    )
    p_collectors.set_defaults(func=_cmd_collectors)

    # `providers` prints the L0 LLM-BACKEND surface -- every accepted provider
    # (`VALID_PROVIDERS`), its offline/cloud kind, the pip package that fulfils it
    # (or none for the built-in `scripted` client), and a one-line description --
    # with zero input: no --workspace, no slate, no LLM. It is the L0 /
    # provider-abstraction analogue of `policy` (L2 autonomy rules), `collectors`
    # (L2 perception), and `tools` (L1 action surface): the FOURTH architectural
    # seam, until now the only one with no catalog window (the provider surface was
    # discoverable only by reading SPEC or by picking a provider and hitting the
    # reactive missing-SDK error). It inherits the globals so --provider/
    # --scripted-responses/--state-dir are ACCEPTED but INERT (the handler builds no
    # LLMClient -- so a bad --provider is never validated and an inert/nonexistent
    # --scripted-responses is never opened, exit 0 not the eager-load exit 1 --
    # resolves no settings, runs no collector, and opens no file), so a reviewer of
    # this public repo can answer "what can I run against, and what do I pip install
    # for each?" WITHOUT running anything. --json swaps the human catalog for one
    # explicit-allowlist object. Deliberately NO --workspace and no positional arg.
    p_providers = sub.add_parser(
        "providers",
        parents=[globals_],
        help="Print the LLM provider backends: every accepted provider, its offline/cloud kind, and the pip package to install (read-only, LLM-free, no workspace).",
    )
    p_providers.add_argument(
        "--json",
        action="store_true",
        help="Emit the provider catalog as one JSON object instead of the human catalog.",
    )
    p_providers.set_defaults(func=_cmd_providers)

    # `config` prints the fully-RESOLVED effective ``Settings`` -- every field
    # after ``PLA_*`` env vars AND the CLI globals (--provider/--state-dir/...) are
    # folded in through the shared ``_settings`` seam. It is the RUNTIME-CONFIG
    # window of the transparency arc: where `policy` catalogs the autonomy RULES,
    # `collectors`/`tools`/`providers` catalog the three architectural seams, and
    # `signals` shows a workspace's perceived input, `config` answers the prior
    # question "what settings will the agent actually run with?" -- the natural
    # companion to the README's PLA_* env-var table. It inherits the globals so
    # --provider/--scripted-responses/--state-dir are folded into the resolved
    # view; unlike a client-building verb it builds NO ``create_client`` (so a
    # provider that would need an SDK is simply reflected, never validated -- exit
    # 0, not the eager-load exit 1), runs no collector, and touches no filesystem.
    # --json swaps the human listing for one explicit-allowlist object. Deliberately
    # READ-ONLY: it only READS/prints the resolved settings, never a --set write
    # mode, and it prints only declared ``Settings`` fields (which hold no secret),
    # never raw ``os.environ``.
    p_config = sub.add_parser(
        "config",
        parents=[globals_],
        help="Print the fully-resolved effective settings after PLA_* env vars and CLI globals are applied (read-only, LLM-free, no workspace).",
    )
    p_config.add_argument(
        "--json",
        action="store_true",
        help="Emit the resolved settings as one JSON object instead of the human listing.",
    )
    p_config.set_defaults(func=_cmd_config)

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
    * ``5`` -- a requested gate tripped on a finding: the command ran fine and
      reported what it perceived, but a ``--fail-on-kind`` gate the caller armed
      matched at least one reported signal. Distinct from ``1`` (the tool itself
      failed) and from ``2`` (nothing to act on / bad invocation) -- this is the
      *finding* channel a pre-commit hook or CI step branches on.

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


def _workspace_path_bases(workspace: Path) -> tuple[Path, ...]:
    """The prefixes a signal path may legitimately carry for *workspace*, in strip order.

    Two of them, because the collectors compose ``path`` two different ways and BOTH
    are live: the content collectors publish a path already relative to the workspace
    (``todo``/``note``/``syntax_error``/``merge_conflict``), while the rest prefix
    whatever string the caller passed as the workspace (``str(root / rel)``). The
    workspace AS GIVEN is tried first, so the exact lexical prefix those collectors
    built is stripped without asking the filesystem anything; the ABSOLUTIZED form is
    tried second, which is what catches an absolute signal path published under a
    relative workspace (and, at ``--workspace .``, the whole absolute family).

    Deliberately LEXICAL (``os.path.abspath``, never ``Path.resolve``): resolving would
    stat the filesystem once per signal AND would make the published spelling depend on
    symlinks (on macOS ``/tmp`` -> ``/private/tmp``), i.e. on the host rather than on
    the input. A perception layer whose output key varies by host is not one a user can
    check into git, which is the whole point of normalizing here.
    """
    bases = [workspace]
    absolute = Path(os.path.abspath(workspace))
    if absolute != workspace:
        bases.append(absolute)
    return tuple(bases)


def _relative_signal_path(bases: tuple[Path, ...], path: str) -> str:
    """*path* re-spelled relative to the workspace, its ``:LINE`` tail preserved.

    The workspace directory itself comes back as ``.`` (that is what
    ``PurePath.relative_to`` yields for an equal path), which is already the spelling
    the default ``--workspace .`` scan publishes for repo-level findings -- so the root
    scan does not move.

    Two rules, both load-bearing:

    * **The trailing ``:<digits>`` group is split off before relativizing and
      re-appended byte-for-byte**, so a ``todo`` path stays a ``PATH:LINE`` pair
      instead of having its line number eaten by path arithmetic. It reuses
      ``_PATH_LINE_SUFFIX``, the SAME regex ``_path_excluded`` strips with, so
      normalization and ``--exclude-path`` can never disagree about what a line
      suffix is.
    * **A path that is not under the workspace is returned UNCHANGED** -- never an
      ``os.path.relpath``-style ``../..`` escape, and never an exception. Live
      example: ``working_tree`` publishes git-porcelain paths relative to the repo
      ROOT, which under a sub-directory workspace is an ancestor, not a descendant.
      Republishing those as ``../`` walks would invent a namespace that is neither
      the collector's nor the workspace's, so the honest answer is to leave the
      string alone; ``relative_to`` raising ``ValueError`` is the test for it.

      Observable consequence, and the exact BOUNDARY of this seam's guarantee: at a
      sub-directory workspace spelled ABSOLUTELY, no base matches the porcelain
      string, so ``working_tree`` keeps the repo-root spelling (``sub/pkg/mod.py``)
      while every workspace-resolved kind publishes ``pkg/mod.py`` for the SAME
      file; spelled RELATIVELY from the repo root the as-given base strips that
      prefix by lexical coincidence. So that one kind stays invocation-dependent,
      and it is the only one: ``git_activity`` publishes the directory itself,
      ``git_state``/``git_stash`` publish ``None``, and
      ``syntax_error``/``merge_conflict`` already relativize. Deliberately NOT
      fixed here -- the correct base is the repository root, which needs
      ``git rev-parse --show-toplevel`` I/O in a function whose contract is lexical,
      and that command returns a symlink-RESOLVED path (on macOS ``/var`` ->
      ``/private/var``), so it would also reintroduce exactly the host-dependence
      documented above. Owned by roadmap row #158.
    """
    match = _PATH_LINE_SUFFIX.search(path)
    body = path[: match.start()] if match else path
    suffix = match.group(0) if match else ""
    if not body:
        # A path that is nothing but a ``:LINE`` tail is not a location; leave it.
        return path
    for base in bases:
        try:
            relative = Path(body).relative_to(base)
        except ValueError:
            continue  # not under this base -- try the next spelling of the workspace
        # ``as_posix`` fixes the separator so the published key is identical on every
        # host, and ``Path`` has already collapsed a leading ``./`` for us.
        return relative.as_posix() + suffix
    return path


def _normalize_signal_paths(workspace: Path, signals: list[ContextSignal]) -> None:
    """Rewrite every non-null ``signal.path`` into ONE workspace-relative namespace.

    WHY this exists at all, and WHY here: ``path`` is a PUBLISHED key of every signal
    and two shipped features key on it -- ``--exclude-path`` filters by it and
    ``--baseline`` puts it inside the identity tuple that decides whether a finding is
    already known. With the collectors composing it two ways (see
    ``_workspace_path_bases``) the spelling depended on the workspace string the CALLER
    typed, so the two namespaces coincided only at ``--workspace .``: a baseline
    recorded from one checkout suppressed none of the prefixer family's findings in
    another, one ``--exclude-path`` glob narrowed the two families differently, and an
    absolute ``--workspace`` published ``/Users/<name>/...`` into a file the README
    invites the user to commit.

    WHY one seam instead of eight collectors: each collector would have to re-derive
    the same relativization, and any new collector could silently re-diverge. Here
    exactly one function owns the namespace, so "what does ``path`` mean" has one
    answer for every kind, present and future. The collectors keep publishing whatever
    is natural for them (an absolute path is the honest thing for a collector handed an
    absolute root, and ``LargeFileCollector`` is still unit-tested for exactly that);
    the SEAM owns what the user sees.

    Mutates in place rather than rebuilding the models: the list is freshly built by
    this scan and owned by the caller, so there is nothing else aliasing these
    objects, and a copy would double the allocation for a one-field rewrite. Note
    what is deliberately NOT touched -- ``path is None`` stays ``None`` (a repo-level
    finding has no location; ``.`` would be a lie and would also expose it to
    ``--exclude-path``), and ``WorkspaceSnapshot.root`` still records the workspace
    exactly as given, since that field's job is to say what was scanned.
    """
    bases = _workspace_path_bases(workspace)
    for signal in signals:
        if signal.path is None:
            continue
        signal.path = _relative_signal_path(bases, signal.path)


def _collect(
    workspace: Path,
    only: set[str] | None = None,
    timings: list[tuple[str, float, int]] | None = None,
) -> WorkspaceSnapshot:
    """Run every collector over *workspace* into one snapshot.

    The §4.1 contract is that collectors never raise (they degrade to ``[]``).
    This loop ENFORCES that invariant at the one orchestration seam behind every
    front-door verb (``scan``/``run``/``signals``/``watch``) rather than merely
    trusting it: each ``collect()`` call is isolated so a single collector that
    raises is logged at WARNING and contributes ``[]``, leaving the surviving
    collectors' signals intact instead of aborting the whole scan. A missing dir
    or absent git therefore still simply yields fewer signals.

    ``only`` is an optional UPSTREAM allowlist of collector names (from
    ``scan --collector`` and ``signals --collector``, and from ``signals --kind``,
    which resolves the kind to the collector that emits it): when not ``None``, a
    collector whose ``.name`` is not in the set is skipped entirely (its
    ``collect()`` never runs), so the caller can focus the scout on a subset of
    the perception surface. ``None`` (the default, what ``run``/``watch`` pass,
    and what ``signals`` passes when neither filter is given) runs every collector,
    byte-identical to before this knob existed; an empty set runs none. The
    filter is applied BEFORE the isolation try/except, so it changes only WHICH
    collectors run, never the never-raise / registry-order semantics of the
    ones that do.

    ``timings`` is an optional OUT-parameter sink for cost attribution (from
    ``signals --timings``): when a list is passed, exactly one
    ``(collector_name, elapsed_ms, signal_count)`` tuple is APPENDED per collector
    that actually ran, in registry order. It defaults to ``None`` -- measure
    nothing, append nothing -- which is what ``scan``/``run``/``watch`` pass, so
    the seam stays byte-identical to before this knob existed for every caller
    that does not ask for it. WHY an out-parameter instead of a second return
    value: the snapshot is this function's contract with four verbs and a wire
    schema, and widening it to a tuple would force every call site to change for
    a diagnostic that only one verb wants.

    This seam also OWNS the namespace of every published ``path``: after the loop,
    ``_normalize_signal_paths`` rewrites each non-null path to the POSIX path relative
    to *workspace* (the workspace itself spelled ``.``), preserving any ``:LINE`` tail.
    That is a spelling change only -- which signals are produced, in what order, and
    with what other fields is untouched, and at the default ``--workspace .`` the two
    namespaces already coincided, so the root scan is byte-identical. It lives here,
    not in the collectors, because ``path`` is a wire key that ``--exclude-path`` and
    ``--baseline`` both compare on: see ``_normalize_signal_paths`` for why one owner
    is the point.

    This seam also DEFINES the lifetime of the shared text cache: the collector
    loop runs inside one ``text_source.scan_scope()``, so a file the content
    collectors overlap on is read and decoded ONCE per scan and never held across
    scans. That is scoping only -- which signals are produced, in what order, and
    with what fields is byte-identical to before -- and it applies to every verb
    that scans through here, since they all share this one loop.
    """
    # Explicitly annotated: the `len(signals)` read below now precedes the first
    # `extend`, so mypy can no longer infer the element type from usage.
    signals: list[ContextSignal] = []
    # ONE shared read+decode per file for the whole scan. The three content
    # collectors (todos / merge_conflict / syntax_error) walk overlapping file
    # sets and each used to read them independently; inside this scope the first
    # one to reach a path pays the decode and the others are served the same
    # string. Wrapping the LOOP (not each collect() call) is what makes the
    # sharing cross-collector, and it is the only change here: `only=` filtering,
    # the never-raise isolation and the `timings` sink below are untouched. The
    # scope empties the cache on both edges even if a collector raises, so no
    # text ever survives a scan -- see collectors/text_source for why the
    # lifetime is exactly one scan.
    with text_source.scan_scope():
        for collector in all_collectors():
            if only is not None and collector.name not in only:
                continue
            started = time.perf_counter()
            before = len(signals)
            try:
                signals.extend(collector.collect(workspace))
            except Exception as exc:  # noqa: BLE001 - deliberate: contain a buggy collector
                # A raising collector VIOLATES the §4.1 "never raises -> []" contract,
                # so it is a bug IN THAT COLLECTOR. The orchestration layer's job is to
                # contain-and-surface it (log + skip), never propagate it and take down
                # every verb that shares this seam. Broad by design: any exception a
                # collector leaks must be isolated, not just a known subset.
                _LOG.warning("collector %r raised, skipping: %s", collector.name, exc)
            if timings is not None:
                # Recorded AFTER the try/except, so a collector that RAISED is still
                # timed and still gets a row -- a broken collector is exactly the one
                # whose cost you want attributed. Its containment WARNING is inside
                # the window by design: the row reports what this SEAM spent on that
                # collector, not an idealized inner duration.
                #
                # The count is the DELTA in the shared list, never len() of a captured
                # return value. That keeps the extend() call above VERBATIM (so a
                # generator that yields then raises still contributes what it yielded,
                # exactly as today) and makes the reconciliation invariant true by
                # construction: the per-collector counts always sum to the snapshot's
                # signal count, so the table can never quietly disagree with the
                # listing it annotates.
                timings.append(
                    (
                        collector.name,
                        (time.perf_counter() - started) * 1000.0,
                        len(signals) - before,
                    )
                )
    # One namespace for the published key, applied AFTER the loop so every collector
    # -- including any added later -- is normalized by construction, and BEFORE the
    # snapshot so no caller can ever observe the un-normalized form.
    _normalize_signal_paths(workspace, signals)
    return WorkspaceSnapshot(root=str(workspace), signals=signals)


def _write_slate(slate: GoalSlate, out: Path) -> None:
    """Persist the slate as pretty JSON atomically, creating parent dirs as needed.

    WHY temp sibling + ``os.replace`` (the same guarantee :class:`Checkpoint`
    documents for its own snapshot): a crash or kill mid-write must never leave a
    truncated slate behind. ``os.replace`` is atomic on the same filesystem, and
    writing the temp file as a SIBLING of *out* is what keeps the rename on that
    one filesystem, so a reader always sees either the previous slate or the
    complete new one -- never a half-written prefix.

    Load-bearing since ``watch --out-dir`` made this a PER-TICK writer: a
    watcher normally exits by Ctrl-C or a kill, and a truncated ``slate-NNN.json``
    would be rejected by the two readers of that stream (``diff``, ``explain``).
    """
    ensure_dir(out.parent)
    tmp = out.with_name(out.name + ".tmp")
    try:
        tmp.write_text(slate.model_dump_json(indent=2))
        os.replace(tmp, out)
    finally:
        # Best-effort cleanup so a failed swap cannot litter a user-chosen
        # ``--out-dir`` with a stray ``.tmp``; after a successful replace the temp
        # name is already gone, so one ``finally`` covers both paths. Cleanup
        # errors are swallowed deliberately: the caller must keep seeing the
        # PRIMARY OS error (the CLI ``error:`` boundary reports that one), never a
        # secondary failure raised while tidying up.
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


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


def _out_dir_guard(out_dir: Path) -> str | None:
    """Reject a ``watch --out-dir`` that cannot become a slate DIRECTORY (message-or-``None``).

    WHY a distinct helper rather than reusing ``_out_target_guard``: that guard is
    for a FILE target, so its first clause has the opposite polarity -- it
    REJECTS ``is_dir()``, which is exactly what a valid ``--out-dir`` is. What is
    shared is the failure MODE this pre-detects: without it, an existing
    non-directory only surfaces at the first tick's write, as a raw OS errno
    (``[Errno 17] File exists`` / ``[Errno 20] Not a directory``) leaked AFTER a
    successful-looking table was already printed and a live provider's budget
    already spent -- and on a long-lived watcher that mistake would repeat every
    tick. So the two structural failures are caught up front:
      * ``out_dir`` EXISTS but is not a directory (the ``_state_dir_guard``
        polarity: the slate files must live INSIDE it).
      * an EXISTING component of its parent chain is a NON-directory (a file
        sitting where a directory must be).
    A fully-absent path is LEGAL -- ``_write_slate`` creates parents on demand --
    so the deepest existing ancestor of an all-new path is a directory and the
    guard allows it. The ancestor walk provably terminates: ``/`` and ``.`` both
    always ``exists()``. Structural typing only (no ``os.access`` probe), keeping
    the guard deterministic and side-effect-free.
    """
    if out_dir.exists() and not out_dir.is_dir():
        return f"--out-dir is not a directory: {out_dir}"
    anc = out_dir.parent
    while not anc.exists():
        anc = anc.parent
    if not anc.is_dir():
        return f"--out-dir parent is not a directory: {anc}"
    return None


def _stream_slates(stream_dir: Path) -> list[Path]:
    """Every stream slate in *stream_dir*, oldest-first by PARSED INTEGER index.

    The reader half of the `watch --out-dir` stream, backing `diff --dir`: the
    caller takes the last two entries to diff the newest tick against the one
    before it.

    WHY ordering by the parsed int rather than by filename: the pad is only 3
    wide, so past 999 ticks a lexicographic sort inverts the pair
    (``slate-1000.json`` sorts BEFORE ``slate-999.json``) and `diff` would
    silently report the change feed backwards. The secondary sort on the name
    keeps the result deterministic if two names map to one index (``slate-1.json``
    beside ``slate-001.json``), because ``iterdir()`` order is OS-dependent.

    Non-stream entries are SKIPPED, never errors -- a stream directory legitimately
    holds other files -- and ``is_file()`` is checked so a DIRECTORY whose name
    happens to match the convention can never be selected and handed to a loader.
    """
    indexed: list[tuple[int, str, Path]] = []
    for entry in stream_dir.iterdir():
        index = _stream_slate_index(entry.name)
        if index is None or not entry.is_file():
            continue
        indexed.append((index, entry.name, entry))
    indexed.sort(key=lambda row: (row[0], row[1]))
    return [row[2] for row in indexed]


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
) -> dict[str, Any]:
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


# Inline CSS for the ``html`` format. Kept intentionally tiny and self-contained
# (no @font-face, no url(...), no external anything) so the rendered document
# opens offline with zero network -- the whole point of a shareable artifact. It
# must never contain the substrings ``http://``/``https://``/``<link``/``<script``
# (behavior 2 asserts their absence), so the style stays plain declarations only.
_HTML_STYLE = (
    "body { font-family: -apple-system, Segoe UI, Helvetica, Arial, sans-serif; "
    "margin: 2rem; color: #1a1a1a; }\n"
    "h1 { font-size: 1.25rem; margin-bottom: 1rem; }\n"
    "table { border-collapse: collapse; width: 100%; font-size: 0.95rem; }\n"
    "th, td { border: 1px solid #cccccc; padding: 0.4rem 0.6rem; "
    "text-align: left; vertical-align: top; }\n"
    "th { background: #f2f2f2; }\n"
    "tr:nth-child(even) td { background: #fafafa; }"
)


def _render_html(
    slate: GoalSlate, decisions: list[DispatchDecision], top: int | None = None
) -> str:
    """Render the ranked slate + gate outcome as one self-contained HTML document.

    A pure, disk-free function of ``(slate, decisions)`` -- like ``_render_table`` /
    ``_render_markdown`` / ``_scan_json_payload`` / ``_render_csv`` it consumes the
    SAME ``zip(slate.ranked(), decisions)``, so the HTML can never disagree with the
    other four formats on order, score, or gate outcome. Fixed 5-column shape
    (``#, decision, score, category, title``) matching every other format -- an
    ``id`` column is deliberately out of scope for cross-format consistency.

    WHY inline ``<style>`` + stdlib ``html.escape`` ONLY: the point of the ``html``
    format is a *shareable* artifact a non-terminal stakeholder can open in a browser
    or paste into a wiki/PR, so the document must be SELF-CONTAINED -- no external
    stylesheet/font/CDN/script (it opens offline) and no markup injection. Every
    dynamic cell (title, decision/category ``.value``) is routed through
    ``html.escape`` (default ``quote=True``, so a ``\"`` in a title becomes ``&quot;``);
    any synthesizer-produced title round-trips as visible text and can never break
    the table or smuggle a tag. ``html`` is stdlib, so the pydantic-v2-only runtime
    dependency rule is honored.

    An empty slate degrades to a well-formed document with the header table plus a
    single ``(no candidate goals)`` row (mirroring ``_render_table`` /
    ``_render_markdown``, NOT the bare data stream of ``csv`` / ``json`` -- ``html``
    is a rendered presentation format). Like those two the marker keys off the FULL
    ``slate.goals``, so it fires iff the WHOLE slate is empty, independent of ``top``.

    ``top`` caps the emitted DATA rows to the first N ranked pairs (identical slice
    discipline to the other renderers); ``None`` shows all. The persisted slate file
    is ALWAYS the complete record regardless of ``top`` (that write is ``_cmd_scan``'s
    job, not this pure renderer's). Returns the document with NO trailing newline; the
    caller ``print``s it, so stdout ends with exactly one ``\n`` after ``</html>``.
    """
    pairs = list(zip(slate.ranked(), decisions))
    if top is not None:
        pairs = pairs[:top]
    body_rows = [
        "    <tr>"
        f"<td>{rank}</td>"
        f"<td>{html.escape(decision.decision.value)}</td>"
        f"<td>{goal.score:.2f}</td>"
        f"<td>{html.escape(goal.category.value)}</td>"
        f"<td>{html.escape(goal.title)}</td>"
        "</tr>"
        for rank, (goal, decision) in enumerate(pairs, start=1)
    ]
    if not slate.goals:
        # Empty-slate marker: one row spanning all five columns whose text content is
        # exactly ``(no candidate goals)`` (behavior 9), mirroring table/markdown. It
        # keys off the FULL slate, so an empty slate always shows it regardless of top.
        body_rows = ['    <tr><td colspan="5">(no candidate goals)</td></tr>']
    return "\n".join(
        [
            "<!DOCTYPE html>",
            '<html lang="en">',
            "<head>",
            '<meta charset="utf-8">',
            "<title>Proactive goal slate</title>",
            "<style>",
            _HTML_STYLE,
            "</style>",
            "</head>",
            "<body>",
            "<h1>Proactive goal slate</h1>",
            "<table>",
            "  <thead>",
            "    <tr><th>#</th><th>decision</th><th>score</th>"
            "<th>category</th><th>title</th></tr>",
            "  </thead>",
            "  <tbody>",
            *body_rows,
            "  </tbody>",
            "</table>",
            "</body>",
            "</html>",
        ]
    )


def _render_run_summary(
    goal: CandidateGoal, state: RunState, run_dir: Path, tools: ToolRegistry
) -> str:
    """Human summary of a finished loop run: status, budget use, retries, artifacts.

    The ``retries`` line makes the product's headline "resilient by design"
    observable: it reports how many transient throttle/timeout blips the L0 layer
    silently recovered from during the run (0 for a clean run). The same line
    also reports ``parse errors`` -- how many malformed PLAN/CHECK replies the L1
    fail-safe absorbed -- so a post-mortem can tell throttle pressure apart from
    model garbage without re-reading the live ``L1 degraded `` WARNING stream.
    """
    lines = [
        "",
        f"dispatched : {goal.title}  (id={goal.id})",
        f"status     : {state.status.value}",
        f"iterations : {state.iterations_used}    llm calls: {state.llm_calls_used}",
        f"retries    : {state.retries}    parse errors: {state.parse_errors}",
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
    """Record the roots a `resume` needs (RunState alone lacks workspace_root).

    Written with the same temp-sibling + ``os.replace`` + ``finally``-cleanup
    idiom as :func:`_write_slate` and :class:`Checkpoint`, and for a sharper
    reason than either: this file is the ONLY record of ``workspace_root``, so a
    truncated ``meta.json`` costs a run its resumability even when the
    checkpoint written beside it is perfectly intact. Keeping the temp a SIBLING
    of the target holds the rename on one filesystem, where ``os.replace`` is
    atomic, so a reader sees either the previous metadata or the complete new
    file. The ``finally`` unlinks the temp -- best-effort, swallowing its own
    ``OSError`` so the PRIMARY failure is what reaches the caller -- because the
    run directory this writes into is a documented, user-visible layout that
    must not accumulate stray ``.tmp`` entries. Parent dirs are created on
    demand for parity with the sibling writers (the sole caller already creates
    the run dir, so that tolerance is idiom parity, not a live-bug fix).
    """
    ensure_dir(run_dir)
    path = run_dir / _META_NAME
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(
            json.dumps(
                {
                    "workspace_root": str(workspace_root),
                    "artifacts_dir": str(artifacts_dir),
                },
                indent=2,
            )
        )
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def _read_meta(run_dir: Path) -> dict[str, Any]:
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


def _run_row(run_dir: Path) -> dict[str, Any]:
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
        # Surface the two persisted resilience counters (ROADMAP #72) so a CI /
        # monitoring script can flag throttle- or garbage-pressured runs across a
        # whole fleet in one ``runs --json`` call, instead of shelling into each
        # run's human ``trace`` header. A degraded row (no/corrupt checkpoint ->
        # state is None) reports 0 for both, mirroring its ``"iterations": 0``.
        # ``_render_runs`` reads only its five named keys, so the human table
        # stays byte-identical; the additive keys are contract-compatible (the
        # runs --json test asserts ``issubset``, not an exact key set).
        "retries": state.retries if state is not None else 0,
        "parse_errors": state.parse_errors if state is not None else 0,
    }


def _select_prunable(state_dir: Path, status: str | None) -> tuple[list[Path], list[str]]:
    """Split *state_dir*'s run dirs into (deletable paths, refused names).

    The ONLY producer of paths that ``--prune --yes`` is allowed to delete, and
    the containment argument lives here rather than at the call site:

    * Candidates come from ``_iter_run_dirs`` alone, so a prunable path is by
      construction a DIRECT ``run-*`` child of *state_dir* -- never a nested
      ``state_dir/other/run-x``, never a plain file named ``run-x``, never a
      sibling of *state_dir*, and never a path built by string concatenation.
    * ``status`` reuses ``_run_row``'s persisted status, i.e. the exact value the
      listing prints, so prune can never select a run ``runs --status`` would not
      show. A degraded ``(no checkpoint)`` row matches no ``RunStatus`` value and
      is therefore excluded by any filter and included when none is given --
      inherited from the listing, not re-implemented.
    * Symlinks are REFUSED, not followed: ``_iter_run_dirs`` filters on
      ``is_dir()``, which follows links, so a symlinked ``run-evil`` IS listed
      today. ``shutil.rmtree`` on a symlink raises ``OSError``, and swallowing
      that would be strictly worse than declining it by name.

    WHY the symlink partition runs AFTER the status filter: "refused" means "we
    would have deleted this and chose not to", so a link the selector never
    selected is not reported as a refusal.

    Both lists inherit ``_iter_run_dirs``'s ascending-by-name order, which makes
    the report and the deletion order deterministic across invocations.
    """
    candidates = _iter_run_dirs(state_dir)
    if status is not None:
        candidates = [d for d in candidates if _run_row(d)["status"] == status]
    selected: list[Path] = []
    refused: list[str] = []
    for candidate in candidates:
        if candidate.is_symlink():
            refused.append(candidate.name)
        else:
            selected.append(candidate)
    return selected, refused


def _render_prune(names: list[str], *, dry_run: bool) -> str:
    """Render a prune report: a header plus one indented run-dir name per line.

    A pure function of already-sorted names -- same convention as
    ``_render_runs``, so the output is deterministic and testable without disk.
    The header is past tense only when something was actually removed, and the
    dry-run header carries its own escalation hint, so the safe default tells the
    reader how to make it act instead of leaving them to find the flag.
    """
    if not names:
        return "no runs to prune"
    header = (
        f"would prune {len(names)} run dir(s) (dry run -- re-run with --yes to delete):"
        if dry_run
        else f"pruned {len(names)} run dir(s):"
    )
    return "\n".join([header, *(f"  {name}" for name in names)])


def _render_runs(rows: list[dict[str, Any]]) -> str:
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
        f"    llm calls: {state.llm_calls_used}    retries: {state.retries}"
        f"    parse errors: {state.parse_errors}",
    ]
    if not state.steps:
        return "\n".join([*header, "(no steps recorded)"])
    return "\n".join([*header, *(_trace_step_line(step) for step in state.steps)])


# The ``:LINE`` tail a TODO-style signal appends to its path (``README.md:48``).
# ASCII ``[0-9]`` (not ``\d``, which also matches non-ASCII digits) and ``\Z`` (not
# ``$``, which would also match before a trailing newline) keep the strip exact.
_PATH_LINE_SUFFIX = re.compile(r":[0-9]+\Z")


def _path_excluded(path: str | None, patterns: list[str] | None) -> bool:
    """Does ``path`` match any ``--exclude-path`` glob? (the exclusion predicate).

    Pure, allocation-light and disk-free -- it never touches the filesystem, so it is
    unit-testable from strings alone and cannot depend on what happens to exist.

    Three load-bearing rules, each chosen against MEASURED signal paths:

    * **A path-less signal is NEVER excluded**, not even by ``'*'``. ``path is None``
      means repo-level perception (a git-activity or CI-config finding), and on this
      repo 16 of 75 live signals are repo-scoped. A path filter that silently dropped
      them would make ``--exclude-path`` lose findings that have nothing to do with
      the location the user was narrowing away.
    * **The pattern is matched against the verbatim path AND against the path with ONE
      trailing ``:<digits>`` group removed.** WHY: 30 of those 75 signals (every
      ``todo``, the single most numerous kind) carry a ``PATH:LINE`` path such as
      ``README.md:48``, and ``fnmatch.fnmatchcase("readme.md:48", "*.md")`` is
      ``False``. Matching only the whole value would ship a flag that silently misses
      TODOs -- a footgun, not a filter. Stripping the suffix makes ``'notes.md'``,
      ``'*.md'`` and ``'notes.md:12'`` all exclude ``notes.md:12``.
    * **Case-folded operands + ``fnmatchcase``** (never ``fnmatch.fnmatch``, which
      normalizes case through ``os.path.normcase`` and is therefore OS-dependent) --
      the same determinism convention ``find_files`` uses in ``loop/tools.py``, so
      results do not vary with the host filesystem's case sensitivity.

    Documented boundary, deliberately DIVERGING from ``find_files``' basename-only
    rule: the pattern is anchored at the START of the path and ``*`` crosses ``/``, so
    ``'sub/*'`` excludes the whole ``sub/`` subtree while ``'top/sub/b.py'`` survives
    it (an any-depth exclusion needs a leading ``*``). A basename match cannot express
    "exclude this subtree", which is the entire point of the flag.
    """
    if path is None or not patterns:
        return False
    candidates = {path.lower()}
    # ONE trailing :<digits> group, not a general split: a Windows-style drive letter
    # or a colon inside a filename must stay part of the path.
    candidates.add(_PATH_LINE_SUFFIX.sub("", path.lower()))
    return any(
        fnmatch.fnmatchcase(candidate, pattern.lower())
        for pattern in patterns
        for candidate in candidates
    )


# The six keys that DEFINE a signal on the wire, in the order ``_signals_json_payload``
# emits them. Named ONCE, here, because two sides read them: the live signals and a
# saved baseline document. A tuple (not a set) because an identity is ORDERED.
_SIGNAL_IDENTITY_KEYS: tuple[str, ...] = (
    "source",
    "kind",
    "summary",
    "detail",
    "path",
    "weight",
)


def _signal_identity(signal: ContextSignal | dict[str, object]) -> tuple[object, ...]:
    """The PUBLISHED identity of a signal: the tuple of its six wire-contract values.

    WHY one function accepts BOTH a live ``ContextSignal`` and a decoded baseline
    entry: ``--baseline`` compares what the collectors just perceived against what a
    saved ``signals --json`` document recorded, and those two sides can only be
    compared if they agree on WHICH keys participate and in WHAT ORDER. Two
    extractors -- one reading attributes, one reading dict keys -- would make that
    agreement a review promise; one function iterating one ``_SIGNAL_IDENTITY_KEYS``
    tuple makes it structural, so a key added to (or reordered in) the wire schema
    cannot desynchronize them. Same reasoning ``_select_signals`` gives for being
    extracted rather than repeated.

    Deliberately the SIX ``--json`` keys and never ``model_dump()``: ``timestamp`` is
    excluded from the wire schema (the iter-08 schema-leak lesson) and a wall-clock
    field could not match across two runs anyway, so including it would make every
    baseline entry dead on arrival. Values are compared AS DECODED, so JSON ``null``
    matches ``path=None`` and a JSON integer matches a float ``weight`` (``1 == 1.0``,
    and they hash equally); a wrong-TYPED value simply fails to match, which is the
    reporting-safe direction.

    Returns ``tuple[object, ...]`` on purpose: the baseline side is arbitrary decoded
    JSON, so annotating the elements ``str``/``float`` would be a claim this function
    does not check.
    """
    if isinstance(signal, dict):
        # Presence of every key is the loader's precondition, so a plain subscript is
        # right here -- a KeyError would be a loader bug, not bad user input.
        return tuple(signal[key] for key in _SIGNAL_IDENTITY_KEYS)
    return tuple(getattr(signal, key) for key in _SIGNAL_IDENTITY_KEYS)


def _load_signal_baseline(path: Path) -> set[tuple[object, ...]]:
    """Load a saved ``signals --json`` document into a SET of signal identities.

    The CONSUME half of ``--baseline``: the user produces the file themselves with
    ``pla signals --json > base.json`` -- the same bring-your-own-file shape
    ``dispatch --slate`` has -- so ``signals`` stays strictly read-only and this
    function only ever reads.

    A SET, not a list, for two reasons: suppression is SET semantics (one baseline
    entry hides EVERY live signal sharing its identity, so a workspace with two
    identical TODO lines needs one entry, not two), and membership stays O(1) over a
    workspace surfacing thousands of signals.

    FAIL-CLOSED on malformed input, mirroring the ``--fail-on-kind``-unreachable
    guard in ``_cmd_signals``: every case below raises ``ValueError`` carrying a
    ready-to-print message body, which the caller turns into ONE ``error: `` line on
    stderr plus exit 2 BEFORE any collector runs. The alternative -- treating an
    unreadable baseline as "suppress nothing" -- is quietly wrong in the direction
    that matters, because a hook author who typos the path would inherit a green
    build computed against a baseline that never loaded. The missing-``signals`` case
    is the realistic one: it is exactly what a ``--summary --json`` document saved by
    mistake looks like.

    Extra keys on an entry are IGNORED rather than rejected, so a document written by
    a future version that adds a field still loads -- only the six identity keys
    participate. Value TYPES are not checked (a string ``"0.5"`` weight loads and
    simply never matches): the schema contract enforced here is the six key NAMES.
    The one exception is structural rather than a type rule -- a JSON array or object
    as an identity value is UNHASHABLE, so the identity ``set`` cannot hold it, and it
    is rejected with the other malformed-input cases rather than escaping as a
    ``TypeError``.
    """
    if not path.is_file():
        raise ValueError(f"baseline file not found or not a regular file: {path}")
    try:
        raw = path.read_text()
    except UnicodeDecodeError as exc:
        # A ValueError subclass, so it would surface anyway -- re-raised only to
        # attach the path the vendor message omits.
        raise ValueError(f"baseline file is not valid UTF-8 text: {path}: {exc}") from None
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"baseline file is not valid JSON: {path}: {exc}") from None
    if not isinstance(document, dict):
        raise ValueError(
            f"baseline file must contain one JSON object: {path}: got "
            f"{type(document).__name__}"
        )
    entries = document.get("signals")
    if not isinstance(entries, list):
        raise ValueError(
            f"baseline file has no 'signals' array: {path}: expected a document saved "
            "by `pla signals --json` (a --summary --json document carries counts, "
            "not signals)"
        )
    baseline: set[tuple[object, ...]] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(
                f"baseline file entry signals[{index}] is not a JSON object: {path}"
            )
        missing = [key for key in _SIGNAL_IDENTITY_KEYS if key not in entry]
        if missing:
            raise ValueError(
                f"baseline file entry signals[{index}] is missing "
                + ", ".join(missing)
                + f": {path}"
            )
        try:
            baseline.add(_signal_identity(entry))
        except TypeError:
            # Present-but-unhashable (a JSON array or object where a scalar
            # belongs) is a STRUCTURAL fault, not the value-type checking this
            # loader keeps out of scope: the identity ``set`` cannot represent
            # such a value at all. So it fails closed with its sibling
            # malformed cases instead of escaping the narrow
            # (LLMError, ValueError, OSError) guard in main() as a raw traceback.
            raise ValueError(
                f"baseline file entry signals[{index}] has a JSON array or object "
                f"where a scalar value is expected: {path}"
            ) from None
    return baseline


def _select_signals(
    snapshot: WorkspaceSnapshot,
    kind: str | None = None,
    min_weight: float | None = None,
    exclude_paths: list[str] | None = None,
    baseline: set[tuple[object, ...]] | None = None,
) -> list[ContextSignal]:
    """The ONE selection predicate every ``signals`` surface shares.

    WHY it is extracted rather than repeated: the same ``kind`` exact match AND
    inclusive ``weight >= min_weight`` lower bound was written out verbatim in the
    four renderers/payload builders below, and it is now ALSO read by the
    ``--fail-on-kind`` gate in ``_cmd_signals``. The gate's contract is that the
    exit status can never disagree with the printed listing, which only holds
    structurally if the gate and the view compute selection from the same code --
    a second copy of the predicate would make that contract a review promise
    instead of a property. Returns a FRESH list on every call because
    ``_signals_json_payload`` sorts its result in place; the ORDERING stays with
    each caller on purpose (the two listing surfaces sort, the two summary
    builders do not, and hoisting a sort here would change stdout). Pure and
    disk-free: no file is opened and no client is built, so it is unit-testable
    from a synthetic snapshot. The ``--collector`` allowlist is NOT applied here --
    it is an UPSTREAM filter honored by ``_collect``, so it is already reflected in
    ``snapshot.signals``.

    ``exclude_paths`` (the ``--exclude-path`` globs) is the third clause and the
    first LOCATION-aware one: a signal is dropped when ``_path_excluded`` says its
    ``path`` matches ANY pattern (OR semantics; see that helper for the matching
    rules, including why a path-less signal always survives). It belongs HERE and
    nowhere else for the same structural reason the other two clauses do -- the gate
    must narrow with the view -- and it defaults to ``None`` (excludes nothing), so
    a bare ``signals`` invocation is byte-identical to before the flag existed.

    ``baseline`` (the ``--baseline`` document, pre-loaded into a set of identity
    tuples by ``_load_signal_baseline``) is the fourth clause and the first
    INSTANCE-aware one: a signal is dropped when its ``_signal_identity`` is already
    present in the set. It is the complement of ``exclude_paths``, not a substitute
    -- that one suppresses by LOCATION (hide a vendored tree), this one by INSTANCE
    (hide the 30 TODOs that were already there and report the 31st) -- which is what
    turns the ``--fail-on-kind`` gate from "no findings" into "no NEW findings" on a
    workspace that has any. It belongs HERE for the same structural reason the other
    three clauses do: the gate must narrow with the view. ``None`` (the default)
    suppresses nothing AND skips the identity computation entirely, so the no-flag
    path is byte-identical and costs nothing; an EMPTY set is valid and also
    suppresses nothing. Staleness fails toward REPORTING -- a baseline entry that no
    longer matches produces noise, never a missed finding.
    """
    return [
        s
        for s in snapshot.signals
        if (kind is None or s.kind == kind)
        and (min_weight is None or s.weight >= min_weight)
        and not _path_excluded(s.path, exclude_paths)
        and (baseline is None or _signal_identity(s) not in baseline)
    ]


def _render_signals(
    snapshot: WorkspaceSnapshot,
    kind: str | None = None,
    min_weight: float | None = None,
    exclude_paths: list[str] | None = None,
    baseline: set[tuple[object, ...]] | None = None,
) -> str:
    """Render the raw collector signals grouped by kind as plain text.

    A pure, disk-free, deterministic function of
    ``(snapshot, kind, min_weight, exclude_paths, baseline)`` -- like
    ``_render_runs`` / ``_render_trace`` it opens no files and builds no client, so
    the exact human view is reproducible from a synthetic snapshot alone. The
    optional ``kind`` narrows the view to one collector-defined kind, and the
    optional ``min_weight`` keeps only signals whose ``weight >= min_weight``
    (an INCLUSIVE relevance lower bound); the two filters compose as a logical
    AND over the same ``selected`` list that drives grouping/counts/ordering, so
    a threshold that excludes every signal (or a ``kind`` matching none) degrades
    to a single ``(no signals collected)`` marker rather than a bare or blank
    block. The optional ``exclude_paths`` globs subtract by LOCATION over that same
    list (``_path_excluded``, OR semantics, path-less signals always survive), so
    ``--exclude-path '*'`` degrades to the same marker. The optional ``baseline``
    set subtracts by INSTANCE over that same list (a signal whose
    ``_signal_identity`` a saved ``signals --json`` document already recorded is
    dropped), so a baseline covering everything degrades to the same marker too. Kind headers ``## <kind> (<count>)`` appear in ascending lexicographic
    order, and within each section signals are ordered by
    ``(source, summary, path or "")``
    so two renders of the same snapshot are byte-identical. ``weight`` is shown as
    ``w<value:.2f>`` (the JSON view keeps it a raw number); a signal's ``path`` is
    echoed verbatim after `` -> `` ONLY when present, so a path-less note carries
    no arrow. Header lines start with ``## `` and signal lines with two spaces, so
    the two are unambiguously distinguishable (a caller can count kinds by ``## ``).
    """
    selected = _select_signals(snapshot, kind, min_weight, exclude_paths, baseline)
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


def _signals_json_payload(
    snapshot: WorkspaceSnapshot,
    kind: str | None = None,
    min_weight: float | None = None,
    exclude_paths: list[str] | None = None,
    baseline: set[tuple[object, ...]] | None = None,
) -> dict[str, Any]:
    """Build the ``signals --json`` document as a pure function of inputs.

    Exactly two top-level keys -- ``workspace_root`` (== ``snapshot.root``) and
    ``signals`` (a FLAT array ordered by ``(kind, source, summary, path or "")``).
    Each signal is an EXPLICIT dict of exactly the six contract keys ``source,
    kind, summary, detail, path, weight`` -- never ``model_dump`` (the iter-08
    schema-leak lesson): the model's ``timestamp`` (and any field added later) is
    deliberately excluded so the wire schema stays a small, stable contract a
    ``jq`` pipeline can rely on. ``path`` is echoed as-is (JSON ``null`` when
    ``None``); ``weight`` stays a raw JSON number (the human view renders it
    ``w<value:.2f>``). The optional ``kind`` (exact match), ``min_weight``
    (inclusive ``weight >= min_weight`` lower bound), ``exclude_paths``
    (``--exclude-path`` globs, subtractive by LOCATION) and ``baseline`` (the
    ``--baseline`` identity set, subtractive by INSTANCE) compose as a logical AND
    over the same ``selected`` list. A filter matching nothing degrades to
    ``signals == []`` (NOT the human ``(no signals collected)`` marker), so the
    JSON is always one object -- an empty array, never prose. Mirrors the ``_scan_json_payload`` /
    ``_run_row`` explicit-dict convention; kept pure/disk-free so it is
    unit-testable without touching a workspace or a client.
    """
    selected = _select_signals(snapshot, kind, min_weight, exclude_paths, baseline)
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


def _render_signals_summary(
    snapshot: WorkspaceSnapshot,
    kind: str | None = None,
    min_weight: float | None = None,
    exclude_paths: list[str] | None = None,
    baseline: set[tuple[object, ...]] | None = None,
) -> str:
    """Render a per-kind COUNT rollup of the selected signals as plain text.

    The AGGREGATE twin of ``_render_signals``: where that groups and LISTS each
    signal, this collapses the same ``selected`` list to one ``"{kind}  {count}"``
    line per DISTINCT kind (kind, two spaces, the integer count) in ascending
    lexicographic kind order, followed by a final ``"total  {N}"`` line whose ``N``
    is the number of selected signals (== the sum of the per-kind counts). Like
    ``_render_signals`` it is a pure, disk-free, deterministic function of
    ``(snapshot, kind, min_weight, exclude_paths, baseline)`` -- it opens no file and builds no
    client -- and it reuses the EXACT same ``selected`` filter (``kind`` exact match
    AND inclusive ``weight >= min_weight`` AND not ``_path_excluded`` AND not
    already present in ``baseline``) so
    ``--summary`` never changes WHICH signals are
    counted, only how they are rendered; the ``--collector`` allowlist is applied
    upstream in ``_collect``. An empty selection (nothing collected, or the filters
    exclude everything) degrades to the SAME ``(no signals collected)`` marker the
    listing view uses -- and, deliberately, NO ``total`` line -- rather than an
    empty table. Deterministic by construction: kinds ascending, ``total`` last.
    """
    selected = _select_signals(snapshot, kind, min_weight, exclude_paths, baseline)
    if not selected:
        return "(no signals collected)"
    counts: dict[str, int] = {}
    for signal in selected:
        counts[signal.kind] = counts.get(signal.kind, 0) + 1
    lines = [f"{k}  {counts[k]}" for k in sorted(counts)]
    lines.append(f"total  {len(selected)}")
    return "\n".join(lines)


def _signals_summary_payload(
    snapshot: WorkspaceSnapshot,
    kind: str | None = None,
    min_weight: float | None = None,
    exclude_paths: list[str] | None = None,
    baseline: set[tuple[object, ...]] | None = None,
) -> dict[str, Any]:
    """Build the ``signals --summary --json`` document as a pure function of inputs.

    The machine twin of ``_render_signals_summary`` and the AGGREGATE analogue of
    ``_signals_json_payload``: EXACTLY three top-level keys -- ``workspace_root``
    (== ``snapshot.root``), ``summary`` (an object mapping each DISTINCT selected
    kind to its integer count, keys in ascending lexicographic order so the
    serialized document is deterministic), and ``total`` (the number of selected
    signals == the sum of the ``summary`` values). No ``signals`` array in summary
    mode. It reuses the SAME ``selected`` filter as ``_signals_json_payload`` (kind
    exact match AND inclusive ``weight >= min_weight`` AND not ``_path_excluded`` AND
    not already present in ``baseline``; the ``--collector`` allowlist is applied
    upstream in ``_collect``), so the counts
    are exactly consistent with the human table. An empty selection degrades to ``summary == {}`` / ``total ==
    0`` (never the human ``(no signals collected)`` marker, never a blank output) --
    the JSON is always one object. Kept pure/disk-free so it is unit-testable from a
    synthetic snapshot with no workspace or client.
    """
    selected = _select_signals(snapshot, kind, min_weight, exclude_paths, baseline)
    counts: dict[str, int] = {}
    for signal in selected:
        counts[signal.kind] = counts.get(signal.kind, 0) + 1
    return {
        "workspace_root": snapshot.root,
        "summary": {k: counts[k] for k in sorted(counts)},
        "total": len(selected),
    }



def _render_collector_timings(timings: list[tuple[str, float, int]]) -> str:
    """Render per-collector wall-clock cost as a plain-text table (stderr-bound).

    The cost twin of ``_render_signals``: where that reports WHAT was perceived,
    this reports what perceiving it COST, from the ``(name, elapsed_ms, count)``
    tuples ``_collect`` appended to its ``timings`` sink. A pure, disk-free
    function of that list alone -- no snapshot, no filters, no client -- so it is
    unit-testable and cannot disagree with the measurement it formats.

    Three deliberate shape decisions:

    * **Registry order, never sorted by duration.** The rows are emitted in the
      order ``_collect`` ran them, so the table lines up 1:1 with the seam's own
      loop and with ``pla collectors``. Sorting by cost would make the row ORDER a
      function of a non-deterministic measurement -- the one thing this repo's
      output contracts refuse to do.
    * **A ``TOTAL`` row, summed from the RAW floats** (not from the 2-decimal
      strings), so the total is the honest scan cost and the displayed rows differ
      from it by at most rounding.
    * **The row set reflects which collectors RAN**, so the UPSTREAM allowlists
      shrink it -- ``--collector`` directly, and ``--kind`` through the collector
      that emits that kind (an excluded collector never ran, so it has no cost to
      report) -- while the stdout display filters (``--min-weight``/``--summary``)
      leave it untouched.

    The caller writes this to STDERR: a duration is non-deterministic, and every
    ``signals`` stdout surface (human listing, ``--summary`` rollup, ``--json``
    object) is a byte-comparable contract that tests and ``jq`` pipelines assert
    on. Diagnostics belong on the other stream. Degenerate case (no collector
    ran at all -- an empty registry under test): header plus a ``TOTAL`` row of
    ``0.00  0``, keeping the "header, N rows, TOTAL" shape unconditional rather
    than adding a second empty-state format to reason about.
    """
    total_label = "TOTAL"
    # Width is derived from the actual names (not a fixed :<16 like
    # _render_collectors) because a test double or a future long collector name
    # must not glue the name column onto the number column. The two explicit
    # spaces between every pair of fields guarantee each row splits into exactly
    # three whitespace-separated fields no matter how wide a value gets.
    width = max([len(name) for name, _, _ in timings] + [len(total_label)])
    lines = ["collector timings (ms):"]
    lines.extend(
        f"  {name:<{width}}  {elapsed_ms:>9.2f}  {count:>5}"
        for name, elapsed_ms, count in timings
    )
    lines.append(
        f"  {total_label:<{width}}  {sum(t[1] for t in timings):>9.2f}  "
        f"{sum(t[2] for t in timings):>5}"
    )
    return "\n".join(lines)


def _explain_json_payload(
    goal: CandidateGoal, decision: DispatchDecision, settings: Settings
) -> dict[str, Any]:
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


def _compute_diff(old: GoalSlate, new: GoalSlate, settings: Settings) -> dict[str, Any]:
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

    added: list[dict[str, Any]] = []
    for key in sorted(new_index.keys() - old_index.keys()):
        goal = new_index[key]
        added.append(
            {
                "title": goal.title,
                "score": goal.score,
                "decision": gate(goal, settings).decision.value,
            }
        )

    removed: list[dict[str, Any]] = []
    for key in sorted(old_index.keys() - new_index.keys()):
        goal = old_index[key]
        removed.append(
            {
                "title": goal.title,
                "score": goal.score,
                "decision": gate(goal, settings).decision.value,
            }
        )

    changed: list[dict[str, Any]] = []
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


def _render_diff(result: dict[str, Any]) -> str:
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


def _diff_json_payload(old_path: str, new_path: str, result: dict[str, Any]) -> dict[str, Any]:
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


def _policy_json_payload(settings: Settings) -> dict[str, Any]:
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


def _config_json_payload(settings: Settings) -> dict[str, Any]:
    """Build the ``config --json`` document as a pure function of ``settings``.

    One object of an EXPLICIT key allowlist -- never ``settings.model_dump()`` (the
    iter-08 schema-leak discipline every ``*_json_payload`` follows): a field added
    later to ``Settings`` must NOT silently leak onto this wire schema, which a
    ``jq``/CI pipeline asserts on. The keys are EXACTLY the resolved-``Settings``
    surface ``{provider, model, scripted_responses_path, workspace_root, state_dir,
    auto_dispatch_min_score, sensitive_categories, max_iterations, max_llm_calls,
    retry}`` with ``retry`` nesting exactly its five knobs.

    Path-typed fields are emitted as strings (``None`` -> JSON ``null`` for an unset
    ``model``/``scripted_responses_path``); ``auto_dispatch_min_score`` is a raw JSON
    number (not the ``:.2f`` human string); ``sensitive_categories`` is a sorted list
    of category ``.value`` strings. Kept pure/disk-free and client-free so it is
    unit-testable without a workspace, a slate file, or an ``LLMClient``.
    """
    scripted = settings.scripted_responses_path
    return {
        "provider": settings.provider,
        "model": settings.model,
        "scripted_responses_path": str(scripted) if scripted is not None else None,
        "workspace_root": str(settings.workspace_root),
        "state_dir": str(settings.state_dir),
        "auto_dispatch_min_score": settings.auto_dispatch_min_score,
        "sensitive_categories": sorted(
            cat.value for cat in settings.sensitive_categories
        ),
        "max_iterations": settings.max_iterations,
        "max_llm_calls": settings.max_llm_calls,
        "retry": {
            "max_attempts": settings.retry.max_attempts,
            "base_backoff_sec": settings.retry.base_backoff_sec,
            "backoff_factor": settings.retry.backoff_factor,
            "max_backoff_sec": settings.retry.max_backoff_sec,
            "jitter_frac": settings.retry.jitter_frac,
        },
    }


def _render_config(settings: Settings) -> str:
    """Render the fully-resolved effective settings as plain text (read-only, LLM-free).

    A pure, disk-free, client-free function of ``settings`` -- like ``_render_policy``
    it opens no file and builds no client, so the exact human view is reproducible
    from a ``Settings`` alone. It surfaces every resolved field (all ``PLA_*`` env
    vars and CLI globals already folded in via the shared ``_settings`` seam) as a
    flat catalog, with the five ``RetryPolicy`` knobs nested under ``retry:``.

    ``auto_dispatch_min_score`` uses ``:.2f`` (mirroring ``_render_policy``) so a
    default renders ``4.00``; an unset ``model``/``scripted_responses_path`` renders
    ``(unset)``; ``sensitive_categories`` is a sorted comma-joined list of category
    ``.value`` strings. Field labels are the literal ``Settings`` attribute names so
    the render is self-describing.
    """
    scripted = settings.scripted_responses_path
    scripted_str = str(scripted) if scripted is not None else "(unset)"
    model_str = settings.model if settings.model is not None else "(unset)"
    categories = ", ".join(sorted(cat.value for cat in settings.sensitive_categories))
    lines = [
        "effective settings",
        f"  provider: {settings.provider}",
        f"  model: {model_str}",
        f"  scripted_responses_path: {scripted_str}",
        f"  workspace_root: {settings.workspace_root}",
        f"  state_dir: {settings.state_dir}",
        f"  auto_dispatch_min_score: {settings.auto_dispatch_min_score:.2f}",
        f"  sensitive_categories: {categories}",
        f"  max_iterations: {settings.max_iterations}",
        f"  max_llm_calls: {settings.max_llm_calls}",
        "  retry:",
        f"    max_attempts: {settings.retry.max_attempts}",
        f"    base_backoff_sec: {settings.retry.base_backoff_sec}",
        f"    backoff_factor: {settings.retry.backoff_factor}",
        f"    max_backoff_sec: {settings.retry.max_backoff_sec}",
        f"    jitter_frac: {settings.retry.jitter_frac}",
    ]
    return "\n".join(lines)


# The four access classes a sandbox tool can belong to -- a CLOSED set, named
# once so the `tools` catalog, its JSON, and any reviewer read the identical
# vocabulary (mirrors how `_POLICY_RULES` pins the gate narration). read-only:
# reads/discovers but never mutates; create-update: writes/extends an artifact;
# move: relocates one artifact; delete: removes one artifact.
_ACCESS_READ_ONLY = "read-only"
_ACCESS_CREATE_UPDATE = "create-update"
_ACCESS_MOVE = "move"
_ACCESS_DELETE = "delete"

# The hand-maintained catalog of the L1 ACT tool surface: name -> (access class,
# one-line description). This is the ONE deliberate, acknowledged doc-vs-code
# coupling of the `tools` verb (mirroring `_POLICY_RULES` for `policy`): the
# access class and the human prose are curated here, NOT reflected out of
# `tools.py`. What IS source-driven is the completeness guard -- a test asserts
# this map's KEY SET equals `ToolRegistry.tool_names()`, so a tool added to (or
# dropped from) the registry without a matching catalog edit turns that guard RED
# (the iter-37/38 completeness-trap discipline). Each description avoids emitting
# any access word OTHER than the tool's own class, so a per-line check reads one
# unambiguous access token. Ordering here is irrelevant -- both renders sort by
# name -- but it is grouped by access class for a human editor's benefit.
_TOOL_CATALOG: dict[str, tuple[str, str]] = {
    # create-update -- the write side
    "write_file": (_ACCESS_CREATE_UPDATE, "Create or overwrite a file under the artifacts dir."),
    "append_file": (_ACCESS_CREATE_UPDATE, "Extend a file under the artifacts dir, creating it if absent."),
    "replace_in_file": (_ACCESS_CREATE_UPDATE, "Replace all occurrences of a literal substring in a file under the artifacts dir."),
    # read-only -- the read/discovery side
    "read_file": (_ACCESS_READ_ONLY, "Return the whole contents of a file from the sandbox."),
    "head_file": (_ACCESS_READ_ONLY, "Return the first N lines of a file (a bounded top-of-file peek)."),
    "tail_file": (_ACCESS_READ_ONLY, "Return the last N lines of a file (a bounded bottom-of-file peek)."),
    "read_lines": (_ACCESS_READ_ONLY, "Return an inclusive 1-based line range [start, end] of a file (a bounded interior window)."),
    "list_files": (_ACCESS_READ_ONLY, "List the entries of one directory in the sandbox."),
    "stat_file": (_ACCESS_READ_ONLY, "Describe one path in a line: type, byte size, line count, extension."),
    "search_files": (_ACCESS_READ_ONLY, "Grep file contents for a substring across a sandbox directory."),
    "find_files": (_ACCESS_READ_ONLY, "Find files by basename glob across a sandbox directory."),
    "diff_files": (_ACCESS_READ_ONLY, "Compare two files and return a bounded unified diff (read-only)."),
    # move -- relocate
    "move_file": (_ACCESS_MOVE, "Atomically rename or relocate one file within the artifacts dir."),
    # delete -- remove
    "remove_file": (_ACCESS_DELETE, "Remove one file under the artifacts dir."),
}

# The sandbox invariant, named once so the human view and the --json object agree:
# writes are confined to the artifacts dir; the workspace is read-only.
_SANDBOX_WRITABLE_ROOT = "artifacts_dir"
_SANDBOX_READ_ONLY_ROOT = "workspace_root"


def _tools_json_payload() -> dict[str, Any]:
    """Build the ``tools --json`` document -- a pure, input-free function.

    One object of EXACTLY two top-level keys ``{sandbox, tools}``, built from an
    EXPLICIT allowlist (never ``model_dump``; the iter-08 schema-leak discipline):
    ``sandbox`` names the writable root (``artifacts_dir``) and the read-only root
    (``workspace_root``); ``tools`` is the ``_TOOL_CATALOG`` projected to a list of
    ``{name, access, description}`` objects with EXACTLY those three keys each,
    ordered by ``name`` ascending (``sorted`` on the catalog items). The catalog
    is the single source for the emitted set, and a test drift-guards its key set
    against ``ToolRegistry.tool_names()`` so the wire set can never diverge from
    the live registry. Disk-free and client-free -- the tool surface is static, so
    no workspace / slate / ``LLMClient`` is consulted.
    """
    return {
        "sandbox": {
            "writable_root": _SANDBOX_WRITABLE_ROOT,
            "read_only_root": _SANDBOX_READ_ONLY_ROOT,
        },
        "tools": [
            {"name": name, "access": access, "description": description}
            for name, (access, description) in sorted(_TOOL_CATALOG.items())
        ],
    }


def _render_tools() -> str:
    """Render the L1 sandbox tool surface as plain text (read-only, LLM-free).

    A pure, disk-free, deterministic function -- like ``_render_policy`` it opens
    no file and builds no client, so the exact human view is reproducible from the
    module catalog alone. It states the sandbox invariant (``artifacts_dir`` is
    the WRITABLE root, ``workspace_root`` is READ-ONLY) then lists every tool,
    name-ascending, one per line as ``name  access  description`` so a reader can
    answer "what can a dispatched goal do to my disk, and how dangerous is each
    door?" at a glance. The access token on each tool line is exactly the tool's
    class from the closed set ``{read-only, create-update, move, delete}`` and the
    per-tool descriptions never emit any OTHER access word, so the line for
    ``remove_file`` reads ``delete`` and never ``read-only``.
    """
    lines = [
        "sandbox tool surface (L1 ACT)",
        "",
        "sandbox invariant:",
        f"  writable root:   {_SANDBOX_WRITABLE_ROOT}",
        f"  read-only root:  {_SANDBOX_READ_ONLY_ROOT}",
        "  a dispatched goal may touch the disk ONLY through the tools below,",
        f"  confined to {_SANDBOX_WRITABLE_ROOT}.",
        "",
        "tools (name / access / description):",
    ]
    for name, (access, description) in sorted(_TOOL_CATALOG.items()):
        # Name column is (longest tool name + 1) wide so name and access never
        # collide: "replace_in_file" (iter-66) is 15 chars, so a 16-wide column
        # keeps a >=1-space gap the whitespace-split parsers rely on.
        lines.append(f"  {name:<16}{access:<15}{description}")
    return "\n".join(lines)


# The hand-maintained catalog of the L2 PERCEPTION surface: collector name -> a
# one-line description of what it perceives. This is the ONE deliberate,
# acknowledged doc-vs-code coupling of the `collectors` verb (mirroring
# `_TOOL_CATALOG` for `tools` and `_POLICY_RULES` for `policy`): the human prose
# is curated here, NOT reflected out of the collector class docstrings at
# runtime. What IS source-driven is the completeness guard -- a test asserts this
# map's KEY SET equals `{c.name for c in all_collectors()}`, so a collector added
# to (or dropped from) the registry without a matching catalog edit turns that
# guard RED (the same anti-rot discipline `_TOOL_CATALOG` uses against
# `ToolRegistry.tool_names()`). Each description is one line, curated from the
# collector's own class docstring, and deliberately describes ONLY that collector
# (never another collector's job). Ordering here is irrelevant -- both renders
# sort by name.
_COLLECTOR_CATALOG: dict[str, str] = {
    "broken_link": "Markdown links whose relative target is missing from the workspace.",
    "ci_config": "Continuous-integration posture: a recognized CI config, or source code with none.",
    "dependencies": "Dependency manifests declared in the workspace (pyproject, package.json, etc.).",
    "git_activity": "Recent commits across the workspace's git repositories.",
    "git_stash": "Forgotten entries sitting in the git stash reflog.",
    "git_state": "Interrupted or dangling git operations read from .git markers.",
    "large_file": "Files at or above a byte-size threshold worth a second look.",
    "license": "Open-source hygiene: a code-carrying workspace with no recognized root LICENSE file.",
    "lockfile_drift": "Manifest/lockfile drift: a manifest whose lockfile is missing or older than it.",
    "merge_conflict": "Files still carrying unresolved conflict markers.",
    "notes": "Heading-and-paragraph blocks found in notes directories.",
    "recent_files": "Files modified most recently under the workspace.",
    "secret_file": "Secret-shaped files matched by basename (.env, credentials, keys).",
    "syntax_error": "Python files that fail to parse (stdlib compile, parse-only).",
    "test_posture": "Top-level project directories that contain source files.",
    "todos": "TODO/FIXME/XXX comments and unchecked Markdown checkboxes.",
    "working_tree": "Present-state git signals: dirty paths and unpushed commits.",
}


# The collector name -> emitted `ContextSignal.kind` mapping, published so the
# transparency arc's FRONT DOOR hands a reader a token the NEXT command accepts.
#
# WHY this exists at all: five of the seventeen collector NAMES are not valid
# `pla signals --kind` values (`dependencies`->`dependency`, `git_activity`->
# `git_commit`, `notes`->`note`, `recent_files`->`recent_file`, `todos`->`todo`).
# Since `--kind` became fail-closed (an unknown kind is a parse-time exit 2, so a
# typo can no longer read as a quiet workspace), publishing only the NAME made the
# documented path `collectors` -> `signals --kind` a dead end a third of the time:
# `pla signals --kind todos` exits 2 while `todo` works, and the working token
# appeared NOWHERE in the product's own output. Publishing the mapping fixes that
# WITHOUT relaxing the validation -- the alternative (teaching `signals --kind` to
# also accept collector names) would re-open the silently-empty-listing hole.
#
# WHY a separate dict instead of widening `_COLLECTOR_CATALOG`'s values to tuples:
# the catalog is a curated PROSE surface with its own guards; keeping it a plain
# `name -> description` map means this feature adds a mapping rather than migrating
# an existing structure (and both dicts stay independently greppable and diffable).
#
# WHY a scalar `str` and not a set/list of kinds: measured, not assumed -- an `ast`
# pass over `collectors/*.py` finds each of the 17 collectors emitting EXACTLY ONE
# distinct string-literal `kind=`, and the 17 kinds are distinct, so name <-> kind
# is a genuine BIJECTION onto `SIGNAL_KINDS`. A list would be dishonest about a 1:1
# relation, and the bijection is what makes the reverse `--kind` lookup total:
# every value `choices=SIGNAL_KINDS` admits matches exactly one collector, so the
# filtered view can never be empty and needs no "no matches" branch.
#
# What keeps it HONEST is the fail-closed drift guard in the test suite: it asserts
# this map's key set equals `{c.name for c in all_collectors()}`, its value set
# equals `set(SIGNAL_KINDS)`, its values are pairwise distinct, and -- the
# load-bearing part -- that each published kind equals the `kind=` string literal
# that collector's own SOURCE MODULE emits. NOTE for whoever writes/edits that
# guard: the join must be MODULE-scoped via `type(c).__module__`, NOT class-scoped
# and NOT by filename. Three collectors (`git_activity`, `notes`, `todos`) build
# their signals in module-level helper functions OUTSIDE the class body, so a
# class-scoped scan finds zero kinds for them; and `filesystem.py` hosts
# `recent_files`, so the filename is not the collector name either.
_COLLECTOR_KINDS: dict[str, str] = {
    "broken_link": "broken_link",
    "ci_config": "ci_config",
    "dependencies": "dependency",
    "git_activity": "git_commit",
    "git_stash": "git_stash",
    "git_state": "git_state",
    "large_file": "large_file",
    "license": "license",
    "lockfile_drift": "lockfile_drift",
    "merge_conflict": "merge_conflict",
    "notes": "note",
    "recent_files": "recent_file",
    "secret_file": "secret_file",
    "syntax_error": "syntax_error",
    "test_posture": "test_posture",
    "todos": "todo",
    "working_tree": "working_tree",
}

# The INVERSE of `_COLLECTOR_KINDS`, DERIVED at import time and never hand-typed,
# so it cannot drift from the forward map (which the suite already pins against the
# `kind=` literal each collector module emits). It answers the question that
# `signals --kind K` actually asks -- "which collectors can emit K?" -- which is
# what turns that flag from a display-only post-filter into an UPSTREAM allowlist:
# asking for one cheap kind no longer pays for the whole perception sweep (measured
# on this repo before the change: `--kind ci_config` spent ~378 ms to print the
# output of a 0.16 ms collector, and `--kind todo` cost 3.2x `--collector todos`
# for byte-identical stdout).
#
# WHY the value is a SET of names when the forward map is a bijection TODAY: the
# value type IS the safety property, not a convenience. Let a future collector emit
# two kinds (or two collectors share one kind) and the forward map becomes
# many-to-one; a scalar inverse would then silently pick ONE owner and narrowing
# would DROP signals the user asked to see. With owner SETS the same change merely
# widens the allowlist, so the worst case degrades to correct-but-slower.
#
# Kind-ascending by construction (`sorted`): iteration order over a plain `set` of
# strings varies between interpreter runs, and every ordered surface in this repo
# has to be reproducible.
_KIND_COLLECTORS: dict[str, frozenset[str]] = {
    kind: frozenset(name for name, k in _COLLECTOR_KINDS.items() if k == kind)
    for kind in sorted(set(_COLLECTOR_KINDS.values()))
}


def _collector_rows(kind: str | None = None) -> list[tuple[str, str, str]]:
    """Return ``(name, kind, description)`` triples, name-ascending.

    The ONE place the two catalogs are joined, so the human render and the JSON
    payload cannot disagree about a collector's kind. ``kind`` filters to the
    single collector emitting it; because the mapping is a bijection onto
    ``SIGNAL_KINDS`` (and the CLI validates ``--kind`` against exactly that tuple)
    a non-``None`` value always yields exactly one row -- an unknown kind never
    reaches here, it is rejected at PARSE time with exit 2.
    """
    return [
        (name, _COLLECTOR_KINDS[name], description)
        for name, description in sorted(_COLLECTOR_CATALOG.items())
        if kind is None or _COLLECTOR_KINDS[name] == kind
    ]


def _collectors_json_payload(kind: str | None = None) -> dict[str, Any]:
    """Build the ``collectors --json`` document -- a pure, input-free function.

    One object of EXACTLY one top-level key ``{collectors}``, built from an
    EXPLICIT allowlist (never ``model_dump``; the iter-08 schema-leak discipline):
    ``collectors`` is the catalog join projected to a list of
    ``{name, kind, description}`` objects with EXACTLY those three keys each,
    ordered by ``name`` ascending (``sorted`` on the catalog items). ``kind`` is
    the ``ContextSignal.kind`` that collector emits -- i.e. the token to hand
    ``pla signals --kind`` -- which is NOT always the collector's name. The
    catalogs are the single source for the emitted set, and tests drift-guard the
    key set against ``{c.name for c in all_collectors()}`` and the kind set against
    ``SIGNAL_KINDS``, so neither the wire set nor the published kinds can diverge
    from the live registry. The optional ``kind`` argument filters to the single
    collector emitting it (the payload shape is unchanged -- still exactly one
    top-level key -- so a filtered document parses identically). Disk-free and
    client-free -- the collector SET is static, so no workspace / signal /
    ``LLMClient`` is consulted.
    """
    return {
        "collectors": [
            {"name": name, "kind": signal_kind, "description": description}
            for name, signal_kind, description in _collector_rows(kind)
        ],
    }


def _render_collectors(kind: str | None = None) -> str:
    """Render the L2 perception surface as plain text (read-only, LLM-free).

    A pure, disk-free, deterministic function -- like ``_render_tools`` it opens
    no file and builds no client, so the exact human view is reproducible from the
    module catalog alone. It lists every registered collector, name-ascending, one
    per line as ``name  description`` so a reader can answer "what does the
    proactivity layer even look at?" with no workspace and no LLM call. It is the
    context-free FRONT DOOR to ``signals`` (which needs a ``--workspace`` and only
    shows what fired there) -- so each row publishes the signal ``kind`` that
    collector emits, which is the token ``signals --kind`` accepts and is NOT
    always the collector's name (``todos`` emits ``todo``). ``kind`` filters the
    listing to the single collector emitting it.
    """
    lines = [
        "context collectors (L2 perception)",
        "",
        "each collector perceives one kind of working-context signal;",
        "run `pla signals --kind K --workspace W` to see what one emits for a",
        "workspace -- K is the kind column below, not the collector name.",
        "",
        "collectors (name / kind / description):",
    ]
    for name, signal_kind, description in _collector_rows(kind):
        lines.append(f"  {name:<16}{signal_kind:<16}{description}")
    if kind is not None:
        lines.append("")
        lines.append(f"(filtered to signal kind `{kind}`; omit --kind to list all)")
    return "\n".join(lines)


# The hand-maintained catalog of the L0 LLM-BACKEND surface: provider name -> a
# (kind, package, description) triple. This is the ONE deliberate, acknowledged
# doc-vs-code coupling of the `providers` verb (mirroring `_TOOL_CATALOG` for
# `tools` and `_COLLECTOR_CATALOG` for `collectors`): the curated prose lives
# here, NOT reflected out of the provider factory at runtime. What IS
# source-driven is the completeness guard -- a test asserts this map's KEY SET
# equals `set(VALID_PROVIDERS)`, so a provider added to (or dropped from) the
# registry without a matching catalog edit turns that guard RED (the same
# anti-rot discipline `_TOOL_CATALOG`/`_COLLECTOR_CATALOG` use). `kind` is the
# offline/cloud split; `package` is the pip install target (str) or None for the
# built-in `scripted` client -- and each `package` matches the module name the
# live provider's `_require(module, provider)` call names, so the confusing
# `bedrock` -> `boto3` label-vs-package divergence is surfaced honestly. Ordering
# here is irrelevant -- both the JSON payload and the human render sort by name.
_PROVIDER_CATALOG: dict[str, tuple[str, str | None, str]] = {
    "scripted": ("offline", None, "Built-in offline test double: replays a recorded JSON script (no SDK, no key, no network)."),
    "anthropic": ("cloud", "anthropic", "Anthropic Claude models via the official anthropic SDK."),
    "openai": ("cloud", "openai", "OpenAI GPT models via the official openai SDK."),
    "bedrock": ("cloud", "boto3", "AWS Bedrock-hosted models via boto3 (the pip package name differs from the provider label)."),
    "ollama": ("offline", "ollama", "Locally-served open models on localhost via ollama (no API key, no network egress)."),
    "groq": ("cloud", "groq", "Groq LPU-hosted open models (Llama/Mixtral) via the groq SDK."),
    "together": ("cloud", "together", "Together AI-hosted open models (Llama/Mixtral) via the together SDK."),
}


def _providers_json_payload() -> dict[str, Any]:
    """Build the ``providers --json`` document -- a pure, input-free function.

    One object of EXACTLY one top-level key ``{providers}``, built from an
    EXPLICIT allowlist (never ``model_dump``; the iter-08 schema-leak discipline):
    ``providers`` is the ``_PROVIDER_CATALOG`` projected to a list of
    ``{name, kind, package, description}`` objects with EXACTLY those four keys
    each, ordered by ``name`` ascending (``sorted`` on the catalog items).
    ``package`` is a ``str`` or JSON ``null`` (``scripted`` has no SDK to install).
    The catalog is the single source for the emitted set, and a test drift-guards
    its key set against ``set(VALID_PROVIDERS)`` so the wire set can never diverge
    from the live provider registry. Disk-free and client-free -- the provider
    surface is static, so no workspace / slate / ``LLMClient`` is consulted.
    """
    return {
        "providers": [
            {
                "name": name,
                "kind": kind,
                "package": package,
                "description": description,
            }
            for name, (kind, package, description) in sorted(_PROVIDER_CATALOG.items())
        ],
    }


def _render_providers() -> str:
    """Render the L0 LLM-backend surface as plain text (read-only, LLM-free).

    A pure, disk-free, deterministic function -- like ``_render_tools`` it opens
    no file and builds no client, so the exact human view is reproducible from the
    module catalog alone. It lists every accepted provider name-ascending, one per
    line, each line carrying its ``kind`` token (``offline``/``cloud``), its pip
    install target (``pip install <pkg>``, or ``(built-in)`` for the SDK-less
    ``scripted`` client -- so the ``bedrock`` line names ``boto3``, not its
    label), and a one-line description, so a reader can answer "what can I run
    against, and what do I ``pip install`` for each?" with no workspace and no LLM
    call.
    """
    lines = [
        "LLM provider backends (L0 / provider abstraction)",
        "",
        "the default backend is offline and built-in (no SDK, no API key, no",
        "network); point at a live model with `--provider NAME`. a cloud backend",
        "needs the named pip package installed and an API key; an offline backend",
        "needs no key and sends nothing off the machine.",
        "",
        "providers (name / kind / install / description):",
    ]
    for name, (kind, package, description) in sorted(_PROVIDER_CATALOG.items()):
        install = "(built-in)" if package is None else f"pip install {package}"
        lines.append(f"  {name:<11}{kind:<9}{install:<24}{description}")
    return "\n".join(lines)


def _dispatch_goal(
    goal: CandidateGoal, workspace_root: Path, settings: Settings, client: LLMClient
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
    """scan: collect -> synthesize -> gate -> render (table|json|markdown|csv|html) -> write slate JSON.

    ``--format`` selects the STDOUT rendering only; every format writes the
    identical slate file to ``--out`` (behavior 10), so a later
    ``dispatch``/``explain``/``trace`` behaves the same regardless of which format
    printed it. ``json``, ``csv``, and ``html`` are the pure-document formats that
    suppress the ``slate written:`` trailer (and the ``--top`` truncation note) so
    their whole stdout is a single self-contained document -- ``json`` pipes cleanly
    into ``jq``, ``csv`` loads with ``pandas.read_csv`` / a spreadsheet, ``html`` opens
    in a browser (or pastes into a wiki/PR); ``table`` (the default) and ``markdown``
    keep the human trailer. The ``table`` branch is the
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

    # --collector is a repeatable allowlist (argparse action="append" -> a list or
    # None). Fold it into the OPTIONAL _collect filter: a non-empty list restricts
    # synthesis to those collectors; absent (None or []) => None => all collectors,
    # keeping a bare scan byte-identical. Only scan threads this; the shared
    # _collect seam under run/signals/watch still calls _collect(workspace).
    only = set(args.collector) if args.collector else None
    snapshot = _collect(workspace, only=only)
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
    if args.format == "html":
        # A self-contained, dependency-free HTML document (json/csv-style purity):
        # NO `slate written:` trailer and NO `... showing top N of M` note, so the
        # ENTIRE stdout is one standalone .html file a non-terminal stakeholder can
        # open in a browser or paste into a wiki/PR. `print` appends exactly one
        # trailing newline after `</html>` (behavior 2 permits it) so the redirected
        # file is well-formed. `--top` caps the shown rows while `_write_slate` still
        # persists the COMPLETE slate (behaviors 6, 8).
        print(_render_html(slate, decisions, top=args.top))
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

    # --dry-run is the confirm-before-you-act preview twin of this sole
    # autonomous verb: it has already done the identical scan+gate+render+write
    # (and the needs-approval listing above), so the ONLY thing it skips is the
    # dispatch itself. Print the goal `run` WOULD auto-dispatch plus a paste-ready
    # command, then return 0 WITHOUT building a GoalLoop, a run dir, or spending a
    # loop iteration -- the core safety property this flag exists to provide.
    if args.dry_run:
        print(f"\n[dry-run] would auto-dispatch top goal: {top.title}")
        print(f"  pla dispatch --slate {slate_path} --goal-id {top.id}")
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


def _prune_runs(state_dir: Path, args: argparse.Namespace) -> int:
    """runs --prune: report, and with ``--yes`` delete, the selected run dirs.

    Split out of ``_cmd_runs`` so the shipped listing path stays byte-identical:
    the listing never evaluates a prune branch, and this function is unreachable
    without a literal ``--prune``.

    Always exits 0. Nothing here is a fault: an absent state dir, a filter that
    matches no run, and a refused symlink are all legitimate answers, and the
    verb introduces no new exit code.
    """
    selected, refused = _select_prunable(state_dir, args.status)
    # A refusal is a stderr TRAILER-style warning (the `signals --timings`
    # convention): it must survive --json, because suppressing "I declined to
    # touch this" in machine mode is exactly when a human would want to see it,
    # and stdout purity is preserved by writing to stderr rather than by staying
    # silent. The name is also echoed in the JSON object's `refused` list.
    for name in refused:
        print(f"refused: {name} is a symlink, not a run dir", file=sys.stderr)
    names = [d.name for d in selected]
    dry_run = not args.yes
    if not dry_run:
        # Delete BEFORE reporting so the "pruned N" header is a statement of fact,
        # never a prediction. Each argument is a path `_select_prunable` produced.
        for run_dir in selected:
            shutil.rmtree(run_dir)
    if args.json:
        # The ENTIRE stdout must parse as ONE JSON object; no prose, in either
        # mode (an empty selection is a legitimate object, not the human line).
        print(
            json.dumps(
                {
                    "dry_run": dry_run,
                    "status": args.status,
                    "selected": names,
                    "refused": refused,
                    "deleted": 0 if dry_run else len(names),
                },
                indent=2,
            )
        )
    else:
        print(_render_prune(names, dry_run=dry_run))
    return 0


def _cmd_runs(args: argparse.Namespace) -> int:
    """runs: list past dispatched runs under the state dir (LLM-free).

    WHY it builds no LLMClient: it is a pure, tolerant read over the run state
    dispatch/run/resume already persist, so a fresh clone can enumerate and
    inspect every past run with zero provider wiring. It also repairs resume's
    usability -- the run_id column is exactly the --run-dir value resume wants,
    so discovering a run no longer means hand-hunting an opaque path. Always
    exits 0: an absent or empty state dir is a legitimate "no runs" answer, not
    a fault.

    Read-only EXCEPT on the one opted-in path: ``--prune --yes`` deletes the run
    dirs this same command would have listed (delegated to ``_prune_runs``).
    Without ``--prune`` no deletion code is reachable at all, so the listing
    contract every other caller depends on is unchanged.
    """
    settings = _settings(args)
    if args.prune:
        return _prune_runs(settings.state_dir, args)
    rows = [_run_row(d) for d in _iter_run_dirs(settings.state_dir)]
    # Optional post-mapping status filter (ROADMAP #98). Applied AFTER building
    # rows so the default path (args.status is None) stays byte-identical, and a
    # degraded "(no checkpoint)" row -- whose marker matches no RunStatus value --
    # is naturally excluded by any filter. The filtered rows feed the SAME
    # _render_runs / json.dumps paths, so the empty result reuses the existing
    # "no runs" line (human) or "[]" (--json) verbatim.
    if args.status is not None:
        rows = [r for r in rows if r["status"] == args.status]
    if args.json:
        # The ENTIRE stdout must parse as one JSON array (empty -> []); no prose.
        print(json.dumps(rows, indent=2))
    else:
        print(_render_runs(rows))
    return 0


def _cmd_explain(args: argparse.Namespace) -> int:
    """explain: print a full, LLM-free gate-decision audit from a saved slate.

    WHY it builds no LLMClient (like ``runs``): it is a pure read over a persisted
    slate. It re-gates each goal through the SAME ``gate(goal, settings)`` the
    ``dispatch`` verb uses -- so an ``explain`` and a subsequent ``dispatch`` can
    never disagree -- and renders the score arithmetic, the autonomy rule that
    fired, and the goal's rationale/sources/first-steps. It runs nothing and
    re-scores nothing.

    Two audit scopes, chosen by whether ``--goal-id`` was given:

    * ``--goal-id ID`` (single-goal) -- audit that ONE goal. Byte-identical to the
      pre-optional behavior: ``2`` for a missing slate file or an unknown goal id
      (returned explicitly, before any exception); ``--json`` prints ONE object.
    * ``--goal-id`` OMITTED (whole-slate) -- audit EVERY goal in ``slate.ranked()``
      order in one pass, so a script/CI can answer the slate-level safety question
      ("did ANY sensitive goal resolve AUTO_DISPATCH?") without shelling out per id.
      Human form prints the per-goal blocks (the SAME ``_render_explain`` block, no
      new rendering) joined by a single blank line, or exactly ``(no goals in
      slate)`` when empty; ``--json`` prints a JSON ARRAY of the 12-key objects
      (``[]`` when empty). Exit 0 in all cases; there is no unknown-id path (no id
      was named).

    A corrupt slate raises ``ValidationError`` (a ``ValueError``) and is mapped to
    ``1`` by the top-level ``main()`` boundary as one legible ``error:`` line, on
    both scopes. ``--json`` is applied AFTER the exit-2/exit-1 guards, so it selects
    a rendering only and leaves the exit-code contract untouched -- like
    ``runs``/``trace``/``signals``.
    """
    slate_path = Path(args.slate)
    if not slate_path.is_file():
        print(f"error: slate file not found: {slate_path}", file=sys.stderr)
        return 2

    slate = _load_slate(slate_path)

    if args.goal_id is None:
        # Whole-slate audit: reuse the two EXISTING pure render helpers verbatim
        # over slate.ranked() (no schema drift, no new rendering) so element/block i
        # is byte-identical to the single-goal audit for that goal's id. --json is a
        # JSON array; the human form joins the per-goal blocks with a single blank
        # line (an empty slate prints the explicit "(no goals in slate)" sentinel).
        settings = _settings(args)
        ranked = slate.ranked()
        if args.json:
            payload = [_explain_json_payload(g, gate(g, settings), settings) for g in ranked]
            print(json.dumps(payload, indent=2))
        else:
            blocks = [_render_explain(g, gate(g, settings), settings) for g in ranked]
            print("\n\n".join(blocks) if blocks else "(no goals in slate)")
        return 0

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
    collector-defined kind, validated at PARSE time against the live
    ``SIGNAL_KINDS`` registry (an unknown kind is an argparse usage error, exit 2,
    never a silently empty listing) -- and it narrows COLLECTION as well as the
    view: the kind's emitting collector is intersected into the ``only`` allowlist
    below, so only that collector runs (fail-OPEN -- a kind with no known owner
    runs them all rather than none);
    ``--min-weight`` keeps only signals whose ``weight >= min_weight`` (an
    inclusive relevance lower bound, AND-composed with ``--kind``) -- a non-numeric
    OR non-finite (``nan``/``inf``/``-inf``) value is rejected by argparse (exit 2)
    BEFORE this handler runs, while a finite negative or ``> 1.0`` value is accepted
    and an impossibly high finite value simply empties the view (no error).
    ``--collector NAME`` is a repeatable UPSTREAM allowlist restricting WHICH
    collectors are inspected (the perception-INPUT knob, mirroring
    ``scan --collector``): its accepted values are exactly the live collector
    names, an unknown name is an argparse usage error (exit 2) BEFORE this
    handler runs, absent (the default) inspects all collectors, and it composes
    as a logical AND with ``--kind``/``--min-weight``. ``--exclude-path GLOB``
    (repeatable, OR semantics) is the first LOCATION-aware knob and the only
    SUBTRACTIVE one: it hides signals whose ``path`` matches a case-folded glob, so a
    vendored/generated/fixture tree can be dropped without re-rooting ``--workspace``
    (which would also throw away every repo-level, path-less signal). It is a
    DOWNSTREAM display filter read after ``_collect``, so ``--timings`` is untouched;
    an empty pattern is an argparse usage error (exit 2). ``--baseline FILE`` is the
    second subtractive knob and the INSTANCE-aware complement of that LOCATION-aware
    one: it hides every signal whose six published keys already appear in a document
    the user saved with ``signals --json``, which is what turns the ``--fail-on-kind``
    gate from "no findings" into "no NEW findings" on a workspace that has any. It is
    loaded ONCE below -- BEFORE ``_collect``, beside the ``--fail-on-kind``-unreachable
    guard -- and a missing or malformed document is a fail-CLOSED usage error (one
    ``error: `` line, exit 2, nothing scanned) rather than a silent "suppress nothing";
    like ``--exclude-path`` it narrows every surface AND the gate identically and leaves
    ``--timings`` alone. ``--timings`` is the one
    knob here that is not a view filter: it arms ``_collect``'s measurement sink
    and prints a per-collector cost table (name / elapsed ms / signal count, plus
    a ``TOTAL`` row, in registry order) to STDERR only, so every stdout surface
    stays byte-identical to the same command without the flag -- durations are
    non-deterministic and must never enter a stdout contract. Its rows report
    which collectors RAN, so the UPSTREAM filters narrow them (``--collector``,
    and ``--kind`` via its emitting collector) while the display-only ones
    (``--min-weight``/``--summary``/``--exclude-path``) do not, and the front-door workspace guard
    above still runs FIRST, so a mistyped path exits 2 with no timing block.
    ``--fail-on-kind KIND`` (repeatable, registry-validated at PARSE time) is the
    only knob here that touches the EXIT STATUS: it returns ``5`` when the REPORTED
    signals include at least one signal of a named kind, which is what lets a
    pre-commit hook or a CI step branch on what the perception layer found -- until
    it existed, a workspace holding a committed ``.env`` and an empty directory both
    exited ``0``. It gates on the same ``_select_signals`` list the view rendered, so
    narrowing that hides a finding (``--min-weight`` above its weight, a disjoint
    ``--collector``, an ``--exclude-path`` covering its directory) also disarms the
    gate and the exit status can never contradict the listing; the report is exactly one ``gate: fail-on-kind tripped --
    <kind>=<count>`` line on STDERR (kinds ascending, matched kinds only, no
    ``error:`` prefix because a finding is not a fault), so every stdout surface
    stays byte-identical with and without the flag and ``--json`` keeps parsing as
    one object. ``--kind K`` paired with a different ``--fail-on-kind V`` is refused
    as a usage error (exit 2) before collection: that gate could never fire.

    ``--fail-over N`` is the COUNT-budget sibling of that gate and the third
    ratchet: exit 5 when the number of reported signals is STRICTLY greater than
    the non-negative integer ``N``, so ``count == N`` is inside the budget. It is
    counted over the same ``_select_signals`` list, so it composes with every
    filter, and it reports exactly one ``gate: fail-over tripped -- count=<count>
    budget=<N>`` line on STDERR. It is checked AFTER the kind gate, so when both
    are armed and both would trip only the kind line prints (it names WHICH kind)
    and the status is still 5. ``--kind K --fail-over N`` is deliberately NOT
    refused, unlike the kind pair above: an unreachable KIND gate is statically
    provable, an unreachable COUNT budget is not.
    """
    workspace = Path(args.workspace)
    if not workspace.is_dir():
        print(f"error: workspace not found: {workspace}", file=sys.stderr)
        return 2
    only = set(args.collector) if args.collector else None
    kind = getattr(args, "kind", None)
    # The gate vocabulary, de-duplicated and sorted so a repeated flag cannot change
    # the report line. Empty list (never None) means "no gate armed", which keeps the
    # exit path below a single expression.
    gate_kinds = sorted(set(getattr(args, "fail_on_kind", None) or ()))
    # A gate that could never fire is a usage error, not a silently dead flag: with
    # `--kind K` the view EXCLUDES every other kind by construction, so any
    # `--fail-on-kind V` where V != K would report success on a workspace that is
    # full of V. Refusing it (exit 2, one error line, BEFORE _collect -- next to the
    # --workspace guard above) is the fail-CLOSED choice; a hook author who mistypes
    # a pair like this must hear about it rather than inherit a green build forever.
    # The AGREEING pair `--kind K --fail-on-kind K` is accepted and gates normally.
    unreachable = [k for k in gate_kinds if k != kind] if kind is not None else []
    if unreachable:
        print(
            "error: --fail-on-kind "
            + ", ".join(unreachable)
            + f" can never trip under --kind {kind}: that view reports only "
            f"{kind} signals -- drop --kind or gate on {kind} instead",
            file=sys.stderr,
        )
        return 2
    # Read BEFORE _collect, beside the guard above, because a baseline that cannot be
    # loaded is a USAGE error: nothing should be scanned and stdout must stay empty.
    # Fail-CLOSED for the same reason that guard is (see _load_signal_baseline): the
    # alternative -- degrading to "suppress nothing" -- would let a typo'd path buy a
    # permanently green gate. Loaded ONCE into a set of identity tuples and threaded
    # into every surface below, so the four renderers and the gate cannot disagree
    # about what was already known. None (flag absent) suppresses nothing and skips
    # the identity computation entirely, so a bare `signals` is byte-identical to
    # before the flag existed.
    baseline: set[tuple[object, ...]] | None = None
    baseline_path = getattr(args, "baseline", None)
    if baseline_path is not None:
        try:
            baseline = _load_signal_baseline(Path(baseline_path))
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    # UPSTREAM narrowing: --kind is read BEFORE collecting (it used to be read
    # after) and its emitting collector(s) are intersected into the --collector
    # allowlist, so a kind-filtered inspection now does a kind-filtered amount of
    # WORK. STDOUT is unchanged by construction: the display filter downstream is
    # simply re-applied over an already-narrow list, and it cannot lose a row
    # because `_COLLECTOR_KINDS` is a guarded bijection -- kind K is emitted by
    # exactly one collector, so no OTHER collector could have contributed a signal
    # that `--kind K` would have displayed.
    #
    # Fail-OPEN on purpose (`if owners`, not `if owners is not None`): a kind with
    # no known owner runs EVERY collector -- correct but slow -- instead of none,
    # which would be fast but wrong. Narrowing is an optimization, so its
    # degenerate case must never be able to hide a signal the user asked for.
    #
    # Intersecting (never replacing) keeps --collector authoritative, so a disjoint
    # pair like `--collector notes --kind todo` collapses to the empty allowlist:
    # zero collectors run, the listing is empty, exit stays 0. It is an honest
    # answer to a contradictory question, not a usage error.
    owners = _KIND_COLLECTORS.get(kind) if kind is not None else None
    if owners:
        only = set(owners) if only is None else only & owners
    # An empty list (not None) is what ARMS the measurement in _collect; None
    # leaves that seam on its default no-op path, so a bare `signals` runs the
    # collectors exactly as scan/run/watch do.
    timings: list[tuple[str, float, int]] | None = (
        [] if getattr(args, "timings", False) else None
    )
    snapshot = _collect(workspace, only=only, timings=timings)
    min_weight = getattr(args, "min_weight", None)
    # Read ONCE here and threaded into every surface below (never re-derived), so the
    # four renderers and the gate cannot disagree about what was excluded. DOWNSTREAM
    # by construction: it is read AFTER _collect, so no exclude pattern can change
    # which collectors ran or what --timings reports.
    exclude_paths = getattr(args, "exclude_path", None)
    if getattr(args, "summary", False):
        # AGGREGATE view: a per-kind count rollup over the SAME selected list,
        # NOT the per-signal listing. --json emits the {workspace_root, summary,
        # total} object; otherwise the human count table (kinds ascending, total
        # last). Selection (kind/min_weight/collector) is unchanged.
        if args.json:
            payload = _signals_summary_payload(snapshot, kind, min_weight, exclude_paths, baseline)
            print(json.dumps(payload, indent=2))
        else:
            print(_render_signals_summary(snapshot, kind, min_weight, exclude_paths, baseline))
    elif args.json:
        # The ENTIRE stdout must parse as one JSON object; no human trailer.
        payload = _signals_json_payload(snapshot, kind, min_weight, exclude_paths, baseline)
        print(json.dumps(payload, indent=2))
    else:
        print(_render_signals(snapshot, kind, min_weight, exclude_paths, baseline))
    if timings is not None:
        # A stderr TRAILER, printed after the stdout view so the primary output
        # leads when both streams share a terminal. Nothing above this line
        # branches on `timings`, which is how "stdout is byte-identical with and
        # without --timings" is guaranteed structurally rather than by review.
        print(_render_collector_timings(timings), file=sys.stderr)
    if gate_kinds:
        # The gate counts over the SAME selected list the view rendered (the shared
        # `_select_signals` predicate, applied to a snapshot the --collector
        # allowlist already narrowed upstream), so behavior "the exit status can
        # never disagree with the printed listing" holds structurally rather than by
        # review: a --min-weight that hides the finding also disarms the gate.
        # OR semantics across the named kinds; only kinds that ACTUALLY matched are
        # named in the line, each with its own count, kinds ascending.
        selected = _select_signals(snapshot, kind, min_weight, exclude_paths, baseline)
        tripped = {k: n for k in gate_kinds if (n := sum(1 for s in selected if s.kind == k))}
        if tripped:
            # STDERR, exactly one line, and no `error:` prefix: a tripped gate is a
            # FINDING the user asked to be told about, not a fault in the tool -- the
            # same distinction the exit-code table draws between 5 and 1. Printed
            # after the stdout view (and after any --timings block) so the primary
            # output leads when both streams share a terminal.
            detail = ", ".join(f"{k}={tripped[k]}" for k in sorted(tripped))
            print(f"gate: fail-on-kind tripped -- {detail}", file=sys.stderr)
            return 5
    fail_over = getattr(args, "fail_over", None)
    if fail_over is not None:
        # The COUNT budget, checked AFTER the kind gate above and never merged into
        # it: when both are armed and both would trip, the caller gets exactly ONE
        # line and it is the more informative one (fail-on-kind names WHICH kind),
        # which an appended block gives for free because that block has already
        # returned. Leaving it untouched is also what makes "with --fail-over absent
        # every existing invocation is unchanged" true structurally, not by review.
        #
        # Re-derives the count from the SAME shared _select_signals predicate the
        # four renderers and the kind gate each call for themselves -- the house
        # convention for keeping the surfaces in agreement. It is a pure filter over
        # an already-collected snapshot, so a second pass cannot disagree with the
        # first, and the narrowing flags (--kind/--min-weight/--collector/
        # --exclude-path/--baseline) lower the count exactly as they lower the
        # listing. STRICTLY greater than: N is the budget the caller may spend, so
        # count == N is inside it and only count == N + 1 trips.
        count = len(_select_signals(snapshot, kind, min_weight, exclude_paths, baseline))
        if count > fail_over:
            # STDERR, exactly one line, no `error:` prefix -- a finding is not a
            # fault in the tool, the same distinction the sibling gate draws. Two
            # `key=value` pairs mirror that line's `kind=count` idiom and sidestep a
            # singular/plural branch, which would be a second code path for grammar.
            print(
                f"gate: fail-over tripped -- count={count} budget={fail_over}",
                file=sys.stderr,
            )
            return 5
    return 0


def _cmd_watch(args: argparse.Namespace) -> int:
    """watch: re-run the scan pipeline every --interval seconds (proactive loop).

    This is the product's namesake capability finally wired to a verb: it reuses
    ``scan``'s collect -> synthesize -> gate -> render body verbatim, on a timer,
    so a live workspace's ranked, gated slate is re-printed as its context
    changes. Two deliberate departures from ``scan``: (1) it is a LIVE monitor BY
    DEFAULT, so with ``--out-dir`` absent it writes NO slate file and prints no
    ``slate written:`` trailer -- a watch tick's output is ephemeral, not an
    artifact a later ``dispatch`` consumes; (2) the LLM client is built ONCE,
    before the loop, and reused across ticks (the provider never changes between
    scans, and rebuilding it per-tick would be pointless work for a long-lived
    watcher).

    ``--out-dir DIR`` opts INTO persistence, writing one ``DIR/slate-<NNN>.json``
    per tick (1-based index, zero-padded to 3) through the same ``_write_slate``
    seam ``scan`` uses. WHY the flag exists: ``diff`` is documented as watch's
    comparative companion, "turning a stream of point-in-time slates into a change
    feed", but a stream had no producer -- ``scan --out`` defaults to ONE fixed
    path, so repeated scans clobber a single file and the user had to hand-roll two
    invocations. The index (not a timestamp) keeps the filenames DETERMINISTIC, so
    two identical runs produce the same names and a test can assert them; for runs
    up to 999 ticks lexicographic order is also chronological order. The write
    happens AFTER the tick's table renders, so a tick that raised persists nothing
    and the index advances with the TICK rather than with the write.

    Bounded runs (``--max-scans N``) exist for tests and one-offs; the production
    case is ``--max-scans`` omitted (``None``) -> run forever, exited with Ctrl-C,
    exactly as ``run_periodic``'s docstring frames it. We explicitly ``return 0``
    and NOT ``run_periodic``'s scan count -- returning the count would wrongly
    surface as a nonzero exit code (e.g. 2 for a 2-scan run) through ``main()``'s
    ``int()`` cast.

    Resilient by design: a single scan that raises (an exhausted L0 retry or a
    non-retryable model fault) is caught by ``run_periodic``'s ``on_error`` hook,
    logged to stderr as ``scan <n> failed: <exc>``, and the watch continues to the
    next tick -- a transient outage on one scan never kills the long-lived watcher.
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
    # Structural check on the OPT-IN slate directory, also before the client is
    # built: a bad --out-dir must be reported as the problem instead of surfacing
    # as a leaked errno on every tick of a long-lived watch, and pre-detecting it
    # here costs no scripted response and no live provider call.
    out_dir = Path(args.out_dir) if args.out_dir is not None else None
    if out_dir is not None:
        problem = _out_dir_guard(out_dir)
        if problem is not None:
            print(f"error: {problem}", file=sys.stderr)
            return 2
    settings = _settings(args, workspace_root=workspace)
    client = create_client(settings)  # built once, reused every tick

    count = 0

    def scan_once() -> None:
        # run_periodic owns the timer; this closure owns one tick: a 1-based
        # header then the SAME scan body scan/run use (with the slate-file write
        # made conditional on --out-dir), so `watch` and `scan` can never disagree
        # on what a scan produces.
        nonlocal count
        count += 1
        print(f"=== scan {count} ===")
        snapshot = _collect(workspace)
        slate = GoalSynthesizer(client, settings).synthesize(snapshot)
        decisions = gate_slate(slate, settings)
        print(_render_table(slate, decisions))
        if out_dir is not None:
            # Opt-in tick artifact. Written AFTER the render, so a tick whose
            # synthesize() raised leaves no file behind (the exception propagates
            # to run_periodic's on_error before reaching this line) and the file
            # index can never run ahead of the ticks that actually produced one.
            # Same `slate written:` trailer wording `scan` prints, so the two
            # verbs cannot describe the same act differently.
            target = out_dir / _stream_slate_name(count)
            _write_slate(slate, target)
            print(f"\nslate written: {target}")

    def _on_scan_error(scan_number: int, exc: Exception) -> None:
        # Resilient by design (SPEC L0): a scan whose synthesize() exhausts the L0
        # retry budget or hits a non-retryable model fault must not kill a
        # long-lived watcher. Log it and let run_periodic continue to the next tick.
        # NOT the `error:` prefix (reserved for the fatal exit-1 boundary in
        # main()); a failed scan is transient, so this is a plain per-tick note.
        print(f"scan {scan_number} failed: {exc}", file=sys.stderr)

    run_periodic(
        scan_once, args.interval, iterations=args.max_scans, on_error=_on_scan_error
    )
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

    WHY the ``--dir`` mode exists: ``watch --out-dir`` makes the monitor a PRODUCER
    of a slate stream and this verb is its advertised consumer, but composing them
    meant human filename arithmetic (``ls | sort | tail -2``, then retyping two
    paths). ``--dir DIR`` resolves that pair itself -- highest tick index as
    ``--new``, second-highest as ``--old``, over the shared
    `_stream_slate_index` convention -- so "what changed on the last tick?" is one
    command. It is a SELECTOR only: once the pair is resolved the two modes share
    the identical load/gate/render tail, so ``--dir`` cannot drift from the explicit
    contract. The two modes are mutually exclusive and the conflict is rejected
    BEFORE any filesystem probe, so a wrong invocation is never half-executed.
    """
    # Exactly one selector mode. The conflict is rejected BEFORE any filesystem
    # probe, so a wrong invocation is reported even when every path in it is
    # valid and no slate is ever loaded for a request that cannot be served.
    if args.dir is not None:
        if args.old is not None or args.new is not None:
            print("error: --dir cannot be combined with --old/--new", file=sys.stderr)
            return 2
        stream_dir = Path(args.dir)
        if not stream_dir.is_dir():
            # A missing path and an existing non-directory are the SAME operator
            # mistake here -- unlike `watch --out-dir`, this verb never CREATES
            # anything -- so one message covers both cases.
            print(f"error: --dir must be an existing directory: {stream_dir}", file=sys.stderr)
            return 2
        slates = _stream_slates(stream_dir)
        if len(slates) < 2:
            # Reporting the count found (not just "too few") distinguishes "wrong
            # directory" from "the watch has only ticked once" without a second look.
            print(
                f"error: --dir needs at least two stream slates to compare, "
                f"found {len(slates)}: {stream_dir}",
                file=sys.stderr,
            )
            return 2
        old_path, new_path = slates[-2], slates[-1]
        # Under --json, echo the RESOLVED paths: the caller delegated the choice, so
        # the document has to say WHICH pair was chosen -- the `--dir` value alone
        # would leave a machine consumer unable to tell the two ticks apart.
        old_echo, new_echo = str(old_path), str(new_path)
    else:
        if args.old is None or args.new is None:
            print("error: diff needs either --dir DIR or both --old and --new", file=sys.stderr)
            return 2
        old_path = Path(args.old)
        if not old_path.is_file():
            print(f"error: slate file not found: {old_path}", file=sys.stderr)
            return 2
        new_path = Path(args.new)
        if not new_path.is_file():
            print(f"error: slate file not found: {new_path}", file=sys.stderr)
            return 2
        # Explicit mode keeps echoing the RAW arg strings, byte-identically to
        # before: a re-stringified Path would drop a leading ``./``.
        old_echo, new_echo = args.old, args.new

    old_slate = _load_slate(old_path)
    new_slate = _load_slate(new_path)

    settings = _settings(args)
    result = _compute_diff(old_slate, new_slate, settings)
    if args.json:
        # The ENTIRE stdout must parse as one JSON object; no human trailer. Both
        # guards above (exit 2 / exit 1) already ran, so --json selects a rendering
        # only and leaves the exit-code contract untouched. `old`/`new` echo the
        # strings the selector block resolved: the raw arg strings in explicit mode
        # (the raw-arg echo contract -- never the normalized Path, which drops a
        # leading `./`), and the CHOSEN stream paths in `--dir` mode.
        print(json.dumps(_diff_json_payload(old_echo, new_echo, result), indent=2))
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


def _cmd_config(args: argparse.Namespace) -> int:
    """config: print the fully-resolved effective ``Settings`` (read-only, LLM-free).

    Mirrors ``_cmd_policy`` exactly: it resolves ``settings`` through the SHARED
    ``_settings(args)`` seam -- so ``PLA_*`` env vars AND the CLI globals
    (``--provider``/``--scripted-responses``/``--state-dir``) are folded into the
    printed view -- and does NOTHING else: no ``create_client`` (a provider that
    would need an SDK is simply reflected in the output, never validated, so exit 0
    rather than the eager-load exit 1 a client-building verb gives), no collector,
    no filesystem, no mutation. So it structurally cannot regress any existing
    behavior. It always returns 0; ``--json`` swaps the human listing for one
    explicit-allowlist object (rendering selection only -- there is no input to fail
    on). A malformed ``PLA_*`` numeric env var still fails through the ``main()``
    ``except (LLMError, ValueError, OSError)`` boundary (one ``error:`` line + exit
    1), identical to every other settings-resolving verb -- that path lives in
    ``Settings.from_env`` under this handler, not in a pre-flight arg guard.
    """
    settings = _settings(args)
    if args.json:
        # The ENTIRE stdout must parse as one JSON object; no human trailer.
        print(json.dumps(_config_json_payload(settings), indent=2))
    else:
        print(_render_config(settings))
    return 0


def _cmd_tools(args: argparse.Namespace) -> int:
    """tools: print the L1 ACT sandbox tool surface (read-only, LLM-free, zero-input).

    WHY it consults NOTHING -- not even the ``_settings`` seam ``policy`` uses:
    the sandbox tool surface is STATIC (the fourteen registered tools, their access
    classes, and the artifacts-dir/workspace-root invariant do not depend on any
    env override, workspace, slate, or LLM). So this handler resolves no settings,
    builds no ``create_client`` (an inert/bad ``--scripted-responses`` path is
    simply never opened -- exit 0, not the eager-load exit 1 a client-building verb
    would give), runs no collector, and touches no filesystem. It structurally
    cannot regress any existing behavior -- the same envelope that made ``policy``
    a clean ship. It always returns 0; ``--json`` swaps the human catalog for one
    explicit-allowlist object (rendering selection only -- there is no input to
    fail on). It is the L1 action-surface window of the transparency arc: policy
    (autonomy rules) -> signals (L2 perception) -> tools (L1 action surface) ->
    explain (why THIS goal) -> trace (what a run did).
    """
    if args.json:
        # The ENTIRE stdout must parse as one JSON object; no human trailer.
        print(json.dumps(_tools_json_payload(), indent=2))
    else:
        print(_render_tools())
    return 0


def _cmd_collectors(args: argparse.Namespace) -> int:
    """collectors: print the L2 perception surface (read-only, LLM-free, zero-input).

    WHY it consults NOTHING -- not even the ``_settings`` seam ``policy`` uses:
    the collector SET is STATIC (the seventeen registered collectors and their
    curated descriptions do not depend on any env override, workspace, signal, or
    LLM). So this handler resolves no settings, builds no ``create_client`` (an
    inert/bad ``--scripted-responses`` path is simply never opened -- exit 0, not
    the eager-load exit 1 a client-building verb would give), runs no collector,
    and touches no filesystem. It structurally cannot regress any existing
    behavior -- the same envelope that made ``policy``/``tools`` a clean ship. It
    always returns 0: ``--json`` swaps the human catalog for one explicit-allowlist
    object and ``--kind`` narrows the listing, both pure rendering selections with
    no input for the HANDLER to fail on -- an unknown ``--kind`` is rejected by
    argparse (exit 2) before this function is ever entered, and a valid one always
    matches exactly one collector because name <-> kind is a bijection. It is the
    context-free FRONT DOOR of the transparency arc: collectors (what perceivers
    exist, and which signal kind each emits) -> signals (raw output for a
    workspace, filterable by that kind) -> scan (proposals) -> explain (why THIS
    goal) -> trace (what a run did).
    """
    if args.json:
        # The ENTIRE stdout must parse as one JSON object; no human trailer.
        print(json.dumps(_collectors_json_payload(args.kind), indent=2))
    else:
        print(_render_collectors(args.kind))
    return 0


def _cmd_providers(args: argparse.Namespace) -> int:
    """providers: print the L0 LLM-backend surface (read-only, LLM-free, zero-input).

    WHY it consults NOTHING -- not even the ``_settings`` seam ``policy`` uses:
    the provider surface is STATIC (the accepted providers, their offline/cloud
    kind, and the pip package each needs do not depend on any env override,
    workspace, slate, or LLM). So this handler resolves no settings, builds no
    ``create_client`` (so a bad ``--provider`` is never validated and an
    inert/nonexistent ``--scripted-responses`` path is never opened -- exit 0, not
    the eager-load exit 1 a client-building verb would give), runs no collector,
    and touches no filesystem. It structurally cannot regress any existing behavior
    -- the same envelope that made ``policy``/``tools``/``collectors`` a clean ship.
    It always returns 0; ``--json`` swaps the human catalog for one
    explicit-allowlist object (rendering selection only -- there is no input to fail
    on). It closes the transparency arc across all four architectural seams: policy
    (L2 autonomy rules) -> collectors (L2 perception) -> tools (L1 action surface)
    -> providers (L0 LLM backend).
    """
    if args.json:
        # The ENTIRE stdout must parse as one JSON object; no human trailer.
        print(json.dumps(_providers_json_payload(), indent=2))
    else:
        print(_render_providers())
    return 0


if __name__ == "__main__":  # pragma: no cover - module entry convenience
    raise SystemExit(main())
