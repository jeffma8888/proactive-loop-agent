"""Behavior tests for factory iteration 159: the two duplicated ``test_eb8_*``
nested clean-project pytest runs in ``tests/test_iter142_behavior.py`` collapse
into ONE nested child, and every guard that reads that file stays green.

What the change is, black-box: iteration 142's Behavior 8 was proved by TWO
tests that built a byte-identical one-test fixture project and each spawned its
own ``pytest -n 2`` child, differing only by ``-v``. ``-v`` is purely additive to
stdout, so the verbose child satisfies both oracles verbatim and the second child
was pure duplication -- one fewer 3-process tree hangs off a suite that already
runs ``-n auto``. Suite wall-time is a graded ship gate (the foundry post-release
check flips a ship to BROKEN past 120s fresh-clone wall-time), so removing a
redundant nested pool serves the bar directly.

NO BEHAVIOR BELOW ASSERTS A DURATION OR A TIMING BOUND. That is deliberate and it
is the spec's own rule: a wall-clock assertion is flaky, and the iteration's own
paired A/B measurement did NOT reproduce a saving on a 12-core box (the merged
tree measured marginally SLOWER, inside run-to-run drift, because under xdist
``load`` the two children land on different workers so the critical path is one of
them and never their sum). The deletion of a redundant process tree is evidenced
here by a CALL-SITE CENSUS, never by a timer -- which is why this oracle stays
deterministic while the timing claim did not survive measurement.

Coverage (numbered to match the iteration spec's Expected Behaviors):

1. An ``ast`` census of ``tests/test_iter142_behavior.py`` finds exactly ONE
   nested-pytest ``subprocess.run`` call site owned by a ``test_eb8_*`` function
   (there were exactly 2 before this change).
2. That surviving call site pins ``-n`` to the literal ``"2"``, carries ``-p``,
   ``no:cacheprovider`` and ``-v``, passes a ``cwd=`` keyword, and passes
   ``env=_clean_env(...)`` -- the env value is a ``Call`` to the name
   ``_clean_env``.
3. All three of the original assertions survive in the merged function:
   ``returncode == 0``, ``1 passed`` (against ``proc.stdout`` specifically) and
   ``worker``.
4. The merged test builds its clean project under the test's ``tmp_path`` -- one
   ``tests/`` subdir holding one trivial passing module -- and NOT in the repo;
   its coverage artifact is redirected into ``tmp_path`` too, and no fixture
   directory or fixture module has leaked into the repo.
5. Repo-wide invariant preserved: the corpus still holds >= 4 nested-pytest call
   sites and every one pins a statically-known numeric ``-n`` (never ``auto`` /
   ``logical``) no larger than 4 workers -- i.e. iteration 149's
   ``TestRepoWideNestedPytestGuard`` cannot have gone vacuous or red.
6. Iteration 142's Behavior-9 pins are untouched: exactly 2 nested call sites
   owned by ``test_eb9_*`` functions, both original function names still present,
   the ``env=_clean_env`` redirection still on >= 2 call sites in that file, and
   iteration 149's name-pinning guard class still present.
7. Nothing outside the merge moved: ``addopts`` is still exactly ``-q -n auto``,
   the runtime dependency list is still exactly ``["pydantic>=2.7"]``, the dev
   group still declares every tool, no ``conftest.py`` was added, and no pytest
   fixture in the edited file holds a nested pytest run (a module/class/session
   fixture is PER-WORKER under xdist ``load``, so hoisting the child into one
   would let it run twice -- the spec exists partly to forbid that shape).
8. The merged test carries an in-source comment naming why the two runs were
   merged and what was given up (the plain, non-``-v`` invocation is no longer
   exercised separately), and it does NOT republish the retracted wall-time
   numbers that the iteration's own control measurement falsified.

On spec Behavior 3(a) -- "running that single test with the repo's pytest passes".
That is not re-run from inside this module on purpose: the merged test is part of
the same suite, so the suite run IS that assertion, and spawning yet another
nested pytest here to re-prove it would re-add exactly the process tree this
iteration removes. It was additionally run in isolation by the tester and the
verbatim outcome is recorded in this iteration's ``tester.md``.

Offline, deterministic, no network. Every check is a pure ``ast``/``tokenize``
read of tracked files plus two path-existence checks; nothing here depends on
this machine's core count, on gitignored state, or on execution order.
"""

