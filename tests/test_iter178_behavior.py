"""Black-box behavior tests for state-dir iteration 174 (ships as ``factory iter 178``).

Feature under test (``pm.md``): git-ignore AND ``make clean`` the parallel-coverage
data files the suite really writes. Under ``addopts = "-q -n auto"`` coverage.py
writes one ``.coverage.<host>.<pid>.<rand>`` file per xdist worker into the repo
ROOT before combining, and ``.gitignore``'s pre-existing entry is the EXACT name
``.coverage`` with no glob -- so those per-worker files were untracked AND
unignored in a PUBLIC repo, survived ``make clean``, and were seen by every
``git status --porcelain`` consumer (the release gate's ``git add -A``, the
product's own ``working_tree`` collector). The fix is a pure ADD of one separate
``.gitignore`` line plus the same glob in the ``clean`` recipe.

ISOLATION CONTRACT (honored): written strictly against this iteration's spec
("Expected Behaviors" in ``pm.md``) and the PUBLIC build artifacts -- the text of
``.gitignore`` and the behavior of the real ``Makefile`` ``clean`` recipe RUN in an
isolated copy -- plus ``git check-ignore``'s own output. **No file under ``src/``
was read, no engineer or reviewer note was read, and no ``git diff`` was
consulted.** Behavior 6 is a property of a TEST MODULE, so it is measured by
importing and DRIVING that module's pure function, which is inside this role's
contract. Fully offline: no network, no API key. Nothing is ever deleted from the
live working tree -- the ``make clean`` proof runs in ``tmp_path``, because
sibling xdist workers hold real ``.coverage.*`` files in the repo root and
deleting those mid-run is a flake this repo has already paid for.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from tests import test_readme_and_ci_contract as contract

REPO = Path(__file__).resolve().parents[1]
GITIGNORE = REPO / ".gitignore"
MAKEFILE = REPO / "Makefile"

# --------------------------------------------------------------------------
# Spec-declared ground facts (pm.md). Encoded here, never imported from the
# artifact under test, so a silent drift reds the suite.
# --------------------------------------------------------------------------
# The synthetic parallel-data name the spec names verbatim. check-ignore answers
# about the PATH, so this file never has to exist.
PARALLEL_DATA = ".coverage.host.pid1234.abc"
# The pre-existing exact-name entry, which must keep working unchanged.
EXACT_ENTRY = ".coverage"
# The new, NARROW entry: a literal dot after `coverage` is required.
GLOB_ENTRY = ".coverage.*"
# The widened form the spec forbids -- it would also swallow `.coveragerc`.
FORBIDDEN_WIDE = ".coverage*"
# The two-sided negative: no dot after `coverage`, so the narrow glob must miss it.
NEAR_MISS = ".coveragerc"


def _tool_available(*cmd: str) -> bool:
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=15)
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


_needs_git = pytest.mark.skipif(not _tool_available("git", "--version"), reason="git not available")
_needs_make = pytest.mark.skipif(not _tool_available("make", "--version"), reason="make not available")


def _check_ignore(path: str, *flags: str) -> subprocess.CompletedProcess[str]:
    """`git check-ignore` for one path, run inside the real repo."""
    return subprocess.run(
        ["git", "-C", str(REPO), "check-ignore", *flags, path],
        capture_output=True, text=True, timeout=30,
    )


def _attribution(verbose_stdout: str) -> tuple[str, str]:
    """The (source-file, pattern) `check-ignore -v` credits, line number DISCARDED.

    Format is ``<source>:<linenum>:<pattern>\\t<pathname>``. The line number is
    deliberately dropped: which line the rule sits on is not a contract, so
    pinning it would red the build on an unrelated reordering.
    """
    left = verbose_stdout.strip().split("\t", 1)[0]
    source, _linenum, pattern = left.rsplit(":", 2)
    return source, pattern


def _gitignore_patterns() -> tuple[str, ...]:
    """The RULE lines of `.gitignore`, with comments and negations dropped.

    Load-bearing: the file explains in a COMMENT why the rule is not the wider
    glob, so that comment necessarily contains the forbidden literal. A naive
    substring check over the whole text therefore fails on a HEALTHY file. Only
    non-comment lines are rules, so only they are measured.
    """
    patterns: list[str] = []
    for raw in GITIGNORE.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("!"):
            continue
        patterns.append(line)
    return tuple(patterns)


# --------------------------------------------------------------------------
# EB1 -- the per-worker parallel-data name is ignored, and the NEW rule is what
#        does the ignoring (attribution, so the pass cannot be borrowed).
# --------------------------------------------------------------------------
@_needs_git
def test_eb1_parallel_coverage_data_name_is_gitignored() -> None:
    r = _check_ignore(PARALLEL_DATA, "-q")
    assert r.returncode == 0, (
        f"`git check-ignore -q {PARALLEL_DATA}` must exit 0 (the path is ignored); "
        f"got rc={r.returncode}, stderr={r.stderr!r} -- an xdist coverage worker file "
        "would otherwise be untracked AND unignored in the repo root"
    )
    v = _check_ignore(PARALLEL_DATA, "-v")
    assert v.returncode == 0, f"`check-ignore -v` must agree with -q; got rc={v.returncode}"
    source, pattern = _attribution(v.stdout)
    assert Path(source).name == ".gitignore", (
        f"the rule must live in the repo's own .gitignore, not a machine-global "
        f"exclude file; git credited {source!r} ({v.stdout!r})"
    )
    assert pattern == GLOB_ENTRY, (
        f"the match must be credited to the new {GLOB_ENTRY!r} rule, not to a wider "
        f"pattern; git credited {pattern!r} ({v.stdout!r})"
    )


# --------------------------------------------------------------------------
# EB2 -- pure ADD: the pre-existing exact-name rule still works, still by itself.
# --------------------------------------------------------------------------
@_needs_git
def test_eb2_plain_coverage_file_is_still_ignored_by_the_exact_name_rule() -> None:
    r = _check_ignore(EXACT_ENTRY)
    assert r.returncode == 0, (
        f"`git check-ignore {EXACT_ENTRY}` must still exit 0; got rc={r.returncode}, "
        f"stderr={r.stderr!r}"
    )
    assert r.stdout.strip() == EXACT_ENTRY, (
        f"`git check-ignore {EXACT_ENTRY}` must still print {EXACT_ENTRY!r}; got {r.stdout!r}"
    )
    v = _check_ignore(EXACT_ENTRY, "-v")
    _source, pattern = _attribution(v.stdout)
    assert pattern == EXACT_ENTRY, (
        f"the combined data file must still be credited to the untouched exact-name "
        f"rule {EXACT_ENTRY!r} (the new glob requires a literal dot after 'coverage', "
        f"so it must NOT be the matcher here); git credited {pattern!r} ({v.stdout!r})"
    )


# --------------------------------------------------------------------------
# EB3 -- both entries exist as two DISTINCT rule lines; line 7 was not widened.
# --------------------------------------------------------------------------
def test_eb3_gitignore_declares_both_entries_as_separate_rule_lines() -> None:
    patterns = _gitignore_patterns()
    assert patterns, ".gitignore must hold at least one rule line"
    assert EXACT_ENTRY in patterns, (
        f"the pre-existing exact-name rule {EXACT_ENTRY!r} must survive verbatim; "
        f"rule lines are {patterns!r}"
    )
    assert GLOB_ENTRY in patterns, (
        f".gitignore must gain a SEPARATE {GLOB_ENTRY!r} rule line; rule lines are {patterns!r}"
    )
    assert patterns.index(EXACT_ENTRY) != patterns.index(GLOB_ENTRY), (
        "the two entries must be two distinct lines, not one rewritten line"
    )
    assert FORBIDDEN_WIDE not in patterns, (
        f"the exact-name rule must NOT have been widened to {FORBIDDEN_WIDE!r} (that "
        f"would also swallow {NEAR_MISS!r}); rule lines are {patterns!r}"
    )


# --------------------------------------------------------------------------
# EB4 -- two-sided negative: the new rule is NARROW, so `.coveragerc` is visible.
# --------------------------------------------------------------------------
@_needs_git
def test_eb4_coveragerc_is_not_ignored_so_the_new_rule_is_narrow() -> None:
    r = _check_ignore(NEAR_MISS, "-q")
    assert r.returncode == 1, (
        f"`git check-ignore -q {NEAR_MISS}` must exit 1 (NOT ignored): {GLOB_ENTRY!r} "
        f"requires a literal dot after 'coverage' and {NEAR_MISS!r} has none, so a rc of "
        f"0 means the pattern degenerated to {FORBIDDEN_WIDE!r}. rc=1 is the honest "
        f"negative and rc=128 would be a git error, not an answer; got rc={r.returncode}, "
        f"stderr={r.stderr!r}"
    )


# --------------------------------------------------------------------------
# EB5 -- `make clean` removes the glob class AND everything it already handled.
#        Runs the REAL recipe in an isolated copy: never against the live root.
# --------------------------------------------------------------------------
@_needs_make
def test_eb5_make_clean_removes_parallel_coverage_data_and_prior_artifacts(tmp_path: Path) -> None:
    shutil.copy(MAKEFILE, tmp_path / "Makefile")
    # This iteration's new subject, plus the combined file it must still remove.
    parallel = tmp_path / PARALLEL_DATA
    parallel.write_text("fake-parallel-coverage-shard")
    combined = tmp_path / EXACT_ENTRY
    combined.write_text("fake-coverage-db")
    htmlcov = tmp_path / "htmlcov"
    htmlcov.mkdir()
    (htmlcov / "index.html").write_text("<html></html>")
    # Artifacts the recipe already handled: proves the glob was ADDED, not swapped in.
    pla_runs = tmp_path / ".pla_runs"
    pla_runs.mkdir()
    (pla_runs / "slate.json").write_text("{}")
    pycache = tmp_path / "pkg" / "__pycache__"
    pycache.mkdir(parents=True)
    (pycache / "mod.cpython-312.pyc").write_bytes(b"\x00")
    pytest_cache = tmp_path / ".pytest_cache"
    pytest_cache.mkdir()
    (pytest_cache / "CACHEDIR.TAG").write_text("Signature")
    # A near-miss that must SURVIVE: `clean` must not widen either.
    coveragerc = tmp_path / NEAR_MISS
    coveragerc.write_text("[run]\n")

    proc = subprocess.run(
        ["make", "-C", str(tmp_path), "clean"],
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, (
        f"`make clean` must exit 0 (rm -rf is silent on a non-matching glob); "
        f"got rc={proc.returncode}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    )
    assert not parallel.exists(), (
        f"`make clean` must remove the parallel-coverage class {PARALLEL_DATA!r}; "
        f"survivors: {sorted(p.name for p in tmp_path.iterdir())}"
    )
    assert not combined.exists(), f"`make clean` must still remove {EXACT_ENTRY!r}"
    assert not htmlcov.exists(), "`make clean` must still remove htmlcov/"
    assert not pla_runs.exists(), "`make clean` must still remove .pla_runs"
    assert not pycache.exists(), "`make clean` must still remove __pycache__"
    assert not pytest_cache.exists(), "`make clean` must still remove .pytest_cache"
    assert coveragerc.is_file(), (
        f"`make clean` must NOT remove {NEAR_MISS!r} -- the recipe glob has to stay as "
        f"narrow as the .gitignore rule"
    )


# --------------------------------------------------------------------------
# EB6 -- the OTHER layer is untouched: the in-oracle filter still exists and
#        still filters, and it is PURE (it never consults .gitignore).
# --------------------------------------------------------------------------
def test_eb6_in_oracle_parallel_data_filter_is_still_declared_and_still_filters() -> None:
    # Declaration: the import itself is the assertion -- a deletion raises AttributeError.
    pattern = contract.COVERAGE_PARALLEL_DATA
    assert pattern.match(PARALLEL_DATA), (
        f"COVERAGE_PARALLEL_DATA must still match a parallel-data name; "
        f"{PARALLEL_DATA!r} did not match {pattern.pattern!r}"
    )
    assert not pattern.match(EXACT_ENTRY), (
        f"COVERAGE_PARALLEL_DATA must stay narrow: the combined {EXACT_ENTRY!r} carries no "
        f"dot-suffix and must NOT match {pattern.pattern!r}"
    )
    # Consultation: the pure function still drops exactly that class ...
    appeared = f"?? {PARALLEL_DATA}"
    assert contract.collection_tree_violations([], [appeared]) == [], (
        f"collection_tree_violations must still filter {appeared!r}; the two layers are "
        "independent and .gitignore does not replace this one"
    )
    # ... and still reports a genuine dirtying, so the filter is not a blanket pass.
    genuine = ["?? htmlcov/", f"?? {EXACT_ENTRY}"]
    assert contract.collection_tree_violations([], genuine) == sorted(genuine), (
        f"collection_tree_violations must still return a real tree-dirtying entry; got "
        f"{contract.collection_tree_violations([], genuine)!r}"
    )


def test_eb6_in_oracle_filter_is_pure_and_never_reads_gitignore(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same verdict from a cwd holding NO `.gitignore`, so no ambient file is read.

    This is why a future iteration must not delete the in-oracle filter on the
    theory that `.gitignore` now covers the class: the function cannot see
    `.gitignore` at all.
    """
    monkeypatch.chdir(tmp_path)
    assert not (tmp_path / ".gitignore").exists(), "fixture precondition: no ambient .gitignore"
    appeared = f"?? {PARALLEL_DATA}"
    assert contract.collection_tree_violations([], [appeared]) == []
    assert contract.collection_tree_violations([], ["?? htmlcov/"]) == ["?? htmlcov/"]


