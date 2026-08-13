"""Black-box behavior tests for state-dir iteration 103 (ships as commit-seq
**factory iter 110**): the local release gate ``make check`` gains a single
NAMED state-dir freshness pre-step (``rm -rf .pla_runs``) as its first recipe
step, and the iter-102 drift-guard gains the missing recipe -> declared-set
direction (ROADMAP #114).

Feature under test (``pm.md``): row #102 shipped ``make check`` as a local
reproduction of the graded CI gate (it overclaimed a full equivalence with CI,
which factory iter 156 corrected: CI grades those steps under both matrix
interpreters and ``make check-matrix`` covers the second leg's SUITE), but its
last two steps
(``test -f .pla_runs/slate.json`` / ``ls .pla_runs/run-*/artifacts/*.md``) are
pure EXISTENCE checks against a PERSISTENT gitignored dir. In CI that is a
freshness check by accident of environment (every run is a fresh checkout);
locally it is FAIL-OPEN -- a demo that exits 0 and writes nothing still passes
the gate because hours-old artifacts satisfy both assertions. Establishing a
clean pre-state converts both existence checks into freshness checks. The second
half closes a fail-open in the GUARD itself: iter-102 asserts every declared
gate step appears in the recipe, but nothing enumerated the recipe's OWN lines,
so an undeclared local step was invisible. Behavior 3 adds that direction, so the
pre-step is exactly ONE named allowance rather than a general escape hatch.

ISOLATION CONTRACT (honored): every assertion here is written from THIS
iteration's spec (``pm.md`` Expected Behaviors) plus the public build artifacts
the spec designates as this iteration's black-box surfaces -- the parsed TEXT of
``Makefile`` and ``.github/workflows/ci.yml`` -- and (for behavior 7's
no-new-dependency half) ``pyproject.toml``. **No file under ``src/`` was read, no
engineer or reviewer note was read, and no ``git diff`` was consulted by the
author**: the spec-declared strings (the pre-step, the demo state dir, the CI
gate commands, the six pre-existing target names, the CI run-step count) are
encoded below as the CONTRACT's ground facts, NOT imported from or copied out of
any implementation, so a silent drift goes RED.

Cap-safety: behaviors 1-7 are pure file reads and text parsing. Behavior 8 is the
single deliberate exception -- it shells out, but ONLY the three cheap steps
``rm -rf`` / ``test -f`` / ``ls`` (milliseconds), taken VERBATIM from the parsed
recipe, and ONLY inside ``tmp_path``. The install / ``uv run pytest`` / mypy /
``make demo`` / armed ``pla signals`` self-scan steps are NEVER executed by this
suite (asserted in-test), so there is no nested pytest run, no ``uv``, no
``make``, and no network.
"""

from __future__ import annotations

import re
import subprocess
import tomllib
from pathlib import Path

# --------------------------------------------------------------------------
# Tester's ground facts --- the spec-declared contract constants (pm.md).
# Encoded here (NOT imported from the implementation) so these tests encode the
# CONTRACT and would catch a silent drift in either direction.
# --------------------------------------------------------------------------

REPO = Path(__file__).resolve().parents[1]
MAKEFILE = REPO / "Makefile"
WORKFLOW = REPO / ".github" / "workflows" / "ci.yml"
PYPROJECT = REPO / "pyproject.toml"

# THIS iteration's single new step, and the one directory it removes.
FRESHNESS_PRE_STEP = "rm -rf .pla_runs"
DEMO_STATE_DIR = ".pla_runs"

# The ordered seven commands of the CI graded gate (the first six unchanged from
# iter-102; the 7th, an armed `pla signals` self-scan, added factory iter 128).
# The artifact-list step is matched WITHOUT its `> /dev/null` suffix.
CI_GATE_STEPS = (
    "uv sync --locked",
    "uv run pytest",
    "uv run mypy src/proactive_loop",
    "make demo",
    "test -f .pla_runs/slate.json",
    "ls .pla_runs/run-*/artifacts/*.md",
    "uv run pla signals --workspace . --fail-on-kind merge_conflict "
    "--fail-on-kind syntax_error --fail-on-kind secret_file "
    "--fail-on-kind broken_link",
)

