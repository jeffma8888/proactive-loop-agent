"""Independent second opinion on iteration 231's PER-PATH I/O-budget oracle.

WHY A SECOND MODULE. This iteration's shipped artifact IS a test module
(``test_iter208_behavior.py``), so the usual arrangement -- one stage writes the
behavior, another writes the oracle -- has to be turned inside out: the thing under
test is itself an assertion. A module cannot supply its own two-sidedness control,
because every claim it makes about its own rigor is checked by the same code that
makes the claim. So this module verifies, from OUTSIDE, the properties this
iteration's Expected Behaviors demand of that one, and it re-measures both budgets
against a fixture and an instrument it builds itself. It follows the arrangement
``test_iter193_behavior.py`` already uses over ``test_iter192_behavior.py``.

MODULE NAME derived from the repo and never from the state-dir counter (the operator
pin, and the defect that cost factory iteration 186 a shipped oracle): the highest
tracked ``test_iterNN_behavior.py`` is 207 and the engineer's new module takes 208,
so this file is 209, and ``git cat-file -e HEAD:tests/test_iter209_behavior.py``
failed before a byte was written, proving the path free in ``HEAD``.

THREE KINDS OF CHECK LIVE HERE, and the split is deliberate.

STRUCTURAL (``ast``, nothing executed) -- the properties the spec requires of the
ORACLE rather than of the product: both budgets are module-level ``Final`` named
constants; the binding fraction is a real fraction; NO comparison anywhere tests a
budget for equality **in either operand order and with either equality operator**;
every ceiling's failure message names its constant and forbids editing it to green;
no scan is ever pointed at the ambient repository; the patching helper restores in a
``finally``; and nothing imports a clock. These are exactly the claims an oracle
cannot make about itself.

RE-MEASURED (executed, against a fixture and shims this module builds) -- an
independent confirmation that the two published ceilings are true off their own
fixture and still BIND there. A ceiling measured only by the module that publishes it
is a self-report.

MUTATION (executed, against the sibling's own code) -- the control the sibling cannot
run on itself: with a budget lowered under it, its ceiling assertions must actually
FAIL, and the failure text must carry the path it measured and the remedy sentence.
An oracle that cannot be made to fail is decoration, and reading its source can never
establish that it bites.

HERMETIC. Every scan here runs against a tree built under ``tmp_path``; nothing reads
the ambient repository as a scan root, because a count taken against the working tree
passes only on this machine and breaks in the fresh-clone release check (the
2026-08-11 operator lesson). No network, no wall clock, and no assertion on a
docstring or on help-text indentation, so the 3.12 and 3.13 matrix legs cannot
diverge here.

BLACK BOX. This module reads the sibling test module's text, imports it under a
private name, and drives the package's public entry point. It does not read ``src/``.
"""

from __future__ import annotations

import ast
import importlib.util
import os
import sys
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from functools import cache
from pathlib import Path
from types import ModuleType
from typing import Any, Final

import pytest

from proactive_loop import cli

BUDGET_MODULE: Final[Path] = Path(__file__).with_name("test_iter208_behavior.py")

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[1]

REQUIRED_BUDGETS: Final[frozenset[str]] = frozenset({"STATS_PER_PATH", "DECODES_PER_PATH"})

# The sentence every budget failure must end with, quoted from this iteration's
# Expected Behavior 8 rather than from the module under test -- so the check is
# against the SPEC and cannot be satisfied by rewording both sides at once.
REMEDY_PHRASE: Final[str] = "fresh measurement recorded in the commit"

# Captured at import, BEFORE anything in this process patches them, so the teardown
# checks below compare against the genuine callables and not a sibling's shim.
_REAL_STAT: Final = Path.stat
_REAL_READ_TEXT: Final = Path.read_text


def _source() -> str:
    return BUDGET_MODULE.read_text(encoding="utf-8")


@cache
def _tree() -> ast.Module:
    return ast.parse(_source())


def _module_constants() -> dict[str, object]:
    """Every module-level ``NAME: Final[...] = <literal>`` in the module under test."""
    found: dict[str, object] = {}
    for node in _tree().body:
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and "Final" in ast.unparse(node.annotation)
            and isinstance(node.value, ast.Constant)
        ):
            found[node.target.id] = node.value.value
    return found


def _names_in(node: ast.AST) -> set[str]:
    return {child.id for child in ast.walk(node) if isinstance(child, ast.Name)}


