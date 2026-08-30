"""Black-box oracle for factory iteration 254 (state dir ``iter-254``).

Feature under test: ``pla signals --fail-over N`` -- an enforcement flag shipped
in factory iter 145 and never once executed by a gate, recipe, hook or example --
gains its FIRST CONSUMER. An armed, scoped count-budget step is inserted into
``make check`` and byte-identically into ``.github/workflows/ci.yml``,
immediately BEFORE the existing armed ``--fail-on-kind`` self-scan, which stays
last on both surfaces.

MODULE NAME (derived from the REPO, never from the state-dir number). This repo
names behavior modules by an ITERATION counter that runs ahead of nothing in
particular: ``git ls-files tests`` tops out at ``test_iter231_behavior.py``, so
this file is **232**. The state dir is ``iter-254`` and ``pm.md`` is headed
"factory iteration 254"; writing ``tests/test_iter254_behavior.py`` would be a
guess at an offset, while writing an already-tracked number DESTROYS a shipped
oracle (the iter-172 destroyed-oracle failure, and the iter-186 near-miss
recorded in that module's own docstring). ``git cat-file -e
HEAD:tests/test_iter232_behavior.py`` was proven to FAIL before this file was
created, so nothing was overwritten.

ISOLATION CONTRACT (honored, no exceptions). Every assertion here is derived
from this iteration's spec ("Expected Behaviors" in ``pm.md``), the repo's own
``tests/`` conventions, the two GATE DEFINITIONS the behaviors are about
(``Makefile`` and ``.github/workflows/ci.yml``), and the product's OBSERVABLE
exit status and stdout obtained by RUNNING it. **No file under ``src/`` was
read, no ``git diff`` was inspected, and ``engineer.md``, ``reviewer.md`` and
``fix_review.md`` were never opened.** Fully offline and deterministic: no
network, no API key, no model provider.

NO RE-TYPED LITERALS. The step under test is PARSED out of the two shipped
surfaces and compared against itself; it is never spelled out here. A hand-typed
copy differing by one space would fail with an unreadable diff that looks like an
ordering bug (the iter-254 fix pass recorded exactly that trap), and a re-typed
copy also cannot prove behavior 3's byte-identity claim -- comparing a literal to
a literal proves nothing about the two files.

NO AMBIGUOUS FIRST-MATCH LOCATORS. ``next(i for i, s in enumerate(steps) if
s.startswith(SIGNALS_PREFIX))`` is now ambiguous on BOTH surfaces, because this
iteration makes ``uv run pla signals --workspace .`` a prefix of TWO steps. Every
locator here selects on the DISCRIMINATING flag (``--fail-over`` vs
``--fail-on-kind``) and asserts the match is UNIQUE, so a third ``signals`` step
added later is a loud failure rather than a silent retarget.

NO NESTED BUILD TOOLS. ``tests/test_iter110_behavior.py`` forbids the suite from
shelling out to a gate step, and a nested ``uv``/``make``/``pytest``/``mypy`` run
strands the tester stage against its 600s cap. Behaviors 4 and 5 therefore run
the product's INSTALLED console script directly -- the ``uv run pla`` -> ``pla``
substitution ``tests/test_iter128_behavior.py`` established -- so no resolver,
no build tool and no second interpreter is ever spawned.

NO INDENTATION ASSERTIONS. CI is a 3.12 + 3.13 matrix and 3.13 strips the common
leading indent from docstrings at compile time, so nothing here asserts on
docstring, comment or help-text indentation.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Final

REPO: Final = Path(__file__).resolve().parents[1]
MAKEFILE: Final = REPO / "Makefile"
WORKFLOW: Final = REPO / ".github" / "workflows" / "ci.yml"

# The two discriminating flags. Neither step is spelled out; these are the
# smallest tokens that tell the count budget from the kind self-scan.
BUDGET_FLAG: Final = "--fail-over"
SELF_SCAN_FLAG: Final = "--fail-on-kind"
SIGNALS_PREFIX: Final = "uv run pla signals"

_REDIRECT_SUFFIX: Final = re.compile(r"\s*>\s*/dev/null\s*$")
_RUN_KEY: Final = re.compile(r"^(\s*)-?\s*run:\s*(.*)$")


# --------------------------------------------------------------------------
# Makefile / workflow parsing -- lifted verbatim from the conventions already
# shipped in tests/test_iter128_behavior.py so both oracles read the two gate
# definitions the SAME way.
# --------------------------------------------------------------------------
def _makefile_lines() -> list[str]:
    return MAKEFILE.read_text(encoding="utf-8").splitlines()


def _make_recipe(target: str) -> list[str]:
    """The tab-indented recipe lines of a Makefile ``target:`` (each stripped)."""
    recipe: list[str] = []
    in_target = False
    for line in _makefile_lines():
        if re.match(rf"^{re.escape(target)}\s*:", line):
            in_target = True
            continue
        if in_target:
            if line.startswith("\t"):
                recipe.append(line.strip())
            elif line.strip() == "":
                continue
            else:
                break
    return recipe


def _normalize(line: str) -> str:
    """``$(MAKE)`` -> ``make``, whitespace collapsed, make's line prefixes dropped."""
    text = re.sub(r"\s+", " ", line.replace("$(MAKE)", "make")).strip()
    return text.lstrip("@-+ ").strip()


