"""Black-box behavior tests for iteration 95 (factory iter 102) --- add a
``make check`` aggregate target that reproduces the EXACT CI graded gate locally
in one command, paired with a text-only drift-guard that keeps the target in
lockstep with ``.github/workflows/ci.yml`` (ROADMAP #102).

Feature under test (``pm.md``): CI (``.github/workflows/ci.yml``) grades a real
gate on every push to a PUBLIC portfolio repo --- locked install, the test
suite, the mypy type oracle, the offline end-to-end demo, and two demo-artifact
assertions. Before this iteration there was NO single local command that
reproduced that graded gate, and the two demo-artifact assertions
(``test -f .pla_runs/slate.json`` / ``ls .pla_runs/run-*/artifacts/*.md``) lived
ONLY inside ``ci.yml`` (nowhere runnable locally), so they could silently rot.
The new ``.PHONY`` ``check`` target runs those graded steps in CI's own
order, so ONE local command reproduces ONE leg of what CI grades (the original
wording here claimed the target equalled the whole CI build; factory iter 156
corrected that -- CI runs these seven steps under both matrix interpreters, and
``make check-matrix`` covers the second leg's SUITE). This drift-guard
makes the unavoidable CI-logic duplication SAFE: if the ``check`` recipe and ``ci.yml``
diverge, the suite goes RED. This is build-tooling ONLY: no ``src/`` runtime
change, no ``SPEC.md`` / ``README.md`` / ``pyproject.toml`` / ``uv.lock`` change,
no dependency change, no new CLI verb / tool / collector / provider, and no
count cascade (this touches none of the three carved-out README numbers).

ISOLATION CONTRACT (honored): these tests are written strictly against THIS
iteration's public contract --- the spec's Expected Behaviors (``pm.md``) and the
public build artifacts ``Makefile`` and ``.github/workflows/ci.yml`` --- and
drive ONLY the documented public surface (the parsed text of those two files:
the ``.PHONY`` line, the tab-indented recipe lines of each named target, and the
graded ``run:`` steps of the workflow). **No file under ``src/`` was read, no
engineer/reviewer notes were read, and no ``git diff`` was consulted.** The
spec-declared strings (the CI gate commands, the six pre-existing target
names) are encoded here as the CONTRACT's ground facts, NOT imported from any
implementation, so the suite would go RED on a silent drift. Every test is fully
offline and cap-safe: pure file reads and text parsing, zero network, and --- by
construction --- this drift-guard NEVER executes the gate it describes (no
nested test run, no wheel build, no shell-out, no ``make``/``uv`` invocation).
"""

from __future__ import annotations

import re
from pathlib import Path

# --------------------------------------------------------------------------
# Tester's ground facts --- the spec-declared contract constants (pm.md).
# Encoded here as constants (NOT imported from the implementation) so these
# tests encode the CONTRACT and would catch a silent drift.
# --------------------------------------------------------------------------

REPO = Path(__file__).resolve().parents[1]
MAKEFILE = REPO / "Makefile"
WORKFLOW = REPO / ".github" / "workflows" / "ci.yml"

