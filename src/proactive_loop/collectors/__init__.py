"""Collectors package for the proactive loop agent.

The all_collectors() registry returns one instance of every collector.
Importers can use this list directly or filter/extend it as needed.
"""

from __future__ import annotations

from proactive_loop.collectors.base import Collector
from proactive_loop.collectors.ci_config import CiConfigCollector
from proactive_loop.collectors.dependencies import DependencyCollector
from proactive_loop.collectors.filesystem import RecentFilesCollector
from proactive_loop.collectors.git_activity import GitActivityCollector
from proactive_loop.collectors.git_state import GitStateCollector
from proactive_loop.collectors.git_stash import GitStashCollector
from proactive_loop.collectors.large_file import LargeFileCollector
from proactive_loop.collectors.lockfile_drift import LockfileDriftCollector
from proactive_loop.collectors.merge_conflict import MergeConflictCollector
from proactive_loop.collectors.notes import NotesCollector
from proactive_loop.collectors.secret_file import SecretFileCollector
from proactive_loop.collectors.test_posture import TestPostureCollector
from proactive_loop.collectors.todos import TodoCollector
from proactive_loop.collectors.working_tree import WorkingTreeCollector


def all_collectors() -> list[Collector]:
    """Return one instance of every built-in collector.

    WHY a factory function instead of a module-level constant: collectors
    carry mutable default state (e.g. max_files), and callers may want to
    customise or replace individual instances without affecting others.
    """
    return [
        RecentFilesCollector(),
        GitActivityCollector(),
        GitStateCollector(),
        GitStashCollector(),
        TodoCollector(),
        NotesCollector(),
        DependencyCollector(),
        WorkingTreeCollector(),
        TestPostureCollector(),
        MergeConflictCollector(),
        LargeFileCollector(),
        SecretFileCollector(),
        CiConfigCollector(),
        LockfileDriftCollector(),
    ]


__all__ = [
    "Collector",
    "RecentFilesCollector",
    "GitActivityCollector",
    "GitStateCollector",
    "GitStashCollector",
    "TodoCollector",
    "NotesCollector",
    "DependencyCollector",
    "WorkingTreeCollector",
    "TestPostureCollector",
    "MergeConflictCollector",
    "LargeFileCollector",
    "SecretFileCollector",
    "CiConfigCollector",
    "LockfileDriftCollector",
    "all_collectors",
]
