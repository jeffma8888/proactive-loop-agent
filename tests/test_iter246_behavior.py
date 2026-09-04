"""Black-box behavior tests for factory iteration 276 --- the mypy type oracle is
WIDENED so it grades the two shipped, EXECUTED ``examples/`` consumer scripts in
addition to ``src/proactive_loop``.

MODULE NAME, derived from the repo and never from the state-dir counter. This is
state-dir iteration 276, while ``git ls-files tests`` tops out at
``test_iter245_behavior.py``, so the free name is ``iter246``. Proved free before
writing a byte: ``git cat-file -e HEAD:tests/test_iter246_behavior.py`` returned
``fatal: path 'tests/test_iter246_behavior.py' does not exist in 'HEAD'``.

WHAT THIS ITERATION CLAIMS (restated so this file stands alone):

* The README's human-owned intro advertises the package as fully type-hinted, and
  iterations 86-88 built the permanent oracle for that claim: ``make typecheck``
  locally plus a BYTE-IDENTICAL step in ``.github/workflows/ci.yml``. That oracle
  stopped at ``src/proactive_loop``.
* ``examples/check_run.py`` and ``examples/check_autonomy.py`` are not decoration.
  They are executed on every push by ``make demo`` / ``make check`` / CI, they
  import the package, and they are the code a stranger copies to consume
  ``pla run --json``. Under ``[tool.mypy] strict = true`` an UNANNOTATED ``def``
  is not merely ungraded, it is INVISIBLE, so those two files were the likeliest
  place for the published quality claim to quietly stop being true.
* The widening is ADDITIVE (``src/proactive_loop`` is still named) and it is
  SCOPED BY FILE, never by directory: ``examples/fixture_workspace/`` exists to be
  imperfect, so a directory-form ``mypy examples`` would red the build for no
  defect.
* It is a ONE-STRING change at every carrier that spells the command: two Makefile
  recipes, one CI step, and the four already-shipped test constants that pin the
  gate step-for-step. No new gate step, no new Makefile target -- both of those
  shapes trip pins that this module re-asserts (behaviors 3 and 4).

TWO SPEC READINGS THIS MODULE HAD TO CHOOSE (reported as PM feedback in
``tester.md``, tested here in their only satisfiable form):

1. The spec's behavior 4 says the gate-step constants "each still declare 9
   entries". MEASURED, the live tuples declare **10** entries; 9 is
   ``EXPECTED_CI_RUN_STEPS``, which is one lower BY DESIGN because the two
   demo-artifact assertions share a single ``run: |`` block. This module asserts
   both real numbers and derives neither from the other.
2. The spec's behavior 6 says the ``check`` recipe must not name any path under
   ``examples/fixture_workspace``. Taken literally that is unsatisfiable and
   always was: the 8th gate step is ``uv run pla signals --workspace
   examples/fixture_workspace --baseline ...``, shipped in iteration 264. The
   directory ban therefore scopes to the TYPE-ORACLE INVOCATION -- the only place
   where naming a directory would change what mypy grades -- and this module
   proves the scoped predicate FIRES on a synthetic directory-form command
   (``test_b6_guard_*``) so it cannot pass vacuously.

Isolation: black-box. The seams are (a) plain-text reads of the three PUBLISHED
carriers this iteration is about (``Makefile``, ``.github/workflows/ci.yml``,
``README.md``), (b) importing gate constants from modules that already ship under
``tests/``, and (c) parsing the two ``examples/`` scripts with ``ast`` to read
DECLARED SIGNATURES ONLY -- which the spec's behavior 8 requires, because the
suite may not shell out to ``uv``/``mypy``. No file under ``src/`` was opened, no
engineer or reviewer note was opened, and no ``git diff`` was run.

Offline: file reads, in-process imports, and one ``git ls-files`` subprocess. No
network, no writes outside ``tmp_path``.
"""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

import pytest

