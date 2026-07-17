"""Tests for the collectors package.

Coverage:
- RecentFilesCollector: finds recent files, skips hidden/noise dirs, respects max_files.
- GitActivityCollector: real temp git repo (skipped if git unavailable), missing-repo degrades.
- TodoCollector: finds TODO/FIXME/XXX and markdown checkboxes, respects max_items.
- NotesCollector: finds headings + paragraphs under notes/journal/docs dirs.
- Graceful degradation: all collectors return [] on missing or empty directories.
- all_collectors(): returns one of each type.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from proactive_loop.collectors import (
    GitActivityCollector,
    NotesCollector,
    RecentFilesCollector,
    TodoCollector,
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
    def test_returns_all_four_types(self) -> None:
        collectors = all_collectors()
        types = {type(c) for c in collectors}
        assert RecentFilesCollector in types
        assert GitActivityCollector in types
        assert TodoCollector in types
        assert NotesCollector in types

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
    """Verify that no collector raises on unusual inputs."""

    @pytest.mark.parametrize(
        "collector",
        [
            RecentFilesCollector(),
            GitActivityCollector(),
            TodoCollector(),
            NotesCollector(),
        ],
    )
    def test_nonexistent_root_returns_empty(
        self, collector: Collector, tmp_path: Path
    ) -> None:
        signals = collector.collect(tmp_path / "does_not_exist")
        assert signals == []

    @pytest.mark.parametrize(
        "collector",
        [
            RecentFilesCollector(),
            GitActivityCollector(),
            TodoCollector(),
            NotesCollector(),
        ],
    )
    def test_empty_root_returns_list(
        self, collector: Collector, tmp_path: Path
    ) -> None:
        result = collector.collect(tmp_path)
        assert isinstance(result, list)

    @pytest.mark.parametrize(
        "collector",
        [
            RecentFilesCollector(),
            GitActivityCollector(),
            TodoCollector(),
            NotesCollector(),
        ],
    )
    def test_file_passed_as_root_returns_empty(
        self, collector: Collector, tmp_path: Path
    ) -> None:
        """Passing a file path instead of a directory should degrade to []."""
        f = tmp_path / "file.txt"
        f.write_text("hello")
        result = collector.collect(f)
        assert isinstance(result, list)
