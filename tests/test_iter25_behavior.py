"""Black-box behavior tests for iteration 25 --- ``pla -v/--verbose`` runtime log
verbosity + the L1 executor's live "L0 retry" INFO record.

Feature under test: a repeatable ``-v``/``--verbose`` ``count`` flag on the shared
globals parent parser (accepted AFTER any subcommand, like ``--provider``) that
configures the ``proactive_loop`` package logger ONCE per process via a single
guarded ``StreamHandler(sys.stderr)`` --- level 0 (no flag) is a strict no-op,
``-v`` -> INFO, ``-vv`` -> DEBUG --- so the L0 retry/backoff self-healing becomes
visible on stderr *as it happens* while stdout stays pipe-clean. Independently,
the executor now emits, unconditionally at the source (module logger
``proactive_loop.loop.executor``), one INFO record per RECOVERED backoff-retry
whose message begins ``L0 retry `` and carries the 1-based attempt number; the
``RunState.retries`` counter (iter-08) is preserved.

ISOLATION CONTRACT (honored): these tests are written strictly against THIS
iteration's public contract --- the spec's "Expected Behaviors" (``pm.md``),
``README.md``, and ``SPEC.md`` section 4.4/4.5 --- and drive ONLY documented
public surfaces: the ``pla`` CLI via ``proactive_loop.cli.main(argv) -> int`` (its
observable stdout/stderr/exit codes), the public ``proactive_loop.loop.executor.
GoalLoop`` API, the two importable helpers the spec names by fully-qualified path
(``proactive_loop.cli._verbosity_to_level`` and the sentinel handler type
``proactive_loop.cli._CliLogHandler``), and the ``__version__`` metadata. **No
file under ``src/`` was read, no engineer/reviewer notes were read, and no ``git
diff`` was consulted.** Every test is fully offline: zero network, zero API keys,
driven through the scripted provider seam; workspaces/state dirs are synthetic
``tmp_path`` (or the repo's own public offline demo fixtures, exactly as
``tests/test_cli_integration.py`` does) --- never the in-repo source tree.

Behavior 4 note: ``_configure_logging`` mutates PROCESS-GLOBAL logging state, so
every test runs inside an autouse fixture that snapshots and fully restores the
``proactive_loop`` logger's handler list + level. This guarantees the module
leaks nothing into the rest of the suite --- a stale stderr handler bound to a
torn-down capsys stream is exactly the cross-test hazard the fixture prevents.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path

import pytest

from proactive_loop import __version__
from proactive_loop.cli import _CliLogHandler, _verbosity_to_level, main
from proactive_loop.config import RetryPolicy, Settings
from proactive_loop.llm.client import ScriptedLLMClient
from proactive_loop.loop.executor import GoalLoop
from proactive_loop.loop.tools import ToolRegistry
from proactive_loop.models import CandidateGoal, RunStatus

REPO = Path(__file__).resolve().parents[1]
# The public offline demo artifacts (runner-location-independent).
FIXTURE = REPO / "examples" / "fixture_workspace"
SCRIPT = REPO / "examples" / "scripted_responses.json"

_PKG = "proactive_loop"
_EXEC_LOGGER = "proactive_loop.loop.executor"


# ---------------------------------------------------------------------------
# Isolation fixture + helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _restore_package_logger():
    """Snapshot + restore the package logger so no test leaks logging state
    (a stderr handler bound to a torn-down capsys stream is the hazard)."""
    logger = logging.getLogger(_PKG)
    saved_handlers = list(logger.handlers)
    saved_level = logger.level
    try:
        yield logger
    finally:
        for h in list(logger.handlers):
            if h not in saved_handlers:
                logger.removeHandler(h)
        logger.handlers[:] = saved_handlers
        logger.setLevel(saved_level)


def _cli_handlers(logger: logging.Logger) -> list[logging.Handler]:
    """The sentinel-identifiable handlers this CLI attaches --- never any other."""
    return [h for h in logger.handlers if isinstance(h, _CliLogHandler)]


def _runs_argv(state_dir: Path, *extra: str) -> list[str]:
    return ["runs", "--state-dir", str(state_dir), *extra]


def _scan_argv(workspace: Path, state_dir: Path, *extra: str) -> list[str]:
    return [
        "scan",
        "--workspace", str(workspace),
        "--provider", "scripted",
        "--scripted-responses", str(SCRIPT),
        "--state-dir", str(state_dir),
        *extra,
    ]


def _goal() -> CandidateGoal:
    return CandidateGoal(
        title="Write a learning plan",
        rationale="capture next steps",
        suggested_first_steps=["draft learning_plan.md"],
    )


def _tools(tmp_path: Path) -> ToolRegistry:
    return ToolRegistry(
        workspace_root=tmp_path / "workspace",
        artifacts_dir=tmp_path / "artifacts",
    )


def _plan(tool: str, args: dict) -> dict:
    return {
        "tag": "plan",
        "text": json.dumps({"thought": "do it", "action": {"tool": tool, "args": args}}),
    }


def _check(done: bool, reason: str = "") -> dict:
    return {"tag": "check", "text": json.dumps({"done": done, "reason": reason})}


def _no_sleep(_: float) -> None:
    """Injected sleep spy that never waits --- keeps the retry test wait-free."""


# ===========================================================================
# Behavior 1 --- the flag exists and is inherited by every subcommand
# ===========================================================================


def test_b1_verbose_accepted_after_runs_subcommand(tmp_path):
    """`-v` is accepted AFTER the verb (shared globals parent parser); an empty
    state dir still exits 0."""
    assert main(_runs_argv(tmp_path / "state", "-v")) == 0


def test_b1_verbose_accepted_after_scan_subcommand(tmp_path):
    """`scan ... -v ...` (flag interleaved after the verb) exits 0 offline."""
    rc = main(_scan_argv(FIXTURE, tmp_path / "state", "-v"))
    assert rc == 0


@pytest.mark.parametrize("flag", ["-v", "-vv", "-vvv"])
def test_b1_repeatable_count_flag_never_errors(tmp_path, flag):
    """A repeatable count flag (`-v`/`-vv`/`-vvv`) is a valid arg on every verb;
    none is an argparse usage error (exit 2) or a crash."""
    assert main(_runs_argv(tmp_path / "state", flag)) == 0


def test_b1_verbose_does_not_change_runs_json_stdout(tmp_path, capsys):
    """Supplying `-v` NEVER changes a verb's stdout: `runs --json` is byte-
    identical with and without `-v` (same empty state dir -> `[]`)."""
    state = tmp_path / "state"
    assert main(_runs_argv(state, "--json")) == 0
    plain = capsys.readouterr().out
    assert main(_runs_argv(state, "-v", "--json")) == 0
    verbose = capsys.readouterr().out
    assert verbose == plain
    # And it really is machine-readable JSON, not a log-polluted stream.
    assert json.loads(plain) == []


# ===========================================================================
# Behavior 2 --- _verbosity_to_level is a pure, importable mapper
# ===========================================================================


@pytest.mark.parametrize(
    "count, expected",
    [
        (-3, logging.WARNING),
        (0, logging.WARNING),   # 30
        (1, logging.INFO),      # 20
        (2, logging.DEBUG),     # 10
        (5, logging.DEBUG),
    ],
)
def test_b2_maps_count_to_level(count, expected):
    assert _verbosity_to_level(count) == expected


def test_b2_returns_canonical_stdlib_ints():
    assert _verbosity_to_level(0) == 30
    assert _verbosity_to_level(1) == 20
    assert _verbosity_to_level(2) == 10


def test_b2_is_pure_no_logger_mutation():
    """Calling the mapper mutates no logger/handler/global state."""
    logger = logging.getLogger(_PKG)
    before_handlers = list(logger.handlers)
    before_level = logger.level
    for c in (-1, 0, 1, 2, 9):
        _verbosity_to_level(c)
    assert list(logger.handlers) == before_handlers
    assert logger.level == before_level


# ===========================================================================
# Behavior 3 --- level 0 (no `-v`) is a strict no-op
# ===========================================================================


def test_b3_no_v_attaches_no_handler_and_leaves_level(tmp_path):
    """After a verb run WITHOUT `-v`, the CLI has attached NO handler to the
    package logger and has NOT changed its level."""
    logger = logging.getLogger(_PKG)
    before_level = logger.level
    assert main(_runs_argv(tmp_path / "state")) == 0
    assert _cli_handlers(logger) == []
    assert logger.level == before_level


def test_b3_no_v_scan_is_also_a_no_op(tmp_path):
    """The no-op holds for an LLM-driving verb (scan) too, not just `runs`."""
    logger = logging.getLogger(_PKG)
    before_level = logger.level
    assert main(_scan_argv(FIXTURE, tmp_path / "state")) == 0
    assert _cli_handlers(logger) == []
    assert logger.level == before_level


# ===========================================================================
# Behavior 4 --- verbose attaches exactly ONE stderr handler, idempotently
# ===========================================================================


def test_b4_verbose_attaches_exactly_one_stderr_handler_idempotent(tmp_path):
    """N>=1 verbose `main()` calls in one process -> at most ONE CLI-attached
    handler (never N stacked); it is a StreamHandler on sys.stderr; the package
    logger's effective level is INFO for `-v`."""
    logger = logging.getLogger(_PKG)
    for _ in range(3):
        assert main(_runs_argv(tmp_path / "state", "-v")) == 0
    attached = _cli_handlers(logger)
    assert len(attached) == 1
    handler = attached[0]
    assert isinstance(handler, logging.StreamHandler)
    assert handler.stream is sys.stderr
    assert logger.level == logging.INFO


