"""Black-box behavior tests for iteration 143 (ships as commit-sequence **factory
iter 150**): the HOTFIX that makes the post-release fresh-clone gate green again.

``tests/test_iter99_behavior.py::test_b08_determinism_via_cli`` byte-compares two
CLI runs. Until this iteration both runs were driven over the IN-REPO fixture
``examples/fixture_workspace``, which carries no ``.git`` of its own, so every
git-family collector resolved UPWARD and reported the enclosing product repo.
Two suites running concurrently dirtied that shared tree between the two compared
runs, a ``working_tree`` row appeared in one stdout and not the other, and the
byte-comparison failed for a reason that has nothing to do with the product's
determinism. The fix roots the compared runs at a copy of the fixture under
pytest's ``tmp_path`` while keeping both byte-identical assertions exactly as
strong as they were (ROADMAP #175).

ISOLATION CONTRACT (honored): every assertion here is written strictly against
this iteration's spec ("Expected Behaviors" in ``pm.md``), the repo's own
``tests/`` tree, and the product's OBSERVABLE output obtained by RUNNING it via
``proactive_loop.cli.main(argv)``. **No file under ``src/`` was read, no
engineer/reviewer/fix note was consulted, and no ``git diff`` was inspected.**
The four collector classes in Behavior 5 are named BY THE SPEC and driven as
public API; the kinds they emit are DERIVED at runtime from repos this module
builds, never transcribed from source. Fully offline: no network, no API keys.
Every git repo built here lives entirely under ``tmp_path`` and no test writes
anything inside the product repo.
"""

from __future__ import annotations

import ast
import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from proactive_loop.cli import main
from proactive_loop.collectors import (
    GitActivityCollector,
    GitStashCollector,
    GitStateCollector,
    WorkingTreeCollector,
)

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "examples" / "fixture_workspace"
TESTS_DIR = REPO / "tests"
TARGET_MODULE = TESTS_DIR / "test_iter99_behavior.py"
TARGET_FUNC = "test_b08_determinism_via_cli"

_EMPTY_MARKER = "(no signals collected)"
_FIXTURE_PATH_FRAGMENT = "examples/fixture_workspace"
_RUNNER_NAMES = frozenset({"_run", "main", "_cli", "_invoke"})
_COPY_IGNORE = shutil.ignore_patterns(".git", "__pycache__", "*.pyc")

# The four collectors the spec names as the git family. Kept as a tuple so every
# Behavior-5 assertion iterates the same list.
_GIT_COLLECTORS = (
    GitActivityCollector,
    GitStateCollector,
    GitStashCollector,
    WorkingTreeCollector,
)

# The 5 files the spec names as the fixture's tracked content (Behavior 3).
_SPEC_FIXTURE_FILES = (
    "README.md",
    "notes/journal.md",
    "projects/ai-experiments/agent.py",
    "projects/ai-experiments/eval_harness.py",
    "projects/api-gateway/server.py",
)

# Any of these applied inside the target function would normalize a compared
# string and silently weaken the byte-identical assertions (Behavior 2).
_NORMALIZERS = frozenset(
    {
        "loads",
        "sorted",
        "strip",
        "rstrip",
        "lstrip",
        "split",
        "splitlines",
        "lower",
        "upper",
        "replace",
        "casefold",
        "dumps",
    }
)


# ---------------------------------------------------------------------------
# Black-box helpers (public CLI / public collector API / this repo's tests dir).
# ---------------------------------------------------------------------------
def _git_available() -> bool:
    try:
        subprocess.run(["git", "--version"], check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError):  # pragma: no cover - env dependent
        return False
    return True


_GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "T",
    "GIT_AUTHOR_EMAIL": "t@t.com",
    "GIT_COMMITTER_NAME": "T",
    "GIT_COMMITTER_EMAIL": "t@t.com",
}


def _run(argv: list[str]) -> tuple[int, str, str]:
    """Drive main(argv) IN-PROCESS; return (exit_code, stdout, stderr).

    WHY in-process instead of a subprocess: this is the exact path the target
    test drives, and it is the path whose git isolation is at stake -- the
    process cwd stays at the repo root here, so a collector that inherited the
    process cwd rather than the workspace argument would still leak. A
    subprocess measurement (fresh cwd) cannot observe that failure mode.
    """
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rv = main(argv)
            code = rv if isinstance(rv, int) else 0
        except SystemExit as exc:  # pragma: no cover - argparse usage errors
            code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
    return code, out.getvalue(), err.getvalue()


