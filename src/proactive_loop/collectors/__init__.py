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
from proactive_loop.collectors.license import LicenseCollector
from proactive_loop.collectors.lockfile_drift import LockfileDriftCollector
from proactive_loop.collectors.merge_conflict import MergeConflictCollector
from proactive_loop.collectors.notes import NotesCollector
from proactive_loop.collectors.secret_file import SecretFileCollector
from proactive_loop.collectors.syntax_error import SyntaxErrorCollector
from proactive_loop.collectors.test_posture import TestPostureCollector
from proactive_loop.collectors.todos import TodoCollector
from proactive_loop.collectors.working_tree import WorkingTreeCollector


# The closed vocabulary of ``ContextSignal.kind`` strings the built-in collectors
# emit -- i.e. the value universe of ``pla signals --kind K``, which the CLI wires
# in as argparse ``choices`` so an unknown kind is a PARSE-time usage error.
#
# WHY a literal tuple rather than deriving it from the registry at import time:
# a ``kind`` is chosen per-SIGNAL inside a collector's ``collect()`` body, not
# declared on the class, so the only runtime derivation available would be to RUN
# every collector against some workspace -- that is filesystem I/O during
# ``build_parser()``, and it would still report only the kinds that one workspace
# happened to trigger. A literal keeps parser construction pure, instant and
# workspace-independent. What makes the literal SAFE is the fail-closed drift
# guard in the test suite: it ``ast``-parses every module in this package for
# ``kind=`` keyword arguments and fails the build both when this tuple diverges
# from what the source emits and when any ``kind=`` argument stops being a plain
# string literal (a computed ``kind=f"git_{x}"`` would otherwise silently shrink
# the discoverable universe).
#
# WHY a tuple and not a list: argparse stores ``choices`` BY REFERENCE, so a
# mutable sequence would let any importer silently widen the CLI's accepted
# vocabulary at a distance. Sorted ascending so ``--help`` and the exit-2 error
# enumerate the kinds in a stable, reviewable order.
SIGNAL_KINDS: tuple[str, ...] = (
    "ci_config",
    "dependency",
    "git_commit",
    "git_stash",
    "git_state",
    "large_file",
    "license",
    "lockfile_drift",
    "merge_conflict",
    "note",
    "recent_file",
    "secret_file",
    "syntax_error",
    "test_posture",
    "todo",
    "working_tree",
)


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
        SyntaxErrorCollector(),
        LicenseCollector(),
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
    "SyntaxErrorCollector",
    "LicenseCollector",
    "all_collectors",
    "SIGNAL_KINDS",
]