from __future__ import annotations

import ast
import io
import re
import tokenize
import tomllib
from pathlib import Path
from typing import NamedTuple

import pytest

REPO = Path(__file__).resolve().parents[1]
TESTS_DIR = REPO / "tests"
TARGET = TESTS_DIR / "test_iter142_behavior.py"
GUARD = TESTS_DIR / "test_iter149_behavior.py"

EB8_PREFIX = "test_eb8_"
EB9_PREFIX = "test_eb9_"
EXPECTED_ADDOPTS = "-q -n auto"
EXPECTED_RUNTIME_DEPS = ["pydantic>=2.7"]
REQUIRED_DEV_TOOLS = {"pytest", "pytest-cov", "pytest-xdist", "mypy"}
MAX_WORKERS = 4
FORBIDDEN_COUNTS = ("auto", "logical")

# The two Behavior-9 functions iteration 149 pins BY NAME. Spelled out here so a
# rename shows up as a failure in this oracle too, not only in that one.
EB9_FUNCTIONS = (
    "test_eb9_coverage_reports_a_real_total_under_inherited_parallelism",
    "test_eb9_run_left_no_coverage_artifact_in_the_repo_root",
)

# The fixture project the merged test builds under tmp_path. If either of these
# ever appears in the repo, the child was run in the wrong place.
FIXTURE_DIR_NAME = "clean"
FIXTURE_MODULE_NAME = "test_smoke.py"

# Numbers the iteration's own paired A/B control falsified. They must not be
# republished at the call site -- a source comment is the channel a reader
# actually opens, so a retracted measurement left there outlives the commit
# message that retracted it.
RETRACTED_TIMING_CLAIMS = ("14.5%", "6.04s", "6.59s", "24.74s")

# "-n2" / "-n=2" / "-nauto": one literal carrying its own count. A bare "-n" does
# not match, which keeps the flag-plus-value form on its own code path below.
_WORKER_LITERAL = re.compile(r"^-n=?(?P<count>.+)$")


# --------------------------------------------------------------------------
# The census. Pure ``ast``: no import of anything under test, no child process,
# no clock. Deliberately a local copy of the predicate rather than an import
# from a sibling oracle, so the two cannot drift into agreeing by construction.
# --------------------------------------------------------------------------
class NestedPytestCall(NamedTuple):
    """One ``subprocess.run([... "-m", "pytest" ...])`` call site."""

    owner: str
    lineno: int
    argv: tuple[str | None, ...]
    pinned: str | None
    keywords: tuple[str, ...]
    env_callee: str | None


def _module_string_constants(tree: ast.Module) -> dict[str, str]:
    """Module-level ``NAME = "literal"`` bindings, for the ``Name`` argv form."""
    consts: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets: list[ast.expr] = list(node.targets)
            value = node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
            value = node.value
        else:
            continue
        if not (isinstance(value, ast.Constant) and isinstance(value.value, str)):
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                consts[target.id] = value.value
    return consts


def _resolve(element: ast.expr, consts: dict[str, str]) -> str | None:
    if isinstance(element, ast.Constant) and isinstance(element.value, str):
        return element.value
    if isinstance(element, ast.Name):
        return consts.get(element.id)
    return None


def _is_subprocess_run(call: ast.Call) -> bool:
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr == "run"
    if isinstance(func, ast.Name):
        return func.id == "run"
    return False


def _argv_list(call: ast.Call) -> ast.List | None:
    if not call.args:
        return None
    first = call.args[0]
    return first if isinstance(first, ast.List) else None


def _is_nested_pytest(resolved: list[str | None]) -> bool:
    return any(
        resolved[i] == "-m" and resolved[i + 1] == "pytest" for i in range(len(resolved) - 1)
    )


