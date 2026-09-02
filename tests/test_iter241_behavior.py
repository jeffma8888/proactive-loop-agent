"""Black-box behavior tests for state-dir iteration 265 (ships as ``foundry iter 264``):
``--baseline`` GAINS ITS FIRST EXECUTABLE CONSUMER AS A SAME-RUN ROUND TRIP.

Feature under test (``pm.md`` "## Feature"): ``make check`` and
``.github/workflows/ci.yml`` each gain ONE step that consumes the snapshot
``make demo`` just wrote and requires the survivors to be empty --
``uv run pla signals --workspace examples/fixture_workspace --baseline
.pla_runs/snapshot.json --fail-over 0`` -- retiring roadmap row #161, which sat
QUEUED for 130 iterations behind an objection ("a committed snapshot rots into a
blindfold") that a same-run round trip retires rather than pays.

MODULE NAME -- derived from the REPO, never from the state-dir number. The
highest tracked ``tests/test_iterNN_behavior.py`` is **240**, so **241** is the
next free name, and ``git cat-file -e HEAD:tests/test_iter241_behavior.py``
FAILED (``path 'tests/test_iter241_behavior.py' does not exist in 'HEAD'``)
before the first byte was written. The state dir is 265; naming a module from
the state-dir counter is what overwrote a shipped 18,786-byte oracle in state
dir 186.

ISOLATION CONTRACT (honored, no exceptions). Every assertion below is derived
from this iteration's ``pm.md`` "## Expected Behaviors" 1-9, from the tracked
gate documents themselves (``Makefile``, ``.github/workflows/ci.yml``,
``ROADMAP.md``, ``ROADMAP_ARCHIVE.md``), from the conventions of existing
modules under ``tests/`` (``test_iter138_behavior.py`` for the console-script
subprocess idiom and the six-key identity tuple, ``test_iter102_behavior.py``
for the ``CI_GATE_STEPS`` constants, ``test_iter214_behavior.py`` for the
ledger/budget idiom and the ``from tests.test_roadmap_size_budget import ...``
style), and from RUNNING the shipped ``pla`` console script. **No file under
``src/`` was read as source text, no engineer, reviewer or fix-review note was
opened, and no ``git diff`` was consulted.**

OFFLINE, DETERMINISTIC, FRESH-CLONE SAFE. Every path asserted on is TRACKED by
git and resolved from ``__file__``: no network and no ``git`` invocation. The
two behaviors that must EXECUTE the round trip (spec behaviors 4 and 5) do NOT
read ``.pla_runs/`` -- that directory is gitignored and absent from a fresh
clone, which is the iter-154 trap. They instead reproduce the gate's own two
halves against the TRACKED ``examples/fixture_workspace`` with ``--state-dir``
and ``--snapshot`` pointed into ``tmp_path``, which is exactly what ``make
demo`` does with ``.pla_runs``. Nothing asserts on docstring or help-text
indentation, so the 3.12/3.13 matrix legs cannot diverge here.

NO SIGNAL COUNT IS PINNED, DELIBERATELY. The population of the fixture
workspace is state-dependent: the PM measured **38** signals in a fresh clone
(``recent_file`` fires 5 times against checkout-time mtimes) and this tester
measured **46** in the warm tree (``recent_file`` fires 0 times, other
collectors more). A test pinning either number is red on the other machine, so
the executable arms assert the state-INDEPENDENT invariant instead: the
identity set the produce half records EQUALS the set the consume half perceives,
so the residual is empty whatever the population is. Non-vacuousness is
asserted rather than assumed -- every empty-residual arm is paired with a
control arm proving the same workspace emits signals at all.

PINNED BY IDENTITY, NOT BY POSITION -- a deliberate, disclosed deviation from
the literal wording of spec behavior 8 ("the Done ledger ENDS with" the #161
record). ``tests/test_iter240_behavior.py`` pinned iteration 263's row as the
ledger TAIL and thereby red-tested the very next iteration, which is REQUIRED
to append its own row; positional pinning forces each successor either to break
the suite or to re-key the literal and thereby stop verifying its predecessor.
So behavior 8 is verified here as presence + uniqueness + shape + ADJACENCY
(``#161`` immediately follows ``#261``), which is everything the spec's intent
needs and is stable across every future append.

Coverage (numbered to match the spec's Expected Behaviors):

1. ``make check``'s recipe contains the new step verbatim, exactly once.
2. ``ci.yml`` carries the SAME string byte-identically in exactly one ``run:``
   step -- so the two sites cannot diverge.
3. In BOTH files the step sits AFTER ``pla verify --fail-on-unresolved`` and
   BEFORE both ``--workspace .`` steps, leaving the repo self-scan last.
4. The green arm: a same-run snapshot leaves zero residual and ``--fail-over 0``
   exits 0 printing the empty marker.
5. The FIRE arm: deleting ONE live signal from the baseline exits 5 and names
   both ``count=1`` and ``budget=0``.
6. ``test_iter102`` and ``test_iter110`` each carry the step at index 7 of
   ``CI_GATE_STEPS``, immediately after the ``verify`` entry, and each set
   ``EXPECTED_CI_RUN_STEPS = 9``; the two modules' constants agree.
7. Row ``| 161 |`` is gone from ``ROADMAP.md`` and one ``- **#161 -- `` bullet
   carrying its pre-ship index text is in ``ROADMAP_ARCHIVE.md``.
8. ``ROADMAP.md``'s Done ledger carries exactly one ``- #161 `` record, <= 120
   chars, citing ``(foundry iter 264)``, adjacent to ``#261``.
9. ``ROADMAP.md`` fits the EFFECTIVE ceiling -- the 40,000 char limit composed
   with the 4,000-char headroom floor, both imported from the live guards
   rather than hardcoded -- and no row #161 text remains to be relocated.
"""

