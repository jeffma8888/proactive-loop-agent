"""Black-box oracle for iteration 430 (foundry iter 313): ``git_activity`` and
``working_tree`` stop spawning ``git`` against a workspace ROOT that cannot be
inside a repository.

Spec: ``state/iter-430/pm.md``, Expected Behaviors 1-9. The shared pure-pathlib
precheck ``_may_be_inside_repo(path) -> bool`` lives in ``git_activity`` and is
imported by ``working_tree``; it is consulted ONLY for the workspace root, so a
plain directory pays zero child processes for the ``[]`` the perception layer
already promised (SPEC 4.1), while direct children keep today's ``.git``-gated
spawn and a real repository keeps every signal it emitted before.

Everything here is offline. Behaviors 7-9 run a LOCAL ``git init`` in
``tmp_path`` with the developer's global/system config masked (the convention of
``tests/test_iter139_behavior.py``); behaviors 5-6 stub ``subprocess.run`` and
never reach a ``git`` binary at all. The three discovery variables are cleared by
an autouse fixture so no test depends on ambient shell state.
"""

from __future__ import annotations

import os
import subprocess
import types
from pathlib import Path
from typing import Any, Final

import pytest

import proactive_loop.collectors.git_activity as git_activity
import proactive_loop.collectors.working_tree as working_tree
from proactive_loop.collectors import GitActivityCollector, WorkingTreeCollector
from proactive_loop.collectors.git_activity import _may_be_inside_repo
from proactive_loop.models import ContextSignal

# The three variables under which git discovers a repository without a ``.git``
# in the walked tree (behavior 2). Cleared for every test by ``_clear_git_env``.
DISCOVERY_VARS: Final[tuple[str, ...]] = ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR")

# Both root-scanning git collectors share the precheck; behaviors 5, 6 and 8
# assert each one independently.
COLLECTORS: Final[tuple[type, ...]] = (GitActivityCollector, WorkingTreeCollector)

_REAL_RUN: Final = subprocess.run


@pytest.fixture(autouse=True)
def _clear_git_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """No behavior may inherit a ``GIT_DIR``-style override from the shell."""
    for name in DISCOVERY_VARS:
        monkeypatch.delenv(name, raising=False)


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------
def _plain_root(tmp_path: Path) -> Path:
    """A fresh directory with a little content and NO repository marker anywhere."""
    root = tmp_path / "plain"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "mod.py").write_text("x = 1\n", encoding="utf-8")
    (root / "README.md").write_text("# plain\n", encoding="utf-8")
    return root


def _recording_stub(calls: list[list[str]]) -> Any:
    """A ``subprocess.run`` stand-in that records argv and answers like a quiet git."""

    def _fake_run(cmd: Any, *args: Any, **kwargs: Any) -> Any:
        calls.append([str(part) for part in cmd])
        return types.SimpleNamespace(returncode=0, stdout="")

    return _fake_run


def _recording_passthrough(calls: list[list[str]]) -> Any:
    """A ``subprocess.run`` wrapper that records argv, then runs the REAL child."""

    def _wrapper(cmd: Any, *args: Any, **kwargs: Any) -> Any:
        calls.append([str(part) for part in cmd])
        return _REAL_RUN(cmd, *args, **kwargs)

    return _wrapper


def _c_targets(calls: list[list[str]]) -> list[str]:
    """The ``-C <dir>`` operand of every recorded git invocation."""
    return [argv[argv.index("-C") + 1] for argv in calls if "-C" in argv]


def _git_env() -> dict[str, str]:
    """Deterministic identity; a git blind to the developer's global/system config."""
    return {
        **os.environ,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@x",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@x",
        "GIT_TERMINAL_PROMPT": "0",
    }


def _git(cwd: Path, *args: str) -> str:
    result = _REAL_RUN(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        env=_git_env(),
        timeout=30,
    )
    assert result.returncode == 0, (
        f"test setup `git {' '.join(args)}` failed rc={result.returncode}: "
        f"{result.stderr.strip()!r}"
    )
    return result.stdout


def _committed_repo(root: Path, rel: str = "sub/note.txt") -> Path:
    """``git init`` *root* offline and commit ONE file at *rel*; returns its parent."""
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("one\n", encoding="utf-8")
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "-c", "commit.gpgsign=false", "commit", "-qm", "init")
    return target.parent