def _summary_human(workspace: Path) -> str:
    code, out, err = _run(["signals", "--workspace", str(workspace), "--summary"])
    assert code == 0, f"--summary must exit 0 over {workspace}; stderr={err!r}"
    return out


def _summary_json(workspace: Path) -> dict:
    code, out, err = _run(["signals", "--workspace", str(workspace), "--summary", "--json"])
    assert code == 0, f"--summary --json must exit 0 over {workspace}; stderr={err!r}"
    return json.loads(out)


def _shipped_copy_helper():
    """Load the copy helper the TARGET module actually uses, by file path.

    Loading via importlib (rather than ``from tests.test_iter99_behavior
    import ...``) keeps this independent of whichever sys.path pytest happens to
    prepend, and the private module name means pytest never collects the loaded
    copy a second time.
    """
    spec = importlib.util.spec_from_file_location("_iter99_under_test", TARGET_MODULE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    helper = getattr(module, "_isolated_fixture_copy", None)
    assert helper is not None, (
        "test_iter99_behavior.py must expose the tmp_path copy helper "
        "_isolated_fixture_copy that its compared runs are rooted at"
    )
    return helper


def _relative_files(root: Path) -> set[str]:
    return {
        str(p.relative_to(root))
        for p in root.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
    }


def _func_node(module_path: Path, func_name: str) -> ast.FunctionDef:
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            return node
    raise AssertionError(f"{module_path.name} no longer defines {func_name}()")


def _called_names(node: ast.AST) -> list[str]:
    names: list[str] = []
    for call in ast.walk(node):
        if not isinstance(call, ast.Call):
            continue
        if isinstance(call.func, ast.Name):
            names.append(call.func.id)
        elif isinstance(call.func, ast.Attribute):
            names.append(call.func.attr)
    return names


def _runner_calls(node: ast.AST, name: str) -> list[ast.Call]:
    return [
        c
        for c in ast.walk(node)
        if isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id == name
    ]


def _argv_tokens(call: ast.Call) -> list[str]:
    """String literals reachable from a call's arguments (the argv list)."""
    tokens: list[str] = []
    for arg in list(call.args) + [kw.value for kw in call.keywords]:
        for n in ast.walk(arg):
            if isinstance(n, ast.Constant) and isinstance(n.value, str):
                tokens.append(n.value)
    return tokens


def _references_in_repo_fixture(call: ast.Call) -> bool:
    for arg in list(call.args) + [kw.value for kw in call.keywords]:
        for n in ast.walk(arg):
            if isinstance(n, ast.Name) and "FIXTURE" in n.id.upper():
                return True
            if isinstance(n, ast.Constant) and isinstance(n.value, str):
                if _FIXTURE_PATH_FRAGMENT in n.value:
                    return True
    return False


def _bare_name_eq_pairs(fn: ast.AST) -> list[tuple[str, str]]:
    """(left, right) for every `assert <name> == <name>` in *fn*."""
    pairs: list[tuple[str, str]] = []
    for stmt in ast.walk(fn):
        if not isinstance(stmt, ast.Assert):
            continue
        for cmp_ in ast.walk(stmt.test):
            if not (isinstance(cmp_, ast.Compare) and len(cmp_.ops) == 1):
                continue
            if not isinstance(cmp_.ops[0], ast.Eq):
                continue
            left, right = cmp_.left, cmp_.comparators[0]
            if isinstance(left, ast.Name) and isinstance(right, ast.Name):
                pairs.append((left.id, right.id))
    return pairs


def _census_unsafe_compared_runs(tree: ast.AST) -> list[str]:
    """Behavior 7's class census over one parsed module.

    A member is a test function that BOTH (a) makes two or more calls to a
    CLI-runner name whose arguments reference the in-repo fixture, AND (b)
    asserts equality between two bare names -- i.e. byte-compares two runs over
    a tree the rest of the machine can mutate underneath it.
    """
    hits: list[str] = []
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef) or not fn.name.startswith("test"):
            continue
        fixture_runner_calls = [
            c
            for c in ast.walk(fn)
            if isinstance(c, ast.Call)
            and isinstance(c.func, ast.Name)
            and c.func.id in _RUNNER_NAMES
            and _references_in_repo_fixture(c)
        ]
        if len(fixture_runner_calls) >= 2 and _bare_name_eq_pairs(fn):
            hits.append(fn.name)
    return hits


def _init_git_repo(path: Path) -> None:
    subprocess.run(
        ["git", "init", "-b", "main", str(path)], check=True, capture_output=True, env=_GIT_ENV
    )


