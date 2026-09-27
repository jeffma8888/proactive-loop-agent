"""Black-box oracle for foundry iteration 326 (state-dir iteration 474, ROADMAP #305):
the CI ``test`` job carries a job-level ``timeout-minutes`` and a ratchet pins the count of
UNTIMED ``subprocess`` calls in ``tests/`` while ``src/`` stays at zero -- written by the
tester from the spec alone (pm.md ``## Expected Behaviors``), the repo's own ``tests/``
tree, ``ROADMAP.md`` / ``ROADMAP_ARCHIVE.md`` and ``.github/workflows/ci.yml`` (the
artifact behavior 1 grades).

WHY THIS MODULE EXISTS. Until foundry iter 326 ``ci.yml`` had no ``timeout-minutes``
anywhere, so GitHub's default of 360 minutes per job applied to BOTH matrix legs: one
wedged child process (the suite spawns ``git``, ``pla`` and ``python -m`` children, 39 of
them without ``timeout=`` at the parent commit) would hold the public badge at
"in progress" for six hours per leg instead of turning red. The job timeout caps that
blast radius; the ratchet stops the number of unbounded test children from growing; the
``src/`` pin keeps the product's own two ``subprocess`` sites timed.

WHAT THIS MODULE GRADES (THREE collected items -- ``make readme-headroom`` read
``binding_headroom == MIN_BINDING_HEADROOM`` once three items were added, so the module is
funded 1:1 by three retired assert-message-only duplicates, see ``RETIRED_TESTS``; extra
assertions live INSIDE these three bodies, never as a fourth item or a parametrization):
(1) behavior 1: ``jobs.test`` in ``ci.yml`` carries exactly one job-level (indent 4, not a
comment, not inside ``steps:``) ``timeout-minutes: N`` line with ``10 <= N <= 30``;
(2) behavior 2: an ``ast`` census over the worktree glob ``tests/test_*.py`` counts calls
to ``subprocess.{run,check_output,check_call,call,Popen}`` (module alias and
``from subprocess import`` forms included) that carry no ``timeout=`` keyword, and that
count is ``<= UNTIMED_SUBPROCESS_BUDGET`` -- a ratchet-down constant. The census proves
itself alive on an inline snippet (each of the five names, timed and untimed, both import
forms) and on the real tree (this file is in the glob; timed sites are found), so it can
never pass vacuously;
(3) behavior 3 + records: every ``subprocess`` site under ``src/proactive_loop`` carries
``timeout=`` (and at least one exists); ROADMAP.md holds exactly one ``- #305`` Done-ledger
row (<= 120 chars, tagged ``(foundry iter 326)`` exactly once, naming ``timeout-minutes``,
``subprocess`` and the budget number -- bound to ``UNTIMED_SUBPROCESS_BUDGET``, never a
live count), the index keeps its 20 rows with no #305 row, ROADMAP_ARCHIVE.md never
mentions #305, ``test_iter264::EXPECTED_LEDGER_ROWS`` was re-keyed past 93, the three
named duplicates are gone while their canonical copies survive, and this module holds
exactly three collected items and bounds no document by size (test_iter172's census).

ISOLATION CONTRACT (honored). Every assertion was written from pm.md's Expected Behaviors,
the ``tests/`` tree, the two roadmap files and ``ci.yml``. No file under ``src/`` was read
by the tester (the census in (3) is executed by the test, not read by its author); no
engineer/reviewer notes, no ``git diff``.

Offline and deterministic: no subprocess, no network, no tmp files. ``ci.yml`` is parsed
by indentation (no ``yaml`` dependency -- the runtime dependency is pydantic v2 ONLY).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Final

from tests.test_iter172_behavior import roadmap_size_bounds
from tests.test_iter264_behavior import EXPECTED_LEDGER_ROWS

REPO = Path(__file__).resolve().parents[1]
CI_YML = REPO / ".github" / "workflows" / "ci.yml"
TESTS_DIR = REPO / "tests"
SRC_DIR = REPO / "src" / "proactive_loop"
ROADMAP = REPO / "ROADMAP.md"
ARCHIVE = REPO / "ROADMAP_ARCHIVE.md"

#: Behavior 1: the job whose wall clock is capped, and the spec's inclusive bounds.
CI_JOB = "test"
TIMEOUT_KEY = "timeout-minutes"
TIMEOUT_MIN_MINUTES = 10
TIMEOUT_MAX_MINUTES = 30
JOB_INDENT = 2  # ``  test:`` under ``jobs:``
JOB_FIELD_INDENT = 4  # ``    timeout-minutes: N`` -- job level, not a step

#: Behavior 2: the ratchet. 39 untimed sites across 23 modules were measured at the parent
#: commit (4beda63); this number may only go DOWN. When you add ``timeout=`` to a site,
#: LOWER this constant in the same commit so the ratchet keeps biting.
UNTIMED_SUBPROCESS_BUDGET: Final[int] = 39
#: The ``subprocess`` callables that spawn or wait on a child.
SPAWN_NAMES: Final[frozenset[str]] = frozenset(
    {"run", "check_output", "check_call", "call", "Popen"}
)

#: Behavior 3 + records.
LEDGER_ROW_NUMBER = 305
ITER_TAG = "(foundry iter 326)"
LEDGER_ROW_MAX_CHARS = 120  # tests/test_iter241_behavior.py cap
LEDGER_ROW_NEEDLES = (TIMEOUT_KEY, "subprocess", str(UNTIMED_SUBPROCESS_BUDGET))
INDEX_ROWS = 20  # #305 never had an index row (mirrors #304 in 4beda63)
LEDGER_ROWS_BEFORE = 93  # test_iter264::EXPECTED_LEDGER_ROWS at the parent commit
COLLECTED_ITEMS = 3

#: Funding: the assert-message-only duplicates retired in this commit (each body was a
#: registry-count assertion differing from its canonical copy only in its message).
RETIRED_TESTS: tuple[tuple[str, str], ...] = (
    ("test_iter83_behavior.py", "test_b8_provider_count_unchanged"),
    ("test_iter87_behavior.py", "test_b7_cli_subcommand_count_unchanged"),
    ("test_iter90_behavior.py", "test_b7_provider_count_unchanged"),
)
#: The canonical copies that must SURVIVE.
KEEPERS: tuple[tuple[str, str], ...] = (
    ("test_iter81_behavior.py", "test_b8_provider_count_unchanged"),
    ("test_iter81_behavior.py", "test_b8_cli_subcommand_count_unchanged"),
)


# --------------------------------------------------------------------------- helpers


def _strip_comment(line: str) -> str:
    """Drop a YAML ``#`` comment (a ``#`` preceded by whitespace or at column 0)."""
    return re.sub(r"(^|\s)#.*$", "", line).rstrip()


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _job_block(text: str, job: str) -> list[str]:
    """Return the lines of ``jobs.<job>`` (exclusive of the ``  <job>:`` key line)."""
    lines = text.splitlines()
    try:
        jobs_at = next(i for i, ln in enumerate(lines) if _strip_comment(ln) == "jobs:")
    except StopIteration as exc:  # pragma: no cover - the assertion below reports it
        raise AssertionError("behavior 1: ci.yml has a top-level `jobs:` mapping") from exc
    key = " " * JOB_INDENT + f"{job}:"
    start = None
    for i in range(jobs_at + 1, len(lines)):
        stripped = _strip_comment(lines[i])
        if not stripped:
            continue
        if _indent(stripped) == 0:
            break  # left the jobs mapping without finding the job
        if stripped == key:
            start = i + 1
            break
    assert start is not None, f"behavior 1: ci.yml declares `jobs.{job}`"
    block: list[str] = []
    for ln in lines[start:]:
        stripped = _strip_comment(ln)
        if stripped and _indent(stripped) <= JOB_INDENT:
            break
        block.append(ln)
    return block


