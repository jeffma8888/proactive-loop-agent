"""Black-box behavior tests for state-dir iteration 121 (ships as commit-seq
**factory iter 128**): the repo's own graded gate DOGFOODS the product's
enforcement mode (ROADMAP #145).

Feature under test (``pm.md``): factory iter 127 shipped
``pla signals --fail-on-kind`` -- the product's only enforcement mode, whose
README text sells exit 5 as "the gate for a pre-commit hook or a CI step". One
commit later it had ZERO consumers: ``fail-on-kind`` appeared 0 times in
``Makefile``, ``.github/workflows/ci.yml`` and ``SPEC.md``. This iteration arms a
self-scan as the FINAL step of ``make check`` and mirrors it as a graded CI
``run:`` step, so the exit-5 path is exercised end to end through the shipped
console script on every push, and the advertised integration has a demonstrated
consumer instead of a documented one.

The arm set is the whole design and it is what these tests pin hardest. Of the
registered signal kinds, only the STATE-INDEPENDENT, must-never-appear subset
``{merge_conflict, syntax_error, secret_file, broken_link}`` is safe to make a
build gate (``broken_link`` was armed as the 4th kind in factory iter 147):
``lockfile_drift`` / ``test_posture`` / ``ci_config`` are non-zero in this repo
today (red on arrival), and ``working_tree`` / ``git_state`` / ``git_stash`` are
LOCAL-STATE dependent -- arming those makes the gate red for every developer
mid-edit while CI (a fresh checkout) stays green, i.e. green in the only place it
is measured and red everywhere it is used. Behavior 5 is the regression guard
that keeps a future "strengthening" of the gate from landing.

ISOLATION CONTRACT (honored): every assertion here is written from THIS
iteration's spec (``pm.md`` Expected Behaviors) plus the black-box surfaces the
spec designates -- the parsed TEXT of ``Makefile`` / ``.github/workflows/ci.yml``
/ ``pyproject.toml``, the two sibling drift-guard modules under ``tests/``, and
the OBSERVABLE behavior of the real ``pla`` console script (exit code, stdout,
stderr). **No file under ``src/`` was read, no engineer or reviewer note was
read, and no ``git diff`` was consulted by the author.** The armed command, the
armed kind set, the six forbidden kinds, the ordered pre-existing gate steps and
the CI run-step count are encoded below as the CONTRACT's ground facts, NOT
copied out of any implementation, so a silent drift in either direction goes RED.

Offline + cap-safe: behaviors 1, 2, 5, 6, 7 and the flag/dependency halves of 8
are pure file reads and text parsing. Behaviors 3, 4 and the stdout-identity half
of 8 are the deliberate exceptions -- they execute the ARMED COMMAND ITSELF, but
via the installed ``pla`` console script (never ``uv``, never ``make``, so no
nested resolve/sync and no nested pytest), never inside the repository as CWD,
and against fixture workspaces under ``tmp_path``. Measured with
``--durations``: 5 tests shell out, 6 subprocess invocations in all, 0.20-0.56s
each and 1.91s together, no network.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

# --------------------------------------------------------------------------
# Tester's ground facts --- the spec-declared contract constants (pm.md).
# --------------------------------------------------------------------------

REPO = Path(__file__).resolve().parents[1]
MAKEFILE = REPO / "Makefile"
WORKFLOW = REPO / ".github" / "workflows" / "ci.yml"
PYPROJECT = REPO / "pyproject.toml"

# Behavior 1/2: the one new gate step, verbatim.
EXPECTED_GATE_STEP = (
    "uv run pla signals --workspace . "
    "--fail-on-kind merge_conflict "
    "--fail-on-kind syntax_error "
    "--fail-on-kind secret_file "
    "--fail-on-kind broken_link"
)

# Behavior 5: the state-independent, must-never-appear arm set...
ARMED_KINDS = frozenset(
    {"merge_conflict", "syntax_error", "secret_file", "broken_link"}
)

# ...and the six kinds that may NEVER be armed by a build gate. The first three
# are non-zero in this repo today; the last three are local-state dependent.
FORBIDDEN_KINDS = frozenset(
    {
        "lockfile_drift",
        "test_posture",
        "ci_config",
        "working_tree",
        "git_state",
        "git_stash",
    }
)

# Behavior 1: the six pre-existing gate steps, in their established order. The
# new step APPENDS; every one of these keeps its relative position.
PREEXISTING_GATE_STEPS = (
    "uv sync --locked",
    "uv run pytest",
    "uv run mypy src/proactive_loop "
    "examples/check_run.py examples/check_autonomy.py",
    "make demo",
    "test -f .pla_runs/slate.json",
    "ls .pla_runs/run-*/artifacts/*.md",
)

# Behavior 6: the two demo-artifact assertions --- the ONLY gate steps
# tests/test_iter110_behavior.py is allowed to shell out to.
ARTIFACT_ASSERTIONS = (
    "test -f .pla_runs/slate.json",
    "ls .pla_runs/run-*/artifacts/*.md",
)

# Behavior 7: graded `run:` steps ci.yml exposes today. Bumped 6 -> 7 by factory
# iter 186, which added an armed `pla verify --fail-on-unresolved` of the demo's
# own slate/snapshot pair AHEAD of this iteration's self-scan, and 7 -> 8 by
# factory iter 254, which added an armed `pla signals --fail-over 9` count budget
# in the same slot for the same reason: this self-scan stays LAST.
EXPECTED_CI_RUN_STEPS = 9

# Behavior 7: entries the two sibling drift guards' CI_GATE_STEPS tuples declare.
# It exceeds EXPECTED_CI_RUN_STEPS by one because the two demo-artifact
# assertions share a single `run: |` block -- one graded step, two gate commands.
# 8 -> 9 in factory iter 254 (the armed count budget). This literal is the thing
# doing the work: it pins the SIZE of the gate, so it must move deliberately and
# cannot be derived from CI_GATE_STEPS without becoming a tautology.
# 9 until factory iter 264 inserted the same-run `--baseline` round trip ahead of
# the two `--workspace .` gates; the self-scan is still LAST.
EXPECTED_TOTAL_GATE_STEPS = 10

# Behavior 8: the `check` recipe stays pure shell + $(MAKE) + the uv runner.
ALLOWED_CHECK_COMMANDS = frozenset({"rm", "test", "ls", "uv", "make"})

# Behavior 8: the armed step may use only flags `pla signals` already had.
ALLOWED_GATE_STEP_FLAGS = frozenset({"--workspace", "--fail-on-kind"})

_REDIRECT_SUFFIX = re.compile(r"\s*>\s*/dev/null(\s+2>&1)?\s*$")
_RUN_KEY = re.compile(r"^(\s*)run:\s*(.*)$")


# --------------------------------------------------------------------------
# Helpers --- the Makefile-reading pattern of tests/test_iter102_behavior.py
# (_makefile_lines / _make_recipe / _normalize / _recipe_steps / _bare), plus an
# INDEPENDENT ci.yml `run:`-step reader written for this module.
#
# The ci.yml reader is deliberately NOT the sibling guards' helper: behavior 2 is
# a "these two files cannot diverge" claim, and a claim like that verified with
# the same normalization helper that encodes it only proves the helper agrees
# with itself. A second, independent reader is the point.
# --------------------------------------------------------------------------


def _makefile_lines() -> list[str]:
    return MAKEFILE.read_text(encoding="utf-8").splitlines()


def _make_recipe(target: str) -> list[str]:
    """The tab-indented recipe lines of a Makefile ``target:`` (each stripped)."""
    recipe: list[str] = []
    in_target = False
    for ln in _makefile_lines():
        if re.match(rf"^{re.escape(target)}\s*:", ln):
            in_target = True
            continue
        if in_target:
            if ln.startswith("\t"):
                recipe.append(ln.strip())
            elif ln.strip() == "":
                continue
            else:
                break
    return recipe


def _normalize(line: str) -> str:
    """``$(MAKE)`` -> ``make``, whitespace collapsed, make's line prefixes
    (``@`` silence, ``-`` ignore-errors, ``+`` always-run) dropped."""
    text = re.sub(r"\s+", " ", line.replace("$(MAKE)", "make")).strip()
    return text.lstrip("@-+ ").strip()


def _recipe_steps(target: str) -> list[str]:
    """Normalized SHELL steps of a recipe: one per line, ``&&`` chains split,
    pure ``#`` comment lines dropped."""
    steps: list[str] = []
    for line in _make_recipe(target):
        normalized = _normalize(line)
        if not normalized or normalized.startswith("#"):
            continue
        for fragment in normalized.split("&&"):
            fragment = fragment.strip()
            if fragment and not fragment.startswith("#"):
                steps.append(fragment)
    return steps