def _pinned_worker_spec(resolved: list[str | None]) -> str | None:
    """The worker count this argv pins, or None when ``-n`` is absent. Last wins."""
    spec: str | None = None
    for index, item in enumerate(resolved):
        if item is None:
            continue
        if item == "-n":
            following = resolved[index + 1] if index + 1 < len(resolved) else None
            if following is not None:
                spec = following
            continue
        match = _WORKER_LITERAL.match(item)
        if match is not None:
            spec = match.group("count")
    return spec


def _env_callee(call: ast.Call) -> str | None:
    """Name of the callable passed as ``env=<callee>(...)``, or None."""
    for keyword in call.keywords:
        if keyword.arg != "env" or not isinstance(keyword.value, ast.Call):
            continue
        func = keyword.value.func
        if isinstance(func, ast.Name):
            return func.id
        if isinstance(func, ast.Attribute):
            return func.attr
    return None


def _scan(source: str) -> list[NestedPytestCall]:
    """Every nested pytest call in ``source``, with its enclosing function name."""
    tree = ast.parse(source)
    consts = _module_string_constants(tree)
    found: list[NestedPytestCall] = []

    def walk(node: ast.AST, owner: str) -> None:
        for child in ast.iter_child_nodes(node):
            child_owner = (
                child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else owner
            )
            if isinstance(child, ast.Call) and _is_subprocess_run(child):
                argv = _argv_list(child)
                if argv is not None:
                    resolved = [_resolve(element, consts) for element in argv.elts]
                    if _is_nested_pytest(resolved):
                        found.append(
                            NestedPytestCall(
                                owner=child_owner,
                                lineno=child.lineno,
                                argv=tuple(resolved),
                                pinned=_pinned_worker_spec(resolved),
                                keywords=tuple(k.arg for k in child.keywords if k.arg),
                                env_callee=_env_callee(child),
                            )
                        )
            walk(child, child_owner)

    walk(tree, "<module>")
    return sorted(found, key=lambda call: call.lineno)


def _scan_file(path: Path) -> list[NestedPytestCall]:
    return _scan(path.read_text(encoding="utf-8"))


def _functions(source: str) -> dict[str, ast.FunctionDef]:
    """Every function definition in ``source``, keyed by name (last wins)."""
    out: dict[str, ast.FunctionDef] = {}
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.FunctionDef):
            out[node.name] = node
    return out


def _function_source(source: str, name: str) -> str:
    functions = _functions(source)
    assert name in functions, f"{name} is not defined -- functions: {sorted(functions)}"
    return ast.get_source_segment(source, functions[name]) or ""


def _comments_in_span(source: str, first_line: int, last_line: int) -> str:
    """All comment text on lines ``first_line..last_line``, newline-joined."""
    tokens = tokenize.generate_tokens(io.StringIO(source).readline)
    return "\n".join(
        token.string
        for token in tokens
        if token.type == tokenize.COMMENT and first_line <= token.start[0] <= last_line
    )


def _is_fixture_decorator(node: ast.expr) -> bool:
    """True for ``@pytest.fixture`` and ``@pytest.fixture(...)`` in any spelling."""
    target = node.func if isinstance(node, ast.Call) else node
    if isinstance(target, ast.Attribute):
        return target.attr == "fixture"
    if isinstance(target, ast.Name):
        return target.id == "fixture"
    return False


def _pyproject() -> dict[str, object]:
    with (REPO / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)


def _requirement_name(entry: str) -> str:
    return re.split(r"[<>=!~\[; ]", entry.strip(), maxsplit=1)[0].lower()


@pytest.fixture(scope="module")
def target_source() -> str:
    return TARGET.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def target_calls() -> list[NestedPytestCall]:
    return _scan_file(TARGET)


def _eb8_calls(calls: list[NestedPytestCall]) -> list[NestedPytestCall]:
    return [call for call in calls if call.owner.startswith(EB8_PREFIX)]


def _eb9_calls(calls: list[NestedPytestCall]) -> list[NestedPytestCall]:
    return [call for call in calls if call.owner.startswith(EB9_PREFIX)]