def _subprocess_census(source: str) -> tuple[int, int]:
    """Return ``(timed, untimed)`` counts of spawn calls in one module's source.

    A site is ``subprocess.<name>(...)`` (through any ``import subprocess [as x]``) or a bare
    ``<name>(...)`` bound by ``from subprocess import <name> [as x]``; it is TIMED when the
    call carries a ``timeout=`` keyword.
    """
    tree = ast.parse(source)
    module_aliases: set[str] = set()
    bare_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "subprocess":
                    module_aliases.add(alias.asname or "subprocess")
        elif isinstance(node, ast.ImportFrom) and node.module == "subprocess":
            for alias in node.names:
                if alias.name in SPAWN_NAMES:
                    bare_names.add(alias.asname or alias.name)
    timed = untimed = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_site = (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id in module_aliases
            and func.attr in SPAWN_NAMES
        ) or (isinstance(func, ast.Name) and func.id in bare_names)
        if not is_site:
            continue
        if any(kw.arg == "timeout" for kw in node.keywords):
            timed += 1
        else:
            untimed += 1
    return timed, untimed


def _census_tree(paths: list[Path]) -> tuple[int, int, dict[str, int]]:
    """Sum the census over ``paths``; also return ``{module: untimed}`` for the offenders."""
    timed_total = untimed_total = 0
    offenders: dict[str, int] = {}
    for path in paths:
        timed, untimed = _subprocess_census(path.read_text(encoding="utf-8"))
        timed_total += timed
        untimed_total += untimed
        if untimed:
            offenders[path.name] = untimed
    return timed_total, untimed_total, offenders


