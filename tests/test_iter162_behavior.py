"""Behavior tests for factory iteration 162 -- the audited DOMAIN of the
root-Markdown table guard.

Iteration 162 re-keys ``tests/test_iter133_behavior.py``'s root-Markdown table
guard from a working-directory glob onto git's TRACKED root-level Markdown set,
and widens its anti-vacuity floor from 3 names to all 5 tracked root docs. The
defect being fixed is bidirectional: a working-directory domain audits scratch
files that exist in exactly ONE clone (so a defect there reds ``uv run pytest``
on one machine and is unreproducible everywhere else), and the reverse hole lets
a tracked public doc leave the audited set with nothing said.

ISOLATION: written from ``pm.md``, this repo's README/ROADMAP and the contents of
``tests/`` only (all inside the tester role's read scope). No implementation
source under ``src/`` was read, no ``git diff`` was run, and neither the
engineer's nor the reviewer's notes were opened.

Offline and deterministic: no network, no clock, no product import. Writes only
under ``tmp_path``. Subprocesses are read-only ``git`` calls plus ONE ``git init``
inside ``tmp_path``; no nested ``pytest`` child is spawned.
"""

from __future__ import annotations

import inspect
import subprocess
from pathlib import Path

import pytest

from tests import test_iter133_behavior as guard

REPO_ROOT = Path(__file__).resolve().parents[1]

#: The tracked ROOT-level Markdown docs, pinned HERE independently of the guard's
#: own ``TRACKED_ROOT_DOCS`` tuple. Two independent pins are the point: comparing
#: git's listing against a constant derived from that same listing would be
#: ``set(x) == set(x)``, which detects nothing.
EXPECTED_ROOT_DOCS = frozenset(
    {
        "DIRECTIONS.md",
        "README.md",
        "ROADMAP.md",
        "ROADMAP_ARCHIVE.md",
        "SPEC.md",
    }
)

#: Tracked Markdown that ``git ls-files "*.md"`` DOES list (git's pathspec ``*``
#: crosses ``/``) and that the root-only filter must therefore drop. Their content
#: is deliberately arbitrary fixture prose, so auditing them would red the build
#: on a file no one intended to audit.
NESTED_TRACKED_MARKDOWN = (
    "examples/fixture_workspace/README.md",
    "examples/fixture_workspace/notes/journal.md",
)

#: The retired call spelling, composed from two fragments ON PURPOSE. Behavior 1
#: forbids it inside the guard function; spelling it literally here would plant
#: the same landmine for any future whole-file census, which cannot tell a test's
#: expectation from the code it forbids.
RETIRED_GLOB_CALL = "REPO_ROOT" + ".glob"

#: A table whose second body row is one cell short of its header -- the known-bad
#: sample proving behaviors 1-6 did not narrow the domain into a decorative guard.
RAGGED_TABLE = """# Sample

| Row | Value | Status |
| --- | ----- | ------ |
| 1 | High | done |
| 2 | Low |
| 3 | Med | open |
"""


def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Read-only-by-default git call, skipping (never failing) if git is absent."""
    try:
        return subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:  # no binary / hung binary
        pytest.skip(f"git is unavailable ({exc}); the tracked set is unknowable here")


def _raw_listing() -> str:
    """This repo's verbatim ``git ls-files "*.md"`` output, or skip."""
    listed = _git("ls-files", "*.md", cwd=REPO_ROOT)
    if listed.returncode != 0:
        pytest.skip("not a git checkout; the tracked set is unknowable here")
    return listed.stdout


# ==========================================================================
# Behavior 1 -- the guard's domain is git-derived, not a working-dir glob.
# ==========================================================================


def test_b1_guard_function_no_longer_globs_the_working_directory() -> None:
    source = inspect.getsource(guard.test_b4_every_root_markdown_file_is_table_clean)

    assert RETIRED_GLOB_CALL not in source, (
        "the guard still globs the repo root, so its audited set is whatever "
        "scratch Markdown happens to sit in ONE clone"
    )
    assert "tracked_root_markdown" in source, (
        "the guard must take its domain from the git-backed helper; got:\n" + source
    )


def test_b1_guard_still_passes_on_this_repo() -> None:
    """The re-key is a correctness fix, not a new failure: the guard is green."""
    guard.test_b4_every_root_markdown_file_is_table_clean()


# ==========================================================================
# Behavior 2 -- nested tracked Markdown is excluded from the audited set.
# ==========================================================================


def test_b2_nested_tracked_markdown_is_listed_by_git_but_never_audited() -> None:
    raw = _raw_listing()

    # Anti-vacuity FIRST: the exclusion below means nothing unless git really
    # does list nested paths for this pathspec.
    present = [name for name in NESTED_TRACKED_MARKDOWN if name in raw.splitlines()]
    assert sorted(present) == sorted(NESTED_TRACKED_MARKDOWN), (
        "git no longer lists the nested fixture Markdown, so the root-only "
        f"filter is being proved against nothing; listing was:\n{raw}"
    )

    audited = guard.tracked_root_markdown()
    assert set(audited) == EXPECTED_ROOT_DOCS, (
        f"audited set {sorted(audited)} != the 5 tracked root docs "
        f"{sorted(EXPECTED_ROOT_DOCS)}"
    )
    for nested in NESTED_TRACKED_MARKDOWN:
        assert nested not in audited, f"{nested} leaked into the audited set"