from tests.test_iter102_behavior import CI_GATE_STEPS as STEPS_102
from tests.test_iter102_behavior import EXPECTED_CI_RUN_STEPS as CI_RUN_STEPS_102
from tests.test_iter110_behavior import CI_GATE_STEPS as STEPS_110
from tests.test_iter110_behavior import EXPECTED_CI_RUN_STEPS as CI_RUN_STEPS_110
from tests.test_iter110_behavior import FRESHNESS_PRE_STEP
from tests.test_iter128_behavior import PREEXISTING_GATE_STEPS
from tests.test_iter97_behavior import TYPECHECK_CMD as NARROW_ORACLE

REPO = Path(__file__).resolve().parents[1]
MAKEFILE = REPO / "Makefile"
WORKFLOW = REPO / ".github" / "workflows" / "ci.yml"
README = REPO / "README.md"

#: The widened type-oracle command. Spelled ONCE here; every assertion derives
#: from this constant so a future re-key is a one-line edit.
WIDE = (
    "uv run mypy src/proactive_loop "
    "examples/check_run.py examples/check_autonomy.py"
)

#: The two GRADED example consumers the widening pulls into the oracle.
GRADED_EXAMPLES = ("examples/check_run.py", "examples/check_autonomy.py")

#: The example subtree that must stay OUT of the oracle: it exists to be
#: imperfect (a directory-form ``mypy examples`` reports real errors, all inside
#: it), so the oracle scopes by file.
UNGRADED_EXAMPLE_SUBTREE = "examples/fixture_workspace"

#: The number of ENTRIES each gate-step tuple declares. Higher than
#: ``EXPECTED_CI_RUN_STEPS`` by exactly one, because the two demo-artifact
#: assertions share one ``run: |`` block: one graded CI step, two gate commands.
EXPECTED_GATE_STEP_ENTRIES = 10

#: The armed self-scan that must remain the LAST gate step.
LAST_GATE_STEP_PREFIX = "uv run pla signals --workspace . --fail-on-kind"

#: Ordinal position of the type-oracle step among the gate steps, 0-based.
ORACLE_GATE_INDEX = 2

#: The human-owned README block's boundary marker.
MARKER = "PORTFOLIO INTRO"

_REDIRECT_SUFFIX = re.compile(r"\s*>\s*/dev/null(\s+2>&1)?\s*$")

#: A ``mypy`` invocation that grades a DIRECTORY under ``examples/`` rather than
#: the two named files. ``examples`` bare, or any ``examples/`` path that is not
#: one of the two graded scripts, is a violation.
_EXAMPLE_ARG = re.compile(r"(?<![\w/.-])examples(?:/[\w./-]*)?")


# ---------------------------------------------------------------------------
# Fail-closed readers. Each asserts it actually found something, so a renamed
# target or a reshaped workflow can never make a guard pass vacuously.
# ---------------------------------------------------------------------------


def _normalize(step: str) -> str:
    """A recipe line as the CI gate spells it: ``$(MAKE)`` -> ``make``, no
    ``> /dev/null`` redirect, no surrounding whitespace."""
    return _REDIRECT_SUFFIX.sub("", step.replace("$(MAKE)", "make")).strip()


def _recipe_steps(target: str) -> list[str]:
    """The normalized, tab-indented recipe lines of a Makefile ``target:``.

    Blank lines inside a recipe are tolerated; recipe comments are dropped (they
    are prose, not commands). The recipe ends at the first line that is neither
    tab-indented nor blank.
    """
    steps: list[str] = []
    seen = False
    for raw in MAKEFILE.read_text(encoding="utf-8").splitlines():
        if not seen:
            if raw.startswith(f"{target}:"):
                seen = True
            continue
        if raw.startswith("\t"):
            body = raw.strip()
            if body and not body.startswith("#"):
                steps.append(_normalize(body))
            continue
        if not raw.strip():
            continue
        break
    assert seen, (
        f"{MAKEFILE.name} must declare a `{target}:` target -- the reader found "
        f"no such line, so every assertion about it would pass vacuously"
    )
    assert steps, f"the `{target}:` recipe in {MAKEFILE.name} must be non-empty"
    return steps


