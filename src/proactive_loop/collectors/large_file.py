"""LargeFileCollector: surface unexpectedly large files as an L2 repo-hygiene signal.

WHY this collector exists: the scout's proactivity ceiling is set entirely by
*what its collectors can perceive* (SPEC sections 1, 4.1). The existing
collectors see file recency, git activity/state, uncommitted/unpushed work,
TODO/FIXME comments, notes, dependency manifests, test posture, and committed
merge-conflict markers -- but none of them perceives **repo hygiene**: an
oversized file sitting in a workspace (a stray build artifact, an accidentally
saved dataset, a checked-in binary) is a classic pre-commit hazard. Commit it and
you irreversibly bloat git history and slow every clone; it should have gone to
`.gitignore` / git-lfs instead. This is a per-file byte-size-threshold signal no
existing collector produces (`test_posture` counts files per dir, `recent_files`
weights by mtime, nothing surfaces "which files here are unexpectedly large"), so
a new kind="large_file" gives the synthesizer a genuinely new hygiene axis and
flows into synthesis via WorkspaceSnapshot.by_kind() with zero synthesizer change.

The collector reports plain *facts* (which file, how large); it makes no
judgement -- the synthesizer LLM decides whether a goal is warranted, exactly like
DependencyCollector. It reads only `st_size` metadata and NEVER opens file
content, so it structurally cannot raise on binary/non-UTF-8 bytes (SPEC Out of
Scope: no content reading, no MIME sniffing, no git/.gitignore awareness). Pure
stdlib (`os`/`pathlib`) only, so the runtime stays pydantic-v2-only and offline.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# Reuse the EXACT skip rules RecentFilesCollector uses (the SPEC-sanctioned shared
# seam, mirroring dependencies.py / test_posture.py) so a large file buried in
# node_modules/.venv/a hidden dir is invisible here too (spec Behavior 6).
from proactive_loop.collectors.filesystem import _SKIP_DIRS, _is_hidden
from proactive_loop.models import ContextSignal

# The ONE home for "how big is too big" in the perception layer.
#
# WHY a named module-level constant rather than a bare dataclass default: this
# collector owns the size decision, and the three whole-tree TEXT collectors
# (todos, merge_conflict, syntax_error) cap the bytes they are willing to DECODE
# at this same number. Sharing one constant makes their coverage compose exactly:
# a file too big for them to read is necessarily big enough to be reported here,
# so no file becomes invisible (see those modules' docstrings).
LARGE_FILE_MIN_BYTES: int = 5_000_000


def _human_size(n: int) -> str:
    """Render a raw byte count *n* with SI (decimal) units and one decimal place.

    WHY SI/decimal (1_000-based) not binary (1_024-based): the threshold default
    (5_000_000) and the human string share one base, so the boundary anchor reads
    cleanly as ``5.0 MB`` instead of a lopsided ``4.8 MiB``. Deterministic and
    total over every non-negative int (spec Behavior 4).
    """
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f} MB"
    if n >= 1_000:
        return f"{n / 1_000:.1f} KB"
    return f"{n} B"


@dataclass
class LargeFileCollector:
    """Emit one ContextSignal per file whose size is at or above *min_bytes*.

    WHY a dataclass with defaults: mirrors the sibling collectors so
    all_collectors() can construct it with no arguments, while a caller can lower
    `min_bytes` (e.g. in tests) or cap `max_items` on a very large tree. The
    comparison is inclusive (`size >= min_bytes`) so a file of exactly the
    threshold IS flagged (spec Behavior 2).
    """

    name: str = "large_file"
    max_items: int = 20
    min_bytes: int = LARGE_FILE_MIN_BYTES

    def collect(self, root: Path) -> list[ContextSignal]:
        """Walk *root* and return one signal per oversized file.

        Never raises: any filesystem error degrades to ``[]``, honouring the
        Collector contract so one unreadable tree can never abort a scan.
        """
        try:
            return self._collect(root)
        except Exception:
            return []

    def _collect(self, root: Path) -> list[ContextSignal]:
        if not root.is_dir():
            return []

        # (size, relpath, absolute-path) triples, so we can order deterministically
        # by descending size then ascending relpath regardless of os.walk order.
        candidates: list[tuple[int, str, Path]] = []
        for dirpath, dirnames, filenames in os.walk(root):
            # Prune noise + hidden dirs in place, identical to the sibling
            # collectors, so os.walk never descends into them (spec Behavior 6).
            dirnames[:] = [
                d for d in dirnames if not _is_hidden(d) and d not in _SKIP_DIRS
            ]
            for fname in filenames:
                # Hidden files are skipped like RecentFilesCollector (spec Behavior 6).
                if _is_hidden(fname):
                    continue
                full = Path(dirpath) / fname
                # Per-file guard: a file that vanishes or denies stat() between the
                # walk and the size read is skipped; its siblings still emit
                # (spec Behavior 8). We read ONLY st_size -- never file content.
                try:
                    size = full.stat().st_size
                except OSError:
                    continue
                if size < self.min_bytes:
                    continue
                candidates.append((size, self._relative(root, full), full))

        # Descending size, ties broken by ascending forward-slashed relpath, then
        # truncate to the first max_items so the LARGEST files are kept (Behavior 5).
        candidates.sort(key=lambda triple: (-triple[0], triple[1]))
        return [
            self._signal_for(size, rel, full)
            for size, rel, full in candidates[: self.max_items]
        ]

    @staticmethod
    def _relative(root: Path, path: Path) -> str:
        """Path of *path* relative to *root*, always forward-slashed (Behavior 4)."""
        try:
            return path.relative_to(root).as_posix()
        except ValueError:
            return path.as_posix()

    def _signal_for(self, size: int, rel: str, full: Path) -> ContextSignal:
        """Build one large-file signal.

        The absolute path lives in `path` (mirrors RecentFilesCollector /
        DependencyCollector / TestPostureCollector "the file it came from"); the
        deterministic forward-slashed relative path is carried in `summary`.
        """
        return ContextSignal(
            source=self.name,
            kind="large_file",
            summary=f"{rel}: {_human_size(size)} (large)",
            detail="",
            path=str(full),
            # Fixed mid-range weight mirroring DependencyCollector: an oversized
            # file is a durable, always-relevant hygiene fact, not time-decaying.
            weight=0.6,
            timestamp=None,
        )
