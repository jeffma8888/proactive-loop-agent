"""Independent second opinion on iteration 189's per-scan WORK-BUDGET oracle.

WHY A SECOND MODULE. This iteration's shipped artifact IS a test module
(``test_iter192_behavior.py``), so the usual arrangement -- one stage writes the
behavior, another writes the oracle -- has to be turned inside out: the thing
under test is itself an assertion. A module cannot supply its own two-sidedness
control, because every claim it makes about its own rigor is checked by the same
code that makes the claim. So this module verifies, from OUTSIDE, the properties
the spec's Acceptance Criteria demand of that one, and it re-measures the same
three budgets against a fixture it builds itself.

MODULE NAME derived from the repo and never from the state-dir counter (the
operator pin, and the defect that cost factory iteration 186 a shipped oracle):
the highest ``test_iterNN_behavior.py`` in ``git ls-files tests`` is 192, so this
file is 193, and ``git cat-file -e HEAD:tests/test_iter193_behavior.py`` failed
before a byte was written, proving the path free in ``HEAD``.

TWO KINDS OF CHECK LIVE HERE, and the split is deliberate.

STRUCTURAL (ast, no execution) -- the properties the spec requires of the ORACLE
rather than of the product: every budget is a module-level ``Final`` named
constant; every budget comparison is ``<=`` and never ``==``, so no future edit
can quietly convert a ceiling into a ratchet that reds the build on the day a
collector is improved; every ceiling's failure message names its target and
forbids raising it; no scan is ever pointed at the ambient repository; the
patching fixture tears down unconditionally; and nothing anywhere asserts a
duration. These are exactly the claims an oracle cannot make about itself.

BEHAVIORAL (executed, against this module's OWN fixture) -- an independent
re-measurement of the three budgets, plus the control the sibling module cannot
run on itself: that its ceilings actually BIND. A ceiling far above the observed
cost is green and worthless; it would admit a whole new hand-rolled traversal for
free. So the slack between measured work and published budget is itself bounded,
which is what turns the sibling's prose instruction ("LOWER this constant when a
collector is converted") into a machine-checked coupled edit.

HERMETIC. Every scan here runs against a tree built under ``tmp_path``; nothing
reads the ambient repository as a scan root, because a count taken against the
working tree passes only on this machine and breaks in the fresh-clone release
check (the 2026-08-11 operator lesson). No network, no wall clock, and no
assertion on docstring or help-text indentation, so the 3.12 and 3.13 matrix legs
cannot diverge here.

BLACK BOX. This module reads the sibling test module's text and drives the
package's public entry point. It does not read ``src/``.
"""

from __future__ import annotations

import ast
import builtins
import importlib.util
import os
import subprocess
import sys
from collections.abc import Callable, Iterator
from functools import cache
from pathlib import Path
from types import ModuleType
from typing import Any, Final

import pytest

from proactive_loop import cli
from proactive_loop.collectors.dir_source import clear_walk_cache, walk_cache_stats
from proactive_loop.collectors.syntax_error import clear_parse_memo

_REAL_WALK: Final = os.walk
_REAL_COMPILE: Final = builtins.compile
_REAL_RUN: Final = subprocess.run

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[1]

# The module under examination. Both files ship in one commit, so this path is
# tracked wherever this test runs, including a fresh clone.
BUDGET_MODULE: Final[Path] = Path(__file__).with_name("test_iter192_behavior.py")

# The three budgets the spec names. Each must exist as a module-level constant.
REQUIRED_BUDGETS: Final[frozenset[str]] = frozenset(
    {"WALK_BUDGET", "PARSES_PER_SOURCE_FILE", "CHILD_PROCESS_BUDGET"}
)

# How far a published ceiling may sit ABOVE the cost actually measured here.
#
# Zero, and the zero is the whole point. A ceiling with slack is a brake with a
# gap in it: at slack 1 an entire new hand-rolled traversal lands green, which is
# precisely the regression the sibling module exists to stop. Keeping it at zero
# also makes the sibling's own instruction enforceable -- convert a collector and
# the measured cost drops, so the constant MUST be lowered in the same commit or
# this guard reds. That is a coupled edit on purpose: it is one line, and the
# failure message below names it.
MAX_CEILING_SLACK: Final[int] = 0

