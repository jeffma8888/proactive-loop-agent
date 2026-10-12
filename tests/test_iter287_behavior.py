"""Black-box oracle for foundry iteration 327 (state-dir iteration 475, ROADMAP #306):
``make check`` and CI gain a SLATE-level determinism gate -- re-scan the fixture workspace
into ``.pla_runs/rescan`` and ``pla diff --fail-on-change`` it against the demo slate --
written by the tester from the spec alone (pm.md ``## Expected Behaviors``), the repo's own
``tests/`` tree, README.md, ROADMAP.md, and the two gate artifacts the behaviors grade
(``Makefile``, ``.github/workflows/ci.yml``), plus the product's CLI by RUNNING it.

WHY THIS MODULE EXISTS. ``diff --fail-on-change`` shipped in foundry iter 319 with README and
SPEC prose calling it "the channel a pre-commit hook or a CI step branches on", and nothing
outside ``tests/`` branched on it. This ship gives it its first executable consumer, so
"deterministic" is now proven at the slate level on every push (the ``--baseline`` round trip
proves it only at the signal level).

WHAT THIS MODULE GRADES (ONE collected item -- the tree sat at exactly
``tests/test_iter263_behavior.py::MIN_BINDING_HEADROOM`` when this landed, so every extra
``def test_`` costs a retirement elsewhere; the assertions live INSIDE the body as ``_bN_``
helpers named for the spec behavior they encode, never as extra items):
(1) the TREE -- behaviors 1-4 and 6-9. The ``check`` recipe holds the two new
lines in the pinned slot with the self-scan still LAST and every other line unchanged; ci.yml
exposes exactly 10 graded ``run:`` steps, the new ``run: |`` block is byte-identical to the
recipe lines and sits between ``--fail-over 9`` and the self-scan under a ``name:`` and a
comment; both ``CI_GATE_STEPS`` tuples hold 12 entries with the two new ones at indices 9-10;
every step-count constant site reads 10 / 12 and the stale "exceeds by one" wording is gone;
README gains the bold-led paragraph (below the human-owned marker, before the "Three more
developer entry points" line, with the two commands in a bash block); the Makefile comment
block says ten / twenty / 20; ROADMAP holds exactly one verbatim ``- #306`` row directly
after ``- #305`` as the ledger's last row; and this module is self-shaped (ONE item, every
spawn timed, no size bound on ROADMAP.md).
(2) the GATE, executed -- behavior 5. In a tmp copy of the fixture, ``pla run``
produces the demo slate the way ``make demo`` does, then the two gate commands run via the
console script: both exit 0, the diff prints ``(no differences)``, ``rescan/slate.json``
exists, ``pla runs`` does not list ``rescan``; and the NEGATIVE control -- one goal popped
from the re-scan -- exits 5 WITH the flag and 0 WITHOUT it, so exit 0 is not vacuous.

ISOLATION CONTRACT (honored). No file under ``src/`` was read; no engineer/reviewer notes;
no ``git diff``. The recipe/ci.yml/tuple/constant expectations are pm.md's text.

Offline and deterministic: the only children are the installed ``pla`` console script
(``tests/test_iter158_behavior.py::_console_script``), every spawn carries ``timeout=``.
"""

from __future__ import annotations

import ast
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Final

from tests.test_iter102_behavior import CI_GATE_STEPS as GATE_102
from tests.test_iter110_behavior import CI_GATE_STEPS as GATE_110
from tests.test_iter158_behavior import _console_script
from tests.test_iter172_behavior import roadmap_size_bounds
from tests.test_iter241_behavior import _module_constant

REPO = Path(__file__).resolve().parents[1]
MAKEFILE = REPO / "Makefile"
CI_YML = REPO / ".github" / "workflows" / "ci.yml"
README = REPO / "README.md"
ROADMAP = REPO / "ROADMAP.md"
FIXTURE = REPO / "examples" / "fixture_workspace"
SCRIPTED = REPO / "examples" / "scripted_responses.json"

