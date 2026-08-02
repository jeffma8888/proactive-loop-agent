"""Tests for the collectors package.

Coverage:
- RecentFilesCollector: finds recent files, skips hidden/noise dirs, respects max_files.
- GitActivityCollector: real temp git repo (skipped if git unavailable), missing-repo degrades.
- TodoCollector: finds TODO/FIXME/XXX and markdown checkboxes, respects max_items.
- NotesCollector: finds headings + paragraphs under notes/journal/docs dirs.
- Graceful degradation (registry-driven): EVERY collector in all_collectors()
  returns [] / a list (never raises) on nonexistent, file-as-root, empty, and
  hostile undecodable-content roots -- proving the SPEC §4.1 invariant for all 15
  collectors and auto-covering any future one with zero test edits.
- all_collectors(): the registry exposes EXACTLY the 15 documented collector types.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from proactive_loop.collectors import (
    CiConfigCollector,
    DependencyCollector,
    GitActivityCollector,
    GitStateCollector,
    GitStashCollector,
    LargeFileCollector,
    LockfileDriftCollector,
    MergeConflictCollector,
    NotesCollector,
    RecentFilesCollector,
    SecretFileCollector,
    SyntaxErrorCollector,
    # Aliased so the module-level name is NOT 'Test*': pytest's collection
    # heuristic would otherwise try to collect the collector class itself as a
    # test case and emit a PytestCollectionWarning (same trick as test_iter16_*).
    TestPostureCollector as PostureCollector,
    TodoCollector,
    WorkingTreeCollector,
    all_collectors,
)
from proactive_loop.collectors.base import Collector
from proactive_loop.models import ContextSignal


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _git_available() -> bool:
    """Return True if the git executable is accessible."""
    try:
        result = subprocess.run(
            ["git", "--version"], capture_output=True, timeout=5
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


def _touch_file(path: Path, content: str = "", *, mtime_offset_sec: float = 0.0) -> Path:
    """Write *content* to *path* and optionally adjust its mtime."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if mtime_offset_sec:
        new_mtime = time.time() + mtime_offset_sec
        os.utime(path, (new_mtime, new_mtime))
    return path


# ---------------------------------------------------------------------------
# Registry-driven never-raise proof (SPEC §4.1)
# ---------------------------------------------------------------------------
#
# The SPEC §4.1 invariant -- every collector is pure stdlib + deterministic and
# NEVER raises on a missing dir / hostile input, degrading to [] -- is the core
# "resilient by design" thesis. Driving the graceful-degradation proof from
# all_collectors() (rather than a hardcoded subset) means every present AND
# future collector is proven automatically, so the proof can never rot: add a
# collector to the registry and it is covered here with zero test edits.
_ALL_COLLECTOR_PARAMS = [pytest.param(c, id=c.name) for c in all_collectors()]

# The 15 collectors documented in SPEC §4.1. Asserting the full name-SET (not a
# subset, not a bare count) catches BOTH a collector silently dropped from the
# registry and a documented collector missing from it.
_DOCUMENTED_COLLECTOR_NAMES = frozenset(
    {
        "ci_config",
        "lockfile_drift",
        "recent_files",
        "git_activity",
        "git_state",
        "todos",
        "notes",
        "dependencies",
        "working_tree",
        "test_posture",
        "merge_conflict",
        "large_file",
        "secret_file",
        "git_stash",
        "syntax_error",
    }
)
_EXPORTED_COLLECTOR_CLASSES = frozenset(
    {
        CiConfigCollector,
        LockfileDriftCollector,
        RecentFilesCollector,
        GitActivityCollector,
        GitStateCollector,
        GitStashCollector,
        TodoCollector,
        NotesCollector,
        DependencyCollector,
        WorkingTreeCollector,
        PostureCollector,
        MergeConflictCollector,
        LargeFileCollector,
        SecretFileCollector,
        SyntaxErrorCollector,
    }
)