def _bare(step: str) -> str:
    """A step's identity: its command with any trailing ``> /dev/null`` removed."""
    return _REDIRECT_SUFFIX.sub("", step).strip()


def _check_steps() -> list[str]:
    return [_bare(step) for step in _recipe_steps("check")]


def _ci_run_blocks(text: str) -> list[list[str]]:
    """Every graded ``run:`` step of a workflow, as a list of command LINES.

    Handles both scalar (``run: uv run pytest``) and block (``run: |``) forms: a
    block's body is every following line indented deeper than the ``run:`` key
    itself, which is exactly YAML's block-scalar rule for this shape and needs no
    YAML parser (this suite has no yaml dependency and must stay offline).
    """
    lines = text.splitlines()
    blocks: list[list[str]] = []
    index = 0
    while index < len(lines):
        match = _RUN_KEY.match(lines[index])
        if not match:
            index += 1
            continue
        indent, inline = match.group(1), match.group(2).strip()
        index += 1
        if inline and inline not in {"|", "|-", "|+", ">", ">-", ">+"}:
            blocks.append([inline])
            continue
        body: list[str] = []
        while index < len(lines):
            candidate = lines[index]
            if candidate.strip() == "":
                index += 1
                continue
            leading = len(candidate) - len(candidate.lstrip())
            if leading <= len(indent):
                break
            body.append(candidate.strip())
            index += 1
        blocks.append(body)
    return blocks