# Directories the package's walk policy prunes. Seeded with content the content
# collectors would otherwise parse, so pruning is exercised rather than assumed.
PRUNED_DIRS: Final[tuple[str, ...]] = (
    "node_modules",
    "dist",
    "__pycache__",
    ".tox",
    ".venv",
    ".git",
)

# Distinct CONTENT is load-bearing: the parse memo is digest-keyed, so two
# byte-identical files would legitimately cost one compile between them.
UNPRUNED_SOURCES: Final[dict[str, str]] = {
    "pkg/mod_a.py": "y = 41\n# TODO: an independent fixture\n",
    "pkg/mod_b.py": "def h() -> int:\n    return 7\n",
    # Deliberately unparseable, so the failing-parse path is counted too.
    "pkg/wrecked.py": "def h(:\n",
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_perception_caches() -> Iterator[None]:
    """Clear the provider counters and the parse memo on BOTH sides of a test.

    Inheriting a warm parse memo makes a parse budget vacuous, and leaking one
    makes a later module's count depend on this one. The memo is keyed by content
    digest and lives for the life of the process, not the scan.
    """
    clear_walk_cache()
    clear_parse_memo()
    yield
    clear_walk_cache()
    clear_parse_memo()


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    """A small tmp tree, built here, that reaches the walking AND content collectors."""
    root = tmp_path / "independent_ws"
    root.mkdir()
    for rel, content in UNPRUNED_SOURCES.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    (root / "docs").mkdir()
    (root / "docs" / "notes.md").write_text("- TODO: an independent note\n", encoding="utf-8")
    (root / "README.md").write_text("# independent_ws\n", encoding="utf-8")
    for name in PRUNED_DIRS:
        pruned = root / name
        pruned.mkdir()
        (pruned / "pruned.py").write_text("def wrecked(:\n", encoding="utf-8")
        (pruned / "pruned.md").write_text("- TODO: pruned\n", encoding="utf-8")
    return root


class _Tally:
    """One scan's observed work, recorded by pass-through shims."""

    def __init__(self) -> None:
        self.walks: list[str] = []
        self.compiles: list[str] = []
        self.runs: list[tuple[str, ...]] = []


@pytest.fixture()
def tally(monkeypatch: pytest.MonkeyPatch) -> Iterator[_Tally]:
    """Install pass-through counting shims for ONE test and remove them regardless.

    Teardown is doubled: the explicit ``undo()`` in ``finally`` runs even when the
    test body raises, and pytest's own teardown runs even if this fixture is
    interrupted. A leaked ``builtins.compile`` patch would corrupt every later
    module in the same xdist worker.
    """
    counted = _Tally()

    def walk_shim(top: Any, *args: Any, **kwargs: Any) -> Any:
        counted.walks.append(str(top))
        return _REAL_WALK(top, *args, **kwargs)

    def compile_shim(*args: Any, **kwargs: Any) -> Any:
        counted.compiles.append(str(args[1] if len(args) > 1 else kwargs.get("filename")))
        return _REAL_COMPILE(*args, **kwargs)

    def run_shim(*args: Any, **kwargs: Any) -> Any:
        argv = args[0] if args else kwargs.get("args")
        if isinstance(argv, (list, tuple)):
            counted.runs.append(tuple(str(part) for part in argv))
        else:
            counted.runs.append((str(argv),))
        return _REAL_RUN(*args, **kwargs)

    monkeypatch.setattr(os, "walk", walk_shim)
    monkeypatch.setattr(builtins, "compile", compile_shim)
    monkeypatch.setattr(subprocess, "run", run_shim)
    try:
        yield counted
    finally:
        monkeypatch.undo()


# ---------------------------------------------------------------------------
# Reading the module under examination
# ---------------------------------------------------------------------------


def _source() -> str:
    return BUDGET_MODULE.read_text(encoding="utf-8")


def _tree() -> ast.Module:
    return ast.parse(_source())


def _module_constants() -> dict[str, int]:
    """Every module-level ``NAME: Final[int] = <int>`` in the module under test."""
    found: dict[str, int] = {}
    for node in _tree().body:
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and "Final" in ast.unparse(node.annotation)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, int)
            and not isinstance(node.value.value, bool)
        ):
            found[node.target.id] = node.value.value
    return found