def _build_hostile_tree(root: Path) -> None:
    """Populate *root* with a realistic 'never-raise' stressor tree.

    WHY these six ingredients: the existing empty/nonexistent cases never touch
    the CONTENT-scanning collectors on undecodable input. This tree forces every
    parse/decode path -- UTF-8 text decode, tomllib, json, and conflict-marker
    scanning -- to face bytes it cannot decode or parse, which is exactly where a
    naive collector would raise instead of degrading to a list.
    """
    (root / "a" / "b" / "c" / "d").mkdir(parents=True)
    # Zero-byte file with a scanned extension.
    (root / "empty.md").write_bytes(b"")
    # A scanned SOURCE file whose bytes are not valid UTF-8.
    (root / "junk.py").write_bytes(b"\xff\xfe\x00\x01 TODO garbage \x80\x81")
    # Invalid, non-UTF-8 pyproject.toml -- stresses DependencyCollector's TOML parse.
    (root / "pyproject.toml").write_bytes(b"\xff\xfe not toml \x00")
    # Invalid package.json with garbage bytes -- stresses the JSON parse.
    (root / "package.json").write_bytes(b"\x00\x01\x02 no")
    # Committed conflict-marker file -- stresses MergeConflictCollector.
    (root / "conflict.py").write_text(
        "x = 1\n<<<<<<< HEAD\na\n=======\nb\n>>>>>>> other\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# RecentFilesCollector
# ---------------------------------------------------------------------------


class TestRecentFilesCollector:
    def test_finds_recent_files(self, tmp_path: Path) -> None:
        """A file modified within within_days should produce a signal."""
        _touch_file(tmp_path / "work.py", "print('hi')")
        collector = RecentFilesCollector(within_days=14)
        signals = collector.collect(tmp_path)
        assert len(signals) >= 1
        kinds = {s.kind for s in signals}
        assert kinds == {"recent_file"}

    def test_skips_old_files(self, tmp_path: Path) -> None:
        """A file older than within_days should be excluded."""
        old_file = _touch_file(
            tmp_path / "old.py",
            "x = 1",
            mtime_offset_sec=-(20 * 86_400),  # 20 days ago
        )
        assert old_file.exists()
        collector = RecentFilesCollector(within_days=14)
        signals = collector.collect(tmp_path)
        paths = [s.path for s in signals]
        assert "old.py" not in paths

    def test_skips_hidden_files(self, tmp_path: Path) -> None:
        """Files starting with '.' should be ignored."""
        _touch_file(tmp_path / ".hidden.py", "secret = True")
        _touch_file(tmp_path / "visible.py", "public = True")
        collector = RecentFilesCollector()
        signals = collector.collect(tmp_path)
        paths = [s.path for s in signals]
        assert not any(p.startswith(".") for p in paths if p)

    def test_skips_node_modules(self, tmp_path: Path) -> None:
        """node_modules directory should be pruned from the walk."""
        noise_file = _touch_file(tmp_path / "node_modules" / "lib.js", "// noise")
        app_file = _touch_file(tmp_path / "app.js", "console.log('hi')")
        collector = RecentFilesCollector()
        signals = collector.collect(tmp_path)
        paths = [s.path or "" for s in signals]
        # The file INSIDE node_modules should NOT be collected
        assert str(noise_file) not in paths
        assert str(noise_file.resolve()) not in paths
        # The app.js outside node_modules SHOULD be collected
        collected = {str(p) for p in paths}
        assert str(app_file) in collected or str(app_file.resolve()) in collected

    def test_skips_venv(self, tmp_path: Path) -> None:
        """`.venv` directory should be pruned."""
        _touch_file(tmp_path / ".venv" / "bin" / "python", "#!/usr/bin/env python")
        _touch_file(tmp_path / "main.py", "pass")
        collector = RecentFilesCollector()
        signals = collector.collect(tmp_path)
        paths = [s.path or "" for s in signals]
        assert not any(".venv" in p for p in paths)

    def test_respects_max_files(self, tmp_path: Path) -> None:
        """Number of signals must not exceed max_files."""
        for i in range(30):
            _touch_file(tmp_path / f"file_{i:02d}.py", f"x = {i}")
        collector = RecentFilesCollector(max_files=5)
        signals = collector.collect(tmp_path)
        assert len(signals) <= 5

    def test_weight_between_zero_and_one(self, tmp_path: Path) -> None:
        """All signal weights must be in [0, 1]."""
        _touch_file(tmp_path / "a.py", "pass")
        collector = RecentFilesCollector()
        signals = collector.collect(tmp_path)
        for sig in signals:
            assert 0.0 <= sig.weight <= 1.0

    def test_missing_directory_returns_empty(self, tmp_path: Path) -> None:
        """Collector must return [] for a directory that doesn't exist."""
        collector = RecentFilesCollector()
        signals = collector.collect(tmp_path / "nonexistent")
        assert signals == []

    def test_empty_directory_returns_empty(self, tmp_path: Path) -> None:
        """An empty directory should produce no signals."""
        collector = RecentFilesCollector()
        signals = collector.collect(tmp_path)
        assert signals == []

    def test_source_name(self, tmp_path: Path) -> None:
        """All signals should carry the collector's name as source."""
        _touch_file(tmp_path / "f.py", "pass")
        collector = RecentFilesCollector(name="recent_files")
        for sig in collector.collect(tmp_path):
            assert sig.source == "recent_files"


# ---------------------------------------------------------------------------
# GitActivityCollector
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _git_available(), reason="git is not available on this system")
class TestGitActivityCollector:
    def _init_repo(self, path: Path, commits: list[tuple[str, str]]) -> None:
        """Create a git repo at *path* with the given (filename, content) commits."""
        env = {**os.environ, "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "t@test.com",
               "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "t@test.com"}
        subprocess.run(["git", "init", "-b", "main", str(path)], check=True,
                       capture_output=True, env=env)
        subprocess.run(["git", "-C", str(path), "config", "user.email", "t@test.com"],
                       check=True, capture_output=True, env=env)
        subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"],
                       check=True, capture_output=True, env=env)
        for fname, content in commits:
            fpath = path / fname
            fpath.write_text(content, encoding="utf-8")
            subprocess.run(["git", "-C", str(path), "add", fname],
                           check=True, capture_output=True, env=env)
            subprocess.run(["git", "-C", str(path), "commit", "-m", f"add {fname}"],
                           check=True, capture_output=True, env=env)

    def test_finds_commits_in_root_repo(self, tmp_path: Path) -> None:
        """Commits in a root-level repo should produce git_commit signals."""
        self._init_repo(tmp_path, [("hello.py", "print('hello')"),
                                    ("world.py", "print('world')")])
        collector = GitActivityCollector(max_commits=15)
        signals = collector.collect(tmp_path)
        assert len(signals) >= 1
        assert all(s.kind == "git_commit" for s in signals)

    def test_finds_commits_in_child_repo(self, tmp_path: Path) -> None:
        """Commits in a direct child directory repo should also surface."""
        child = tmp_path / "sub_project"
        child.mkdir()
        self._init_repo(child, [("main.py", "x = 1")])
        collector = GitActivityCollector(max_commits=15)
        signals = collector.collect(tmp_path)
        assert len(signals) >= 1

    def test_respects_max_commits(self, tmp_path: Path) -> None:
        """Number of signals must not exceed max_commits."""
        self._init_repo(
            tmp_path,
            [(f"f{i}.py", f"x = {i}") for i in range(10)],
        )
        collector = GitActivityCollector(max_commits=3)
        signals = collector.collect(tmp_path)
        assert len(signals) <= 3

    def test_signal_fields(self, tmp_path: Path) -> None:
        """Each signal must have non-empty summary and correct kind."""
        self._init_repo(tmp_path, [("a.py", "pass")])
        collector = GitActivityCollector()
        for sig in collector.collect(tmp_path):
            assert sig.kind == "git_commit"
            assert sig.summary
            assert sig.source == "git_activity"

    def test_no_double_count_across_dirs(self, tmp_path: Path) -> None:
        """Commits should not be duplicated even if root and child both found."""
        # The root itself is not a repo; only the child is.
        child = tmp_path / "proj"
        child.mkdir()
        self._init_repo(child, [("a.py", "pass"), ("b.py", "pass")])
        collector = GitActivityCollector(max_commits=15)
        signals = collector.collect(tmp_path)
        summaries = [s.summary for s in signals]
        assert len(summaries) == len(set(summaries))


