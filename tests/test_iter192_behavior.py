"""Per-scan WORK-BUDGET oracle for the perception layer (state dir ``iter-189``).

WHAT THIS MODULE PINS. One perception scan -- driven through the same entry point
every front-door verb shares, ``cli._collect`` -- is allowed a BOUNDED amount of
work, counted in units a machine can check: physical directory traversals
(``os.walk`` calls), source parses (``builtins.compile`` calls) and child
processes (``subprocess.run`` calls). Until now every throughput property this
product won was protected either as dated prose (``collectors/text_source``'s
"583 -> 200 read_text" comment, true when written and unenforced since) or
per-feature (factory iter 187's oracle counts traversals only for the two
collectors that iteration converted). There was no single place stating what a
scan is allowed to COST, so the next collector added could reintroduce a
duplicate traversal or a duplicate parse with every gate staying green.

MODULE NAME, derived from the repo and never from the state-dir counter -- the
operator pin, and the defect that cost factory iteration 186 a shipped oracle.
The highest tracked ``tests/test_iterNN_behavior.py`` is 191, so this file is
192, and ``git cat-file -e HEAD:tests/test_iter192_behavior.py`` FAILED before a
byte was written, proving the path free in ``HEAD``. The number therefore runs
one AHEAD of this commit's ``factory iter`` tag, because factory iteration 190's
commit shipped TWO oracle modules (``test_iter190_behavior.py`` and
``test_iter191_behavior.py``, the re-landing iteration's independent second
opinion). The filename is a free-slot marker, not a claim about which iteration
built it.

WHY COUNTS AND NOT MILLISECONDS. A count is deterministic and regime-free: it is
identical on a loaded CI box, on a 2-core runner and on a 12-core laptop, and it
is identical on both legs of the 3.12/3.13 matrix. A millisecond threshold is
none of those things, and a flaky timing assertion on a PUBLIC portfolio repo
reds a badge for reasons no contributor caused. Nothing here asserts a duration.

WHY EVERY BUDGET IS A CEILING AND NEVER AN EQUALITY. The traversal count this
fixture exhibits today is WASTEFUL -- most walking collectors still walk for
themselves instead of reading the shared listing from ``collectors/dir_source``
-- and an ``==`` assertion would BLESS that waste: it would red the build on the
day someone converts another collector onto the provider, which is the exact
improvement this file exists to protect. So every budget is asserted with ``<=``,
every constant names its TARGET in its own failure message, and the message says
in words that the constant may be LOWERED and must never be RAISED. A ceiling
forbids only getting worse. The one equality here is on the provider's
``misses``, and that is deliberate: "one physical traversal per scope" is
``dir_source``'s correctness contract, not a budget with slack.

WHY THE PARSE MEMO IS CLEARED FOR EVERY TEST, AND WHAT FORGETTING IT COSTS.
MEASURED while building this module: two scans of two DIFFERENT directories in
ONE process compiled 3 files and then 0, because ``syntax_error._PARSE_MEMO`` is
keyed by content DIGEST and lives for the life of the process, not the scan. A
parse-budget test that does not clear it is therefore VACUOUSLY green whenever
any sibling test happened to scan the same bytes first -- a fail-open guard whose
verdict depends on test ORDER, which under ``-n auto`` is not even stable. Hence
the autouse fixture below, and hence the anti-vacuity lower bounds: a budget
satisfied by counting ZERO work proves nothing at all.

HERMETIC BY CONSTRUCTION. Every scan below runs against a tree the test CREATES
under ``tmp_path``, and Behavior 1 asserts that rather than assuming it: a count
taken against the ambient repository would pass only on this machine and break
in the fresh-clone release check, which is the 2026-08-11 operator lesson. No
network, no wall clock, and no assertion on docstring or help-text indentation,
so neither matrix leg can diverge here.

Coverage (numbered to match this iteration's ``pm.md`` Expected Behaviors):

1. The scan root is inside ``tmp_path`` and is NOT the repository root.
2. Traversal budget: ``os.walk`` calls over one scan are ``<= WALK_BUDGET``.
3. The shared provider performs exactly ONE physical traversal per scope
   (``misses == 1``) and actually serves the rest (``hits >= 1``).
4. Parse budget: no source file is compiled twice -- ``compile`` calls are
   ``<= PARSES_PER_SOURCE_FILE`` per distinct unpruned ``.py`` file.
5. Child-process budget: ``<= CHILD_PROCESS_BUDGET`` calls, and no two calls
   share an identical argv.
6. The oracle is two-sided: each counting shim is proved to COUNT, by invoking
   the patched callable a known number of times and asserting the tally, and the
   shims are proved absent outside the fixture that installs them.
"""

