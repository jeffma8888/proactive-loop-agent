"""Black-box behavior tests for iteration 149 (foundry iteration 142).

Feature under test: the nested ``pytest`` child processes this suite spawns must
PIN an explicit xdist worker count instead of inheriting
``[tool.pytest.ini_options].addopts = "-q -n auto"`` from the repo's
``pyproject.toml``. A ``cwd=REPO`` child that inherits ``-n auto`` brings up a
second full-width worker pool *inside* the already-parallel parent suite, so the
box is oversubscribed ~3x -- strictly worse on the public CI matrix, whose
runners have 2-4 cores. The iteration pins the two offending call sites in
``tests/test_iter142_behavior.py`` and adds the guard below so a future author
cannot silently re-nest a full pool.

ISOLATION CONTRACT (honored): these tests were written strictly against this
iteration's PM spec ("Expected Behaviors" 1-9) plus files the tester card allows
-- the repo README, ``ROADMAP.md`` and everything under ``tests/``. No file under
``src/`` was read, no engineer or reviewer note was opened, and no ``git diff``
was inspected.

Coverage (numbered to match the spec's Expected Behaviors):

1. Both nested child runs in the Behavior-9 coverage class of
   ``tests/test_iter142_behavior.py`` pin ``-n``, under the spec's definition:
   an argv list holding adjacent ``"-m"``, ``"pytest"`` is a NESTED PYTEST CALL,
   and it PINS ``-n`` when the list holds a literal ``"-n"`` followed by a count,
   or a single literal of the form ``-n<count>`` / ``-n=<count>``, or a ``Name``
   bound at module level to a string of one of those forms.
2. Neither pins zero: each resolves to a count ``>= 2``, so the cross-worker
   coverage-combination oracle those tests exist for is still exercised.
3. The pinned count is small and explicit: an integer in 2..4, never ``auto``
   and never ``logical``.
4. Repo-wide, unconditional guard: across every ``tests/*.py``, EVERY nested
   pytest call pins ``-n``, with no ``cwd`` condition (a sandbox ``cwd`` is not
   safe either -- ``test_iter146_strict_contract.py`` copies ``pyproject.toml``
   into its sandbox, which is why its author pinned ``-n0`` there). The failure
   message reports every offending ``file:line``.
5. The guard accepts any explicit pin and mandates no particular value: ``-n0``,
   ``-n 2``, ``-n=3`` and the ``SERIAL = "-n0"`` module-constant form all pass.
   Only an ABSENT ``-n`` fails.
6. The guard is proven TWO-SIDED against inline synthetic fixtures: a snippet
   holding two unpinned nested calls is reported as exactly two offenders at
   their real line numbers, while the live ``tests/`` tree reports zero.
   DELIBERATE DEVIATION from the spec's wording, which asked for the negative
   side to come from ``git show HEAD:tests/test_iter142_behavior.py``: that is a
   review-time command, not a shippable assertion. Once this change is
   committed, HEAD holds the FIXED file, so a history-keyed negative fixture
   reports 0 where it demands 2 and goes red in the post-release fresh clone.
   Two-sidedness is a property of the PREDICATE, so the negative fixture is
   synthetic and inline. See ``tester.md`` for the PM feedback note.
7. The guard is pure source analysis: this module imports no ``subprocess`` and
   no clock, contains no wall-clock threshold, and spawns no pytest child of its
   own (asserted by running the guard against this very file).
8. The two Behavior-9 tests still assert what they asserted before the pin: a
   non-zero coverage ``TOTAL``, no coverage artifact left in the repo root, and
   an unchanged ``env=_clean_env(...)`` ``COVERAGE_FILE`` redirection. Each call
   site also carries the rationale comment the acceptance criteria require.
9. Full-suite outcome and the suite's test-count growth are the suite run
   itself rather than a test; they are recorded in this iteration's
   ``tester.md``.

Offline, deterministic, no network, no dependency on this machine's core count.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import NamedTuple

import pytest

REPO = Path(__file__).resolve().parents[1]
TESTS_DIR = REPO / "tests"
TARGET = TESTS_DIR / "test_iter142_behavior.py"
SELF = Path(__file__).resolve()

# The spec's own vocabulary, encoded here rather than imported, to keep this
# module black-box against the contract.
BEHAVIOR9_PREFIX = "test_eb9_"
MIN_WORKERS = 2
MAX_WORKERS = 4
FORBIDDEN_COUNTS = ("auto", "logical")

# "-n2" / "-n=2" / "-nauto" -- a single literal carrying its own count. A bare
# "-n" does NOT match (the count group requires at least one character), which
# is what keeps the flag-plus-value form on its own code path below.
_WORKER_LITERAL = re.compile(r"^-n=?(?P<count>.+)$")


# --------------------------------------------------------------------------
# The predicate. Pure ``ast``: no import of the module under test, no pytest
# child process, no clock.
# --------------------------------------------------------------------------
class NestedPytestCall(NamedTuple):
    """One ``subprocess.run([... "-m", "pytest" ...])`` call site."""

    owner: str
    lineno: int
    pinned: str | None


def _module_string_constants(tree: ast.Module) -> dict[str, str]:
    """Module-level ``NAME = "literal"`` bindings, for the ``Name`` pin form."""
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
    """Static string value of one argv element, or None if not statically known."""
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


def _is_nested_pytest(argv: ast.List, consts: dict[str, str]) -> bool:
    resolved = [_resolve(element, consts) for element in argv.elts]
    return any(
        resolved[i] == "-m" and resolved[i + 1] == "pytest" for i in range(len(resolved) - 1)
    )


def _pinned_worker_spec(argv: ast.List, consts: dict[str, str]) -> str | None:
    """The worker count this argv pins, or None when ``-n`` is absent.

    Last ``-n`` wins, matching xdist's own argument handling.
    """
    resolved = [_resolve(element, consts) for element in argv.elts]
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


def _scan(source: str) -> list[NestedPytestCall]:
    """Every nested pytest call in ``source``, with its enclosing function name."""
    tree = ast.parse(source)
    consts = _module_string_constants(tree)
    found: list[NestedPytestCall] = []

    def walk(node: ast.AST, owner: str) -> None:
        for child in ast.iter_child_nodes(node):
            child_owner = (
                child.name
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                else owner
            )
            if isinstance(child, ast.Call) and _is_subprocess_run(child):
                argv = _argv_list(child)
                if argv is not None and _is_nested_pytest(argv, consts):
                    found.append(
                        NestedPytestCall(child_owner, child.lineno, _pinned_worker_spec(argv, consts))
                    )
            walk(child, child_owner)

    walk(tree, "<module>")
    return sorted(found, key=lambda call: call.lineno)


def _scan_file(path: Path) -> list[NestedPytestCall]:
    return _scan(path.read_text(encoding="utf-8"))


def _offenders(path: Path) -> list[str]:
    """``file:line`` for every nested pytest call in ``path`` that leaves ``-n`` unpinned."""
    return [
        f"{path.name}:{call.lineno} (in {call.owner})"
        for call in _scan_file(path)
        if call.pinned is None
    ]


CLOCK_ATTRS = frozenset({"perf_counter", "monotonic", "process_time", "time_ns", "clock"})


def _clock_reads(source: str) -> list[str]:
    """Clock attributes read in ``source`` (``time.perf_counter`` and friends)."""
    return sorted(
        {
            node.attr
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Attribute) and node.attr in CLOCK_ATTRS
        }
    )


def _behavior9_calls() -> list[NestedPytestCall]:
    return [call for call in _scan_file(TARGET) if call.owner.startswith(BEHAVIOR9_PREFIX)]


def _function_source(path: Path, name: str) -> str:
    """Raw source slice of one function, comments included."""
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            segment = ast.get_source_segment(source, node)
            assert segment is not None, f"could not slice source for {name}"
            return segment
    raise AssertionError(f"{path.name} has no function named {name}")


# --------------------------------------------------------------------------
# Synthetic fixtures for the two-sided proof. Inline, not git history: after the
# ship commit HEAD holds the FIXED file, so a history-keyed negative fixture
# inverts and reddens the post-release fresh-clone verification.
# --------------------------------------------------------------------------
UNPINNED_SNIPPET = '''import subprocess
import sys


def one():
    return subprocess.run([sys.executable, "-m", "pytest", "--cov=pkg"], cwd="/repo")


def two():
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "no:cacheprovider",
        ],
        cwd="/repo",
    )
'''

PINNED_SNIPPETS: dict[str, str] = {
    "flag-and-value": 'import subprocess, sys\n'
    'def f():\n'
    '    return subprocess.run([sys.executable, "-m", "pytest", "-n", "2"])\n',
    "joined-literal-zero": 'import subprocess, sys\n'
    'def f():\n'
    '    return subprocess.run([sys.executable, "-m", "pytest", "-n0"])\n',
    "equals-literal": 'import subprocess, sys\n'
    'def f():\n'
    '    return subprocess.run([sys.executable, "-m", "pytest", "-n=3"])\n',
    "module-constant-name": 'import subprocess, sys\n'
    'SERIAL = "-n0"\n'
    'def f(*extra):\n'
    '    return subprocess.run([sys.executable, "-m", "pytest", SERIAL, *extra])\n',
}

NON_PYTEST_SNIPPET = 'import subprocess, sys\n' 'def f():\n' '    return subprocess.run([sys.executable, "-c", "print(1)"])\n'


# ==========================================================================
# Behaviors 1-3: the two Behavior-9 call sites pin a small, explicit count.
# ==========================================================================
class TestBehavior9CallSitesArePinned:
    def test_b1_both_behavior9_nested_runs_pin_a_worker_count(self) -> None:
        calls = _behavior9_calls()
        assert len(calls) == 2, (
            "expected exactly 2 nested pytest calls inside the Behavior-9 coverage "
            f"tests of {TARGET.name}, found {len(calls)}: {calls}"
        )
        unpinned = [f"{TARGET.name}:{call.lineno} (in {call.owner})" for call in calls if call.pinned is None]
        assert not unpinned, (
            "these Behavior-9 child runs inherit addopts '-q -n auto' from the repo "
            f"pyproject and nest a second full worker pool: {unpinned}"
        )

    def test_b2_neither_behavior9_run_pins_zero_workers(self) -> None:
        for call in _behavior9_calls():
            assert call.pinned is not None
            assert call.pinned.isdigit(), (
                f"{TARGET.name}:{call.lineno} pins a non-numeric worker count "
                f"{call.pinned!r}; behavior 3 requires an explicit integer"
            )
            assert int(call.pinned) >= MIN_WORKERS, (
                f"{TARGET.name}:{call.lineno} pins {call.pinned!r}: a serial child "
                "deletes the cross-worker coverage-combination oracle these tests exist for"
            )

    def test_b3_pinned_count_is_small_explicit_and_never_auto(self) -> None:
        for call in _behavior9_calls():
            assert call.pinned not in FORBIDDEN_COUNTS, (
                f"{TARGET.name}:{call.lineno} resolves to {call.pinned!r}, which is the "
                "machine-width setting this iteration exists to remove"
            )
            assert call.pinned is not None and call.pinned.isdigit()
            count = int(call.pinned)
            assert MIN_WORKERS <= count <= MAX_WORKERS, (
                f"{TARGET.name}:{call.lineno} pins {count} workers, outside the "
                f"{MIN_WORKERS}..{MAX_WORKERS} range behavior 3 mandates"
            )


# ==========================================================================
# Behavior 4: repo-wide, unconditional guard over every tests/*.py.
# ==========================================================================
class TestRepoWideNestedPytestGuard:
    def test_b4_every_nested_pytest_call_under_tests_pins_workers(self) -> None:
        scanned = 0
        nested = 0
        offenders: list[str] = []
        for path in sorted(TESTS_DIR.glob("test_*.py")):
            scanned += 1
            calls = _scan_file(path)
            nested += len(calls)
            offenders.extend(_offenders(path))
        assert scanned >= 100, f"corpus scan found only {scanned} test files -- glob is fail-open"
        assert nested >= 4, (
            f"only {nested} nested pytest calls found across {scanned} files -- the "
            "predicate has stopped recognizing call sites, so this guard is vacuous"
        )
        assert not offenders, (
            "these nested pytest children leave -n unpinned, so a cwd=REPO child "
            "inherits '-q -n auto' and nests a full worker pool inside the parallel "
            f"suite: {offenders}"
        )

    def test_b4_guard_is_unconditional_and_ignores_cwd(self) -> None:
        # No cwd condition: resolving what a cwd expression points at is the fragile
        # part, and a sandbox cwd is not safe either -- test_iter146_strict_contract
        # copies pyproject.toml INTO its sandbox, so that child inherits addopts too.
        source = UNPINNED_SNIPPET.replace('cwd="/repo"', "cwd=str(tmp_path)")
        calls = _scan(source)
        assert len(calls) == 2, calls
        assert [call.pinned for call in calls] == [None, None], (
            "a sandbox cwd must not exempt a nested child from the pin requirement"
        )

    def test_b4_failure_message_names_every_offending_file_and_line(self) -> None:
        offenders = _offenders(TARGET)
        assert offenders == [], offenders
        # The formatter itself, proven on a planted offender rather than on the
        # (now clean) real file.
        planted = TESTS_DIR / "test_iter142_behavior.py"
        rendered = [
            f"{planted.name}:{call.lineno} (in {call.owner})"
            for call in _scan(UNPINNED_SNIPPET)
            if call.pinned is None
        ]
        assert rendered == ["test_iter142_behavior.py:6 (in one)", "test_iter142_behavior.py:10 (in two)"], rendered


# ==========================================================================
# Behavior 5: any explicit pin is accepted; only an absent -n fails.
# ==========================================================================
class TestGuardAcceptsAnyExplicitPin:
    @pytest.mark.parametrize("label", sorted(PINNED_SNIPPETS))
    def test_b5_every_pin_spelling_is_accepted(self, label: str) -> None:
        calls = _scan(PINNED_SNIPPETS[label])
        assert len(calls) == 1, f"{label}: expected one nested call, got {calls}"
        assert calls[0].pinned is not None, (
            f"{label}: the guard rejected a legitimately pinned call site, so it "
            "would force a specific worker count instead of merely requiring one"
        )

    def test_b5_resolved_counts_match_each_spelling(self) -> None:
        resolved = {label: _scan(source)[0].pinned for label, source in PINNED_SNIPPETS.items()}
        assert resolved == {
            "flag-and-value": "2",
            "joined-literal-zero": "0",
            "equals-literal": "3",
            "module-constant-name": "0",
        }, resolved

    def test_b5_serial_pin_is_legal_repo_wide_even_though_behavior9_forbids_it(self) -> None:
        # -n0 is a legal repo-wide pin (test_iter52 uses it deliberately); it is only
        # the two Behavior-9 sites that additionally need >= 2 workers.
        calls = _scan(PINNED_SNIPPETS["module-constant-name"])
        assert calls[0].pinned == "0"
        assert not [call for call in calls if call.pinned is None]


# ==========================================================================
# Behavior 6: two-sided proof, against inline synthetic fixtures.
# ==========================================================================
class TestGuardIsTwoSided:
    def test_b6_negative_fixture_reports_exactly_two_offenders(self) -> None:
        calls = _scan(UNPINNED_SNIPPET)
        assert [(call.owner, call.lineno, call.pinned) for call in calls] == [
            ("one", 6, None),
            ("two", 10, None),
        ], calls

    def test_b6_positive_side_worktree_is_clean(self) -> None:
        offenders: list[str] = []
        for path in sorted(TESTS_DIR.glob("test_*.py")):
            offenders.extend(f"{path.name}:{item}" for item in _offenders(path))
        assert offenders == [], offenders

    def test_b6_non_pytest_children_are_not_flagged(self) -> None:
        assert _scan(NON_PYTEST_SNIPPET) == [], (
            "a python -c child is not a nested pytest run; flagging it would make "
            "the guard a false-positive machine"
        )

    def test_b6_bare_dash_n_with_no_count_is_not_a_pin(self) -> None:
        source = 'import subprocess, sys\ndef f():\n    return subprocess.run([sys.executable, "-m", "pytest", "-n"])\n'
        calls = _scan(source)
        assert len(calls) == 1
        assert calls[0].pinned is None, (
            "'-n' with no following count is not an explicit pin -- accepting it "
            "would let a broken argv satisfy the guard"
        )


# ==========================================================================
# Behavior 7: pure, offline source analysis -- no clock, no pytest child.
# ==========================================================================
class TestGuardIsPureSourceAnalysis:
    def test_b7_this_module_imports_no_subprocess_and_no_clock(self) -> None:
        forbidden = {"subprocess", "time", "timeit", "socket", "urllib", "requests"}
        tree = ast.parse(SELF.read_text(encoding="utf-8"))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        leaked = sorted(imported & forbidden)
        assert not leaked, (
            f"this guard must be pure source analysis, but it imports {leaked}; a "
            "timing or subprocess dependency makes it machine-dependent"
        )

    def test_b7_this_module_spawns_no_nested_pytest_child(self) -> None:
        assert _scan_file(SELF) == [], "the guard must not shell out to pytest"

    def test_b7_no_clock_is_read_anywhere_in_this_module(self) -> None:
        # AST-level, not a text scan: a text scan of this file would match its own
        # marker list and fail unconditionally, which proves nothing.
        assert _clock_reads(SELF.read_text(encoding="utf-8")) == [], (
            "this guard reads a clock, so its verdict would depend on how loaded "
            "this machine is; behavior 7 requires pure source analysis"
        )

    def test_b7_clock_detector_fires_on_a_planted_timing_call(self) -> None:
        planted = "import time\nstart = time.perf_counter()\nend = time.monotonic()\n"
        assert _clock_reads(planted) == ["monotonic", "perf_counter"], _clock_reads(planted)


# ==========================================================================
# Behavior 8: the Behavior-9 assertions and their COVERAGE_FILE redirection
# survive the pin, and each call site documents WHY it is pinned.
# ==========================================================================
class TestBehavior9AssertionsSurvive:
    def test_b8_first_behavior9_test_still_asserts_a_real_total(self) -> None:
        source = _function_source(
            TARGET, "test_eb9_coverage_reports_a_real_total_under_inherited_parallelism"
        )
        assert "--cov=proactive_loop" in source
        assert "_TOTAL_PCT.search" in source
        assert "int(match.group(1)) > 0" in source, (
            "the non-zero-TOTAL assertion is the whole point of this test: under xdist, "
            "per-worker data that is never combined reports 0% while the build stays green"
        )

    def test_b8_second_behavior9_test_still_proves_the_redirection(self) -> None:
        source = _function_source(TARGET, "test_eb9_run_left_no_coverage_artifact_in_the_repo_root")
        assert "data_file.exists()" in source
        assert ".coverage-redirect" in source
        assert "COVERAGE_FILE" in source

    def test_b8_both_call_sites_keep_the_clean_env_coverage_redirection(self) -> None:
        source = TARGET.read_text(encoding="utf-8")
        tree = ast.parse(source)
        consts = _module_string_constants(tree)
        checked = 0
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and _is_subprocess_run(node)):
                continue
            argv = _argv_list(node)
            if argv is None or not _is_nested_pytest(argv, consts):
                continue
            keywords = {kw.arg for kw in node.keywords if kw.arg}
            env_kw = next((kw for kw in node.keywords if kw.arg == "env"), None)
            if env_kw is None:
                continue
            checked += 1
            assert "cwd" in keywords, f"{TARGET.name}:{node.lineno} lost its cwd"
            assert isinstance(env_kw.value, ast.Call), (
                f"{TARGET.name}:{node.lineno} no longer calls a helper for env"
            )
            callee = env_kw.value.func
            name = callee.id if isinstance(callee, ast.Name) else getattr(callee, "attr", "")
            assert name == "_clean_env", (
                f"{TARGET.name}:{node.lineno} redirects COVERAGE_FILE via {name!r}, not "
                "_clean_env; behavior 8 requires that redirection unchanged"
            )
        assert checked >= 2, f"only {checked} env=_clean_env nested call sites found"

    def test_b8_each_behavior9_call_site_documents_why_it_is_pinned(self) -> None:
        for name in (
            "test_eb9_coverage_reports_a_real_total_under_inherited_parallelism",
            "test_eb9_run_left_no_coverage_artifact_in_the_repo_root",
        ):
            source = _function_source(TARGET, name).lower()
            assert "addopts" in source, f"{name} does not name the inherited addopts"
            assert "auto" in source, f"{name} does not say what it would inherit"
            assert "nest" in source, f"{name} does not say what the inheritance would cost"