from __future__ import annotations

import ast
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Final

import pytest

from tests.test_iter214_behavior import MIN_HEADROOM
from tests.test_roadmap_size_budget import ROADMAP_CHAR_LIMIT

REPO_ROOT: Final[Path] = Path(__file__).resolve().parent.parent

#: The one command this iteration exists to add, spelled ONCE so behaviors 1, 2,
#: 3 and 6 all compare against the same literal and cannot drift apart.
ROUND_TRIP_STEP: Final[str] = (
    "uv run pla signals --workspace examples/fixture_workspace "
    "--baseline .pla_runs/snapshot.json --fail-over 0"
)

#: The step the round trip must follow (the produce half's existing consumer).
VERIFY_STEP_MARK: Final[str] = "pla verify --slate"

#: The two steps the round trip must precede -- the repo self-scan stays last.
SELF_SCAN_MARKS: Final[tuple[str, ...]] = (
    "--workspace . --collector notes",
    "--workspace . --fail-on-kind merge_conflict",
)

#: The six published identity keys a ``--baseline`` subtraction is defined over
#: (``pla signals --help``, and the same tuple ``test_iter138_behavior.py`` uses).
IDENTITY_KEYS: Final[tuple[str, ...]] = (
    "source",
    "kind",
    "summary",
    "detail",
    "path",
    "weight",
)

#: The effective ROADMAP.md ceiling, COMPOSED from the two live guards rather
#: than hardcoded as 36,000: a scout measured that a reader who knows only the
#: 40,000 literal believes there are 4,572 chars of room when there are 572.
EFFECTIVE_ROADMAP_LIMIT: Final[int] = ROADMAP_CHAR_LIMIT - MIN_HEADROOM


# ======================================================================================
# Helpers -- tracked documents
# ======================================================================================


def _read(relative: str) -> str:
    path = REPO_ROOT / relative
    assert path.is_file(), f"expected a tracked file at {relative}"
    return path.read_text(encoding="utf-8")


def _check_recipe_lines() -> list[str]:
    """The tab-indented recipe lines of the ``check`` target, in order."""
    lines = _read("Makefile").splitlines()
    start = next(
        (i for i, line in enumerate(lines) if line.startswith("check:")),
        None,
    )
    assert start is not None, "Makefile must define a `check` target"
    recipe: list[str] = []
    for line in lines[start + 1 :]:
        if line.startswith("\t"):
            recipe.append(line.lstrip("\t").strip())
        elif line.strip() == "":
            break
        else:
            break
    assert recipe, "the `check` target must have a recipe"
    return recipe


def _ci_run_commands() -> list[str]:
    """Every one-line ``run:`` command in ci.yml, in file order."""
    commands: list[str] = []
    for line in _read(".github/workflows/ci.yml").splitlines():
        stripped = line.strip()
        if stripped.startswith("run:") and stripped != "run: |":
            commands.append(stripped[len("run:") :].strip())
    assert commands, "ci.yml must expose one-line `run:` steps"
    return commands