def _index_rows(text: str) -> list[str]:
    rows = []
    for line in text.splitlines():
        parts = line.split("|")
        if len(parts) > 2 and line.startswith("|") and parts[1].strip().isdigit():
            rows.append(line)
    return rows


# ------------------------------------------------------------------------- behaviors


def test_b1_ci_test_job_carries_exactly_one_job_level_timeout_minutes() -> None:
    text = CI_YML.read_text(encoding="utf-8")
    block = _job_block(text, CI_JOB)
    assert block, f"behavior 1: `jobs.{CI_JOB}` has a body"

    job_level = []
    for raw in block:
        stripped = _strip_comment(raw)
        if not stripped or _indent(stripped) != JOB_FIELD_INDENT:
            continue
        match = re.fullmatch(rf"\s*{TIMEOUT_KEY}:\s*(\S+)", stripped)
        if match:
            job_level.append(match.group(1))
    assert len(job_level) == 1, (
        f"behavior 1: `jobs.{CI_JOB}` carries exactly one job-level `{TIMEOUT_KEY}: N` "
        f"line (indent {JOB_FIELD_INDENT}, outside `steps:`); got {job_level!r}"
    )
    value = job_level[0]
    assert value.isdigit(), (
        f"behavior 1: `{TIMEOUT_KEY}` is a literal integer, not an expression; got {value!r}"
    )
    minutes = int(value)
    assert TIMEOUT_MIN_MINUTES <= minutes <= TIMEOUT_MAX_MINUTES, (
        f"behavior 1: {TIMEOUT_MIN_MINUTES} <= {TIMEOUT_KEY} <= {TIMEOUT_MAX_MINUTES}; "
        f"got {minutes}"
    )
    # The key never hides in a comment or a step: every occurrence in the file is the one
    # job-level line just graded (GitHub's 360-minute default must not be re-opened by a
    # second, looser value on a step or on another job).
    live = [
        ln for ln in text.splitlines() if TIMEOUT_KEY in _strip_comment(ln)
    ]
    assert len(live) == 1, (
        f"behavior 1: `{TIMEOUT_KEY}` appears on exactly one non-comment line in ci.yml; "
        f"got {live!r}"
    )


def test_b2_untimed_subprocess_sites_in_tests_never_exceed_the_ratchet() -> None:
    # The census proves itself alive before it grades anything: every spawn name, both
    # import forms, timed and untimed, on an inline snippet with a known answer.
    snippet = "\n".join(
        [
            "import subprocess",
            "import subprocess as sp",
            "from subprocess import check_call, Popen as P",
            "subprocess.run(['x'])",
            "subprocess.run(['x'], timeout=1)",
            "sp.check_output(['x'])",
            "sp.call(['x'], timeout=2)",
            "check_call(['x'])",
            "P(['x'], timeout=3)",
            "subprocess.CompletedProcess(['x'], 0)",  # not a spawn: never counted
            "other.run(['x'])",  # not subprocess: never counted
        ]
    )
    assert _subprocess_census(snippet) == (3, 3), (
        "precondition: the census recognises all five spawn names through both import "
        f"forms and separates timed from untimed; got {_subprocess_census(snippet)!r}"
    )

    modules = sorted(TESTS_DIR.glob("test_*.py"))
    assert Path(__file__).resolve() in [m.resolve() for m in modules], (
        "precondition: the worktree glob `tests/test_*.py` includes this module"
    )
    timed, untimed, offenders = _census_tree(modules)
    assert timed >= 1, "precondition: the census finds timed subprocess sites in tests/"
    assert untimed <= UNTIMED_SUBPROCESS_BUDGET, (
        f"behavior 2: untimed subprocess sites in tests/test_*.py <= "
        f"{UNTIMED_SUBPROCESS_BUDGET}; got {untimed} across {len(offenders)} modules: "
        f"{offenders!r}. Add `timeout=` to the new site instead of raising the budget."
    )