# A planted sample, used to prove the census is two-sided: a matcher that has
# quietly stopped recognizing call sites would otherwise make every "exactly one"
# and "count is zero" assertion below pass for the wrong reason.
PLANTED_NESTED = (
    "import subprocess, sys\n"
    "def test_eb8_planted(tmp_path):\n"
    "    proc = subprocess.run(\n"
    '        [sys.executable, "-m", "pytest", "-n", "3", "-v"],\n'
    "        cwd=str(tmp_path), env=_clean_env(tmp_path),\n"
    "    )\n"
    "def test_eb9_planted(tmp_path):\n"
    '    subprocess.run([sys.executable, "-m", "pytest", "-nauto"], cwd=str(tmp_path))\n'
)


# ==========================================================================
# Behavior 1: the eb8 duplication is gone.
# ==========================================================================
class TestBehavior1OneEb8CallSiteRemains:
    def test_b1_exactly_one_eb8_nested_pytest_call_site(
        self, target_calls: list[NestedPytestCall]
    ) -> None:
        eb8 = _eb8_calls(target_calls)
        sites = [f"{TARGET.name}:{call.lineno} ({call.owner})" for call in eb8]
        assert len(eb8) == 1, (
            "behavior 1 requires exactly ONE nested clean-project pytest child "
            f"owned by a {EB8_PREFIX}* function (there were 2 before the merge); "
            f"found {len(eb8)}: {sites}"
        )

    def test_b1_census_is_two_sided(self) -> None:
        planted = _scan(PLANTED_NESTED)
        assert len(planted) == 2, f"the census missed a planted nested run: {planted}"
        assert len(_eb8_calls(planted)) == 1, planted
        assert _scan("import subprocess\ndef test_x():\n    subprocess.run(['ls'])\n") == [], (
            "the census counted a non-pytest subprocess call, so 'exactly one' "
            "above would be satisfiable by an unrelated call site"
        )


# ==========================================================================
# Behavior 2: the surviving call site keeps the whole argv contract.
# ==========================================================================
class TestBehavior2SurvivingCallSiteContract:
    def test_b2_pins_exactly_two_workers(self, target_calls: list[NestedPytestCall]) -> None:
        call = _eb8_calls(target_calls)[0]
        assert call.pinned == "2", (
            f"{TARGET.name}:{call.lineno} must pin '-n' to the literal '2' so the "
            "child cannot inherit '-q -n auto' and nest a full worker pool inside "
            f"the parallel parent suite; pinned={call.pinned!r}"
        )

    @pytest.mark.parametrize("flag", ["-p", "no:cacheprovider", "-v"])
    def test_b2_argv_carries_the_required_flags(
        self, target_calls: list[NestedPytestCall], flag: str
    ) -> None:
        call = _eb8_calls(target_calls)[0]
        assert flag in call.argv, (
            f"{flag!r} missing from the surviving child argv {call.argv} -- "
            "'-p no:cacheprovider' keeps the child from writing a cache into the "
            "fixture project, and '-v' is what makes the worker banner observable"
        )

    def test_b2_passes_a_cwd_keyword(self, target_calls: list[NestedPytestCall]) -> None:
        call = _eb8_calls(target_calls)[0]
        assert "cwd" in call.keywords, (
            "the child must run with cwd= pointing at the throwaway fixture "
            f"project, not at the repo; keywords={call.keywords}"
        )

    def test_b2_env_is_a_clean_env_call(self, target_calls: list[NestedPytestCall]) -> None:
        call = _eb8_calls(target_calls)[0]
        assert call.env_callee == "_clean_env", (
            "the child must be handed env=_clean_env(...) so PYTEST_ADDOPTS is "
            "cleared and COVERAGE_FILE is redirected out of the repo; "
            f"env callee={call.env_callee!r}"
        )


