"""Black-box oracle for factory iteration 186 (state dir ``iter-182``).

Feature under test: ``make demo`` PERSISTS the scan snapshot its slate was
synthesized from, and both graded gates (``make check`` and ``.github/workflows/
ci.yml``) then run ``pla verify --fail-on-unresolved`` over that same-run pair --
so a fabricated ``sources`` entry in the published slate becomes a red build
instead of an unverifiable claim.

MODULE NAME (deliberate deviation from the spec's acceptance criteria, recorded
here because it is a REAL defect this stage caught). ``pm.md`` names the new test
module ``tests/test_iter182_behavior.py``. That file ALREADY EXISTS and is
TRACKED -- it is the 348-line shipped oracle for factory iteration 182 (state dir
``iter-178``, the SPEC.md enumerating-sections drift guard). This repo names
behavior modules by the FACTORY iteration number, which runs ahead of the
state-dir counter (``tests/test_iter109_behavior.py`` documents the offset, and
``tests/test_iter181_behavior.py`` records the same collision one iteration ago);
factory 182-185 are all shipped oracles, so state dir 182 is factory **186** and
this file is 186. Writing the spec's filename DESTROYS a shipped oracle -- the
iter-172 destroyed-oracle failure -- so the number, not the spec string, wins.

ISOLATION CONTRACT (honored, no exceptions). Every assertion is derived from this
iteration's spec ("Expected Behaviors" in ``pm.md``), the repo's own ``tests/``
conventions, the two GATE DEFINITIONS the behaviors are about (``Makefile`` and
``.github/workflows/ci.yml``), and the product's OBSERVABLE output obtained by
RUNNING it. **No file under ``src/`` was read, no ``git diff`` was inspected, and
neither ``engineer.md`` nor ``reviewer.md`` was opened.** Fully offline and
deterministic: the bundled scripted provider only, no network, no API key.

NO NESTED BUILD TOOLS. ``tests/test_iter110_behavior.py:519`` forbids the suite
from shelling out to a gate step, and a nested ``uv``/``make``/``pytest``/``mypy``
run strands the tester stage against its 600s cap. Behaviors 2 and 3 therefore
drive the CLI **in-process** via ``proactive_loop.cli.main([...])`` -- the idiom
99 existing call sites use -- and every byte either verb writes lands under
``tmp_path``. The repo's ``examples/fixture_workspace`` is read as the ``run``
input exactly as the demo recipe reads it; nothing here writes into it.

NO INDENTATION ASSERTIONS. CI is a 3.12 + 3.13 matrix and 3.13 strips the common
leading indent from docstrings at compile time, so nothing here asserts on
docstring, comment or help-text indentation.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Final

import pytest

from proactive_loop.cli import main

REPO: Final = Path(__file__).resolve().parents[1]
MAKEFILE: Final = REPO / "Makefile"
CI_YML: Final = REPO / ".github" / "workflows" / "ci.yml"
FIXTURE: Final = REPO / "examples" / "fixture_workspace"
SCRIPT: Final = REPO / "examples" / "scripted_responses.json"

# The step this iteration arms, spelled ONCE here. Behaviors 4 and 5 both assert
# the recipe and the workflow carry it BYTE-IDENTICALLY, so a single literal is
# the point -- two spellings could drift apart while both tests stayed green.
VERIFY_STEP: Final = (
    "uv run pla verify --slate .pla_runs/slate.json "
    "--snapshot .pla_runs/snapshot.json --fail-on-unresolved"
)
# The two pre-existing demo-artifact assertions (behavior 6's positional slice).
SLATE_ASSERTION: Final = "test -f .pla_runs/slate.json"
ARTIFACT_ASSERTION: Final = "ls .pla_runs/run-*/artifacts/*.md"
# The armed self-scan that must REMAIN the final graded step of both gates.
SIGNALS_PREFIX: Final = "uv run pla signals --workspace ."
# Since factory iter 254 the prefix above matches TWO gate steps -- the armed
# count budget was inserted immediately before the self-scan -- so a first-match
# `startswith(SIGNALS_PREFIX)` silently resolves to the budget. These are the
# flags that tell them apart, spelled once so the three call sites cannot drift.
SELF_SCAN_FLAG: Final = "--fail-on-kind"
BUDGET_FLAG: Final = "--fail-over"

# Spec behaviors 2/3: the shipped gate exit code, not a new one.
GATE_EXIT: Final = 5
# 8 until factory iter 264 inserted the same-run `--baseline` round trip between
# the citation verification and the two `--workspace .` gates.
EXPECTED_RUN_STEPS: Final = 9

# `verify`'s human-mode trailer carries the authoritative count.
_TRAILER_RE: Final = re.compile(
    r"^verified: (?P<goals>\d+) goals, (?P<sources>\d+) sources, "
    r"(?P<unresolved>\d+) unresolved$"
)
_GATE_KV_RE: Final = re.compile(r"\bunresolved=(?P<count>\d+)\b")

# A citation no collector can ever emit (behavior 3's fabricated source).
FABRICATED: Final = "no/such/path/fabricated-by-iter186.md"


# ---------------------------------------------------------------------------
# Helpers -- an INDEPENDENT reading of each gate definition, so this oracle can
# disagree with the shipped drift guards instead of echoing them.
# ---------------------------------------------------------------------------


def _recipe(target: str) -> list[str]:
    """The command lines of one ``Makefile`` target, backslash-continuations
    joined into ONE logical command each and whitespace normalized."""
    lines = MAKEFILE.read_text(encoding="utf-8").splitlines()
    start = next(
        (i for i, ln in enumerate(lines) if ln.startswith(f"{target}:")), None
    )
    assert start is not None, f"Makefile must define a `{target}:` target"
    out: list[str] = []
    pending = ""
    for raw in lines[start + 1 :]:
        if raw and not raw.startswith("\t"):
            break  # next target or a blank-separated block ends the recipe
        body = raw.strip()
        if not body:
            continue
        if body.endswith("\\"):
            pending += body[:-1].strip() + " "
            continue
        out.append(" ".join((pending + body).split()))
        pending = ""
    assert not pending, f"`{target}:` ends on a dangling continuation"
    return out


def _ci_run_steps() -> list[str]:
    """Every graded ``run:`` step of ``ci.yml``, as normalized command strings.

    A block scalar (``run: |``) is ONE step whose body may hold several
    commands; they are joined with ``" ; "`` so a block cannot be mistaken for
    several steps, which is what makes the count in behavior 5 meaningful.
    """
    steps: list[str] = []
    lines = CI_YML.read_text(encoding="utf-8").splitlines()
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if stripped == "run: |":
            indent = len(lines[i]) - len(lines[i].lstrip())
            body: list[str] = []
            i += 1
            while i < len(lines):
                nxt = lines[i]
                if nxt.strip() and (len(nxt) - len(nxt.lstrip())) <= indent:
                    break
                if nxt.strip():
                    body.append(" ".join(nxt.split()))
                i += 1
            steps.append(" ; ".join(body))
            continue
        if stripped.startswith("run: "):
            steps.append(" ".join(stripped[len("run: ") :].split()))
        i += 1
    return steps


def _invoke(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, str, str]:
    rc = main(list(args))
    captured = capsys.readouterr()
    return rc, captured.out, captured.err


def _trailer(stdout: str) -> re.Match[str]:
    for line in stdout.splitlines():
        match = _TRAILER_RE.match(line.strip())
        if match:
            return match
    raise AssertionError(f"expected a `verified: ...` trailer line; got {stdout!r}")


def _demo_pair(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> tuple[Path, Path]:
    """Run the demo's EXACT argument set in-process into ``tmp_path``.

    Returns ``(slate, snapshot)``. This is the same-run pair the gate verifies:
    one ``pla run`` writes both, which is why this caller -- and only this
    caller -- is entitled to arm ``--fail-on-unresolved``.
    """
    state = tmp_path / "state"
    snapshot = state / "snapshot.json"
    rc, out, err = _invoke(
        capsys,
        "run",
        "--workspace",
        str(FIXTURE),
        "--provider",
        "scripted",
        "--scripted-responses",
        str(SCRIPT),
        "--state-dir",
        str(state),
        "--snapshot",
        str(snapshot),
    )
    assert rc == 0, f"the demo argument set must exit 0; got {rc}\n{out}\n{err}"
    slate = state / "slate.json"
    assert slate.is_file(), f"the demo must publish a slate; state held {list(state.iterdir())}"
    assert snapshot.is_file(), "`run --snapshot PATH` must persist the scan snapshot"
    assert snapshot.stat().st_size > 0, "the persisted snapshot must be non-empty"
    return slate, snapshot


# ---------------------------------------------------------------------------
# Behavior 1 -- the demo recipe persists a snapshot
# ---------------------------------------------------------------------------


def test_b1_demo_recipe_persists_its_snapshot_beside_the_slate() -> None:
    """Spec behavior 1.

    Exactly ONE ``--snapshot``, valued ``.pla_runs/snapshot.json``, and the
    recipe still writes into ``.pla_runs`` -- the one directory ``make check``'s
    ``rm -rf .pla_runs`` pre-step wipes and the artifact assertions read.
    """
    recipe = _recipe("demo")
    joined = " ".join(recipe)
    assert joined.count("--snapshot") == 1, (
        "the demo recipe must pass exactly one --snapshot argument; recipe is "
        f"{recipe!r}"
    )
    assert "--snapshot .pla_runs/snapshot.json" in joined, recipe
    assert "--state-dir .pla_runs" in joined, recipe
    # The pair must land in the SAME wiped directory, or `make check` verifies a
    # snapshot left over from an earlier run.
    assert "--state-dir .pla_runs --snapshot .pla_runs/snapshot.json" in joined, (
        "snapshot and state-dir must both be rooted at .pla_runs; recipe is "
        f"{joined!r}"
    )


# ---------------------------------------------------------------------------
# Behaviors 2 and 3 -- the armed pair, proven in BOTH directions
# ---------------------------------------------------------------------------


def test_b2_armed_gate_is_green_on_the_real_demo_data(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec behavior 2: the real published pair verifies clean, exit 0."""
    slate, snapshot = _demo_pair(tmp_path, capsys)
    rc, out, err = _invoke(
        capsys,
        "verify",
        "--slate",
        str(slate),
        "--snapshot",
        str(snapshot),
        "--fail-on-unresolved",
    )
    assert rc == 0, f"the armed gate must be GREEN on real demo data; got {rc}\n{err}"
    match = _trailer(out)
    assert int(match.group("unresolved")) == 0, out
    # Anti-vacuity: a run that cited NOTHING would also report 0 unresolved.
    assert int(match.group("sources")) > 0, (
        "the slate must cite at least one source, or `0 unresolved` proves nothing"
    )
    assert int(match.group("goals")) > 0, out