def _ci_run_step_count() -> int:
    r"""Count graded ``run:`` steps the way the SHIPPED oracle counts them.

    ``test_iter102_behavior.py::test_b4`` uses ``re.findall(r"^\s*run:", text,
    re.MULTILINE)``, which counts the one ``run: |`` block as a single graded
    step even though it holds two gate commands. That is why
    ``EXPECTED_CI_RUN_STEPS`` (9) is one less than ``len(CI_GATE_STEPS)`` (10).
    Re-deriving the count with a narrower rule that skips ``run: |`` reports 8
    and falsely accuses a correct workflow -- measured while writing this module.
    """
    text = _read(".github/workflows/ci.yml")
    return len(re.findall(r"^\s*run:", text, re.MULTILINE))


def _module_constant(relative: str, name: str) -> Any:
    """Read a module-level literal constant WITHOUT importing the module."""
    tree = ast.parse(_read(relative))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            target = node.targets[0]
        elif isinstance(node, ast.AnnAssign):
            target = node.target
        else:
            continue
        if getattr(target, "id", None) == name:
            return ast.literal_eval(node.value)
    raise AssertionError(f"{relative} must define a module-level {name}")


def _ledger_rows() -> list[str]:
    return [
        line
        for line in _read("ROADMAP.md").splitlines()
        if re.match(r"^- #\d+ ", line)
    ]


# ======================================================================================
# Helpers -- running the shipped console script (offline, scripted provider)
# ======================================================================================


def _console_script() -> Path:
    bindir = Path(sys.executable).parent
    candidates = [bindir / "pla", bindir / "pla.exe"]
    which = shutil.which("pla")
    if which:
        candidates.append(Path(which))
    script = next((c for c in candidates if c.is_file()), None)
    assert script is not None, "the `pla` console script must be installed"
    return script


def _pla(*args: str) -> subprocess.CompletedProcess[str]:
    """Run ``pla`` from the repo root, which is where both gates run it."""
    return subprocess.run(
        [str(_console_script()), *args],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=300,
    )