def _copy_fixture_into(dest: Path) -> Path:
    shutil.copytree(FIXTURE, dest, ignore=_COPY_IGNORE)
    return dest


# ===========================================================================
# Behavior 1 -- Isolation: the compared runs are rooted under tmp_path, and the
# function body references neither the in-repo FIXTURE constant nor any string
# containing 'examples/fixture_workspace'.
# ===========================================================================
def test_b01_target_function_does_not_reference_the_in_repo_fixture():
    node = _func_node(TARGET_MODULE, TARGET_FUNC)
    names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
    assert "FIXTURE" not in names, (
        f"{TARGET_FUNC} still references the in-repo FIXTURE constant; its "
        "compared runs must be rooted under tmp_path"
    )
    literals = [
        n.value
        for n in ast.walk(node)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    ]
    offenders = [s for s in literals if _FIXTURE_PATH_FRAGMENT in s]
    assert not offenders, f"{TARGET_FUNC} hardcodes the in-repo fixture path: {offenders}"


def test_b01_target_function_roots_its_workspace_under_tmp_path():
    node = _func_node(TARGET_MODULE, TARGET_FUNC)
    assert any(a.arg == "tmp_path" for a in node.args.args), (
        f"{TARGET_FUNC} must take pytest's tmp_path fixture; got "
        f"{[a.arg for a in node.args.args]}"
    )
    # Every --workspace value handed to a runner call must be a name bound in
    # the function, not a module-level constant reaching outside tmp_path.
    for call in _runner_calls(node, "_run"):
        tokens = _argv_tokens(call)
        assert "--workspace" in tokens, f"runner call without --workspace: {tokens}"


# ===========================================================================
# Behavior 2 -- Assertion strength preserved: still exactly four CLI runs (two
# human --summary, two --summary --json) and still two raw `==` comparisons
# between un-normalized stdout strings.
# ===========================================================================
def test_b02_exactly_four_cli_runs_two_human_two_json():
    node = _func_node(TARGET_MODULE, TARGET_FUNC)
    calls = _runner_calls(node, "_run")
    assert len(calls) == 4, f"{TARGET_FUNC} must make exactly 4 CLI runs; found {len(calls)}"
    human = [c for c in calls if "--summary" in _argv_tokens(c) and "--json" not in _argv_tokens(c)]
    js = [c for c in calls if "--summary" in _argv_tokens(c) and "--json" in _argv_tokens(c)]
    assert len(human) == 2, f"expected 2 human --summary runs; found {len(human)}"
    assert len(js) == 2, f"expected 2 --summary --json runs; found {len(js)}"


def test_b02_two_raw_equality_assertions_between_run_outputs():
    node = _func_node(TARGET_MODULE, TARGET_FUNC)
    # Names bound by unpacking a _run(...) result -- the only legitimate
    # operands of the two byte-identical comparisons.
    bound: set[str] = set()
    for assign in ast.walk(node):
        if not isinstance(assign, ast.Assign) or not isinstance(assign.value, ast.Call):
            continue
        func = assign.value.func
        if not (isinstance(func, ast.Name) and func.id == "_run"):
            continue
        for target in assign.targets:
            for n in ast.walk(target):
                if isinstance(n, ast.Name):
                    bound.add(n.id)
    pairs = _bare_name_eq_pairs(node)
    assert len(pairs) == 2, (
        f"{TARGET_FUNC} must keep exactly two bare-name == comparisons (human "
        f"pair and json pair); found {pairs}"
    )
    for left, right in pairs:
        assert left in bound and right in bound, (
            f"both operands of `{left} == {right}` must be raw _run stdout "
            f"names; bound-from-_run names are {sorted(bound)}"
        )
        assert left != right, "comparing a name to itself would be vacuous"
    assert len({frozenset(p) for p in pairs}) == 2, f"the two comparisons must differ; got {pairs}"


def test_b02_no_normalization_of_the_compared_strings():
    node = _func_node(TARGET_MODULE, TARGET_FUNC)
    used = set(_called_names(node))
    leaked = sorted(used & _NORMALIZERS)
    assert not leaked, (
        f"{TARGET_FUNC} must compare RAW stdout; found normalizing call(s) {leaked}"
    )


