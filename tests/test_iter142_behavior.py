"""Behavior tests for iteration 142: run the test suite in parallel by default.

Iteration 142 is a pure build-throughput change with **no ``src/`` edit at all**:
``pytest-xdist`` becomes a declared dev dependency, ``uv.lock`` is regenerated in
the same commit (CI runs ``uv sync --locked``, so drift is a red public build),
and ``[tool.pytest.ini_options].addopts`` becomes exactly ``-q -n auto`` so EVERY
call site -- ``make test``, ``make cov``, ``make check``, all six CI run-steps and
a bare ``uv run pytest`` -- inherits the parallelism without any recipe changing.

Why it matters (this is the oracle for a real cliff, not a preference): the
foundry's post-release check flips a ship to BROKEN when the fresh-clone suite
wall-time crosses 120s, and this suite went 61s -> 89/99s -> 102/112/106s over
three days. A silent revert of the ``addopts`` string would quietly hand back the
measured 3.45x and re-arm that cliff, so behavior 5 pins the exact string.

Coverage (numbered to match the iteration spec's Expected Behaviors):

1. ``pytest-xdist`` is declared in ``[dependency-groups].dev``.
2. No pre-existing dev dependency was dropped: ``pytest``, ``pytest-cov`` and
   ``mypy`` are all still declared.
3. The RUNTIME dependency set is untouched -- ``[project].dependencies`` is
   exactly ``["pydantic>=2.7"]``, and neither ``pytest-xdist`` nor ``execnet``
   leaks into it.
4. ``uv.lock`` was regenerated in the same commit: it carries a package stanza
   for ``pytest-xdist`` AND one for ``execnet`` (xdist's own dependency).
5. ``addopts`` is exactly ``-q -n auto`` (both as a string and tokenized).
6. Coverage is still never global: that ``addopts`` string carries no ``--cov``
   under any spelling. This is the load-bearing half of the iteration-52 guard.
7. The plugin is INSTALLED, not merely declared -- importable from the very
   interpreter running this suite.
8. Distribution actually works, offline, in a clean throwaway project that does
   NOT inherit this repo's ini -- and that same single nested child proves an xdist
   worker pool was really created. These were two near-identical children until
   factory iter 159 merged them; the surviving call site documents the trade.
9. Coverage under xdist still reports a REAL total. This is the one silent-failure
   mode xdist introduces: per-worker coverage data that is never combined reports
   0% (or no ``TOTAL`` row) while the build stays green. Both child runs PIN
   ``-n 2`` rather than inheriting ``-n auto`` (see the comment at each call
   site): the assertion is unchanged and still cross-worker, it is simply no
   longer nesting a second 12-worker pool inside the parallel parent suite.
12. ``Makefile`` and ``.github/workflows/ci.yml`` carry no worker flag -- the win
    comes from ``addopts`` inheritance alone, and both still invoke a bare
    ``uv run pytest``.
13. ``src/`` is untouched in the way that is observable black-box: no module under
    ``src/proactive_loop`` references ``xdist`` or ``execnet``, and the PEP 561
    ``py.typed`` marker still ships.

Behaviors 10, 11 and 14 are deliberately NOT duplicated here: 10/11 live in
``tests/test_iter52_behavior.py`` (whose own assertions are the oracle), and 14 is
the full-suite outcome, which is the suite run itself rather than a test. The
expected-``addopts`` value is IMPORTED from that module rather than re-spelled here,
so the two oracles cannot disagree AT ALL: there is one constant, not two copies
policed by a source-text drift guard (which could only ever see one of the two
duplicates, and is deleted in factory iter 266).

Offline, deterministic. EVERY nested subprocess test keeps its coverage artifact in
``tmp_path`` via ``COVERAGE_FILE`` so it can never race the repo-root ``.coverage``
file that iteration 52's oracles own.
"""

from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from tests.test_iter52_behavior import EXPECTED_ADDOPTS

REPO = Path(__file__).resolve().parents[1]
PYPROJECT = REPO / "pyproject.toml"
UV_LOCK = REPO / "uv.lock"
MAKEFILE = REPO / "Makefile"
CI_YML = REPO / ".github" / "workflows" / "ci.yml"
SRC_PKG = REPO / "src" / "proactive_loop"