from __future__ import annotations

import builtins
import os
import subprocess
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

import pytest

from proactive_loop import cli
from proactive_loop.collectors.dir_source import (
    clear_walk_cache,
    walk_cache_stats,
)
from proactive_loop.collectors.syntax_error import clear_parse_memo

# Captured ONCE at import, BEFORE any fixture rebinds them. Patching a module
# attribute is a process-global rebind, so a shim that re-looked-up the live
# attribute at call time would recurse into itself (the ``test_iter175`` idiom).
_REAL_WALK: Final = os.walk
_REAL_COMPILE: Final = builtins.compile
_REAL_RUN: Final = subprocess.run

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# The budgets. Each is a CEILING measured on the fixture below, never a target.
# ---------------------------------------------------------------------------

# Physical traversals one scan performs of the single scanned root. 1 is the
# correct number -- one pruned walk served to every walking collector by
# ``dir_source``. LOWER this as collectors are converted; never raise it.
WALK_BUDGET: Final[int] = 8

# Compilations permitted per distinct unpruned ``.py`` file in the scan root.
# 1 is both the measured value and the only defensible one: the second parse of
# identical bytes is what ``syntax_error._PARSE_MEMO`` exists to remove.
PARSES_PER_SOURCE_FILE: Final[int] = 1

# Child processes one scan may spawn. Two git invocations are shipped behavior
# (``git log`` for activity, ``git status`` for the working tree); a third would
# mean a collector re-issuing work a sibling already paid for.
CHILD_PROCESS_BUDGET: Final[int] = 2

# Directories the package's walk policy prunes, each seeded in the fixture with
# content the content-collectors would otherwise parse or report.
PRUNED_DIRS: Final[tuple[str, ...]] = (
    "node_modules",
    "dist",
    "__pycache__",
    ".tox",
    ".venv",
    ".git",
)

# The ``.py`` files the fixture plants OUTSIDE any pruned directory. Distinct
# CONTENT is load-bearing: the parse memo is digest-keyed, so two byte-identical
# files would legitimately cost one compile and silently weaken Behavior 4.
UNPRUNED_SOURCES: Final[dict[str, str]] = {
    "pkg/mod_a.py": "x = 1\n# TODO: wire this up\n",
    "pkg/mod_b.py": "def f() -> int:\n    return 2\n",
    # Deliberately INVALID, so the failing-parse path is exercised too and the
    # budget is not measured only over files that compile cleanly.
    "pkg/broken.py": "def f(:\n",
}


@dataclass
class WorkCounters:
    """One scan's tally of the three units of work this module budgets."""

    walks: list[str] = field(default_factory=list)
    compiles: list[str] = field(default_factory=list)
    runs: list[tuple[str, ...]] = field(default_factory=list)


@pytest.fixture(autouse=True)
def _isolate_perception_caches() -> Iterator[None]:
    """No test may inherit or leak provider counters or memoized parse verdicts.

    Both directions matter. Inheriting a warm ``_PARSE_MEMO`` makes Behavior 4
    vacuous (measured: 3 compiles then 0 for identical bytes in one process);
    leaking one makes some LATER module's count depend on this one.
    """
    clear_walk_cache()
    clear_parse_memo()
    yield
    clear_walk_cache()
    clear_parse_memo()


