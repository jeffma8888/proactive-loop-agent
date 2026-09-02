"""Black-box behavior tests for factory iteration 266 (ROADMAP #263) --- the expected
``addopts`` string is DEFINED ONCE in the test corpus and imported by its two
dependents, the token list is derived rather than re-spelled, and the cross-module
source-text drift guard that existed only because the copies existed is deleted.

WHY this module exists. The surviving oracles
(``tests/test_iter52_behavior.py``, ``tests/test_iter142_behavior.py``,
``tests/test_iter159_behavior.py``) each pin what ``addopts`` IS; none of them pins
how many times the expectation is SPELLED. A future iteration that "fixes" a red
addopts test by re-declaring a local literal would leave all three of them green
while quietly restoring the drift this iteration made unrepresentable. So this
module owns the STRUCTURE of the expectation, and deliberately owns nothing else:

* it does NOT re-spell ``-q -n auto`` --- a fourth copy of the very literal being
  de-duplicated would defeat the change it verifies, and comparing an imported
  constant against itself is the import-and-assert-itself tautology
  ``tests/test_iter164_behavior.py`` warns about. The VALUE stays owned by the
  three surviving pyproject-vs-constant assertions;
* it does NOT re-assert the roadmap size budget. ``ROADMAP_CHAR_LIMIT`` minus
  ``MIN_HEADROOM`` already yields the same effective ceiling in
  ``tests/test_roadmap_size_budget.py`` and ``tests/test_iter214_behavior.py``;
  adding a third spelling of it here would be the same duplication in a new place.

Every census below is TWO-SIDED: each helper is a pure function of source text and
is proved to fire on a synthetic violating module AND to stay silent on a synthetic
compliant one, so a green run means the census still bites rather than that it
stopped looking. The needles for the deleted guard's source-text grep are ASSEMBLED
AT RUNTIME from fragments, never written out as literals, so this module cannot
exempt itself from its own corpus-wide censuses --- it is inside their domain.

ISOLATION CONTRACT (honored): every assertion here was written from this
iteration's spec ("Expected Behaviors" in ``pm.md``), the repo's own ``tests/``
tree, ``ROADMAP.md``, ``README.md`` and ``pyproject.toml``. **No file under
``src/`` was read, no engineer / reviewer / fix note was consulted, and no ``git
diff`` was inspected.**

Offline and deterministic: no network, no API key. ``git ls-files`` is used to take
the SHIPPING tree as the census domain (34 tracked modules already do this), with a
glob fallback plus an unconditional union of this file so the domain can never be
empty and can never silently drop the module doing the measuring.

Python-version note: the CI matrix runs 3.12 and 3.13, and 3.13 strips the common
docstring indent while 3.12 does not, so nothing here asserts on docstring layout.
"""

from __future__ import annotations

import ast
import importlib
import subprocess
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
TESTS_DIR = REPO / "tests"
PYPROJECT = REPO / "pyproject.toml"
ROADMAP = REPO / "ROADMAP.md"
SELF = Path(__file__).resolve()

# --------------------------------------------------------------------------
# The spec's own vocabulary (pm.md), encoded here rather than imported, to keep
# these tests black-box against the contract.
# --------------------------------------------------------------------------
CONST = "EXPECTED_ADDOPTS"
TOKENS_CONST = "EXPECTED_ADDOPTS_TOKENS"
OWNER_NAME = "test_iter52_behavior.py"
OWNER_MODULE = "tests.test_iter52_behavior"
DEPENDENT_MODULES = ("tests.test_iter142_behavior", "tests.test_iter159_behavior")
STRING_ORACLE = TESTS_DIR / "test_iter142_behavior.py"
TOKEN_ORACLE = TESTS_DIR / "test_iter142_behavior.py"
EXACT_ORACLE = TESTS_DIR / "test_iter159_behavior.py"
CENSUS_GUARD = TESTS_DIR / "test_iter149_behavior.py"
DELETED_GUARD = "test_eb11_iter52_expected_addopts_constant_agrees"
ORPHANED_HELPER = "ITER52"
EB9_PREFIX = "test_eb9_"

