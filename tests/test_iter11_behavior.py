"""Black-box behavior tests for iteration 11.

Feature under test: a new **L2 present-state perception signal**, the
``WorkingTreeCollector``. It is the "right now" companion to
``GitActivityCollector`` (which sees only the committed past): it runs
``git status --porcelain`` (plus a purely-local unpushed ahead-count) over
``root`` and each direct-child git repo, and emits one ``ContextSignal``
(``kind == "working_tree"``) per changed path -- tracked modification/staged
change or untracked file -- plus at most one summary signal counting unpushed
local commits. It is stdlib-``subprocess``-only, fully offline (it reads only
the local tracking ref ``@{u}..HEAD`` and NEVER runs ``git fetch``/``ls-remote``
or any network op), deterministic, and (like every collector) degrades to
``[]`` rather than raising on any missing dir/tool/parse error.

ISOLATION CONTRACT (honored): these tests are written strictly against the
public contract -- this iteration's spec "Expected Behaviors" (``pm.md``),
``README.md``, and ``SPEC.md`` section 4.1 (the ``collectors`` module contract)
-- and drive only the documented public surface: the public collector API
``WorkingTreeCollector().collect(root)``, the ``proactive_loop.collectors``
package imports (``WorkingTreeCollector``, ``all_collectors``), the
``proactive_loop.collectors.working_tree`` submodule import, the ``Collector``
protocol from ``proactive_loop.collectors.base``, and the ``ContextSignal``
domain model from ``proactive_loop.models``. **No file under ``src/`` was read,
no engineer/reviewer notes were read, and no ``git diff`` was consulted.**
Signal field names (``source``/``kind``/``summary``/``path``/``weight``/
``detail``) were confirmed only from the public model schema and the existing
published tests (``tests/test_collectors.py``), never from the implementation.
Every git-dependent test builds a REAL temp git repo via ``subprocess`` (exactly
like ``test_collectors.py``) and is ``skipif``-guarded on git availability so
the suite stays green where git is absent; the git-unavailable-degradation test
(Behavior 12) is deliberately *not* guarded -- it IS the git-absent path. Every
test runs under a fresh ``tmp_path`` and is fully offline: zero network (the
"remote" for unpushed-detection is a local ``git init --bare`` repo), zero API
keys.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from proactive_loop.collectors import WorkingTreeCollector, all_collectors
from proactive_loop.collectors.base import Collector
from proactive_loop.collectors.working_tree import (
    WorkingTreeCollector as WorkingTreeCollector_direct,
)
from proactive_loop.models import ContextSignal


# ---------------------------------------------------------------------------
# git availability guard (mirrors tests/test_collectors.py exactly)
# ---------------------------------------------------------------------------


def _git_available() -> bool:
    """Return True if the git executable is accessible."""
    try:
        result = subprocess.run(["git", "--version"], capture_output=True, timeout=5)
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


_GIT = _git_available()
_needs_git = pytest.mark.skipif(not _GIT, reason="git is not available on this system")


# ---------------------------------------------------------------------------
# Helpers -- build real temp git repos via subprocess (offline, deterministic)
# ---------------------------------------------------------------------------


def _git_env() -> dict[str, str]:
    """Deterministic identity + no GPG signing, mirroring test_collectors.py."""
    return {
        **os.environ,
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "t@test.com",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "t@test.com",
    }


def _git(cwd: Path, *args: str) -> None:
    """Run ``git -C cwd <args>`` and raise on failure (test-setup only)."""
    subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True,
        capture_output=True,
        env=_git_env(),
    )


def _init_repo(path: Path, files: list[tuple[str, str]]) -> None:
    """Create a git repo at *path*, committing each (filename, content) file."""
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init", "-b", "main", str(path)],
        check=True,
        capture_output=True,
        env=_git_env(),
    )
    _git(path, "config", "user.email", "t@test.com")
    _git(path, "config", "user.name", "Test")
    _git(path, "config", "commit.gpgsign", "false")
    for fname, content in files:
        (path / fname).write_text(content, encoding="utf-8")
        _git(path, "add", fname)
        _git(path, "commit", "-m", f"add {fname}")


def _modify_tracked(path: Path, fname: str, content: str) -> None:
    """Overwrite an already-committed file, leaving the change UNSTAGED."""
    (path / fname).write_text(content, encoding="utf-8")


def _add_untracked(path: Path, fname: str, content: str = "new = True\n") -> None:
    """Create a brand-new file that git does not yet track."""
    (path / fname).write_text(content, encoding="utf-8")


def _setup_upstream_ahead(work: Path, bare: Path, extra_commits: int) -> None:
    """Give *work* a local (file://) upstream it is ahead of by *extra_commits*.

    Fully offline: the "remote" is a local bare repo. After push, the working
    tree is clean and HEAD is `extra_commits` commits ahead of `@{u}`.
    """
    subprocess.run(
        ["git", "init", "--bare", str(bare)],
        check=True,
        capture_output=True,
        env=_git_env(),
    )
    _git(work, "remote", "add", "origin", str(bare))
    _git(work, "push", "-u", "origin", "main")
    for i in range(extra_commits):
        (work / f"ahead_{i}.py").write_text(f"x = {i}\n", encoding="utf-8")
        _git(work, "add", f"ahead_{i}.py")
        _git(work, "commit", "-m", f"ahead {i}")


def _refs(sig: ContextSignal, name: str) -> bool:
    """True iff *sig* references *name* in its summary, detail, or path."""
    haystacks = (
        sig.summary or "",
        getattr(sig, "detail", "") or "",
        str(getattr(sig, "path", "") or ""),
    )
    return any(name in h for h in haystacks)


def _wt(root: Path, **kwargs) -> list[ContextSignal]:
    """collect() and assert list-of-ContextSignal shape; return the signals."""
    signals = WorkingTreeCollector(**kwargs).collect(root)
    assert isinstance(signals, list)
    for s in signals:
        assert isinstance(s, ContextSignal)
    return signals


# ===========================================================================
# Behavior 1 -- Class shape + dual importability
# ===========================================================================


def test_b01_class_shape_and_defaults() -> None:
    c = WorkingTreeCollector()
    assert c.name == "working_tree"
    assert isinstance(c.max_items, int)
    assert c.max_items == 30


def test_b01_importable_two_ways_same_class() -> None:
    # Package-level and submodule-level imports resolve to the same class object.
    assert WorkingTreeCollector is WorkingTreeCollector_direct
    assert isinstance(WorkingTreeCollector_direct(), WorkingTreeCollector)


# ===========================================================================
# Behavior 2 -- Modified tracked file -> signal referencing that file
# ===========================================================================


@_needs_git
def test_b02_modified_tracked_file_emits_signal(tmp_path: Path) -> None:
    _init_repo(tmp_path, [("alpha.py", "x = 1\n")])
    _modify_tracked(tmp_path, "alpha.py", "x = 2  # edited\n")
    signals = _wt(tmp_path)
    assert signals, "expected at least one working_tree signal for a dirty tree"
    assert any(s.kind == "working_tree" and _refs(s, "alpha.py") for s in signals)


# ===========================================================================
# Behavior 3 -- Untracked file -> signal referencing that file
# ===========================================================================


@_needs_git
def test_b03_untracked_file_emits_signal(tmp_path: Path) -> None:
    _init_repo(tmp_path, [("committed.py", "x = 1\n")])
    _add_untracked(tmp_path, "brand_new.py")
    signals = _wt(tmp_path)
    assert any(s.kind == "working_tree" and _refs(s, "brand_new.py") for s in signals)


# ===========================================================================
# Behavior 4 -- Tracked change weighted strictly above untracked
# ===========================================================================


@_needs_git
def test_b04_tracked_change_outweighs_untracked(tmp_path: Path) -> None:
    _init_repo(tmp_path, [("alpha.py", "x = 1\n")])
    _modify_tracked(tmp_path, "alpha.py", "x = 2\n")   # tracked change (unstaged)
    _add_untracked(tmp_path, "zeta_new.py")            # untracked
    signals = _wt(tmp_path)

    tracked = [s.weight for s in signals if _refs(s, "alpha.py")]
    untracked = [s.weight for s in signals if _refs(s, "zeta_new.py")]
    assert tracked, "no signal referenced the modified tracked file"
    assert untracked, "no signal referenced the untracked file"
    assert max(tracked) > max(untracked)


# ===========================================================================
# Behavior 5 -- Weight invariant: 0.0 < weight <= 1.0 for every signal
# ===========================================================================


@_needs_git
def test_b05_weight_invariant(tmp_path: Path) -> None:
    _init_repo(tmp_path, [("alpha.py", "x = 1\n"), ("beta.py", "y = 1\n")])
    _modify_tracked(tmp_path, "alpha.py", "x = 2\n")
    _add_untracked(tmp_path, "gamma_new.py")
    bare = tmp_path.parent / "bare5.git"
    _setup_upstream_ahead(tmp_path, bare, extra_commits=2)  # also adds a summary signal
    # Re-dirty after the upstream push made the tree clean.
    _modify_tracked(tmp_path, "alpha.py", "x = 3\n")
    _add_untracked(tmp_path, "gamma_new.py")
    signals = _wt(tmp_path)
    assert signals
    for s in signals:
        assert 0.0 < s.weight <= 1.0, f"weight out of range: {s.weight!r}"


# ===========================================================================
# Behavior 6 -- Per-path cap: per-changed-path signals <= max_items
# ===========================================================================


@_needs_git
def test_b06_per_path_cap_respected(tmp_path: Path) -> None:
    # No upstream -> guaranteed NO unpushed-summary signal, so every returned
    # signal is a per-changed-path signal and the cap applies to the total.
    _init_repo(tmp_path, [("committed.py", "x = 1\n")])
    for i in range(5):  # strictly more than max_items=2 changed paths
        _add_untracked(tmp_path, f"extra_{i}.py")
    signals = _wt(tmp_path, max_items=2)
    assert len(signals) <= 2


# ===========================================================================
# Behavior 7 -- Unpushed commits -> exactly one summary signal containing str(K)
# ===========================================================================


@_needs_git
def test_b07_unpushed_commits_summary_signal(tmp_path: Path) -> None:
    work = tmp_path / "work"
    _init_repo(work, [("committed.py", "x = 1\n")])
    bare = tmp_path / "bare7.git"
    K = 3
    _setup_upstream_ahead(work, bare, extra_commits=K)
    # Tree is clean now (all committed); only the unpushed-summary should appear.
    signals = _wt(work)
    with_count = [s for s in signals if s.kind == "working_tree" and str(K) in (s.summary or "")]
    assert len(with_count) == 1, (
        f"expected exactly one unpushed-summary signal containing {K!r}; "
        f"summaries={[s.summary for s in signals]}"
    )


@_needs_git
def test_b07_unpushed_detection_runs_no_network_op(tmp_path: Path, monkeypatch) -> None:
    """The unpushed count MUST come from the local tracking ref only -- collect()
    may NOT invoke `git fetch` / `ls-remote` / `remote update` (SPEC section 5)."""
    work = tmp_path / "work"
    _init_repo(work, [("committed.py", "x = 1\n")])
    bare = tmp_path / "bare7b.git"
    _setup_upstream_ahead(work, bare, extra_commits=2)

    real_run = subprocess.run
    seen_argvs: list[list[str]] = []

    def recording_run(cmd, *args, **kwargs):
        try:
            seen_argvs.append([str(x) for x in cmd])
        except TypeError:
            seen_argvs.append([str(cmd)])
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", recording_run)
    WorkingTreeCollector().collect(work)  # drive the public API under recording

    forbidden = ("fetch", "ls-remote", "remote update", "pull")
    for argv in seen_argvs:
        joined = " ".join(argv)
        for bad in forbidden:
            assert bad not in joined, f"collect() invoked a network git op: {argv}"


# ===========================================================================
# Behavior 8 -- No upstream -> no crash, no unpushed signal
# ===========================================================================


@_needs_git
def test_b08_no_upstream_clean_is_empty(tmp_path: Path) -> None:
    _init_repo(tmp_path, [("committed.py", "x = 1\n")])  # no remote, clean tree
    assert _wt(tmp_path) == []


@_needs_git
def test_b08_no_upstream_dirty_has_no_summary_signal(tmp_path: Path) -> None:
    _init_repo(tmp_path, [("alpha.py", "x = 1\n")])  # no remote configured
    _modify_tracked(tmp_path, "alpha.py", "x = 2\n")
    signals = _wt(tmp_path)  # must not raise
    assert signals, "a dirty tree should still yield per-path signals"
    # Every signal references the one changed path -> no repo-level summary snuck in.
    assert all(_refs(s, "alpha.py") for s in signals), (
        f"an unpushed-summary signal appeared without an upstream: "
        f"{[s.summary for s in signals]}"
    )


# ===========================================================================
# Behavior 9 -- Clean repo -> []
# ===========================================================================


@_needs_git
def test_b09_clean_repo_returns_empty(tmp_path: Path) -> None:
    _init_repo(tmp_path, [("only.py", "x = 1\n")])  # committed, clean, no upstream
    assert WorkingTreeCollector().collect(tmp_path) == []


# ===========================================================================
# Behavior 10 -- Missing directory -> [] (NOT git-guarded; pure)
# ===========================================================================


def test_b10_missing_directory_returns_empty(tmp_path: Path) -> None:
    missing = tmp_path / "no" / "such" / "dir_xyz"
    assert WorkingTreeCollector().collect(missing) == []
    assert WorkingTreeCollector().collect(Path("/no/such/dir_xyz_zzz")) == []


# ===========================================================================
# Behavior 11 -- Non-repo directory -> [] (returns [] with or without git)
# ===========================================================================


def test_b11_non_repo_directory_returns_empty(tmp_path: Path) -> None:
    (tmp_path / "plain.py").write_text("pass\n", encoding="utf-8")
    (tmp_path / "notes.md").write_text("# hi\n", encoding="utf-8")
    assert WorkingTreeCollector().collect(tmp_path) == []


# ===========================================================================
# Behavior 12 -- git unavailable -> [] (deliberately NOT skipif-guarded)
# ===========================================================================


def test_b12_git_unavailable_returns_empty(tmp_path: Path, monkeypatch) -> None:
    # Force a ``.git`` dir so the collector *attempts* a git subprocess call,
    # then make every subprocess invocation behave as if git is not installed.
    (tmp_path / ".git").mkdir()
    (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")

    def boom(*args, **kwargs):
        raise FileNotFoundError("git: command not found")

    monkeypatch.setattr(subprocess, "run", boom)
    # Must swallow FileNotFoundError and degrade to [].
    assert WorkingTreeCollector().collect(tmp_path) == []


# ===========================================================================
# Behavior 13 -- Child-repo scan parity
# ===========================================================================


@_needs_git
def test_b13_child_repo_dirty_tree_surfaces(tmp_path: Path) -> None:
    # root itself is NOT a repo; a direct child dir is a dirty repo.
    assert not (tmp_path / ".git").exists()
    child = tmp_path / "proj"
    _init_repo(child, [("alpha.py", "x = 1\n")])
    _modify_tracked(child, "alpha.py", "x = 2\n")
    _add_untracked(child, "child_new.py")
    signals = _wt(tmp_path)  # scan the PARENT
    assert signals, "child repo's dirty tree should surface from the parent scan"
    assert all(s.kind == "working_tree" for s in signals)
    assert any(_refs(s, "alpha.py") or _refs(s, "child_new.py") for s in signals)


# ===========================================================================
# Behavior 14 -- Kind/source stamp on every signal
# ===========================================================================


@_needs_git
def test_b14_kind_and_source_stamp(tmp_path: Path) -> None:
    work = tmp_path / "work"
    _init_repo(work, [("alpha.py", "x = 1\n")])
    _modify_tracked(work, "alpha.py", "x = 2\n")
    _add_untracked(work, "new_one.py")
    bare = tmp_path / "bare14.git"
    _setup_upstream_ahead(work, bare, extra_commits=1)
    _modify_tracked(work, "alpha.py", "x = 3\n")
    _add_untracked(work, "new_one.py")
    signals = _wt(work)
    assert signals
    for s in signals:
        assert s.kind == "working_tree", f"bad kind: {s.kind!r}"
        assert s.source == "working_tree", f"bad source: {s.source!r}"


# ===========================================================================
# Behavior 15 -- Registry integration (exactly one, independent instances)
# ===========================================================================


def test_b15_registered_exactly_once() -> None:
    collectors = all_collectors()
    by_type = [c for c in collectors if type(c) is WorkingTreeCollector]
    assert len(by_type) == 1
    by_name = [c for c in collectors if getattr(c, "name", None) == "working_tree"]
    assert len(by_name) == 1
    assert by_type[0] is by_name[0]


def test_b15_instances_are_independent_across_calls() -> None:
    def _find(cs):
        return next(c for c in cs if type(c) is WorkingTreeCollector)

    first = _find(all_collectors())
    second = _find(all_collectors())
    assert first is not second


# ===========================================================================
# Behavior 16 -- Protocol / empty-dir safety (regression parity for ALL collectors)
# ===========================================================================


def test_b16_all_collectors_empty_dir_safety(tmp_path: Path) -> None:
    for c in all_collectors():
        signals = c.collect(tmp_path)  # empty dir
        assert isinstance(signals, list)
        for s in signals:
            assert isinstance(s, ContextSignal)
        name = getattr(c, "name", None)
        assert isinstance(name, str) and name  # truthy string
        assert callable(c.collect)


def test_b16_new_collector_conforms_to_protocol() -> None:
    assert isinstance(WorkingTreeCollector(), Collector)