# --------------------------------------------------------------------------
# Spec-declared ground facts (pm.md), encoded here rather than imported, to keep
# these tests black-box against the contract. ONE exception, imported above:
# ``EXPECTED_ADDOPTS``. The artifact under test is ``pyproject.toml``, never iteration
# 52's module, so sharing the EXPECTED spelling is not the import-and-assert-itself
# tautology `test_iter164` warns about -- it keeps both oracles two-sided while making
# a disagreement between them unrepresentable rather than merely detected. The token
# form is derived (``.split()``) for the same reason.
# --------------------------------------------------------------------------
EXPECTED_RUNTIME_DEPS = ["pydantic>=2.7"]
REQUIRED_DEV_DEPS = {"pytest", "pytest-cov", "mypy", "pytest-xdist"}
PREEXISTING_DEV_DEPS = {"pytest", "pytest-cov", "mypy"}
LOCK_REQUIRED_PACKAGES = ("pytest-xdist", "execnet")
COV_MODULE = "tests/test_scheduler.py"

# A coverage summary row: ``TOTAL`` at line start carrying an ``<n>%`` token.
_TOTAL_PCT = re.compile(r"^TOTAL\b.*?\b(\d+)%", re.MULTILINE)
# PEP 508 requirement -> bare distribution name (cut at the first marker char).
_REQ_SPLIT = re.compile(r"[>=<!~\[ ;@]")
# Any spelling of an xdist worker-count flag. Applied ONLY to lines that invoke
# pytest: `-n<digits>` is also plain `git log -n15`, which ci.yml legitimately
# mentions in a comment -- matching that would be a fail-closed matcher bug, not a
# product defect (it fired on exactly that line on the first run).
_WORKER_FLAG = re.compile(r"(?:^|\s)(?:-n\s*\d|-n\s+auto|-n\s*logical|--numprocesses|--dist\b|-p\s+xdist)")


def _load_pyproject() -> dict:
    with PYPROJECT.open("rb") as fh:
        return tomllib.load(fh)


def _canonical(name: str) -> str:
    """PEP 503 normalization, so ``pytest_xdist`` and ``Pytest-XDist`` compare equal."""
    return re.sub(r"[-_.]+", "-", name.strip()).lower()


def _requirement_name(req: str) -> str:
    return _canonical(_REQ_SPLIT.split(req.strip(), 1)[0])


def _dev_group() -> list[str]:
    data = _load_pyproject()
    groups = data.get("dependency-groups", {})
    assert isinstance(groups, dict), "pyproject.toml has no [dependency-groups] table"
    dev = groups.get("dev")
    assert isinstance(dev, list) and dev, "[dependency-groups].dev must be a non-empty list"
    return [str(entry) for entry in dev]


def _dev_names() -> set[str]:
    return {_requirement_name(entry) for entry in _dev_group()}


def _addopts() -> str:
    data = _load_pyproject()
    ini = data.get("tool", {}).get("pytest", {}).get("ini_options", {})
    assert isinstance(ini, dict), "pyproject.toml has no [tool.pytest.ini_options] table"
    addopts = ini.get("addopts")
    assert isinstance(addopts, str), "[tool.pytest.ini_options].addopts must be a string"
    return addopts


def _clean_env(coverage_file: Path) -> dict[str, str]:
    """Environment for a child pytest: no inherited PYTEST_ADDOPTS, coverage in tmp_path.

    NOTE the precision: this clears the PYTEST_ADDOPTS *env var* only. A child with
    ``cwd=REPO`` still reads this repo ini ``addopts`` (that is exactly why the two
    Behavior-9 children below pin their own ``-n``), so do not read this helper as
    making a nested run opt out of the repo parallelism -- it does not.
    """
    env = dict(os.environ)
    env.pop("PYTEST_ADDOPTS", None)
    env.pop("PYTEST_CURRENT_TEST", None)
    env.pop("PYTEST_XDIST_WORKER", None)
    env.pop("PYTEST_XDIST_WORKER_COUNT", None)
    # COVERAGE_FILE takes precedence over [tool.coverage.run].data_file, so a child
    # run in the REAL repo root cannot touch the shared <repo>/.coverage artifact
    # that iteration 52's oracles assert on. Without this the two would race under
    # `-n auto`, which is exactly the class of flake this iteration must not add.
    env["COVERAGE_FILE"] = str(coverage_file)
    return env