def test_b3_armed_gate_fires_on_a_fabricated_citation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec behavior 3: two-sided. A gate proven green but never proven to fire
    is a fail-open gate, so the SAME command must exit 5 on a slate carrying one
    citation no collector emitted."""
    slate, snapshot = _demo_pair(tmp_path, capsys)
    doc = json.loads(slate.read_text(encoding="utf-8"))
    assert doc["goals"], "the demo slate must hold at least one goal"
    doc["goals"][0]["sources"].append(FABRICATED)
    tampered = tmp_path / "slate_with_fabricated_source.json"
    tampered.write_text(json.dumps(doc), encoding="utf-8")

    rc, out, err = _invoke(
        capsys,
        "verify",
        "--slate",
        str(tampered),
        "--snapshot",
        str(snapshot),
        "--fail-on-unresolved",
    )
    assert rc == GATE_EXIT, (
        f"a fabricated citation must trip the gate with exit {GATE_EXIT}; got {rc}"
    )
    kv = _GATE_KV_RE.search(err) or _GATE_KV_RE.search(out)
    assert kv is not None, f"the failure must name the unresolved count; stderr {err!r}"
    assert int(kv.group("count")) > 0, err
    assert int(_trailer(out).group("unresolved")) > 0, out


def test_b3b_arming_the_gate_here_did_not_arm_it_for_every_caller(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Third direction (spec behavior 3's intent, made explicit).

    ``verify`` is documented reporting-only BY DEFAULT because several
    collectors are mtime-driven, so an unresolved source can mean staleness
    rather than fabrication. Wiring the flag into two gate sites must not turn
    the DEFAULT into a gate: the same fabricated slate, verified WITHOUT
    ``--fail-on-unresolved``, still exits 0 while reporting the count.
    """
    slate, snapshot = _demo_pair(tmp_path, capsys)
    doc = json.loads(slate.read_text(encoding="utf-8"))
    doc["goals"][0]["sources"].append(FABRICATED)
    tampered = tmp_path / "slate_unarmed.json"
    tampered.write_text(json.dumps(doc), encoding="utf-8")

    rc, out, _ = _invoke(
        capsys, "verify", "--slate", str(tampered), "--snapshot", str(snapshot)
    )
    assert rc == 0, f"the UNARMED default must stay reporting-only; got {rc}"
    assert int(_trailer(out).group("unresolved")) > 0, (
        "reporting-only still has to REPORT the unresolved citation"
    )