# ===========================================================================
# Behavior 3 -- Faithful copy: every tracked fixture file is present at the same
# relative path with byte-identical content, and the copy carries no .git.
# ===========================================================================
def test_b03_copy_is_byte_identical_and_has_no_git_dir(tmp_path):
    copy = _shipped_copy_helper()(tmp_path / "fixture_copy")
    copy = Path(copy)
    assert copy.is_dir(), f"the helper must return an existing directory; got {copy!r}"
    assert copy.resolve().is_relative_to(tmp_path.resolve()), (
        f"the copy must live under tmp_path; got {copy}"
    )
    assert _relative_files(copy) == _relative_files(FIXTURE), (
        "the copy must hold exactly the fixture's files; "
        f"missing={_relative_files(FIXTURE) - _relative_files(copy)} "
        f"extra={_relative_files(copy) - _relative_files(FIXTURE)}"
    )
    for rel in _SPEC_FIXTURE_FILES:
        src, dst = FIXTURE / rel, copy / rel
        assert dst.is_file(), f"{rel} missing from the copied workspace"
        assert dst.read_bytes() == src.read_bytes(), f"{rel} was not copied byte-identically"
    assert not (copy / ".git").exists(), "the copied workspace must carry no .git entry"
    assert not any(p.name == ".git" for p in copy.rglob("*")), (
        "no .git entry may appear anywhere inside the copied workspace"
    )


# ===========================================================================
# Behavior 4 -- Not vacuous: the isolated copy still produces signals, so the
# byte-comparison is not two identical empty slates. The total is DERIVED.
# ===========================================================================
def test_b04_isolated_copy_still_produces_signals(tmp_path):
    copy = Path(_shipped_copy_helper()(tmp_path / "fixture_copy"))
    human = _summary_human(copy)
    assert human != _EMPTY_MARKER + "\n", (
        "the isolated copy must still surface signals or the determinism "
        f"comparison is vacuous; got {human!r}"
    )
    assert _EMPTY_MARKER not in human, f"empty-slate marker leaked into the table: {human!r}"
    doc = _summary_json(copy)
    assert doc["total"] >= 1, f"expected at least one signal over the copy; got {doc}"
    assert doc["summary"], f"summary rollup must be non-empty; got {doc}"
    # Cross-check, never hardcode: the rollup must account for the total.
    assert doc["total"] == sum(doc["summary"].values()), (
        f"total must equal the sum of the per-kind counts; got {doc}"
    )


# ===========================================================================
# Behavior 5 -- Git-isolated: the four git collectors are EMPTY over the copy,
# and no kind they emit appears in the copy's --summary --json rollup.
# ===========================================================================
def test_b05_four_git_collectors_return_empty_over_the_copy(tmp_path):
    copy = Path(_shipped_copy_helper()(tmp_path / "fixture_copy"))
    for cls in _GIT_COLLECTORS:
        signals = cls().collect(copy)
        assert signals == [], (
            f"{cls.__name__} must see no git state over an isolated copy; got "
            f"{[(s.kind, s.summary) for s in signals]}"
        )


@pytest.mark.skipif(not _git_available(), reason="git is not available on this system")
def test_b05_no_git_derived_kind_reaches_the_copy_summary(tmp_path):
    # DERIVE the git family's kinds from repos built here, so the assertion
    # cannot silently pass against a stale hardcoded kind list. One repo with a
    # commit (git_commit) plus one untracked file (working_tree).
    donor_repo = tmp_path / "donor_repo"
    donor_repo.mkdir()
    _init_git_repo(donor_repo)
    donor_ws = _copy_fixture_into(donor_repo / "ws")
    subprocess.run(
        ["git", "-C", str(donor_repo), "add", "-A"], check=True, capture_output=True, env=_GIT_ENV
    )
    subprocess.run(
        ["git", "-C", str(donor_repo), "commit", "-m", "seed"],
        check=True,
        capture_output=True,
        env=_GIT_ENV,
    )
    (donor_repo / "untracked.txt").write_text("dirty\n", encoding="utf-8")
    git_kinds = {s.kind for cls in _GIT_COLLECTORS for s in cls().collect(donor_ws)}
    assert len(git_kinds) >= 2, (
        "fail closed: the donor repo must exercise at least two git kinds or "
        f"this absence check proves nothing; got {sorted(git_kinds)}"
    )

    copy = Path(_shipped_copy_helper()(tmp_path / "fixture_copy"))
    doc = _summary_json(copy)
    leaked = sorted(git_kinds & set(doc["summary"]))
    assert not leaked, (
        f"git-derived kind(s) {leaked} reached the isolated copy's summary "
        f"{doc['summary']} -- repo state is still leaking into the comparison"
    )


