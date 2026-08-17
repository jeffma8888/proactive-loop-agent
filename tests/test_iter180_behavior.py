"""Black-box behavior tests for state-dir iteration 176 (ships as ``factory iter 180``).

Feature under test: ``pla verify --fail-on-unresolved`` (roadmap #214) -- the
enforcement half of ``verify`` (#201, iter-173) and ``run --snapshot`` (#213,
iter-175). Before it, a verification that resolved EVERY cited source and one
that resolved NONE returned the same exit code 0, so no automated caller could
consume the report: success and total failure were indistinguishable.

MODULE NAME. This repo names behavior modules by the FACTORY iteration number,
which runs ahead of the state-dir counter (``tests/test_iter109_behavior.py``
documents the offset for itself, ``tests/test_iter177_behavior.py`` repeats it).
The highest existing module is ``test_iter179_behavior.py``, so state-dir 176 is
factory 180 and this file is 180 -- writing 176 would have SILENTLY OVERWRITTEN
a shipped oracle (the iter-172 destroyed-oracle lesson), and the spec's
acceptance criteria name ``tests/test_iter180_behavior.py`` explicitly.

TWO-SIDED BY CONSTRUCTION. The spec requires that "the matched pair MUST stay 0
and the mismatched pair MUST go 5", because a test that only asserts the failure
case cannot tell a working gate from one that always trips. Every gate assertion
here is therefore made against BOTH pairs, and the ``pairs`` fixture asserts its
own bad sample really is bad (>0 unresolved) so this module can never silently
decay into a one-sided oracle.

WHY NO SNAPSHOT IS HAND-EDITED. The mismatched pair is the fixture slate against
a snapshot from a DIFFERENT workspace -- both are real ``scan --snapshot``
output. Mangling a snapshot by hand instead would land in ``verify``'s
pre-existing exit-2 refusal ladder (measured: a truncated document exits 2 with
``error: snapshot file is not valid JSON``, a key-stripped one exits 2 with
``error: snapshot file has no 'signals' array``), so it would test the guard this
iteration did NOT change rather than the gate it did.

WHY BEHAVIORS ARE DRIVEN THROUGH A REAL SUBPROCESS. Behaviors 4, 5 and 6 are
claims about WHOLE STREAMS -- stdout byte-identical across two runs, stderr being
EXACTLY one line, an entire stdout parsing as ONE JSON object with the gate line
provably not in it. An in-process ``capsys`` run cannot falsify those honestly,
so this module spends real ``pla`` console-script invocations (the
iter-114 / iter-152 / iter-163 / iter-177 convention). Cost is bounded: TWO
module-scoped scans build both pairs, and the six verify invocations every test
shares are module-scoped too, so the whole module costs 8 processes plus the
parametrized refusal ladder.

ISOLATION CONTRACT (honored, no exceptions). Every assertion is derived from this
iteration's spec ("Expected Behaviors" in ``pm.md``), the repo's own ``tests/``
conventions, ``README.md`` / ``ROADMAP.md``, and the product's OBSERVABLE output
obtained by RUNNING it. **No file under ``src/`` was read, no ``git diff`` was
inspected, and neither ``engineer.md`` nor ``reviewer.md`` was opened.** Fully
offline and deterministic: the bundled scripted provider only, no network, no API
key. Every invocation is rooted at a PRIVATE COPY of
``examples/fixture_workspace`` under a ``tmp_path_factory`` dir (the iter-142
shared-mutable-tree hazard).

NO INDENTATION ASSERTIONS. CI is a 3.12 + 3.13 matrix and 3.13 strips the common
leading indent from docstrings at compile time, so nothing here asserts on
docstring or help-text indentation; the epilog scan below matches ``^\\s*`` and
never a fixed indent width.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from proactive_loop.cli import build_parser

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "examples" / "fixture_workspace"
SCRIPT = REPO / "examples" / "scripted_responses.json"

FLAG = "--fail-on-unresolved"
GATE_PREFIX = "gate: "
ERROR_PREFIX = "error: "

# Spec behavior 4/5: the shipped gate exit code, NOT a new one.
GATE_EXIT = 5
# Spec behavior 7: the pre-existing refusal ladder that must keep winning.
REFUSAL_EXIT = 2
# Spec behavior 9: the code SET is unchanged by this iteration.
EXPECTED_CODE_SET = frozenset({0, 1, 2, 3, 4, 5})

_TRAILER_RE = re.compile(
    r"^verified: (?P<goals>\d+) goals, (?P<sources>\d+) sources, (?P<unresolved>\d+) unresolved$"
)
# Spec behavior 5: the count is reported as a key=value pair, sibling-style.
_GATE_KV_RE = re.compile(r"\bunresolved=(?P<count>\d+)\b")


# ---------------------------------------------------------------------------
# Helpers (iter-114 / iter-152 / iter-163 / iter-177 console-script convention)
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


def _trailer(stdout: str) -> re.Match[str]:
    """The human-mode summary line, which carries the authoritative count."""
    for line in stdout.splitlines():
        match = _TRAILER_RE.match(line.strip())
        if match:
            return match
    raise AssertionError(f"expected a `verified: ...` trailer line; got {stdout!r}")


def _unresolved_count(stdout: str) -> int:
    return int(_trailer(stdout).group("unresolved"))


def _stderr_lines(stderr: str) -> list[str]:
    return [line for line in stderr.splitlines() if line.strip()]


def _scan(root: Path, workspace: Path, tag: str) -> dict[str, Path]:
    """One offline scan writing BOTH a slate and its same-run snapshot."""
    slate = root / f"slate_{tag}.json"
    snapshot = root / f"snapshot_{tag}.json"
    proc = _run(
        "scan",
        "--workspace",
        str(workspace),
        "--provider",
        "scripted",
        "--scripted-responses",
        str(SCRIPT),
        "--state-dir",
        str(root / f"state_{tag}"),
        "--out",
        str(slate),
        "--snapshot",
        str(snapshot),
        cwd=root,
    )
    assert proc.returncode == 0, (
        f"fixture scan {tag!r} must succeed offline; stderr={proc.stderr!r}"
    )
    assert slate.is_file() and snapshot.is_file(), (
        f"scan {tag!r} must write both --out and --snapshot"
    )
    return {"slate": slate, "snapshot": snapshot}


# ---------------------------------------------------------------------------
# Fixtures: ONE matched pair and ONE mismatched pair, both real product output
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def pairs(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    """A matched pair (0 unresolved) and a mismatched pair (>0 unresolved).

    The mismatched pair reuses the SAME slate against an unrelated workspace's
    snapshot, which is the spec's construction: the citations are genuine, the
    snapshot simply cannot account for them.
    """
    root = tmp_path_factory.mktemp("iter180")

    workspace_a = root / "workspace_a"
    shutil.copytree(FIXTURE, workspace_a)
    pair_a = _scan(root, workspace_a, "a")

    workspace_b = root / "workspace_b"
    workspace_b.mkdir()
    (workspace_b / "notes.md").write_text(
        "# Unrelated workspace\n\nNothing here overlaps workspace A.\n", encoding="utf-8"
    )
    (workspace_b / "todo.txt").write_text("unrelated errand\n", encoding="utf-8")
    pair_b = _scan(root, workspace_b, "b")

    built = {
        "root": root,
        "slate": pair_a["slate"],
        "matched_snapshot": pair_a["snapshot"],
        "mismatched_snapshot": pair_b["snapshot"],
    }

    # A two-sided oracle must prove its own samples: if these preconditions ever
    # stop holding, this module has decayed into a one-sided test and must fail
    # LOUDLY rather than keep passing.
    good = _run(
        "verify", "--slate", str(built["slate"]), "--snapshot", str(built["matched_snapshot"]),
        cwd=root,
    )
    bad = _run(
        "verify", "--slate", str(built["slate"]), "--snapshot", str(built["mismatched_snapshot"]),
        cwd=root,
    )
    assert _unresolved_count(good.stdout) == 0, (
        "PRECONDITION: the matched pair must resolve every cited source, otherwise "
        f"the known-GOOD sample is not good; got {good.stdout!r}"
    )
    assert _unresolved_count(bad.stdout) > 0, (
        "PRECONDITION: the mismatched pair must leave at least one source "
        "unresolved, otherwise the known-BAD sample cannot trip any gate and "
        f"this module is one-sided; got {bad.stdout!r}"
    )
    return built


def _verify(pairs: dict[str, Path], snapshot_key: str, *extra: str) -> subprocess.CompletedProcess[str]:
    return _run(
        "verify",
        "--slate",
        str(pairs["slate"]),
        "--snapshot",
        str(pairs[snapshot_key]),
        *extra,
        cwd=pairs["root"],
    )


@pytest.fixture(scope="module")
def matched_default(pairs: dict[str, Path]) -> subprocess.CompletedProcess[str]:
    return _verify(pairs, "matched_snapshot")


@pytest.fixture(scope="module")
def matched_gated(pairs: dict[str, Path]) -> subprocess.CompletedProcess[str]:
    return _verify(pairs, "matched_snapshot", FLAG)


@pytest.fixture(scope="module")
def mismatched_default(pairs: dict[str, Path]) -> subprocess.CompletedProcess[str]:
    return _verify(pairs, "mismatched_snapshot")


@pytest.fixture(scope="module")
def mismatched_gated(pairs: dict[str, Path]) -> subprocess.CompletedProcess[str]:
    return _verify(pairs, "mismatched_snapshot", FLAG)


@pytest.fixture(scope="module")
def mismatched_json_default(pairs: dict[str, Path]) -> subprocess.CompletedProcess[str]:
    return _verify(pairs, "mismatched_snapshot", "--json")


@pytest.fixture(scope="module")
def mismatched_json_gated(pairs: dict[str, Path]) -> subprocess.CompletedProcess[str]:
    return _verify(pairs, "mismatched_snapshot", "--json", FLAG)


# ==========================================================================
# Behavior 1 -- default unchanged on the matched pair
# ==========================================================================


def test_b01_default_matched_pair_exits_zero_with_a_clean_report(
    matched_default: subprocess.CompletedProcess[str],
) -> None:
    assert matched_default.returncode == 0, (
        "`verify` without the new flag must still exit 0 on a matched pair; "
        f"got {matched_default.returncode}; stderr={matched_default.stderr!r}"
    )
    assert _unresolved_count(matched_default.stdout) == 0
    assert matched_default.stderr == "", (
        "the default path must leave stderr completely untouched -- an opt-out "
        f"caller sees no new output at all; got {matched_default.stderr!r}"
    )


def test_b01_default_matched_pair_prints_no_gate_line_anywhere(
    matched_default: subprocess.CompletedProcess[str],
) -> None:
    assert GATE_PREFIX not in matched_default.stdout
    assert GATE_PREFIX not in matched_default.stderr


# ==========================================================================
# Behavior 2 -- default unchanged on the MISMATCHED pair (report-only kept)
# ==========================================================================


def test_b02_default_mismatched_pair_still_exits_zero(
    mismatched_default: subprocess.CompletedProcess[str],
) -> None:
    assert mismatched_default.returncode == 0, (
        "the report-only default is the shipped contract: WITHOUT the flag, an "
        "unresolved source must NOT change the exit code, or every existing "
        f"caller breaks; got {mismatched_default.returncode}"
    )
    assert mismatched_default.stderr == "", (
        f"no gate was armed, so stderr must stay empty; got {mismatched_default.stderr!r}"
    )


def test_b02_default_mismatched_pair_prints_the_full_unresolved_report(
    mismatched_default: subprocess.CompletedProcess[str],
) -> None:
    count = _unresolved_count(mismatched_default.stdout)
    assert count > 0, "the mismatched pair must report unresolved sources"
    reported = [
        line for line in mismatched_default.stdout.splitlines()
        if line.strip().startswith("UNRESOLVED: ")
    ]
    assert len(reported) == count, (
        f"the trailer says {count} unresolved, so {count} UNRESOLVED lines must be "
        f"printed; got {len(reported)}"
    )


# ==========================================================================
# Behavior 3 -- flag set, nothing unresolved: silent no-op
# ==========================================================================


def test_b03_flag_on_matched_pair_exits_zero(
    matched_gated: subprocess.CompletedProcess[str],
) -> None:
    assert matched_gated.returncode == 0, (
        "an armed gate that finds nothing must NOT trip -- this is the half of "
        "the oracle that detects a flag which always fails; got "
        f"{matched_gated.returncode}; stderr={matched_gated.stderr!r}"
    )


def test_b03_flag_on_matched_pair_leaves_stdout_byte_identical(
    matched_default: subprocess.CompletedProcess[str],
    matched_gated: subprocess.CompletedProcess[str],
) -> None:
    assert matched_gated.stdout == matched_default.stdout, (
        "arming the gate must not alter the report by one byte on a clean pair"
    )


def test_b03_flag_on_matched_pair_prints_no_gate_line(
    matched_gated: subprocess.CompletedProcess[str],
) -> None:
    assert GATE_PREFIX not in matched_gated.stderr, (
        f"an untripped gate must announce nothing; got {matched_gated.stderr!r}"
    )
    assert GATE_PREFIX not in matched_gated.stdout
    assert matched_gated.stderr == "", (
        f"an untripped gate must leave stderr empty; got {matched_gated.stderr!r}"
    )


# ==========================================================================
# Behavior 4 -- flag set, something unresolved: exit 5, report intact
# ==========================================================================


def test_b04_flag_on_mismatched_pair_exits_five(
    mismatched_gated: subprocess.CompletedProcess[str],
) -> None:
    assert mismatched_gated.returncode == GATE_EXIT, (
        f"an armed gate with an unresolved source must exit {GATE_EXIT} (the "
        "SHIPPED gate-tripped code, shared with --fail-on-kind / --fail-over); "
        f"got {mismatched_gated.returncode}; stderr={mismatched_gated.stderr!r}"
    )


def test_b04_gate_colours_the_exit_code_without_touching_stdout(
    mismatched_default: subprocess.CompletedProcess[str],
    mismatched_gated: subprocess.CompletedProcess[str],
) -> None:
    assert mismatched_gated.stdout == mismatched_default.stdout, (
        "the gate must colour the EXIT CODE only: stdout has to stay byte-"
        "identical to the report-only run, so a caller can trust one stream "
        "regardless of whether it armed the gate"
    )
    assert GATE_PREFIX not in mismatched_gated.stdout, (
        "the gate line belongs on stderr; putting it on stdout would corrupt "
        "the report for any consumer parsing it"
    )


# ==========================================================================
# Behavior 5 -- the gate names itself on exactly one stderr line
# ==========================================================================


def test_b05_gate_announces_itself_on_exactly_one_stderr_line(
    mismatched_gated: subprocess.CompletedProcess[str],
) -> None:
    lines = _stderr_lines(mismatched_gated.stderr)
    assert len(lines) == 1, (
        f"the tripped gate must print exactly one stderr line; got {lines}"
    )
    assert lines[0].startswith(GATE_PREFIX), (
        f"the line must open with {GATE_PREFIX!r} in the sibling idiom; got {lines[0]!r}"
    )


def test_b05_gate_line_is_a_finding_not_a_tool_fault(
    mismatched_gated: subprocess.CompletedProcess[str],
) -> None:
    assert ERROR_PREFIX not in mismatched_gated.stderr, (
        "an unresolved source is a FINDING the tool reported successfully, not a "
        "tool fault, so it must NOT wear the `error: ` prefix -- the same "
        "distinction the `gate: fail-over tripped` sibling already draws; got "
        f"{mismatched_gated.stderr!r}"
    )


def test_b05_gate_line_reports_the_count_as_a_key_value_pair(
    mismatched_gated: subprocess.CompletedProcess[str],
) -> None:
    match = _GATE_KV_RE.search(mismatched_gated.stderr)
    assert match is not None, (
        "the gate line must report the unresolved count as a `key=value` pair so "
        f"a log scraper can read it; got {mismatched_gated.stderr!r}"
    )
    assert int(match.group("count")) == _unresolved_count(mismatched_gated.stdout), (
        "the count on the gate line must agree with the report's own trailer, "
        "otherwise stderr and stdout tell a caller two different stories"
    )
    assert int(match.group("count")) > 0, "a tripped gate must report a positive count"


def test_b05_gate_line_names_the_flag_that_tripped(
    mismatched_gated: subprocess.CompletedProcess[str],
) -> None:
    assert "unresolved" in mismatched_gated.stderr, (
        "the line must name WHICH gate tripped -- `verify` could grow a second "
        f"one; got {mismatched_gated.stderr!r}"
    )


# ==========================================================================
# Behavior 6 -- --json stays exactly one parseable object
# ==========================================================================


def test_b06_gated_json_run_exits_five(
    mismatched_json_gated: subprocess.CompletedProcess[str],
) -> None:
    assert mismatched_json_gated.returncode == GATE_EXIT, (
        f"--json must not disarm the gate; got {mismatched_json_gated.returncode}"
    )


def test_b06_entire_gated_json_stdout_parses_as_one_object(
    mismatched_json_gated: subprocess.CompletedProcess[str],
) -> None:
    payload = json.loads(mismatched_json_gated.stdout)
    assert isinstance(payload, dict), (
        f"stdout must be ONE JSON object, not a stream; got {type(payload).__name__}"
    )
    assert GATE_PREFIX not in mismatched_json_gated.stdout, (
        "a gate line appended to a --json stdout would make the document "
        "unparseable -- the whole point of routing it to stderr"
    )
    assert payload["unresolved_count"] > 0


def test_b06_gated_json_payload_equals_the_ungated_payload(
    mismatched_json_default: subprocess.CompletedProcess[str],
    mismatched_json_gated: subprocess.CompletedProcess[str],
) -> None:
    assert json.loads(mismatched_json_gated.stdout) == json.loads(
        mismatched_json_default.stdout
    ), "the gate must not alter the --json payload shape or content"
    assert mismatched_json_default.returncode == 0, (
        "sanity: the ungated --json run must still be report-only, or this "
        "comparison is not two-sided"
    )


def test_b06_gated_json_run_still_announces_the_gate_on_stderr(
    mismatched_json_gated: subprocess.CompletedProcess[str],
) -> None:
    lines = _stderr_lines(mismatched_json_gated.stderr)
    assert len(lines) == 1 and lines[0].startswith(GATE_PREFIX), (
        f"--json must keep the stderr announcement; got {lines}"
    )


# ==========================================================================
# Behavior 7 -- the pre-existing refusals still win, and print no gate line
# ==========================================================================


@pytest.mark.parametrize(
    ("case", "payload"),
    [
        ("malformed", "{not json"),
        ("schema_invalid", json.dumps({"hello": "world"})),
    ],
)
def test_b07_a_broken_snapshot_refuses_at_exit_two_even_with_the_gate_armed(
    pairs: dict[str, Path], tmp_path: Path, case: str, payload: str
) -> None:
    broken = tmp_path / f"{case}.json"
    broken.write_text(payload, encoding="utf-8")
    proc = _run(
        "verify", "--slate", str(pairs["slate"]), "--snapshot", str(broken), FLAG,
        cwd=pairs["root"],
    )
    assert proc.returncode == REFUSAL_EXIT, (
        f"a {case} snapshot must keep refusing at exit {REFUSAL_EXIT}: the gate "
        "reports on a verification that RAN, and must never repaint a refusal as "
        f"a finding; got {proc.returncode}; stderr={proc.stderr!r}"
    )
    lines = _stderr_lines(proc.stderr)
    assert len(lines) == 1 and lines[0].startswith(ERROR_PREFIX), (
        f"the refusal keeps its single `error: ` line; got {lines}"
    )
    assert GATE_PREFIX not in proc.stderr, (
        "a refusal must print NO gate line -- there was no verification to gate"
    )


def test_b07_a_missing_slate_refuses_at_exit_two_even_with_the_gate_armed(
    pairs: dict[str, Path], tmp_path: Path
) -> None:
    proc = _run(
        "verify",
        "--slate",
        str(tmp_path / "absent.json"),
        "--snapshot",
        str(pairs["matched_snapshot"]),
        FLAG,
        cwd=pairs["root"],
    )
    assert proc.returncode == REFUSAL_EXIT, (
        f"a missing --slate must refuse at exit {REFUSAL_EXIT}; got {proc.returncode}"
    )
    lines = _stderr_lines(proc.stderr)
    assert len(lines) == 1 and lines[0].startswith(ERROR_PREFIX), (
        f"expected one `error: ` line; got {lines}"
    )
    assert GATE_PREFIX not in proc.stderr


# ==========================================================================
# Behavior 8 -- discoverable, scoped to `verify`, and off by default
# ==========================================================================


def test_b08_verify_help_documents_the_flag(pairs: dict[str, Path]) -> None:
    proc = _run("verify", "--help", cwd=pairs["root"])
    assert proc.returncode == 0
    assert FLAG in proc.stdout, (
        f"`pla verify --help` must list {FLAG}; an undiscoverable gate cannot be "
        f"adopted; got {proc.stdout!r}"
    )


def test_b08_no_other_verb_gains_the_flag() -> None:
    parser = build_parser()
    subparser_actions = [
        action
        for action in parser._subparsers._group_actions  # noqa: SLF001 -- repo convention
        if isinstance(action, argparse._SubParsersAction)
    ]
    assert len(subparser_actions) == 1, (
        f"expected exactly one subparser action, got {len(subparser_actions)}"
    )
    owners = sorted(
        verb
        for verb, sub in subparser_actions[0].choices.items()
        if any(FLAG in action.option_strings for action in sub._actions)  # noqa: SLF001
    )
    assert owners == ["verify"], (
        f"{FLAG} must exist on `verify` and nowhere else -- it is a verify-scoped "
        f"gate, not a global one; got {owners}"
    )


def test_b08_the_flag_is_a_boolean_switch_that_defaults_off() -> None:
    parser = build_parser()
    args = parser.parse_args(["verify", "--slate", "s.json", "--snapshot", "n.json"])
    assert getattr(args, "fail_on_unresolved") is False, (
        "the gate must default OFF, so no existing invocation changes behavior"
    )
    armed = parser.parse_args(
        ["verify", "--slate", "s.json", "--snapshot", "n.json", FLAG]
    )
    assert getattr(armed, "fail_on_unresolved") is True


def test_b08_repeating_the_flag_is_accepted_because_store_true_is_idempotent() -> None:
    parser = build_parser()
    args = parser.parse_args(
        ["verify", "--slate", "s.json", "--snapshot", "n.json", FLAG, FLAG]
    )
    assert getattr(args, "fail_on_unresolved") is True, (
        "a boolean switch is idempotent, so unlike --fail-on-kind it needs no "
        "at-most-once action and repeating it must not be an error"
    )


# ==========================================================================
# Behavior 9 -- the exit-code contract names the new trigger, SET unchanged
# ==========================================================================


def _epilog_codes(help_text: str) -> dict[int, str]:
    """The rendered `exit codes:` epilog as {code: its wrapped meaning}.

    Tolerant of ANY leading indent (3.13 strips docstring indentation, 3.12 does
    not), and it stops at the first blank-separated non-code paragraph.
    """
    lines = help_text.splitlines()
    start = next(
        (i for i, line in enumerate(lines) if line.strip().lower().startswith("exit codes:")),
        None,
    )
    assert start is not None, f"`pla --help` must render an `exit codes:` epilog; got {help_text!r}"
    codes: dict[int, str] = {}
    current: int | None = None
    for line in lines[start + 1 :]:
        match = re.match(r"^\s*(\d+)\s+(\S.*)$", line)
        if match:
            current = int(match.group(1))
            codes[current] = match.group(2)
        elif line.strip() and current is not None:
            codes[current] = f"{codes[current]} {line.strip()}"
    return codes


def test_b09_the_published_code_set_is_unchanged_by_this_iteration(
    pairs: dict[str, Path],
) -> None:
    proc = _run("--help", cwd=pairs["root"])
    assert proc.returncode == 0
    codes = _epilog_codes(proc.stdout)
    assert set(codes) == set(EXPECTED_CODE_SET), (
        "this iteration reuses the SHIPPED code 5 and must invent NO new code; "
        f"the epilog must still publish exactly {sorted(EXPECTED_CODE_SET)}; got "
        f"{sorted(codes)}"
    )


def test_b09_code_five_meaning_names_unresolved_source_enforcement(
    pairs: dict[str, Path],
) -> None:
    proc = _run("--help", cwd=pairs["root"])
    meaning = _epilog_codes(proc.stdout)[GATE_EXIT]
    assert "unresolved" in meaning.lower(), (
        "a reader who gets a 5 out of `verify` must be able to learn why from "
        f"`pla --help`; code 5's meaning reads {meaning!r}"
    )
    for sibling in ("--fail-on-kind", "--fail-over"):
        assert sibling in meaning, (
            f"code 5's meaning must keep naming its sibling gate {sibling}, so "
            f"the new trigger is listed ALONGSIDE them rather than replacing "
            f"them; got {meaning!r}"
        )


def test_b09_code_five_meaning_names_the_new_flag_itself(
    pairs: dict[str, Path],
) -> None:
    meaning = _epilog_codes(_run("--help", cwd=pairs["root"]).stdout)[GATE_EXIT]
    assert "verify" in meaning, (
        f"code 5's meaning must name the verb that can now return it; got {meaning!r}"
    )
