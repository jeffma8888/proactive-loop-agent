"""TodoCollector: surfaces TODO/FIXME/XXX comments and Markdown checkboxes.

Scans source files (*.py, *.ts, *.js, *.md) for actionable items.
WHY include markdown checkboxes: project notes often use `- [ ]`, `* [ ]`,
or `+ [ ]` to track tasks; surfacing them gives the synthesizer richer
intent signals. All three GFM unordered-list bullets are treated alike.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from proactive_loop.models import ContextSignal

# Matches TODO / FIXME / XXX anywhere in a line (case-insensitive).
_INLINE_TAG_RE = re.compile(r"\b(TODO|FIXME|XXX)\b[:\s]*(.*)", re.IGNORECASE)

# Matches a Markdown unchecked task item. GitHub-Flavored Markdown treats
# `-`, `*`, and `+` as interchangeable unordered-list bullets, so accept any
# of them before the `[ ]` box: `- [ ] text`, `* [ ] text`, `+ [ ] text`.
_CHECKBOX_RE = re.compile(r"^\s*[-*+]\s+\[\s\]\s+(.*)")

_SCAN_EXTENSIONS: frozenset[str] = frozenset({".py", ".ts", ".js", ".md"})

_SKIP_DIRS: frozenset[str] = frozenset(
    {"node_modules", ".venv", "__pycache__", ".git", "dist", "build"}
)


def _is_hidden(name: str) -> bool:
    return name.startswith(".")


@dataclass
class TodoCollector:
    """Emit one ContextSignal per TODO/FIXME/XXX comment or Markdown checkbox.

    Caps results at *max_items* to keep the synthesizer prompt concise.
    """

    name: str = "todos"
    max_items: int = 30

    def collect(self, root: Path) -> list[ContextSignal]:
        """Scan *root* recursively for actionable todo items."""
        try:
            return self._collect(root)
        except Exception:
            return []

    def _collect(self, root: Path) -> list[ContextSignal]:
        if not root.is_dir():
            return []

        # Accumulate (relpath, lineno, signal) so we can order deterministically
        # regardless of os.walk traversal order across platforms.
        found: list[tuple[str, int, ContextSignal]] = []

        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [
                d for d in dirnames
                if not _is_hidden(d) and d not in _SKIP_DIRS
            ]
            for fname in filenames:
                if _is_hidden(fname):
                    continue
                if Path(fname).suffix.lower() not in _SCAN_EXTENSIONS:
                    continue
                full = Path(dirpath) / fname
                try:
                    text = full.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                found.extend(_extract_todos(text, full, root, self.name))

        # Deterministic: sort by (relpath, lineno) ascending, then cap -- so which
        # todos survive the cap and their order are a total, os.walk-order-independent
        # function of the filesystem, matching the sibling file-scanning collectors.
        found.sort(key=lambda item: (item[0], item[1]))
        return [signal for _, _, signal in found[: self.max_items]]


def _extract_todos(
    text: str,
    file_path: Path,
    root: Path,
    source_name: str,
) -> list[tuple[str, int, ContextSignal]]:
    """Return actionable items in *text* as ``(relpath, lineno, signal)`` tuples.

    WHY the (relpath, lineno) prefix: it is the deterministic sort key
    ``_collect`` uses to order and cap. Two todos can never share BOTH a relpath
    AND a line number (one signal per matched source line), so ``(relpath,
    lineno)`` is a genuine total order within one scan. The emitted
    ``ContextSignal`` fields are byte-unchanged from before.
    """
    found: list[tuple[str, int, ContextSignal]] = []
    try:
        rel = str(file_path.relative_to(root))
    except ValueError:
        rel = str(file_path)

    for lineno, line in enumerate(text.splitlines(), start=1):
        # Check for TODO/FIXME/XXX pattern.
        m = _INLINE_TAG_RE.search(line)
        if m:
            tag = m.group(1).upper()
            description = m.group(2).strip()
            summary = f"{tag}: {description}" if description else tag
            found.append(
                (
                    rel,
                    lineno,
                    ContextSignal(
                        source=source_name,
                        kind="todo",
                        summary=summary,
                        detail=line.strip(),
                        path=f"{rel}:{lineno}",
                        weight=1.0,
                    ),
                )
            )
            continue  # Don't double-count a line that is also a checkbox.

        # Check for Markdown unchecked checkbox.
        m2 = _CHECKBOX_RE.match(line)
        if m2:
            task_text = m2.group(1).strip()
            found.append(
                (
                    rel,
                    lineno,
                    ContextSignal(
                        source=source_name,
                        kind="todo",
                        summary=f"TODO: {task_text}",
                        detail=line.strip(),
                        path=f"{rel}:{lineno}",
                        weight=0.8,
                    ),
                )
            )

    return found