# ==========================================================================
# Behavior 3: all three original assertions survived the merge.
# ==========================================================================
class TestBehavior3MergedAssertionsSurvive:
    @pytest.mark.parametrize("fragment", ["returncode == 0", "1 passed", "worker"])
    def test_b3_merged_function_keeps_every_original_assertion(
        self, target_source: str, target_calls: list[NestedPytestCall], fragment: str
    ) -> None:
        owner = _eb8_calls(target_calls)[0].owner
        body = _function_source(target_source, owner)
        assert fragment in body, (
            f"{owner} dropped the {fragment!r} assertion -- the merge must be a "
            "union of both original oracles, not a replacement of one by the other"
        )

    def test_b3_one_passed_is_asserted_against_stdout_specifically(
        self, target_source: str, target_calls: list[NestedPytestCall]
    ) -> None:
        owner = _eb8_calls(target_calls)[0].owner
        body = _function_source(target_source, owner)
        assert re.search(r'"1 passed"\s+in\s+proc\.stdout', body), (
            "'1 passed' must be asserted against proc.stdout, not the combined "
            "streams: pytest never writes its summary line to stderr, so accepting "
            "stdout+stderr would let a stderr echo satisfy the oracle"
        )

    def test_b3_worker_assertion_is_case_insensitive_on_combined_output(
        self, target_source: str, target_calls: list[NestedPytestCall]
    ) -> None:
        owner = _eb8_calls(target_calls)[0].owner
        body = _function_source(target_source, owner)
        assert ".lower()" in body, (
            "the worker-banner assertion must lowercase the combined output; "
            "xdist has spelled that banner several ways across versions"
        )


# ==========================================================================
# Behavior 4: the fixture project stays out of the repo.
# ==========================================================================
class TestBehavior4FixtureStaysUnderTmpPath:
    def test_b4_project_and_coverage_file_are_built_under_tmp_path(
        self, target_source: str, target_calls: list[NestedPytestCall]
    ) -> None:
        owner = _eb8_calls(target_calls)[0].owner
        body = _function_source(target_source, owner)
        assert "tmp_path /" in body, (
            f"{owner} must build its throwaway project under the test's tmp_path"
        )
        assert re.search(r"_clean_env\(\s*tmp_path\s*/", body), (
            "COVERAGE_FILE must be redirected into tmp_path, or the child races "
            "the repo-root .coverage artifact that iteration 52's oracles own"
        )
        assert "REPO" not in body, (
            f"{owner} references REPO -- the clean-project child must never be "
            "pointed at the real repo, whose ini would give it '-n auto'"
        )

    def test_b4_fixture_is_one_tests_subdir_with_one_trivial_module(
        self, target_source: str, target_calls: list[NestedPytestCall]
    ) -> None:
        owner = _eb8_calls(target_calls)[0].owner
        body = _function_source(target_source, owner)
        assert body.count("write_text(") == 1, (
            f"{owner} should write exactly one fixture module; the clean project is "
            "deliberately minimal so the child's cost is the pool, not the tests"
        )
        assert '"tests"' in body and "mkdir(parents=True)" in body, (
            f"{owner} must create a tests/ subdir inside the throwaway project"
        )
        assert FIXTURE_MODULE_NAME in body, (
            f"the fixture module name {FIXTURE_MODULE_NAME!r} is what behavior 4's "
            "leak check below looks for in the repo; keep them in sync"
        )

    def test_b4_no_fixture_artifact_leaked_into_the_repo(self) -> None:
        assert not (REPO / FIXTURE_DIR_NAME).exists(), (
            f"{FIXTURE_DIR_NAME}/ exists in the repo root -- a nested child built "
            "its throwaway project in the repo instead of tmp_path"
        )
        assert not (TESTS_DIR / FIXTURE_MODULE_NAME).exists(), (
            f"tests/{FIXTURE_MODULE_NAME} exists -- the clean-project fixture "
            "leaked into the real suite, where it would be collected forever"
        )