# ---------------------------------------------------------------------------
# Behavior 4 -- `make check` runs it, and the self-scan stays last
# ---------------------------------------------------------------------------


def test_b4_check_recipe_verifies_after_the_artifacts_and_before_the_self_scan() -> None:
    """Spec behavior 4."""
    recipe = _recipe("check")
    assert VERIFY_STEP in recipe, (
        f"`make check` must run the verify step verbatim; recipe is {recipe!r}"
    )
    idx_verify = recipe.index(VERIFY_STEP)
    idx_artifacts = next(
        i for i, step in enumerate(recipe) if step.startswith(ARTIFACT_ASSERTION)
    )
    # factory iter 254 inserted a SECOND `pla signals` step (the armed count
    # budget) ahead of the self-scan, so SIGNALS_PREFIX alone no longer
    # identifies one step: a bare first-match resolves to the BUDGET. Locate
    # each by the flag that makes it what it is.
    idx_signals = next(
        i
        for i, step in enumerate(recipe)
        if step.startswith(SIGNALS_PREFIX) and SELF_SCAN_FLAG in step
    )
    idx_budget = next(
        i
        for i, step in enumerate(recipe)
        if step.startswith(SIGNALS_PREFIX) and BUDGET_FLAG in step
    )
    assert idx_artifacts < idx_verify < idx_signals, (
        "verify must sit AFTER the demo-artifact assertions and BEFORE the "
        f"self-scan; got artifacts={idx_artifacts} verify={idx_verify} "
        f"signals={idx_signals}"
    )
    assert idx_verify < idx_budget < idx_signals, (
        "the count budget must sit AFTER verify and BEFORE the self-scan; got "
        f"verify={idx_verify} budget={idx_budget} self-scan={idx_signals}"
    )
    assert idx_signals == len(recipe) - 1, (
        f"the armed self-scan must remain the FINAL step; recipe is {recipe!r}"
    )