def _b3_src_sites_all_timed() -> None:
    modules = sorted(SRC_DIR.rglob("*.py"))
    assert modules, f"precondition: {SRC_DIR} holds Python modules"
    timed, untimed, offenders = _census_tree(modules)
    assert timed >= 1, "precondition: the product itself spawns at least one timed child"
    assert untimed == 0, (
        f"behavior 3: every subprocess site under src/proactive_loop carries timeout=; "
        f"untimed sites: {offenders!r}"
    )


def _b3_roadmap_records() -> None:
    text = ROADMAP.read_text(encoding="utf-8")
    ledger = [line for line in text.splitlines() if line.startswith(f"- #{LEDGER_ROW_NUMBER} ")]
    assert len(ledger) == 1, (
        f"records: exactly one Done-ledger row for #{LEDGER_ROW_NUMBER}; got {ledger!r}"
    )
    row = ledger[0]
    assert len(row) <= LEDGER_ROW_MAX_CHARS, (
        f"records: the #{LEDGER_ROW_NUMBER} row is <= {LEDGER_ROW_MAX_CHARS} chars; got {len(row)}"
    )
    assert row.endswith(ITER_TAG), f"records: the row ends with {ITER_TAG!r}; got {row!r}"
    for needle in LEDGER_ROW_NEEDLES:
        assert needle in row, (
            f"records: the #{LEDGER_ROW_NUMBER} row names {needle!r} (the budget number is "
            f"bound to UNTIMED_SUBPROCESS_BUDGET, so lowering the ratchet re-words the row)"
        )
    assert text.count(ITER_TAG) == 1, (
        f"records: {ITER_TAG} appears exactly once in ROADMAP.md (one row per iteration)"
    )
    rows = _index_rows(text)
    numbers = [int(r.split("|")[1].strip()) for r in rows]
    assert len(rows) == INDEX_ROWS, (
        f"records: no index row is retired -- the index keeps {INDEX_ROWS} rows; got {len(rows)}"
    )
    assert LEDGER_ROW_NUMBER not in numbers, f"records: #{LEDGER_ROW_NUMBER} never had an index row"
    assert EXPECTED_LEDGER_ROWS > LEDGER_ROWS_BEFORE, (
        f"records: test_iter264::EXPECTED_LEDGER_ROWS was re-keyed past {LEDGER_ROWS_BEFORE} "
        f"for the #{LEDGER_ROW_NUMBER} row; got {EXPECTED_LEDGER_ROWS}"
    )
    archive = ARCHIVE.read_text(encoding="utf-8")
    assert f"#{LEDGER_ROW_NUMBER}" not in archive, (
        f"records: ROADMAP_ARCHIVE.md is untouched (no #{LEDGER_ROW_NUMBER} bullet or row)"
    )


def _b3_funding_and_self_shape() -> None:
    for module, name in RETIRED_TESTS:
        source = (TESTS_DIR / module).read_text(encoding="utf-8")
        assert f"def {name}(" not in source, (
            f"funding: {module}::{name} was retired to fund this module; it is back"
        )
    for module, name in KEEPERS:
        source = (TESTS_DIR / module).read_text(encoding="utf-8")
        assert f"def {name}(" in source, f"funding: canonical copy {module}::{name} must survive"

    own_source = Path(__file__).read_text(encoding="utf-8")
    tree = ast.parse(own_source)
    collected = [
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
    ]
    assert len(collected) == COLLECTED_ITEMS, (
        f"self-shape: this module holds exactly {COLLECTED_ITEMS} collected items; got {collected}"
    )
    marker = "param" + "etrize"
    assert marker not in own_source.replace('"param" + "etrize"', ""), (
        "self-shape: no parametrization multiplies the collected count"
    )
    assert roadmap_size_bounds(own_source) == (), (
        "this module must not bound ROADMAP.md by size (test_iter172 census); "
        f"found {roadmap_size_bounds(own_source)}"
    )


def test_b3_src_sites_timed_and_iteration_records_landed() -> None:
    _b3_src_sites_all_timed()
    _b3_roadmap_records()
    _b3_funding_and_self_shape()
