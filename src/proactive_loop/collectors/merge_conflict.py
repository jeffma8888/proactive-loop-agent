"""MergeConflictCollector: surface committed VCS conflict markers as L2 signals.

WHY this collector exists: the scout's proactivity ceiling is set entirely by
*what its collectors can perceive* (SPEC sections 1, 4.1). A common, high-urgency
footgun was invisible to every existing collector: a merge/rebase that was
"finished" (committed) but left git conflict markers INSIDE the committed files
-- non-compiling code, broken tests, a corrupt diff the developer forgot to
resolve. This is a genuine PERCEPTION HOLE, not a near-copy of an existing
collector:

  * ``GitStateCollector`` reads ``.git/MERGE_HEAD`` to detect an *in-progress*
    merge -- that marker VANISHES the instant you ``git commit``, while the
    ``<<<<<<<`` / ``>>>>>>>`` TEXT survives in the committed file.
  * ``WorkingTreeCollector`` reports *that* a path changed, never its content.
  * ``GitActivityCollector`` reads committed history, never file content.

Different state, different urgency, different fix. This collector line-scans
scanned-extension files for the two UNAMBIGUOUS conflict-marker label prefixes
git writes at column 0 -- the OPEN ``"<<<<<<< "`` and CLOSE ``">>>>>>> "``
(seven chevrons plus exactly one space) -- and emits one ``kind="merge_conflict"``
signal per affected file carrying the marker count. It reports plain *facts*
(which file, how many markers); it makes no judgement -- the synthesizer LLM
decides whether a "resolve leftover conflict markers in X" goal is warranted,
exactly like ``TodoCollector`` / ``NotesCollector`` (the established
content-scan mechanism this reuses). A new ``kind="merge_conflict"`` flows into
the synthesis prompt automatically because ``synthesizer._build_prompt`` iterates
``snapshot.by_kind()``, so this file plus the two-line registry wiring is the
whole cost -- additive, no version bump (mirrors iters 09/11/16/20).

The middle ``=======`` separator is DELIBERATELY excluded from both detection
and the count: a bare run of ``=`` is ambiguous (a Markdown setext-H1 underline,
an ASCII rule/separator) and counting it would manufacture false positives. On a
PUBLIC repo the unambiguous signal is the correct one. Pure stdlib
(``os``/``pathlib``) only, so the runtime stays pydantic-v2-only and fully
offline; never raises -> ``[]``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from proactive_loop.collectors.base import BaseCollector
# Reuse the EXACT skip rules RecentFilesCollector uses (the SPEC-sanctioned
# shared seam, mirroring dependencies.py / test_posture.py) so a marked file
# buried in node_modules/.venv/a hidden dir is invisible here too.
from proactive_loop.collectors.filesystem import _SKIP_DIRS, _is_hidden
from proactive_loop.collectors.large_file import LARGE_FILE_MIN_BYTES
# The MODULE is imported (not its ``read_text`` function) so all three content
# collectors resolve the provider through ONE patchable attribute.
from proactive_loop.collectors import text_source
from proactive_loop.models import ContextSignal

# The two conflict-marker label prefixes git writes at column 0: exactly seven
# chevrons followed by exactly one space. Matching the FULL prefix (not just the
# chevrons) rejects ``<<<<<<<<`` (eight), ``<<<<<<<foo`` (no space) and a bare
# ``<<<<<<<`` (no trailing content), so only a genuine git marker line counts.
# The middle ``=======`` separator is NOT here on purpose (see module docstring).
_OPEN_PREFIX: str = "<<<<<<< "
_CLOSE_PREFIX: str = ">>>>>>> "

# Extensions we content-scan. Deliberately a focused text/source set: lockfiles
# (`.lock`) and binary/image types are excluded so a marker-looking byte run in a
# blob can never register. Extension match is case-insensitive (`.PY` == `.py`).
_SCAN_EXTS: frozenset[str] = frozenset(
    {
        ".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".java",
        ".c", ".h", ".cpp", ".rb", ".cs", ".php",
        ".md", ".txt", ".yml", ".yaml", ".json", ".toml", ".cfg", ".ini", ".sh",
    }
)


def _count_markers(text: str) -> int:
    """Count conflict-marker label lines in *text*.

    A line is a marker line iff its raw text (trailing newline already stripped
    by ``splitlines``, with NO leading-whitespace strip -- git never indents
    markers) STARTS WITH the OPEN or CLOSE prefix. The return value is the number
    of OPEN-prefix lines PLUS the number of CLOSE-prefix lines; the ambiguous
    ``=======`` separator is never counted. A standard single conflict block
    (``<<<<<<< HEAD`` / ``=======`` / ``>>>>>>> branch``) therefore returns 2.
    """
    count = 0
    for line in text.splitlines():
        if line.startswith(_OPEN_PREFIX) or line.startswith(_CLOSE_PREFIX):
            count += 1
    return count


@dataclass
class MergeConflictCollector(BaseCollector):
    """Emit one ContextSignal per file that still contains conflict markers.

    WHY a dataclass with defaults: mirrors the sibling collectors so
    ``all_collectors()`` can construct it with no arguments, while a caller
    scanning a very large tree can still cap the number of files reported.

    WHY *max_read_bytes*: this collector DECODES every scanned-extension file it
    walks (the widest extension set of the three text collectors), so without an
    upper bound one vendored blob is pulled into memory on every scan -- and
    ``pla watch`` repeats that each interval. Files whose ``st_size`` EXCEEDS the
    cap are skipped unread. This is not a blind spot: the cap equals
    ``LARGE_FILE_MIN_BYTES``, and ``LargeFileCollector`` reports at ``size >=
    LARGE_FILE_MIN_BYTES`` from ``st_size`` alone, so every file skipped here is
    already reported there as a ``kind="large_file"`` signal -- skipped-here
    implies reported-there. The comparison is STRICTLY greater, deliberately
    overlapping that inclusive ``>=`` by exactly one size so the ranges leave no gap.
    """

    name: str = "merge_conflict"
    max_items: int = 30
    max_read_bytes: int = LARGE_FILE_MIN_BYTES

    def _collect(self, root: Path) -> list[ContextSignal]:
        """Walk *root* and return one signal per file containing conflict markers."""
        if not root.is_dir():
            return []

        # Collect (relpath, signal) pairs so we can order deterministically
        # regardless of os.walk traversal order across platforms.
        found: list[tuple[str, ContextSignal]] = []
        for dirpath, dirnames, filenames in os.walk(root):
            # Prune noise + hidden dirs in place, identical to the sibling
            # collectors, so os.walk never descends into them.
            dirnames[:] = [
                d for d in dirnames if not _is_hidden(d) and d not in _SKIP_DIRS
            ]
            for fname in filenames:
                # A hidden FILE (name starting with '.') is skipped too.
                if _is_hidden(fname):
                    continue
                if Path(fname).suffix.lower() not in _SCAN_EXTS:
                    continue
                full = Path(dirpath) / fname
                # Per-file guard: one unreadable file (OSError) is skipped
                # without aborting the walk; errors="replace" means a decode
                # never raises, so a binary-ish text file just yields 0 markers.
                # The size read sits inside the SAME try, so a file that vanishes
                # or denies stat() mid-walk is skipped just like an unreadable one,
                # and an oversized file is skipped BEFORE any decode happens.
                try:
                    if full.stat().st_size > self.max_read_bytes:
                        continue
                    # Shared per-scan decode (see text_source): ``strict=False``
                    # preserves this collector's errors="replace" policy, so a
                    # binary-ish text file still just yields 0 markers and a
                    # marker inside an undecodable file is still reported.
                    text = text_source.read_text(full, strict=False)
                except OSError:
                    continue
                count = _count_markers(text)
                if count == 0:
                    continue
                rel = self._relative(root, full)
                found.append((rel, self._signal_for(rel, count)))

        # Deterministic: sort by relpath ascending, then cap at max_items (so the
        # kept set is the max_items lexicographically-smallest relpaths).
        found.sort(key=lambda pair: pair[0])
        return [signal for _, signal in found[: self.max_items]]

    def _signal_for(self, rel: str, count: int) -> ContextSignal:
        """Build one merge-conflict signal for *rel* with *count* markers.

        ``path`` is the RELATIVE path (not absolute like RecentFiles/dependencies)
        so the signal is stable and human-readable on a PUBLIC repo. ``detail`` is
        empty: one signal per file, no embedded file content, keeps the slate JSON
        compact. The noun is singular ONLY at count == 1.
        """
        noun = "conflict marker" if count == 1 else "conflict markers"
        return ContextSignal(
            source=self.name,
            kind="merge_conflict",
            summary=f"{rel}: {count} {noun}",
            detail="",
            path=rel,
            weight=0.9,
            timestamp=None,
        )