class TestGitActivityCollectorDegradation:
    """These tests run regardless of git availability."""

    def test_missing_directory_returns_empty(self, tmp_path: Path) -> None:
        collector = GitActivityCollector()
        assert collector.collect(tmp_path / "ghost") == []

    def test_non_repo_returns_empty(self, tmp_path: Path) -> None:
        """A plain directory (no .git) should return []."""
        (tmp_path / "plain.py").write_text("pass")
        collector = GitActivityCollector()
        signals = collector.collect(tmp_path)
        # Either [] (non-repo) or valid signals (if tmp_path is inside a repo at test time).
        # We can only assert the type.
        assert isinstance(signals, list)

    def test_empty_directory_returns_empty(self, tmp_path: Path) -> None:
        collector = GitActivityCollector()
        signals = collector.collect(tmp_path)
        assert isinstance(signals, list)


# ---------------------------------------------------------------------------
# TodoCollector
# ---------------------------------------------------------------------------


class TestTodoCollector:
    def test_finds_todo_comment_in_python(self, tmp_path: Path) -> None:
        _touch_file(tmp_path / "app.py", "# TODO: refactor this function\nx = 1\n")
        collector = TodoCollector()
        signals = collector.collect(tmp_path)
        assert any("refactor this function" in s.summary for s in signals)

    def test_finds_fixme_comment(self, tmp_path: Path) -> None:
        _touch_file(tmp_path / "lib.py", "def foo():\n    # FIXME: this is broken\n    pass\n")
        collector = TodoCollector()
        signals = collector.collect(tmp_path)
        assert any("broken" in s.summary for s in signals)

    def test_finds_xxx_comment(self, tmp_path: Path) -> None:
        _touch_file(tmp_path / "util.js", "// XXX: legacy hack\n")
        collector = TodoCollector()
        signals = collector.collect(tmp_path)
        assert any("legacy hack" in s.summary for s in signals)

    def test_finds_markdown_checkbox(self, tmp_path: Path) -> None:
        _touch_file(
            tmp_path / "tasks.md",
            "# Tasks\n\n- [ ] Write unit tests\n- [x] Done already\n",
        )
        collector = TodoCollector()
        signals = collector.collect(tmp_path)
        assert any("Write unit tests" in s.summary for s in signals)

    def test_checked_checkbox_ignored(self, tmp_path: Path) -> None:
        """A `- [x]` checkbox should NOT be treated as a todo."""
        _touch_file(tmp_path / "done.md", "- [x] Already finished\n")
        collector = TodoCollector()
        signals = collector.collect(tmp_path)
        assert not any("Already finished" in s.summary for s in signals)

    def test_scans_ts_and_md_extensions(self, tmp_path: Path) -> None:
        _touch_file(tmp_path / "component.ts", "// TODO: add types\n")
        _touch_file(tmp_path / "notes.md", "<!-- TODO: update docs -->\n")
        collector = TodoCollector()
        signals = collector.collect(tmp_path)
        assert len(signals) >= 2

    def test_skips_unsupported_extensions(self, tmp_path: Path) -> None:
        """Files with extensions not in the scan set should be ignored."""
        _touch_file(tmp_path / "data.csv", "TODO: not a code file\n")
        collector = TodoCollector()
        signals = collector.collect(tmp_path)
        assert signals == []

    def test_respects_max_items(self, tmp_path: Path) -> None:
        lines = "\n".join(f"# TODO: item {i}" for i in range(50))
        _touch_file(tmp_path / "big.py", lines)
        collector = TodoCollector(max_items=5)
        signals = collector.collect(tmp_path)
        assert len(signals) <= 5

    def test_kind_is_todo(self, tmp_path: Path) -> None:
        _touch_file(tmp_path / "a.py", "# TODO: check this\n")
        collector = TodoCollector()
        for sig in collector.collect(tmp_path):
            assert sig.kind == "todo"

    def test_source_name(self, tmp_path: Path) -> None:
        _touch_file(tmp_path / "a.py", "# TODO: check\n")
        collector = TodoCollector(name="todos")
        for sig in collector.collect(tmp_path):
            assert sig.source == "todos"

    def test_missing_directory_returns_empty(self, tmp_path: Path) -> None:
        collector = TodoCollector()
        assert collector.collect(tmp_path / "ghost") == []

    def test_empty_directory_returns_empty(self, tmp_path: Path) -> None:
        collector = TodoCollector()
        assert collector.collect(tmp_path) == []

    def test_path_field_contains_filename(self, tmp_path: Path) -> None:
        """The signal path should contain the source filename."""
        _touch_file(tmp_path / "src.py", "# TODO: needs work\n")
        collector = TodoCollector()
        signals = collector.collect(tmp_path)
        assert any("src.py" in (s.path or "") for s in signals)