def _ci_run_bodies() -> list[str]:
    """Every CI ``run:`` body, one entry per graded step.

    An inline ``run: cmd`` yields ``cmd``; a ``run: |`` block yields its
    more-indented continuation lines joined by newlines. Comment lines are kept
    OUT of the body, because a WHY comment is not a command.
    """
    bodies: list[str] = []
    lines = WORKFLOW.read_text(encoding="utf-8").splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        match = re.match(r"^(\s*)run:\s*(.*)$", line)
        if match is None:
            i += 1
            continue
        indent, inline = match.group(1), match.group(2).strip()
        i += 1
        if inline not in {"|", "|-", ">", ">-"}:
            bodies.append(inline)
            continue
        block: list[str] = []
        while i < len(lines):
            nxt = lines[i]
            if nxt.strip() and not nxt.startswith(indent + " "):
                break
            stripped = nxt.strip()
            if stripped and not stripped.startswith("#"):
                block.append(stripped)
            i += 1
        bodies.append("\n".join(block))
    assert bodies, (
        f"{WORKFLOW.name} exposes no `run:` step -- the reader is broken or the "
        f"workflow was restructured, so the CI half of every lockstep assertion "
        f"below would pass vacuously"
    )
    return bodies


def _gate_steps(target: str) -> list[str]:
    """The ``check`` recipe's steps with the freshness pre-step removed."""
    return [s for s in _recipe_steps(target) if s != FRESHNESS_PRE_STEP]


def _example_dir_args(command: str) -> list[str]:
    """Every ``examples`` path in a command that is NOT one of the two graded
    scripts -- i.e. every way the oracle could grade the wrong surface."""
    return [
        hit
        for hit in _EXAMPLE_ARG.findall(command)
        if hit not in GRADED_EXAMPLES
    ]