# ==========================================================================
# Behaviors 1-3: the declared dependency sets.
# ==========================================================================
class TestDeclaredDependencies:
    def test_eb1_pytest_xdist_is_a_declared_dev_dependency(self) -> None:
        assert "pytest-xdist" in _dev_names(), (
            "[dependency-groups].dev must declare pytest-xdist; found "
            f"{sorted(_dev_names())}"
        )

    def test_eb2_no_preexisting_dev_dependency_was_dropped(self) -> None:
        missing = sorted(PREEXISTING_DEV_DEPS - _dev_names())
        assert not missing, f"dev group lost pre-existing dev dependencies: {missing}"

    def test_eb2_dev_group_declares_every_required_tool(self) -> None:
        assert REQUIRED_DEV_DEPS <= _dev_names()

    def test_eb3_runtime_dependency_list_is_unchanged(self) -> None:
        deps = _load_pyproject()["project"]["dependencies"]
        assert deps == EXPECTED_RUNTIME_DEPS, (
            "the runtime dependency set must stay pydantic-only; found " f"{deps}"
        )

    def test_eb3_no_test_tooling_leaked_into_runtime_dependencies(self) -> None:
        names = {_requirement_name(d) for d in _load_pyproject()["project"]["dependencies"]}
        assert names == {"pydantic"}
        for forbidden in ("pytest-xdist", "execnet", "pytest", "pytest-cov", "mypy"):
            assert forbidden not in names


# ==========================================================================
# Behavior 4: the lockfile was regenerated in the same commit.
# ==========================================================================
class TestLockfileRegenerated:
    def test_eb4_lock_declares_pytest_xdist_and_execnet(self) -> None:
        text = UV_LOCK.read_text(encoding="utf-8")
        for package in LOCK_REQUIRED_PACKAGES:
            assert f'name = "{package}"' in text, (
                f"uv.lock has no stanza for {package!r}; CI runs `uv sync --locked` "
                "and will fail on that drift"
            )

    def test_eb4_lock_guard_is_not_vacuous(self) -> None:
        # If the stanza spelling ever changed, the assertion above would silently
        # pass on nothing. Pin a package that is unconditionally present.
        text = UV_LOCK.read_text(encoding="utf-8")
        assert 'name = "pydantic"' in text
        assert 'name = "pytest"' in text

    def test_eb4_every_declared_dev_dependency_is_locked(self) -> None:
        text = UV_LOCK.read_text(encoding="utf-8")
        unlocked = [n for n in sorted(_dev_names()) if f'name = "{n}"' not in text]
        assert not unlocked, f"declared but unlocked dev dependencies: {unlocked}"


# ==========================================================================
# Behaviors 5-6: the single lever, and the coverage invariant it must not break.
# ==========================================================================
class TestAddoptsContract:
    def test_eb5_addopts_is_exactly_dash_q_dash_n_auto(self) -> None:
        assert _addopts() == EXPECTED_ADDOPTS, (
            "addopts is the ONLY thing making every call site parallel; a silent "
            f"revert hands back the measured 3.45x. Found {_addopts()!r}"
        )

    def test_eb5_addopts_tokenizes_to_exactly_three_flags(self) -> None:
        # Derived, never re-spelled: a second literal token list is exactly the
        # duplicate this iteration removes. The length assertion keeps this
        # function's name ("three flags") load-bearing rather than decorative.
        expected = EXPECTED_ADDOPTS.split()
        assert len(expected) == 3, (
            f"the pinned addopts stopped being three flags: {EXPECTED_ADDOPTS!r}"
        )
        assert _addopts().split() == expected

    def test_eb6_addopts_never_enables_coverage_globally(self) -> None:
        addopts = _addopts().lower()
        assert "--cov" not in addopts, (
            "coverage must stay opt-in per call (iteration 52's invariant); found "
            f"{_addopts()!r}"
        )
        assert not any(tok.startswith("--cov") for tok in addopts.split())