def _budget_comparisons() -> list[tuple[ast.Compare, set[str]]]:
    """Every ``ast.Compare`` that mentions a budget constant on EITHER side.

    Operand order is the point. The module under test bans equality with a text
    search for ``"== " + name``, which is one-sided: it cannot see
    ``name + " =="`` and it cannot see ``!=`` at all. Comparing over the parse tree
    is order-free and operator-complete, which is the property a guard against
    "someone converted this ceiling into a ratchet" actually needs.
    """
    out: list[tuple[ast.Compare, set[str]]] = []
    for node in ast.walk(_tree()):
        if not isinstance(node, ast.Compare):
            continue
        referenced: set[str] = set()
        for side in (node.left, *node.comparators):
            referenced |= _names_in(side)
        overlap = referenced & REQUIRED_BUDGETS
        if overlap:
            out.append((node, overlap))
    return out


def _module_functions() -> dict[str, ast.FunctionDef]:
    return {
        node.name: node for node in _tree().body if isinstance(node, ast.FunctionDef)
    }


def _expanded_message(node: ast.Assert) -> str:
    """An assert's message text with any module-level helper it CALLS inlined.

    MEASURED, and the reason this indirection is followed at all: the sibling factors
    its shared remedy sentence into ``_raise_only_with_a_measurement(...)`` and
    concatenates the result, so a scan of the message alone finds the call and not the
    sentence -- this very check reported BOTH budgets unremedied before it followed one
    level of calls. Same defect class as pricing a ceiling that is compared against a
    LOCAL alias: the text is one hop away from where the scan looks.
    """
    if node.msg is None:
        return ""
    text = ast.unparse(node.msg)
    helpers = _module_functions()
    for call in ast.walk(node.msg):
        if not isinstance(call, ast.Call):
            continue
        name = ast.unparse(call.func)
        body = helpers.get(name)
        if body is not None:
            text += "\n" + ast.unparse(body)
    return text


def _budget_asserts() -> list[ast.Assert]:
    """Asserts naming a budget in their test OR in their message.

    The message half is load-bearing: each ceiling is compared against a LOCAL alias
    (``floor``), so only the failure message names the constant. Detecting on the
    test alone would silently under-count the census.
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

    ``exec()`` into a bare dict is NOT enough, and the failure is instructive: that
    module declares a ``@dataclass`` under ``from __future__ import annotations``, so
    its annotations are strings and ``dataclasses`` resolves them by looking the
    owning module up in ``sys.modules``. With no entry there the lookup returns
    ``None`` and raises from inside the standard library, nowhere near the cause.
    Registering the module before executing it is the documented import protocol.
    """
    spec = importlib.util.spec_from_file_location("_per_path_budget_probe", BUDGET_MODULE)
    assert spec is not None and spec.loader is not None, f"cannot load {BUDGET_MODULE}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# This module's OWN instrument and OWN fixture. Deliberately not the sibling's:
# a re-measurement that borrows the instrument it is checking measures nothing.
# ---------------------------------------------------------------------------


@contextmanager
def _own_instrument() -> Iterator[tuple[Counter[str], Counter[str]]]:
    stats: Counter[str] = Counter()
    decodes: Counter[str] = Counter()

    def stat_shim(self: Path, *args: Any, **kwargs: Any) -> Any:
        stats[str(self)] += 1
        return _REAL_STAT(self, *args, **kwargs)

    def read_text_shim(self: Path, *args: Any, **kwargs: Any) -> Any:
        decodes[str(self)] += 1
        return _REAL_READ_TEXT(self, *args, **kwargs)

    Path.stat = stat_shim  # type: ignore[method-assign]
    Path.read_text = read_text_shim  # type: ignore[method-assign]
    try:
        yield stats, decodes
    finally:
        Path.stat = _REAL_STAT  # type: ignore[method-assign]
        Path.read_text = _REAL_READ_TEXT  # type: ignore[method-assign]


def _resolved_within(root: Path, tally: Counter[str]) -> Counter[str]:
    """Merge onto real paths, then keep only what lies under *root*.

    Merging matters on macOS, where ``tmp_path`` reaches collectors both as
    ``/var/...`` and ``/private/var/...``; counting those apart HALVES an observed
    fan-out. Restricting to *root* matters because patching ``Path`` is a
    process-global rebind, so pytest's own machinery lands in the raw tally.
    """
    real_root = Path(os.path.realpath(root))
    merged: Counter[str] = Counter()
    for raw, count in tally.items():
        merged[os.path.realpath(raw)] += count
    return Counter(
        {path: count for path, count in merged.items() if Path(path).is_relative_to(real_root)}
    )