#: Behavior 1/2/3: the two gate commands, spelled ONCE. The recipe and ci.yml carry the
#: scan WITH ``> /dev/null``; the CI_GATE_STEPS tuples carry it WITHOUT (iter-110 identity).
RESCAN_BARE: Final = (
    "uv run pla scan --workspace examples/fixture_workspace --provider scripted "
    "--scripted-responses examples/scripted_responses.json --state-dir .pla_runs/rescan"
)
RESCAN_LINE: Final = RESCAN_BARE + " > /dev/null"
DIFF_LINE: Final = (
    "uv run pla diff --old .pla_runs/slate.json --new .pla_runs/rescan/slate.json "
    "--fail-on-change"
)
COUNT_BUDGET_LINE: Final = (
    "uv run pla signals --workspace . --collector notes --collector ci_config "
    "--collector dependencies --collector test_posture --fail-over 9"
)
SELF_SCAN_LINE: Final = (
    "uv run pla signals --workspace . --fail-on-kind merge_conflict "
    "--fail-on-kind syntax_error --fail-on-kind secret_file --fail-on-kind broken_link"
)
#: Behavior 1: the whole ``check`` recipe after this ship, in order.
EXPECTED_CHECK_RECIPE: Final = (
    "rm -rf .pla_runs",
    "uv sync --locked",
    "uv run pytest",
    "uv run mypy src/proactive_loop examples/check_run.py examples/check_autonomy.py",
    "$(MAKE) demo",
    "test -f .pla_runs/slate.json",
    "ls .pla_runs/run-*/artifacts/*.md > /dev/null",
    "uv run pla verify --slate .pla_runs/slate.json --snapshot .pla_runs/snapshot.json "
    "--fail-on-unresolved",
    "uv run pla signals --workspace examples/fixture_workspace "
    "--baseline .pla_runs/snapshot.json --fail-over 0",
    COUNT_BUDGET_LINE,
    RESCAN_LINE,
    DIFF_LINE,
    SELF_SCAN_LINE,
)
#: Behavior 2/4: graded ``run:`` steps and gate-tuple size after this ship.
EXPECTED_CI_RUN_STEPS: Final = 10
EXPECTED_GATE_ENTRIES: Final = 12
RESCAN_INDEX: Final = 9  # after ``--fail-over 9`` (index 8), before the self-scan (last)
#: Behavior 4: every step-count constant site, (module, name, value).
CONSTANT_SITES: Final = (
    ("tests/test_iter102_behavior.py", "EXPECTED_CI_RUN_STEPS", 10),
    ("tests/test_iter110_behavior.py", "EXPECTED_CI_RUN_STEPS", 10),
    ("tests/test_iter128_behavior.py", "EXPECTED_CI_RUN_STEPS", 10),
    ("tests/test_iter128_behavior.py", "EXPECTED_TOTAL_GATE_STEPS", 12),
    ("tests/test_iter186_behavior.py", "EXPECTED_RUN_STEPS", 10),
)
#: Behavior 6/8: README and ROADMAP records.
README_MARKER: Final = "PORTFOLIO INTRO"  # the marker line spells the dash as U+2014
README_ANCHOR: Final = "Three more developer entry points exist, "
LEDGER_ROW: Final = (
    "- #306 make check + CI re-scan the fixture, diff --fail-on-change vs demo slate: "
    "determinism gate (foundry iter 327)"
)
PREVIOUS_ROW_PREFIX: Final = "- #305 "
COLLECTED_ITEMS: Final = 1


def _check_recipe_lines() -> list[str]:
    """Tab-indented recipe lines of the ``check`` target, in order (tabs stripped)."""
    lines = MAKEFILE.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("check:"))
    recipe: list[str] = []
    for line in lines[start + 1 :]:
        if not line.startswith("\t"):
            break
        recipe.append(line.lstrip("\t").rstrip())
    return recipe


def _b1_makefile_recipe() -> None:
    recipe = _check_recipe_lines()
    assert recipe == list(EXPECTED_CHECK_RECIPE), (
        "behavior 1: the `check` recipe must be the 11 pre-existing lines plus the "
        f"re-scan and diff lines in the pinned slot, self-scan LAST; got {recipe}"
    )
    assert recipe.index(RESCAN_LINE) == recipe.index(COUNT_BUDGET_LINE) + 1
    assert recipe.index(DIFF_LINE) == recipe.index(RESCAN_LINE) + 1
    assert recipe.index(SELF_SCAN_LINE) == recipe.index(DIFF_LINE) + 1 == len(recipe) - 1
    assert recipe.count(RESCAN_LINE) == recipe.count(DIFF_LINE) == 1


