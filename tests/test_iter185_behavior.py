"""Black-box oracle for factory iteration 185 --- the suite is HERMETIC against
the published ``PLA_*`` configuration namespace.

MODULE NAME. This repo names behavior modules by the FACTORY iteration number,
which runs ahead of the state-dir counter (state-dir iteration 181 ships as
factory iter 185; ``tests/test_iter184_behavior.py`` and
``tests/test_iter179_behavior.py`` each document the same offset for
themselves). ``test_iter180..184_behavior.py`` are already tracked, so 185 is
the next free number and no shipped oracle is overwritten.

Feature under test (this iteration's ``pm.md``, Expected Behaviors 1-10).
``README.md`` publishes the ``PLA_*`` knobs as the supported configuration
surface, and the same README publishes ``uv run pytest`` as how a reader checks
the project out. Measured on ``5d7737b``, those two documented actions
CONTRADICTED each other: ``PLA_AUTO_DISPATCH_MIN_SCORE=9.9`` red 3 tests and
``PLA_SENSITIVE_CATEGORIES=career`` red 5 --- 7 distinct tests across
``test_iter22_behavior.py`` and ``test_iter39_behavior.py`` --- because those
modules assert documented DEFAULTS and never cleared the namespace. CI was
green only because a fresh runner exports no ``PLA_*``. On a public portfolio
repo that failure reads as broken code, not as an environment leak.

The fix under test here is one shared clearer, ``clear_pla_env``, whose target
set is DERIVED from the runtime's own ``Settings.from_env`` call sites
(``derive_env_names``, already shipped in ``tests/test_iter125_behavior.py``),
plus ONE module-level ``autouse`` fixture in each env-sensitive module. Deriving
rather than listing is the point: the previous second copy --- a hardcoded
15-name tuple in ``test_iter104_behavior.py`` --- had ALREADY drifted (14 derived
vs 15 hardcoded, the extra name dead in ``src/``) with no guard tying the copies
together, so this iteration removes the drift by CONSTRUCTION instead of adding
an equality check between two hand-maintained lists.

ISOLATION CONTRACT (honored): the seams used here are the public
``proactive_loop.config.Settings`` / ``ENV_PREFIX`` (the same settings seam every
verb resolves through) and the shipped test modules' own SOURCE TEXT, read as
text/``ast`` --- never their internals at runtime. Cross-module import of the
shared helper follows this repo's existing precedent
(``tests/test_iter119_behavior.py`` imports ``derive_llm_free_verbs`` from
``tests/test_iter116_behavior.py``; ``tests/test_iter168_behavior.py`` and
``tests/test_iter182_behavior.py`` do the same). Every test is in-process and
fully offline: no network, no subprocess, NO nested ``pytest`` or ``uv`` run
(``test_iter149``/``test_iter159`` guard those), and no ``conftest.py``.
"""

from __future__ import annotations

import ast
import inspect
import os
import re
import textwrap
from pathlib import Path

import pytest

import tests.test_iter125_behavior as shared
from proactive_loop.config import ENV_PREFIX, Settings
from tests.test_iter125_behavior import clear_pla_env, derive_env_names

REPO = Path(__file__).resolve().parents[1]
TESTS_DIR = REPO / "tests"

#: The three modules that assert documented DEFAULTS and therefore must run with
#: the namespace cleared. Named, not globbed: this is the MEASURED blast radius
#: of the reported defect, and the spec deliberately makes no repo-wide claim.
HERMETIC_MODULES = (
    "test_iter22_behavior.py",
    "test_iter39_behavior.py",
    "test_iter104_behavior.py",
)

#: The dead env name deleted this iteration. Assembled from fragments ON PURPOSE:
#: behavior 5 asserts the token appears nowhere under ``tests/`` or ``src/``, and
#: a module that spelled it would be the one blind spot in its own census
#: (OPERATOR 2026-08-14: a detector's own domain is where it cannot look).
DEAD_ENV_NAME = "PLA_SCRIPTED_" + "RESPONSES" + "_PATH"

#: README-published default for the auto-dispatch threshold (behavior 8).
DOCUMENTED_THRESHOLD = 4.0

#: A value no knob defaults to. It never reaches a coercer: every test that sets
#: it clears the namespace before calling ``Settings.from_env()``.
PERTURBED = "9"

# Names used only to prove the clearer targets the DERIVED set rather than the
# whole ``PLA_`` prefix. Neither is a live knob.
DERIVED_PROBE = "PLA_PROBE_IN_DERIVED_SET"
DECOY_PROBE = "PLA_PROBE_NOT_IN_DERIVED_SET"


def _module_tree(name: str) -> tuple[str, ast.Module]:
    """Return ``(source_text, ast)`` for a shipped test module, read from disk."""
    source = (TESTS_DIR / name).read_text(encoding="utf-8")
    return source, ast.parse(source)


