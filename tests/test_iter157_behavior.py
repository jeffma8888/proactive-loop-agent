"""Black-box behavior tests for state-dir iteration 151 (ships as commit-seq
**factory iter 157**): a repeated ``--kind`` on ``pla signals`` / ``pla collectors`` is
now a loud PARSE-TIME usage error (exit 2) instead of silently keeping only the last
value (ROADMAP #183).

Feature under test (``pm.md``): ``--kind`` is declared as a SINGLE-valued upstream
filter, but argparse's default ``store`` action accepted a repeat and silently kept the
last one.  That silence was load-bearing: ``pla signals --summary --kind A --kind B
--kind C --kind D --fail-over 4`` collapsed to a ONE-kind view, reported ``total 1`` and
exited 0 -- a count-budget gate passing for the wrong reason.  The union use case already
has a working spelling, the repeatable ``--collector`` flag (collector name maps 1:1 onto
a kind), so the fix is to reject the second occurrence at parse time, before any
collector runs, and to name ``--collector`` in the error.

ISOLATION CONTRACT (honored): every assertion here is derived from THIS iteration's
spec (``pm.md`` Expected Behaviors 1-10) and drives ONLY the public interface -- the
installed ``pla`` console script, its exit codes, its stdout and its stderr, plus its
``--help`` rendering.  **No file under ``src/`` was read, no engineer or reviewer note
was read, and no ``git diff`` was consulted.**  The message contract is asserted at the
level the spec specifies (the option string ``--kind``, the phrase ``may be given at
most once``, and a pointer at ``--collector``) rather than as one frozen sentence, so
wording may be polished without a false red -- but a silent loss of any of the three
required elements goes red.

Offline / deterministic: every invocation runs the shipped script against a workspace
built fresh in ``tmp_path`` (or against the repo itself for the two commands the spec
measured verbatim).  No network, no API key, no provider flags.  Help-text assertions
are whitespace-normalised, because Python 3.13 strips a docstring's common leading
indent at compile time while 3.12 does not.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

# The three elements the spec requires of the message (Expected Behaviors 1, 7, 10).
AT_MOST_ONCE = "may be given at most once"
KIND_OPT = "--kind"
COLLECTOR_OPT = "--collector"

# argparse's own pre-existing rejection of an unknown value (Expected Behavior 8).
INVALID_CHOICE = "invalid choice"

# A value that is NOT a member of SIGNAL_KINDS, held in a NAMED variable rather than
# inline: `test_iter108_behavior.py::test_b05_no_test_passes_an_impossible_kind_through
# _the_cli` is an exemption-free, LINE-BASED corpus scan over every quoted kind flag
# followed by a quoted literal anywhere under `tests/` -- prose in a comment counts, so
# this note deliberately spells no such pair. Its documented convention for a test that
# deliberately DRIVES a
# rejected value is exactly this -- route it through a named variable, so an accidental
# hardcoded typo still trips the scan.
_UNKNOWN_KIND = "bogus"


# ---------------------------------------------------------------------------
# Harness -- drive the shipped console script, read observable output only.
# ---------------------------------------------------------------------------


def _console_script() -> Path:
    """The installed ``pla`` console script (iter-114's resolution convention)."""
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
    return subprocess.run(
        [str(_console_script()), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=120,
    )


def _signals(ws: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return _run("signals", "--workspace", ".", *extra, cwd=ws)


def _norm(text: str) -> str:
    """Whitespace-normalised rendering -- 3.13 dedents docstrings, 3.12 does not."""
    return " ".join(text.split())


def _error_line(stderr: str) -> str:
    """The single ``<prog>: error: ...`` line argparse writes after the usage block."""
    lines = [ln for ln in stderr.splitlines() if ": error: " in ln]
    assert len(lines) == 1, f"expected exactly one argparse error line; got {lines!r}"
    return lines[0]


def _summary_counts(stdout: str) -> dict[str, int]:
    """Parse ``--summary``'s ``<label>  <count>`` rows into a mapping."""
    counts: dict[str, int] = {}
    for line in stdout.splitlines():
        match = re.fullmatch(r"(\S+)\s+(\d+)", line.strip())
        if match:
            counts[match.group(1)] = int(match.group(2))
    return counts


def _assert_at_most_once_error(
    proc: subprocess.CompletedProcess[str], *, verb: str
) -> str:
    """The whole exit-2 contract, asserted in one place (Behaviors 1, 3, 4, 7)."""
    assert proc.returncode == 2, (
        f"`pla {verb}` with a repeated --kind must exit 2 (argparse usage error); "
        f"got {proc.returncode}, stderr={proc.stderr!r}"
    )
    assert proc.stdout == "", (
        "a parse-time usage error must write NOTHING to stdout; got "
        f"{proc.stdout!r}"
    )
    line = _error_line(proc.stderr)
    assert KIND_OPT in line, f"the error must name the option string --kind: {line!r}"
    assert AT_MOST_ONCE in line, (
        f"the error must carry the phrase {AT_MOST_ONCE!r}: {line!r}"
    )
    assert COLLECTOR_OPT in line, (
        "the error must point the user at the repeatable --collector flag: "
        f"{line!r}"
    )
    assert "usage:" in proc.stderr, (
        "stderr must carry argparse's normal usage block, i.e. the error goes "
        f"through the owning parser's error(); got {proc.stderr!r}"
    )
    return line


# ---------------------------------------------------------------------------
# Fixture -- a tiny deterministic workspace with two different signal kinds.
# ---------------------------------------------------------------------------

_TODO_BODY = "\n".join(f"line {i}" for i in range(1, 12)) + "\n# TODO: alpha\n"


@pytest.fixture(scope="module")
def ws(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A workspace emitting at least one ``todo`` and one ``dependency`` signal."""
    root = tmp_path_factory.mktemp("iter157_ws")
    (root / "pyproject.toml").write_text(
        '[project]\nname = "probe"\nversion = "0.0.0"\n', encoding="utf-8"
    )
    (root / "a.py").write_text(_TODO_BODY, encoding="utf-8")
    return root


# ---------------------------------------------------------------------------
# Behavior 1 / 2 -- the repeat is an exit-2 usage error and collects nothing.
# ---------------------------------------------------------------------------


def test_b1_a_repeated_kind_on_signals_is_a_parse_time_usage_error(ws: Path) -> None:
    proc = _signals(ws, "--kind", "todo", "--kind", "ci_config")
    _assert_at_most_once_error(proc, verb="signals")


def test_b2_the_usage_error_precedes_collection_in_every_output_mode(ws: Path) -> None:
    """No signal listing, no ``total`` row and no JSON, on any output mode."""
    for mode in ([], ["--summary"], ["--json"]):
        proc = _signals(ws, *mode, "--kind", "todo", "--kind", "dependency")
        _assert_at_most_once_error(proc, verb="signals")
        assert _summary_counts(proc.stdout) == {}, f"mode={mode!r}"
        assert "total" not in proc.stdout, f"mode={mode!r}"
        assert "{" not in proc.stdout, f"mode={mode!r}"


# ---------------------------------------------------------------------------
# Behaviors 3 / 4 -- any second occurrence errors, whatever its value or count.
# ---------------------------------------------------------------------------


def test_b3_a_repeat_of_the_same_value_is_an_error_too(ws: Path) -> None:
    proc = _signals(ws, "--kind", "todo", "--kind", "todo")
    _assert_at_most_once_error(proc, verb="signals")


def test_b4_three_occurrences_give_the_identical_message(ws: Path) -> None:
    two = _signals(ws, "--kind", "todo", "--kind", "todo")
    three = _signals(ws, "--kind", "todo", "--kind", "todo", "--kind", "note")
    line = _assert_at_most_once_error(three, verb="signals")
    assert line == _error_line(two.stderr), (
        "the message must not vary with the repeat count (the error fires on the "
        f"second occurrence): {line!r} vs {_error_line(two.stderr)!r}"
    )


# ---------------------------------------------------------------------------
# Behavior 5 -- a single --kind is untouched.
# ---------------------------------------------------------------------------


def test_b5_a_single_kind_is_unchanged(ws: Path) -> None:
    proc = _signals(ws, "--summary", "--kind", "todo")
    assert proc.returncode == 0, f"exit {proc.returncode}; stderr={proc.stderr!r}"
    counts = _summary_counts(proc.stdout)
    assert counts.get("todo", 0) >= 1, proc.stdout
    assert counts.get("total", 0) >= 1, proc.stdout


def test_b5_the_specs_verbatim_single_kind_command_on_this_repo_still_exits_0() -> None:
    """The spec's literal example, run where it was measured: the repo itself."""
    proc = _run(
        "signals", "--workspace", ".", "--summary", "--kind", "ci_config", cwd=REPO
    )
    assert proc.returncode == 0, f"exit {proc.returncode}; stderr={proc.stderr!r}"
    counts = _summary_counts(proc.stdout)
    assert counts.get("ci_config", 0) >= 1, proc.stdout
    assert "total" in counts, proc.stdout


# ---------------------------------------------------------------------------
# Behavior 6 -- the measured fail-open is CLOSED, not merely reported.
# ---------------------------------------------------------------------------


def test_b6_the_fail_over_budget_fail_open_is_closed() -> None:
    """Measured before this change: exit 0 with ``dependency 1 / total 1``."""
    proc = _run(
        "signals",
        "--workspace",
        ".",
        "--summary",
        "--kind",
        "lockfile_drift",
        "--kind",
        "ci_config",
        "--kind",
        "test_posture",
        "--kind",
        "dependency",
        "--fail-over",
        "4",
        cwd=REPO,
    )
    _assert_at_most_once_error(proc, verb="signals")
    assert "total" not in proc.stdout, (
        "the budget must never be evaluated against a silently narrowed view; "
        f"stdout={proc.stdout!r}"
    )


# ---------------------------------------------------------------------------
# Behavior 7 -- the sibling verb `collectors` behaves identically.
# ---------------------------------------------------------------------------


def test_b7_a_repeated_kind_on_collectors_is_the_same_usage_error() -> None:
    proc = _run("collectors", "--kind", "todo", "--kind", "note", cwd=REPO)
    _assert_at_most_once_error(proc, verb="collectors")


def test_b7_a_single_kind_on_collectors_still_lists_exactly_one_row() -> None:
    proc = _run("collectors", "--kind", "todo", cwd=REPO)
    assert proc.returncode == 0, f"exit {proc.returncode}; stderr={proc.stderr!r}"
    rows = [
        line
        for line in proc.stdout.splitlines()
        if re.fullmatch(r"\s{2,}\S+\s+\S+\s+\S.*", line)
    ]
    assert len(rows) == 1, f"expected exactly one collector row; got {rows!r}"
    assert "todo" in rows[0], rows[0]


# ---------------------------------------------------------------------------
# Behavior 8 -- an unknown value is still rejected FIRST, in either position.
# ---------------------------------------------------------------------------


def test_b8_an_unknown_kind_still_loses_to_argparses_choices_check(ws: Path) -> None:
    """Both positions in ONE test: the suite has a published size floor with only a
    handful of tests of headroom, so cheap cases share a test rather than a param id."""
    for args in (
        ("--kind", _UNKNOWN_KIND, "--kind", "todo"),
        ("--kind", "todo", "--kind", _UNKNOWN_KIND),
    ):
        proc = _signals(ws, *args)
        assert proc.returncode == 2, (
            f"args={args!r}: exit {proc.returncode}; stderr={proc.stderr!r}"
        )
        line = _error_line(proc.stderr)
        assert INVALID_CHOICE in line, f"args={args!r}: {line!r}"
        assert AT_MOST_ONCE not in line, (
            "choices validation must run BEFORE the at-most-once action, so an "
            f"unknown value wins in either position: args={args!r}, {line!r}"
        )


# ---------------------------------------------------------------------------
# Behavior 9 -- the three genuinely repeatable filters are untouched.
# ---------------------------------------------------------------------------


def test_b9_collector_is_still_repeatable_and_still_unions(ws: Path) -> None:
    both = _signals(
        ws, "--summary", "--collector", "todos", "--collector", "dependencies"
    )
    only_todos = _signals(ws, "--summary", "--collector", "todos")
    only_deps = _signals(ws, "--summary", "--collector", "dependencies")
    for proc in (both, only_todos, only_deps):
        assert proc.returncode == 0, f"exit {proc.returncode}; stderr={proc.stderr!r}"
    union = _summary_counts(both.stdout)["total"]
    a = _summary_counts(only_todos.stdout)["total"]
    b = _summary_counts(only_deps.stdout)["total"]
    assert a >= 1 and b >= 1, (only_todos.stdout, only_deps.stdout)
    assert union > a and union > b, (
        f"--collector must still UNION: union={union}, todos={a}, dependencies={b}"
    )


def test_b9_fail_on_kind_and_exclude_path_still_accept_two_values(ws: Path) -> None:
    for extra in (
        ("--fail-on-kind", "todo", "--fail-on-kind", "dependency"),
        ("--exclude-path", "nope/*", "--exclude-path", "other/*"),
    ):
        proc = _signals(ws, "--summary", *extra)
        assert AT_MOST_ONCE not in proc.stderr, (
            f"{extra[0]} must stay repeatable; stderr={proc.stderr!r}"
        )
        assert proc.returncode != 2, (
            f"{extra[0]} with two values must not be a usage error; "
            f"exit {proc.returncode}, stderr={proc.stderr!r}"
        )


# ---------------------------------------------------------------------------
# Behavior 10 -- both help screens teach the rule.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("verb", ["signals", "collectors"])
def test_b10_help_states_the_rule_and_points_at_the_repeatable_flag(verb: str) -> None:
    proc = _run(verb, "--help", cwd=REPO)
    assert proc.returncode == 0, f"exit {proc.returncode}; stderr={proc.stderr!r}"
    text = _norm(proc.stdout)
    assert AT_MOST_ONCE in text, f"`pla {verb} --help` must state the rule: {text!r}"
    assert COLLECTOR_OPT in text, (
        f"`pla {verb} --help` must name the repeatable --collector flag: {text!r}"
    )


# ---------------------------------------------------------------------------
# Spellings a real user types, and one shared source of truth.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "args",
    [
        ("--kind=todo", "--kind", "note"),
        ("--ki", "todo", "--ki", "note"),
    ],
    ids=["equals-then-space", "abbreviated"],
)
def test_every_spelling_of_the_repeat_errors_and_names_the_canonical_flag(
    ws: Path, args: tuple[str, ...]
) -> None:
    proc = _signals(ws, *args)
    line = _assert_at_most_once_error(proc, verb="signals")
    assert KIND_OPT in line, (
        "the message must report the canonical --kind spelling, never an "
        f"abbreviation the user happened to type: {line!r}"
    )


def test_the_message_is_one_shared_source_of_truth_across_both_verbs(ws: Path) -> None:
    """One Action, wired onto both declarations -- so the sentence cannot drift."""
    from_signals = _error_line(_signals(ws, "--kind", "todo", "--kind", "note").stderr)
    from_collectors = _error_line(
        _run("collectors", "--kind", "todo", "--kind", "note", cwd=REPO).stderr
    )
    strip_prog = re.compile(r"^.*?: error: ")
    assert strip_prog.sub("", from_signals) == strip_prog.sub("", from_collectors), (
        "both verbs must render the SAME message body (differing only in the "
        f"argparse prog prefix): {from_signals!r} vs {from_collectors!r}"
    )