# The ordered tuple of the nine commands that make up the CI graded gate. The
# `check` recipe must reproduce these, in this order; each must also be a real
# CI step. `make demo` is written `$(MAKE) demo` in the recipe (normalized
# below); the two demo-artifact assertions live in ci.yml's single `run: |`
# block. NOTE: the artifact-list step is matched WITHOUT its `> /dev/null`
# redirect suffix so the substring test is redirect-insensitive.
#
# The LAST step (added factory iter 128) is the product dogfooding its own
# enforcement mode: an armed `pla signals --fail-on-kind` self-scan whose kinds
# are the STATE-INDEPENDENT, must-never-appear subset, so it can only go red on
# a broken checkout -- never on a developer's work in progress.
CI_GATE_STEPS = (
    "uv sync --locked",
    "uv run pytest",
    "uv run mypy src/proactive_loop",
    "make demo",
    "test -f .pla_runs/slate.json",
    "ls .pla_runs/run-*/artifacts/*.md",
    # The 8th step (added factory iter 186) reads what the demo PUBLISHED
    # rather than merely asserting it exists: `verify --fail-on-unresolved`
    # resolves every goal's cited `sources` against the snapshot the SAME
    # `pla run` wrote, so a fabricated citation in the published slate is a red
    # build. ONE entry, written as two implicitly-concatenated fragments to stay
    # inside the line budget -- count ENTRIES here, never lines.
    "uv run pla verify --slate .pla_runs/slate.json "
    "--snapshot .pla_runs/snapshot.json --fail-on-unresolved",
    # The 9th step (added factory iter 254) is the COUNT BUDGET, the third
    # ratchet, and the first consumer `--fail-over N` has ever had. It budgets the
    # four kinds `--fail-on-kind` structurally cannot arm (all non-zero here, so
    # arming them by kind is red on arrival) over an UPSTREAM `--collector`
    # selection that is state-independent: a whole-census budget would also count
    # `working_tree` (75 signals clean, 76 with one uncommitted edit) and so be red
    # for every developer mid-edit while CI stayed green. ONE entry, written as
    # fragments to stay inside the line budget -- count ENTRIES here, never lines.
    "uv run pla signals --workspace . --collector notes --collector ci_config "
    "--collector dependencies --collector test_posture --fail-over 9",
    "uv run pla signals --workspace . --fail-on-kind merge_conflict "
    "--fail-on-kind syntax_error --fail-on-kind secret_file "
    "--fail-on-kind broken_link",
)

# The number of graded `run:` steps ci.yml exposes today: locked install,
# pytest, mypy, `make demo`, the single `run: |` block holding the two
# demo-artifact assertions, the armed source-citation verification, and the armed
# signal count budget, and the armed signals self-scan. If a CI run-step is
# added/removed, behavior 4 fails, forcing CI_GATE_STEPS + the `check` recipe to
# be updated together. NOTE the count is 8 while CI_GATE_STEPS holds 9: the two
# demo-artifact assertions share one `run: |` block, so they are one graded step
# and two gate commands.
EXPECTED_CI_RUN_STEPS = 8

# Every pre-existing .PHONY target that must survive this additive edit
# (behavior 5): each must remain declared in .PHONY AND keep a non-empty recipe.
PREEXISTING_TARGETS = ("setup", "test", "cov", "typecheck", "demo", "clean")


# --------------------------------------------------------------------------
# Helpers --- reused VERBATIM from the iter97/iter100 Makefile-reading pattern
# (tests/test_iter97_behavior.py / tests/test_iter100_behavior.py:
# _makefile_lines / _phony_tokens / _make_recipe).
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
    """The tab-indented recipe lines of a Makefile ``target:`` (each stripped).

    Blank lines inside a recipe are tolerated (skipped); the recipe ends at the
    first non-tab-indented, non-blank line after the target header.
    """
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


def _normalized_check_recipe() -> str:
    """The ``check`` recipe as one normalized string: ``$(MAKE)`` -> ``make`` and
    runs of whitespace (incl. newlines) collapsed to a single space, so a
    multi-line recipe can be matched with plain substring / subsequence logic."""
    text = "\n".join(_make_recipe("check")).replace("$(MAKE)", "make")
    return re.sub(r"\s+", " ", text).strip()


# ==========================================================================
# Behavior 1 --- `check` target exists and is phony.
# ==========================================================================


def test_b1_check_target_is_phony():
    tokens = _phony_tokens()
    assert "check" in tokens, (
        f"Makefile .PHONY must declare 'check'; found tokens {sorted(tokens)}"
    )


def test_b1_check_target_has_nonempty_recipe():
    recipe = _make_recipe("check")
    assert recipe, "Makefile must define a `check:` target with a non-empty recipe"


# ==========================================================================
# Behavior 2 --- the `check` recipe reproduces the CI gate, in order.
# ==========================================================================


def test_b2_check_recipe_contains_every_ci_gate_step():
    norm = _normalized_check_recipe()
    for step in CI_GATE_STEPS:
        assert step in norm, (
            f"the `check` recipe must reproduce the CI gate step {step!r}; "
            f"normalized recipe was:\n{norm}"
        )