# Read ONCE, at import. Calling ``_module_constants()`` from inside a test body
# would run this module's OWN ``ast.parse`` while the compile shim is installed --
# MEASURED here: the tally gained a fourth entry whose filename was ``<unknown>``,
# which is ``ast.parse``'s default, and that extra call was the instrument's, not
# the product's. An instrument that performs the very operation it measures
# inflates its own reading, silently, and in the direction that makes a ceiling
# look tight when it is not being tested at all.
PUBLISHED_BUDGETS: Final[dict[str, int]] = {}


def _names_in(node: ast.AST) -> set[str]:
    return {child.id for child in ast.walk(node) if isinstance(child, ast.Name)}


def _budget_asserts() -> list[ast.Assert]:
    """Asserts that reference a budget constant in their test OR their message.

    The message half matters: the parse budget is compared against a local
    ``ceiling`` alias, and only its failure message names
    ``PARSES_PER_SOURCE_FILE``. Detecting on the test alone would miss it and the
    census would silently under-count.
    """
    out: list[ast.Assert] = []
    for node in ast.walk(_tree()):
        if not isinstance(node, ast.Assert):
            continue
        referenced = _names_in(node.test)
        if node.msg is not None:
            referenced |= _names_in(node.msg)
        if referenced & REQUIRED_BUDGETS:
            out.append(node)
    return out


@cache
def _load_oracle() -> ModuleType:
    """Import the module under examination under its own private name.

    ``exec()`` into a bare dict is NOT enough and the failure is instructive: the
    module declares a ``@dataclass`` under ``from __future__ import annotations``,
    so its annotations are strings, and ``dataclasses`` resolves them by looking
    the owning module up in ``sys.modules``. With no entry there the lookup
    returns ``None`` and raises ``AttributeError`` from inside the standard
    library, nowhere near the real cause. Registering the module before executing
    it is the documented import protocol, so it is what this uses.
    """
    spec = importlib.util.spec_from_file_location("_budget_oracle_probe", BUDGET_MODULE)
    assert spec is not None and spec.loader is not None, f"cannot load {BUDGET_MODULE}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


PUBLISHED_BUDGETS.update(_module_constants())


# ===========================================================================
# Structural -- properties an oracle cannot verify about itself
# ===========================================================================