def test_b4_vv_sets_debug_level_single_handler(tmp_path):
    """`-vv` maps to DEBUG on the package logger, still one handler."""
    logger = logging.getLogger(_PKG)
    assert main(_runs_argv(tmp_path / "state", "-vv")) == 0
    assert len(_cli_handlers(logger)) == 1
    assert logger.level == logging.DEBUG


def test_b4_never_touches_the_root_logger(tmp_path):
    """The configurator must not call logging.basicConfig / touch the root."""
    root = logging.getLogger()
    root_handlers_before = list(root.handlers)
    root_level_before = root.level
    assert main(_runs_argv(tmp_path / "state", "-vv")) == 0
    assert list(root.handlers) == root_handlers_before
    assert root.level == root_level_before


# ===========================================================================
# Behavior 5 --- logs go to stderr, never stdout
# ===========================================================================


def test_b5_verbose_json_stdout_is_pure_json(tmp_path, capsys):
    """Authoritative Behavior-5 check: stdout under `-v --json` is pure JSON."""
    assert main(_runs_argv(tmp_path / "state", "-v", "--json")) == 0
    captured = capsys.readouterr()
    parsed = json.loads(captured.out)  # raises if a log line polluted stdout
    assert parsed == []
    # No log record can appear on stdout; the "L0 retry" marker (or any level
    # tag) must never leak there.
    assert "L0 retry" not in captured.out


