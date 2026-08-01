"""Black-box behavior tests for iteration 52 --- wiring the already-declared
``pytest-cov`` dev dependency into a runnable, hygienic DX surface (ROADMAP #13).

Feature under test (``pm.md``): a ``make cov`` target + a ``[tool.coverage]``
config block in ``pyproject.toml`` + gitignore/``make clean`` hygiene for the
coverage artifacts (``.coverage`` / ``htmlcov/``). Coverage is strictly OPT-IN:
it lives only in the ``make cov`` target and MUST NOT enter pytest ``addopts``,
so a bare ``uv run pytest`` stays byte-identical (no coverage columns). This is
DX/build tooling only --- no ``src/`` runtime change, no ``SPEC.md`` contract
change, no ``__version__`` bump (stays ``0.1.1``).

ISOLATION CONTRACT (honored): these tests are written strictly against THIS
iteration's public contract --- the spec's "Expected Behaviors" (``pm.md``),
``README.md``, and the public build artifacts (``pyproject.toml``, ``Makefile``,
``.gitignore``) --- and drive ONLY documented/observable surfaces: the parsed
TOML of ``pyproject.toml``, the text of the ``Makefile``, ``git check-ignore``
and ``git status`` output, and pytest's own stdout/exit-code when RUN with and
without the coverage flags. **No file under ``src/`` was read, no
engineer/reviewer notes were read, and no ``git diff`` was consulted.** The flag
strings, config keys, and artifact names are encoded here as the spec's ground
facts (NOT imported from the implementation), so the suite encodes the contract
and would go RED on a silent drift. Every test is fully offline: zero network,
zero API keys, no live provider. Any test that creates ``.coverage`` / ``htmlcov``
DELETES them in teardown; EB8 runs the real ``clean`` recipe in an ISOLATED
temp copy so it never mutates the live working tree.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PYPROJECT = REPO / "pyproject.toml"
MAKEFILE = REPO / "Makefile"

# --------------------------------------------------------------------------
# Tester's constants --- the spec-declared ground facts (pm.md). Encoded here,
# NOT imported from src/config, to keep the tests black-box against the contract.
# --------------------------------------------------------------------------
COV_SOURCE = "proactive_loop"                     # [tool.coverage.run].source entry
COV_FLAG = "--cov=proactive_loop"                 # the package-scoping cov flag
COV_REPORT_FLAG = "--cov-report=term-missing"     # the terminal-report flag
EXPECTED_ADDOPTS = "-q"                            # addopts MUST stay exactly this
COV_MODULE = "tests/test_scheduler.py"            # the BOUNDED single-module subset
# A coverage summary row: a line beginning with TOTAL that carries a `<n>%` token.
_TOTAL_PCT = re.compile(r"^TOTAL\b.*?\b\d+%")


# --------------------------------------------------------------------------
# Toolchain availability guards (never require anything absent to be present).
# --------------------------------------------------------------------------
def _tool_available(*cmd: str) -> bool:
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=15)
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


_HAS_GIT = _tool_available("git", "--version")
_HAS_MAKE = _tool_available("make", "--version")
_needs_git = pytest.mark.skipif(not _HAS_GIT, reason="git not available")
_needs_make = pytest.mark.skipif(not _HAS_MAKE, reason="make not available")


def _load_pyproject() -> dict:
    with PYPROJECT.open("rb") as fh:
        return tomllib.load(fh)


def _run_pytest(extra_args: list[str]) -> subprocess.CompletedProcess:
    """Run pytest as a subprocess in the real repo root.

    Uses ``sys.executable -m pytest`` --- the runner-independent equivalent of
    ``uv run pytest`` (same venv interpreter that carries pytest-cov, same
    ``pyproject.toml`` config), so it exercises the exact coverage config the
    spec describes without a PATH dependency on the ``uv`` wrapper.
    """
    return subprocess.run(
        [sys.executable, "-m", "pytest", *extra_args],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        timeout=180,
    )


@pytest.fixture
def repo_coverage_cleanup():
    """Guarantee repo-root coverage artifacts are absent before AND after the test."""
    def _wipe() -> None:
        cov = REPO / ".coverage"
        if cov.exists():
            cov.unlink()
        for parallel in REPO.glob(".coverage.*"):
            parallel.unlink()
        html = REPO / "htmlcov"
        if html.is_dir():
            shutil.rmtree(html)

    _wipe()
    yield
    _wipe()


# --------------------------------------------------------------------------
# EB1 --- [tool.coverage.run] table present (source + branch)
# --------------------------------------------------------------------------
def test_eb1_coverage_run_config_present():
    data = _load_pyproject()
    run_cfg = data.get("tool", {}).get("coverage", {}).get("run")
    assert isinstance(run_cfg, dict), (
        "pyproject.toml must define a [tool.coverage.run] table; "
        f"got tool.coverage = {data.get('tool', {}).get('coverage')!r}"
    )
    assert run_cfg.get("source") == [COV_SOURCE], (
        f"[tool.coverage.run].source must be ['{COV_SOURCE}']; got {run_cfg.get('source')!r}"
    )
    assert run_cfg.get("branch") is True, (
        f"[tool.coverage.run].branch must be true; got {run_cfg.get('branch')!r}"
    )


# --------------------------------------------------------------------------
# EB2 --- [tool.coverage.report] table present (show_missing)
# --------------------------------------------------------------------------
def test_eb2_coverage_report_config_present():
    data = _load_pyproject()
    report_cfg = data.get("tool", {}).get("coverage", {}).get("report")
    assert isinstance(report_cfg, dict), (
        "pyproject.toml must define a [tool.coverage.report] table; "
        f"got {data.get('tool', {}).get('coverage', {}).get('report')!r}"
    )
    assert report_cfg.get("show_missing") is True, (
        f"[tool.coverage.report].show_missing must be true; got {report_cfg.get('show_missing')!r}"
    )


# --------------------------------------------------------------------------
# EB3 --- pytest addopts UNCHANGED (coverage never global): exactly "-q"
# --------------------------------------------------------------------------
def test_eb3_pytest_addopts_is_exactly_dash_q():
    data = _load_pyproject()
    addopts = (
        data.get("tool", {})
        .get("pytest", {})
        .get("ini_options", {})
        .get("addopts")
    )
    assert addopts == EXPECTED_ADDOPTS, (
        "addopts must stay EXACTLY '-q' (coverage is opt-in, never global); "
        f"got {addopts!r}"
    )
    # The load-bearing constraint restated as a substring guard: no --cov flag
    # may leak into addopts under any spelling.
    assert "--cov" not in (addopts or ""), (
        f"addopts must contain NO --cov flag; got {addopts!r}"
    )


# --------------------------------------------------------------------------
# EB4 --- `make cov` target exists in .PHONY and runs both cov flags
# --------------------------------------------------------------------------
def test_eb4_make_cov_target_exists_and_runs_coverage():
    text = MAKEFILE.read_text()
    lines = text.splitlines()

    # .PHONY declares `cov` as a word.
    phony_tokens: set[str] = set()
    for ln in lines:
        if ln.startswith(".PHONY:"):
            phony_tokens.update(ln.split(":", 1)[1].split())
    assert "cov" in phony_tokens, (
        f"Makefile .PHONY line must declare 'cov'; found tokens {sorted(phony_tokens)}"
    )

    # Locate the `cov:` target and gather its tab-indented recipe lines.
    recipe: list[str] = []
    in_target = False
    for ln in lines:
        if re.match(r"^cov\s*:", ln):
            in_target = True
            continue
        if in_target:
            if ln.startswith("\t"):
                recipe.append(ln.strip())
            elif ln.strip() == "":
                continue  # blank lines inside a recipe are tolerated
            else:
                break
    assert recipe, "Makefile must define a `cov:` target with a recipe"
    recipe_text = "\n".join(recipe)
    assert "pytest" in recipe_text, (
        f"`cov:` recipe must invoke pytest; got:\n{recipe_text}"
    )
    assert COV_FLAG in recipe_text, (
        f"`cov:` recipe must pass {COV_FLAG!r}; got:\n{recipe_text}"
    )
    assert COV_REPORT_FLAG in recipe_text, (
        f"`cov:` recipe must pass {COV_REPORT_FLAG!r}; got:\n{recipe_text}"
    )


# --------------------------------------------------------------------------
# EB5 --- coverage artifacts are git-ignored (commit-state-independent proof)
# --------------------------------------------------------------------------
@_needs_git
def test_eb5_coverage_artifacts_gitignored():
    r_cov = subprocess.run(
        ["git", "-C", str(REPO), "check-ignore", ".coverage"],
        capture_output=True, text=True, timeout=30,
    )
    assert r_cov.returncode == 0, (
        f"`git check-ignore .coverage` must exit 0 (ignored); "
        f"got rc={r_cov.returncode}, stderr={r_cov.stderr!r}"
    )
    assert r_cov.stdout.strip() == ".coverage", (
        f"`git check-ignore .coverage` must print '.coverage'; got {r_cov.stdout!r}"
    )

    r_html = subprocess.run(
        ["git", "-C", str(REPO), "check-ignore", "htmlcov/"],
        capture_output=True, text=True, timeout=30,
    )
    assert r_html.returncode == 0, (
        f"`git check-ignore htmlcov/` must exit 0 (ignored); "
        f"got rc={r_html.returncode}, stderr={r_html.stderr!r}"
    )
    assert "htmlcov" in r_html.stdout, (
        f"`git check-ignore htmlcov/` must print a path matching 'htmlcov'; got {r_html.stdout!r}"
    )


# --------------------------------------------------------------------------
# EB6 --- running coverage emits a TOTAL report line and exits 0 (BOUNDED subset)
# --------------------------------------------------------------------------
def test_eb6_coverage_run_emits_total_and_exits_zero(repo_coverage_cleanup):
    proc = _run_pytest([COV_FLAG, COV_REPORT_FLAG, COV_MODULE])
    assert proc.returncode == 0, (
        "coverage subset run must exit 0; "
        f"got rc={proc.returncode}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    )
    total_lines = [ln for ln in proc.stdout.splitlines() if _TOTAL_PCT.search(ln.strip())]
    assert total_lines, (
        "coverage stdout must contain a line beginning with 'TOTAL' that includes a "
        f"'%' percentage token; got stdout:\n{proc.stdout}"
    )


# --------------------------------------------------------------------------
# EB7 --- a coverage run does not leak .coverage into git's untracked set
# --------------------------------------------------------------------------
@_needs_git
def test_eb7_coverage_artifact_not_in_git_porcelain(repo_coverage_cleanup):
    proc = _run_pytest([COV_FLAG, COV_REPORT_FLAG, COV_MODULE])
    assert proc.returncode == 0, (
        f"coverage subset run must exit 0; got rc={proc.returncode}\n{proc.stdout}\n{proc.stderr}"
    )
    cov_file = REPO / ".coverage"
    assert cov_file.is_file(), (
        "a .coverage file must exist in repo root after the coverage run "
        "(proves the run actually measured something)"
    )
    status = subprocess.run(
        ["git", "-C", str(REPO), "status", "--porcelain"],
        capture_output=True, text=True, timeout=30,
    )
    assert status.returncode == 0, f"git status failed: {status.stderr!r}"
    paths = {ln[3:].strip() for ln in status.stdout.splitlines() if len(ln) > 3}
    assert ".coverage" not in paths, (
        "the .coverage artifact must never appear in `git status --porcelain` "
        f"(the .gitignore entry must suppress it); porcelain paths: {sorted(paths)}"
    )


# --------------------------------------------------------------------------
# EB8 --- `make clean` removes coverage artifacts (isolated, non-destructive)
# --------------------------------------------------------------------------
@_needs_make
def test_eb8_make_clean_removes_coverage_and_prior_artifacts(tmp_path):
    # Run the REAL clean recipe in an isolated copy so the live tree is untouched.
    shutil.copy(MAKEFILE, tmp_path / "Makefile")
    (tmp_path / ".coverage").write_text("fake-coverage-db")
    htmlcov = tmp_path / "htmlcov"
    htmlcov.mkdir()
    (htmlcov / "index.html").write_text("<html></html>")
    # Artifacts the clean target already handled (must still be removed).
    pla_runs = tmp_path / ".pla_runs"
    pla_runs.mkdir()
    (pla_runs / "slate.json").write_text("{}")
    pycache = tmp_path / "pkg" / "__pycache__"
    pycache.mkdir(parents=True)
    (pycache / "mod.cpython-312.pyc").write_bytes(b"\x00")
    pytest_cache = tmp_path / ".pytest_cache"
    pytest_cache.mkdir()
    (pytest_cache / "CACHEDIR.TAG").write_text("Signature")

    proc = subprocess.run(
        ["make", "-C", str(tmp_path), "clean"],
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, (
        f"`make clean` must exit 0; got rc={proc.returncode}\n{proc.stdout}\n{proc.stderr}"
    )
    # BOTH coverage artifacts gone.
    assert not (tmp_path / ".coverage").exists(), "make clean must remove .coverage"
    assert not htmlcov.exists(), "make clean must remove htmlcov/"
    # The pre-existing artifacts it already handled are still removed.
    assert not pla_runs.exists(), "make clean must still remove .pla_runs"
    assert not pycache.exists(), "make clean must still remove __pycache__"
    assert not pytest_cache.exists(), "make clean must still remove .pytest_cache"


# --------------------------------------------------------------------------
# EB9 --- a bare pytest run produces NO coverage output (dynamic opt-in proof)
# --------------------------------------------------------------------------
def test_eb9_bare_run_has_no_coverage_output(repo_coverage_cleanup):
    proc = _run_pytest([COV_MODULE])  # NO --cov flag
    assert proc.returncode == 0, (
        f"bare pytest run must exit 0; got rc={proc.returncode}\n{proc.stdout}\n{proc.stderr}"
    )
    leaked = [ln for ln in proc.stdout.splitlines() if _TOTAL_PCT.search(ln.strip())]
    assert not leaked, (
        "a bare pytest run (no --cov) must emit NO coverage 'TOTAL ... %' line "
        f"(coverage must stay strictly opt-in); leaked lines: {leaked}\n"
        f"full stdout:\n{proc.stdout}"
    )
    # Belt-and-suspenders: a bare run must not write a repo-root .coverage either.
    assert not (REPO / ".coverage").exists(), (
        "a bare pytest run must not create a .coverage artifact"
    )