def _shape(signals: list[ContextSignal]) -> list[tuple[str, str, str | None]]:
    return sorted((s.kind, s.summary, None if s.path is None else str(s.path)) for s in signals)


# ===========================================================================
# Behavior 1 -- a ``.git`` child (directory OR file) on the path or ANY ancestor
# means "may be inside a repo"; no subprocess is involved in deciding.
# ===========================================================================
def test_b01_dot_git_dir_or_file_on_any_ancestor_means_may_be_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _no_spawn(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError(f"the precheck must not spawn; got subprocess.run{args!r}")

    monkeypatch.setattr(subprocess, "run", _no_spawn)

    with_dir = tmp_path / "with_dir"
    (with_dir / ".git").mkdir(parents=True)
    deep = with_dir / "a" / "b" / "c"
    deep.mkdir(parents=True)
    assert _may_be_inside_repo(with_dir) is True, "a .git DIRECTORY on p itself"
    assert _may_be_inside_repo(deep) is True, "a .git DIRECTORY three ancestors up"

    with_file = tmp_path / "with_file"
    with_file.mkdir()
    (with_file / ".git").write_text("gitdir: /elsewhere/.git/worktrees/x\n", encoding="utf-8")
    leaf = with_file / "pkg"
    leaf.mkdir()
    assert _may_be_inside_repo(with_file) is True, "a .git FILE (worktree/submodule) on p"
    assert _may_be_inside_repo(leaf) is True, "a .git FILE on p's parent"


# ===========================================================================
# Behavior 2 -- any of GIT_DIR / GIT_WORK_TREE / GIT_COMMON_DIR set NON-EMPTY
# wins regardless of the tree; an empty value does not.
# ===========================================================================
def test_b02_each_discovery_variable_alone_means_may_be_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _plain_root(tmp_path)
    assert _may_be_inside_repo(root) is False, "precondition: the bare tree says no"
    for name in DISCOVERY_VARS:
        for other in DISCOVERY_VARS:
            monkeypatch.delenv(other, raising=False)
        monkeypatch.setenv(name, str(tmp_path / "elsewhere.git"))
        assert _may_be_inside_repo(root) is True, f"{name} set non-empty must win"
        monkeypatch.setenv(name, "")
        assert _may_be_inside_repo(root) is False, f"{name} set EMPTY must not count"


# ===========================================================================
# Behavior 3 -- the bare-repo layout (HEAD file + objects/ + refs/) on p itself.
# ===========================================================================
def test_b03_bare_repo_layout_means_may_be_repo_and_needs_all_three(tmp_path: Path) -> None:
    bare = tmp_path / "bare.git"
    (bare / "objects").mkdir(parents=True)
    (bare / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    assert _may_be_inside_repo(bare) is False, "HEAD + objects/ without refs/ is not the layout"
    (bare / "refs").mkdir()
    assert _may_be_inside_repo(bare) is True, "HEAD file + objects/ + refs/ is a bare repo"
    (bare / "HEAD").unlink()
    (bare / "HEAD").mkdir()
    assert _may_be_inside_repo(bare) is False, "HEAD must be a FILE, not a directory"


# ===========================================================================
# Behavior 4 -- a fresh tmp_path subtree with none of the above says False.
# ===========================================================================
def test_b04_fresh_tmp_subdir_cannot_be_inside_repo(tmp_path: Path) -> None:
    root = _plain_root(tmp_path)
    assert _may_be_inside_repo(root) is False
    assert _may_be_inside_repo(root / "pkg") is False, "nor any nested plain directory"
    assert _may_be_inside_repo(root / "does-not-exist") is False, "a missing path is not a repo"


# ===========================================================================
# Behavior 5 -- on such a root BOTH collectors spawn nothing and return [].
# ===========================================================================
@pytest.mark.parametrize("collector_cls", COLLECTORS, ids=lambda c: c.__name__)
def test_b05_non_repo_root_spawns_zero_children_and_returns_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, collector_cls: type
) -> None:
    root = _plain_root(tmp_path)
    calls: list[list[str]] = []
    monkeypatch.setattr(subprocess, "run", _recording_stub(calls))
    signals = collector_cls().collect(root)
    assert signals == [], f"a non-repo root must yield []; got {signals!r}"
    assert calls == [], f"a non-repo root must spawn NO child process; got {calls!r}"


# ===========================================================================
# Behavior 6 -- a direct child with ``.git/`` still gets exactly ONE spawn,
# addressed at the child and never at the root.
# ===========================================================================
@pytest.mark.parametrize("collector_cls", COLLECTORS, ids=lambda c: c.__name__)
def test_b06_child_with_dot_git_gets_exactly_one_spawn_addressed_at_the_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, collector_cls: type
) -> None:
    root = _plain_root(tmp_path)
    child = root / "child"
    (child / ".git").mkdir(parents=True)
    calls: list[list[str]] = []
    monkeypatch.setattr(subprocess, "run", _recording_stub(calls))
    collector_cls().collect(root)
    targets = _c_targets(calls)
    assert len(calls) == 1, f"exactly one child process for one marked child; got {calls!r}"
    assert targets == [str(child)], f"the spawn must target -C {child}; got {calls!r}"
    assert str(root) not in targets, f"the root must not be spawned against; got {calls!r}"


