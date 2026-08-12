"""Black-box behavior tests for foundry iteration 144 (ships as commit-sequence
**factory iter 151**): close the rest of the SHARED-MUTABLE-TREE COMPARISON class
in ``tests/test_iter99_behavior.py`` and ship a census WIDE ENOUGH TO SEE IT.

Four functions still derived one of their two compared values from a CLI run
rooted at the IN-REPO fixture ``examples/fixture_workspace``. That directory
carries no ``.git`` of its own, so every git-family collector resolves UPWARD and
reports the enclosing product repo: with ``-n auto`` fan-out pinned in
``addopts``, a sibling worker writing byte-cache files flips a ``working_tree``
row between the two runs being compared, and the comparison fails for a reason
that has nothing to do with the product. That is exactly the operator's recorded
iter-142 post-release break.

The iteration-150 census meant to prevent regressions of this class is FAIL-OPEN
against these four: it counts only DIRECT runner calls in a function body and
only ``assert <name> == <name>`` comparisons, while each of the four makes ONE
direct isolated run and got its second run from the module-level helper
``_listing_counts_via_cli``, comparing ``<name> == <call>``. This module ships the
widened, TRANSITIVE census and asserts the narrow one's blind spot two-sidedly.

SPEC AMBIGUITY (recorded, and tested in its decidable form). Behavior 1 asks that
"neither the function body nor any helper it calls references the module-level
in-repo ``FIXTURE`` constant", but Behavior 1 also mandates the shipped
``_isolated_fixture_copy`` helper, whose body is ``copytree(FIXTURE, dest)``
(``tests/test_iter99_behavior.py``, the copytree source). Read literally the
criterion is unsatisfiable, so it is tested in the form that is actually
decidable and actually load-bearing: no CLI run REACHABLE from the four
functions is ROOTED at the in-repo fixture -- i.e. the property is about the
value flowing into a run's ``--workspace`` argument, never about the identifier
appearing anywhere in the call graph. A reference that only feeds ``copytree``
is by construction safe; a reference that feeds ``--workspace`` is the bug.

ISOLATION CONTRACT (honored): every assertion here is written strictly against
this iteration's spec ("Expected Behaviors" in ``pm.md``), the repo's own
``tests/`` tree, and the product's OBSERVABLE output obtained by RUNNING it via
``proactive_loop.cli.main(argv)``. **No file under ``src/`` was read, no
engineer's or reviewer's note was consulted, and no ``git diff`` was inspected.**
Fully offline: no network, no API keys, no provider calls (``signals`` builds no
LLM client). Every workspace this module runs over is built under ``tmp_path``;
nothing is written inside the product repo. No fixture count is transcribed --
both sides of every compared value are derived at run time, which matters here
because over a ``copytree`` copy no git-family kind appears at all.
"""

from __future__ import annotations

import ast
import contextlib
import importlib.util
import io
import json
import shutil
from collections import Counter
from pathlib import Path

import pytest

from proactive_loop.cli import main

REPO = Path(__file__).resolve().parents[1]
TESTS_DIR = REPO / "tests"
TARGET_MODULE = TESTS_DIR / "test_iter99_behavior.py"
NARROW_CENSUS_MODULE = TESTS_DIR / "test_iter150_behavior.py"
FIXTURE = REPO / "examples" / "fixture_workspace"

# The four class members this iteration migrates (named by the spec).
TARGET_FUNCS = (
    "test_b01_human_summary_end_to_end_via_cli",
    "test_b03_json_summary_end_to_end_via_cli",
    "test_b05_kind_composition_via_cli",
    "test_b07_collector_composition_via_cli",
)

LISTING_HELPER = "_listing_counts_via_cli"
COPY_HELPER = "_isolated_fixture_copy"

_FIXTURE_PATH_FRAGMENT = "examples/fixture_workspace"
# Same runner vocabulary the shipped iter-150 census uses, so the widened census
# is a strict superset of it rather than a differently-scoped detector.
_RUNNER_NAMES = frozenset({"_run", "main", "_cli", "_invoke"})
_COPY_IGNORE = shutil.ignore_patterns(".git", "__pycache__", "*.pyc")