# The two demo-artifact assertions --- the steps this iteration makes honest, and
# the only gate steps behavior 8 is permitted to execute.
#
# EXPLICITLY BOUNDED `[4:6]`, not an open-ended `[4:]`: this is a POSITIONAL
# slice over a tuple that later iterations append to, and behavior 8 SHELLS OUT
# to every step in it. An open tail silently swept factory iter 128's
# `uv run pla signals ...` step into the executed set, which would have broken
# this module's own contract that the suite never invokes `uv` (a nested run
# strands the tester stage against its 600s cap) -- while every assertion still
# read green. Widen this bound only for a step that is genuinely cheap AND safe
# to run inside the suite.
ARTIFACT_ASSERTION_STEPS = CI_GATE_STEPS[4:6]

# Pre-existing .PHONY targets that must survive this additive edit.
PREEXISTING_TARGETS = ("setup", "test", "cov", "typecheck", "demo", "clean")

# Graded `run:` steps ci.yml exposes today.
EXPECTED_CI_RUN_STEPS = 6

# Only these command words may appear in the `check` recipe: pure shell plus
# `$(MAKE)` and the `uv` runner. A new tool would trip behavior 7.
ALLOWED_CHECK_COMMANDS = frozenset({"rm", "test", "ls", "uv", "make"})

# A trailing output redirect is not part of a step's identity.
_REDIRECT_SUFFIX = re.compile(r"\s*>\s*/dev/null(\s+2>&1)?\s*$")


# --------------------------------------------------------------------------
# Helpers --- the Makefile-reading pattern reused from
# tests/test_iter102_behavior.py (_makefile_lines / _phony_tokens /
# _make_recipe / $(MAKE)->make + whitespace normalization).
# --------------------------------------------------------------------------


def _makefile_lines() -> list[str]:
    return MAKEFILE.read_text(encoding="utf-8").splitlines()


def _phony_tokens() -> set[str]:
    """The set of target names declared on the Makefile ``.PHONY:`` line(s)."""
    tokens: set[str] = set()
    for ln in _makefile_lines():
        if ln.startswith(".PHONY:"):
            tokens.update(ln.split(":", 1)[1].split())
    return tokens


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
                continue  # blank lines inside a recipe are tolerated
            else:
                break
    return recipe


def _normalize(line: str) -> str:
    """iter-102 normalization (``$(MAKE)`` -> ``make``, whitespace collapsed),
    plus make's recipe-line prefixes (``@`` silence, ``-`` ignore-errors, ``+``
    always-run) dropped: those select make's ECHO/ERROR policy, not the command.
    """
    text = re.sub(r"\s+", " ", line.replace("$(MAKE)", "make")).strip()
    return text.lstrip("@-+ ").strip()


def _recipe_steps(target: str) -> list[str]:
    """Normalized SHELL steps of a recipe.

    A recipe line may chain commands with ``&&``, so each fragment is its own
    step (that keeps behavior 3 honest against a chained undeclared command).
    Pure ``#`` comment lines are not steps and are dropped.
    """
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


def _normalized_recipe_text(target: str) -> str:
    """The whole recipe as one normalized string (iter-102's matching surface)."""
    text = "\n".join(_make_recipe(target)).replace("$(MAKE)", "make")
    return re.sub(r"\s+", " ", text).strip()


def _resolve_make_value(value: str) -> str:
    """Resolve ``$(NAME)`` / ``${NAME}`` against the Makefile's own assignments,
    so a variable-ised state dir is compared by VALUE, not by spelling."""
    match = re.fullmatch(r"\$[({](\w+)[)}]", value)
    if not match:
        return value
    name = match.group(1)
    for ln in _makefile_lines():
        assignment = re.match(rf"^{re.escape(name)}\s*[:?+]?=\s*(.+?)\s*$", ln)
        if assignment:
            return assignment.group(1)
    return value


def _step_for_gate(gate_step: str) -> str:
    """The recipe step (VERBATIM, redirect included) whose identity is ``gate_step``."""
    for step in _recipe_steps("check"):
        if _bare(step) == gate_step:
            return step
    raise AssertionError(
        f"the `check` recipe has no step whose command is {gate_step!r}; "
        f"steps were {_recipe_steps('check')}"
    )


