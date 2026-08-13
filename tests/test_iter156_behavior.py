"""Black-box behavior tests for state-dir iteration 150 (ships as commit-seq
**factory iter 156**): a new ``make check-matrix`` target that runs the SUITE once per
CI matrix interpreter, each in its own throwaway project environment; the honest
correction of the ``check`` comment's false claim of equivalence with a passing CI
build; and a two-sided drift guard pinning the target's leg set to ``ci.yml``'s
``strategy.matrix.python-version`` (ROADMAP #181).

Feature under test (``pm.md``): CI's ``test`` job is a ``fail-fast: false`` matrix over
two interpreters, so it grades its six run-steps TWICE -- twelve run-steps -- while
``make check`` runs them ONCE, under whichever interpreter ``uv`` last left in
``.venv``. There is no ``.python-version`` in the repo, so which leg runs locally is an
accident rather than a choice, and the gap already cost a reverted iteration (a failure
reproducible only on the newer interpreter reached CI unseen). ``check-matrix`` closes
the leg-varying half -- the suite -- and the drift guard below makes the duplicated leg
list safe: adding a leg to CI alone, or to the Makefile alone, goes RED.

ISOLATION CONTRACT (honored): every assertion here is written from THIS iteration's
spec (``pm.md`` Expected Behaviors 1-8) and drives ONLY the public build artifacts the
spec designates as this iteration's black-box surfaces -- the parsed TEXT of
``Makefile``, ``.github/workflows/ci.yml`` and ``.gitignore``, plus ``pyproject.toml``
for the no-new-dependency half of behavior 2. **No file under ``src/`` was read, no
engineer or reviewer note was read, and no ``git diff`` was consulted.** The
spec-declared ground facts (the pre-existing ``.PHONY`` tokens, today's leg set, the
forbidden environment values, the two stale-docstring filenames) are encoded below as
the CONTRACT's constants, NOT imported from any implementation, so a silent drift in
either direction goes RED.

Cap-safety / offline: pure file reads, ``re`` parsing and ``fnmatch``. This module runs
NO subprocess, NO interpreter, NO ``make``, NO ``uv``, and never executes the matrix it
describes -- deliberately, since a nested 3.13 suite run would both blow the suite's
wall-clock budget and require an interpreter a stranger's machine may not have. Both
properties are self-policed by ``test_module_is_self_contained_and_yaml_free`` below.
"""

from __future__ import annotations

import re
import tomllib
from fnmatch import fnmatch
from pathlib import Path

# ---------------------------------------------------------------------------
# Tester's ground facts -- the spec-declared contract constants (pm.md).
# ---------------------------------------------------------------------------

REPO = Path(__file__).resolve().parents[1]
MAKEFILE = REPO / "Makefile"
WORKFLOW = REPO / ".github" / "workflows" / "ci.yml"
GITIGNORE = REPO / ".gitignore"
PYPROJECT = REPO / "pyproject.toml"

# THIS iteration's new target.
MATRIX_TARGET = "check-matrix"

# The seven targets that existed before it -- the edit must be purely additive.
PRE_EXISTING_PHONY = ("setup", "test", "cov", "typecheck", "demo", "clean", "check")

# Today's CI matrix (asserted on BOTH sides, and against this literal, so a
# one-sided change is red even if both sides were edited to agree on something else
# than what the spec approved).
EXPECTED_LEGS = frozenset({"3.12", "3.13"})

# A leg must never point uv at the shared default environment.
FORBIDDEN_ENV_VALUES = frozenset({".venv", ".venv/", "./.venv", "./.venv/"})

# The two modules that quoted the false claim in their docstrings (a bounded
# census named by the spec, not a tree walk).
STALE_CLAIM_FILES = ("test_iter102_behavior.py", "test_iter110_behavior.py")