# ---------------------------------------------------------------------------
# NotesCollector
# ---------------------------------------------------------------------------


class TestNotesCollector:
    def test_finds_headings_under_notes_dir(self, tmp_path: Path) -> None:
        notes_dir = tmp_path / "notes"
        notes_dir.mkdir()
        _touch_file(
            notes_dir / "journal.md",
            "# Learning Plans\n\nStarting a new course this week.\n\n## Day 1\n\nReview basics.\n",
        )
        collector = NotesCollector()
        signals = collector.collect(tmp_path)
        summaries = [s.summary for s in signals]
        assert "Learning Plans" in summaries

    def test_finds_headings_under_journal_dir(self, tmp_path: Path) -> None:
        journal = tmp_path / "journal"
        journal.mkdir()
        _touch_file(journal / "week.md", "# Weekly Review\n\nGot a lot done.\n")
        collector = NotesCollector()
        signals = collector.collect(tmp_path)
        assert any("Weekly Review" in s.summary for s in signals)

    def test_finds_headings_under_docs_dir(self, tmp_path: Path) -> None:
        docs = tmp_path / "docs"
        docs.mkdir()
        _touch_file(docs / "guide.md", "# Getting Started\n\nInstall dependencies.\n")
        collector = NotesCollector()
        signals = collector.collect(tmp_path)
        assert any("Getting Started" in s.summary for s in signals)

    def test_ignores_md_outside_notes_dirs(self, tmp_path: Path) -> None:
        """Markdown files not under notes/journal/docs should be ignored."""
        _touch_file(tmp_path / "README.md", "# Project README\n\nSome content.\n")
        collector = NotesCollector()
        signals = collector.collect(tmp_path)
        assert signals == []

    def test_first_paragraph_in_detail(self, tmp_path: Path) -> None:
        notes_dir = tmp_path / "notes"
        notes_dir.mkdir()
        _touch_file(
            notes_dir / "note.md",
            "# Topic\n\nThis is the first paragraph.\n\nThis is the second.\n",
        )
        collector = NotesCollector()
        signals = collector.collect(tmp_path)
        heading_sig = next((s for s in signals if s.summary == "Topic"), None)
        assert heading_sig is not None
        assert "first paragraph" in heading_sig.detail

    def test_respects_max_items(self, tmp_path: Path) -> None:
        notes_dir = tmp_path / "notes"
        notes_dir.mkdir()
        headings = "\n\n".join(f"# Heading {i}\n\nContent {i}." for i in range(50))
        _touch_file(notes_dir / "big.md", headings)
        collector = NotesCollector(max_items=5)
        signals = collector.collect(tmp_path)
        assert len(signals) <= 5

    def test_kind_is_note(self, tmp_path: Path) -> None:
        notes_dir = tmp_path / "notes"
        notes_dir.mkdir()
        _touch_file(notes_dir / "n.md", "# Title\n\nBody.\n")
        collector = NotesCollector()
        for sig in collector.collect(tmp_path):
            assert sig.kind == "note"

    def test_source_name(self, tmp_path: Path) -> None:
        notes_dir = tmp_path / "notes"
        notes_dir.mkdir()
        _touch_file(notes_dir / "n.md", "# Title\n\nBody.\n")
        collector = NotesCollector(name="notes")
        for sig in collector.collect(tmp_path):
            assert sig.source == "notes"

    def test_missing_directory_returns_empty(self, tmp_path: Path) -> None:
        collector = NotesCollector()
        assert collector.collect(tmp_path / "ghost") == []

    def test_empty_directory_returns_empty(self, tmp_path: Path) -> None:
        collector = NotesCollector()
        assert collector.collect(tmp_path) == []

    def test_no_notes_dirs_returns_empty(self, tmp_path: Path) -> None:
        """When there are no notes/journal/docs dirs, result should be []."""
        src = tmp_path / "src"
        src.mkdir()
        _touch_file(src / "code.py", "# TODO: something\n")
        collector = NotesCollector()
        assert collector.collect(tmp_path) == []

    def test_subheadings_captured(self, tmp_path: Path) -> None:
        """Both top-level and sub-level headings should produce signals."""
        notes_dir = tmp_path / "notes"
        notes_dir.mkdir()
        _touch_file(
            notes_dir / "multi.md",
            "# Top\n\nIntro.\n\n## Sub\n\nDetails here.\n",
        )
        collector = NotesCollector()
        signals = collector.collect(tmp_path)
        summaries = {s.summary for s in signals}
        assert "Top" in summaries
        assert "Sub" in summaries