class TestTheOracleIsShapedTheWayTheSpecRequires:
    def test_the_budget_oracle_module_exists_at_the_derived_path(self) -> None:
        assert BUDGET_MODULE.is_file(), (
            "iteration 189 ships its work budget AS a test module; without that "
            f"file every budget claim in the spec is unenforced. missing={BUDGET_MODULE}"
        )

    def test_every_budget_is_a_module_level_final_named_constant(self) -> None:
        constants = PUBLISHED_BUDGETS
        missing = REQUIRED_BUDGETS - set(constants)
        assert not missing, (
            "each budget must be a module-level Final int constant, or the number "
            "a future contributor is told to LOWER cannot be found; "
            f"missing={sorted(missing)} present={sorted(constants)}"
        )

    def test_every_budget_comparison_is_a_ceiling_and_never_an_equality(self) -> None:
        offenders: list[str] = []
        for node in _budget_asserts():
            if not isinstance(node.test, ast.Compare):
                offenders.append(f"line {node.lineno}: not a comparison")
                continue
            for op in node.test.ops:
                if not isinstance(op, ast.LtE):
                    offenders.append(f"line {node.lineno}: {type(op).__name__}")
        assert not offenders, (
            "a budget asserted with == or < is a RATCHET, not a ceiling: it reds "
            "the build on the day a collector is converted onto the shared walk "
            "provider, which is the improvement this oracle exists to protect. "
            f"Use <=. offenders={offenders}"
        )

    def test_the_census_of_budget_assertions_is_not_empty(self) -> None:
        # Two-sidedness for the check above: an AST predicate that matches
        # nothing reports every property as satisfied.
        found = _budget_asserts()
        assert len(found) >= len(REQUIRED_BUDGETS), (
            "each of the three budgets must be ASSERTED somewhere, or the check "
            f"above passes by matching nothing; found {len(found)} at lines "
            f"{[node.lineno for node in found]}"
        )

    def test_every_ceiling_failure_message_names_its_target_and_forbids_raising(
        self,
    ) -> None:
        source = _source()
        offenders: list[int] = []
        for node in _budget_asserts():
            if node.msg is None:
                offenders.append(node.lineno)
                continue
            message = ast.get_source_segment(source, node.msg) or ""
            if "never raise" not in message.lower():
                offenders.append(node.lineno)
        assert not offenders, (
            "a ceiling whose failure message does not forbid raising the constant "
            "teaches the next contributor to raise it, which converts the brake "
            f"into a rubber stamp; offending asserts at lines {offenders}"
        )

    def test_the_providers_one_walk_per_scope_contract_stays_an_equality(self) -> None:
        source = _source()
        equalities = [
            node.lineno
            for node in ast.walk(_tree())
            if isinstance(node, ast.Assert)
            and isinstance(node.test, ast.Compare)
            and any(isinstance(op, ast.Eq) for op in node.test.ops)
            and "misses" in (ast.get_source_segment(source, node.test) or "")
        ]
        assert equalities, (
            "one physical traversal per scope is dir_source's correctness "
            "contract, not a budget with slack, so the misses assertion must be "
            "an equality; found none"
        )

    def test_no_scan_in_the_oracle_is_pointed_at_the_ambient_repository(self) -> None:
        collects = [
            node
            for node in ast.walk(_tree())
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "_collect"
        ]
        assert collects, "the oracle must actually drive a scan; found no _collect call"
        foreign = [
            node.lineno
            for node in collects
            if not (node.args and isinstance(node.args[0], ast.Name))
        ]
        assert not foreign, (
            "every scan must be rooted at a fixture-built tmp tree; a literal "
            "path, a cwd or a repo-root expression makes the count pass only on "
            f"this machine and red in a fresh clone. lines={foreign}"
        )

    def test_the_patching_fixture_tears_down_unconditionally(self) -> None:
        source = _source()
        patchers = [
            node
            for node in ast.walk(_tree())
            if isinstance(node, ast.FunctionDef)
            and "monkeypatch.setattr" in (ast.get_source_segment(source, node) or "")
        ]
        assert patchers, "the oracle installs no shim; behaviors 2, 4 and 5 cannot be measured"
        for func in patchers:
            tries = [node for node in ast.walk(func) if isinstance(node, ast.Try)]
            assert any(node.finalbody for node in tries), (
                f"fixture {func.name!r} installs a process-global patch without a "
                "finally: a failing test then leaks builtins.compile into every "
                "later module in the same xdist worker"
            )

    def test_the_oracle_asserts_no_duration_anywhere(self) -> None:
        tree = _tree()
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        banned = imported & {"time", "timeit", "datetime", "resource"}
        assert not banned, (
            "counts only: a millisecond threshold is flaky on a shared CI runner "
            f"and would red a public portfolio badge for nobody's fault; got {sorted(banned)}"
        )
        source = _source()
        for token in ("perf_counter", "monotonic", "process_time"):
            assert token not in source, f"wall-clock token {token!r} found in a count-based oracle"


# ===========================================================================
# Behavioral -- the same budgets, re-measured against an independent fixture
# ===========================================================================