def _recipe_steps(target: str) -> list[str]:
    """Normalized SHELL steps of a recipe: one per line, ``&&`` chains split."""
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
    """Every graded ``run:`` step of a workflow, as a list of command LINES."""
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
            nxt = lines[index]
            if nxt.strip() == "":
                index += 1
                continue
            leading = len(nxt) - len(nxt.lstrip())
            if leading <= len(indent):
                break
            body.append(nxt.strip())
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
                commands.append(_bare(line))
    return commands


# --------------------------------------------------------------------------
# UNIQUE locators. Selecting on the discriminating flag, and asserting the
# match is unique, is what stops a later third `signals` step from silently
# retargeting these tests (the defect the iter-254 review caught in three
# already-shipped call sites).
# --------------------------------------------------------------------------
def _sole_index(steps: list[str], flag: str, surface: str) -> int:
    hits = [i for i, step in enumerate(steps) if flag in step]
    assert len(hits) == 1, (
        f"exactly ONE {surface} step may carry {flag!r}, so that every locator "
        f"in this module is unambiguous; found {len(hits)} at {hits}: "
        f"{[steps[i] for i in hits]}"
    )
    return hits[0]


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


def _budget_argv(*, override: str | None = None) -> list[str]:
    """The gate's OWN budget command, built from the PARSED Makefile step.

    Two substitutions only: ``uv run pla`` -> the installed console script (same
    entry point, no nested ``uv`` resolve), and ``--workspace`` -> this repo's
    absolute path, because the step's literal ``.`` is relative to the gate's cwd.
    ``override`` replaces the budget VALUE, which is how behavior 4's two-sided
    arm proves the flag is enforcing rather than inert.
    """
    steps = _check_steps()
    tokens = steps[_sole_index(steps, BUDGET_FLAG, "`check` recipe")].split()
    assert tokens[:3] == ["uv", "run", "pla"], (
        f"the budget step must invoke the product's console script; got {tokens}"
    )
    argv = [str(_console_script()), *tokens[3:]]
    argv[argv.index("--workspace") + 1] = str(REPO)
    if override is not None:
        argv[argv.index(BUDGET_FLAG) + 1] = override
    return argv


def _run(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv, cwd=str(REPO), capture_output=True, text=True, timeout=120
    )


# ==========================================================================
# Behavior 1 -- `make check`'s recipe contains a `pla signals` invocation
# carrying `--fail-over`.
# ==========================================================================
def test_b1_check_recipe_runs_an_armed_count_budget() -> None:
    steps = _check_steps()
    index = _sole_index(steps, BUDGET_FLAG, "`check` recipe")
    step = steps[index]

    assert step.startswith(SIGNALS_PREFIX), (
        f"the count budget must be armed on the `signals` verb (the verb that "
        f"owns {BUDGET_FLAG}), not bolted onto another command; step was {step!r}"
    )
    value = step.split()[step.split().index(BUDGET_FLAG) + 1]
    assert value.isdigit(), (
        f"{BUDGET_FLAG} must be armed with a concrete integer budget, otherwise "
        f"the step is advertised-but-not-enforcing; got {value!r} in {step!r}"
    )


# ==========================================================================
# Behavior 2 -- the budget step is NOT last; the armed `--fail-on-kind`
# self-scan stays last.
# ==========================================================================
def test_b2_budget_precedes_the_self_scan_which_stays_last() -> None:
    steps = _check_steps()
    idx_budget = _sole_index(steps, BUDGET_FLAG, "`check` recipe")
    idx_self_scan = _sole_index(steps, SELF_SCAN_FLAG, "`check` recipe")

    assert idx_self_scan == len(steps) - 1, (
        "the armed --fail-on-kind self-scan must remain the LAST step of "
        f"`check` (it is the gate every earlier step is allowed to precede); it "
        f"sits at {idx_self_scan} of {len(steps) - 1}: {steps}"
    )
    assert idx_budget < idx_self_scan, (
        f"the count budget must be INSERTED BEFORE the self-scan, not appended "
        f"after it; budget at {idx_budget}, self-scan at {idx_self_scan}"
    )
    assert idx_budget == idx_self_scan - 1, (
        "the spec places the budget IMMEDIATELY before the self-scan; budget at "
        f"{idx_budget}, self-scan at {idx_self_scan}"
    )


# ==========================================================================
# Behavior 3 -- the CI job runs the same invocation, BYTE-IDENTICAL to the
# Makefile's.
# ==========================================================================
def test_b3_ci_runs_the_byte_identical_budget_step() -> None:
    make_steps = _check_steps()
    ci_steps = _ci_commands()
    make_budget = make_steps[_sole_index(make_steps, BUDGET_FLAG, "`check` recipe")]
    ci_budget = ci_steps[_sole_index(ci_steps, BUDGET_FLAG, "ci.yml run")]

    assert ci_budget == make_budget, (
        "the CI budget step must be BYTE-IDENTICAL to the `check` recipe's, so "
        "the local gate and the graded build enforce the same budget over the "
        f"same collector set;\n  Makefile: {make_budget!r}\n  ci.yml:   {ci_budget!r}"
    )