def test_b2_check_recipe_runs_gate_steps_in_ci_order():
    norm = _normalized_check_recipe()
    prev = -1
    for step in CI_GATE_STEPS:
        pos = norm.find(step)
        assert pos >= 0, (
            f"missing gate step {step!r} in normalized `check` recipe:\n{norm}"
        )
        assert pos >= prev, (
            f"gate step {step!r} (at {pos}) appears BEFORE the previous step "
            f"(at {prev}); the `check` recipe must run the CI gate in CI's own "
            f"order: {list(CI_GATE_STEPS)}. Normalized recipe:\n{norm}"
        )
        prev = pos


# ==========================================================================
# Behavior 3 --- every reproduced gate step is a real CI step (check -> CI).
# ==========================================================================


def test_b3_every_gate_step_is_a_real_ci_step():
    assert WORKFLOW.is_file(), (
        f"missing {WORKFLOW.relative_to(REPO)} --- the CI gate the recipe mirrors"
    )
    text = WORKFLOW.read_text(encoding="utf-8")
    for step in CI_GATE_STEPS:
        assert step in text, (
            f"`make check` step {step!r} is not a command CI actually runs "
            f"(not found in {WORKFLOW.relative_to(REPO)}); the local gate must "
            "never claim a step CI does not run"
        )


# ==========================================================================
# Behavior 4 --- CI has no graded run-step the recipe omits (CI -> check).
# ==========================================================================


def test_b4_ci_has_exactly_expected_graded_run_steps():
    text = WORKFLOW.read_text(encoding="utf-8")
    run_steps = re.findall(r"^\s*run:", text, re.MULTILINE)
    assert len(run_steps) == EXPECTED_CI_RUN_STEPS, (
        f"ci.yml must expose exactly {EXPECTED_CI_RUN_STEPS} graded `run:` steps "
        f"(locked install, pytest, mypy, `make demo`, and the demo-artifact "
        f"block); found {len(run_steps)}. If a CI run-step was added or removed, "
        "update CI_GATE_STEPS and the `check` recipe together so the local gate "
        "stays in lockstep with CI."
    )


# ==========================================================================
# Behavior 5 --- additive Makefile edit; nothing pre-existing removed.
# ==========================================================================


def test_b5_preexisting_targets_still_declared_phony():
    tokens = _phony_tokens()
    for target in PREEXISTING_TARGETS:
        assert target in tokens, (
            f"pre-existing .PHONY token {target!r} must remain (nothing removed); "
            f"found tokens {sorted(tokens)}"
        )


def test_b5_preexisting_targets_still_have_a_recipe():
    for target in PREEXISTING_TARGETS:
        recipe = _make_recipe(target)
        assert recipe, (
            f"pre-existing Makefile target {target!r} must still be defined with "
            "a non-empty recipe (this edit is additive: nothing removed/emptied)"
        )


# ==========================================================================
# Behavior 6 --- the drift-guard is pure text parsing (cap-safe by construction).
#
# The "full quality-check suite passes" half of behavior 6 is verified by the
# tester RUNNING `uv run pytest` once (its duty), NOT by nesting a suite run
# here. This test instead pins the design constraint that makes that safe: the
# drift-guard must never import a process-launching or network module, so it can
# never execute the gate it describes (no nested pytest, no wheel build, no
# shell-out) and never touches the network. Scanning ONLY import lines is
# deliberate: the CI gate COMMANDS legitimately appear as string CONSTANTS in
# this file (data), so a naive source-wide grep for those tokens would false-
# positive on its own data --- an import scan cannot.
# ==========================================================================


def test_b6_drift_guard_imports_no_process_or_network_module():
    src = Path(__file__).read_text(encoding="utf-8")
    import_lines = [
        ln for ln in src.splitlines() if re.match(r"^\s*(import|from)\s", ln)
    ]
    joined = "\n".join(import_lines)
    banned = ("subprocess", "socket", "urllib", "requests", "httpx", "http.client")
    offenders = [mod for mod in banned if mod in joined]
    assert not offenders, (
        "the drift-guard must be pure text parsing (cap-safe, offline): it must "
        f"not import {offenders!r}. It must never run the gate it describes "
        "(no nested pytest, no wheel build, no shell-out) or touch the network. "
        f"import lines were:\n{joined}"
    )