def _is_autouse_fixture(decorator: ast.expr) -> bool:
    """True for ``@pytest.fixture(autouse=True)`` in either import spelling."""
    if not isinstance(decorator, ast.Call):
        return False
    func = decorator.func
    named = (
        func.attr
        if isinstance(func, ast.Attribute)
        else func.id if isinstance(func, ast.Name) else ""
    )
    if named != "fixture":
        return False
    return any(
        kw.arg == "autouse" and isinstance(kw.value, ast.Constant) and kw.value.value is True
        for kw in decorator.keywords
    )


def _called_names(node: ast.AST) -> set[str]:
    """Every bare-name function called anywhere inside ``node``."""
    return {
        call.func.id
        for call in ast.walk(node)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
    }


# ===========================================================================
# Behavior 1 -- one home, and the clearer's target set IS the derived set.
# ===========================================================================
def test_b01_clearer_and_derivation_live_in_one_module() -> None:
    assert clear_pla_env.__module__ == derive_env_names.__module__, (
        "the clearer and the derivation must live beside each other; two homes "
        "is how the previous copy drifted"
    )
    assert Path(inspect.getfile(clear_pla_env)).name == "test_iter125_behavior.py"
    names = derive_env_names()
    assert names, "the derived set is EMPTY -- every assertion below would pass vacuously"
    assert all(name.startswith(ENV_PREFIX) for name in names), sorted(names)


def test_b01_clearer_iterates_the_derivation_and_holds_no_literal_name_list() -> None:
    """The whole point of the fix: no second, hand-maintained copy of the names."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(clear_pla_env)))
    assert "derive_env_names" in _called_names(tree), (
        "the clearer must call derive_env_names(); a literal list is exactly the "
        "drift this iteration removes"
    )
    literals = sorted(
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value.startswith(ENV_PREFIX)
    )
    assert literals == [], f"the clearer hardcodes env names {literals}"


def test_b01_clearer_targets_exactly_the_derived_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two-sided: a derived name goes, a same-prefix non-derived name STAYS.

    A blanket ``PLA_*`` purge would also pass the other behaviors here, so this
    is the test that pins the target set to the derivation.
    """
    monkeypatch.setenv(DERIVED_PROBE, PERTURBED)
    monkeypatch.setenv(DECOY_PROBE, PERTURBED)
    monkeypatch.setattr(shared, "derive_env_names", lambda: {DERIVED_PROBE})

    clear_pla_env(monkeypatch)

    assert DERIVED_PROBE not in os.environ, "a derived name survived the clearer"
    assert os.environ.get(DECOY_PROBE) == PERTURBED, (
        "the clearer purged the PLA_ prefix wholesale instead of the derived set"
    )


# ===========================================================================
# Behavior 2 -- a fully perturbed environment collapses to the defaults.
# ===========================================================================
def test_b02_full_perturbation_then_clear_yields_default_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    derived = derive_env_names()
    for name in sorted(derived):
        monkeypatch.setenv(name, PERTURBED)

    clear_pla_env(monkeypatch)

    leaked = sorted(name for name in derived if name in os.environ)
    assert leaked == [], f"the clearer left these overrides in place: {leaked}"
    assert Settings.from_env().model_dump() == Settings().model_dump()


# ===========================================================================
# Behavior 3/4 -- controls, so behavior 2 cannot pass vacuously.
# ===========================================================================
def test_b03_control_threshold_override_survives_without_the_clearer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PLA_AUTO_DISPATCH_MIN_SCORE", "9.9")
    assert Settings.from_env().auto_dispatch_min_score == 9.9, (
        "the knob no longer reaches Settings.from_env(), so behavior 2 proves nothing"
    )


def test_b04_control_sensitive_categories_override_survives_without_the_clearer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PLA_SENSITIVE_CATEGORIES", "career")
    live = Settings.from_env().sensitive_categories
    assert {category.value for category in live} == {"career"}
    assert live != Settings().sensitive_categories, "the chosen value is not a perturbation"


def test_b04_sensitive_categories_return_to_default_after_the_clearer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PLA_SENSITIVE_CATEGORIES", "career")
    clear_pla_env(monkeypatch)
    assert Settings.from_env().sensitive_categories == Settings().sensitive_categories


# ===========================================================================
# Behavior 5 -- the drifted second copy, and its dead entry, are gone.
# ===========================================================================
def test_b05_iter104_holds_no_env_name_outside_the_derived_set() -> None:
    source, _tree = _module_tree("test_iter104_behavior.py")
    literals = {match.group(0) for match in re.finditer(rf"{ENV_PREFIX}[A-Z0-9_]+", source)}
    assert literals, "no PLA_ literal found in the module at all -- this scan is fail-open"
    stray = sorted(literals - derive_env_names())
    assert stray == [], (
        f"{HERMETIC_MODULES[2]} still names env vars the runtime does not read: {stray}"
    )


def test_b05_dead_env_name_is_gone_from_tests_and_src() -> None:
    scanned = 0
    hits: list[str] = []
    paths = sorted(TESTS_DIR.glob("test_*.py")) + sorted((REPO / "src").rglob("*.py"))
    for path in paths:
        scanned += 1
        if DEAD_ENV_NAME in path.read_text(encoding="utf-8"):
            hits.append(str(path.relative_to(REPO)))
    assert scanned >= 100, f"scan reached only {scanned} files -- the glob is fail-open"
    assert hits == [], f"the dead env name is still spelled in {hits}"