# ==========================================================================
# Behavior 1 --- the pre-step exists and runs FIRST.
# ==========================================================================


def test_b1_first_check_step_is_the_freshness_pre_step() -> None:
    steps = _recipe_steps("check")
    assert steps, "Makefile must define a `check:` target with a non-empty recipe"
    assert _bare(steps[0]) == FRESHNESS_PRE_STEP, (
        f"the FIRST step of the `check` recipe must be exactly "
        f"{FRESHNESS_PRE_STEP!r} so the gate's two demo-artifact assertions can "
        f"only pass on artifacts THIS invocation produced; first step was "
        f"{steps[0]!r}. Full recipe steps: {steps}"
    )


def test_b1_pre_step_precedes_every_ci_gate_step() -> None:
    norm = _normalized_recipe_text("check")
    pre_pos = norm.find(FRESHNESS_PRE_STEP)
    assert pre_pos >= 0, (
        f"missing freshness pre-step {FRESHNESS_PRE_STEP!r} in the normalized "
        f"`check` recipe:\n{norm}"
    )
    for gate_step in CI_GATE_STEPS:
        pos = norm.find(gate_step)
        assert pos >= 0, f"missing gate step {gate_step!r} in:\n{norm}"
        assert pre_pos < pos, (
            f"the freshness pre-step (at {pre_pos}) must run STRICTLY BEFORE "
            f"gate step {gate_step!r} (at {pos}) -- a wipe after a gate step "
            f"would either be pointless or destroy the artifacts under test. "
            f"Normalized recipe:\n{norm}"
        )


# ==========================================================================
# Behavior 2 --- no regression of the iter-102 property.
# ==========================================================================


def test_b2_check_is_still_phony_with_a_recipe() -> None:
    tokens = _phony_tokens()
    assert "check" in tokens, (
        f"Makefile .PHONY must still declare 'check'; found {sorted(tokens)}"
    )
    assert _make_recipe("check"), "`check` must still have a non-empty recipe"


def test_b2_check_recipe_still_runs_the_whole_gate_in_ci_order() -> None:
    norm = _normalized_recipe_text("check")
    prev = -1
    for gate_step in CI_GATE_STEPS:
        pos = norm.find(gate_step)
        assert pos >= 0, (
            f"the `check` recipe must still reproduce CI gate step {gate_step!r} "
            f"(iter-102's property); normalized recipe:\n{norm}"
        )
        assert pos >= prev, (
            f"gate step {gate_step!r} (at {pos}) appears BEFORE the previous step "
            f"(at {prev}); the gate must run in CI's own order "
            f"{list(CI_GATE_STEPS)}. Normalized recipe:\n{norm}"
        )
        prev = pos


def test_b2_no_check_step_suppresses_its_exit_status() -> None:
    """The gate must stay FAIL-CLOSED.

    ``_normalize`` deliberately drops make's recipe-line prefixes so ``@rm ...``
    still satisfies behavior 1 -- but ``-`` (ignore-errors) is NOT cosmetic: a
    line written ``-uv run pytest`` would make the local gate exit 0 on a red
    suite, which is exactly the class of fail-open this iteration exists to
    close. So the RAW lines are checked here, before normalization.
    """
    offenders = [
        ln for ln in _make_recipe("check") if ln.lstrip("@+ ").startswith("-")
    ]
    assert not offenders, (
        "no `check` recipe line may carry make's `-` (ignore-errors) prefix: the "
        "local gate must fail on the first non-zero step, exactly as CI does. "
        f"Offending raw lines: {offenders}"
    )


# ==========================================================================
# Behavior 3 --- recipe -> declared-set direction (closes the guard's own
# fail-open): every recipe step is a declared gate step or THE pre-step.
# ==========================================================================


def test_b3_every_check_step_is_declared() -> None:
    allowed = set(CI_GATE_STEPS) | {FRESHNESS_PRE_STEP}
    steps = _recipe_steps("check")
    assert steps, "`check` recipe is empty -- this direction would pass vacuously"
    offenders = [step for step in steps if _bare(step) not in allowed]
    assert not offenders, (
        "these `check` recipe steps are neither one of the declared CI gate "
        f"steps nor the single named freshness pre-step {FRESHNESS_PRE_STEP!r}: "
        f"{offenders}. The local gate may differ from CI by exactly ONE named "
        f"allowance -- it is not an escape hatch for arbitrary local steps. "
        f"Declared set: {sorted(allowed)}"
    )