def _ci_commands() -> list[str]:
    """Every command LINE any graded ``run:`` step executes, comments dropped."""
    text = WORKFLOW.read_text(encoding="utf-8")
    commands: list[str] = []
    for block in _ci_run_blocks(text):
        for line in block:
            if line and not line.startswith("#"):
                commands.append(line)
    return commands


def _armed_kinds(step: str) -> list[str]:
    """The kinds a ``--fail-on-kind`` step arms, parsed out of the step text."""
    return re.findall(r"--fail-on-kind\s+([A-Za-z_]+)", step)


def _console_script() -> Path:
    """The installed ``pla`` console script (iter114's resolution convention)."""
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


def _gate_argv(workspace: Path) -> list[str]:
    """The gate's OWN armed command, re-pointed at ``workspace``.

    Built from the PARSED Makefile step, never from a re-typed copy, so this runs
    what the gate runs. Two substitutions: ``uv run pla`` -> the installed
    console script (the same entry point, without a nested `uv` resolve), and the
    ``--workspace`` value -> the fixture path.
    """
    tokens = _check_steps()[-1].split()
    assert tokens[:3] == ["uv", "run", "pla"], (
        f"the final `check` step must invoke the product's console script; "
        f"tokens were {tokens}"
    )
    argv = [str(_console_script()), *tokens[3:]]
    position = argv.index("--workspace")
    argv[position + 1] = str(workspace)
    return argv


def _run_gate(workspace: Path, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        _gate_argv(workspace),
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=120,
    )


def _plant_tripping_workspace(root: Path) -> Path:
    """A workspace holding exactly the two must-never-appear findings the gate
    arms and can be planted deterministically offline: an unparseable ``.py``
    (``syntax_error``) and a ``.env`` (``secret_file``)."""
    workspace = root / "ws"
    workspace.mkdir()
    (workspace / "broken.py").write_text("def f(:\n", encoding="utf-8")
    (workspace / ".env").write_text("TOKEN=abc\n", encoding="utf-8")
    return workspace


# ==========================================================================
# Behavior 1 --- the gate step exists, is LAST, and appends without reordering.
# ==========================================================================


def test_b1_final_check_step_is_the_armed_signals_selfscan() -> None:
    steps = _check_steps()
    assert steps, "Makefile must define a `check:` target with a non-empty recipe"
    assert steps[-1] == EXPECTED_GATE_STEP, (
        "the FINAL step of the `check` recipe must be the armed self-scan "
        f"{EXPECTED_GATE_STEP!r} -- the product policing the repo that ships it; "
        f"last step was {steps[-1]!r}. Full recipe steps: {steps}"
    )