#: Ledger row this iteration owes ``ROADMAP.md``, and the commit tag it must cite.
LEDGER_ROW = "- #263 "
LEDGER_TAG = "(foundry iter 266)"
#: The queued throughput row whose blocker this iteration pays down.
QUEUED_ROW_ID = "| 257 |"
LIVE_MARKERS = ("**QUEUED", "**BLOCKED")


# --------------------------------------------------------------------------
# Domain + pure census helpers (each proved two-sided further down).
# --------------------------------------------------------------------------
def _tracked_test_paths() -> list[Path]:
    """Every test module in the SHIPPING tree, plus this file unconditionally."""
    paths: set[Path] = {SELF}
    try:
        out = subprocess.run(
            ["git", "ls-files", "tests"],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=False,
        )
        listed = [line for line in out.stdout.split() if line.endswith(".py")]
    except OSError:  # pragma: no cover - git is present in CI and in a fresh clone
        listed = []
    if not listed:
        listed = [str(p.relative_to(REPO)) for p in sorted(TESTS_DIR.glob("*.py"))]
    for rel in listed:
        candidate = REPO / rel
        if candidate.is_file():
            paths.add(candidate.resolve())
    return sorted(paths)


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _string_assignment_lines(source: str, name: str) -> list[int]:
    """Line numbers where ``name`` is assigned a string literal, at any depth."""
    lines: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Assign):
            continue
        if not isinstance(node.value, ast.Constant) or not isinstance(
            node.value.value, str
        ):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == name:
                lines.append(node.lineno)
    return lines


def _list_assignment_lines(source: str, name: str) -> list[int]:
    """Line numbers where ``name`` is assigned a list/tuple/set display."""
    lines: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        value = node.value
        if not isinstance(value, (ast.List, ast.Tuple, ast.Set)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if isinstance(target, ast.Name) and target.id == name:
                lines.append(node.lineno)
    return lines


def _any_assignment_lines(source: str, name: str) -> list[int]:
    lines: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Assign):
            targets: list[ast.expr] = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name) and target.id == name:
                lines.append(node.lineno)
    return lines


def _function_names(source: str) -> set[str]:
    return {
        node.name
        for node in ast.walk(ast.parse(source))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _imported_names_from(source: str, module: str) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module == module:
            names.update(alias.name for alias in node.names)
    return names


def _has_split_of(source: str, name: str) -> bool:
    """True when the source calls ``<name>.split()`` somewhere."""
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "split"
            and isinstance(func.value, ast.Name)
            and func.value.id == name
        ):
            return True
    return False


def _code_string_constants(source: str) -> list[str]:
    """Every string literal that is CODE --- docstrings excluded.

    A module is allowed to NAME a sibling in prose; behavior 4 is about no longer
    READING it as a file, so the census must not fire on documentation.
    """
    tree = ast.parse(source)
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                docstrings.add(id(body[0].value))
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]


def _assignment_grep_needle() -> str:
    """``CONST = "{`` --- assembled, never spelled, so this module is in-domain.

    The deleted guard read a sibling module's SOURCE TEXT and asserted that an
    interpolated ``CONST = "<value>"`` line occurred in it. That needle is what a
    restored source-text grep would have to contain; the plain definition line in
    the owning module does NOT match, because it carries no ``{``.
    """
    return CONST + " = " + chr(34) + chr(123)


def _needle_hits(source: str) -> int:
    return source.count(_assignment_grep_needle())


def _addopts() -> str:
    with PYPROJECT.open("rb") as fh:
        data = tomllib.load(fh)
    tool = data["tool"]["pytest"]["ini_options"]
    value = tool["addopts"]
    assert isinstance(value, str)
    return value