def test_b3_direction_fires_on_a_synthetic_undeclared_step() -> None:
    """Two-sided: the classifier must REJECT an undeclared step (a guard that has
    never fired is not evidence) and ACCEPT the real recipe's steps."""
    allowed = set(CI_GATE_STEPS) | {FRESHNESS_PRE_STEP}
    known_bad = ("curl https://example.com", "rm -rf /", "uv run pytest -x -k smoke")
    for bad in known_bad:
        assert _bare(bad) not in allowed, f"classifier failed to reject {bad!r}"
    for good in (*CI_GATE_STEPS, FRESHNESS_PRE_STEP):
        assert _bare(good) in allowed, f"classifier wrongly rejected {good!r}"
    assert _bare("ls .pla_runs/run-*/artifacts/*.md > /dev/null") in allowed, (
        "a trailing `> /dev/null` redirect must not change a step's identity"
    )


# ==========================================================================
# Behavior 4 --- the freshness target is single-sourced.
# ==========================================================================


def test_b4_pre_step_removes_exactly_the_demo_state_dir() -> None:
    pre_step = _bare(_recipe_steps("check")[0])
    operands = pre_step.split()[2:]  # after `rm -rf`
    assert operands == [DEMO_STATE_DIR], (
        f"the pre-step must remove exactly {DEMO_STATE_DIR!r} (the demo's own "
        f"state dir) and nothing else -- `$(MAKE) clean` was rejected because it "
        f"also nukes caches for no freshness gain; pre-step was {pre_step!r}"
    )


def test_b4_demo_recipe_passes_the_same_state_dir() -> None:
    demo = _normalized_recipe_text("demo")
    values = [
        _resolve_make_value(v)
        for v in re.findall(r"--state-dir[=\s]+(\S+)", demo)
    ]
    assert values, (
        "could not find a `--state-dir` argument in the `demo` recipe, so the "
        "pre-step's target cannot be shown to be the dir the demo writes. "
        f"Normalized `demo` recipe:\n{demo}"
    )
    assert set(values) == {DEMO_STATE_DIR}, (
        f"the `demo` recipe must write to {DEMO_STATE_DIR!r} -- the same dir the "
        f"`check` pre-step removes -- or the freshness guarantee is vacuous; "
        f"found --state-dir values {values}. Normalized `demo` recipe:\n{demo}"
    )


def test_b4_both_artifact_assertions_target_the_same_state_dir() -> None:
    for gate_step in ARTIFACT_ASSERTION_STEPS:
        step = _bare(_step_for_gate(gate_step))
        paths = [tok for tok in step.split() if DEMO_STATE_DIR in tok]
        assert paths, (
            f"artifact-assertion step {step!r} references no path under "
            f"{DEMO_STATE_DIR!r}, so wiping that dir would not make it fresh"
        )
        for path in paths:
            assert path.startswith(f"{DEMO_STATE_DIR}/"), (
                f"artifact-assertion path {path!r} must live directly under "
                f"{DEMO_STATE_DIR!r} (the dir the pre-step removes); if the "
                "state dir is renamed in one place only, this test fails"
            )


# ==========================================================================
# Behavior 5 --- `clean` still removes the same state dir and is not narrowed.
# ==========================================================================


def test_b5_clean_still_removes_the_demo_state_dir() -> None:
    steps = _recipe_steps("clean")
    assert steps, "`clean` must still have a non-empty recipe"
    removed: set[str] = set()
    for step in steps:
        tokens = _bare(step).split()
        if tokens and tokens[0] == "rm":
            removed.update(t for t in tokens[1:] if not t.startswith("-"))
    assert DEMO_STATE_DIR in removed, (
        f"`clean` must still remove {DEMO_STATE_DIR!r} so the new `check` "
        f"pre-step stays a strict SUBSET of `clean` and the two cannot diverge; "
        f"`clean` removes {sorted(removed)}"
    )
    assert removed - {DEMO_STATE_DIR} or len(steps) > 1, (
        "`clean` must keep its other removals -- this iteration adds a pre-step "
        f"to `check`, it does not narrow `clean`; `clean` steps were {steps}"
    )