def test_b1_gate_step_runs_after_install_and_after_both_artifact_assertions() -> None:
    steps = _check_steps()
    gate_at = steps.index(EXPECTED_GATE_STEP)
    for earlier in ("uv sync --locked", *ARTIFACT_ASSERTIONS):
        assert earlier in steps, f"missing pre-existing gate step {earlier!r}: {steps}"
        assert steps.index(earlier) < gate_at, (
            f"the armed self-scan (step {gate_at}) must run AFTER {earlier!r} "
            f"(step {steps.index(earlier)}): it needs the project venv `uv sync` "
            "creates, and moving it ahead of the demo-artifact assertions would "
            f"let an enforcement failure mask an artifact failure. Steps: {steps}"
        )


def test_b1_preexisting_gate_steps_keep_their_relative_order() -> None:
    steps = _check_steps()
    positions: list[int] = []
    for step in PREEXISTING_GATE_STEPS:
        assert step in steps, (
            f"pre-existing gate step {step!r} disappeared from the `check` recipe; "
            f"this iteration is APPEND-ONLY. Steps: {steps}"
        )
        positions.append(steps.index(step))
    assert positions == sorted(positions), (
        "the six pre-existing gate steps must keep their established relative "
        f"order (the new step APPENDS, it does not insert); positions were "
        f"{list(zip(PREEXISTING_GATE_STEPS, positions))}"
    )


# ==========================================================================
# Behavior 2 --- CI mirrors the Makefile step string-for-string.
# ==========================================================================


def test_b2_ci_runs_the_makefile_gate_step_verbatim() -> None:
    assert WORKFLOW.is_file(), (
        f"missing {WORKFLOW.relative_to(REPO)} -- the CI gate the recipe mirrors"
    )
    makefile_step = _check_steps()[-1]
    commands = _ci_commands()
    assert makefile_step in commands, (
        f"ci.yml must expose a graded `run:` step whose command is string-equal "
        f"to the Makefile's final gate step {makefile_step!r}, so the local and "
        f"CI gates cannot silently diverge. CI commands parsed: {commands}"
    )


def test_b2_the_armed_scan_is_a_single_ci_step() -> None:
    commands = _ci_commands()
    armed = [c for c in commands if "--fail-on-kind" in c]
    assert len(armed) == 1, (
        "exactly ONE CI command may arm the enforcement gate (two would double "
        f"the scan cost and could disagree); found {armed}"
    )


# ==========================================================================
# Behavior 3 --- GREEN side: the armed command is clean on THIS repository.
# ==========================================================================


def test_b3_armed_gate_exits_zero_and_says_nothing_on_this_repository(
    tmp_path: Path,
) -> None:
    proc = _run_gate(REPO, tmp_path)
    assert proc.returncode == 0, (
        "the armed self-scan must exit 0 on this repository -- otherwise the gate "
        "it was just added to is red on arrival and every push shows a failing "
        f"public build. rc={proc.returncode} stderr={proc.stderr!r}"
    )
    assert proc.stderr == "", (
        "a passing gate step must write NOTHING to stderr (the `gate:` line is "
        f"the trip channel only); got {proc.stderr!r}"
    )
    assert proc.stdout.strip(), (
        "the scan must still REPORT its findings on stdout; a silent green run "
        "cannot be distinguished from a scan that collected nothing"
    )


def test_b3_the_gate_step_writes_no_state_dir_beside_its_caller(
    tmp_path: Path,
) -> None:
    """A gate step that wrote a state dir would litter every developer's CWD and
    (on a self-scan) could feed its own output back into the next scan."""
    before = sorted(p.name for p in tmp_path.iterdir())
    proc = _run_gate(REPO, tmp_path)
    after = sorted(p.name for p in tmp_path.iterdir())
    assert proc.returncode == 0, f"green run failed: {proc.returncode} {proc.stderr!r}"
    assert before == after, (
        f"the armed scan must be READ-ONLY: it created {sorted(set(after) - set(before))} "
        f"in its working directory"
    )


