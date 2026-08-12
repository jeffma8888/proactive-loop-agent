"""Black-box behavior tests for state-dir iteration 140 (ships as commit-seq
**factory iter 147**): ``broken_link`` is armed as the 4th kind in the product's
shared gate set (ROADMAP #167).

Feature under test (``pm.md``): ``BrokenDocLinkCollector`` shipped two commits ago
(``5939593``, factory iter 144) as the 17th collector and had ZERO consumers -- it
emitted into ``pla signals`` output and no gate, Makefile step or hook branched on
it. All three gate sites armed exactly ``merge_conflict`` / ``syntax_error`` /
``secret_file``. This iteration arms the 4th kind at all three sites in one
commit, so a Markdown link the filesystem disproves is a red build on a PUBLIC
portfolio repo whose docs the loop rewrites every iteration.

The whole design is the ARMED SET and its three-site parity, so that is what
these tests pin hardest: behavior 4 fails if any single site is widened alone.
Behavior 7 is the attribution guard -- it re-runs the OLD 3-kind set against the
SAME broken-link fixture and requires exit 0, which is what makes behavior 5's
exit 5 attributable to the newly armed kind rather than to some unrelated finding
in the fixture.

ISOLATION CONTRACT (honored): every assertion here is written from THIS
iteration's spec (``pm.md`` Expected Behaviors) plus the black-box surfaces that
spec designates -- the parsed TEXT of ``Makefile`` / ``.github/workflows/ci.yml``
/ ``hooks/pre-commit`` / ``README.md`` / ``ROADMAP.md``, and the OBSERVABLE
behavior of the real ``pla`` console script (exit code, stdout, stderr). **No file
under ``src/`` was read, no engineer or reviewer note was read, and no ``git
diff`` was consulted by the author.** The armed set, its order, the trip-line
text and the exit codes are encoded below as the CONTRACT's ground facts, NOT
copied out of any implementation, so a silent drift in either direction goes RED.

Offline + cap-safe: behaviors 1, 2, 3, 4, 9, 10 and 11 are pure file reads and
text parsing. Behaviors 5, 6, 7 and 8 execute the ARMED COMMAND ITSELF, but via
the installed ``pla`` console script (never ``uv``, never ``make``, so no nested
resolve/sync and no nested pytest) and -- for 5, 6 and 7 -- against fixture
workspaces built under ``tmp_path``, never the ambient tree. No network.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

# --------------------------------------------------------------------------
# Tester's ground facts -- the spec-declared contract constants (pm.md).
# --------------------------------------------------------------------------

REPO = Path(__file__).resolve().parents[1]
MAKEFILE = REPO / "Makefile"
WORKFLOW = REPO / ".github" / "workflows" / "ci.yml"
HOOK = REPO / "hooks" / "pre-commit"
README = REPO / "README.md"
ROADMAP = REPO / "ROADMAP.md"

# Behaviors 1-4: the 4-kind armed set, IN ORDER. `broken_link` is the addition.
EXPECTED_ARMED_KINDS = [
    "merge_conflict",
    "syntax_error",
    "secret_file",
    "broken_link",
]
NEW_KIND = "broken_link"
# Behavior 7: the pre-iteration armed set, used only as the attribution control.
OLD_ARMED_KINDS = ["merge_conflict", "syntax_error", "secret_file"]

# Behavior 2: the shared command prefix both the Makefile and CI must spell.
GATE_PREFIX = "uv run pla signals --workspace ."
# Behavior 5: the gate's exit code and its one stderr diagnostic.
GATE_EXIT = 5
TRIP_PREFIX = "gate: fail-on-kind tripped --"

_FAIL_ON_KIND = re.compile(r"--fail-on-kind[=\s]+([A-Za-z_][A-Za-z0-9_]*)")


# --------------------------------------------------------------------------
# Black-box parsers -- the three gate sites, read as TEXT.
# --------------------------------------------------------------------------


def _make_recipe(target: str) -> list[str]:
    """The tab-indented recipe lines of a Makefile target."""
    lines = MAKEFILE.read_text(encoding="utf-8").splitlines()
    body: list[str] = []
    collecting = False
    for line in lines:
        if line.startswith(f"{target}:"):
            collecting = True
            continue
        if collecting:
            if line.startswith("\t"):
                body.append(line[1:])
                continue
            if line.strip() == "" or line.startswith("#"):
                continue
            break
    assert body, f"the Makefile must define a non-empty `{target}` recipe"
    return body


def _make_gate_line() -> str:
    """The ONE armed self-scan line of the `check` recipe."""
    armed = [line.strip() for line in _make_recipe("check") if "--fail-on-kind" in line]
    assert len(armed) == 1, (
        "expected exactly one armed self-scan line in the Makefile `check` recipe "
        f"so parity has an unambiguous side; found {len(armed)}: {armed}"
    )
    return armed[0]


def _ci_gate_line() -> str:
    """The ONE non-comment armed gate line of the CI workflow."""
    armed = [
        line.strip()
        for line in WORKFLOW.read_text(encoding="utf-8").splitlines()
        if "--fail-on-kind" in line and not line.strip().startswith("#")
    ]
    assert len(armed) == 1, (
        "expected exactly one non-comment armed gate line in ci.yml so parity has "
        f"an unambiguous other side; found {len(armed)}: {armed}"
    )
    return armed[0]


def _ci_gate_command() -> str:
    """The CI gate line with its YAML `run:` key stripped."""
    line = _ci_gate_line()
    _, _, command = line.partition("run:")
    return (command or line).strip()


def _hook_text() -> str:
    return HOOK.read_text(encoding="utf-8")


def _armed_from_make() -> list[str]:
    return _FAIL_ON_KIND.findall(_make_gate_line())


def _armed_from_ci() -> list[str]:
    return _FAIL_ON_KIND.findall(_ci_gate_line())


def _armed_from_hook() -> list[str]:
    return _FAIL_ON_KIND.findall(_hook_text())


# --------------------------------------------------------------------------
# Behaviors 1-4 -- the armed set and its three-site parity.
# --------------------------------------------------------------------------


def test_b1_makefile_check_arms_the_four_kinds_in_order() -> None:
    """Behavior 1: the `check` self-scan passes exactly four kinds, in order."""
    assert _armed_from_make() == EXPECTED_ARMED_KINDS, (
        "the Makefile `check` self-scan must arm exactly the 4-kind set in order; "
        f"parsed {_armed_from_make()} from {_make_gate_line()!r}"
    )


def test_b2_ci_arms_the_same_four_kinds_and_matches_the_makefile() -> None:
    """Behavior 2: CI arms the same ordered set and is byte-identical to the
    Makefile line after the shared `uv run pla signals --workspace .` prefix."""
    assert _armed_from_ci() == EXPECTED_ARMED_KINDS, (
        "the CI self-scan step must arm exactly the 4-kind set in order; "
        f"parsed {_armed_from_ci()} from {_ci_gate_line()!r}"
    )
    make_command = _make_gate_line()
    ci_command = _ci_gate_command()
    assert make_command.startswith(GATE_PREFIX), (
        f"the Makefile gate must spell the shared prefix {GATE_PREFIX!r}; got "
        f"{make_command!r}"
    )
    assert ci_command.startswith(GATE_PREFIX), (
        f"the CI gate must spell the shared prefix {GATE_PREFIX!r}; got {ci_command!r}"
    )
    assert make_command == ci_command, (
        "the local and CI gates must stay byte-identical or they can silently "
        f"diverge; Makefile={make_command!r} CI={ci_command!r}"
    )


def test_b3_hook_arms_the_same_four_kinds_one_flag_per_continuation_line() -> None:
    """Behavior 3: the hook arms the same ordered set, one flag per continuation
    line ending in a single backslash, so the line-shaped parser still parses."""
    assert _armed_from_hook() == EXPECTED_ARMED_KINDS, (
        "hooks/pre-commit must arm exactly the 4-kind set in order; parsed "
        f"{_armed_from_hook()}"
    )
    flag_lines = [
        line for line in _hook_text().splitlines() if "--fail-on-kind" in line
    ]
    assert len(flag_lines) == len(EXPECTED_ARMED_KINDS), (
        "each armed kind must sit on its OWN continuation line so the "
        f"line-shaped parity parser keeps working; found {flag_lines}"
    )
    for line in flag_lines[:-1]:
        stripped = line.rstrip()
        assert stripped.endswith("\\") and not stripped.endswith("\\\\"), (
            "every armed kind except the last must end in a single line "
            f"continuation; got {line!r}"
        )
        assert len(_FAIL_ON_KIND.findall(line)) == 1, (
            f"exactly one --fail-on-kind per line; got {line!r}"
        )


def test_b4_all_three_gate_sites_arm_the_identical_set() -> None:
    """Behavior 4: Makefile, CI and hook parse to the same armed set. Widening
    one site alone fails here."""
    sites = {
        "Makefile": _armed_from_make(),
        ".github/workflows/ci.yml": _armed_from_ci(),
        "hooks/pre-commit": _armed_from_hook(),
    }
    assert len(set(map(tuple, sites.values()))) == 1, (
        "all three gate sites must arm the IDENTICAL ordered set -- a partial "
        f"arming breaks three-site parity; parsed {sites}"
    )
    for name, armed in sites.items():
        assert NEW_KIND in armed, f"{name} must arm the newly wired {NEW_KIND!r}"


# --------------------------------------------------------------------------
# Live-gate helpers -- run the ARMED COMMAND ITSELF, parsed from the Makefile.
# --------------------------------------------------------------------------


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

    Built from the PARSED Makefile line, never from a re-typed copy, so this runs
    what the gate runs. Two substitutions: ``uv run pla`` -> the installed console
    script (same entry point, no nested `uv` resolve), and the ``--workspace``
    value -> the fixture path.
    """
    tokens = _make_gate_line().split()
    assert tokens[:3] == ["uv", "run", "pla"], (
        f"the armed self-scan must invoke the product's console script; tokens "
        f"were {tokens}"
    )
    argv = [str(_console_script()), *tokens[3:]]
    position = argv.index("--workspace")
    argv[position + 1] = str(workspace)
    return argv


