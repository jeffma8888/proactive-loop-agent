"""RecentFilesCollector, plus the package's single shared filesystem walk policy.

Only pure stdlib is used. The collector skips hidden directories and
common noise directories (node_modules, .venv, __pycache__) so the
signal list stays relevant to developer work.

WHY sibling collectors import private names from here: this module is the ONE
home of the package's walk policy -- ``_SKIP_DIRS`` and ``_is_hidden`` ("which
parts of a tree are worth looking at") and ``_has_source`` ("does this tree
contain source code"). Eleven modules already import that seam (``broken_link``,
``ci_config``, ``dependencies``, ``large_file``, ``license``,
``lockfile_drift``, ``merge_conflict``, ``secret_file``, ``syntax_error``,
``test_posture``, and ``loop/tools.py``'s L1 ACT sandbox), so a policy question
answered here is answered once. ``_has_source`` was hoisted here because it had
been answered TWICE -- ``ci_config`` and ``license`` each carried a verbatim copy
behind a comment asking a human to keep them equal by hand, and both copies
decide whether their collector emits an actionable L2 gap signal, so a split
would have changed emitted signals.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from proactive_loop.collectors.base import BaseCollector
from proactive_loop.models import ContextSignal

# Directories that are never useful to scan
_SKIP_DIRS: frozenset[str] = frozenset(
    {"node_modules", ".venv", "__pycache__", ".git", ".tox", "dist", "build"}
)


def _is_hidden(name: str) -> bool:
    """Return True if a file or directory name starts with '.'."""
    return name.startswith(".")


# Extensions that count as "code" when a collector asks whether a tree holds
# anything worth building or licensing. Deliberately narrow and
# language-agnostic; anything else (docs, config, data) is ignored.
#
# WHY `test_posture._CANDIDATE_EXTS` is deliberately NOT folded in here even
# though it holds the same five suffixes today: it answers a DIFFERENT question
# ("could this file hold a test?"), so aliasing the two would couple two
# independent policies that are merely equal -- widening one would silently
# widen the other. Equal values are not one concept.
_SOURCE_EXTS: frozenset[str] = frozenset({".py", ".ts", ".js", ".go", ".rs"})


def _has_source(root: Path) -> bool:
    """True iff any non-pruned file under *root* has a source extension.

    WHY this lives here rather than in either caller: ``CiConfigCollector`` and
    ``LicenseCollector`` both gate an actionable L2 gap ("no CI configured", "no
    license file") on there being code to act on, so that gate must have exactly
    ONE definition -- while it had two, an edit to either copy could silently
    change which signals the other collector emits.

    Walks the tree once, pruning noise + hidden dirs in place exactly like
    ``RecentFilesCollector``, so a source file that lives ONLY inside
    ``node_modules``/``.venv``/a hidden dir does not count (SPEC skip rule).
    Reads only filenames -- never file content -- so it cannot raise on
    undecodable bytes. Deliberately does NOT skip hidden FILES and is
    deliberately case-sensitive on the suffix: both are the long-standing
    behavior of the two copies this replaces, so changing either would be a
    behavior change, not a cleanup.
    """
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames if not _is_hidden(d) and d not in _SKIP_DIRS
        ]
        for fname in filenames:
            if Path(fname).suffix in _SOURCE_EXTS:
                return True
    return False


@dataclass
class RecentFilesCollector(BaseCollector):
    """Emit one ContextSignal per recently-modified file under *root*.

    WHY weight by recency: files touched in the last hour deserve more
    attention in the synthesizer prompt than files from two weeks ago.
    """

    name: str = "recent_files"
    max_files: int = 20
    within_days: float = 14.0

    def _collect(self, root: Path) -> list[ContextSignal]:
        """Walk *root* and return signals for recently modified files."""
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

        # Sort newest first, ties broken by ascending path, then cap. WHY the
        # negation form over reverse=True: mtime is genuinely tie-able (files
        # written/copied/checked-out/extracted in one op, or coarse-resolution
        # filesystems, share an st_mtime), and reverse=True on a stable sort would
        # then leave equal-mtime files in arbitrary os.walk order -- so WHICH files
        # survive the max_files cap (and their emission order) would depend on
        # filesystem-entry order, not content. Keying on (-mtime, path) makes
        # collect(root) a total, os.walk-order-independent function of the
        # filesystem, matching LargeFileCollector's documented ascending-relpath
        # tie-break.
        candidates.sort(key=lambda t: (-t[0], str(t[1])))
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
