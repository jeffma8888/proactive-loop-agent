"""Black-box behavior tests for iteration 20.

Feature under test: a new **L2 perception collector**, ``GitStateCollector``
(``name == "git_state"``, ``kind == "git_state"``). It is the *interrupted-
operation* companion to ``GitActivityCollector`` (the committed past) and
``WorkingTreeCollector`` (the present diff / unpushed count): it surfaces
**dangling git operations** that silently block or corrupt the next action --
an unfinished merge / rebase / cherry-pick / revert and a detached HEAD -- by
reading ``.git`` **marker files with ``pathlib`` only** (a genuinely different
mechanism than the two subprocess-based git collectors: NO ``subprocess``, NO
network, NO ``git`` invocation). It scans ``root`` plus each direct-child dir
whose ``.git`` is a directory, reports each detected state as an independent
``ContextSignal`` (``weight == 0.8``, ``path is None``, ``timestamp is None``),
sorts output by ``summary`` ascending, and -- like every collector -- degrades
to ``[]`` rather than raising on any missing/hostile input.

ISOLATION CONTRACT (honored): these tests are written strictly against the
public contract -- this iteration's spec "Expected Behaviors" (``pm.md``),
``README.md``, and ``SPEC.md`` section 4.1 (the ``collectors`` module contract)
-- and drive ONLY the documented public surface: the collector API
``GitStateCollector().collect(root)``, the ``proactive_loop.collectors`` package
imports (``GitStateCollector``, ``all_collectors``), the
``proactive_loop.collectors.git_state`` submodule import, the ``Collector``
protocol from ``proactive_loop.collectors.base``, the ``ContextSignal`` domain
model from ``proactive_loop.models``, and the ``proactive_loop.__version__``
metadata. **No file under ``src/`` was read, no engineer/reviewer notes were
read, and no ``git diff`` was consulted.** Signal field names
(``source``/``kind``/``summary``/``detail``/``weight``/``path``/``timestamp``)
were taken from this iteration's spec and the existing published tests, never
from the implementation. Every git-state test builds its own synthetic
``tmp_path`` workspace -- it creates a ``.git/`` **directory** and drops marker
files/dirs into it (NO real git repo, NO ``subprocess``, NO network, NO API
keys) -- because the collector only reads marker files. No test asserts against
``examples/fixture_workspace`` (per the iter-15/16 env-stability lesson tests
use self-built tmp workspaces).
"""

from __future__ import annotations

from pathlib import Path

from proactive_loop.collectors import GitStateCollector, all_collectors
from proactive_loop.collectors.base import Collector
from proactive_loop.collectors.git_state import (
    GitStateCollector as GitStateCollector_direct,
)
from proactive_loop.models import ContextSignal

# The seven collectors that predate git_state; the registry must remain a
# superset of these (no prior collector dropped) -- asserted as membership,
# never as a brittle exact count on the prior seven (per spec Behavior 1).
PRIOR_SEVEN = {
    "recent_files",
    "git_activity",
    "todos",
    "notes",
    "dependencies",
    "working_tree",
    "test_posture",
}


# ---------------------------------------------------------------------------
# Helpers (self-built synthetic workspaces -- marker files only, no real git)
# ---------------------------------------------------------------------------


def _make_repo(base: Path, name: str = "repo") -> Path:
    """Create ``base/<name>`` with a ``.git/`` **directory** inside; return it."""
    d = base / name
    (d / ".git").mkdir(parents=True)
    return d


def _assert_fixed_fields(s: ContextSignal, repo_dir: Path) -> None:
    """Every git_state signal carries these fixed fields (spec, verbatim)."""
    assert isinstance(s, ContextSignal), f"not a ContextSignal: {s!r}"
    assert s.source == "git_state", f"bad source: {s.source!r}"
    assert s.kind == "git_state", f"bad kind: {s.kind!r}"
    assert s.weight == 0.8, f"bad weight: {s.weight!r}"
    assert s.path is None, f"path must be None, got: {s.path!r}"
    assert s.timestamp is None, f"timestamp must be None, got: {s.timestamp!r}"
    # detail is a non-empty human explanation; content intentionally unspecified.
    assert isinstance(s.detail, str) and s.detail.strip(), (
        f"detail must be a non-empty string, got: {s.detail!r}"
    )
    # summary must contain the repo dir's base name.
    assert repo_dir.name in (s.summary or ""), (
        f"summary must mention repo base name {repo_dir.name!r}: {s.summary!r}"
    )


def _summaries_lower(signals: list[ContextSignal]) -> list[str]:
    return [(s.summary or "").lower() for s in signals]