@pytest.fixture(scope="module")
def tracked() -> list[Path]:
    paths = _tracked_test_paths()
    assert len(paths) > 100, f"census domain collapsed to {len(paths)} module(s)"
    assert SELF in paths, "the census domain excludes the module doing the measuring"
    return paths


# ==========================================================================
# Behavior 1: exactly one definition site, and it is iteration 52's module.
# ==========================================================================
class TestSingleDefinitionSite:
    def test_b1_exactly_one_module_defines_the_constant(
        self, tracked: list[Path]
    ) -> None:
        sites = {
            path: _string_assignment_lines(path.read_text(encoding="utf-8"), CONST)
            for path in tracked
        }
        owners = {p.name: lines for p, lines in sites.items() if lines}
        assert list(owners) == [OWNER_NAME], (
            f"{CONST} must be defined in exactly one tracked test module "
            f"({OWNER_NAME}); found {owners}"
        )
        assert owners[OWNER_NAME] == sorted(owners[OWNER_NAME])[:1], (
            f"{OWNER_NAME} defines {CONST} more than once: {owners[OWNER_NAME]}"
        )

    def test_b1_census_fires_on_a_second_definition(self) -> None:
        bad = f'{CONST} = "-q -n auto"\n'
        assert _string_assignment_lines(bad, CONST) == [1]

    def test_b1_census_stays_silent_on_an_import_and_on_a_reference(self) -> None:
        good = (
            f"from {OWNER_MODULE} import {CONST}\n"
            f"def t() -> None:\n"
            f"    assert {CONST}\n"
        )
        assert _string_assignment_lines(good, CONST) == []


# ==========================================================================
# Behavior 2: the dependents import the value instead of redeclaring it.
# ==========================================================================
class TestDependentsImport:
    @pytest.mark.parametrize("module", DEPENDENT_MODULES)
    def test_b2_each_dependent_imports_the_constant_from_its_owner(
        self, module: str
    ) -> None:
        path = REPO / (module.replace(".", "/") + ".py")
        names = _imported_names_from(path.read_text(encoding="utf-8"), OWNER_MODULE)
        assert CONST in names, (
            f"{path.name} does not import {CONST} from {OWNER_MODULE}; found {names}"
        )

    @pytest.mark.parametrize("module", DEPENDENT_MODULES)
    def test_b2_each_dependent_shares_the_owner_object_at_runtime(
        self, module: str
    ) -> None:
        owner = importlib.import_module(OWNER_MODULE)
        dependent = importlib.import_module(module)
        assert getattr(dependent, CONST) is getattr(owner, CONST), (
            f"{module} carries its own {CONST} object, so the two can disagree"
        )

    @pytest.mark.parametrize("module", DEPENDENT_MODULES)
    def test_b2_no_dependent_assigns_the_constant_locally(self, module: str) -> None:
        path = REPO / (module.replace(".", "/") + ".py")
        lines = _any_assignment_lines(path.read_text(encoding="utf-8"), CONST)
        assert lines == [], f"{path.name} still assigns {CONST} at lines {lines}"


# ==========================================================================
# Behavior 3: the token list is derived from the constant, never re-spelled.
# ==========================================================================
class TestTokenListDerived:
    def test_b3_no_module_level_token_literal_survives(
        self, tracked: list[Path]
    ) -> None:
        offenders = {
            path.name: _list_assignment_lines(
                path.read_text(encoding="utf-8"), TOKENS_CONST
            )
            for path in tracked
        }
        remaining = {name: lines for name, lines in offenders.items() if lines}
        assert remaining == {}, (
            f"a re-spelled {TOKENS_CONST} literal survives: {remaining}"
        )

    def test_b3_the_tokenized_assertion_derives_from_the_constant(self) -> None:
        assert _has_split_of(TOKEN_ORACLE.read_text(encoding="utf-8"), CONST), (
            f"{TOKEN_ORACLE.name} no longer derives its token expectation from "
            f"{CONST}.split(); a re-spelled token list is the duplication this "
            "iteration removed"
        )

    def test_b3_token_census_is_two_sided(self) -> None:
        bad = f'{TOKENS_CONST} = ["-q", "-n", "auto"]\n'
        assert _list_assignment_lines(bad, TOKENS_CONST) == [1]
        good = f"def t() -> None:\n    tokens = {CONST}.split()\n    assert tokens\n"
        assert _list_assignment_lines(good, TOKENS_CONST) == []
        assert _has_split_of(good, CONST) is True
        assert _has_split_of(f"{CONST}\n", CONST) is False