def _peak(counts: Counter[str]) -> tuple[str, int]:
    if not counts:
        return ("", 0)
    path, count = counts.most_common(1)[0]
    return (path, count)


@pytest.fixture()
def own_workspace(tmp_path: Path) -> Path:
    """A tmp tree of this module's own shape -- NOT a copy of the sibling's.

    Different file names, different counts and different pruned directories, so a
    ceiling that happens to hold only for one exact fixture cannot pass here.
    """
    root = tmp_path / "second_opinion_ws"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "alpha.py").write_text("y = 3\n# TODO: alpha\n", encoding="utf-8")
    (root / "pkg" / "beta.py").write_text("def h() -> int:\n    return 7\n", encoding="utf-8")
    (root / "pkg" / "unparseable.py").write_text("def h(:\n", encoding="utf-8")
    (root / "docs").mkdir()
    (root / "docs" / "notes.md").write_text("- TODO: independent notes\n", encoding="utf-8")
    (root / "README.md").write_text("# second opinion\n", encoding="utf-8")
    for pruned in ("node_modules", "dist", "__pycache__", ".git"):
        (root / pruned).mkdir()
        (root / pruned / "hidden.py").write_text("def z(:\n", encoding="utf-8")
        (root / pruned / "hidden.md").write_text("- TODO: pruned\n", encoding="utf-8")
    return root


@pytest.fixture(autouse=True)
def _cold_caches() -> Iterator[None]:
    """Clear the perception caches through the module under test's own imports.

    A warm walk cache makes a scan cheaper than a real one, so every ceiling below
    would be met by work that never happened -- and under ``-n auto`` test order is
    not stable, so a verdict that depends on which sibling ran first is not a
    verdict.
    """
    oracle = _load_oracle()
    oracle.clear_walk_cache()
    oracle.clear_parse_memo()
    yield
    oracle.clear_walk_cache()
    oracle.clear_parse_memo()


def _ceiling_entry_points() -> list[tuple[str, str, str]]:
    """``(class, method, budget)`` for every ceiling assertion, DISCOVERED not named.

    The mutation tests below have to invoke the sibling's ceiling checks, and
    hardcoding their names would make this module a transcription of that one. So the
    entry points are read off the parse tree: any ``assert <expr> <= <budget>`` inside
    a class method IS a ceiling check, whatever it is called.
    """
    found: list[tuple[str, str, str]] = []
    for klass in _tree().body:
        if not isinstance(klass, ast.ClassDef):
            continue
        for func in klass.body:
            if not isinstance(func, ast.FunctionDef):
                continue
            for node in ast.walk(func):
                if not isinstance(node, ast.Assert) or not isinstance(node.test, ast.Compare):
                    continue
                compare = node.test
                if not any(isinstance(op, ast.LtE) for op in compare.ops):
                    continue
                names: set[str] = set()
                for side in (compare.left, *compare.comparators):
                    names |= _names_in(side)
                for budget in sorted(names & REQUIRED_BUDGETS):
                    found.append((klass.name, func.name, budget))
    return found


def _collect_calls() -> list[ast.Call]:
    return [
        node
        for node in ast.walk(_tree())
        if isinstance(node, ast.Call) and ast.unparse(node.func).endswith("_collect")
    ]


# ===========================================================================
# STRUCTURAL -- properties an oracle cannot establish about itself
# ===========================================================================