def _identity(record: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(record.get(key) for key in IDENTITY_KEYS)


@pytest.fixture(scope="module")
def round_trip(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """Reproduce the gate's two halves with tmp_path standing in for .pla_runs.

    The PRODUCE half is ``make demo``'s own invocation with ``--state-dir`` and
    ``--snapshot`` redirected into a throwaway dir; the CONSUME half is the exact
    new gate step with the same redirection. Nothing is written inside the
    workspace being scanned, which is the property that makes
    ``--workspace examples/fixture_workspace`` (and never ``--workspace .``)
    correct for this gate.
    """
    tmp = tmp_path_factory.mktemp("iter241_round_trip")
    snapshot = tmp / "snapshot.json"
    produce = _pla(
        "run",
        "--workspace",
        "examples/fixture_workspace",
        "--provider",
        "scripted",
        "--scripted-responses",
        "examples/scripted_responses.json",
        "--state-dir",
        str(tmp / "state"),
        "--snapshot",
        str(snapshot),
        "--json",
    )
    assert produce.returncode == 0, (
        f"the produce half must succeed offline; exit {produce.returncode}, "
        f"stderr={produce.stderr!r}"
    )
    assert snapshot.is_file(), "the produce half must write the snapshot document"
    recorded = json.loads(snapshot.read_text(encoding="utf-8"))["signals"]

    control = _pla(
        "signals", "--workspace", "examples/fixture_workspace", "--json"
    )
    assert control.returncode == 0, f"control arm stderr={control.stderr!r}"
    perceived = json.loads(control.stdout)["signals"]

    return {
        "tmp": tmp,
        "snapshot": snapshot,
        "recorded": recorded,
        "perceived": perceived,
    }


# ======================================================================================
# Behavior 1 -- the local gate carries the step
# ======================================================================================


def test_b01_makefile_check_recipe_carries_the_round_trip_step_once() -> None:
    recipe = _check_recipe_lines()
    hits = [line for line in recipe if line == ROUND_TRIP_STEP]
    assert len(hits) == 1, (
        "`make check` must carry the same-run --baseline round trip exactly "
        f"once, verbatim:\n  {ROUND_TRIP_STEP}\nrecipe was:\n"
        + "\n".join(f"  {line}" for line in recipe)
    )


def test_b01b_the_round_trip_never_scopes_itself_at_the_repo_root() -> None:
    """The gate writes .pla_runs/ into the root between produce and consume, so a
    root-scoped round trip would perceive its own artifacts as new signals."""
    assert "--workspace examples/fixture_workspace" in ROUND_TRIP_STEP
    for surface, commands in (
        ("Makefile check", _check_recipe_lines()),
        ("ci.yml", _ci_run_commands()),
    ):
        for command in commands:
            if "--baseline" in command:
                assert "--workspace ." not in command, (
                    f"{surface}: a --baseline step must not be scoped at the "
                    f"repo root; the gate's own .pla_runs/ writes would churn "
                    f"it. Offending step: {command}"
                )


# ======================================================================================
# Behavior 2 -- ci.yml carries the SAME string, byte-identically
# ======================================================================================


def test_b02_ci_carries_the_identical_step_exactly_once() -> None:
    commands = _ci_run_commands()
    hits = [command for command in commands if command == ROUND_TRIP_STEP]
    assert len(hits) == 1, (
        "ci.yml must carry the round trip exactly once, byte-identically with "
        f"`make check`:\n  {ROUND_TRIP_STEP}\nrun: steps were:\n"
        + "\n".join(f"  {command}" for command in commands)
    )


def test_b02b_the_two_sites_are_byte_identical_not_merely_similar() -> None:
    from_make = next(
        line for line in _check_recipe_lines() if "--baseline" in line
    )
    from_ci = next(
        command for command in _ci_run_commands() if "--baseline" in command
    )
    assert from_make == from_ci == ROUND_TRIP_STEP, (
        "the local gate and CI must spell the round trip identically; "
        f"Makefile={from_make!r} ci.yml={from_ci!r}"
    )


# ======================================================================================
# Behavior 3 -- placement: after verify, before both --workspace . self-scans
# ======================================================================================


def _sole_index(commands: list[str], mark: str, surface: str) -> int:
    matches = [i for i, command in enumerate(commands) if mark in command]
    assert len(matches) == 1, (
        f"{surface}: {mark!r} must identify exactly one step, found "
        f"{len(matches)}: {[commands[i] for i in matches]}"
    )
    return matches[0]


@pytest.mark.parametrize(
    "surface",
    ["Makefile check recipe", "ci.yml run steps"],
)
def test_b03_round_trip_sits_after_verify_and_before_both_self_scans(
    surface: str,
) -> None:
    commands = (
        _check_recipe_lines()
        if surface.startswith("Makefile")
        else _ci_run_commands()
    )
    round_trip_at = _sole_index(commands, ROUND_TRIP_STEP, surface)
    verify_at = _sole_index(commands, VERIFY_STEP_MARK, surface)
    assert verify_at < round_trip_at, (
        f"{surface}: the round trip must run AFTER `pla verify "
        f"--fail-on-unresolved` (verify at {verify_at}, round trip at "
        f"{round_trip_at})"
    )
    for mark in SELF_SCAN_MARKS:
        scan_at = _sole_index(commands, mark, surface)
        assert round_trip_at < scan_at, (
            f"{surface}: the repo self-scan must stay the final graded step, so "
            f"the round trip must precede {mark!r} (round trip at "
            f"{round_trip_at}, scan at {scan_at})"
        )


# ======================================================================================
# Behavior 4 -- the green arm, and it is not vacuous
# ======================================================================================


def test_b04_control_arm_proves_the_fixture_workspace_emits_signals(
    round_trip: dict[str, Any],
) -> None:
    """Non-vacuousness: without a baseline the same command perceives signals, so
    the green arm below is a real subtraction and not a silent collector."""
    assert len(round_trip["perceived"]) > 0, (
        "fixture precondition: `pla signals --workspace "
        "examples/fixture_workspace` must emit at least one signal, or an empty "
        "residual proves nothing"
    )
    assert len(round_trip["recorded"]) > 0, (
        "the produce half must record at least one signal in its snapshot"
    )


def test_b04_same_run_baseline_leaves_zero_residual_and_exits_zero(
    round_trip: dict[str, Any],
) -> None:
    result = _pla(
        "signals",
        "--workspace",
        "examples/fixture_workspace",
        "--baseline",
        str(round_trip["snapshot"]),
        "--fail-over",
        "0",
    )
    assert result.returncode == 0, (
        "the same-run round trip must exit 0; exit "
        f"{result.returncode}, stdout={result.stdout!r}, "
        f"stderr={result.stderr!r}"
    )
    assert result.stdout == "(no signals collected)\n", (
        f"the residual must be empty; stdout={result.stdout!r}"
    )
    assert "fail-over tripped" not in result.stderr, (
        f"the green arm must not trip the gate; stderr={result.stderr!r}"
    )


def test_b04b_produce_and_consume_agree_on_the_wire_contract_both_ways(
    round_trip: dict[str, Any],
) -> None:
    """The stated PURPOSE of the gate (pm.md "## Why"): a non-empty residual
    means --snapshot and --baseline have stopped agreeing over the six published
    identity keys. Asserted MUTUALLY -- a one-way check would pass if the
    snapshot recorded a strict superset, which is subsumption, not agreement."""
    recorded = {_identity(record) for record in round_trip["recorded"]}
    perceived = {_identity(record) for record in round_trip["perceived"]}
    assert perceived - recorded == set(), (
        "signals the consume half perceived but the produce half never "
        f"recorded: {sorted(perceived - recorded)}"
    )
    assert recorded - perceived == set(), (
        "signals the produce half recorded but the consume half cannot "
        f"perceive: {sorted(recorded - perceived)}"
    )


def test_b04c_no_identity_key_carries_a_timestamp_or_an_age(
    round_trip: dict[str, Any],
) -> None:
    """Why the round trip cannot churn between produce and consume: none of the
    six identity keys is a clock reading. Asserted structurally (the key SET is
    exactly the six published names) rather than by sleeping."""
    for record in round_trip["recorded"]:
        assert set(record.keys()) == set(IDENTITY_KEYS), (
            "a snapshot signal object must carry exactly the six published "
            f"identity keys, got {sorted(record.keys())}"
        )


# ======================================================================================
# Behavior 5 -- the FIRE arm: the gate is proven to fire, not merely proven green
# ======================================================================================


def test_b05_deleting_one_live_signal_from_the_baseline_trips_the_budget(
    round_trip: dict[str, Any],
) -> None:
    perceived = round_trip["perceived"]
    assert perceived, "fixture precondition: the workspace must emit signals"
    target = _identity(perceived[0])
    snapshot = json.loads(
        Path(round_trip["snapshot"]).read_text(encoding="utf-8")
    )
    kept = [
        record
        for record in snapshot["signals"]
        if _identity(record) != target
    ]
    assert len(snapshot["signals"]) - len(kept) == 1, (
        "the fire fixture must remove exactly one baseline entry, removed "
        f"{len(snapshot['signals']) - len(kept)}"
    )
    holed = Path(round_trip["tmp"]) / "baseline_missing_one.json"
    holed.write_text(
        json.dumps({"workspace_root": snapshot["workspace_root"], "signals": kept}),
        encoding="utf-8",
    )

    result = _pla(
        "signals",
        "--workspace",
        "examples/fixture_workspace",
        "--baseline",
        str(holed),
        "--fail-over",
        "0",
    )
    assert result.returncode == 5, (
        "one unrecorded signal must trip the --fail-over 0 budget with exit 5; "
        f"exit {result.returncode}, stdout={result.stdout!r}, "
        f"stderr={result.stderr!r}"
    )
    assert "count=1" in result.stderr, (
        f"the gate line must name the count; stderr={result.stderr!r}"
    )
    assert "budget=0" in result.stderr, (
        f"the gate line must name the budget; stderr={result.stderr!r}"
    )
    assert "gate: fail-over tripped" in result.stderr, (
        f"the gate line must be recognisable; stderr={result.stderr!r}"
    )


# ======================================================================================
# Behavior 6 -- both gate-parity modules carry the step at index 7
# ======================================================================================


_GATE_PARITY_MODULES: Final[tuple[str, ...]] = (
    "tests/test_iter102_behavior.py",
    "tests/test_iter110_behavior.py",
)


@pytest.mark.parametrize("module", _GATE_PARITY_MODULES)
def test_b06_gate_parity_module_carries_the_step_at_index_seven(
    module: str,
) -> None:
    steps = list(_module_constant(module, "CI_GATE_STEPS"))
    assert steps[7] == ROUND_TRIP_STEP, (
        f"{module}: CI_GATE_STEPS[7] must be the round trip, got {steps[7]!r}"
    )
    assert VERIFY_STEP_MARK in steps[6], (
        f"{module}: the round trip must sit immediately after the verify entry, "
        f"but CI_GATE_STEPS[6] is {steps[6]!r}"
    )
    assert "--fail-over 9" in steps[8], (
        f"{module}: the --fail-over 9 self-scan must follow the round trip, but "
        f"CI_GATE_STEPS[8] is {steps[8]!r}"
    )
    assert _module_constant(module, "EXPECTED_CI_RUN_STEPS") == 9, (
        f"{module}: EXPECTED_CI_RUN_STEPS must be 9 now that ci.yml exposes a "
        "ninth one-line run: step"
    )


def test_b06b_the_two_gate_parity_modules_do_not_diverge() -> None:
    """The two modules hold DUPLICATE copies of both constants, so editing one
    alone is exactly the two-site drift this iteration's step is guarding."""
    first, second = _GATE_PARITY_MODULES
    assert list(_module_constant(first, "CI_GATE_STEPS")) == list(
        _module_constant(second, "CI_GATE_STEPS")
    ), f"{first} and {second} must hold identical CI_GATE_STEPS"
    assert _module_constant(first, "EXPECTED_CI_RUN_STEPS") == _module_constant(
        second, "EXPECTED_CI_RUN_STEPS"
    ), f"{first} and {second} must hold identical EXPECTED_CI_RUN_STEPS"


def test_b06c_expected_ci_run_steps_matches_the_live_workflow() -> None:
    """The constant is only worth 9 if ci.yml really exposes 9 one-line steps --
    a gate proven green but never proven to match the artifact is fail-open."""
    assert _ci_run_step_count() == _module_constant(
        _GATE_PARITY_MODULES[0], "EXPECTED_CI_RUN_STEPS"
    ), (
        "EXPECTED_CI_RUN_STEPS must equal the number of graded `run:` steps in "
        f"ci.yml counted the shipped oracle's way, which is "
        f"{_ci_run_step_count()}"
    )
    # And the ONE-LINE commands are one fewer, because the two demo-artifact
    # assertions share a single `run: |` block. Pinning the relationship stops a
    # future reader "fixing" the constant to match a narrower extractor.
    assert len(_ci_run_commands()) == _ci_run_step_count() - 1, (
        f"ci.yml must hold exactly one `run: |` block step; one-line steps="
        f"{len(_ci_run_commands())} total run: steps={_ci_run_step_count()}"
    )


# ======================================================================================
# Behavior 7 -- row #161 is archived, then dropped
# ======================================================================================


def test_b07_row_161_is_gone_from_the_live_index() -> None:
    roadmap = _read("ROADMAP.md")
    assert "| 161 |" not in roadmap, (
        "row #161 must be dropped from ROADMAP.md's index -- it shipped this "
        "iteration"
    )


def test_b07b_row_161_pre_ship_text_survives_in_the_archive() -> None:
    archive = _read("ROADMAP_ARCHIVE.md")
    bullets = [
        line
        for line in archive.splitlines()
        if line.startswith("- **#161 -- ")
    ]
    assert len(bullets) == 1, (
        f"ROADMAP_ARCHIVE.md must carry exactly one `- **#161 -- ` retirement "
        f"bullet, found {len(bullets)}"
    )
    bullet = bullets[0]
    # Distinctive fragments of the row's PRE-SHIP index text. Chosen because
    # each is load-bearing: the proposal, the two rejected per-kind arms, and
    # the blocking objection the round trip retires rather than pays.
    for fragment in (
        "Give `--baseline` its first consumer",
        "the ratchet shipped as row #150 and nothing consults it",
        "only `ci_config` is safely armable",
        "`test_posture` churns BY CONSTRUCTION",
        "`lockfile_drift` is mtime-driven",
        "Needs a stated refresh rule or the committed snapshot rots into a blindfold",
    ):
        assert fragment in bullet, (
            "the retirement bullet must carry row #161's verbatim pre-ship "
            f"text; missing fragment: {fragment!r}"
        )


def test_b07c_the_archive_bullet_cannot_be_parsed_as_a_table_row() -> None:
    """The archive's shipped convention: pipes are replaced by field labels, so a
    retired row can never be re-counted as a live index row."""
    bullet = next(
        line
        for line in _read("ROADMAP_ARCHIVE.md").splitlines()
        if line.startswith("- **#161 -- ")
    )
    assert "| 161 |" not in bullet, (
        "the retirement bullet must not reintroduce a parseable `| 161 |` row"
    )


# ======================================================================================
# Behavior 8 -- the ship record, pinned by identity and adjacency (see docstring)
# ======================================================================================


def test_b08_one_ledger_record_for_161_citing_the_measured_commit_tag() -> None:
    rows = [row for row in _ledger_rows() if row.startswith("- #161 ")]
    assert len(rows) == 1, (
        f"ROADMAP.md's Done ledger must carry exactly one `- #161 ` record, "
        f"found {len(rows)}: {rows}"
    )
    row = rows[0]
    assert row.endswith("(foundry iter 264)"), (
        "the ship record must cite the commit tag the PM measured against the "
        f"pending bound (263 -> 264), got: {row!r}"
    )
    assert len(row) <= 120, (
        f"the ledger record must be <= 120 chars, is {len(row)}: {row!r}"
    )
    assert "--baseline" in row, (
        f"the ship record must name what shipped, got: {row!r}"
    )


def test_b08b_the_161_record_is_adjacent_to_the_previous_ship() -> None:
    """ADJACENCY, not position: #161 must directly follow #261, the last ship
    before it. This survives every future append, unlike pinning the tail."""
    numbers = [int(re.match(r"^- #(\d+) ", row).group(1)) for row in _ledger_rows()]
    assert 161 in numbers, "the #161 ship record must be in the ledger"
    assert 261 in numbers, "the #261 ship record must still be in the ledger"
    assert numbers.index(161) == numbers.index(261) + 1, (
        "the #161 record must be appended directly after #261, so the ledger "
        f"stays in ship order; tail was {numbers[-4:]}"
    )


def test_b08c_no_existing_ship_record_was_dropped() -> None:
    """The ledger is append-only: this iteration adds one row and removes none."""
    numbers = [int(re.match(r"^- #(\d+) ", row).group(1)) for row in _ledger_rows()]
    assert len(numbers) == len(set(numbers)), (
        f"no ship number may appear twice in the ledger; got {numbers}"
    )
    for previously_shipped in (168, 215, 260, 261):
        assert previously_shipped in numbers, (
            f"ship record #{previously_shipped} must survive this iteration's "
            "append"
        )


# ======================================================================================
# Behavior 9 -- the effective ROADMAP.md budget, composed from the live guards
# ======================================================================================


def test_b09_roadmap_fits_the_effective_ceiling_not_just_the_literal_cap() -> None:
    chars = len(_read("ROADMAP.md"))
    assert chars <= EFFECTIVE_ROADMAP_LIMIT, (
        f"ROADMAP.md is {chars} chars; the EFFECTIVE ceiling is "
        f"{EFFECTIVE_ROADMAP_LIMIT} = {ROADMAP_CHAR_LIMIT} (test_roadmap_size_"
        f"budget) - {MIN_HEADROOM} (test_iter214 headroom floor). Reading only "
        "the 40,000 literal is what mispriced iters 261-263 by a factor of eight"
    )


def test_b09b_the_effective_ceiling_is_composed_from_both_live_guards() -> None:
    """Guard the composition itself: if either constant moves, this module's
    ceiling moves with it instead of silently pinning a stale 36,000."""
    assert ROADMAP_CHAR_LIMIT == 40_000
    assert MIN_HEADROOM == 4_000
    assert EFFECTIVE_ROADMAP_LIMIT == 36_000


def test_b09c_retiring_the_row_bought_headroom_rather_than_spending_it() -> None:
    """The PM's stated reason for choosing this candidate over scout A's: the
    825-char row leaves and a <=120-char ledger line arrives, so the file must
    now sit further under the ceiling than the 35,428 chars it stood at."""
    chars = len(_read("ROADMAP.md"))
    assert chars < 35_428, (
        f"ROADMAP.md is {chars} chars; retiring row #161 must leave it smaller "
        "than the 35,428 chars measured before this change"
    )