# ==========================================================================
# Behavior 6 --- CI is unchanged and remains the graded reference.
# ==========================================================================


def test_b6_ci_still_exposes_exactly_the_expected_graded_run_steps() -> None:
    assert WORKFLOW.is_file(), (
        f"missing {WORKFLOW.relative_to(REPO)} --- the CI gate the recipe mirrors"
    )
    text = WORKFLOW.read_text(encoding="utf-8")
    run_steps = re.findall(r"^\s*run:", text, re.MULTILINE)
    assert len(run_steps) == EXPECTED_CI_RUN_STEPS, (
        f"ci.yml must still expose exactly {EXPECTED_CI_RUN_STEPS} graded `run:` "
        f"steps; found {len(run_steps)}. The COUNT is the contract, not CI's "
        "immutability: a CI run-step may be added, but only together with the "
        "matching `check` recipe step and this constant, or the local gate and "
        "the graded gate have silently diverged."
    )


def test_b6_ci_still_contains_every_gate_step() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    for gate_step in CI_GATE_STEPS:
        assert gate_step in text, (
            f"gate step {gate_step!r} is not a command CI actually runs (absent "
            f"from {WORKFLOW.relative_to(REPO)}); the local gate must never "
            "claim a step CI does not run"
        )


def test_b6_ci_has_no_freshness_pre_step() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert FRESHNESS_PRE_STEP not in text, (
        f"ci.yml must NOT contain {FRESHNESS_PRE_STEP!r}: every CI run is a fresh "
        "checkout, so a pre-step there is noise. The pre-step exists to give the "
        "LOCAL gate the freshness CI gets for free."
    )


def test_b6_local_gate_is_a_single_step_superset_of_ci() -> None:
    local = {_bare(step) for step in _recipe_steps("check")}
    extra = local - set(CI_GATE_STEPS)
    assert extra == {FRESHNESS_PRE_STEP}, (
        "the local `check` gate must be CI's gate plus EXACTLY the one named "
        f"freshness pre-step; extra local steps were {sorted(extra)}"
    )
    missing = set(CI_GATE_STEPS) - local
    assert not missing, f"local gate is missing CI steps {sorted(missing)}"


# ==========================================================================
# Behavior 7 --- additive edit: nothing pre-existing removed, no new tool or
# dependency.
# ==========================================================================


def test_b7_preexisting_targets_still_declared_and_nonempty() -> None:
    tokens = _phony_tokens()
    for target in PREEXISTING_TARGETS:
        assert target in tokens, (
            f"pre-existing .PHONY token {target!r} must remain (nothing "
            f"removed); found {sorted(tokens)}"
        )
        assert _make_recipe(target), (
            f"pre-existing target {target!r} must still have a non-empty recipe"
        )


def test_b7_check_recipe_introduces_no_new_tool() -> None:
    offenders = []
    for step in _recipe_steps("check"):
        command = _bare(step).split()[0]
        if command not in ALLOWED_CHECK_COMMANDS:
            offenders.append((command, step))
    assert not offenders, (
        f"the `check` recipe must stay pure shell + `$(MAKE)` + `uv` "
        f"({sorted(ALLOWED_CHECK_COMMANDS)}); new tools found: {offenders}"
    )


def test_b7_no_new_runtime_dependency() -> None:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    deps = data["project"]["dependencies"]
    assert len(deps) == 1 and deps[0].lower().startswith("pydantic"), (
        "the runtime dependency set must stay pydantic-v2-ONLY (this iteration "
        f"is build tooling: no dependency change, so no lockfile churn); found {deps}"
    )


# ==========================================================================
# Behavior 8 --- two-sided EXECUTABLE proof: the known-bad sample must FIRE.
#
# The only test in this file that shells out. It runs the recipe's OWN text (no
# re-typed copies) for the three cheap steps only, inside tmp_path, never the
# repo. Safety rails are asserted, not assumed.
# ==========================================================================


def _run_step(step: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        step,
        shell=True,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=15,
    )