# ===========================================================================
# Behavior 1 -- Registration & protocol
# ===========================================================================


def test_b01_importable_two_ways_same_class() -> None:
    # Package-level and submodule-level imports resolve to the same class.
    assert GitStateCollector is GitStateCollector_direct


def test_b01_default_instance_name_and_collect_callable() -> None:
    c = GitStateCollector()
    assert c.name == "git_state"
    assert callable(c.collect)


def test_b01_satisfies_collector_protocol() -> None:
    assert isinstance(GitStateCollector(), Collector)


def test_b01_registry_contains_exactly_one_git_state() -> None:
    collectors = all_collectors()
    git_state = [c for c in collectors if getattr(c, "name", None) == "git_state"]
    assert len(git_state) == 1
    assert isinstance(git_state[0], GitStateCollector)


def test_b01_registry_superset_of_prior_seven_plus_git_state() -> None:
    names = {getattr(c, "name", None) for c in all_collectors()}
    # No prior collector was dropped, and git_state was added -> 8 names present.
    assert (PRIOR_SEVEN | {"git_state"}) <= names, (
        f"registry names not a superset of the eight expected: {sorted(names)}"
    )


# ===========================================================================
# Behavior 2 -- Merge in progress
# ===========================================================================


def test_b02_merge_in_progress(tmp_path: Path) -> None:
    d = _make_repo(tmp_path, "merge_repo")
    (d / ".git" / "MERGE_HEAD").write_text("0123456789abcdef\n")
    signals = GitStateCollector().collect(d)
    assert len(signals) == 1, f"expected exactly one signal: {_summaries_lower(signals)}"
    s = signals[0]
    _assert_fixed_fields(s, d)
    assert "merge" in (s.summary or "").lower(), f"summary lacks 'merge': {s.summary!r}"


# ===========================================================================
# Behavior 3 -- Rebase in progress (either marker directory)
# ===========================================================================


def test_b03_rebase_merge_dir(tmp_path: Path) -> None:
    d = _make_repo(tmp_path, "rebase_a")
    (d / ".git" / "rebase-merge").mkdir()
    signals = GitStateCollector().collect(d)
    assert len(signals) == 1, f"expected exactly one signal: {_summaries_lower(signals)}"
    s = signals[0]
    _assert_fixed_fields(s, d)
    assert "rebase" in (s.summary or "").lower(), f"summary lacks 'rebase': {s.summary!r}"


def test_b03_rebase_apply_dir(tmp_path: Path) -> None:
    d = _make_repo(tmp_path, "rebase_b")
    (d / ".git" / "rebase-apply").mkdir()
    signals = GitStateCollector().collect(d)
    assert len(signals) == 1, f"expected exactly one signal: {_summaries_lower(signals)}"
    s = signals[0]
    _assert_fixed_fields(s, d)
    assert "rebase" in (s.summary or "").lower(), f"summary lacks 'rebase': {s.summary!r}"


# ===========================================================================
# Behavior 4 -- Cherry-pick in progress
# ===========================================================================


def test_b04_cherry_pick_in_progress(tmp_path: Path) -> None:
    d = _make_repo(tmp_path, "cherry_repo")
    (d / ".git" / "CHERRY_PICK_HEAD").write_text("0123456789abcdef\n")
    signals = GitStateCollector().collect(d)
    assert len(signals) == 1, f"expected exactly one signal: {_summaries_lower(signals)}"
    s = signals[0]
    _assert_fixed_fields(s, d)
    assert "cherry-pick" in (s.summary or "").lower(), (
        f"summary lacks 'cherry-pick': {s.summary!r}"
    )


# ===========================================================================
# Behavior 5 -- Revert in progress
# ===========================================================================


def test_b05_revert_in_progress(tmp_path: Path) -> None:
    d = _make_repo(tmp_path, "revert_repo")
    (d / ".git" / "REVERT_HEAD").write_text("0123456789abcdef\n")
    signals = GitStateCollector().collect(d)
    assert len(signals) == 1, f"expected exactly one signal: {_summaries_lower(signals)}"
    s = signals[0]
    _assert_fixed_fields(s, d)
    assert "revert" in (s.summary or "").lower(), f"summary lacks 'revert': {s.summary!r}"


# ===========================================================================
# Behavior 6 -- Detached HEAD
# ===========================================================================


def test_b06_detached_head(tmp_path: Path) -> None:
    d = _make_repo(tmp_path, "detached_repo")
    # Raw 40-char hex SHA (trailing newline exercises the strip), no "ref:" prefix.
    (d / ".git" / "HEAD").write_text("a" * 40 + "\n")
    signals = GitStateCollector().collect(d)
    assert len(signals) == 1, f"expected exactly one signal: {_summaries_lower(signals)}"
    s = signals[0]
    _assert_fixed_fields(s, d)
    assert "detached" in (s.summary or "").lower(), (
        f"summary lacks 'detached': {s.summary!r}"
    )