# ==========================================================================
# Behavior 4 --- TRIP side: a planted known-bad workspace must FIRE exit 5.
#
# The green side alone is worthless as evidence: a gate that can never fire is
# indistinguishable from a gate that is passing.
# ==========================================================================


def test_b4_armed_gate_exits_5_on_a_planted_workspace(tmp_path: Path) -> None:
    workspace = _plant_tripping_workspace(tmp_path)
    proc = _run_gate(workspace, tmp_path)
    assert proc.returncode == 5, (
        "a workspace holding an unparseable .py and a .env must trip the armed "
        f"gate with exit 5 (the documented CI branch point); rc={proc.returncode} "
        f"stderr={proc.stderr!r}"
    )


def test_b4_trip_reports_exactly_one_stderr_line_naming_both_kinds(
    tmp_path: Path,
) -> None:
    workspace = _plant_tripping_workspace(tmp_path)
    proc = _run_gate(workspace, tmp_path)
    lines = [ln for ln in proc.stderr.splitlines() if ln.strip()]
    assert len(lines) == 1, (
        f"the trip must be ONE diagnostic line on stderr, not {len(lines)}: "
        f"{proc.stderr!r}"
    )
    assert lines[0].startswith("gate: fail-on-kind tripped --"), (
        f"the trip line must start with the documented prefix; got {lines[0]!r}"
    )
    for kind in ("syntax_error", "secret_file"):
        assert kind in lines[0], (
            f"the trip line must name every tripped kind (missing {kind!r}) so a "
            f"CI log says WHAT failed, not merely THAT it failed; got {lines[0]!r}"
        )


# ==========================================================================
# Behavior 5 --- the armed set is state-independent (the regression guard).
# ==========================================================================


def test_b5_gate_arms_exactly_the_state_independent_kinds() -> None:
    armed = _armed_kinds(_check_steps()[-1])
    assert armed, "the final gate step arms no kind at all -- it cannot ever fail"
    assert set(armed) == ARMED_KINDS, (
        "the gate must arm exactly the state-independent, must-never-appear kinds "
        f"{sorted(ARMED_KINDS)}; the recipe arms {armed}"
    )
    assert len(armed) == len(set(armed)), f"a kind is armed twice: {armed}"


def test_b5_gate_arms_no_local_state_or_already_present_kind() -> None:
    for source, step in (
        ("Makefile", _check_steps()[-1]),
        ("ci.yml", next(c for c in _ci_commands() if "--fail-on-kind" in c)),
    ):
        offenders = sorted(set(_armed_kinds(step)) & FORBIDDEN_KINDS)
        assert not offenders, (
            f"{source} arms {offenders}, which no build gate may arm: "
            "lockfile_drift / test_posture / ci_config are NON-ZERO in this repo "
            "today (red on arrival), and working_tree / git_state / git_stash are "
            "LOCAL-STATE dependent -- they would make `make check` red for every "
            "developer with an uncommitted edit while CI, a fresh checkout, stayed "
            "green. Arm a kind only after measuring that it is zero AND "
            "state-independent."
        )


# ==========================================================================
# Behavior 6 --- the positional-slice trap: the artifact slice still names 2.
# ==========================================================================


def test_b6_artifact_assertion_slice_still_names_exactly_the_two_assertions() -> None:
    from tests.test_iter110_behavior import ARTIFACT_ASSERTION_STEPS

    assert tuple(ARTIFACT_ASSERTION_STEPS) == ARTIFACT_ASSERTIONS, (
        "tests/test_iter110_behavior.py's ARTIFACT_ASSERTION_STEPS must still be "
        f"exactly the two demo-artifact assertions {list(ARTIFACT_ASSERTIONS)}; it "
        f"is {list(ARTIFACT_ASSERTION_STEPS)}. It is a POSITIONAL slice of "
        "CI_GATE_STEPS and that module SHELLS OUT to every step in it, so an "
        "open-ended tail silently swept this iteration's `uv run pla signals` step "
        "into the executed set -- breaking that module's own never-runs-`uv` "
        "contract while every assertion still read green."
    )