def test_b3b_ci_self_scan_also_stays_last() -> None:
    ci_steps = _ci_commands()
    idx_budget = _sole_index(ci_steps, BUDGET_FLAG, "ci.yml run")
    idx_self_scan = _sole_index(ci_steps, SELF_SCAN_FLAG, "ci.yml run")

    assert idx_self_scan == len(ci_steps) - 1, (
        "the armed self-scan must stay the LAST graded CI command, mirroring "
        f"`check`; it sits at {idx_self_scan} of {len(ci_steps) - 1}: {ci_steps}"
    )
    assert idx_budget == idx_self_scan - 1, (
        "CI must place the budget immediately before the self-scan, exactly as "
        f"`check` does; budget {idx_budget}, self-scan {idx_self_scan}"
    )


# ==========================================================================
# Behavior 4 -- the armed budget exits 0 against this repo today.
#
# TWO-SIDED ON PURPOSE. "Exits 0" alone is satisfiable by an INERT flag: a
# budget that can never trip is exactly the "advertised but never demonstrated"
# condition this iteration exists to end, and it would pass a green-only test.
# So the same parsed command is also run with its budget lowered below the
# measured count, and it MUST fail. The count is never hardcoded -- it is read
# back out of the product's own trip message, so this pair keeps working when
# the census legitimately changes.
# ==========================================================================
_TRIP_COUNT: Final = re.compile(r"count=(\d+)")


def _measured_count() -> tuple[int, str]:
    """The census the shipped budget governs, read from the product's own trip
    message by arming an impossible budget of 0. Returns (count, combined output).
    """
    result = _run(_budget_argv(override="0"))
    combined = result.stdout + result.stderr
    assert result.returncode != 0, (
        "a budget of 0 must TRIP on any non-empty census -- if it exits 0 the "
        "census is empty and the shipped budget is inert, which is the exact "
        f"fail-open this step exists to close; output was:\n{combined[-2000:]}"
    )
    match = _TRIP_COUNT.search(combined)
    assert match is not None, (
        "the tripped budget must report the COUNT it measured, so a red build "
        f"is diagnosable without re-running by hand; output was:\n{combined[-2000:]}"
    )
    return int(match.group(1)), combined


def test_b4_armed_budget_passes_against_this_repo() -> None:
    steps = _check_steps()
    step = steps[_sole_index(steps, BUDGET_FLAG, "`check` recipe")]
    budget = int(step.split()[step.split().index(BUDGET_FLAG) + 1])

    result = _run(_budget_argv())
    assert result.returncode == 0, (
        "the budget armed in the gate must PASS against this repo, otherwise "
        "every `make check` and every CI run is red on arrival; "
        f"exit was {result.returncode}\n"
        f"stdout:\n{result.stdout[-1500:]}\nstderr:\n{result.stderr[-1500:]}"
    )

    count, _ = _measured_count()
    assert count <= budget, (
        f"the census ({count}) must fit inside the armed budget ({budget}); a "
        "budget below the count is a gate that is red by construction"
    )


def test_b4b_armed_budget_actually_fires_when_the_census_exceeds_it() -> None:
    count, _ = _measured_count()
    assert count >= 1, (
        "a budget over an EMPTY census cannot fire and is decoration, not "
        f"enforcement; measured count was {count}"
    )

    result = _run(_budget_argv(override=str(count - 1)))
    combined = result.stdout + result.stderr
    assert result.returncode != 0, (
        f"with the budget one below the measured census ({count - 1} < {count}) "
        "the gate MUST fail -- a budget that never trips is an inert flag and "
        "leaves --fail-over still unconsumed; "
        f"exit was {result.returncode}\noutput:\n{combined[-2000:]}"
    )
    assert str(count) in combined, (
        "the failure must name the measured count so the red build is "
        f"self-explaining; output was:\n{combined[-2000:]}"
    )


def test_b4c_budget_is_scoped_to_an_explicit_collector_set() -> None:
    """WHY this is a behavior and not a style point: the budget's stability is
    what makes behavior 4 durable. A budget over the WHOLE census would move
    whenever any collector gains a signal -- including the mtime-driven ones,
    which differ between a working tree and a fresh clone -- so CI could go red
    on a checkout that changed nothing. Pinning an explicit collector set is the
    property that makes the same number hold in both populations.
    """
    steps = _check_steps()
    step = steps[_sole_index(steps, BUDGET_FLAG, "`check` recipe")]
    collectors = re.findall(r"--collector\s+([A-Za-z_]+)", step)

    assert len(collectors) >= 2, (
        "the count budget must name an explicit collector set, so the number it "
        f"enforces is stable across a working tree and a fresh clone; got {collectors}"
    )
    assert len(collectors) == len(set(collectors)), (
        f"a collector must not be listed twice in the budget step; got {collectors}"
    )
    assert "--workspace" in step, (
        f"the budget must pin the workspace it censuses; step was {step!r}"
    )