# ===========================================================================
# Behavior 6 -- one autouse clearer per env-sensitive module, no call sites.
# ===========================================================================
def test_b06_each_env_sensitive_module_has_exactly_one_autouse_clearer() -> None:
    for name in HERMETIC_MODULES:
        source, tree = _module_tree(name)
        fixtures = [
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and any(_is_autouse_fixture(dec) for dec in node.decorator_list)
        ]
        assert len(fixtures) == 1, (
            f"{name} must hold exactly ONE module-level autouse fixture; found "
            f"{[node.name for node in fixtures]}"
        )
        assert "clear_pla_env" in _called_names(fixtures[0]), (
            f"{name}'s autouse fixture must delegate to the shared clearer"
        )
        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            and node.module == "tests.test_iter125_behavior"
            for alias in node.names
        }
        assert "clear_pla_env" in imported, f"{name} must import the shared clearer, not copy it"
        assert "scope=" not in (ast.get_source_segment(source, fixtures[0].decorator_list[0]) or ""), (
            f"{name}'s clearer must stay function-scoped, or it cannot re-run per test "
            "(and monkeypatch is function-scoped anyway)"
        )


def test_b06_no_module_clears_the_namespace_at_per_test_call_sites() -> None:
    """The retired shape: every test body calling a local ``_clean_env`` helper."""
    source, _tree = _module_tree("test_iter104_behavior.py")
    assert "_clean_env" not in source, (
        "the per-test clearing helper is still present; behavior 6 mandates one "
        "autouse fixture instead"
    )


# ===========================================================================
# Behavior 7 -- a test that deliberately overrides a knob still wins.
# ===========================================================================
def test_b07_a_test_body_override_still_wins_over_the_autouse_clearer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Replays the fixture-then-body order in one process.

    A pytest fixture runs BEFORE the test body, so the body's own ``setenv`` is
    applied last and wins. The real subject,
    ``test_iter22::test_behavior8_threshold_reflects_env_override``, is verified
    by the suite that contains it; this pins the ORDERING property the fixture
    relies on, without a nested pytest run (banned by ``test_iter159``).
    """
    monkeypatch.setenv("PLA_AUTO_DISPATCH_MIN_SCORE", "9.9")  # ambient shell leak
    clear_pla_env(monkeypatch)  # what the autouse fixture does
    monkeypatch.setenv("PLA_AUTO_DISPATCH_MIN_SCORE", "2.5")  # what the test body does
    assert Settings.from_env().auto_dispatch_min_score == 2.5


def test_b07_the_deliberate_override_test_still_exists_and_sets_the_knob() -> None:
    source, _tree = _module_tree("test_iter22_behavior.py")
    assert "def test_behavior8_threshold_reflects_env_override" in source
    assert 'monkeypatch.setenv("PLA_AUTO_DISPATCH_MIN_SCORE"' in source, (
        "the override test no longer sets the knob, so behavior 7 guards nothing"
    )


# ===========================================================================
# Behavior 8 -- regression oracle for the two MEASURED knobs, in-process.
# ===========================================================================
def test_b08_both_measured_knobs_read_back_their_documented_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PLA_AUTO_DISPATCH_MIN_SCORE", "9.9")
    monkeypatch.setenv("PLA_SENSITIVE_CATEGORIES", "career")

    clear_pla_env(monkeypatch)
    live = Settings.from_env()

    assert live.auto_dispatch_min_score == DOCUMENTED_THRESHOLD
    assert live.auto_dispatch_min_score == Settings().auto_dispatch_min_score
    assert live.sensitive_categories == Settings().sensitive_categories


# ===========================================================================
# Behavior 9 -- no conftest.py was added (three corpus guards glob tests/).
# ===========================================================================
def test_b09_no_conftest_exists_at_the_repo_root_or_under_tests() -> None:
    found = [
        str(path.relative_to(REPO))
        for path in (REPO / "conftest.py", TESTS_DIR / "conftest.py")
        if path.exists()
    ]
    assert found == [], f"a conftest.py is a blind spot for the tests/*.py censuses: {found}"


# ===========================================================================
# Behavior 10 -- the mechanism is confined to tests/; nothing else is coupled.
# ===========================================================================
def test_b10_the_hermeticity_mechanism_is_confined_to_tests() -> None:
    assert Path(inspect.getfile(clear_pla_env)).parent == TESTS_DIR
    scanned = 0
    hits: list[str] = []
    candidates = [
        REPO / "README.md",
        REPO / "Makefile",
        REPO / "SPEC.md",
        REPO / "pyproject.toml",
        REPO / ".github" / "workflows" / "ci.yml",
        *sorted((REPO / "src").rglob("*.py")),
    ]
    for path in candidates:
        if not path.exists():
            continue
        scanned += 1
        if "clear_pla_env" in path.read_text(encoding="utf-8"):
            hits.append(str(path.relative_to(REPO)))
    assert scanned >= 20, f"scan reached only {scanned} files -- the domain is fail-open"
    assert hits == [], f"a test-only helper leaked into shipped files: {hits}"