# ==========================================================================
# Behavior 5: the repo-wide nested-pytest invariant still holds.
# ==========================================================================
class TestBehavior5RepoWideCensusPreserved:
    def test_b5_corpus_still_holds_at_least_four_pinned_nested_children(self) -> None:
        scanned = 0
        calls: list[NestedPytestCall] = []
        for path in sorted(TESTS_DIR.glob("test_*.py")):
            scanned += 1
            calls.extend(
                call._replace(owner=f"{path.name}::{call.owner}") for call in _scan_file(path)
            )
        assert scanned >= 100, f"corpus scan found only {scanned} test files -- glob is fail-open"
        assert len(calls) >= 4, (
            f"only {len(calls)} nested pytest children across {scanned} files -- "
            "either the merge deleted more than the one duplicate, or this census "
            "has stopped recognizing call sites and is now vacuous"
        )

    def test_b5_every_nested_child_pins_a_sane_numeric_worker_count(self) -> None:
        offenders: list[str] = []
        for path in sorted(TESTS_DIR.glob("test_*.py")):
            for call in _scan_file(path):
                pinned = call.pinned
                if pinned is None or pinned in FORBIDDEN_COUNTS or not pinned.isdigit():
                    offenders.append(f"{path.name}:{call.lineno} pins {pinned!r}")
                elif int(pinned) > MAX_WORKERS:
                    offenders.append(f"{path.name}:{call.lineno} pins {pinned} workers")
        assert not offenders, (
            "every nested pytest child must pin a small numeric -n; an unpinned or "
            f"'auto' child nests a full worker pool inside the suite: {offenders}"
        )

    def test_b5_worker_pin_detector_is_two_sided(self) -> None:
        planted = _scan(PLANTED_NESTED)
        pins = sorted(str(call.pinned) for call in planted)
        assert pins == ["3", "auto"], (
            f"the pin detector must read both the '-n 3' and '-nauto' forms; got {pins}"
        )


# ==========================================================================
# Behavior 6: iteration 142's Behavior-9 pair is untouched.
# ==========================================================================
class TestBehavior6Eb9PairUntouched:
    def test_b6_exactly_two_eb9_nested_call_sites(
        self, target_calls: list[NestedPytestCall]
    ) -> None:
        eb9 = _eb9_calls(target_calls)
        assert len(eb9) == 2, (
            "the two Behavior-9 coverage children are explicitly out of scope for "
            f"this iteration; found {len(eb9)}: {[c.lineno for c in eb9]}"
        )

    @pytest.mark.parametrize("name", EB9_FUNCTIONS)
    def test_b6_both_eb9_functions_still_exist_by_name(
        self, target_source: str, name: str
    ) -> None:
        assert name in _functions(target_source), (
            f"{name} is gone -- iteration 149 pins this function BY EXACT NAME, so "
            "renaming it turns TestBehavior9AssertionsSurvive red"
        )

    def test_b6_clean_env_redirection_still_on_at_least_two_call_sites(
        self, target_calls: list[NestedPytestCall]
    ) -> None:
        checked = [call for call in target_calls if call.env_callee == "_clean_env"]
        assert len(checked) >= 2, (
            "iteration 149 requires at least two nested children in this file to "
            "route coverage through _clean_env; the merge takes that count 4 -> 3, "
            f"found {len(checked)}"
        )

    def test_b6_iteration_149_name_pinning_guard_is_still_present(self) -> None:
        guard_source = GUARD.read_text(encoding="utf-8")
        classes = {
            node.name for node in ast.walk(ast.parse(guard_source)) if isinstance(node, ast.ClassDef)
        }
        assert "TestBehavior9AssertionsSurvive" in classes, (
            "iteration 149's name-pinning guard class is gone, so behavior 6 would "
            f"have nothing enforcing it between iterations; classes={sorted(classes)}"
        )
        assert 'BEHAVIOR9_PREFIX = "test_eb9_"' in guard_source, (
            "iteration 149 no longer pins the eb9 prefix it is supposed to pin"
        )