def test_b8_fail_open_is_real_and_the_pre_step_closes_it(tmp_path: Path) -> None:
    pre_step = _recipe_steps("check")[0]
    artifact_steps = [_step_for_gate(gate) for gate in ARTIFACT_ASSERTION_STEPS]

    # ---- safety rails, asserted BEFORE anything executes ----
    executed = [pre_step, *artifact_steps]
    assert len(executed) == 3, f"exactly 3 steps may execute; got {executed}"
    assert {_bare(s) for s in executed} == {
        FRESHNESS_PRE_STEP,
        *ARTIFACT_ASSERTION_STEPS,
    }, f"the executed subset must be exactly the 3 cheap steps; got {executed}"
    for forbidden in ("uv ", "make ", "pytest", "mypy", "sync"):
        for step in executed:
            assert forbidden not in step, (
                f"step {step!r} would execute {forbidden!r} -- the install / "
                "pytest / mypy / `make demo` gate steps must NEVER run inside "
                "the suite (nested run would strand the tester stage)"
            )
    cwd = tmp_path.resolve()
    assert cwd != REPO.resolve(), f"refusing to execute in the repo itself ({cwd})"
    assert not REPO.resolve().is_relative_to(cwd), (
        f"tmp_path {cwd} contains the repo -- a relative `rm -rf` would not be isolated"
    )
    repo_state_dir = REPO / DEMO_STATE_DIR
    repo_state_dir_existed = repo_state_dir.exists()

    # ---- synthesize a STALE artifact tree (the known-bad sample) ----
    stale = cwd / DEMO_STATE_DIR
    (stale / "run-deadbeef" / "artifacts").mkdir(parents=True)
    (stale / "slate.json").write_text("{}", encoding="utf-8")
    (stale / "run-deadbeef" / "artifacts" / "plan.md").write_text("# stale", encoding="utf-8")

    try:
        # ---- Direction A: the defect is REAL (no pre-step -> both pass) ----
        for step in artifact_steps:
            result = _run_step(step, cwd)
            assert result.returncode == 0, (
                f"KNOWN-BAD SAMPLE DID NOT FIRE: artifact assertion {step!r} "
                f"exited {result.returncode} against a STALE tree, so this "
                "iteration's premise (the assertions are fail-OPEN existence "
                f"checks) is unproven. stdout={result.stdout!r} "
                f"stderr={result.stderr!r}"
            )

        # ---- Direction B: the fix WORKS (pre-step -> both fail) ----
        wipe = _run_step(pre_step, cwd)
        assert wipe.returncode == 0, (
            f"pre-step {pre_step!r} must exit 0; got {wipe.returncode} "
            f"(stderr={wipe.stderr!r})"
        )
        assert not stale.exists(), (
            f"pre-step {pre_step!r} did not remove {stale} -- the gate would "
            "still be judging stale artifacts"
        )
        for step in artifact_steps:
            result = _run_step(step, cwd)
            assert result.returncode != 0, (
                f"artifact assertion {step!r} still exited 0 AFTER the freshness "
                "pre-step wiped the state dir: a demo that produced nothing "
                f"would still pass the gate. stdout={result.stdout!r}"
            )
    finally:
        # ---- safety rail: the relative `rm -rf` must not have touched the repo ----
        if repo_state_dir_existed:
            assert repo_state_dir.exists(), (
                f"{repo_state_dir} was removed by this test -- the relative "
                "pre-step escaped tmp_path"
            )


def test_b8_never_executes_an_expensive_gate_step() -> None:
    """Standing constraint (spec Out of Scope): the suite must never run the
    install / pytest / mypy / `make demo` steps. Asserted over the whole declared
    gate, not just the steps behavior 8 happens to pick."""
    expensive = [s for s in CI_GATE_STEPS if s not in ARTIFACT_ASSERTION_STEPS]
    assert expensive == [
        "uv sync --locked",
        "uv run pytest",
        "uv run mypy src/proactive_loop",
        "make demo",
        "uv run pla signals --workspace . --fail-on-kind merge_conflict "
        "--fail-on-kind syntax_error --fail-on-kind secret_file "
        "--fail-on-kind broken_link",
    ], expensive
    source = Path(__file__).read_text(encoding="utf-8")
    for step in expensive:
        assert f"_run_step({step!r}" not in source, (
            f"this file must never shell out to the expensive gate step {step!r}"
        )
