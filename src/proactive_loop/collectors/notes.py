"""NotesCollector: surfaces headings and opening paragraphs from Markdown notes.

Only scans *.md files under directories whose name matches notes, journal, or
docs (case-insensitive). This keeps the signal set focused on intentional
notes rather than every README in the workspace.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from proactive_loop.models import ContextSignal

# ATX-style heading: one or more '#' followed by the title.
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)")

# A fenced code block opens/closes on a line whose leading non-whitespace is 3+
# backticks or 3+ tildes. WHY: '#' lines inside such a fence are code (shell
# scripts, Python top-level comments), not note headings; surfacing them as
# heading signals would pollute the L2 perception surface with false positives.
_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")

# Directories to scan for notes (matched case-insensitively against the dir name).
_NOTES_DIRS: frozenset[str] = frozenset({"notes", "journal", "docs"})

_SKIP_DIRS: frozenset[str] = frozenset(
    {"node_modules", ".venv", "__pycache__", ".git", "dist", "build"}
)


def _is_hidden(name: str) -> bool:
    return name.startswith(".")


def _is_notes_dir(name: str) -> bool:
    """Return True if *name* matches one of the canonical notes directory names."""
    return name.lower() in _NOTES_DIRS


def _fence_mask(lines: list[str]) -> list[bool]:
    """Return a per-line mask where True means the line lies inside a fenced code block.

    WHY: heading detection must skip fenced regions. A fence opens on the first
    line whose leading non-whitespace is 3+ backticks or 3+ tildes and closes only
    on a later line using the SAME delimiter character (so a ``~~~`` line cannot
    close a ``` block). An unterminated fence runs to end-of-file. The delimiter
    lines themselves are marked inside the block; they are never headings anyway.
    """
    mask = [False] * len(lines)
    fence_char: str | None = None
    for idx, line in enumerate(lines):
        m = _FENCE_RE.match(line)
        if fence_char is None:
            if m:
                fence_char = m.group(1)[0]
                mask[idx] = True
        else:
            mask[idx] = True
            if m and m.group(1)[0] == fence_char:
                fence_char = None
    return mask


@dataclass
class NotesCollector:
    """Emit one ContextSignal per heading-plus-paragraph found in notes directories.

    WHY capture first paragraph: it gives the synthesizer enough context to
    judge whether the note is relevant without overwhelming the prompt with
    full file contents.
    """

    name: str = "notes"
    max_items: int = 20

    def collect(self, root: Path) -> list[ContextSignal]:
        """Scan *root* for notes directories and extract heading/paragraph signals."""
        try:
            return self._collect(root)
        except Exception:
            return []

    def _collect(self, root: Path) -> list[ContextSignal]:
        if not root.is_dir():
            return []

        signals: list[ContextSignal] = []

        # Find all notes-style directories under root (including root itself if named so).
        notes_dirs: list[Path] = []
        for dirpath, dirnames, _filenames in os.walk(root):
            dp = Path(dirpath)
            if _is_notes_dir(dp.name):
                notes_dirs.append(dp)
                # No need to recurse into a notes dir searching for sub-notes dirs.
                dirnames.clear()
                continue
            # Prune noise.
            dirnames[:] = [
                d for d in dirnames
                if not _is_hidden(d) and d not in _SKIP_DIRS
            ]

        for notes_dir in notes_dirs:
            for fpath in sorted(notes_dir.rglob("*.md")):
                if _is_hidden(fpath.name):
                    continue
                try:
                    text = fpath.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                for sig in _extract_note_signals(text, fpath, root, self.name):
                    signals.append(sig)
                    if len(signals) >= self.max_items:
                        return signals

        return signals


def _extract_note_signals(
    text: str,
    file_path: Path,
    root: Path,
    source_name: str,
) -> list[ContextSignal]:
    """Extract (heading, first-paragraph) pairs from *text*.

    ATX headings inside fenced code blocks are ignored (see ``_fence_mask``): an
    unindented ``#`` line inside a ``` / ~~~ fence is code, not a note heading.
    """
    try:
        rel = str(file_path.relative_to(root))
    except ValueError:
        rel = str(file_path)

    signals: list[ContextSignal] = []
    lines = text.splitlines()
    in_fence = _fence_mask(lines)
    i = 0

    while i < len(lines):
        # A heading only counts when it is NOT inside a fenced code block.
        m = None if in_fence[i] else _HEADING_RE.match(lines[i])
        if m:
            heading_text = m.group(2).strip()
            # Collect the first non-empty paragraph following the heading.
            para_lines: list[str] = []
            j = i + 1
            # Skip blank lines immediately after heading.
            while j < len(lines) and not lines[j].strip():
                j += 1
            # Collect paragraph until a blank line or the next NON-fenced heading.
            # A fenced '#' must not truncate the paragraph, else it would be
            # re-exposed to the outer loop as a spurious heading.
            while (
                j < len(lines)
                and lines[j].strip()
                and not (not in_fence[j] and _HEADING_RE.match(lines[j]))
            ):
                para_lines.append(lines[j].strip())
                j += 1

            first_para = " ".join(para_lines)
            signals.append(
                ContextSignal(
                    source=source_name,
                    kind="note",
                    summary=heading_text,
                    detail=first_para[:300],  # Cap detail length.
                    path=rel,
                    weight=1.0,
                )
            )
            i = j
        else:
            i += 1

    return signals