# ==========================================================================
# Behavior 4: the duplication-only guard, its orphaned helper, and the
# source-text grep it performed are all gone corpus-wide.
# ==========================================================================
class TestDuplicationOnlyGuardRemoved:
    def test_b4_the_deleted_guard_is_absent_corpus_wide(
        self, tracked: list[Path]
    ) -> None:
        owners = [
            path.name
            for path in tracked
            if DELETED_GUARD in _function_names(path.read_text(encoding="utf-8"))
        ]
        assert owners == [], f"{DELETED_GUARD} still defined in {owners}"

    def test_b4_the_orphaned_helper_constant_is_gone(self) -> None:
        source = STRING_ORACLE.read_text(encoding="utf-8")
        assert _any_assignment_lines(source, ORPHANED_HELPER) == [], (
            f"{STRING_ORACLE.name} still assigns {ORPHANED_HELPER}, whose only "
            f"reader was {DELETED_GUARD}"
        )
        assert ORPHANED_HELPER not in source, (
            f"{ORPHANED_HELPER} is still referenced in {STRING_ORACLE.name}"
        )

    def test_b4_the_owner_module_is_no_longer_read_as_a_file(self) -> None:
        offenders = [
            value
            for value in _code_string_constants(
                STRING_ORACLE.read_text(encoding="utf-8")
            )
            if OWNER_NAME in value
        ]
        assert offenders == [], (
            f"{STRING_ORACLE.name} still names {OWNER_NAME} in CODE ({offenders}); "
            "the cross-module reference must be an import, not a file read"
        )

    def test_b4_the_code_string_census_ignores_prose(self) -> None:
        bad = f'ITER = TESTS_DIR / "{OWNER_NAME}"\n'
        assert _code_string_constants(bad) == [OWNER_NAME]
        good = f'"""Sits next to {OWNER_NAME}, which owns the constant."""\n'
        assert _code_string_constants(good) == []

    def test_b4_no_test_greps_a_sibling_for_the_assignment_line(
        self, tracked: list[Path]
    ) -> None:
        offenders = {
            path.name: _needle_hits(path.read_text(encoding="utf-8"))
            for path in tracked
        }
        remaining = {name: n for name, n in offenders.items() if n}
        assert remaining == {}, (
            "a source-text drift grep for the constant's assignment line survives: "
            f"{remaining}"
        )

    def test_b4_needle_census_is_two_sided(self) -> None:
        needle = _assignment_grep_needle()
        bad = "assert f'" + needle + CONST + '}"\' in text\n'
        assert _needle_hits(bad) == 1
        good = f'{CONST} = "-q -n auto"\n'
        assert _needle_hits(good) == 0, (
            "the needle must not match a plain definition line, only an "
            "interpolated grep for one"
        )
        assert _needle_hits(f"from {OWNER_MODULE} import {CONST}\n") == 0

    def test_b4_the_function_census_is_two_sided(self) -> None:
        bad = f"def {DELETED_GUARD}(self) -> None:\n    assert True\n"
        assert DELETED_GUARD in _function_names(bad)
        assert DELETED_GUARD not in _function_names("def other() -> None:\n    pass\n")