def test_b2_audited_names_are_bare_root_names_with_no_separator() -> None:
    audited = guard.tracked_root_markdown()

    assert audited, "empty audited set -- the domain helper is vacuous"
    assert all("/" not in name for name in audited), audited
    assert all((REPO_ROOT / name).is_file() for name in audited), (
        "every audited name must resolve to a real file at the repo root; got "
        f"{audited}"
    )


# ==========================================================================
# Behavior 3 -- set equality, with INDEPENDENT provenance on both sides.
# ==========================================================================


def test_b3_guards_pinned_constant_matches_this_files_independent_pin() -> None:
    assert set(guard.TRACKED_ROOT_DOCS) == EXPECTED_ROOT_DOCS, (
        "the guard's pinned root-doc tuple drifted from this file's independent "
        f"pin: guard={sorted(guard.TRACKED_ROOT_DOCS)} "
        f"expected={sorted(EXPECTED_ROOT_DOCS)}"
    )
    assert len(guard.TRACKED_ROOT_DOCS) == len(set(guard.TRACKED_ROOT_DOCS)), (
        f"duplicate name in the pinned tuple: {guard.TRACKED_ROOT_DOCS}"
    )


def test_b3_git_derived_set_equals_the_pin_exactly() -> None:
    assert set(guard.tracked_root_markdown()) == EXPECTED_ROOT_DOCS


def test_b3_a_superset_reds_the_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    """No untracked file may be audited -- an extra name must fail, not pass."""
    monkeypatch.setattr(
        guard,
        "tracked_root_markdown",
        lambda: sorted({*guard.TRACKED_ROOT_DOCS, "SCRATCH_NOTE.md"}),
    )
    with pytest.raises(AssertionError) as caught:
        guard.test_b4_every_root_markdown_file_is_table_clean()
    assert "SCRATCH_NOTE.md" in str(caught.value), str(caught.value)


def test_b3_a_subset_reds_the_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    """No tracked root doc may silently leave the audited set."""
    monkeypatch.setattr(
        guard,
        "tracked_root_markdown",
        lambda: [n for n in guard.TRACKED_ROOT_DOCS if n != "SPEC.md"],
    )
    with pytest.raises(AssertionError) as caught:
        guard.test_b4_every_root_markdown_file_is_table_clean()
    assert "SPEC.md" in str(caught.value), str(caught.value)


# ==========================================================================
# Behavior 4 -- the anti-vacuity floor covers all 5 docs, and runs FIRST.
# ==========================================================================