# ===========================================================================
# Behavior 7 -- a root that is a SUBDIRECTORY of a real repo still yields
# git_commit signals: ancestor discovery is preserved.
# ===========================================================================
def test_b07_subdirectory_of_a_real_repo_still_yields_git_commit_signals(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    sub = _committed_repo(repo, "sub/note.txt")
    assert not (sub / ".git").exists(), "precondition: the root itself carries no .git"
    assert _may_be_inside_repo(sub) is True, "the ancestor's .git must be discovered"
    signals = GitActivityCollector().collect(sub)
    kinds = [s.kind for s in signals]
    assert "git_commit" in kinds, (
        f"a committed ancestor repo must surface git_commit from a subdirectory root; "
        f"got kinds {kinds!r}"
    )


# ===========================================================================
# Behavior 8 -- a fake ``.git`` DIRECTORY full of junk still spawns (git itself
# decides) and still returns []: identical to HEAD, so test_iter192's
# CHILD_PROCESS_BUDGET == 2 non-vacuity stays true.
# ===========================================================================
def test_b08_junk_dot_git_directory_still_spawns_once_per_collector_and_returns_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _plain_root(tmp_path)
    (root / ".git").mkdir()
    (root / ".git" / "pruned.py").write_text("def g(:\n", encoding="utf-8")
    (root / ".git" / "pruned.md").write_text("- TODO: pruned todo\n", encoding="utf-8")
    calls: list[list[str]] = []
    monkeypatch.setattr(subprocess, "run", _recording_passthrough(calls))
    per_collector: dict[str, int] = {}
    for collector_cls in COLLECTORS:
        before = len(calls)
        signals = collector_cls().collect(root)
        assert signals == [], f"{collector_cls.__name__}: junk .git must still yield []"
        per_collector[collector_cls.__name__] = len(calls) - before
    assert per_collector == {c.__name__: 1 for c in COLLECTORS}, (
        f"each collector must still spawn exactly once against a junk .git root; "
        f"got {per_collector!r} from {calls!r}"
    )
    assert set(_c_targets(calls)) == {str(root)}, f"every spawn targets the root; got {calls!r}"


# ===========================================================================
# Behavior 9 -- signal parity on a real single-repo workspace: the precheck
# changes nothing a collector emits.
# ===========================================================================
def test_b09_real_repo_signals_are_identical_with_and_without_the_precheck(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    _committed_repo(repo, "pkg/mod.py")
    (repo / "pkg" / "mod.py").write_text("one\ntwo\n", encoding="utf-8")
    (repo / "pkg" / "brand_new.py").write_text("n = 1\n", encoding="utf-8")

    guarded = {c.__name__: _shape(c().collect(repo)) for c in COLLECTORS}
    assert guarded["GitActivityCollector"], "precondition: the repo must emit git activity"
    assert guarded["WorkingTreeCollector"], "precondition: the dirty tree must emit signals"

    assert working_tree._may_be_inside_repo is git_activity._may_be_inside_repo, (
        "the precheck must be defined once in git_activity and imported by working_tree"
    )
    monkeypatch.setattr(git_activity, "_may_be_inside_repo", lambda p: True)
    monkeypatch.setattr(working_tree, "_may_be_inside_repo", lambda p: True)
    unguarded = {c.__name__: _shape(c().collect(repo)) for c in COLLECTORS}

    assert guarded == unguarded, (
        "the root precheck must not change any (kind, summary, path) a collector emits "
        f"on a real repository; guarded={guarded!r} unguarded={unguarded!r}"
    )