# ==========================================================================
# Behavior 6: the coverage invariant this refactor must not weaken.
# ==========================================================================
class TestCoverageInvariantIntact:
    def test_b6_addopts_enables_no_coverage_globally(self) -> None:
        assert "--cov" not in _addopts().lower(), (
            f"coverage must stay opt-in per call; addopts is {_addopts()!r}"
        )

    def test_b6_the_coverage_guards_still_exist(self, tracked: list[Path]) -> None:
        guards = sorted(
            f"{path.name}::{name}"
            for path in tracked
            for name in _function_names(path.read_text(encoding="utf-8"))
            if "addopts" in name and "cov" in name
        )
        assert len(guards) >= 2, (
            "the 'addopts never enables coverage globally' guards were thinned by "
            f"this refactor; found {guards}"
        )


# ==========================================================================
# Behavior 7: the neighbouring censuses over the edited module still bite.
# ==========================================================================
class TestNeighbouringCensusesStillBite:
    def test_b7_every_eb9_name_pinned_by_the_guard_still_exists_in_its_target(
        self,
    ) -> None:
        pinned = sorted(
            {
                node.value
                for node in ast.walk(_parse(CENSUS_GUARD))
                if isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and node.value.startswith(EB9_PREFIX)
                and len(node.value) > len(EB9_PREFIX)
            }
        )
        assert len(pinned) >= 2, (
            f"{CENSUS_GUARD.name} no longer pins any exact {EB9_PREFIX}* name, so "
            "behavior 7 has nothing to protect"
        )
        defined = _function_names(STRING_ORACLE.read_text(encoding="utf-8"))
        missing = [name for name in pinned if name not in defined]
        assert missing == [], (
            f"the deletion removed {missing} from {STRING_ORACLE.name}, which "
            f"{CENSUS_GUARD.name} pins by exact name"
        )

    def test_b7_the_deleted_guard_was_neither_of_the_pinned_prefixes(self) -> None:
        assert not DELETED_GUARD.startswith(EB9_PREFIX)
        assert not DELETED_GUARD.startswith("test_eb8_")


# ==========================================================================
# Behavior 9: the iteration records itself and leaves no stale claim.
# ==========================================================================
class TestRoadmapRecordsTheIteration:
    def test_b9_exactly_one_new_ledger_row_citing_this_iteration_tag(self) -> None:
        rows = [
            line
            for line in ROADMAP.read_text(encoding="utf-8").splitlines()
            if line.startswith(LEDGER_ROW)
        ]
        assert len(rows) == 1, f"expected exactly one {LEDGER_ROW!r} row; got {rows}"
        assert rows[0].rstrip().endswith(LEDGER_TAG), (
            f"the ledger row must cite {LEDGER_TAG}; got {rows[0]!r}"
        )
        assert CONST in rows[0], f"the ledger row does not name {CONST}: {rows[0]!r}"

    def test_b9_the_queued_row_is_restated_and_still_reads_as_open_work(self) -> None:
        rows = [
            line
            for line in ROADMAP.read_text(encoding="utf-8").splitlines()
            if line.startswith(QUEUED_ROW_ID)
        ]
        assert len(rows) == 1, f"expected one {QUEUED_ROW_ID!r} table row; got {rows}"
        row = rows[0]
        assert any(marker in row for marker in LIVE_MARKERS), (
            "the re-stated row lost its live status marker, so it now reads as a "
            f"missed retirement: {row!r}"
        )
        assert DELETED_GUARD not in row, (
            "the row still names the guard this iteration deleted"
        )

    def test_b9_no_roadmap_line_still_names_the_deleted_guard(self) -> None:
        text = ROADMAP.read_text(encoding="utf-8")
        offenders = [
            i for i, line in enumerate(text.splitlines(), 1) if DELETED_GUARD in line
        ]
        assert offenders == [], (
            f"ROADMAP.md still names {DELETED_GUARD} at lines {offenders}"
        )