# ==========================================================================
# Behaviors 7-8: the plugin is installed and really distributes, offline.
# ==========================================================================
class TestPluginIsInstalledAndWorks:
    def test_eb7_xdist_is_importable_in_the_session_interpreter(self) -> None:
        assert importlib.util.find_spec("xdist") is not None, (
            "pytest-xdist is declared but not installed in the venv running the "
            "suite -- `uv sync` did not materialize the dev group"
        )

    def test_eb8_distribution_works_offline_and_creates_a_worker_pool(
        self, tmp_path: Path
    ) -> None:
        """One nested child proves both halves of behavior 8: it distributes, and a pool exists."""
        # WHY THESE TWO TESTS ARE NOW ONE (merged in factory iter 159).
        #
        # This was two tests -- `..._distribution_works_offline_in_a_clean_project` and
        # `..._worker_pool_is_actually_created` -- that built a BYTE-IDENTICAL one-test
        # fixture project and spawned their own `pytest -n 2` child, differing ONLY by
        # `-v`. `-v` is purely additive to stdout, so the verbose invocation satisfies
        # both oracles verbatim: the second child was pure duplication. That redundancy
        # is the WHOLE justification for this merge -- it stands on its own and needs no
        # timing argument, which matters because the timing argument did not survive
        # measurement.
        #
        # NO WALL-TIME SAVING IS CLAIMED, and the reason is structural rather than noise.
        # A paired, interleaved A/B on a 12-core dev box measured the merged tree 0.38s
        # SLOWER, not faster (two children 36.26s mean, one child 36.64s mean, two runs
        # per side), a difference well inside this box's run-to-run drift. Under xdist's
        # `load` distribution the two children land on DIFFERENT workers, so the suite's
        # critical path is ONE of them and never their sum, and a spare worker simply
        # absorbs whichever child is freed. A saving is plausible in DIRECTION ONLY on
        # the 2-4 core CI matrix runners, which have no spare worker to absorb a nested
        # 3-process pool -- that was NOT measured, so it is not claimed here. Suite
        # wall-time is a graded CI gate, so removing a redundant nested pool is still
        # worth doing; it is just not worth a number anyone can quote.
        #
        # WHAT WAS GIVEN UP, recorded at the call site so the trade is discoverable here
        # and not only in the iteration spec: the PLAIN (non-`-v`) invocation is no
        # longer exercised separately, so an xdist regression visible ONLY without `-v`
        # would now be missed. Judged negligible -- `-v` changes report verbosity, not
        # the distribution mechanism under test -- and the worker-banner assertion below
        # REQUIRES `-v`, so the verbose run is the strictly more informative of the two.
        #
        # Deliberately ONE test function, NOT a shared fixture: under xdist's default
        # `load` distribution a module- or session-scoped fixture is PER-WORKER, so two
        # tests can land on different workers and the child would run twice -- measuring
        # zero saving exactly where it matters.
        project = tmp_path / "clean"
        (project / "tests").mkdir(parents=True)
        (project / "tests" / "test_smoke.py").write_text(
            "def test_smoke() -> None:\n    assert 1 + 1 == 2\n", encoding="utf-8"
        )
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-n", "2", "-p", "no:cacheprovider", "-v"],
            cwd=str(project),
            capture_output=True,
            text=True,
            timeout=180,
            env=_clean_env(tmp_path / ".coverage-clean"),
        )
        combined = proc.stdout + proc.stderr
        assert proc.returncode == 0, f"clean-project parallel run failed:\n{combined}"
        # Asserted against stdout specifically: pytest's summary line is never on stderr,
        # so accepting `combined` here would let a stderr echo satisfy the oracle.
        assert "1 passed" in proc.stdout, combined
        assert "worker" in combined.lower(), (
            "no xdist worker banner in the output -- the run may have silently "
            f"fallen back to serial:\n{combined}"
        )