def _b2_ci_yml_step() -> None:
    text = CI_YML.read_text(encoding="utf-8")
    assert len(re.findall(r"^\s*run:", text, re.M)) == EXPECTED_CI_RUN_STEPS, (
        "behavior 2: ci.yml must expose exactly 10 graded `run:` steps"
    )
    lines = text.splitlines()
    blocks = [i for i, line in enumerate(lines) if line.strip() == "run: |"]
    assert len(blocks) == 2, f"behavior 2: exactly two `run: |` blocks expected, at {blocks}"
    new_block = blocks[1]
    assert lines[new_block + 1].strip() == RESCAN_LINE, lines[new_block + 1]
    assert lines[new_block + 2].strip() == DIFF_LINE, lines[new_block + 2]
    assert lines[new_block + 3].strip() == "", "behavior 2: the block holds exactly two lines"
    name_line = lines[new_block - 1].strip()
    assert name_line.startswith("- name:") and len(name_line) > len("- name: "), name_line
    # a short explanatory comment directly precedes the step (mirrors the artifact step)
    above = [ln.strip() for ln in lines[max(0, new_block - 12) : new_block - 1]]
    assert any(ln.startswith("#") and "fail-on-change" in ln for ln in above), above
    # slot: after the ``--fail-over 9`` step and before the self-scan step
    budget_at = next(i for i, ln in enumerate(lines) if ln.strip() == "run: " + COUNT_BUDGET_LINE)
    scan_at = next(i for i, ln in enumerate(lines) if ln.strip() == "run: " + SELF_SCAN_LINE)
    assert budget_at < new_block < scan_at, (budget_at, new_block, scan_at)
    assert scan_at == max(i for i, ln in enumerate(lines) if ln.strip().startswith("run:"))


def _b3_gate_tuples() -> None:
    for name, steps in (("test_iter102", GATE_102), ("test_iter110", GATE_110)):
        assert len(steps) == EXPECTED_GATE_ENTRIES, f"behavior 3: {name} len={len(steps)}"
        assert steps[RESCAN_INDEX - 1] == COUNT_BUDGET_LINE, f"{name}[8] is not --fail-over 9"
        assert steps[RESCAN_INDEX] == RESCAN_BARE, f"{name}[9] must be the bare re-scan"
        assert steps[RESCAN_INDEX + 1] == DIFF_LINE, f"{name}[10] must be the diff gate"
        assert steps[-1] == SELF_SCAN_LINE, f"{name}: self-scan must stay LAST"
        assert not any(step.endswith("/dev/null") for step in steps), name
    assert GATE_102 == GATE_110, "behavior 3: the two drift guards must agree entry-for-entry"


def _b4_constant_sites() -> None:
    for relative, name, value in CONSTANT_SITES:
        got = _module_constant(relative, name)
        assert got == value, f"behavior 4: {relative}::{name} == {got}, expected {value}"
    t198 = (REPO / "tests/test_iter198_behavior.py").read_text(encoding="utf-8")
    assert "assert C102 == C110 == 10" in t198 and "== 9," not in t198, "behavior 4: test_iter198"
    t241 = (REPO / "tests/test_iter241_behavior.py").read_text(encoding="utf-8")
    assert '_module_constant(module, "EXPECTED_CI_RUN_STEPS") == 10' in t241, "behavior 4: 241"
    assert "EXPECTED_CI_RUN_STEPS must be 10" in t241 and "must be 9" not in t241
    t128 = (REPO / "tests/test_iter128_behavior.py").read_text(encoding="utf-8")
    assert "exceeds by one" not in t128 and "share one `run: |` block" not in t128
    assert "two `run: |` blocks" in t128, "behavior 4: the 128 comment names both blocks"


def _b6_readme_paragraph() -> None:
    text = README.read_text(encoding="utf-8")
    marker_at = text.index(README_MARKER)
    anchor_at = text.index(README_ANCHOR)
    para_at = text.index("**Both graded gates also prove slate-level determinism.**")
    assert marker_at < para_at < anchor_at, "behavior 6: paragraph below marker, before anchor"
    between = text[para_at:anchor_at]
    assert "diff --fail-on-change" in between and re.search(r"exits? 5", between), between
    assert between.count("```bash\n" + RESCAN_BARE + "\n" + DIFF_LINE + "\n```") == 1, between
    assert between.strip().endswith("```"), "behavior 6: the bash block ends the paragraph"
    assert text.count(README_ANCHOR) == 1 and text.count("**Both graded gates also") == 1


def _b7_makefile_comment_words() -> None:
    lines = MAKEFILE.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("check:"))
    block: list[str] = []
    for line in reversed(lines[:start]):
        if not line.startswith("#"):
            break
        block.insert(0, line)
    joined = "\n".join(block)
    assert "grades ten run-steps" in joined, "behavior 7: `ten run-steps`"
    assert "those ten steps TWICE -- twenty run-steps" in joined, "behavior 7: `twenty`"
    assert "12 of CI's 20" in joined and "rather than all 20" in joined, "behavior 7: `20`"
    for stale in ("eight run-steps", "sixteen", "of CI's 16", "all 16", "nine run-steps"):
        assert stale not in joined, f"behavior 7: stale count word {stale!r} survives"