# ---------------------------------------------------------------------------
# Behavior 5 -- CI grades the identical step, and all three guards agree
# ---------------------------------------------------------------------------


def test_b5_ci_grades_the_byte_identical_step_in_the_same_position() -> None:
    """Spec behavior 5: same command, same relative position, 7 graded steps."""
    steps = _ci_run_steps()
    assert len(steps) == EXPECTED_RUN_STEPS, (
        f"ci.yml must expose exactly {EXPECTED_RUN_STEPS} graded `run:` steps; "
        f"found {len(steps)}: {steps!r}"
    )
    assert VERIFY_STEP in steps, (
        "ci.yml must grade the verify step BYTE-IDENTICALLY to the `make check` "
        f"recipe step; graded steps are {steps!r}"
    )
    idx_verify = steps.index(VERIFY_STEP)
    idx_artifacts = next(
        i for i, s in enumerate(steps) if ARTIFACT_ASSERTION in s
    )
    # Narrowed for the same reason as behavior 4 above: two `pla signals` steps
    # share SIGNALS_PREFIX since factory iter 254.
    idx_signals = next(
        i
        for i, s in enumerate(steps)
        if s.startswith(SIGNALS_PREFIX) and SELF_SCAN_FLAG in s
    )
    idx_budget = next(
        i
        for i, s in enumerate(steps)
        if s.startswith(SIGNALS_PREFIX) and BUDGET_FLAG in s
    )
    assert idx_artifacts < idx_verify < idx_signals, (
        f"artifacts={idx_artifacts} verify={idx_verify} signals={idx_signals}"
    )
    assert idx_verify < idx_budget < idx_signals, (
        f"verify={idx_verify} budget={idx_budget} self-scan={idx_signals}"
    )
    assert idx_signals == len(steps) - 1, "the self-scan must stay the last graded step"
    # The local gate and CI cannot silently diverge.
    assert VERIFY_STEP in _recipe("check"), "the two gate sites must carry one spelling"