# ===========================================================================
# Behavior 6 --- the L1 executor emits one INFO record per RECOVERED retry
# ===========================================================================


def test_b6_executor_emits_one_info_per_recovered_retry(tmp_path, caplog):
    """Throttle the PLAN twice then succeed (injected no-op sleep): the executor
    emits EXACTLY 2 INFO records on `proactive_loop.loop.executor`, each message
    beginning `L0 retry ` and carrying the 1-based attempt number (1, then 2).
    Emission is UNCONDITIONAL at the source --- this test never touches the CLI
    or configures any handler; `caplog.set_level(..., logger=...)` alone
    captures it. `RunState.retries` is preserved (== 2)."""
    tools = _tools(tmp_path)
    client = ScriptedLLMClient(
        [
            {"tag": "plan", "raise": "throttle"},
            {"tag": "plan", "raise": "throttle"},
            _plan("write_file", {"path": "out.md", "content": "done"}),
            _check(True, "complete"),
        ]
    )
    settings = Settings(
        retry=RetryPolicy(
            max_attempts=5, base_backoff_sec=1.0, backoff_factor=2.0, jitter_frac=0.0
        )
    )
    loop = GoalLoop(client, settings, tools, sleep=_no_sleep)

    caplog.set_level(logging.INFO, logger=_EXEC_LOGGER)
    state = loop.run(_goal())

    assert state.status is RunStatus.DONE
    # The iter-08 counter is preserved, not replaced.
    assert state.retries == 2

    records = [
        r for r in caplog.records
        if r.name == _EXEC_LOGGER and r.levelno == logging.INFO
        and r.getMessage().startswith("L0 retry ")
    ]
    assert len(records) == 2, (
        "throttle-twice-then-succeed must emit exactly 2 'L0 retry' INFO "
        f"records; got {len(records)}: {[r.getMessage() for r in records]}"
    )
    attempts = []
    for r in records:
        remainder = r.getMessage()[len("L0 retry "):]
        m = re.search(r"\d+", remainder)
        assert m is not None, (
            f"the retry message must carry the attempt number; got {r.getMessage()!r}"
        )
        attempts.append(int(m.group()))
    assert attempts == [1, 2], (
        f"records must carry the 1-based attempt numbers 1 then 2; got {attempts}"
    )