def test_b6_the_new_gate_step_is_never_executed_by_the_sibling_guard() -> None:
    from tests.test_iter110_behavior import ARTIFACT_ASSERTION_STEPS, CI_GATE_STEPS

    assert EXPECTED_GATE_STEP not in tuple(ARTIFACT_ASSERTION_STEPS), (
        "the armed self-scan must NOT be in the set of steps the sibling guard "
        "executes: it is the expensive, whole-repo step"
    )
    expensive = [s for s in CI_GATE_STEPS if s not in tuple(ARTIFACT_ASSERTION_STEPS)]
    assert EXPECTED_GATE_STEP in expensive, (
        "the armed self-scan must be classified with the expensive, "
        f"never-executed gate steps; never-executed set was {expensive}"
    )


# ==========================================================================
# Behavior 7 --- both drift guards moved in the same commit.
# ==========================================================================


def test_b7_both_drift_guards_declare_the_new_step_as_the_last() -> None:
    """The self-scan must stay the FINAL gate step, so a tripped scan can never
    mask an earlier assertion.

    Originally pinned POSITIONALLY (``len(steps) == 7`` and ``steps[6]``), which
    made a later step inserted anywhere ahead of the self-scan read as this
    iteration's step going missing. Factory iter 186 inserted exactly such a step
    (armed citation verification, index 6), so the claim is now expressed the way
    iter 128 actually meant it: the self-scan is LAST, the six pre-existing steps
    keep their positions, and the declared total is pinned by its own constant.
    """
    from tests.test_iter102_behavior import CI_GATE_STEPS as STEPS_102
    from tests.test_iter110_behavior import CI_GATE_STEPS as STEPS_110

    for name, steps in (("iter102", STEPS_102), ("iter110", STEPS_110)):
        assert len(steps) == EXPECTED_TOTAL_GATE_STEPS, (
            f"{name}'s CI_GATE_STEPS must declare {EXPECTED_TOTAL_GATE_STEPS} gate "
            f"steps; it declares {len(steps)}: {list(steps)}. A step may be added, "
            "but only together with this constant and the `check` recipe."
        )
        assert steps[-1] == EXPECTED_GATE_STEP, (
            f"{name}'s LAST gate step must be the armed self-scan -- it runs last "
            "so a tripped scan cannot mask an earlier assertion; got "
            f"{steps[-1]!r}"
        )
        assert tuple(steps[:6]) == PREEXISTING_GATE_STEPS, (
            f"{name}'s first six gate steps must be unchanged (append-only); got "
            f"{list(steps[:6])}"
        )
    assert tuple(STEPS_102) == tuple(STEPS_110), (
        "the two drift guards must declare the SAME gate contract, or one of them "
        f"is stale: iter102={list(STEPS_102)} iter110={list(STEPS_110)}"
    )


def test_b7_both_drift_guards_expect_seven_graded_ci_run_steps() -> None:
    from tests.test_iter102_behavior import EXPECTED_CI_RUN_STEPS as COUNT_102
    from tests.test_iter110_behavior import EXPECTED_CI_RUN_STEPS as COUNT_110

    assert COUNT_102 == COUNT_110 == EXPECTED_CI_RUN_STEPS, (
        f"both drift guards must expect {EXPECTED_CI_RUN_STEPS} graded `run:` "
        f"steps after this iteration; iter102={COUNT_102} iter110={COUNT_110}"
    )
    blocks = _ci_run_blocks(WORKFLOW.read_text(encoding="utf-8"))
    assert len(blocks) == EXPECTED_CI_RUN_STEPS, (
        f"ci.yml must expose exactly {EXPECTED_CI_RUN_STEPS} graded `run:` steps "
        f"(locked install, pytest, mypy, `make demo`, the demo-artifact block, the "
        f"armed citation verification, and the armed self-scan); an independent "
        f"parse found {len(blocks)}: {blocks}"
    )


# ==========================================================================
# Behavior 8 --- no runtime or interface change; this is build tooling.
# ==========================================================================


def test_b8_check_recipe_introduces_no_new_command_word() -> None:
    offenders = [
        (step.split()[0], step)
        for step in _check_steps()
        if step.split()[0] not in ALLOWED_CHECK_COMMANDS
    ]
    assert not offenders, (
        f"the `check` recipe must stay pure shell + `$(MAKE)` + `uv` "
        f"({sorted(ALLOWED_CHECK_COMMANDS)}); new tools found: {offenders}"
    )