class TestTheBudgetsHoldOnAnIndependentFixture:
    def test_the_fixture_is_hermetic_and_the_scan_perceives_something(
        self, workspace: Path, tmp_path: Path
    ) -> None:
        root = workspace.resolve()
        assert root.is_relative_to(tmp_path.resolve()), f"scan root escaped tmp_path: {root}"
        assert root != REPO_ROOT, f"scan root must not be the repository root: {root}"
        snapshot = cli._collect(workspace)
        assert snapshot.signals, (
            "fixture regression -- a budget measured over a scan that perceived "
            "NOTHING is green and worthless"
        )

    def test_one_scan_stays_within_every_published_budget(
        self, workspace: Path, tally: _Tally
    ) -> None:
        constants = PUBLISHED_BUDGETS
        distinct_sources = len(UNPRUNED_SOURCES)

        cli._collect(workspace)

        assert 0 < len(tally.walks) <= constants["WALK_BUDGET"], (
            f"{len(tally.walks)} traversals against a published WALK_BUDGET of "
            f"{constants['WALK_BUDGET']}; a count of zero would mean the shim, not "
            "the product, is broken"
        )
        parse_ceiling = constants["PARSES_PER_SOURCE_FILE"] * distinct_sources
        assert 0 < len(tally.compiles) <= parse_ceiling, (
            f"{len(tally.compiles)} compiles for {distinct_sources} distinct "
            f"sources against a ceiling of {parse_ceiling}; files={tally.compiles!r}"
        )
        assert 0 < len(tally.runs) <= constants["CHILD_PROCESS_BUDGET"], (
            f"{len(tally.runs)} child processes against a published "
            f"CHILD_PROCESS_BUDGET of {constants['CHILD_PROCESS_BUDGET']}; "
            f"argvs={tally.runs!r}"
        )

    def test_every_published_ceiling_actually_binds(
        self, workspace: Path, tally: _Tally
    ) -> None:
        # THE control the sibling module cannot run on itself. A ceiling above
        # the observed cost is green and admits new waste for free.
        constants = PUBLISHED_BUDGETS

        cli._collect(workspace)

        measured = {
            "WALK_BUDGET": len(tally.walks),
            "PARSES_PER_SOURCE_FILE": len(tally.compiles) // len(UNPRUNED_SOURCES),
            "CHILD_PROCESS_BUDGET": len(tally.runs),
        }
        slack = {
            name: constants[name] - observed
            for name, observed in measured.items()
            if constants[name] - observed > MAX_CEILING_SLACK
        }
        assert not slack, (
            "a published ceiling sits ABOVE the work actually measured, so that "
            "much new waste would land GREEN. LOWER the named constant in "
            "tests/test_iter192_behavior.py to the measured value -- which is what "
            "its own failure messages already instruct -- and never raise it. "
            f"slack={slack} measured={measured} published="
            f"{ {name: constants[name] for name in measured} }"
        )

    def test_every_compile_in_one_scan_names_a_real_file_under_the_scanned_root(
        self, workspace: Path, tally: _Tally
    ) -> None:
        cli._collect(workspace)

        root = str(workspace)
        foreign = [name for name in tally.compiles if not name.startswith(root)]
        assert not foreign, (
            "every parse a scan performs must be of a file inside the scanned "
            "root. This guard doubles as the parse budget's instrument check: a "
            "helper that calls ast.parse inside the patched window contributes a "
            "phantom '<unknown>' entry and inflates the count silently, which is "
            "how a ceiling gets met by measuring the measurer. If the product "
            "legitimately learns to parse a snippet, add a NAMED allowance and "
            f"say so here. foreign={foreign!r}"
        )
        assert len(set(tally.compiles)) == len(tally.compiles), (
            "no source file may be compiled twice in one scan -- that is exactly "
            "what syntax_error._PARSE_MEMO exists to guarantee, and counting "
            f"DISTINCT filenames says so directly rather than by proxy. "
            f"files={tally.compiles!r}"
        )

    def test_no_two_child_processes_in_one_scan_share_an_argv(
        self, workspace: Path, tally: _Tally
    ) -> None:
        cli._collect(workspace)

        assert tally.runs, "a duplicate-free claim over an empty list is vacuous"
        duplicates = [argv for argv in tally.runs if tally.runs.count(argv) > 1]
        assert not duplicates, (
            "two collectors issued the identical child process in one scan; the "
            f"second is pure waste. duplicates={duplicates!r}"
        )

    def test_every_traversal_in_one_scan_is_rooted_at_the_scanned_root(
        self, workspace: Path, tally: _Tally
    ) -> None:
        cli._collect(workspace)

        assert set(tally.walks) == {str(workspace)}, (
            "a traversal rooted anywhere but the scanned root is work the budget "
            f"does not describe; got {sorted(set(tally.walks))!r}"
        )

    def test_the_shared_provider_walks_each_scope_once_and_serves_the_rest(
        self, workspace: Path
    ) -> None:
        clear_walk_cache()
        cli._collect(workspace)

        stats = walk_cache_stats()
        assert stats["misses"] == 1, (
            f"one physical traversal per scope is a contract, not a budget; got {stats!r}"
        )
        assert stats["hits"] >= 1, (
            f"the provider must SERVE the traversal it paid for; got {stats!r}"
        )