# ---------------------------------------------------------------------------
# all_collectors() registry
# ---------------------------------------------------------------------------


class TestAllCollectors:
    def test_registry_covers_all_collector_types(self) -> None:
        """The registry must expose EXACTLY the 15 documented collectors (SPEC §4.1).

        WHY a full-set check (not the old 4-type subset, and not a bare count): a
        SUBSET check silently passes when a collector is dropped from the registry,
        and a COUNT check passes when one collector is swapped for a duplicate of
        another. Asserting both the exact name-set and the exact type-set catches a
        documented collector missing from the registry AND an undocumented one
        sneaking in.
        """
        collectors = all_collectors()
        assert {c.name for c in collectors} == _DOCUMENTED_COLLECTOR_NAMES
        assert {type(c) for c in collectors} == _EXPORTED_COLLECTOR_CLASSES

    def test_each_has_name_attribute(self) -> None:
        for c in all_collectors():
            assert isinstance(c.name, str)
            assert c.name

    def test_each_satisfies_collector_protocol(self) -> None:
        """Every collector must implement the Collector protocol."""
        for c in all_collectors():
            assert hasattr(c, "name")
            assert callable(getattr(c, "collect", None))

    def test_collect_returns_list_of_context_signals(self, tmp_path: Path) -> None:
        """Each collector should return a list of ContextSignal on an empty dir."""
        for c in all_collectors():
            result = c.collect(tmp_path)
            assert isinstance(result, list)
            for item in result:
                assert isinstance(item, ContextSignal)

    def test_returns_new_instances_each_call(self) -> None:
        """Each call should return independent instances (not singletons)."""
        c1 = all_collectors()
        c2 = all_collectors()
        assert c1 is not c2