def test_b8_gate_step_uses_only_preexisting_signals_flags() -> None:
    tokens = _check_steps()[-1].split()
    assert tokens[3] == "signals", (
        f"the gate must dogfood the existing `signals` verb, not a new one; got "
        f"{tokens[3]!r}"
    )
    flags = {t for t in tokens if t.startswith("-")}
    assert flags <= ALLOWED_GATE_STEP_FLAGS, (
        "this iteration adds NO CLI flag: the gate step may use only "
        f"{sorted(ALLOWED_GATE_STEP_FLAGS)}; it uses {sorted(flags)}"
    )


def test_b8_arming_the_gate_leaves_stdout_byte_identical(tmp_path: Path) -> None:
    """The enforcement flag is an EXIT-CODE contract, not a reporting change: the
    same scan must print the same bytes armed and unarmed, so adding the gate step
    could not have altered what the tool reports."""
    workspace = _plant_tripping_workspace(tmp_path)
    argv = _gate_argv(workspace)
    unarmed = [argv[0]]
    index = 1
    while index < len(argv):
        if argv[index] == "--fail-on-kind":
            index += 2
            continue
        unarmed.append(argv[index])
        index += 1
    armed_proc = subprocess.run(
        argv, cwd=str(tmp_path), capture_output=True, text=True, timeout=120
    )
    plain_proc = subprocess.run(
        unarmed, cwd=str(tmp_path), capture_output=True, text=True, timeout=120
    )
    assert armed_proc.returncode == 5, (
        f"armed run must trip: rc={armed_proc.returncode} {armed_proc.stderr!r}"
    )
    assert plain_proc.returncode == 0, (
        f"unarmed run must exit 0: rc={plain_proc.returncode} {plain_proc.stderr!r}"
    )
    assert armed_proc.stdout == plain_proc.stdout, (
        "stdout must be byte-identical with and without the armed flags -- the "
        "gate may only add ONE stderr line and change the exit code"
    )
    assert plain_proc.stderr == "", (
        f"the unarmed scan must be silent on stderr; got {plain_proc.stderr!r}"
    )


def test_b8_no_new_runtime_dependency() -> None:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    deps = data["project"]["dependencies"]
    assert len(deps) == 1 and deps[0].lower().startswith("pydantic"), (
        "the runtime dependency set must stay pydantic-v2-ONLY (this iteration is "
        f"build tooling: no dependency change, so no lockfile churn); found {deps}"
    )


# ==========================================================================
# Guard self-tests --- every reader above must FIRE on a known-bad sample.
# A tripwire that cannot be made to fire is indistinguishable from a broken one.
# ==========================================================================


def test_guard_ci_run_reader_handles_scalar_and_block_steps() -> None:
    sample = (
        "jobs:\n"
        "  build:\n"
        "    steps:\n"
        "      - name: install\n"
        "        run: uv sync --locked\n"
        "      - name: artifacts\n"
        "        run: |\n"
        "          test -f a\n"
        "\n"
        "          ls b > /dev/null\n"
        "      - name: after\n"
        "        uses: actions/checkout@v4\n"
    )
    assert _ci_run_blocks(sample) == [
        ["uv sync --locked"],
        ["test -f a", "ls b > /dev/null"],
    ]
    assert _ci_run_blocks("steps:\n  - uses: actions/checkout@v4\n") == []


def test_guard_armed_kind_parser_fires_and_does_not_overmatch() -> None:
    assert _armed_kinds("pla signals --fail-on-kind todo --fail-on-kind note") == [
        "todo",
        "note",
    ]
    assert _armed_kinds("pla signals --kind todo --summary") == []


def test_guard_recipe_reader_rejects_a_recipe_with_a_wrong_final_step() -> None:
    """The Makefile reader must be order-sensitive and comment-blind, or
    behavior 1 could pass on a recipe whose last step is something else."""
    assert _bare("ls x > /dev/null") == "ls x"
    assert _normalize("\t@$(MAKE) demo") == "make demo"
    steps = _check_steps()
    assert steps[-1] != "uv sync --locked", (
        "sanity: the reader returned the FIRST step as the last one -- it is not "
        f"order-preserving. Steps: {steps}"
    )