# ---------------------------------------------------------------------------
# Black-box runtime helpers (public CLI only).
# ---------------------------------------------------------------------------
def _run(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code: int
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rv = main(argv)
            code = rv if isinstance(rv, int) else 0
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
    return code, out.getvalue(), err.getvalue()


def _isolated_copy(dest: Path) -> Path:
    """A private copy of the bundled fixture under ``tmp_path``.

    Built here rather than imported so this module's own runtime evidence does
    not depend on the very helper it is auditing.
    """
    shutil.copytree(FIXTURE, dest, ignore=_COPY_IGNORE)
    return dest


def _summary_json(workspace: str, extra: list[str] | None = None) -> dict:
    code, out, err = _run(
        ["signals", "--workspace", workspace, "--summary", "--json", *(extra or [])]
    )
    assert code == 0, f"--summary --json must exit 0 over {workspace}; stderr={err!r}"
    return json.loads(out)


def _listing_counts(workspace: str, extra: list[str] | None = None) -> dict[str, int]:
    code, out, err = _run(["signals", "--workspace", workspace, "--json", *(extra or [])])
    assert code == 0, f"listing must exit 0 over {workspace}; stderr={err!r}"
    doc = json.loads(out)
    return dict(Counter(s["kind"] for s in doc["signals"]))


# ---------------------------------------------------------------------------
# AST plumbing.
# ---------------------------------------------------------------------------
def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _module_functions(tree: ast.Module) -> dict[str, ast.FunctionDef]:
    """MODULE-LEVEL function defs by name (the helper population a test can reach)."""
    return {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}


def _func(tree: ast.Module, name: str) -> ast.FunctionDef:
    fn = _module_functions(tree).get(name)
    assert fn is not None, f"{TARGET_MODULE.name} no longer defines {name}()"
    return fn


def _references_in_repo_fixture(call: ast.Call) -> bool:
    """True when a call's arguments name the in-repo fixture (constant or Name)."""
    for arg in list(call.args) + [kw.value for kw in call.keywords]:
        for node in ast.walk(arg):
            if isinstance(node, ast.Name) and "FIXTURE" in node.id.upper():
                return True
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if _FIXTURE_PATH_FRAGMENT in node.value:
                    return True
    return False


def _direct_in_repo_runs(fn: ast.AST) -> list[ast.Call]:
    return [
        c
        for c in ast.walk(fn)
        if isinstance(c, ast.Call)
        and isinstance(c.func, ast.Name)
        and c.func.id in _RUNNER_NAMES
        and _references_in_repo_fixture(c)
    ]


def _called_helper_names(fn: ast.AST, helpers: dict[str, ast.FunctionDef]) -> list[str]:
    """Module-level helper names called from *fn*, one entry PER CALL SITE."""
    names: list[str] = []
    for call in ast.walk(fn):
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name):
            if call.func.id in helpers:
                names.append(call.func.id)
    return names


def _reachable_in_repo_runs(
    fn: ast.FunctionDef,
    helpers: dict[str, ast.FunctionDef],
    _stack: frozenset[str] = frozenset(),
) -> int:
    """Count in-repo-fixture CLI runs reachable from *fn*, following module-level
    helper calls TRANSITIVELY.

    This is the widening over the shipped iter-150 census, which counted only
    DIRECT runner calls in the function body: the four members of this class each
    make one direct run and obtain the SECOND from a helper. Cycle-safe: a helper
    already on the stack contributes 0 rather than recursing forever.
    """
    total = len(_direct_in_repo_runs(fn))
    stack = _stack | {fn.name}
    for name in _called_helper_names(fn, helpers):
        if name in stack:
            continue
        total += _reachable_in_repo_runs(helpers[name], helpers, stack)
    return total


def _census_helper_indirect(tree: ast.Module) -> list[str]:
    """Names of test functions that reach TWO OR MORE in-repo-fixture CLI runs.

    Two or more such runs is the hazard whether or not the comparison is
    ``assert <name> == <name>``: the compared value can be a call, a dict, an
    f-string or a subscript. The shipped narrow census additionally required the
    bare-name shape, which is precisely why it is silent on this class.
    """
    helpers = _module_functions(tree)
    return sorted(
        fn.name
        for fn in tree.body
        if isinstance(fn, ast.FunctionDef)
        and fn.name.startswith("test")
        and _reachable_in_repo_runs(fn, helpers) >= 2
    )