def test_b5b_all_three_drift_guards_expect_the_same_step_count() -> None:
    """Spec behavior 5: ``EXPECTED_CI_RUN_STEPS`` agrees across all three
    modules that declare it, and equals this module's independent count."""
    from tests.test_iter102_behavior import EXPECTED_CI_RUN_STEPS as C102
    from tests.test_iter110_behavior import EXPECTED_CI_RUN_STEPS as C110
    from tests.test_iter128_behavior import EXPECTED_CI_RUN_STEPS as C128

    assert C102 == C110 == C128 == EXPECTED_RUN_STEPS, (
        f"drift: test_iter102={C102} test_iter110={C110} test_iter128={C128} "
        f"independent count={EXPECTED_RUN_STEPS}"
    )
    assert len(_ci_run_steps()) == C110


def test_b5c_the_new_command_is_in_every_declared_gate_step_tuple() -> None:
    """Spec behavior 5: the step joins ``CI_GATE_STEPS`` in BOTH modules that
    declare one, so neither drift guard can stay green while the gate changes."""
    from tests.test_iter102_behavior import CI_GATE_STEPS as GATE_102
    from tests.test_iter110_behavior import CI_GATE_STEPS as GATE_110

    for name, gate in (("test_iter102", GATE_102), ("test_iter110", GATE_110)):
        assert VERIFY_STEP in tuple(gate), (
            f"{name}'s CI_GATE_STEPS must contain the new verify step; got "
            f"{list(gate)!r}"
        )
        # Position: after the artifact assertion, before the self-scan.
        idx = tuple(gate).index(VERIFY_STEP)
        idx_art = next(i for i, s in enumerate(gate) if s.startswith(ARTIFACT_ASSERTION))
        # Narrowed for the same reason as behaviors 4/5: without SELF_SCAN_FLAG
        # this stays GREEN while silently checking "before the count budget".
        idx_sig = next(
            i
            for i, s in enumerate(gate)
            if s.startswith(SIGNALS_PREFIX) and SELF_SCAN_FLAG in s
        )
        assert idx_art < idx < idx_sig, f"{name}: art={idx_art} verify={idx} sig={idx_sig}"


# ---------------------------------------------------------------------------
# Behavior 6 -- the positional slice held, and the new step is never executed
# ---------------------------------------------------------------------------


def test_b6_artifact_assertion_slice_still_names_exactly_the_two_assertions() -> None:
    """Spec behavior 6: ``ARTIFACT_ASSERTION_STEPS`` is a POSITIONAL slice
    (``CI_GATE_STEPS[4:6]``); inserting at index 6 must leave it untouched."""
    from tests.test_iter110_behavior import ARTIFACT_ASSERTION_STEPS

    assert tuple(ARTIFACT_ASSERTION_STEPS) == (SLATE_ASSERTION, ARTIFACT_ASSERTION), (
        "the slice must still name exactly the two pre-existing demo-artifact "
        f"assertions; it is {list(ARTIFACT_ASSERTION_STEPS)!r}"
    )


def test_b6b_the_new_step_is_expensive_and_never_executed_by_the_suite() -> None:
    """Spec behavior 6: the verify step is a member of the ``expensive`` set the
    suite is forbidden to shell out to -- it invokes ``uv``, and a nested run
    strands the tester stage against its 600s cap."""
    from tests.test_iter110_behavior import ARTIFACT_ASSERTION_STEPS, CI_GATE_STEPS

    expensive = [s for s in CI_GATE_STEPS if s not in tuple(ARTIFACT_ASSERTION_STEPS)]
    assert VERIFY_STEP in expensive, (
        "the verify step must NOT be classified as a cheap artifact assertion; "
        f"expensive set is {expensive!r}"
    )
    assert len(expensive) == 8, (
        f"the expensive set grew 5 -> 6 in THIS iteration, 6 -> 7 in factory "
        f"iter 254 (the armed count budget) and 7 -> 8 in factory iter 264 (the "
        f"same-run `--baseline` round trip), each a never-executed gate step; got "
        f"{len(expensive)}: {expensive!r}"
    )
    # The safety rail behind the whole rule.
    assert "uv " in VERIFY_STEP