# ===========================================================================
# Behavior 6 -- The mechanism, proven two-sided and entirely under tmp_path: a
# fixture copy inside a git repo picks up git kinds AND its two --summary runs
# DIFFER when the repo is dirtied between them; the same copy outside any repo
# is byte-identical under the same mutation.
# ===========================================================================
@pytest.mark.skipif(not _git_available(), reason="git is not available on this system")
def test_b06_inside_a_tmp_git_repo_the_two_runs_diverge(tmp_path):
    repo = tmp_path / "enclosing_repo"
    repo.mkdir()
    assert repo.resolve().is_relative_to(tmp_path.resolve()), "git work must stay under tmp_path"
    _init_git_repo(repo)
    ws = _copy_fixture_into(repo / "ws")

    git_kinds = {s.kind for cls in _GIT_COLLECTORS for s in cls().collect(ws)}
    assert git_kinds, (
        "a fixture copy inside a git repo must surface at least one git-family "
        "kind, else this arm of the mechanism proof is inert"
    )
    before = _summary_human(ws)
    assert any(f"{kind}  " in before for kind in git_kinds), (
        f"expected a git kind row from {sorted(git_kinds)} in {before!r}"
    )

    # Dirty the enclosing repo OUTSIDE the workspace -- exactly what a sibling
    # test process does to the product repo while the compared runs execute.
    (repo / "elsewhere.txt").write_text("new untracked file\n", encoding="utf-8")
    after = _summary_human(ws)
    assert before != after, (
        "the leak is unproven: dirtying the enclosing repo outside the "
        f"workspace left the summary unchanged ({before!r})"
    )


def test_b06_outside_any_repo_the_two_runs_stay_byte_identical(tmp_path):
    plain = tmp_path / "plain_parent"
    plain.mkdir()
    ws = _copy_fixture_into(plain / "ws")
    before = _summary_human(ws)
    (plain / "elsewhere.txt").write_text("new untracked file\n", encoding="utf-8")
    after = _summary_human(ws)
    assert before == after, (
        "outside any git repo the same mutation must not move a single byte; "
        f"before={before!r} after={after!r}"
    )
    assert before != _EMPTY_MARKER + "\n", "fail closed: this arm must not compare empty slates"


# ===========================================================================
# Behavior 7 -- Class guard: the census of "two compared CLI runs over the
# in-repo fixture" is now EMPTY across tests/, and the detector is two-sided.
# ===========================================================================
def test_b07_census_of_compared_in_repo_runs_is_empty():
    hits = []
    for path in sorted(TESTS_DIR.glob("test_*.py")):
        for name in _census_unsafe_compared_runs(ast.parse(path.read_text(encoding="utf-8"))):
            hits.append(f"{path.name}::{name}")
    assert hits == [], (
        "these test functions byte-compare two CLI runs over the in-repo "
        f"fixture and can flake when any process dirties the repo: {hits}"
    )


def test_b07_census_detector_is_two_sided():
    bad = (
        "FIXTURE = 'x'\n"
        "def test_planted_bad_shape():\n"
        "    a = _run(['signals', '--workspace', str(FIXTURE), '--summary'])\n"
        "    b = _run(['signals', '--workspace', str(FIXTURE), '--summary'])\n"
        "    assert a == b\n"
    )
    good = (
        "def test_planted_good_shape(tmp_path):\n"
        "    ws = str(_isolated_fixture_copy(tmp_path / 'c'))\n"
        "    a = _run(['signals', '--workspace', ws, '--summary'])\n"
        "    b = _run(['signals', '--workspace', ws, '--summary'])\n"
        "    assert a == b\n"
    )
    assert _census_unsafe_compared_runs(ast.parse(bad)) == ["test_planted_bad_shape"], (
        "the census must FIRE on a planted module carrying the pre-fix shape, "
        "or its zero over tests/ is a fail-open zero"
    )
    assert _census_unsafe_compared_runs(ast.parse(good)) == [], (
        "the census must stay silent on a tmp_path-rooted comparison"
    )


# ===========================================================================
# Behavior 8 (partial, static half) -- the hotfix must not have disturbed
# iteration 142's fan-out pins, which the operator ruled NOT the cause.
# ===========================================================================
def test_b08_iter142_fanout_pins_are_still_present():
    pinned = TESTS_DIR / "test_iter142_behavior.py"
    assert pinned.is_file(), "iteration 142's fan-out guard module must still exist"
    text = pinned.read_text(encoding="utf-8")
    assert "-n" in text and "2" in text, "the -n 2 fan-out pins must remain in place"
    assert any(
        isinstance(n, ast.FunctionDef) and n.name.startswith("test")
        for n in ast.walk(ast.parse(text))
    ), "iteration 142's guard module must still define tests"