def _eq_pairs(fn: ast.AST) -> list[tuple[str, str]]:
    """(unparsed left, unparsed right) for every ``==`` comparison asserted in *fn*."""
    pairs: list[tuple[str, str]] = []
    for stmt in ast.walk(fn):
        if not isinstance(stmt, ast.Assert):
            continue
        for cmp_ in ast.walk(stmt.test):
            if isinstance(cmp_, ast.Compare) and len(cmp_.ops) == 1:
                if isinstance(cmp_.ops[0], ast.Eq):
                    pairs.append((ast.unparse(cmp_.left), ast.unparse(cmp_.comparators[0])))
    return pairs


def _normalize_ws_arg(text: str) -> str:
    """Blank out the workspace identifier passed to the listing helper, so the
    preserved relationship can be pinned without pinning the local variable name
    the migration introduced."""
    marker = LISTING_HELPER + "("
    if marker not in text:
        return text
    head, _, tail = text.partition(marker)
    _first, sep, rest = tail.partition(", ")
    return head + marker + "WS" + sep + rest if sep else head + marker + "WS)"


def _load_narrow_census():
    """The SHIPPED iter-150 census, loaded by file path (never collected twice)."""
    spec = importlib.util.spec_from_file_location("_iter150_census_under_test", NARROW_CENSUS_MODULE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    fn = getattr(module, "_census_unsafe_compared_runs", None)
    assert fn is not None, (
        "test_iter150_behavior.py must keep exposing _census_unsafe_compared_runs; "
        "this module asserts its blind spot, so both oracles stay"
    )
    return fn


# Synthetic modules for the two-sided census proof (Behavior 6). Text, not
# imports: the census is a pure function of a parsed module.
_BAD_MODULE = '''
FIXTURE = "/repo/examples/fixture_workspace"


def _listing_counts_via_cli(argv_filters):
    return _run(["signals", "--workspace", str(FIXTURE), "--json", *argv_filters])


def test_planted_helper_indirect():
    summary = _run(["signals", "--workspace", str(FIXTURE), "--summary"])
    assert summary == _listing_counts_via_cli([])
'''

_GOOD_MODULE = '''
FIXTURE = "/repo/examples/fixture_workspace"


def _isolated_fixture_copy(dest):
    return copytree(FIXTURE, dest)


def _listing_counts_via_cli(workspace, argv_filters):
    return _run(["signals", "--workspace", workspace, "--json", *argv_filters])


def test_planted_isolated(tmp_path):
    ws = str(_isolated_fixture_copy(tmp_path / "fixture_copy"))
    summary = _run(["signals", "--workspace", ws, "--summary"])
    assert summary == _listing_counts_via_cli(ws, [])
'''


@pytest.fixture(scope="module")
def target_tree() -> ast.Module:
    return _parse(TARGET_MODULE)


# ===========================================================================
# Behavior 1 -- the four remaining members are isolated: BOTH compared values
# come from runs rooted under tmp_path, and no run reachable from them is rooted
# at the in-repo fixture. (See the module docstring for why this is tested on
# the run ROOT and not on the FIXTURE identifier.)
# ===========================================================================
@pytest.mark.parametrize("func_name", TARGET_FUNCS)
def test_b01_no_reachable_run_is_rooted_at_the_in_repo_fixture(target_tree, func_name):
    helpers = _module_functions(target_tree)
    fn = _func(target_tree, func_name)
    reached = _reachable_in_repo_runs(fn, helpers)
    assert reached == 0, (
        f"{func_name}() still reaches {reached} CLI run(s) rooted at the in-repo "
        "fixture (directly or through a module-level helper); every compared run "
        "must be rooted under tmp_path"
    )


@pytest.mark.parametrize("func_name", TARGET_FUNCS)
def test_b01_workspace_is_built_under_tmp_path(target_tree, func_name):
    fn = _func(target_tree, func_name)
    params = [a.arg for a in fn.args.args]
    assert "tmp_path" in params, f"{func_name}() must take pytest's tmp_path; got {params}"
    copy_calls = [
        c
        for c in ast.walk(fn)
        if isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id == COPY_HELPER
    ]
    assert copy_calls, f"{func_name}() must build its workspace via {COPY_HELPER}()"
    for call in copy_calls:
        names = {n.id for n in ast.walk(call) if isinstance(n, ast.Name)}
        assert "tmp_path" in names, (
            f"{func_name}() must root its {COPY_HELPER}() destination at tmp_path; "
            f"got {ast.unparse(call)}"
        )


@pytest.mark.parametrize("func_name", TARGET_FUNCS)
def test_b01_no_run_argv_names_the_fixture_path_string(target_tree, func_name):
    fn = _func(target_tree, func_name)
    for call in ast.walk(fn):
        if isinstance(call, ast.Call):
            for node in ast.walk(call):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    assert _FIXTURE_PATH_FRAGMENT not in node.value, (
                        f"{func_name}() still hardcodes the in-repo fixture path "
                        f"{node.value!r}"
                    )


# ===========================================================================
# Behavior 2 -- the listing helper can no longer produce an in-repo run: its
# workspace is an explicit parameter with NO default.
# ===========================================================================
def test_b02_listing_helper_requires_an_explicit_workspace(target_tree):
    fn = _func(target_tree, LISTING_HELPER)
    params = [a.arg for a in fn.args.args]
    assert params and params[0] == "workspace", (
        f"{LISTING_HELPER}() must take the workspace as its first parameter; got {params}"
    )
    assert not fn.args.defaults, (
        f"{LISTING_HELPER}() must carry NO positional default -- a default would hand a "
        "caller an in-repo run by omission; got "
        f"{[ast.unparse(d) for d in fn.args.defaults]}"
    )
    assert not [d for d in fn.args.kw_defaults or [] if d is not None], (
        f"{LISTING_HELPER}() must carry no keyword default either"
    )


def test_b02_listing_helper_body_makes_no_in_repo_run(target_tree):
    fn = _func(target_tree, LISTING_HELPER)
    offenders = [ast.unparse(c) for c in _direct_in_repo_runs(fn)]
    assert offenders == [], (
        f"{LISTING_HELPER}() must not pin the in-repo fixture in any run; got {offenders}"
    )


def test_b02_listing_helper_is_callable_and_needs_the_workspace():
    """Runtime confirmation of the signature contract, not just its AST shape."""
    spec = importlib.util.spec_from_file_location("_iter99_under_test_b02", TARGET_MODULE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    helper = getattr(module, LISTING_HELPER, None)
    assert helper is not None, f"{TARGET_MODULE.name} must keep exposing {LISTING_HELPER}"
    with pytest.raises(TypeError):
        helper()  # no workspace -> cannot silently default to the in-repo fixture


# ===========================================================================
# Behavior 3 -- the preserved assertions are not weakened: same relationship,
# same `==`, no subset/`in`/conditional/normalized comparison.
# ===========================================================================
_PRESERVED_EQ = {
    "test_b01_human_summary_end_to_end_via_cli": ("counts", "_listing_counts_via_cli(WS, [])"),
    "test_b03_json_summary_end_to_end_via_cli": (
        "doc['summary']",
        "_listing_counts_via_cli(WS, [])",
    ),
    "test_b05_kind_composition_via_cli": ("doc['summary']", "{kind: listing[kind]}"),
    "test_b07_collector_composition_via_cli": ("doc['summary']", "restricted_listing"),
}


@pytest.mark.parametrize("func_name", TARGET_FUNCS)
def test_b03_preserved_equality_assertion_survives(target_tree, func_name):
    fn = _func(target_tree, func_name)
    pairs = [(_normalize_ws_arg(left), _normalize_ws_arg(right)) for left, right in _eq_pairs(fn)]
    expected = _PRESERVED_EQ[func_name]
    assert expected in pairs, (
        f"{func_name}() must still assert {expected[0]} == {expected[1]} with the same "
        f"`==` operator; found {pairs}"
    )


@pytest.mark.parametrize("func_name", TARGET_FUNCS)
def test_b03_no_relaxation_and_no_conditional_assertions(target_tree, func_name):
    fn = _func(target_tree, func_name)
    # SCOPED DELIBERATELY to the PRESERVED operands. A blanket ban on membership
    # comparisons fires on pre-existing schema assertions that have nothing to do
    # with this migration (test_b03 asserts "'signals' not in doc" -- the summary
    # object carries no listing array), so the guard keys on an operand of the
    # relationship the spec says must not be relaxed.
    protected = {_normalize_ws_arg(t) for t in _PRESERVED_EQ[func_name]}
    for stmt in ast.walk(fn):
        if isinstance(stmt, ast.Assert):
            for cmp_ in ast.walk(stmt.test):
                if not isinstance(cmp_, ast.Compare):
                    continue
                texts = {_normalize_ws_arg(ast.unparse(cmp_.left))} | {
                    _normalize_ws_arg(ast.unparse(c)) for c in cmp_.comparators
                }
                if not (texts & protected) and LISTING_HELPER not in ast.unparse(cmp_):
                    continue
                bad = [
                    type(op).__name__
                    for op in cmp_.ops
                    if isinstance(op, (ast.In, ast.NotIn, ast.Is, ast.IsNot))
                ]
                assert not bad, (
                    f"{func_name}() must not relax a compared value to a membership "
                    f"check; got {ast.unparse(cmp_)}"
                )
    softeners = {"issubset", "issuperset", "approx", "lower", "strip", "startswith"}
    for call in ast.walk(fn):
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute):
            assert call.func.attr not in softeners, (
                f"{func_name}() must not normalize/soften a compared value; got "
                f"{ast.unparse(call)}"
            )
    ifs = [n for n in ast.walk(fn) if isinstance(n, (ast.If, ast.Try))]
    assert not ifs, f"{func_name}() must assert unconditionally (no if/try wrapper)"


@pytest.mark.parametrize("func_name", TARGET_FUNCS)
def test_b03_fail_closed_non_vacuity_guard_is_present(target_tree, func_name):
    """Each migrated function must still refuse to pass on an empty selection."""
    fn = _func(target_tree, func_name)
    has_guard = False
    for stmt in ast.walk(fn):
        if not isinstance(stmt, ast.Assert):
            continue
        for cmp_ in ast.walk(stmt.test):
            if isinstance(cmp_, ast.Compare) and any(isinstance(op, ast.Gt) for op in cmp_.ops):
                for node in ast.walk(cmp_):
                    if isinstance(node, ast.Constant) and node.value == 0:
                        has_guard = True
    assert has_guard, (
        f"{func_name}() must keep a fail-closed 'total > 0' guard so the preserved "
        "equality cannot pass over two empty selections"
    )


# ===========================================================================
# Behavior 4 -- over the isolated copy the compared mappings are NON-EMPTY:
# at least one kind present and a total greater than zero. Derived at run time;
# no fixture count is transcribed.
# ===========================================================================
def test_b04_isolated_copy_summary_is_non_empty_and_matches_the_listing(tmp_path):
    ws = str(_isolated_copy(tmp_path / "fixture_copy"))
    doc = _summary_json(ws)
    assert doc["summary"], f"the isolated copy must still surface signals; got {doc!r}"
    assert doc["total"] > 0, f"total must be positive; got {doc!r}"
    assert doc["summary"] == _listing_counts(ws), "summary counts must match the listing view"
    assert doc["total"] == sum(doc["summary"].values())


def test_b04_isolated_copy_kind_and_collector_compositions_are_non_empty(tmp_path):
    ws = str(_isolated_copy(tmp_path / "fixture_copy"))
    listing = _listing_counts(ws)
    assert listing, "the copy must surface at least one kind"
    kind = sorted(listing)[0]
    kind_doc = _summary_json(ws, ["--kind", kind])
    assert kind_doc["summary"] == {kind: listing[kind]}
    assert kind_doc["total"] == listing[kind] > 0
    restricted = _listing_counts(ws, ["--collector", "notes"])
    assert restricted, "the notes collector must fire over the copy"
    notes_doc = _summary_json(ws, ["--collector", "notes"])
    assert notes_doc["summary"] == restricted
    assert notes_doc["total"] == sum(restricted.values()) > 0


def test_b04_no_git_family_kind_reaches_the_copy(tmp_path):
    """Why the counts must be derived, never transcribed: the copy carries no
    .git, so the git-family kinds present over the in-repo path are absent."""
    ws = str(_isolated_copy(tmp_path / "fixture_copy"))
    kinds = set(_listing_counts(ws))
    leaked = {k for k in kinds if k.startswith("git_") or k == "working_tree"}
    assert not leaked, f"a copy outside any repo must surface no git-family kind; got {leaked}"


# ===========================================================================
# Behavior 5 -- the widened census sees helper-indirect runs, and the shipped
# target module has no member left.
# ===========================================================================
def test_b05_widened_census_of_the_target_module_is_empty(target_tree):
    members = _census_helper_indirect(target_tree)
    assert members == [], (
        "these test functions still reach two or more in-repo-fixture CLI runs "
        f"(directly or via a module-level helper): {members}"
    )


def test_b05_census_is_not_vacuous_it_still_sees_single_in_repo_runs(target_tree):
    """Non-vacuity anchor: the census machinery is not simply blind to in-repo
    runs. Some functions legitimately make ONE (they compare nothing across
    runs), and the counter must still see them."""
    helpers = _module_functions(target_tree)
    counted = {
        fn.name: _reachable_in_repo_runs(fn, helpers)
        for fn in target_tree.body
        if isinstance(fn, ast.FunctionDef) and fn.name.startswith("test")
    }
    assert any(v >= 1 for v in counted.values()), (
        "the in-repo-run counter reports zero everywhere, so a regression would be "
        f"invisible; counts={counted}"
    )
    assert max(counted.values()) < 2, f"max reachable in-repo runs must be < 2; got {counted}"


def test_b05_census_is_transitive_through_module_level_helpers():
    """The widening itself: a run made INSIDE a helper counts for the caller."""
    tree = ast.parse(_BAD_MODULE)
    helpers = _module_functions(tree)
    fn = helpers["test_planted_helper_indirect"]
    assert len(_direct_in_repo_runs(fn)) == 1, "the planted function makes ONE direct run"
    assert _reachable_in_repo_runs(fn, helpers) == 2, (
        "the second run comes from the module-level helper and must be counted"
    )


# ===========================================================================
# Behavior 6 -- two-sided proof, including the shipped narrow census's blind
# spot on the bad half.
# ===========================================================================
def test_b06_widened_census_names_the_helper_indirect_name_eq_call_shape():
    assert _census_helper_indirect(ast.parse(_BAD_MODULE)) == ["test_planted_helper_indirect"], (
        "the census must name a function that compares one direct in-repo run against "
        "a helper-produced in-repo run as `<name> == <helper_call>(...)`"
    )


def test_b06_widened_census_clears_the_isolated_variant():
    assert _census_helper_indirect(ast.parse(_GOOD_MODULE)) == [], (
        "rooting the helper's run at a tmp_path workspace must clear the census"
    )


def test_b06_shipped_narrow_census_is_silent_on_the_bad_half():
    """The reason this iteration exists: the iter-150 census reports the class
    CLOSED while a helper-indirect member is live. Recording it keeps both
    oracles and makes the blind spot itself a regression test."""
    narrow = _load_narrow_census()
    assert narrow(ast.parse(_BAD_MODULE)) == [], (
        "expected the narrow census to be SILENT on the helper-indirect shape; if it "
        "now reports it, this module's widening is redundant and the note above is stale"
    )
    assert narrow(ast.parse(_GOOD_MODULE)) == [], "the narrow census must clear the good half too"
    assert _census_helper_indirect(ast.parse(_BAD_MODULE)) != narrow(ast.parse(_BAD_MODULE)), (
        "the widened census must be strictly wider than the shipped narrow one"
    )


def test_b06_narrow_census_still_passes_over_the_target_module(target_tree):
    """Out of scope says the iter-150 census stays as shipped, so it must remain
    green over the target module as well."""
    assert _load_narrow_census()(target_tree) == []


# ===========================================================================
# Anchor -- this iteration is test-side only: the shipped CLI surface and
# version are untouched.
# ===========================================================================
def test_anchor_version_unchanged():
    from proactive_loop import __version__

    assert __version__ == "0.1.1", f"a test-only iteration must not bump the version; got {__version__!r}"


def test_anchor_signals_summary_still_works_over_a_tmp_workspace(tmp_path):
    ws = tmp_path / "empty_ws"
    ws.mkdir()
    (ws / "notes.md").write_text("TODO: still collectible\n", encoding="utf-8")
    code, out, err = _run(["signals", "--workspace", str(ws), "--summary"])
    assert code == 0, f"stderr={err!r}"
    assert out.endswith("\n"), f"the CLI must end with a newline; got {out!r}"