def _write(root: Path, rel: str, content: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    """A small tmp tree that reaches the walking AND the content collectors."""
    root = tmp_path / "ws"
    root.mkdir()
    for rel, content in UNPRUNED_SOURCES.items():
        _write(root, rel, content)
    _write(root, "docs/notes.md", "- TODO: write the docs\n")
    _write(root, "README.md", "# ws\n")
    for name in PRUNED_DIRS:
        _write(root, f"{name}/pruned.py", "def g(:\n")
        _write(root, f"{name}/pruned.md", "- TODO: pruned todo\n")
    return root


def _unpruned_sources(root: Path) -> list[Path]:
    """Every ``.py`` file under *root* that the walk policy does not prune.

    Derived by measurement rather than read off :data:`UNPRUNED_SOURCES`, so the
    two derivations can be cross-checked; Behavior 4 asserts they agree before
    it prices anything against either.
    """
    return [
        path
        for path in sorted(root.rglob("*.py"))
        if not any(
            part in PRUNED_DIRS or part.startswith(".")
            for part in path.relative_to(root).parts
        )
    ]


def _counting_walk(tally: list[str]) -> Callable[..., Any]:
    """A pass-through ``os.walk`` that records the root of each invocation."""

    def wrapper(top: Any, *args: Any, **kwargs: Any) -> Any:
        tally.append(str(top))
        return _REAL_WALK(top, *args, **kwargs)

    return wrapper


def _counting_compile(tally: list[str]) -> Callable[..., Any]:
    """A pass-through ``compile`` that records each invocation's filename."""

    def wrapper(*args: Any, **kwargs: Any) -> Any:
        tally.append(str(args[1] if len(args) > 1 else kwargs.get("filename")))
        return _REAL_COMPILE(*args, **kwargs)

    return wrapper


def _counting_run(tally: list[tuple[str, ...]]) -> Callable[..., Any]:
    """A pass-through ``subprocess.run`` that records each normalised argv.

    Normalising to a tuple of ``str`` is what makes the duplicate check total:
    argv members reach the collectors as ``str`` and ``Path`` alike, and two
    spellings of one command must count as the SAME command here.
    """

    def wrapper(*args: Any, **kwargs: Any) -> Any:
        argv = args[0] if args else kwargs.get("args")
        if isinstance(argv, (list, tuple)):
            tally.append(tuple(str(part) for part in argv))
        else:
            tally.append((str(argv),))
        return _REAL_RUN(*args, **kwargs)

    return wrapper


@pytest.fixture()
def counters(monkeypatch: pytest.MonkeyPatch) -> Iterator[WorkCounters]:
    """Install all three counting shims for ONE test and remove them regardless.

    Teardown is doubled on purpose: the explicit ``monkeypatch.undo()`` in the
    ``finally`` runs even if the test body raises, and pytest's own teardown runs
    even if this fixture is itself interrupted. A leaked ``builtins.compile``
    patch would corrupt every later module in the same xdist worker, so the cost
    of the redundancy is one line and the cost of missing it is the suite.
    """
    tally = WorkCounters()
    monkeypatch.setattr(os, "walk", _counting_walk(tally.walks))
    monkeypatch.setattr(builtins, "compile", _counting_compile(tally.compiles))
    monkeypatch.setattr(subprocess, "run", _counting_run(tally.runs))
    try:
        yield tally
    finally:
        monkeypatch.undo()


# ===========================================================================
# Behavior 1 -- the fixture's isolation is ASSERTED, not assumed
# ===========================================================================


class TestBehavior1FixtureIsolation:
    def test_the_scan_root_is_inside_tmp_path_and_is_not_the_repo_root(
        self, workspace: Path, tmp_path: Path
    ) -> None:
        root = workspace.resolve()
        assert root.is_relative_to(tmp_path.resolve()), (
            "the scan root must live under tmp_path; a budget counted against the "
            f"ambient tree passes only on this machine. root={root}"
        )
        assert root != REPO_ROOT, (
            "the scan root must NOT be the repository root -- the fresh-clone "
            f"release check has no gitignored local state. root={root}"
        )

    def test_the_scan_reports_signals_so_the_budgets_are_not_vacuous(
        self, workspace: Path
    ) -> None:
        # A budget measured over a scan that perceived NOTHING would be green and
        # worthless, so the fixture's reach is pinned before anything is priced.
        snapshot = cli._collect(workspace)
        assert snapshot.signals, (
            "fixture regression -- this tree must reach the collectors, or every "
            "budget below is satisfied by doing no work"
        )


# ===========================================================================
# Behavior 2 -- traversal budget, as a ceiling
# ===========================================================================


class TestBehavior2TraversalBudget:
    def test_one_scan_stays_within_the_traversal_budget(
        self, workspace: Path, counters: WorkCounters
    ) -> None:
        cli._collect(workspace)

        assert len(counters.walks) <= WALK_BUDGET, (
            f"{len(counters.walks)} physical traversals of one root; the budget "
            f"is {WALK_BUDGET}. 1 is the correct number -- LOWER this constant "
            "when a collector is converted onto dir_source.walk; NEVER raise it "
            "to accommodate a new hand-rolled walk."
        )

    def test_the_traversal_budget_is_not_satisfied_by_walking_nothing(
        self, workspace: Path, counters: WorkCounters
    ) -> None:
        cli._collect(workspace)

        assert counters.walks, (
            "a traversal ceiling met by performing ZERO traversals is fail-open; "
            "the shim must observe the scan's real walks"
        )
        assert set(counters.walks) == {str(workspace)}, (
            "every traversal in a scan must be rooted at the scanned root -- a "
            "foreign root means a collector is walking somewhere the budget does "
            f"not describe; got {sorted(set(counters.walks))!r}"
        )


# ===========================================================================
# Behavior 3 -- the shared provider walks each scope exactly once
# ===========================================================================


class TestBehavior3OnePhysicalTraversalPerScope:
    def test_one_scan_leaves_one_miss_and_serves_the_rest(self, workspace: Path) -> None:
        clear_walk_cache()
        cli._collect(workspace)

        stats = walk_cache_stats()
        assert stats["misses"] == 1, (
            "dir_source's contract is ONE physical traversal per scope, so this "
            f"is an equality and not a budget; got {stats!r}"
        )
        assert stats["hits"] >= 1, (
            "the provider must actually SERVE the traversal it paid for; zero "
            f"hits means the cache is present but unused; got {stats!r}"
        )


# ===========================================================================
# Behavior 4 -- parse budget: no source file is compiled twice
# ===========================================================================


class TestBehavior4ParseBudget:
    def test_the_fixture_plants_enough_distinct_sources_to_be_non_trivial(
        self, workspace: Path
    ) -> None:
        sources = _unpruned_sources(workspace)
        assert len(sources) >= 3, f"the fixture needs >=3 unpruned .py files; got {sources!r}"
        assert len(sources) == len(UNPRUNED_SOURCES), (
            "the measured unpruned source set must agree with the declared one, "
            f"or the budget is priced against the wrong number; measured={sources!r}"
        )
        texts = [path.read_text(encoding="utf-8") for path in sources]
        assert len(set(texts)) == len(texts), (
            "two byte-identical sources legitimately cost ONE compile and would "
            "silently weaken this budget; keep the fixture's contents distinct"
        )

    def test_no_source_file_is_compiled_twice(
        self, workspace: Path, counters: WorkCounters
    ) -> None:
        # The file count is held in its own name rather than recovered from the
        # ceiling by division: a ceiling of 0 would make that division raise
        # ZeroDivisionError and replace this guard's verdict with a crash.
        source_count = len(_unpruned_sources(workspace))
        ceiling = PARSES_PER_SOURCE_FILE * source_count

        cli._collect(workspace)

        assert len(counters.compiles) <= ceiling, (
            f"{len(counters.compiles)} compiles for {source_count} "
            f"distinct source files; the budget is {ceiling}. "
            f"{PARSES_PER_SOURCE_FILE} parse per file is the correct number and it "
            "is what syntax_error._PARSE_MEMO exists to guarantee -- LOWER this "
            "constant if a scan learns to skip files entirely; NEVER raise it to "
            f"accommodate a second parse of the same bytes. filenames="
            f"{counters.compiles!r}"
        )
        assert counters.compiles, (
            "a parse ceiling met by compiling NOTHING is fail-open: it is exactly "
            "what a warm _PARSE_MEMO produces, which is why the autouse fixture "
            "clears it"
        )


# ===========================================================================
# Behavior 5 -- child-process budget: bounded AND duplicate-free
# ===========================================================================


class TestBehavior5ChildProcessBudget:
    def test_a_scan_spawns_no_more_than_the_budgeted_child_processes(
        self, workspace: Path, counters: WorkCounters
    ) -> None:
        cli._collect(workspace)

        assert len(counters.runs) <= CHILD_PROCESS_BUDGET, (
            f"{len(counters.runs)} child processes; the budget is "
            f"{CHILD_PROCESS_BUDGET}, which is the two shipped git invocations. "
            "LOWER this constant if a collector stops shelling out; NEVER raise "
            f"it to accommodate a new one. argvs={counters.runs!r}"
        )

    def test_no_two_child_processes_share_an_argv(
        self, workspace: Path, counters: WorkCounters
    ) -> None:
        cli._collect(workspace)

        # The load-bearing half of Behavior 5: it holds on ANY fixture, with or
        # without a .git directory, and it is what catches a second collector
        # re-issuing a command a sibling already ran.
        assert len(set(counters.runs)) == len(counters.runs), (
            "two collectors issued the identical child process in one scan -- the "
            f"second is pure waste; argvs={counters.runs!r}"
        )
        assert counters.runs, (
            "a duplicate-free claim over an EMPTY list is vacuous; the shim must "
            "observe the scan's real child processes"
        )


# ===========================================================================
# Behavior 6 -- the oracle is two-sided: every shim is proved to COUNT
# ===========================================================================


class TestBehavior6TheShimsActuallyCount:
    def test_the_walk_shim_counts_each_call(
        self, tmp_path: Path, counters: WorkCounters
    ) -> None:
        for _ in range(2):
            list(os.walk(tmp_path))

        assert len(counters.walks) == 2, (
            "the traversal counter must record every os.walk call, or Behavior 2 "
            f"is vacuously green; got {counters.walks!r}"
        )

    def test_the_compile_shim_counts_each_call(self, counters: WorkCounters) -> None:
        for index in range(3):
            compile(f"x = {index}\n", "<probe>", "exec")

        assert len(counters.compiles) == 3, (
            "the parse counter must record every compile call, or Behavior 4 is "
            f"vacuously green; got {counters.compiles!r}"
        )

    def test_the_child_process_shim_counts_each_call(self, counters: WorkCounters) -> None:
        # A binary that cannot exist: the shim tallies the call BEFORE delegating,
        # so the count is proved without spawning anything, and OSError covers the
        # FileNotFoundError every platform raises for a missing executable.
        for _ in range(2):
            with pytest.raises(OSError):
                subprocess.run(["pla-no-such-binary-9f3c1d"], capture_output=True)

        assert len(counters.runs) == 2, (
            "the child-process counter must record every subprocess.run call, or "
            f"Behavior 5 is vacuously green; got {counters.runs!r}"
        )

    def test_the_shims_are_absent_outside_the_fixture_that_installs_them(self) -> None:
        # Proves the teardown, not the install: this test never requests
        # ``counters``, so a shim visible here would be one leaked by a sibling.
        assert os.walk is _REAL_WALK
        assert builtins.compile is _REAL_COMPILE
        assert subprocess.run is _REAL_RUN