class TestTheOracleIsShapedTheWayTheSpecRequires:
    def test_the_per_path_budget_oracle_exists_at_the_derived_path(self) -> None:
        assert BUDGET_MODULE.is_file(), (
            "iteration 231 ships its per-path I/O budgets AS a test module; without "
            f"that file every budget claim in the spec is unenforced. missing={BUDGET_MODULE}"
        )

    def test_both_per_path_budgets_are_module_level_final_int_constants(self) -> None:
        constants = _module_constants()
        missing = REQUIRED_BUDGETS - set(constants)
        assert not missing, (
            "each budget must be a module-level Final int constant, or the number a "
            "future contributor is told to LOWER cannot be found; "
            f"missing={sorted(missing)} present={sorted(constants)}"
        )
        for name in sorted(REQUIRED_BUDGETS):
            value = constants[name]
            assert isinstance(value, int) and not isinstance(value, bool), (
                f"{name} must be an int literal so the ceiling is readable at a glance "
                f"and diffable in review; got {value!r}"
            )
            assert value > 0, f"{name}={value!r} would forbid all work, not bound it"

    def test_the_binding_fraction_is_a_real_fraction(self) -> None:
        constants = _module_constants()
        fraction = constants.get("MIN_BINDING_FRACTION")
        assert isinstance(fraction, float), (
            "Expected Behavior 4 needs a published floor as a fraction of each "
            f"ceiling, or 'the budget BINDS' is prose; got {fraction!r}"
        )
        assert 0.0 < fraction <= 1.0, (
            f"MIN_BINDING_FRACTION={fraction!r} is not a fraction: at or below 0 the "
            "floor admits everything and the ceiling stops binding, above 1 no "
            "measurement can ever satisfy it"
        )

    def test_no_comparison_tests_a_budget_for_equality_in_either_operand_order(
        self,
    ) -> None:
        # THE VALUE THIS ADDS over the module's own guard: that one searches its text
        # for "== " + name, which cannot see `name + " =="` and cannot see `!=` at
        # all. Over the parse tree both operand orders and both equality operators
        # are covered at once.
        offenders = [
            (ast.unparse(compare), sorted(budgets))
            for compare, budgets in _budget_comparisons()
            if any(isinstance(op, (ast.Eq, ast.NotEq)) for op in compare.ops)
        ]
        assert not offenders, (
            "a budget must be asserted with an ORDERING operator only. An equality "
            "blesses today's measured waste and reds the build on the day a "
            "contributor removes it -- the exact improvement these budgets exist to "
            f"protect. found={offenders}"
        )

    def test_every_budget_comparison_is_an_ordering_comparison(self) -> None:
        comparisons = _budget_comparisons()
        assert comparisons, (
            "no comparison anywhere mentions a budget, so this whole guard is "
            "vacuous -- the constants would be documentation, not oracles"
        )
        allowed = (ast.LtE, ast.Lt, ast.GtE, ast.Gt)
        for compare, budgets in comparisons:
            for op in compare.ops:
                assert isinstance(op, allowed), (
                    f"{sorted(budgets)} is compared with {type(op).__name__}, which is "
                    "neither a ceiling nor a floor; only ordering comparisons keep an "
                    f"improvement green. in: {ast.unparse(compare)}"
                )

    def test_each_budget_failure_message_names_its_constant_and_its_remedy(self) -> None:
        asserts = _budget_asserts()
        assert asserts, "no assertion references a budget at all"
        remedied: set[str] = set()
        for node in asserts:
            if node.msg is None:
                continue
            if REMEDY_PHRASE in _expanded_message(node):
                remedied |= _names_in(node.msg) & REQUIRED_BUDGETS
        missing = REQUIRED_BUDGETS - remedied
        assert not missing, (
            "Expected Behavior 8: every budget failure must state that the ceiling may "
            f"be raised ONLY with a {REMEDY_PHRASE!r}, or the cheapest way to green a "
            f"red build is to edit the number. budgets without that sentence: "
            f"{sorted(missing)}"
        )

    def test_no_scan_is_ever_pointed_at_the_ambient_repository(self) -> None:
        calls = _collect_calls()
        assert calls, (
            "the module performs no scan at all, so every budget in it is vacuous"
        )
        for call in calls:
            assert len(call.args) == 1 and not call.keywords, (
                f"a scan must name exactly one root; got {ast.unparse(call)}"
            )
            argument = ast.unparse(call.args[0])
            assert "REPO_ROOT" not in argument and "__file__" not in argument, (
                "the scan root must be a tmp fixture, never the working tree: a count "
                "taken against the ambient repository passes only on this machine and "
                f"breaks the fresh-clone release check. got {ast.unparse(call)}"
            )
            assert not isinstance(call.args[0], ast.Constant), (
                f"an absolute or literal scan root is not hermetic; got {argument}"
            )

    def test_every_scanning_test_runs_exactly_one_scan(self) -> None:
        # Expected Behavior 1. Two scans in one window would double every tally and a
        # per-path ceiling would then be measuring the test, not the product.
        for klass in _tree().body:
            if not isinstance(klass, ast.ClassDef):
                continue
            for func in klass.body:
                if not isinstance(func, ast.FunctionDef):
                    continue
                scans = [
                    node
                    for node in ast.walk(func)
                    if isinstance(node, ast.Call) and ast.unparse(node.func).endswith("_collect")
                ]
                assert len(scans) <= 1, (
                    f"{klass.name}.{func.name} runs {len(scans)} scans in one test; "
                    "each extra scan inflates every per-path count it then prices"
                )

    def test_the_instrument_restores_the_real_callables_in_a_finally(self) -> None:
        finallys = [
            node.finalbody
            for node in ast.walk(_tree())
            if isinstance(node, ast.Try) and node.finalbody
        ]
        assert finallys, (
            "Expected Behavior 7: nothing restores Path.stat in a finally, so a raising "
            "scan leaks a process-global patch into every later module in the worker"
        )
        restoring = [
            body
            for body in finallys
            if all(
                target in "\n".join(ast.unparse(stmt) for stmt in body)
                for target in ("Path.stat", "Path.read_text")
            )
        ]
        assert restoring, (
            "a finally exists but does not restore BOTH Path.stat and Path.read_text; "
            "restoring one of two leaks the other"
        )

    def test_nothing_imports_a_clock(self) -> None:
        imported: set[str] = set()
        for node in ast.walk(_tree()):
            if isinstance(node, ast.Import):
                imported |= {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        banned = imported & {"time", "timeit", "datetime", "resource"}
        assert not banned, (
            "a wall-clock budget is regime-dependent and would flake on a loaded "
            "public CI runner, which is why this iteration budgets CALL COUNTS; "
            f"clock imports found: {sorted(banned)}"
        )


# ===========================================================================
# RE-MEASURED -- the published ceilings, checked with an independent instrument
# ===========================================================================


class TestTheBudgetsHoldOffTheirOwnFixture:
    def test_my_own_instrument_counts_exactly_the_calls_made(self, tmp_path: Path) -> None:
        # Two-sidedness of THIS module's shims, established before anything is
        # measured with them: a re-measurement taken with a silent instrument agrees
        # with any ceiling at all.
        probe = tmp_path / "probe.txt"
        probe.write_text("x\n", encoding="utf-8")

        with _own_instrument() as (stats, decodes):
            for _ in range(3):
                probe.stat()
            for _ in range(2):
                probe.read_text(encoding="utf-8")

        key = os.path.realpath(probe)
        assert _resolved_within(tmp_path, stats)[key] == 3
        assert _resolved_within(tmp_path, decodes)[key] == 2
        assert Path.stat is _REAL_STAT and Path.read_text is _REAL_READ_TEXT

    def test_one_scan_of_my_fixture_respects_both_published_ceilings(
        self, own_workspace: Path
    ) -> None:
        oracle = _load_oracle()

        with _own_instrument() as (stats, decodes):
            snapshot = cli._collect(own_workspace)

        stat_counts = _resolved_within(own_workspace, stats)
        decode_counts = _resolved_within(own_workspace, decodes)
        worst_stat_path, worst_stats = _peak(stat_counts)
        worst_decode_path, worst_decodes = _peak(decode_counts)

        # Behavior 5 -- anti-vacuity, asserted before the ceilings are priced.
        assert stat_counts, "the scan stat'ed nothing, so a stat ceiling is vacuous"
        assert decode_counts, "the scan decoded nothing, so a decode ceiling is vacuous"
        assert snapshot.signals, "the scan perceived nothing; the fixture misses the collectors"

        # Behavior 2/3 -- the ceilings hold on a fixture the sibling never saw.
        assert worst_stats <= oracle.STATS_PER_PATH, (
            f"{worst_stats} stat calls on ONE path ({worst_stat_path}) against a "
            f"published ceiling of {oracle.STATS_PER_PATH}. Measured with an "
            "independent instrument on an independent fixture, so this is the product's "
            "fan-out and not the sibling fixture's shape."
        )
        assert worst_decodes <= oracle.DECODES_PER_PATH, (
            f"{worst_decodes} read_text calls on ONE path ({worst_decode_path}) against "
            f"a published ceiling of {oracle.DECODES_PER_PATH}, measured independently."
        )

    def test_both_ceilings_still_bind_on_my_fixture(self, own_workspace: Path) -> None:
        # Behavior 4, re-derived. A ceiling that binds only against the fixture that
        # chose it is a self-report; if it is slack HERE it is slack.
        oracle = _load_oracle()

        with _own_instrument() as (stats, decodes):
            cli._collect(own_workspace)

        for label, tally, budget in (
            ("stat", stats, oracle.STATS_PER_PATH),
            ("read_text", decodes, oracle.DECODES_PER_PATH),
        ):
            path, observed = _peak(_resolved_within(own_workspace, tally))
            floor = budget * oracle.MIN_BINDING_FRACTION
            assert observed >= floor, (
                f"the worst path ({path}) shows {observed} {label} calls against a "
                f"published ceiling of {budget}, under the "
                f"{oracle.MIN_BINDING_FRACTION:.0%} floor of {floor:g}. A ceiling that "
                "far above the truth cannot catch a regression: LOWER it to the "
                "measured value and record that measurement in the commit."
            )


# ===========================================================================
# MUTATION -- the control the sibling cannot run on itself
# ===========================================================================


class TestTheShippedCeilingsActuallyBite:
    def test_the_ceiling_assertions_were_discovered_not_assumed(self) -> None:
        entry_points = _ceiling_entry_points()
        covered = {budget for _, _, budget in entry_points}
        assert covered == set(REQUIRED_BUDGETS), (
            "every budget needs a discoverable `assert observed <= BUDGET` for the "
            f"mutation below to exercise; found {sorted(covered)} in "
            f"{[(k, f) for k, f, _ in entry_points]}"
        )

    @pytest.mark.parametrize("entry_point", _ceiling_entry_points(), ids=lambda ep: ep[2])
    def test_lowering_a_budget_under_the_oracle_makes_it_fail_loudly(
        self,
        entry_point: tuple[str, str, str],
        own_workspace: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        class_name, method_name, budget = entry_point
        oracle = _load_oracle()

        # 1 is below every measured per-path count, so the ceiling MUST break. This is
        # the only way to establish that an assertion bites; reading its source cannot.
        monkeypatch.setattr(oracle, budget, 1)
        method = getattr(getattr(oracle, class_name)(), method_name)

        with pytest.raises(AssertionError) as failure:
            method(own_workspace)

        message = str(failure.value)
        assert str(own_workspace.resolve()) in message or os.path.realpath(
            own_workspace
        ) in message, (
            "Expected Behavior 8: a budget failure must name the PATH it measured, or "
            f"the reader has to re-derive it by hand. message={message!r}"
        )
        assert REMEDY_PHRASE in message, (
            "Expected Behavior 8: the failure must say the ceiling may be raised only "
            f"with a {REMEDY_PHRASE!r}. message={message!r}"
        )
        assert budget in message, f"the failure must name {budget}; message={message!r}"

    def test_the_within_root_restriction_is_not_fail_open(self, tmp_path: Path) -> None:
        # The sibling prices its budgets over a sub-mapping rooted at the scanned
        # tree. That restriction is the module's one fail-open surface: if it dropped
        # everything, every ceiling would pass on an empty tally. Both directions are
        # checked here because only one of them is the dangerous one.
        oracle = _load_oracle()
        root = tmp_path / "root"
        root.mkdir()
        inside = root / "inside.txt"
        outside = tmp_path / "outside.txt"
        tally: Counter[str] = Counter({str(inside): 3, str(outside): 5})

        kept = oracle._within(root, tally)

        assert kept[os.path.realpath(inside)] == 3, (
            "a path UNDER the scan root was dropped, which would make every ceiling "
            f"pass on work it never priced; kept={dict(kept)!r}"
        )
        assert os.path.realpath(outside) not in kept, (
            "a path outside the scan root was priced, so the verdict depends on the "
            f"test runner's own filesystem traffic; kept={dict(kept)!r}"
        )


class TestTheInstrumentTearsDownUnconditionally:
    def test_the_siblings_window_restores_both_reals_when_it_raises(self) -> None:
        # Behavior 7, executed rather than read. A leaked Path.stat patch corrupts
        # every later module in the same xdist worker, and the leak is invisible until
        # some unrelated module fails.
        oracle = _load_oracle()

        with pytest.raises(RuntimeError, match="deliberate"):
            with oracle._instrumented():
                raise RuntimeError("deliberate failure inside the instrumented window")

        assert Path.stat is _REAL_STAT, (
            "Path.stat was left patched after the sibling's window raised"
        )
        assert Path.read_text is _REAL_READ_TEXT, (
            "Path.read_text was left patched after the sibling's window raised"
        )

    def test_no_shim_is_installed_outside_a_window(self) -> None:
        # Opens no window, so a shim visible here was leaked by a sibling module.
        assert Path.stat is _REAL_STAT
        assert Path.read_text is _REAL_READ_TEXT
