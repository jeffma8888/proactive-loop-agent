"""GitActivityCollector: surfaces recent git commits in a workspace.

Runs `git log` via subprocess for the root directory and any direct
child directory that contains a `.git` folder. Returns [] if git is
not installed, the directory is not a repo, or the subprocess fails.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from proactive_loop.collectors.base import BaseCollector
from proactive_loop.models import ContextSignal

# Format: hash<sep>date<sep>subject<sep>author
_LOG_FORMAT = "%H\x1f%ai\x1f%s\x1f%an"
_SEP = "\x1f"


def _fetch_commits(directory: Path, max_commits: int) -> list[ContextSignal]:
    """Run git log for *directory* and return parsed signals.

    Returns [] on any error (not a repo, git unavailable, etc.).
    """
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(directory),
                "log",
                f"--pretty=format:{_LOG_FORMAT}",
                f"-n{max_commits}",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []

    if result.returncode != 0:
        return []

    signals: list[ContextSignal] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(_SEP, 3)
        if len(parts) < 4:
            continue
        commit_hash, date_str, subject, author = parts
        # Parse ISO-8601 date produced by %ai (e.g. "2024-01-15 10:30:00 -0700")
        ts: datetime | None = None
        try:
            ts = datetime.fromisoformat(date_str.strip())
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            ts = None
        signals.append(
            ContextSignal(
                source="git_activity",
                kind="git_commit",
                summary=f"Commit in {directory.name}: {subject}",
                detail=f"hash={commit_hash[:8]} author={author}",
                path=str(directory),
                weight=1.0,
                timestamp=ts,
            )
        )
    return signals


@dataclass
class GitActivityCollector(BaseCollector):
    """Emit one ContextSignal per recent git commit found in *root* or its repos.

    WHY scan child directories: a workspace often contains several sub-projects
    each with their own .git folder. Scanning each lets the synthesizer see
    commit activity across all of them.
    """

    name: str = "git_activity"
    max_commits: int = 15

    def _collect(self, root: Path) -> list[ContextSignal]:
        """Return commit signals for *root* and direct children that are git repos."""
        if not root.is_dir():
            return []

        # Determine candidate directories: root itself + direct children with .git.
        dirs_to_scan: list[Path] = []

        # Always try root (it may or may not be a repo — git will say).
        dirs_to_scan.append(root)

        # Also check direct child directories. Scan them in ascending name order
        # (sorted) so a multi-repo workspace's cross-repo signal order is
        # deterministic (filesystem iterdir order is arbitrary); per-repo commit
        # order stays newest-first because we sort the directories, not the signals.
        try:
            for child in sorted(root.iterdir()):
                if child.is_dir() and (child / ".git").exists():
                    if child not in dirs_to_scan:
                        dirs_to_scan.append(child)
        except OSError:
            pass

        seen_summaries: set[str] = set()
        signals: list[ContextSignal] = []

        for directory in dirs_to_scan:
            for sig in _fetch_commits(directory, self.max_commits):
                sig.source = self.name
                key = sig.summary
                if key not in seen_summaries:
                    seen_summaries.add(key)
                    signals.append(sig)

        return signals