# --------------------------------------------------------------------------
# EB5 NEGATIVE CONTROL -- proof the EB5 oracle can FAIL, so its pass is real.
#
# `make` gives no rule attribution (unlike `git check-ignore -v`, which is why
# EB1/EB2 need no control repo), so the only way to show the glob is load-bearing
# is to run the PRE-FIX recipe shape and watch the same assertion go red. The old
# recipe text is taken from the spec, which quotes it verbatim as the exact-name
# list `rm -rf .coverage htmlcov`; this fixture is fully synthetic and never reads
# the repo's Makefile, so it cannot drift with it.
# --------------------------------------------------------------------------
@_needs_make
def test_eb5_control_pre_fix_exact_name_recipe_leaves_the_parallel_data_behind(
    tmp_path: Path,
) -> None:
    (tmp_path / "Makefile").write_text(
        "clean:\n" + "\t" + "rm -rf .coverage htmlcov\n"
    )
    parallel = tmp_path / PARALLEL_DATA
    parallel.write_text("fake-parallel-coverage-shard")
    combined = tmp_path / EXACT_ENTRY
    combined.write_text("fake-coverage-db")

    proc = subprocess.run(
        ["make", "-C", str(tmp_path), "clean"],
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, f"control recipe must run; got rc={proc.returncode}\n{proc.stderr}"
    assert not combined.exists(), "control precondition: the exact-name rule does remove .coverage"
    assert parallel.is_file(), (
        "CONTROL BROKEN: the pre-fix exact-name recipe already removed "
        f"{PARALLEL_DATA!r}, which would mean EB5 asserts nothing. EB5's pass is only "
        "evidence if this shape leaves the file behind."
    )


# --------------------------------------------------------------------------
# EB5, second half of the acceptance criterion -- the EMPTY-GLOB case. The spec
# argues no `2>/dev/null` and no shell guard is needed because `rm -rf` ignores a
# nonexistent operand, and an unmatched glob reaches `rm` as its own literal.
# Nothing pinned that, and it is the case a developer hits most: `make clean` on
# an already-clean tree. A recipe that reds there breaks the DX the target exists
# for.
# --------------------------------------------------------------------------
@_needs_make
def test_eb5_make_clean_is_idempotent_on_a_tree_with_no_artifacts(tmp_path: Path) -> None:
    shutil.copy(MAKEFILE, tmp_path / "Makefile")
    for run in (1, 2):
        proc = subprocess.run(
            ["make", "-C", str(tmp_path), "clean"],
            capture_output=True, text=True, timeout=60,
        )
        assert proc.returncode == 0, (
            f"`make clean` run {run} on a tree holding NO artifacts must still exit 0 "
            f"(an unmatched glob reaches `rm -rf` as a literal, and `-f` ignores a "
            f"nonexistent operand); got rc={proc.returncode}\nSTDOUT:\n{proc.stdout}\n"
            f"STDERR:\n{proc.stderr}"
        )
    assert (tmp_path / "Makefile").is_file(), "`make clean` must not remove the Makefile itself"
