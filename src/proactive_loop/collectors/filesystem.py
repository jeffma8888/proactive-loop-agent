"""RecentFilesCollector: surfaces recently modified files in a workspace.

Only pure stdlib is used. The collector skips hidden directories and
common noise directories (node_modules, .venv, __pycache__) so the
signal list stays relevant to developer work.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from proactive_loop.models import ContextSignal

# Directories that are never useful to scan
_SKIP_DIRS: frozenset[str] = frozenset(
    {"node_modules", ".venv", "__pycache__", ".git", ".tox", "dist", "build"}
)


def _is_hidden(name: str) -> bool:
    """Return True if a file or directory name starts with '.'."""
    return name.startswith(".")


@dataclass
class RecentFilesCollector:
    """Emit one ContextSignal per recently-modified file under *root*.

    WHY weight by recency: files touched in the last hour deserve more
    attention in the synthesizer prompt than files from two weeks ago.
    """

    name: str = "recent_files"
    max_files: int = 20
    within_days: float = 14.0

    def collect(self, root: Path) -> list[ContextSignal]:
        """Walk *root* and return signals for recently modified files."""
        try:
            return self._collect(root)
        except Exception:
            # Degrade gracefully: never propagate filesystem errors.
            return []

    def _collect(self, root: Path) -> list[ContextSignal]:
        if not root.is_dir():
            return []

        cutoff_sec = time.time() - self.within_days * 86_400
        candidates: list[tuple[float, Path]] = []

        for dirpath, dirnames, filenames in os.walk(root):
            # Prune unwanted directories in-place so os.walk skips them.
            dirnames[:] = [
                d for d in dirnames
                if not _is_hidden(d) and d not in _SKIP_DIRS
            ]
            for fname in filenames:
                if _is_hidden(fname):
                    continue
                full = Path(dirpath) / fname
                try:
                    mtime = full.stat().st_mtime
                except OSError:
                    continue
                if mtime >= cutoff_sec:
                    candidates.append((mtime, full))

        # Sort newest first, then cap.
        candidates.sort(key=lambda t: t[0], reverse=True)
        candidates = candidates[: self.max_files]

        now = time.time()
        signals: list[ContextSignal] = []
        for mtime, path in candidates:
            age_days = (now - mtime) / 86_400
            # Weight decays linearly from 1.0 (just modified) to ~0.07 at within_days,
            # clamped to [0, 1] so a future mtime (clock skew / archive extraction)
            # cannot push the weight above 1.0 and over-rank the file.
            weight = min(1.0, max(0.0, 1.0 - age_days / max(self.within_days, 1)))
            try:
                rel = path.relative_to(root)
            except ValueError:
                rel = path
            signals.append(
                ContextSignal(
                    source=self.name,
                    kind="recent_file",
                    summary=f"Recently modified: {rel}",
                    detail="",
                    path=str(path),
                    weight=round(weight, 4),
                    timestamp=datetime.fromtimestamp(mtime, tz=timezone.utc),
                )
            )

        return signals