def _dearm(argv: list[str], kind: str) -> list[str]:
    """``argv`` with one ``--fail-on-kind <kind>`` pair removed -- the behavior-7
    control, which reconstructs the PRE-ITERATION armed set from the shipped one
    rather than re-typing it."""
    out: list[str] = []
    index = 0
    while index < len(argv):
        if argv[index] == "--fail-on-kind" and argv[index + 1] == kind:
            index += 2
            continue
        out.append(argv[index])
        index += 1
    return out


def _run(argv: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv, cwd=str(cwd), capture_output=True, text=True, timeout=120
    )


def _gate_lines(stderr: str) -> list[str]:
    return [line for line in stderr.splitlines() if line.startswith("gate:")]


def _plant_broken_link(root: Path) -> Path:
    """A workspace whose ONLY armed finding is one broken relative link."""
    workspace = root / "ws_broken"
    workspace.mkdir()
    (workspace / "index.md").write_text(
        "# Doc\n\n[gone](missing-doc.md)\n", encoding="utf-8"
    )
    return workspace


def _plant_clean_links(root: Path) -> Path:
    """A workspace exercising every link shape the gate must NOT trip on."""
    workspace = root / "ws_clean"
    workspace.mkdir()
    (workspace / "exists.md").write_text("target\n", encoding="utf-8")
    (workspace / "index.md").write_text(
        "# Doc\n\n"
        "- (a) [here](exists.md)\n"
        "- (b) [site](https://example.com/page)\n"
        "- (c) [mail](mailto:someone@example.com)\n"
        "- (d) [anchor](#section)\n"
        "\n"
        "```markdown\n"
        "[not-a-real-link](totally-missing.md)\n"
        "```\n",
        encoding="utf-8",
    )
    return workspace