def _b8_roadmap_row() -> None:
    lines = ROADMAP.read_text(encoding="utf-8").splitlines()
    assert lines.count(LEDGER_ROW) == 1, "behavior 8: exactly one verbatim #306 row"
    at = lines.index(LEDGER_ROW)
    assert lines[at - 1].startswith(PREVIOUS_ROW_PREFIX), "behavior 8: appended after #305"
    ledger = [i for i, line in enumerate(lines) if re.match(r"^- #\d+ ", line)]
    assert at in ledger, "behavior 8: #306 row is among the ledger rows"
    assert sum(1 for line in lines if "#306" in line) == 1, "behavior 8: #306 appears once"
    assert len(LEDGER_ROW) <= 120


def _b9_self_shape() -> None:
    own = Path(__file__).read_text(encoding="utf-8")
    tree = ast.parse(own)
    items = [n.name for n in tree.body if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")]
    assert len(items) == COLLECTED_ITEMS, items
    spawns = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "run"
        and isinstance(n.func.value, ast.Name) and n.func.value.id == "subprocess"
    ]
    assert spawns and all(any(k.arg == "timeout" for k in c.keywords) for c in spawns), "untimed spawn"
    assert roadmap_size_bounds(own) == (), roadmap_size_bounds(own)
    assert Path(__file__).name == "test_iter287_behavior.py"


def _pla(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(_console_script()), *args], cwd=str(cwd), capture_output=True, text=True, timeout=120
    )


def _b5_gate_executes_exit_0_no_differences_and_the_negative_control_exits_5(
    tmp_path: Path,
) -> None:
    shutil.copytree(FIXTURE, tmp_path / "examples" / "fixture_workspace")
    shutil.copy(SCRIPTED, tmp_path / "examples" / "scripted_responses.json")
    (tmp_path / ".pla_runs").mkdir()
    common = ("--provider", "scripted", "--scripted-responses", "examples/scripted_responses.json")
    demo = _pla(
        "run", "--workspace", "examples/fixture_workspace", *common, "--state-dir", ".pla_runs",
        "--snapshot", ".pla_runs/snapshot.json", "--json", cwd=tmp_path,
    )
    assert demo.returncode == 0 and (tmp_path / ".pla_runs" / "slate.json").is_file(), demo.stderr
    # behavior 5, the two gate commands exactly as the recipe spells them (minus ``uv run``)
    scan = _pla(
        "scan", "--workspace", "examples/fixture_workspace", *common,
        "--state-dir", ".pla_runs/rescan", cwd=tmp_path,
    )
    assert scan.returncode == 0, scan.stderr
    assert (tmp_path / ".pla_runs" / "rescan" / "slate.json").is_file()
    diff_args = ("diff", "--old", ".pla_runs/slate.json", "--new", ".pla_runs/rescan/slate.json")
    diff = _pla(*diff_args, "--fail-on-change", cwd=tmp_path)
    assert diff.returncode == 0, (diff.stdout, diff.stderr)
    assert diff.stdout.strip() == "(no differences)", diff.stdout
    runs = _pla("runs", "--state-dir", ".pla_runs", cwd=tmp_path)
    assert runs.returncode == 0 and "rescan" not in runs.stdout, runs.stdout
    assert re.search(r"^run-[0-9a-f]+\s", runs.stdout, re.M), runs.stdout
    # negative control: pop one goal from the re-scan -> 5 WITH the flag, 0 WITHOUT
    popped = tmp_path / ".pla_runs" / "rescan" / "popped.json"
    slate = json.loads((tmp_path / ".pla_runs" / "rescan" / "slate.json").read_text("utf-8"))
    assert len(slate["goals"]) >= 2, slate
    popped.write_text(json.dumps({**slate, "goals": slate["goals"][1:]}), encoding="utf-8")
    armed = _pla("diff", "--old", ".pla_runs/slate.json", "--new", str(popped), "--fail-on-change", cwd=tmp_path)
    assert armed.returncode == 5, (armed.returncode, armed.stdout, armed.stderr)
    assert "- removed (1)" in armed.stdout and "removed=1" in armed.stderr, (armed.stdout, armed.stderr)
    unarmed = _pla("diff", "--old", ".pla_runs/slate.json", "--new", str(popped), cwd=tmp_path)
    assert unarmed.returncode == 0, (unarmed.returncode, unarmed.stdout)


def test_determinism_gate_holds_in_the_tree_and_executes_with_a_biting_negative_control(
    tmp_path: Path,
) -> None:
    """The single collected item: behaviors 1-4 and 6-9 from the tree, then behavior 5
    executed through the console script with its negative control (see module docstring)."""
    _b1_makefile_recipe()
    _b2_ci_yml_step()
    _b3_gate_tuples()
    _b4_constant_sites()
    _b6_readme_paragraph()
    _b7_makefile_comment_words()
    _b8_roadmap_row()
    _b9_self_shape()
    _b5_gate_executes_exit_0_no_differences_and_the_negative_control_exits_5(tmp_path)