@pytest.mark.parametrize("dropped", sorted(EXPECTED_ROOT_DOCS))
def test_b4_floor_covers_every_one_of_the_five_docs(
    dropped: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Dropping ANY of the 5 must red the guard: that is what "floor of 5" means."""
    monkeypatch.setattr(
        guard,
        "tracked_root_markdown",
        lambda: [n for n in guard.TRACKED_ROOT_DOCS if n != dropped],
    )
    with pytest.raises(AssertionError) as caught:
        guard.test_b4_every_root_markdown_file_is_table_clean()
    assert dropped in str(caught.value), str(caught.value)


def test_b4_an_empty_listing_fails_instead_of_passing_vacuously(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(guard, "tracked_root_markdown", list)
    with pytest.raises(AssertionError) as caught:
        guard.test_b4_every_root_markdown_file_is_table_clean()
    assert "vacuous" in str(caught.value).lower(), str(caught.value)


def test_b4_non_emptiness_is_asserted_before_any_file_is_audited() -> None:
    """Ordering matters: the table assertion over an empty set passes trivially."""
    lines = inspect.getsource(
        guard.test_b4_every_root_markdown_file_is_table_clean
    ).splitlines()
    floor = next(
        i for i, line in enumerate(lines) if "assert" in line and "names" in line
    )
    audit = next(i for i, line in enumerate(lines) if "audit_markdown(" in line)

    assert floor < audit, (
        "the anti-vacuity assertion must precede the table audit; floor at "
        f"offset {floor}, audit at {audit}"
    )


# ==========================================================================
# Behavior 5 -- an untracked root *.md on disk is never audited.
# ==========================================================================


def test_b5_untracked_root_markdown_in_a_real_repo_is_not_audited(
    tmp_path: Path,
) -> None:
    """Built here rather than asserted on the ambient tree: a fresh clone has no
    untracked file at all, so the ambient version of this proof is unreachable."""
    if _git("init", "-q", cwd=tmp_path).returncode != 0:
        pytest.skip("git init failed; the tracked set is unknowable here")

    (tmp_path / "TRACKED.md").write_text("# tracked\n", encoding="utf-8")
    (tmp_path / "UNTRACKED.md").write_text("# untracked\n", encoding="utf-8")
    nested = tmp_path / "docs"
    nested.mkdir()
    (nested / "NESTED.md").write_text("# nested\n", encoding="utf-8")
    if _git("add", "TRACKED.md", "docs/NESTED.md", cwd=tmp_path).returncode != 0:
        pytest.skip("git add failed; the tracked set is unknowable here")

    audited = guard.tracked_root_markdown(tmp_path)

    assert audited == ["TRACKED.md"], (
        "the domain must be git's index, not the directory: expected only the "
        f"tracked root file, got {audited}"
    )
    assert (tmp_path / "UNTRACKED.md").is_file(), "fixture lost its untracked file"


def test_b5_this_repos_untracked_root_markdown_is_excluded_when_present() -> None:
    """Ambient companion arm. Skips (never silently passes) on a clean clone."""
    tracked = set(guard.tracked_root_markdown())
    on_disk = {path.name for path in REPO_ROOT.glob("*.md")}
    extras = sorted(on_disk - tracked)
    if not extras:
        pytest.skip("no untracked root *.md in this clone; the tmp-repo arm proves it")

    for extra in extras:
        assert extra not in tracked, f"{extra} is untracked yet audited"


# ==========================================================================
# Behavior 6 -- the root-only filter is pure and proven on a synthetic listing.
# ==========================================================================


def test_b6_filter_keeps_only_stripped_root_names_and_drops_blanks() -> None:
    listing = (
        "  README.md  \n"
        "docs/GUIDE.md\n"
        "\n"
        "a/b/c/DEEP.md\n"
        "   \n"
        "SPEC.md\n"
        "\t\n"
    )

    assert guard.root_markdown_names(listing) == ["README.md", "SPEC.md"]


def test_b6_filter_accepts_a_line_list_and_is_deterministically_sorted() -> None:
    lines = ["ZEBRA.md", "docs/x.md", "alpha.md", "", "  Beta.md  "]

    result = guard.root_markdown_names(lines)

    assert result == sorted(result), f"order must be deterministic; got {result}"
    assert result == ["Beta.md", "ZEBRA.md", "alpha.md"], result


def test_b6_filter_deduplicates_an_unmerged_path_printed_three_times() -> None:
    """``ls-files`` prints one line per index stage during a conflict."""
    assert guard.root_markdown_names("README.md\nREADME.md\nREADME.md\n") == [
        "README.md"
    ]


def test_b6_filter_is_pure_and_needs_no_git(monkeypatch: pytest.MonkeyPatch) -> None:
    def _explode(*args: object, **kwargs: object) -> None:
        raise AssertionError("root_markdown_names must not invoke a subprocess")

    monkeypatch.setattr(subprocess, "run", _explode)
    assert guard.root_markdown_names("ONLY.md\nnested/other.md\n") == ["ONLY.md"]


# ==========================================================================
# Behavior 7 -- the table detector still fires on a known-bad sample.
# ==========================================================================


def test_b7_detector_still_flags_a_ragged_table_through_the_guards_entry_point(
    tmp_path: Path,
) -> None:
    sample = tmp_path / "RAGGED.md"
    sample.write_text(RAGGED_TABLE, encoding="utf-8")

    findings = guard.audit_markdown(guard.read(sample))

    assert findings, (
        "the auditor found nothing in a table with a short row -- the guard is "
        "decorative and behaviors 1-6 narrowed the domain for nothing"
    )
    kinds = {finding.kind for finding in findings}
    assert "column_count" in kinds, f"expected a column_count finding; got {findings}"
    assert any(finding.line == 6 for finding in findings), (
        f"the short row is on line 6; findings reported {[f.line for f in findings]}"
    )


def test_b7_a_well_formed_table_yields_no_findings(tmp_path: Path) -> None:
    """Two-sided: a detector that fired on everything would also be useless."""
    sample = tmp_path / "CLEAN.md"
    sample.write_text(
        "# Sample\n\n| Row | Value |\n| --- | ----- |\n| 1 | High |\n| 2 | Low |\n",
        encoding="utf-8",
    )

    assert guard.audit_markdown(guard.read(sample)) == []


# ==========================================================================
# Behavior 8 -- absent git degrades with a NAMED reason, and not here.
# ==========================================================================


def test_b8_a_directory_with_no_index_skips_with_a_named_reason(
    tmp_path: Path,
) -> None:
    with pytest.raises(pytest.skip.Exception) as caught:
        guard.tracked_root_markdown(tmp_path)

    reason = str(caught.value)
    assert "unknowable" in reason, (
        f"the skip must name the tracked set as unknowable; got {reason!r}"
    )
    assert str(tmp_path) in reason or "git" in reason, reason


def test_b8_the_skip_path_does_not_fire_in_this_checkout() -> None:
    """A degrade path that fires everywhere would mask every real failure."""
    audited = guard.tracked_root_markdown()

    assert audited, "the guard skipped or audited nothing inside a real checkout"
    assert len(audited) == len(EXPECTED_ROOT_DOCS), audited