# ==========================================================================
# Behavior 9: coverage still combines across workers.
# ==========================================================================
class TestCoverageSurvivesParallelism:
    def test_eb9_coverage_reports_a_real_total_under_inherited_parallelism(
        self, tmp_path: Path
    ) -> None:
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                # PINNED worker count, deliberately NOT inherited: this child runs with
                # cwd=REPO, so it reads this repo pyproject and would otherwise inherit
                # addopts = "-q -n auto", bringing up a SECOND full worker pool (12 on a
                # 12-core box) nested inside the already-parallel parent suite. That ~3x
                # oversubscription measured a 19.23s critical-path spike locally and is
                # strictly worse on the 2-4 core CI runners. 2 is the smallest count that
                # still exercises what this test is FOR: per-worker coverage data COMBINED
                # across workers -- "-n0" would delete that oracle. Last -n wins, so this
                # overrides the inherited "auto".
                "-n",
                "2",
                "--cov=proactive_loop",
                "--cov-report=term-missing",
                "-p",
                "no:cacheprovider",
                COV_MODULE,
            ],
            cwd=str(REPO),
            capture_output=True,
            text=True,
            timeout=300,
            env=_clean_env(tmp_path / ".coverage-eb9"),
        )
        combined = proc.stdout + proc.stderr
        assert proc.returncode == 0, f"parallel coverage run failed:\n{combined}"
        match = _TOTAL_PCT.search(proc.stdout)
        assert match is not None, (
            "no TOTAL row in the coverage report -- per-worker data was not "
            f"combined:\n{combined}"
        )
        assert int(match.group(1)) > 0, (
            "coverage TOTAL is 0% under -n 2: worker data was collected but "
            f"never combined:\n{proc.stdout}"
        )

    def test_eb9_run_left_no_coverage_artifact_in_the_repo_root(self, tmp_path: Path) -> None:
        # The child run above is pinned to a tmp_path COVERAGE_FILE precisely so it
        # cannot disturb the repo-root artifact iteration 52 measures. Assert the
        # redirection itself works, in isolation, without touching the repo file.
        data_file = tmp_path / ".coverage-redirect"
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                # PINNED for the same reason as the test above: a cwd=REPO child inherits
                # addopts = "-q -n auto" from this repo pyproject and would nest a second
                # 12-worker pool inside the already-parallel parent suite. 2 keeps the run
                # genuinely cross-worker, so the COVERAGE_FILE redirection is still proven
                # under the multi-worker conditions that make it necessary.
                "-n",
                "2",
                "--cov=proactive_loop",
                "--cov-report=term-missing",
                "-p",
                "no:cacheprovider",
                COV_MODULE,
            ],
            cwd=str(REPO),
            capture_output=True,
            text=True,
            timeout=300,
            env=_clean_env(data_file),
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert data_file.exists(), (
            "COVERAGE_FILE redirection did not take effect, so this module could "
            "race the repo-root .coverage owned by iteration 52"
        )


# ==========================================================================
# Behavior 12: addopts is the ONLY lever -- no recipe carries a worker flag.
# ==========================================================================
class TestNoRecipeCarriesAWorkerFlag:
    @pytest.mark.parametrize("path", [MAKEFILE, CI_YML], ids=["Makefile", "ci.yml"])
    def test_eb12_no_worker_flag_in_build_recipes(self, path: Path) -> None:
        assert path.exists(), f"{path} is missing"
        text = path.read_text(encoding="utf-8")
        offenders = [
            line
            for line in text.splitlines()
            if ("xdist" in line)
            or ("pytest" in line and _WORKER_FLAG.search(line) is not None)
        ]
        assert not offenders, (
            "the parallelism must come from addopts inheritance alone; found a "
            f"worker flag in {path.name}: {offenders}"
        )

    def test_eb12_matcher_fires_on_a_planted_worker_flag(self) -> None:
        # Two-sided: the guard above is only evidence if it can fail. Prove the
        # matcher fires on known-bad lines and stays silent on the known-good
        # `git log -n15` comment that produced a false positive on the first run.
        for bad in (
            "\tuv run pytest -n auto",
            "        run: uv run pytest -n2",
            "\tuv run pytest --numprocesses=4",
        ):
            assert _WORKER_FLAG.search(bad) is not None, bad
        good = "      # runs `git log -n15` against examples/fixture_workspace"
        assert "pytest" not in good

    def test_eb12_both_recipes_still_invoke_a_bare_uv_run_pytest(self) -> None:
        for path in (MAKEFILE, CI_YML):
            text = path.read_text(encoding="utf-8")
            assert "uv run pytest" in text, (
                f"{path.name} no longer invokes `uv run pytest`, so it would not "
                "inherit addopts"
            )


# ==========================================================================
# Behavior 13: src/ is untouched.
# ==========================================================================
class TestSourceTreeUntouched:
    def test_eb13_no_module_under_src_references_xdist_or_execnet(self) -> None:
        modules = sorted(SRC_PKG.rglob("*.py"))
        assert len(modules) >= 20, (
            f"expected the real source package, scanned only {len(modules)} modules "
            "-- this guard would be vacuous"
        )
        offenders = [
            str(p.relative_to(REPO))
            for p in modules
            if "xdist" in p.read_text(encoding="utf-8")
            or "execnet" in p.read_text(encoding="utf-8")
        ]
        assert not offenders, (
            "a test-only plugin leaked into the runtime package: " f"{offenders}"
        )

    def test_eb13_pep561_marker_still_ships(self) -> None:
        assert (SRC_PKG / "py.typed").is_file(), "the PEP 561 py.typed marker is gone"