def _annotation_violations(path: Path) -> list[str]:
    """Reproduce the property ``strict = true`` enforces, from DECLARED
    SIGNATURES only: every ``def``/``async def`` carries a return annotation and
    annotates every parameter except ``self``/``cls``.

    Fail-closed: the caller asserts the sweep saw at least one function.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    problems: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.returns is None:
            problems.append(f"{path.name}:{node.lineno} {node.name}() -> ???")
        args = node.args
        params = [*args.posonlyargs, *args.args, *args.kwonlyargs]
        params += [a for a in (args.vararg, args.kwarg) if a is not None]
        for arg in params:
            if arg.arg in {"self", "cls"}:
                continue
            if arg.annotation is None:
                problems.append(
                    f"{path.name}:{node.lineno} {node.name}(): parameter "
                    f"{arg.arg!r} is unannotated"
                )
    return problems


def _function_count(path: Path) -> int:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return sum(
        isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        for n in ast.walk(tree)
    )


def _readme_halves() -> tuple[str, str]:
    """``(above, below)`` the human-owned marker."""
    text = README.read_text(encoding="utf-8")
    assert text.count(MARKER) == 1, (
        f"README.md must carry the {MARKER!r} marker exactly once (found "
        f"{text.count(MARKER)}); the human-owned boundary is what makes 'above' "
        f"and 'below' decidable at all"
    )
    above, below = text.split(MARKER, 1)
    return above, below


# ---------------------------------------------------------------------------
# Behavior 1 --- `make typecheck` runs exactly the widened command.
# ---------------------------------------------------------------------------


def test_b1_typecheck_recipe_is_exactly_the_widened_command() -> None:
    steps = _recipe_steps("typecheck")
    assert steps == [WIDE], (
        f"the `typecheck:` recipe must run exactly one command, {WIDE!r} -- the "
        f"local half of the type oracle. Found: {steps}"
    )


def test_b1_typecheck_recipe_no_longer_stops_at_the_package() -> None:
    """The narrow oracle must not survive as a whole step anywhere."""
    for target in ("typecheck", "check"):
        for step in _recipe_steps(target):
            if step.startswith("uv run mypy"):
                assert step == WIDE, (
                    f"the `{target}:` recipe still runs a mypy invocation that is "
                    f"not the widened oracle: {step!r}. The widening replaces the "
                    f"command; it must not leave a narrow one behind."
                )


# ---------------------------------------------------------------------------
# Behavior 2 --- the `check` gate keeps the oracle in its original position.
# ---------------------------------------------------------------------------


def test_b2_check_recipe_runs_the_widened_command() -> None:
    assert WIDE in _recipe_steps("check"), (
        f"the `check:` recipe must run {WIDE!r}; found "
        f"{_recipe_steps('check')}"
    )


def test_b2_oracle_is_still_the_third_gate_step() -> None:
    steps = _gate_steps("check")
    assert steps[ORACLE_GATE_INDEX] == WIDE, (
        f"the type oracle must stay the gate's step "
        f"{ORACLE_GATE_INDEX + 1} (after `uv run pytest`, before `make demo`); "
        f"step {ORACLE_GATE_INDEX + 1} is {steps[ORACLE_GATE_INDEX]!r}"
    )
    assert steps[ORACLE_GATE_INDEX - 1] == "uv run pytest"
    assert steps[ORACLE_GATE_INDEX + 1] == "make demo"


# ---------------------------------------------------------------------------
# Behavior 3 --- CI runs the same command, and gains no step doing it.
# ---------------------------------------------------------------------------


def test_b3_ci_type_step_body_is_the_widened_command() -> None:
    bodies = _ci_run_bodies()
    oracle = [b for b in bodies if "mypy" in b]
    assert oracle == [WIDE], (
        f"exactly one CI `run:` body must be the type oracle, and it must be "
        f"{WIDE!r} byte-identical to the `make check` step. Found: {oracle}"
    )


def test_b3_ci_run_step_count_is_unchanged() -> None:
    bodies = _ci_run_bodies()
    assert len(bodies) == CI_RUN_STEPS_102, (
        f"ci.yml must expose {CI_RUN_STEPS_102} graded `run:` steps -- the "
        f"widening edits the EXISTING type step's command and must not add or "
        f"remove a step. Found {len(bodies)}"
    )
    assert CI_RUN_STEPS_102 == CI_RUN_STEPS_110, (
        "the two shipped declarations of the CI run-step count must agree: "
        f"{CI_RUN_STEPS_102} vs {CI_RUN_STEPS_110}"
    )


# ---------------------------------------------------------------------------
# Behavior 4 --- local gate and CI stay in exact lockstep.
# ---------------------------------------------------------------------------


def test_b4_gate_step_constants_are_byte_identical() -> None:
    assert tuple(STEPS_102) == tuple(STEPS_110), (
        "tests/test_iter102_behavior.py and tests/test_iter110_behavior.py must "
        "declare byte-identical gate steps; re-keying one and not the other is "
        "the measured failure mode of a one-string widening"
    )


def test_b4_oracle_is_the_third_declared_gate_step() -> None:
    for name, steps in (("test_iter102", STEPS_102), ("test_iter110", STEPS_110)):
        assert steps[ORACLE_GATE_INDEX] == WIDE, (
            f"{name}'s CI_GATE_STEPS[{ORACLE_GATE_INDEX}] must be the widened "
            f"oracle {WIDE!r}; found {steps[ORACLE_GATE_INDEX]!r}"
        )


def test_b4_gate_step_entry_count_and_tail_are_unchanged() -> None:
    for name, steps in (("test_iter102", STEPS_102), ("test_iter110", STEPS_110)):
        assert len(steps) == EXPECTED_GATE_STEP_ENTRIES, (
            f"{name} must declare {EXPECTED_GATE_STEP_ENTRIES} gate-step ENTRIES "
            f"(count entries, never lines -- several are written as implicitly "
            f"concatenated fragments); found {len(steps)}"
        )
        assert steps[-1].startswith(LAST_GATE_STEP_PREFIX), (
            f"{name}'s last gate step must remain the armed "
            f"`pla signals --fail-on-kind` self-scan; found {steps[-1]!r}"
        )


def test_b4_local_gate_is_a_single_step_superset_of_ci() -> None:
    extra = set(_recipe_steps("check")) - set(STEPS_102)
    assert extra == {FRESHNESS_PRE_STEP}, (
        f"the `check` recipe must run the CI gate plus exactly the one freshness "
        f"pre-step {FRESHNESS_PRE_STEP!r}; extra steps were {sorted(extra)}"
    )


# ---------------------------------------------------------------------------
# Behavior 5 --- the append-only prefix pin survives the re-key.
# ---------------------------------------------------------------------------


def test_b5_preexisting_prefix_holds_against_the_rekeyed_constants() -> None:
    assert len(PREEXISTING_GATE_STEPS) == 6, (
        "test_iter128's PREEXISTING_GATE_STEPS must still declare 6 entries -- "
        "this iteration re-keys one entry's TEXT, it does not change the shape "
        f"of the append-only pin; found {len(PREEXISTING_GATE_STEPS)}"
    )
    assert PREEXISTING_GATE_STEPS[ORACLE_GATE_INDEX] == WIDE, (
        f"PREEXISTING_GATE_STEPS[{ORACLE_GATE_INDEX}] must be the widened "
        f"oracle; found {PREEXISTING_GATE_STEPS[ORACLE_GATE_INDEX]!r}"
    )
    assert tuple(STEPS_102[:6]) == tuple(PREEXISTING_GATE_STEPS), (
        "the gate must stay APPEND-ONLY over its first 6 steps: re-keying the "
        "oracle in CI_GATE_STEPS without re-keying PREEXISTING_GATE_STEPS (or "
        "vice versa) breaks the pin that proves no pre-existing step was "
        "silently dropped"
    )


# ---------------------------------------------------------------------------
# Behavior 6 --- scoped BY FILE: both graded scripts named, no directory form.
# ---------------------------------------------------------------------------


def test_b6_both_graded_examples_are_named_in_the_oracle() -> None:
    for path in GRADED_EXAMPLES:
        assert path in WIDE, (
            f"the widened oracle must name {path!r} explicitly -- naming the "
            f"`examples` directory instead would drag in "
            f"{UNGRADED_EXAMPLE_SUBTREE}, which exists to be imperfect"
        )


def test_b6_oracle_invocations_never_grade_a_directory() -> None:
    """Scoped to the mypy INVOCATIONS, not to file text.

    The Makefile and the workflow both EXPLAIN the file-scoping in prose that has
    to name the excluded surface, and the `check` recipe's 8th step legitimately
    passes `--workspace examples/fixture_workspace` to `pla signals`. A text-level
    ban would therefore red on the explanation of the rule, or on an unrelated
    shipped step, instead of on a violation of it.
    """
    invocations = [WIDE]
    invocations += [
        s
        for target in ("typecheck", "check")
        for s in _recipe_steps(target)
        if "mypy" in s
    ]
    invocations += [b for b in _ci_run_bodies() if "mypy" in b]
    for command in invocations:
        offenders = _example_dir_args(command)
        assert not offenders, (
            f"the type oracle must scope by FILE: {command!r} names "
            f"{offenders} instead of exactly {list(GRADED_EXAMPLES)}"
        )
        assert UNGRADED_EXAMPLE_SUBTREE not in command, (
            f"{UNGRADED_EXAMPLE_SUBTREE} is deliberately ungraded, but "
            f"{command!r} names it"
        )


@pytest.mark.parametrize(
    "bad",
    [
        "uv run mypy src/proactive_loop examples",
        "uv run mypy src/proactive_loop examples/",
        "uv run mypy examples/fixture_workspace",
        "uv run mypy src/proactive_loop examples/check_run.py examples/other.py",
    ],
)
def test_b6_guard_directory_form_is_rejected(bad: str) -> None:
    """The scoped predicate must FIRE on the spellings the ban is about."""
    assert _example_dir_args(bad), (
        f"the directory-form detector let {bad!r} through, so behavior 6 would "
        f"pass vacuously"
    )


def test_b6_guard_accepts_the_shipped_oracle() -> None:
    assert not _example_dir_args(WIDE), (
        "the directory-form detector must not fire on the two explicitly named "
        "graded scripts, or it would be unsatisfiable"
    )


# ---------------------------------------------------------------------------
# Behavior 7 --- the widening is ADDITIVE, never a substitution.
# ---------------------------------------------------------------------------


def test_b7_package_is_still_graded_by_the_widened_command() -> None:
    assert NARROW_ORACLE in WIDE, (
        f"the widened command must still contain {NARROW_ORACLE!r}: iteration "
        f"97's oracle assertion is a SUBSTRING check, and the package is the "
        f"surface the README's 'fully type-hinted' claim is actually about"
    )
    assert WIDE.startswith(f"uv run {NARROW_ORACLE} "), (
        f"the package must stay the FIRST graded path so the widening reads as "
        f"an extension of {NARROW_ORACLE!r}; got {WIDE!r}"
    )


def test_b7_narrow_oracle_substring_survives_in_both_carriers() -> None:
    for carrier in (MAKEFILE, WORKFLOW):
        assert NARROW_ORACLE in carrier.read_text(encoding="utf-8"), (
            f"{carrier.name} must still contain {NARROW_ORACLE!r} -- "
            f"tests/test_iter97_behavior.py pins that substring"
        )


# ---------------------------------------------------------------------------
# Behavior 8 --- the two graded scripts really do satisfy `strict = true`.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("rel", GRADED_EXAMPLES)
def test_b8_graded_example_is_shipped_and_parses(rel: str) -> None:
    path = REPO / rel
    assert path.is_file(), f"{rel} must exist -- the oracle names it explicitly"
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", rel],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert tracked.returncode == 0, (
        f"{rel} must be TRACKED: the oracle grades the SHIPPING tree, and a "
        f"fresh clone must contain every path the gate names. git said: "
        f"{tracked.stderr.strip()!r}"
    )
    assert _function_count(path) > 0, (
        f"the ast sweep found no function in {rel}; a sweep that walks zero "
        f"functions would report 'clean' forever"
    )


@pytest.mark.parametrize("rel", GRADED_EXAMPLES)
def test_b8_graded_example_is_fully_annotated(rel: str) -> None:
    problems = _annotation_violations(REPO / rel)
    assert not problems, (
        f"{rel} is inside the `strict = true` oracle, so every def must carry a "
        f"return annotation and annotate every parameter. Violations:\n"
        + "\n".join(problems)
    )


def test_b8_guard_sweep_fires_on_an_unannotated_def(tmp_path: Path) -> None:
    sample = tmp_path / "bad_example.py"
    sample.write_text(
        "def ok() -> None:\n"
        "    return None\n"
        "\n"
        "\n"
        "def missing_return():\n"
        "    return 1\n"
        "\n"
        "\n"
        "def missing_param(value) -> None:\n"
        "    print(value)\n",
        encoding="utf-8",
    )
    problems = _annotation_violations(sample)
    joined = "\n".join(problems)
    assert "missing_return" in joined and "missing_param" in joined, (
        f"the annotation sweep must catch a missing return annotation AND an "
        f"unannotated parameter, or behavior 8 passes vacuously. Got: {problems}"
    )
    assert "ok()" not in joined, (
        f"the sweep must not flag a fully annotated def: {problems}"
    )


# ---------------------------------------------------------------------------
# Behavior 9 --- the README documents the widened scope, BELOW the marker only.
# ---------------------------------------------------------------------------


def test_b9_reference_docs_name_both_graded_consumers() -> None:
    _, below = _readme_halves()
    typecheck_lines = [
        ln for ln in below.splitlines() if "make typecheck" in ln
    ]
    assert typecheck_lines, (
        "README.md must document `make typecheck` below the human-owned marker"
    )
    documented = "\n".join(typecheck_lines)
    for path in GRADED_EXAMPLES:
        assert path in documented, (
            f"the README's `make typecheck` documentation must name {path!r} -- "
            f"the oracle's scope is the claim, and a reference line that still "
            f"says only 'the package' understates what CI now enforces. Line(s):"
            f"\n{documented}"
        )


def test_b9_human_owned_intro_gained_nothing_from_this_widening() -> None:
    above, _ = _readme_halves()
    for token in (*GRADED_EXAMPLES, WIDE, "uv run mypy"):
        assert token not in above, (
            f"the human-owned PORTFOLIO INTRO block must not be edited by this "
            f"iteration, but it contains {token!r}. Only the three carved-out "
            f"numbers (collector count, CLI-verb count, test floor) may ever "
            f"change above the marker, and this widening touches none of them."
        )