# ===========================================================================
# Behavior 7 -- Attached / clean HEAD emits nothing
# ===========================================================================


def test_b07_attached_head_emits_nothing(tmp_path: Path) -> None:
    d = _make_repo(tmp_path, "clean_repo")
    (d / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    assert GitStateCollector().collect(d) == []


# ===========================================================================
# Behavior 8 -- Non-repo and hostile inputs degrade to [] (never raise)
# ===========================================================================


def test_b08a_dir_without_git(tmp_path: Path) -> None:
    d = tmp_path / "plain_dir"
    d.mkdir()
    assert GitStateCollector().collect(d) == []


def test_b08b_path_does_not_exist(tmp_path: Path) -> None:
    assert GitStateCollector().collect(tmp_path / "nope_missing") == []
    assert GitStateCollector().collect(Path("/no/such/dir_xyz_zzz_qqq")) == []


def test_b08c_path_is_a_regular_file(tmp_path: Path) -> None:
    f = tmp_path / "a_regular_file.txt"
    f.write_text("i am not a directory")
    assert GitStateCollector().collect(f) == []


def test_b08d_git_is_a_file_pointer(tmp_path: Path) -> None:
    # A git-worktree / submodule pointer: .git is a *file*, not a directory.
    d = tmp_path / "worktree_dir"
    d.mkdir()
    (d / ".git").write_text("gitdir: /somewhere/else\n")
    assert GitStateCollector().collect(d) == []


# ===========================================================================
# Behavior 9 -- Child-repo discovery, direct children only
# ===========================================================================


def test_b09_direct_child_repo_surfaced(tmp_path: Path) -> None:
    # Root itself has no .git; a direct child "proj" has a merge in progress.
    child = tmp_path / "proj"
    (child / ".git").mkdir(parents=True)
    (child / ".git" / "MERGE_HEAD").write_text("0123456789abcdef\n")
    signals = GitStateCollector().collect(tmp_path)
    assert len(signals) == 1, f"expected exactly one signal: {_summaries_lower(signals)}"
    s = signals[0]
    _assert_fixed_fields(s, child)
    assert "merge" in (s.summary or "").lower(), f"summary lacks 'merge': {s.summary!r}"


def test_b09_two_levels_deep_not_surfaced(tmp_path: Path) -> None:
    # Root has no .git; R/a has no .git; only R/a/b (two levels deep) is a repo.
    deep = tmp_path / "a" / "b"
    (deep / ".git").mkdir(parents=True)
    (deep / ".git" / "MERGE_HEAD").write_text("0123456789abcdef\n")
    assert GitStateCollector().collect(tmp_path) == []


# ===========================================================================
# Behavior 10 -- Multiple concurrent states in one repo + deterministic order
# ===========================================================================


def test_b10_two_states_emit_two_signals(tmp_path: Path) -> None:
    d = _make_repo(tmp_path, "multi_repo")
    (d / ".git" / "MERGE_HEAD").write_text("0123456789abcdef\n")
    (d / ".git" / "HEAD").write_text("a" * 40 + "\n")  # detached
    signals = GitStateCollector().collect(d)
    assert len(signals) == 2, f"expected two signals: {_summaries_lower(signals)}"
    for s in signals:
        _assert_fixed_fields(s, d)
    lowered = _summaries_lower(signals)
    assert any("merge" in x for x in lowered), f"no merge signal: {lowered}"
    assert any("detached" in x for x in lowered), f"no detached signal: {lowered}"


def test_b10_output_deterministic_sorted_by_summary(tmp_path: Path) -> None:
    d = _make_repo(tmp_path, "multi_repo2")
    (d / ".git" / "MERGE_HEAD").write_text("0123456789abcdef\n")
    (d / ".git" / "HEAD").write_text("a" * 40 + "\n")  # detached
    first = [s.summary for s in GitStateCollector().collect(d)]
    second = [s.summary for s in GitStateCollector().collect(d)]
    # Deterministic across repeated calls.
    assert first == second, f"non-deterministic order: {first!r} vs {second!r}"
    # Sorted by summary ascending.
    assert first == sorted(first), f"not sorted ascending by summary: {first!r}"


# ===========================================================================
# Behavior 11 -- No version bump (additive collector)
# ===========================================================================


def test_b11_no_version_bump() -> None:
    import proactive_loop

    assert proactive_loop.__version__ == "0.1.1"
