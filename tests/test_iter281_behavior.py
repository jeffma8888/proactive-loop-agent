"""Black-box oracle for foundry iteration 321 (state-dir iterations 467 and 468): ``run --max-seconds N`` /
``PLA_MAX_SECONDS`` -- a wall-clock ceiling on the L1 budget, written by the tester from the spec
alone (pm.md ``## Feature``, README "Configuration" table, SPEC.md ``pla run`` entry). Iteration 467's
tree was reverted on ONE byte pin (SPEC.md over 94,400 B); iteration 468 re-landed it with the
same-commit ``SPEC_ARCHIVE.md`` relocation, and the helpers 5b, 7 and 8 below grade that re-land.

WHY THIS MODULE EXISTS. The L1 budget bounded iterations and LLM calls but never wall-clock,
although L0 backoff can stretch one iteration to minutes. ``Settings.max_seconds`` (env
``PLA_MAX_SECONDS``, flag ``run --max-seconds N``) stops the loop on the EXISTING
``BUDGET_EXHAUSTED`` path once the run has executed for N seconds, measured by an injectable
monotonic ``clock`` that mirrors the injectable ``sleep`` -- so the whole contract is provable
offline with a scripted clock and no real waiting.

WHAT THIS MODULE GRADES (six behaviors, one per helper below; collected as ONE item because
``make readme-headroom`` read ``binding_headroom=6 == MIN_BINDING_HEADROOM`` on the engineer's tree
-- zero free items -- so this module is funded 1:1 by retiring the byte-identical twin
``test_iter214::test_b8_the_settled_row_brake_still_reports_a_clean_index``):
(1) ``Settings.max_seconds`` defaults to ``None`` (no ceiling), ``PLA_MAX_SECONDS`` parses to a
float, and a ``from_env`` override beats the environment; (2) a mistyped, non-positive or
non-finite ``PLA_MAX_SECONDS`` is refused with an error naming the knob, and ``Settings``
refuses the same values directly; (3) with a ceiling, the loop stops ``BUDGET_EXHAUSTED`` and
the iteration in flight finishes (the check sits before PLAN, never mid-iteration); (4) with no
ceiling the clock is irrelevant, with a generous ceiling a run still reaches ``DONE``, and a
``GoalLoop`` built WITHOUT a ``clock`` argument (the pre-feature construction) is unchanged;
(5) ``run --max-seconds`` refuses ``0``, negatives, non-numbers and non-finite values as an
argparse usage error (exit 2) at PARSE time, before any state dir exists; (5b) the ACCEPTED value
reaches the loop -- a real offline ``pla run --json`` under a microscopic ceiling publishes
``status: budget_exhausted`` after at most one iteration where the unbounded fixture run reaches
``done`` in three (a refusal-only oracle is satisfied by a flag that does not exist, because
argparse's ``unrecognized arguments`` carries the identical exit-2 signature); (6) the flag is
documented consistently in ``run --help``, the README configuration table and SPEC.md;
(7) SPEC.md holds under its 94,400-B pin because the ``### 4.3 scout`` synthesizer prose (16 lines,
1,130 B) moved VERBATIM into ``SPEC_ARCHIVE.md`` under a dated heading between the ``---`` rule and
the iter-319 ``### 4.4`` heading, leaving exactly one <= 500-B summary bullet that points at the
archive; (8) the ROADMAP Done ledger records the ship in exactly one ``#300`` row that names the
flag, the env twin and the relocation; (9) this module holds NO size opinion on ROADMAP.md
(``roadmap_size_bounds`` of its own source is empty), so the test_iter172 census grades it the
same in the worktree and in preship's fresh clone -- the copied 35k pin that reverted iter 468.

ISOLATION CONTRACT (honored). Drives ``proactive_loop.config.Settings``,
``proactive_loop.loop.executor.GoalLoop``, ``proactive_loop.cli.main`` and the installed ``pla``
console script as an embedding host would, plus the four Markdown files as a reader would; no file
under ``src/`` was read, no engineer/reviewer notes, no ``git diff``. Deterministic and offline:
the only LLMs are ``ScriptedLLMClient`` and the bundled ``scripted`` provider, and every injected
clock is a list of numbers. The one real-clock arm (5b) asserts only what a 0.1-ms ceiling makes
inevitable -- fewer than the fixture's three iterations -- never a timing.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Final

import pytest
from pydantic import ValidationError

from proactive_loop.cli import _settings, build_parser, main
from proactive_loop.config import Settings
from proactive_loop.llm.client import ScriptedLLMClient
from proactive_loop.loop.executor import GoalLoop
from proactive_loop.loop.tools import ToolRegistry
from proactive_loop.models import CandidateGoal, RunStatus, StepKind
from tests.test_iter172_behavior import roadmap_size_bounds

REPO: Final[Path] = Path(__file__).resolve().parents[1]
README: Final[Path] = REPO / "README.md"
SPEC: Final[Path] = REPO / "SPEC.md"
SPEC_ARCHIVE: Final[Path] = REPO / "SPEC_ARCHIVE.md"
ROADMAP: Final[Path] = REPO / "ROADMAP.md"
FIXTURE: Final[Path] = REPO / "examples" / "fixture_workspace"
SCRIPT: Final[Path] = REPO / "examples" / "scripted_responses.json"

#: Behavior 5b. A ceiling no real iteration can finish under; the unbounded fixture run
#: (pinned by tests/test_iter253_behavior.py) reaches ``done`` in three iterations.
MICROSCOPIC_CEILING: Final[str] = "0.0001"
UNBOUNDED_FIXTURE_ITERATIONS: Final[int] = 3
#: Same stamp age as tests/test_iter253_behavior.py: every fixture mtime one known age, so the
#: collectors' within-days windows read identically here and in a fresh clone.
STAMP_AGE_SEC: Final[int] = 6 * 60 * 60

#: Behavior 7. The relocation that bought the byte headroom (pm.md recipe step 2).
SPEC_CEILING_BYTES: Final[int] = 94_400
SPEC_SECTION_HEADING: Final[str] = "### 4.3 scout"
RELOCATED_HEADING: Final[str] = "### 4.3 scout -- synthesizer.py (relocated at foundry iter 321)"
NEXT_ARCHIVE_HEADING: Final[str] = "### 4.4 loop -- executor.py (relocated at foundry iter 319)"
RELOCATED_FIRST_LINE: Final[str] = (
    "- Builds a compact prompt from signals (grouped by kind, capped length; within"
)
RELOCATED_LAST_LINE: Final[str] = "  still surface immediately."
RELOCATED_LINE_COUNT: Final[int] = 16
RELOCATED_BYTES: Final[int] = 1_130
SUMMARY_TAIL: Final[str] = "Settled contract prose: see [SPEC_ARCHIVE.md](SPEC_ARCHIVE.md)."
SUMMARY_MAX_BYTES: Final[int] = 500
#: What the surviving summary bullet must still name (pm.md recipe step 2).
SUMMARY_TOKENS: Final[tuple[str, ...]] = (
    "grouped by kind",
    "highest-weight-first",
    "`client.complete(...)`",
    "`SYNTHESIZE_TAG`",
    "`parse_json_block`",
    "`CandidateGoal`",
    "normalized title",
    "`with_retry`",
    "`sleep`",
)
LLM_CONTRACT_BULLET: Final[str] = "- LLM JSON contract"

#: Behavior 6. The README sentence that counts the settings with a direct CLI flag (6 -> 7).
README_FLAG_COUNT_SENTENCE: Final[str] = "Seven settings also have a direct CLI flag"

#: Behavior 8. The one ledger row.
LEDGER_ROW_PREFIX: Final[str] = "- #300 "
SHIP_TAG: Final[str] = "(foundry iter 321)"
LEDGER_HEADING_PREFIX: Final[str] = "## Done ledger"

ENV_VAR: Final[str] = "PLA_MAX_SECONDS"
FLAG: Final[str] = "--max-seconds"
#: Values the contract refuses everywhere (env, model, flag): non-positive or non-finite.
REJECTED_NUMERIC: Final[tuple[str, ...]] = ("0", "-1", "inf", "-inf", "nan")
NOT_A_NUMBER: Final[str] = "soon"


# --- fixtures (same shape as tests/test_loop.py) ----------------------------------------------


def _goal() -> CandidateGoal:
    return CandidateGoal(
        title="Write a learning plan",
        rationale="capture next steps",
        suggested_first_steps=["draft learning_plan.md"],
    )


def _plan(tool: str, args: dict[str, str]) -> dict[str, str]:
    return {"tag": "plan", "text": json.dumps({"thought": "do it", "action": {"tool": tool, "args": args}})}


def _check(done: bool, reason: str = "") -> dict[str, str]:
    return {"tag": "check", "text": json.dumps({"done": done, "reason": reason})}


def _tools(tmp_path: Path) -> ToolRegistry:
    return ToolRegistry(workspace_root=tmp_path / "workspace", artifacts_dir=tmp_path / "artifacts")


def _no_sleep(_: float) -> None:
    """Sleep spy that never waits."""


def _never_done_client(iterations: int) -> ScriptedLLMClient:
    """PLAN/CHECK pairs whose CHECK never reports done, for ``iterations`` iterations."""
    script: list[dict[str, str]] = []
    for i in range(iterations):
        script.append(_plan("write_file", {"path": f"note{i}.md", "content": f"step {i}\n"}))
        script.append(_check(False, "keep going"))
    return ScriptedLLMClient(script)


class _ScriptedClock:
    """Monotonic clock replaying a fixed reading sequence; the last reading repeats forever."""

    def __init__(self, readings: list[float]) -> None:
        self._readings = list(readings)
        self.calls = 0

    def __call__(self) -> float:
        self.calls += 1
        index = min(self.calls - 1, len(self._readings) - 1)
        return self._readings[index]


class _ArtifactTriggeredClock:
    """Monotonic clock that reads ``before`` until ``trigger`` exists on disk, then ``after``.

    Keys the jump on an observable side effect of iteration 1 (its written artifact) rather than
    on a call count, so the oracle does not depend on HOW OFTEN the loop consults its clock.
    """

    def __init__(self, trigger: Path, *, before: float, after: float) -> None:
        self._trigger = trigger
        self._before = before
        self._after = after
        self.calls = 0

    def __call__(self) -> float:
        self.calls += 1
        return self._after if self._trigger.exists() else self._before


def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_VAR, raising=False)


# --- (1) Settings surface ---------------------------------------------------------------------


def _b1_settings_default_is_no_ceiling_env_parses_and_override_wins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clean_env(monkeypatch)
    assert Settings().max_seconds is None, "no ceiling unless asked for"
    assert Settings.from_env().max_seconds is None, "from_env() with nothing set == bare Settings()"
    assert Settings(max_seconds=90).max_seconds == 90.0

    monkeypatch.setenv(ENV_VAR, "12.5")
    assert Settings.from_env().max_seconds == 12.5, "PLA_MAX_SECONDS is a float, not an int"
    assert Settings.from_env(max_seconds=3).max_seconds == 3.0, "explicit override beats the env"


# --- (2) refusals at the Settings / env layer -------------------------------------------------


def _b2_env_and_model_refuse_non_numeric_non_positive_and_non_finite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clean_env(monkeypatch)
    monkeypatch.setenv(ENV_VAR, NOT_A_NUMBER)
    with pytest.raises(ValueError) as excinfo:
        Settings.from_env()
    message = str(excinfo.value)
    assert ENV_VAR in message and "number" in message and repr(NOT_A_NUMBER) in message, message

    for raw in REJECTED_NUMERIC:
        monkeypatch.setenv(ENV_VAR, raw)
        with pytest.raises(ValueError):  # ValidationError is a ValueError subclass
            Settings.from_env()
        with pytest.raises(ValidationError) as direct:
            Settings(max_seconds=float(raw))
        assert "max_seconds" in str(direct.value), f"{raw!r} must be refused on the field itself"

    _clean_env(monkeypatch)
    assert Settings(max_seconds=0.001).max_seconds == 0.001, "any positive finite value is accepted"


# --- (3) the ceiling stops the loop AFTER the in-flight iteration --------------------------------


def _b3_ceiling_stops_budget_exhausted_after_the_iteration_in_flight(tmp_path: Path) -> None:
    tools = _tools(tmp_path)
    client = _never_done_client(iterations=4)
    # The clock is pinned at 100.0 until iteration 1's ACT has landed ``note0.md``; from then on
    # it reads 111.0, past the 10 s ceiling. So the check before PLAN 1 sees 0 s elapsed and the
    # check before PLAN 2 trips -- no matter how many times the loop consults the clock.
    first_artifact = tmp_path / "artifacts" / "note0.md"
    clock = _ArtifactTriggeredClock(first_artifact, before=100.0, after=111.0)
    loop = GoalLoop(client, Settings(max_iterations=4, max_seconds=10), tools, sleep=_no_sleep, clock=clock)

    state = loop.run(_goal())

    assert state.status is RunStatus.BUDGET_EXHAUSTED
    assert state.iterations_used == 1, "the iteration in flight finished; the NEXT PLAN never started"
    assert state.llm_calls_used == 2, "one PLAN + one CHECK; no partial iteration"
    assert [s.kind for s in state.steps] == [StepKind.PLAN, StepKind.ACT, StepKind.CHECK]
    assert (tmp_path / "artifacts" / "note0.md").read_text() == "step 0\n"
    assert not (tmp_path / "artifacts" / "note1.md").exists()
    assert clock.calls >= 2, "the injected clock, not the wall, was consulted"


# --- (4) no ceiling => clock irrelevant; generous ceiling => DONE as before -----------------------


def _b4_no_ceiling_ignores_the_clock_and_a_generous_ceiling_still_reaches_done(tmp_path: Path) -> None:
    # No ceiling: a clock racing ahead by a billion seconds changes nothing.
    tools = _tools(tmp_path)
    racing = _ScriptedClock([0.0, 1e9, 2e9, 3e9, 4e9])
    loop = GoalLoop(_never_done_client(iterations=3), Settings(max_iterations=3), tools, sleep=_no_sleep, clock=racing)
    state = loop.run(_goal())
    assert state.status is RunStatus.BUDGET_EXHAUSTED, "max_iterations is still the binding budget"
    assert state.iterations_used == 3

    # Generous ceiling: a two-iteration run that finishes inside the window is DONE, not cut.
    tools2 = _tools(tmp_path / "second")
    client2 = ScriptedLLMClient(
        [
            _plan("write_file", {"path": "learning_plan.md", "content": "step 1\n"}),
            _check(False, "written, verifying"),
            _plan("read_file", {"path": "learning_plan.md"}),
            _check(True, "artifact present"),
        ]
    )
    slow = _ScriptedClock([0.0, 1.0, 2.0, 3.0])
    loop2 = GoalLoop(client2, Settings(max_seconds=600), tools2, sleep=_no_sleep, clock=slow)
    state2 = loop2.run(_goal())
    assert state2.status is RunStatus.DONE
    assert state2.iterations_used == 2

    # Default clock (no ``clock`` argument) and no ceiling: the pre-feature construction still
    # works and the run is indistinguishable from the injected-clock run above.
    tools3 = _tools(tmp_path / "third")
    client3 = ScriptedLLMClient(
        [
            _plan("write_file", {"path": "learning_plan.md", "content": "step 1\n"}),
            _check(False, "written, verifying"),
            _plan("read_file", {"path": "learning_plan.md"}),
            _check(True, "artifact present"),
        ]
    )
    state3 = GoalLoop(client3, Settings(), tools3, sleep=_no_sleep).run(_goal())
    assert state3.status is RunStatus.DONE, "no-ceiling default construction is unchanged"
    assert state3.iterations_used == state2.iterations_used == 2
    assert state3.llm_calls_used == state2.llm_calls_used == 4
    assert [s.kind for s in state3.steps] == [s.kind for s in state2.steps], (
        "default clock and injected clock yield the same step sequence when no ceiling binds"
    )


# --- (5) parse-time refusal on the CLI ---------------------------------------------------------


def _b5_run_max_seconds_refuses_bad_values_at_parse_time_with_exit_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _clean_env(monkeypatch)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    state_dir = tmp_path / "state"
    for raw in (*REJECTED_NUMERIC, NOT_A_NUMBER):
        with pytest.raises(SystemExit) as excinfo:
            main(["run", "--workspace", str(workspace), "--state-dir", str(state_dir), FLAG, raw])
        assert excinfo.value.code == 2, f"{raw!r} must be an argparse usage error"
        captured = capsys.readouterr()
        assert FLAG in captured.err, f"stderr must name the flag for {raw!r}; got {captured.err!r}"
        assert captured.out == "", "a usage error prints nothing on stdout"
        assert not state_dir.exists(), f"{raw!r} was refused at PARSE time, so no state dir may exist"
        assert not (workspace / ".pla_runs").exists()

    # Positive path (iter-468 reviewer's request): the accepted value binds as a float on the
    # namespace, and the flag wins over the env twin when both are set.
    args = build_parser().parse_args(["run", "--workspace", str(workspace), FLAG, "2.5"])
    assert args.max_seconds == 2.5, "an accepted value binds on the parsed namespace as a float"
    monkeypatch.setenv(ENV_VAR, "7")
    assert _settings(args, workspace_root=workspace).max_seconds == 2.5, (
        "the --max-seconds flag wins over PLA_MAX_SECONDS when both are given"
    )
    _clean_env(monkeypatch)
    assert not state_dir.exists(), "parsing and settings-building never create a state dir"


# --- (5b) the accepted value reaches the loop: a real offline run under a tiny ceiling ---------


def _console_script() -> Path:
    """The installed ``pla`` entry point next to the running interpreter (tests/test_iter253 shape)."""
    bindir = Path(sys.executable).parent
    candidates = [bindir / "pla", bindir / "pla.exe"]
    which = shutil.which("pla")
    if which:
        candidates.append(Path(which))
    script = next((c for c in candidates if c.is_file()), None)
    assert script is not None, f"the `pla` console script must be installed; searched {candidates}"
    return script


def _stamped_workspace(root: Path) -> Path:
    """A private copy of the offline fixture workspace, every mtime one known age."""
    dest = root / "workspace"
    shutil.copytree(FIXTURE, dest)
    stamp = time.time() - STAMP_AGE_SEC
    for path in [dest, *dest.rglob("*")]:
        os.utime(path, (stamp, stamp))
    return dest


def _b5b_an_accepted_max_seconds_reaches_the_loop_through_the_cli(tmp_path: Path) -> None:
    workspace = _stamped_workspace(tmp_path)
    state_dir = tmp_path / "state"
    env = {k: v for k, v in os.environ.items() if not k.startswith("PLA_")}
    proc = subprocess.run(
        [
            str(_console_script()),
            "run",
            "--workspace",
            str(workspace),
            "--provider",
            "scripted",
            "--scripted-responses",
            str(SCRIPT),
            "--state-dir",
            str(state_dir),
            "--json",
            FLAG,
            MICROSCOPIC_CEILING,
        ],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=180,
        env=env,
    )
    assert proc.returncode == 0, f"a bounded offline run exits 0; got {proc.returncode}\n{proc.stderr}"
    dispatched = json.loads(proc.stdout)["dispatched"]
    assert isinstance(dispatched, dict), "the run must dispatch for its budget to be observable"
    assert dispatched["status"] == "budget_exhausted", (
        f"{FLAG} {MICROSCOPIC_CEILING} must stop the loop on the BUDGET_EXHAUSTED path; "
        f"got {dispatched['status']!r} -- the parsed flag never reached Settings"
    )
    assert dispatched["iterations_used"] <= 1 < UNBOUNDED_FIXTURE_ITERATIONS, (
        "the ceiling is checked before each PLAN, so at most the iteration in flight finishes"
    )
    assert dispatched["llm_calls_used"] == 2 * dispatched["iterations_used"], "no partial iteration"
    assert state_dir.is_dir(), "an ACCEPTED value runs for real and leaves its state dir"


# --- (6) documented in help, README and SPEC -----------------------------------------------------


def _b6_flag_is_documented_in_help_readme_and_spec(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["run", "--help"])
    assert excinfo.value.code == 0
    help_text = capsys.readouterr().out
    assert f"{FLAG} N" in help_text
    assert ENV_VAR in help_text, "help must point at the env twin"

    readme = README.read_text(encoding="utf-8")
    rows = [ln for ln in readme.splitlines() if ln.startswith(f"| `{ENV_VAR}` |")]
    assert len(rows) == 1, "exactly one configuration-table row for the new knob"
    assert f"| `{FLAG}` |" in rows[0], "the row names its flag equivalent"
    assert "*(none)*" in rows[0], "the documented default is no ceiling"
    assert "BUDGET_EXHAUSTED" in rows[0]
    assert readme.count(README_FLAG_COUNT_SENTENCE) == 1, (
        "the README counts the settings that have a CLI flag; the new knob makes it seven"
    )

    spec = SPEC.read_text(encoding="utf-8")
    assert f"[{FLAG} N]" in spec, "the `pla run` usage line carries the flag"
    assert ENV_VAR in spec
    assert not math.isfinite(float("inf"))  # documents why non-finite values are refused


# --- (7) SPEC.md under its byte pin via a verbatim relocation into SPEC_ARCHIVE.md ---------------


def _bullets(lines: list[str]) -> list[str]:
    """Markdown list items in ``lines``, continuation lines (two-space indent) folded in."""
    items: list[str] = []
    for line in lines:
        if line.startswith("- "):
            items.append(line)
        elif line.startswith("  ") and items:
            items[-1] += "\n" + line
    return items


def _b7_spec_holds_its_byte_pin_and_the_synthesizer_prose_moved_verbatim() -> None:
    spec_bytes = SPEC.read_bytes()
    assert len(spec_bytes) <= SPEC_CEILING_BYTES, (
        f"SPEC.md is {len(spec_bytes)} B, over the {SPEC_CEILING_BYTES}-B pin that reverted iter 467"
    )

    archive = SPEC_ARCHIVE.read_text(encoding="utf-8").splitlines()
    assert archive.count(RELOCATED_HEADING) == 1, "exactly one dated relocation heading"
    at = archive.index(RELOCATED_HEADING)
    above = next(ln for ln in reversed(archive[:at]) if ln.strip())
    assert above == "---", f"the heading sits right after the `---` rule; found {above!r} above it"
    assert archive[at + 1] == "", "one blank line between heading and prose"
    block = archive[at + 2 : at + 2 + RELOCATED_LINE_COUNT]
    assert len(block) == RELOCATED_LINE_COUNT
    assert block[0] == RELOCATED_FIRST_LINE
    assert block[-1] == RELOCATED_LAST_LINE
    moved = "\n".join(block) + "\n"
    assert len(moved.encode("utf-8")) == RELOCATED_BYTES, "the 16 lines are the 1,130 B that left SPEC.md"
    assert archive[at + 2 + RELOCATED_LINE_COUNT] == "", "one blank line after the prose"
    assert archive[at + 3 + RELOCATED_LINE_COUNT] == NEXT_ARCHIVE_HEADING, (
        "the 4.3 block is inserted BEFORE the iter-319 4.4 heading (test_iter279 keys on 4.4 -> 4.2)"
    )
    assert archive.count(NEXT_ARCHIVE_HEADING) == 1

    spec = SPEC.read_text(encoding="utf-8")
    assert moved not in spec and RELOCATED_FIRST_LINE not in spec, "relocated, not duplicated"
    spec_lines = spec.splitlines()
    assert spec_lines.count(SPEC_SECTION_HEADING) == 1, "the `### 4.3 scout` heading stays in SPEC.md"
    start = spec_lines.index(SPEC_SECTION_HEADING) + 1
    end = next(
        i for i in range(start, len(spec_lines)) if spec_lines[i].startswith(("## ", "### "))
    )
    bullets = _bullets(spec_lines[start:end])
    summaries = [b for b in bullets if b.endswith(SUMMARY_TAIL)]
    assert len(summaries) == 1, f"exactly one summary bullet points at the archive; got {len(summaries)}"
    summary = summaries[0]
    assert len(summary.encode("utf-8")) <= SUMMARY_MAX_BYTES, f"summary is {len(summary.encode())} B"
    missing = [token for token in SUMMARY_TOKENS if token not in summary]
    assert missing == [], f"the summary bullet must still name {missing}"
    assert sum(b.startswith(LLM_CONTRACT_BULLET) for b in bullets) == 1, "the LLM JSON contract bullet stays"


# --- (8) records: one ledger row -----------------------------------------------------------------


def _b8_roadmap_records_the_ship_in_one_ledger_row() -> None:
    roadmap_bytes = ROADMAP.read_bytes()
    lines = roadmap_bytes.decode("utf-8").splitlines()
    rows = [ln for ln in lines if ln.startswith(LEDGER_ROW_PREFIX)]
    assert len(rows) == 1, f"exactly one `{LEDGER_ROW_PREFIX.strip()}` ledger row; got {len(rows)}"
    row = rows[0]
    assert row.endswith(SHIP_TAG), f"the row carries the ship tag; got {row[-40:]!r}"
    for token in (f"run {FLAG}", ENV_VAR, "SPEC 4.3", "SPEC_ARCHIVE.md"):
        assert token in row, f"the ledger row must name {token!r}: {row}"
    assert sum(ln.endswith(SHIP_TAG) for ln in lines) == 1, "one row per ship, no second row"
    ledger_at = next(i for i, ln in enumerate(lines) if ln.startswith(LEDGER_HEADING_PREFIX))
    assert lines.index(row) > ledger_at, "the row sits under the Done ledger heading"

    # Behavior 9 (the clone-parity fix): this module asserts NOTHING about ROADMAP.md's size, so
    # the test_iter172 census reads it identically whether the file is tracked or not.
    own_source = Path(__file__).read_text(encoding="utf-8")
    assert roadmap_size_bounds(own_source) == (), (
        "test_iter281 must hold no ROADMAP.md size bound; test_iter241 owns that pin"
    )


# --- the single collected item: nine helpers, in spec order --------------------------------------


def test_run_max_seconds_wall_clock_ceiling_contract(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Behaviors 1-9 of the ``--max-seconds`` contract; each helper's assertion names its behavior."""
    b3, b4, b5, b5b = (tmp_path / "b3", tmp_path / "b4", tmp_path / "b5", tmp_path / "b5b")
    for scratch in (b3, b4, b5, b5b):
        scratch.mkdir()
    _b1_settings_default_is_no_ceiling_env_parses_and_override_wins(monkeypatch)
    _b2_env_and_model_refuse_non_numeric_non_positive_and_non_finite(monkeypatch)
    _b3_ceiling_stops_budget_exhausted_after_the_iteration_in_flight(b3)
    _b4_no_ceiling_ignores_the_clock_and_a_generous_ceiling_still_reaches_done(b4)
    _b5_run_max_seconds_refuses_bad_values_at_parse_time_with_exit_2(b5, capsys, monkeypatch)
    _b5b_an_accepted_max_seconds_reaches_the_loop_through_the_cli(b5b)
    _b6_flag_is_documented_in_help_readme_and_spec(capsys)
    _b7_spec_holds_its_byte_pin_and_the_synthesizer_prose_moved_verbatim()
    _b8_roadmap_records_the_ship_in_one_ledger_row()
