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
    """Extract (heading, first-paragraph) pairs from *text*."""
    try:
        rel = str(file_path.relative_to(root))
    except ValueError:
        rel = str(file_path)

    signals: list[ContextSignal] = []
    lines = text.splitlines()
    i = 0

    while i < len(lines):
        m = _HEADING_RE.match(lines[i])
        if m:
            heading_text = m.group(2).strip()
            # Collect the first non-empty paragraph following the heading.
            para_lines: list[str] = []
            j = i + 1
            # Skip blank lines immediately after heading.
            while j < len(lines) and not lines[j].strip():
                j += 1
            # Collect paragraph until blank line or next heading.
            while j < len(lines) and lines[j].strip() and not _HEADING_RE.match(lines[j]):
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