def test_b6_clean_run_emits_zero_retry_records(tmp_path, caplog):
    """A run that recovers zero retries emits zero 'L0 retry' records and leaves
    RunState.retries == 0."""
    tools = _tools(tmp_path)
    client = ScriptedLLMClient(
        [
            _plan("write_file", {"path": "x.md", "content": "hi"}),
            _check(True, "done"),
        ]
    )
    loop = GoalLoop(client, Settings(), tools, sleep=_no_sleep)

    caplog.set_level(logging.INFO, logger=_EXEC_LOGGER)
    state = loop.run(_goal())

    assert state.status is RunStatus.DONE
    assert state.retries == 0
    retry_records = [
        r for r in caplog.records
        if r.name == _EXEC_LOGGER and r.getMessage().startswith("L0 retry ")
    ]
    assert retry_records == []


def test_b6_emission_is_independent_of_any_cli_handler(tmp_path, caplog):
    """The retry INFO record is emitted at the source with NO CLI verbosity
    config in play --- no `_CliLogHandler` is ever attached during this run."""
    tools = _tools(tmp_path)
    client = ScriptedLLMClient(
        [
            {"tag": "plan", "raise": "throttle"},
            _plan("write_file", {"path": "y.md", "content": "z"}),
            _check(True, "ok"),
        ]
    )
    settings = Settings(
        retry=RetryPolicy(max_attempts=5, base_backoff_sec=1.0, jitter_frac=0.0)
    )
    loop = GoalLoop(client, settings, tools, sleep=_no_sleep)

    caplog.set_level(logging.INFO, logger=_EXEC_LOGGER)
    state = loop.run(_goal())

    assert state.retries == 1
    assert _cli_handlers(logging.getLogger(_PKG)) == []
    n = len([
        r for r in caplog.records
        if r.name == _EXEC_LOGGER and r.getMessage().startswith("L0 retry ")
    ])
    assert n == 1


# ===========================================================================
# Behavior 7 --- no regression when `-v` is absent
# ===========================================================================


def test_b7_version_is_unchanged_additive_flag_no_bump():
    """`-v` is additive behavior --- no version bump."""
    assert __version__ == "0.1.1"


def test_b7_no_v_runs_json_matches_verbose_stdout(tmp_path, capsys):
    """Regression proof at the CLI level: a verb's stdout is unchanged by `-v`
    (empty-state `runs --json` is `[]` either way)."""
    state = tmp_path / "state"
    assert main(_runs_argv(state, "--json")) == 0
    without = capsys.readouterr().out
    assert main(_runs_argv(state, "-v", "--json")) == 0
    with_v = capsys.readouterr().out
    assert without == with_v == "[]\n" or json.loads(without) == json.loads(with_v) == []