# ===========================================================================
# The shims the oracle relies on are pass-through, not just counting
# ===========================================================================


class TestTheOraclesShimsPreserveBehaviorAndNotOnlyCount:
    """A counter that breaks its callable would corrupt the scan it measures.

    The sibling module proves its shims COUNT. It never proves they still
    RETURN what the real callable returns -- and a ``compile`` wrapper that
    dropped the code object would break the syntax collector while every budget
    stayed green, since the calls were still tallied.
    """

    @staticmethod
    def _factories() -> dict[str, Callable[..., Any]]:
        module = _load_oracle()
        return {
            name: getattr(module, name)
            for name in ("_counting_walk", "_counting_compile", "_counting_run")
            if hasattr(module, name)
        }

    def test_the_oracle_exposes_the_three_counting_shims(self) -> None:
        assert set(self._factories()) == {
            "_counting_walk",
            "_counting_compile",
            "_counting_run",
        }, (
            "the three shim factories are the mechanism behaviors 2, 4 and 5 rest "
            f"on; found {sorted(self._factories())}"
        )

    def test_the_walk_shim_counts_and_still_yields_the_real_listing(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "a").mkdir()
        (tmp_path / "a" / "f.txt").write_text("x\n", encoding="utf-8")
        seen: list[str] = []
        shim = self._factories()["_counting_walk"](seen)

        assert list(shim(tmp_path)) == list(_REAL_WALK(tmp_path)), (
            "the walk shim must be transparent; a shim that alters the listing "
            "changes the scan it claims only to measure"
        )
        assert seen == [str(tmp_path)], f"the walk shim must tally each call; got {seen!r}"

    def test_the_compile_shim_counts_and_still_returns_a_usable_code_object(self) -> None:
        seen: list[str] = []
        shim = self._factories()["_counting_compile"](seen)

        code = shim("value = 6 * 7\n", "<probe>", "exec")
        namespace: dict[str, Any] = {}
        exec(code, namespace)  # noqa: S102

        assert namespace["value"] == 42, (
            "the compile shim must return the real code object; one that returned "
            "None would break the syntax collector while every count stayed green"
        )
        assert len(seen) == 1, f"the compile shim must tally each call; got {seen!r}"

    def test_the_child_process_shim_counts_before_it_delegates(self) -> None:
        seen: list[tuple[str, ...]] = []
        shim = self._factories()["_counting_run"](seen)

        # A binary that cannot exist: the tally must be recorded even when the
        # delegation raises, which is what makes the count total.
        with pytest.raises(OSError):
            shim(["pla-no-such-binary-4b7e2a"], capture_output=True)

        assert seen == [("pla-no-such-binary-4b7e2a",)], (
            f"the child-process shim must tally each call as a normalised argv; got {seen!r}"
        )


def test_no_counting_shim_leaks_out_of_the_fixture_that_installed_it() -> None:
    # Requests no fixture on purpose: a shim visible here is one a sibling leaked.
    assert os.walk is _REAL_WALK
    assert builtins.compile is _REAL_COMPILE
    assert subprocess.run is _REAL_RUN