# --------------------------------------------------------------------------
# Behaviors 5-8 -- the armed gate's OBSERVABLE behavior.
# --------------------------------------------------------------------------


def test_b5_gate_trips_on_a_broken_relative_link(tmp_path: Path) -> None:
    """Behavior 5: a Markdown link the filesystem disproves exits 5 with exactly
    one stderr diagnostic naming the kind and its count -- and stdout still
    carries the normal report (the gate reports, it does not suppress)."""
    workspace = _plant_broken_link(tmp_path)
    proc = _run(_gate_argv(workspace), cwd=tmp_path)

    assert proc.returncode == GATE_EXIT, (
        f"a broken relative link must exit {GATE_EXIT} through the armed gate; got "
        f"{proc.returncode}. stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
    lines = _gate_lines(proc.stderr)
    assert lines == [f"{TRIP_PREFIX} {NEW_KIND}=1"], (
        "the trip must be ONE stderr line naming the tripped kind and its count, "
        f"so a CI log says WHAT failed; got {proc.stderr!r}"
    )
    assert NEW_KIND in proc.stdout, (
        "the gate must not suppress the normal signal listing on stdout; got "
        f"{proc.stdout!r}"
    )


def test_b6_gate_does_not_over_fire_on_legitimate_link_shapes(
    tmp_path: Path,
) -> None:
    """Behavior 6: an existing relative target, an https URL, a mailto target, a
    bare anchor and a relative-looking link inside a fenced code block are all
    clean -- exit 0 and no gate line. This is what keeps the arming from
    reddening a PUBLIC build over a documentation code sample."""
    workspace = _plant_clean_links(tmp_path)
    proc = _run(_gate_argv(workspace), cwd=tmp_path)

    assert proc.returncode == 0, (
        "none of the five legitimate link shapes may trip the gate; got exit "
        f"{proc.returncode}. stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
    assert _gate_lines(proc.stderr) == [], (
        f"a clean workspace must print no gate line; got {proc.stderr!r}"
    )


def test_b7_the_old_three_kind_set_is_clean_on_the_same_fixture(
    tmp_path: Path,
) -> None:
    """Behavior 7 (ATTRIBUTION): the pre-iteration 3-kind set exits 0 on the very
    fixture that makes the 4-kind set exit 5. Without this control, behavior 5's
    exit 5 could be caused by an unrelated finding in the fixture."""
    workspace = _plant_broken_link(tmp_path)
    control = _dearm(_gate_argv(workspace), NEW_KIND)

    assert _FAIL_ON_KIND.findall(" ".join(control)) == OLD_ARMED_KINDS, (
        "the control must arm exactly the pre-iteration 3-kind set; built "
        f"{control}"
    )
    proc = _run(control, cwd=tmp_path)
    assert proc.returncode == 0, (
        "the OLD armed set must be CLEAN on the broken-link fixture, which is "
        f"what attributes behavior 5's exit {GATE_EXIT} to the newly armed "
        f"{NEW_KIND!r}; got exit {proc.returncode} stderr={proc.stderr!r}"
    )


def test_b8_the_armed_gate_is_green_on_this_checkout() -> None:
    """Behavior 8: arming is fail-CLOSED on a clean tree -- the full 4-kind gate
    exits 0 against the repository itself, so `make check` and the CI self-scan
    do not regress on arrival."""
    proc = _run(_gate_argv(REPO), cwd=REPO)
    assert proc.returncode == 0, (
        "the newly armed gate must be GREEN on this checkout or it reddens a "
        f"PUBLIC build on arrival; got exit {proc.returncode}\n"
        f"stderr={proc.stderr!r}\n"
        "NOTE: the scan walks the WORKING DIR, so an untracked/gitignored "
        "Markdown file with a broken relative link can redden this locally while "
        "CI (a fresh checkout) stays green."
    )
    assert _gate_lines(proc.stderr) == [], (
        f"a clean checkout must print no gate line; got {proc.stderr!r}"
    )


# --------------------------------------------------------------------------
# Behaviors 9-11 -- the pins were UPDATED, not bypassed, and the docs agree.
# --------------------------------------------------------------------------


def test_b9_the_iter140_ordered_pin_was_updated() -> None:
    """Behavior 9: `test_iter140`'s ordered pin carries the 4-element set and its
    now-false "out of scope" prose is gone. The pin is the intended edit point."""
    from tests.test_iter140_behavior import EXPECTED_ARMED_KINDS as pinned

    assert list(pinned) == EXPECTED_ARMED_KINDS, (
        "tests/test_iter140_behavior.py's EXPECTED_ARMED_KINDS must be the "
        f"4-element ORDERED list; it is {list(pinned)}"
    )
    text = (REPO / "tests" / "test_iter140_behavior.py").read_text(encoding="utf-8")
    assert "out of scope for this increment" not in text, (
        "the prose claiming that widening the armed set is out of scope is now "
        "FALSE and must have been corrected, not left to rot beside a 4-kind pin"
    )


def test_b10_the_iter128_set_pin_was_updated_and_forbidden_kinds_untouched() -> (
    None
):
    """Behavior 10: `test_iter128`'s set-equality pin carries the 4-element
    frozenset, `FORBIDDEN_KINDS` is unchanged, and no test name still calls the
    armed set a "trio"."""
    from tests.test_iter128_behavior import ARMED_KINDS, FORBIDDEN_KINDS

    assert ARMED_KINDS == frozenset(EXPECTED_ARMED_KINDS), (
        "tests/test_iter128_behavior.py's ARMED_KINDS is asserted for SET "
        f"EQUALITY, so it must hold exactly the 4 armed kinds; it is {ARMED_KINDS}"
    )
    assert NEW_KIND not in FORBIDDEN_KINDS, (
        f"{NEW_KIND!r} is now ARMED, so it must not also sit in FORBIDDEN_KINDS"
    )
    assert FORBIDDEN_KINDS == frozenset(
        {
            "lockfile_drift",
            "test_posture",
            "ci_config",
            "working_tree",
            "git_state",
            "git_stash",
        }
    ), (
        "FORBIDDEN_KINDS must be left UNCHANGED by this iteration -- it is the "
        f"guard that keeps local-state kinds out of the gate; it is {FORBIDDEN_KINDS}"
    )
    text = (REPO / "tests" / "test_iter128_behavior.py").read_text(encoding="utf-8")
    assert "trio" not in text, (
        'the armed set is now FOUR kinds, so no test name or comment may still '
        'call it a "trio"'
    )


def test_b11_readme_documents_four_armed_kinds_and_names_the_new_one() -> None:
    """Behavior 11: the README's hook section no longer says "three kinds" while
    the code arms four, and it names the newly armed kind."""
    text = README.read_text(encoding="utf-8")
    assert "the same four kinds the CI self-scan arms" in text, (
        "README must say the hook arms the same FOUR kinds as the CI self-scan"
    )
    assert "the same three kinds the CI self-scan arms" not in text, (
        "the stale three-kind claim must be gone -- a docs-vs-code contradiction "
        "on a PUBLIC portfolio repo"
    )
    hook_claim = next(
        line for line in text.splitlines() if "four kinds the CI self-scan" in line
    )
    window = text[text.index(hook_claim) : text.index(hook_claim) + 400]
    assert NEW_KIND in window, (
        f"the README's four-kind claim must NAME {NEW_KIND!r} alongside the other "
        f"three; nearby text was {window!r}"
    )