# The equivalence needle is BUILT BY CONCATENATION at runtime so that this test
# module never itself contains the claim it forbids (per spec behavior 6a).
_GREEN_CI = "green" + " CI"
_CLAIM_NEEDLES = ("==" + " a " + _GREEN_CI, "equals" + " a " + _GREEN_CI)
_CLAIM_RE = re.compile(
    r"(==|=|equals|equivalent to)\s*(the\s+)?a?\s*" + _GREEN_CI, re.IGNORECASE
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Text-only parsing helpers (re / fnmatch only; PyYAML is NOT a dependency).
# ---------------------------------------------------------------------------

_TARGET_LINE = re.compile(r"^(?P<name>[A-Za-z0-9_][A-Za-z0-9_.\-]*)\s*:(?!=)")


def _phony_tokens(text: str) -> tuple[str, ...]:
    tokens: list[str] = []
    for decl in re.findall(r"^\.PHONY:(.*)$", text, flags=re.MULTILINE):
        tokens.extend(decl.split())
    return tuple(tokens)


def _recipe_steps(text: str, target: str) -> tuple[str, ...]:
    """Logical (continuation-joined) recipe lines of `target`, tabs stripped."""
    lines = text.splitlines()
    start: int | None = None
    for index, line in enumerate(lines):
        match = _TARGET_LINE.match(line)
        if match is not None and match.group("name") == target:
            start = index + 1
            break
    if start is None:
        return ()
    steps: list[str] = []
    pending = ""
    for line in lines[start:]:
        if line.startswith("\t"):
            body = line[1:]
            pending = body if not pending else pending + " " + body.strip()
            if pending.rstrip().endswith("\\"):
                pending = pending.rstrip()[:-1].rstrip()
                continue
            steps.append(pending)
            pending = ""
            continue
        if line.strip() == "":
            continue  # blank lines are ignored inside a recipe
        break  # first non-tab, non-blank line ends the recipe
    if pending:
        steps.append(pending)
    return tuple(steps)


def _split_prefixes(step: str) -> tuple[str, str]:
    """Return (make prefix chars such as @ + -, remaining command text)."""
    rest = step.strip()
    prefixes = ""
    while rest and rest[0] in "@+-":
        prefixes += rest[0]
        rest = rest[1:].lstrip()
    return prefixes, rest


def _comment_block_above(text: str, target: str) -> str:
    """The contiguous run of `#` comment lines immediately above `target:`."""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        match = _TARGET_LINE.match(line)
        if match is not None and match.group("name") == target:
            block: list[str] = []
            cursor = index - 1
            while cursor >= 0 and lines[cursor].lstrip().startswith("#"):
                block.append(lines[cursor])
                cursor -= 1
            return "\n".join(reversed(block))
    return ""


def _legs_from_makefile(text: str, target: str = MATRIX_TARGET) -> frozenset[str]:
    joined = "\n".join(_recipe_steps(text, target))
    return frozenset(re.findall(r"--python[=\s]+(\d+\.\d+)", joined))


def _legs_from_ci(text: str) -> frozenset[str]:
    legs: set[str] = set()
    for listing in re.findall(r"python-version:\s*\[([^\]]*)\]", text):
        for item in listing.split(","):
            cleaned = item.strip().strip("\"'").strip()
            if cleaned:
                legs.add(cleaned)
    return frozenset(legs)


def _leg_drift(
    makefile_text: str, ci_text: str
) -> tuple[frozenset[str], frozenset[str]] | None:
    """None when the two leg sets agree, else (makefile_legs, ci_legs)."""
    makefile_legs = _legs_from_makefile(makefile_text)
    ci_legs = _legs_from_ci(ci_text)
    if makefile_legs == ci_legs:
        return None
    return (makefile_legs, ci_legs)


def _gitignore_patterns(text: str) -> tuple[str, ...]:
    patterns: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("!"):
            continue
        patterns.append(line.lstrip("/").rstrip("/"))
    return tuple(patterns)


def _normalise_dir(value: str) -> str:
    """Drop a leading `./` and a trailing `/` without touching the leading dot."""
    cleaned = value.rstrip("/")
    while cleaned.startswith("./"):
        cleaned = cleaned[2:]
    return cleaned


def _leg_env_values(text: str) -> tuple[str, ...]:
    joined = "\n".join(_recipe_steps(text, MATRIX_TARGET))
    return tuple(re.findall(r"UV_PROJECT_ENVIRONMENT=(\S+)", joined))


# ---------------------------------------------------------------------------
# Behavior 1 -- the target exists, is declared, and the edit is additive.
# ---------------------------------------------------------------------------


def test_b1_check_matrix_is_declared_phony_with_a_non_empty_recipe() -> None:
    text = _read(MAKEFILE)
    tokens = _phony_tokens(text)
    assert MATRIX_TARGET in tokens, (
        f"{MATRIX_TARGET!r} must be declared .PHONY; got {tokens!r}"
    )
    steps = _recipe_steps(text, MATRIX_TARGET)
    assert steps, f"{MATRIX_TARGET} must have a non-empty recipe"


def test_b1_pre_existing_phony_targets_all_survive() -> None:
    text = _read(MAKEFILE)
    tokens = _phony_tokens(text)
    missing = [name for name in PRE_EXISTING_PHONY if name not in tokens]
    assert not missing, f"the .PHONY edit must be additive; lost {missing!r}"
    for name in PRE_EXISTING_PHONY:
        assert _recipe_steps(text, name), f"pre-existing target {name} lost its recipe"


# ---------------------------------------------------------------------------
# Behavior 2 -- leg set == CI matrix, derived from BOTH sides.
# ---------------------------------------------------------------------------


def test_b2_recipe_leg_set_equals_ci_matrix_python_versions() -> None:
    drift = _leg_drift(_read(MAKEFILE), _read(WORKFLOW))
    assert drift is None, (
        "check-matrix legs and ci.yml strategy.matrix.python-version diverged: "
        f"makefile={sorted(drift[0])} ci={sorted(drift[1])}"
        if drift
        else ""
    )


def test_b2_both_sides_are_todays_two_approved_legs() -> None:
    assert _legs_from_makefile(_read(MAKEFILE)) == EXPECTED_LEGS
    assert _legs_from_ci(_read(WORKFLOW)) == EXPECTED_LEGS


def test_b2_parsing_needs_no_yaml_dependency() -> None:
    data = tomllib.loads(_read(PYPROJECT))
    declared: list[str] = list(data["project"].get("dependencies", []))
    for group in data.get("dependency-groups", {}).values():
        declared.extend(item for item in group if isinstance(item, str))
    offenders = [item for item in declared if "yaml" in item.lower()]
    assert not offenders, f"ci.yml parsing must stay re-only; found {offenders!r}"
    assert data["project"]["dependencies"] == ["pydantic>=2.7"], (
        "the runtime dependency set must stay pydantic-only"
    )


# ---------------------------------------------------------------------------
# Behavior 3 -- the drift guard is two-sided (a guard that never fired is not
# evidence). Same comparison helper, synthetic text on both sides.
# ---------------------------------------------------------------------------

_SYNTHETIC_CI_TWO_LEGS = (
    "jobs:\n"
    "  test:\n"
    "    strategy:\n"
    "      fail-fast: false\n"
    "      matrix:\n"
    '        python-version: ["3.12", "3.13"]\n'
)
_SYNTHETIC_MAKEFILE_TWO_LEGS = (
    "check-matrix:\n"
    "\tUV_PROJECT_ENVIRONMENT=.venv-py312 uv run --offline --locked"
    " --python 3.12 pytest\n"
    "\tUV_PROJECT_ENVIRONMENT=.venv-py313 uv run --offline --locked"
    " --python 3.13 pytest\n"
)
_SYNTHETIC_MAKEFILE_ONE_LEG = (
    "check-matrix:\n"
    "\tUV_PROJECT_ENVIRONMENT=.venv-py312 uv run --offline --locked"
    " --python 3.12 pytest\n"
)


def test_b3_drift_helper_reports_no_mismatch_on_matching_text() -> None:
    assert _leg_drift(_SYNTHETIC_MAKEFILE_TWO_LEGS, _SYNTHETIC_CI_TWO_LEGS) is None


def test_b3_drift_helper_reports_a_mismatch_when_a_leg_is_missing() -> None:
    drift = _leg_drift(_SYNTHETIC_MAKEFILE_ONE_LEG, _SYNTHETIC_CI_TWO_LEGS)
    assert drift == (frozenset({"3.12"}), frozenset({"3.12", "3.13"}))


def test_b3_drift_helper_fires_in_the_other_direction_too() -> None:
    ci_one_leg = _SYNTHETIC_CI_TWO_LEGS.replace('["3.12", "3.13"]', '["3.12"]')
    drift = _leg_drift(_SYNTHETIC_MAKEFILE_TWO_LEGS, ci_one_leg)
    assert drift == (frozenset({"3.12", "3.13"}), frozenset({"3.12"}))


# ---------------------------------------------------------------------------
# Behavior 4 -- no leg may mutate the shared default environment.
# ---------------------------------------------------------------------------


def test_b4_every_leg_carries_its_own_project_environment() -> None:
    text = _read(MAKEFILE)
    steps = [
        step for step in _recipe_steps(text, MATRIX_TARGET) if "--python" in step
    ]
    assert steps, "expected at least one --python-bearing leg step"
    for step in steps:
        assert "UV_PROJECT_ENVIRONMENT=" in step, (
            "a leg that names --python must set UV_PROJECT_ENVIRONMENT on the SAME "
            f"step, else it mutates the shared .venv: {step!r}"
        )


def test_b4_no_leg_points_at_the_shared_default_venv() -> None:
    values = _leg_env_values(_read(MAKEFILE))
    assert len(values) >= 2, f"expected one env per leg; got {values!r}"
    assert len(set(values)) == len(values), f"legs must not share an env: {values!r}"
    for value in values:
        assert value not in FORBIDDEN_ENV_VALUES, (
            f"leg environment {value!r} is the shared default venv"
        )


# ---------------------------------------------------------------------------
# Behavior 5 -- each leg runs the suite offline, and no leg ignores errors.
# ---------------------------------------------------------------------------


def test_b5_every_leg_is_offline_and_invokes_pytest() -> None:
    steps = [
        step
        for step in _recipe_steps(_read(MAKEFILE), MATRIX_TARGET)
        if "--python" in step
    ]
    assert steps
    for step in steps:
        assert "--offline" in step, f"leg may not reach the network: {step!r}"
        assert "pytest" in step, f"leg must run the suite: {step!r}"


def test_b5_no_matrix_recipe_line_ignores_errors() -> None:
    for step in _recipe_steps(_read(MAKEFILE), MATRIX_TARGET):
        prefixes, rest = _split_prefixes(step)
        assert "-" not in prefixes, (
            "a `-` ignore-errors prefix would make the matrix gate fail-open: "
            f"{step!r} (command part {rest!r})"
        )


# ---------------------------------------------------------------------------
# Behavior 6 -- the false CI-equivalence claim is gone and named honestly.
# ---------------------------------------------------------------------------


def test_b6a_makefile_no_longer_claims_its_local_gate_equals_ci() -> None:
    text = _read(MAKEFILE)
    for needle in _CLAIM_NEEDLES:
        assert needle not in text, f"Makefile still asserts {needle!r}"
    match = _CLAIM_RE.search(text)
    assert match is None, (
        f"Makefile still asserts an equivalence with CI: {match.group(0)!r}"
        if match
        else ""
    )


def test_b6b_check_comment_block_names_the_matrix_target() -> None:
    block = _comment_block_above(_read(MAKEFILE), "check")
    assert block, "the `check` target must keep its explanatory comment block"
    assert MATRIX_TARGET in block, (
        "`check`'s comment must name check-matrix as the target covering the rest "
        "of the graded matrix"
    )


def test_b6_check_recipe_itself_is_unchanged_by_this_iteration() -> None:
    steps = _recipe_steps(_read(MAKEFILE), "check")
    assert steps[0] == "rm -rf .pla_runs"
    joined = "\n".join(steps)
    assert "--python" not in joined, (
        "check must stay the fast single-leg gate; the matrix belongs in "
        f"{MATRIX_TARGET}: {joined!r}"
    )
    assert "UV_PROJECT_ENVIRONMENT" not in joined


# ---------------------------------------------------------------------------
# Behavior 7 -- the two stale docstring copies of the claim are corrected.
# ---------------------------------------------------------------------------


def test_b7_named_test_modules_no_longer_assert_the_equivalence() -> None:
    for name in STALE_CLAIM_FILES:
        path = REPO / "tests" / name
        assert path.is_file(), f"census file missing: {path}"
        text = _read(path)
        for needle in _CLAIM_NEEDLES:
            assert needle not in text, f"{name} still quotes {needle!r}"
        match = _CLAIM_RE.search(text)
        assert match is None, (
            f"{name} still asserts an equivalence with CI: {match.group(0)!r}"
            if match
            else ""
        )


# ---------------------------------------------------------------------------
# Behavior 8 -- per-leg environments are gitignored and cleaned.
# ---------------------------------------------------------------------------


def test_b8_every_leg_environment_is_gitignored() -> None:
    values = _leg_env_values(_read(MAKEFILE))
    patterns = _gitignore_patterns(_read(GITIGNORE))
    assert values
    for value in values:
        target = _normalise_dir(value)
        assert any(fnmatch(target, pattern) for pattern in patterns), (
            f"leg environment {value!r} is not matched by any .gitignore pattern "
            f"({patterns!r}) -- it would show up in `git status`"
        )


def test_b8_make_clean_removes_every_leg_environment() -> None:
    text = _read(MAKEFILE)
    values = _leg_env_values(text)
    clean_tokens = [
        token for step in _recipe_steps(text, "clean") for token in step.split()
    ]
    assert values
    for value in values:
        target = _normalise_dir(value)
        assert any(fnmatch(target, token) for token in clean_tokens), (
            f"`make clean` does not remove leg environment {value!r}; "
            f"clean tokens were {clean_tokens!r}"
        )


# ---------------------------------------------------------------------------
# Self-policing: this module stays text-only, offline and yaml-free.
# ---------------------------------------------------------------------------


def test_module_is_self_contained_and_yaml_free() -> None:
    own_source = Path(__file__).read_text(encoding="utf-8")
    for banned in ("import" + " subprocess", "import" + " yaml", "subprocess" + ".run("):
        assert banned not in own_source, (
            f"this drift guard must never {banned!r}: it may not execute the "
            "matrix it describes (a nested 3.13 suite run is neither cap-safe nor "
            "portable)"
        )