# ==========================================================================
# Behavior 7: nothing outside the merge changed.
# ==========================================================================
class TestBehavior7NothingElseMoved:
    def test_b7_addopts_is_still_exactly_q_n_auto(self) -> None:
        ini = _pyproject().get("tool", {})
        assert isinstance(ini, dict)
        addopts = ini.get("pytest", {}).get("ini_options", {}).get("addopts")
        assert addopts == EXPECTED_ADDOPTS, (
            f"addopts must stay exactly {EXPECTED_ADDOPTS!r}; got {addopts!r}. This "
            "iteration buys throughput by deleting a duplicated child, never by "
            "touching worker counts or xdist distribution mode"
        )

    def test_b7_runtime_dependency_list_is_unchanged(self) -> None:
        project = _pyproject().get("project", {})
        assert isinstance(project, dict)
        assert project.get("dependencies") == EXPECTED_RUNTIME_DEPS, (
            "the runtime dependency set must stay pydantic-only; got "
            f"{project.get('dependencies')!r}"
        )

    def test_b7_dev_group_still_declares_every_tool(self) -> None:
        groups = _pyproject().get("dependency-groups", {})
        assert isinstance(groups, dict)
        dev = groups.get("dev")
        assert isinstance(dev, list) and dev
        names = {_requirement_name(str(entry)) for entry in dev}
        missing = REQUIRED_DEV_TOOLS - names
        assert not missing, f"dev group lost {sorted(missing)}; declared={sorted(names)}"

    def test_b7_no_conftest_was_added(self) -> None:
        found = [
            str(path.relative_to(REPO))
            for path in [REPO / "conftest.py", TESTS_DIR / "conftest.py"]
            if path.exists()
        ]
        assert found == [], (
            "this iteration adds no conftest.py: three corpus guards glob "
            f"tests/test_*.py, so a conftest is a blind spot by construction: {found}"
        )

    def test_b7_no_pytest_fixture_holds_a_nested_pytest_run(self, target_source: str) -> None:
        offenders: list[str] = []
        for node in ast.walk(ast.parse(target_source)):
            if not isinstance(node, ast.FunctionDef):
                continue
            if not any(_is_fixture_decorator(dec) for dec in node.decorator_list):
                continue
            fixture_source = ast.get_source_segment(target_source, node) or ""
            if _scan(f"def _wrapper():\n" + "\n".join(
                f"    {line}" for line in fixture_source.splitlines()
            )):
                offenders.append(node.name)
        assert offenders == [], (
            "a nested pytest run must not live in a pytest fixture: under xdist's "
            "default 'load' distribution a module/class/session fixture is "
            "PER-WORKER, so two tests on two workers would spawn the child TWICE "
            f"and the deduplication would measure zero: {offenders}"
        )


# ==========================================================================
# Behavior 8: the trade is documented at the call site, honestly.
# ==========================================================================
class TestBehavior8TradeIsDocumentedAtTheCallSite:
    def test_b8_comment_names_the_merge_and_what_was_given_up(
        self, target_source: str, target_calls: list[NestedPytestCall]
    ) -> None:
        owner = _eb8_calls(target_calls)[0].owner
        node = _functions(target_source)[owner]
        end = node.end_lineno or node.lineno
        comments = _comments_in_span(target_source, node.lineno, end).lower()
        assert comments, f"{owner} carries no in-source comment at all"
        for phrase in ("merge", "given up", "plain", "-v"):
            assert phrase in comments, (
                f"the merge comment must name {phrase!r} so the trade is "
                "discoverable at the call site rather than only in the iteration "
                f"spec; comment text={comments!r}"
            )

    def test_b8_comment_scanner_is_two_sided(self) -> None:
        planted = "def f():\n    # merged, and this is what we gave up: the plain -v run\n    pass\n"
        assert "gave up" in _comments_in_span(planted, 1, 3)
        assert _comments_in_span("def f():\n    pass\n", 1, 2) == "", (
            "the comment scanner reported a comment where there is none"
        )

    @pytest.mark.parametrize("claim", RETRACTED_TIMING_CLAIMS)
    def test_b8_retracted_wall_time_numbers_are_not_republished(
        self, target_source: str, claim: str
    ) -> None:
        assert claim not in target_source, (
            f"{claim!r} is a wall-time figure this iteration's own paired A/B "
            "control falsified (the merged tree measured marginally slower, inside "
            "run-to-run drift). A source comment is the channel a reader opens, so "
            "a retracted number left here outlives the commit message that "
            "retracted it"
        )

    def test_b8_retraction_matcher_is_two_sided(self) -> None:
        planted = "# the merge bought 14.5% of suite wall-time\n"
        assert any(claim in planted for claim in RETRACTED_TIMING_CLAIMS), (
            "the retracted-number matcher does not fire on a planted claim, so the "
            "absence it reports above is evidence of nothing"
        )