# ---------------------------------------------------------------------------
# Graceful degradation (cross-cutting)
# ---------------------------------------------------------------------------


class TestGracefulDegradation:
    """Prove the SPEC §4.1 never-raise invariant for EVERY registered collector.

    Every test here is parametrized from _ALL_COLLECTOR_PARAMS (built from
    all_collectors()), so all 15 current collectors -- and any future one -- are
    covered with zero test edits. If a collector unexpectedly raises, that is a
    real §4.1 violation to FIX in the collector, not to exempt here.
    """

    @pytest.mark.parametrize("collector", _ALL_COLLECTOR_PARAMS)
    def test_nonexistent_root_returns_empty(
        self, collector: Collector, tmp_path: Path
    ) -> None:
        """A path that does not exist must degrade to exactly [] (not raise)."""
        signals = collector.collect(tmp_path / "does_not_exist")
        assert signals == []

    @pytest.mark.parametrize("collector", _ALL_COLLECTOR_PARAMS)
    def test_empty_root_returns_list(
        self, collector: Collector, tmp_path: Path
    ) -> None:
        """A freshly-created empty directory must return a list (not raise)."""
        result = collector.collect(tmp_path)
        assert isinstance(result, list)

    @pytest.mark.parametrize("collector", _ALL_COLLECTOR_PARAMS)
    def test_file_passed_as_root_returns_list(
        self, collector: Collector, tmp_path: Path
    ) -> None:
        """A regular file passed where a directory is expected must return a list.

        The contract is 'a list, no exception'; the exact contents are unconstrained.
        """
        f = tmp_path / "file.txt"
        f.write_text("hello")
        result = collector.collect(f)
        assert isinstance(result, list)

    @pytest.mark.parametrize("collector", _ALL_COLLECTOR_PARAMS)
    def test_hostile_undecodable_tree_returns_list(
        self, collector: Collector, tmp_path: Path
    ) -> None:
        """A tree of undecodable / unparseable content must not make any collector raise.

        This is the realistic stressor the empty/nonexistent cases never touch: it
        forces the content-scanning and manifest-parsing collectors (todos,
        test_posture, merge_conflict, dependencies, ...) to face non-UTF-8 bytes,
        invalid TOML/JSON, a zero-byte file, and committed conflict markers. Every
        collector must still degrade to a list.
        """
        _build_hostile_tree(tmp_path)
        result = collector.collect(tmp_path)
        assert isinstance(result, list)
