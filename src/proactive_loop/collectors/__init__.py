"""Collectors package for the proactive loop agent.

The all_collectors() registry returns one instance of every collector.
Importers can use this list directly or filter/extend it as needed.
"""

from __future__ import annotations

from proactive_loop.collectors.base import Collector
from proactive_loop.collectors.dependencies import DependencyCollector
from proactive_loop.collectors.filesystem import RecentFilesCollector
from proactive_loop.collectors.git_activity import GitActivityCollector
from proactive_loop.collectors.git_state import GitStateCollector
from proactive_loop.collectors.notes import NotesCollector
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
        TodoCollector(),
        NotesCollector(),
        DependencyCollector(),
        WorkingTreeCollector(),
        TestPostureCollector(),
    ]


__all__ = [
    "Collector",
    "RecentFilesCollector",
    "GitActivityCollector",
    "GitStateCollector",
    "TodoCollector",
    "NotesCollector",
    "DependencyCollector",
    "WorkingTreeCollector",
    "TestPostureCollector",
    "all_collectors",
]
