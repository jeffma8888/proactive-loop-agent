"""Sandboxed tool registry: the ACT phase's only door to the filesystem.

WHY a hard sandbox: the loop hands model-proposed tool calls straight to these
handlers, so any write MUST be confined to a dedicated artifacts directory and
path-traversal / absolute paths MUST be refused. WHY errors are returned rather
than raised: the loop feeds each observation back to the model so it can
recover -- a raised exception would abort an otherwise-recoverable run. Hence
every failure (including an unknown tool) becomes an ``"error: ..."`` string.
"""

from __future__ import annotations

import os
from pathlib import Path

from proactive_loop.collectors.filesystem import _SKIP_DIRS, _is_hidden
from proactive_loop.models import ensure_dir

# Cap on hits returned by search_files: keep observations bounded so a broad
# query on a large workspace cannot flood the model's context window.
_SEARCH_MAX_HITS = 50


class ToolRegistry:
    """Dispatch model tool calls to sandboxed, side-effect-bounded handlers.

    Writes are confined to *artifacts_dir*; reads may come from the read-only
    *workspace_root* or from *artifacts_dir*. Nothing escapes those two roots.
    """

    def __init__(self, workspace_root: Path, artifacts_dir: Path) -> None:
        self.workspace_root = Path(workspace_root)
        self.artifacts_dir = Path(artifacts_dir)
        # The sandbox must exist before the first write; creating it up front
        # also means read_file/list_files never trip over a missing dir.
        ensure_dir(self.artifacts_dir)
        # Relpaths under artifacts_dir written this run, in first-write order.
        self._artifacts: list[str] = []

    def execute(self, tool: str, args: dict) -> str:
        """Run *tool* with *args* and return an observation string.

        Never raises: an unknown tool or a rejected/failed operation becomes an
        ``"error: ..."`` observation the loop can relay back to the model.
        """
        handler = {
            "write_file": self._write_file,
            "read_file": self._read_file,
            "list_files": self._list_files,
            "search_files": self._search_files,
        }.get(tool)
        if handler is None:
            return (
                f"error: unknown tool {tool!r}; "
                "available tools: write_file, read_file, list_files, search_files"
            )
        try:
            return handler(args or {})
        except Exception as exc:  # never let a tool fault abort the loop
            return f"error: tool {tool!r} failed: {exc}"

    def artifacts(self) -> list[str]:
        """Return the relpaths (under artifacts_dir) written so far."""
        return list(self._artifacts)

    # --- tool handlers --------------------------------------------------

    def _write_file(self, args: dict) -> str:
        """Write *content* to *path* under artifacts_dir; refuse escapes."""
        path = str(args.get("path", ""))
        content = str(args.get("content", ""))
        rejection = self._reject_unsafe(path)
        if rejection is not None:
            return rejection
        target = self.artifacts_dir / path
        # Belt-and-suspenders against symlink tricks: confirm the *resolved*
        # destination is still inside the sandbox before touching the disk.
        if not self._within(target, self.artifacts_dir):
            return f"error: refusing to write outside artifacts dir: {path!r}"
        ensure_dir(target.parent)
        target.write_text(content)
        rel = str(target.relative_to(self.artifacts_dir))
        if rel not in self._artifacts:
            self._artifacts.append(rel)
        return f"wrote {len(content)} chars to artifacts/{rel}"

    def _read_file(self, args: dict) -> str:
        """Read *path* from artifacts_dir or the read-only workspace_root."""
        path = str(args.get("path", ""))
        rejection = self._reject_unsafe(path)
        if rejection is not None:
            return rejection
        # Prefer freshly written artifacts over the original workspace copy.
        for root in (self.artifacts_dir, self.workspace_root):
            candidate = root / path
            if self._within(candidate, root) and candidate.is_file():
                return candidate.read_text()
        return f"error: file not found under artifacts or workspace: {path!r}"

    def _list_files(self, args: dict) -> str:
        """List entries of *path* (default '.') in workspace_root or artifacts_dir."""
        path = str(args.get("path", "."))
        rejection = self._reject_unsafe(path)
        if rejection is not None:
            return rejection
        for root in (self.workspace_root, self.artifacts_dir):
            candidate = root / path
            if self._within(candidate, root) and candidate.is_dir():
                names = sorted(p.name for p in candidate.iterdir())
                return "\n".join(names) if names else "(empty)"
        return f"error: directory not found: {path!r}"

    def _search_files(self, args: dict) -> str:
        """Grep-like, read-only substring search over a sandbox directory.

        WHY this tool exists: without it the ACT phase can only ``read_file`` a
        path it already knows -- on a real workspace the dispatched agent is
        blind. ``search_files`` lets the loop *discover* where content lives
        before reading it, which is what makes a goal executable against an
        unfamiliar repo rather than only against pre-known paths.

        Read-only by construction: it walks and reads but never writes, so
        ``artifacts()`` is unaffected. Never raises -- every failure (empty
        query, unsafe/missing path, binary file) degrades to an observation
        string the loop can relay back to the model.
        """
        query = str(args.get("query", ""))
        if not query:
            return "error: search_files requires a non-empty 'query'"
        path = str(args.get("path", "."))
        rejection = self._reject_unsafe(path)
        if rejection is not None:
            return rejection

        # Resolve against workspace_root FIRST, then artifacts_dir -- the same
        # precedence as _list_files: search is directory-oriented and the
        # primary discovery target is the read-only workspace. Only the first
        # root under which *path* is an existing directory is searched (no
        # cross-root merging, mirroring list_files).
        search_root: Path | None = None
        base_root: Path | None = None
        for root in (self.workspace_root, self.artifacts_dir):
            candidate = root / path
            if self._within(candidate, root) and candidate.is_dir():
                base_root = root
                search_root = candidate
                break
        if search_root is None:
            return f"error: directory not found: {path!r}"

        query_lower = query.lower()
        hits: list[tuple[str, int, str]] = []
        # followlinks=False so os.walk never descends INTO a symlinked dir;
        # symlinked *files* still surface in filenames and are guarded below.
        for dirpath, dirnames, filenames in os.walk(search_root, followlinks=False):
            # Prune noise/hidden dirs in place (shared skip set from the
            # filesystem collector, per the iter-09 private-import lesson) and
            # sort so descent order is deterministic.
            dirnames[:] = sorted(
                d for d in dirnames
                if not _is_hidden(d) and d not in _SKIP_DIRS
            )
            for fname in sorted(filenames):
                if _is_hidden(fname):
                    continue
                full = Path(dirpath) / fname
                # Escape guard: a symlinked file resolving outside the sandbox
                # root must never be read (blocks symlink-based exfiltration).
                if not self._within(full, base_root):
                    continue
                try:
                    text = full.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):
                    # Binary/unreadable: skip silently, keep searching.
                    continue
                relpath = full.relative_to(search_root).as_posix()
                for lineno, line in enumerate(text.splitlines(), start=1):
                    if query_lower in line.lower():
                        hits.append((relpath, lineno, line))

        if not hits:
            return f"(no matches for {query!r})"
        # os.walk emits a directory's own files BEFORE descending into its
        # subdirectories, so raw walk order is not strict relpath order. Sort
        # the collected hits to honor the pinned contract: (relpath ascending,
        # then line number ascending), byte-stable across repeat calls.
        hits.sort(key=lambda h: (h[0], h[1]))
        truncated = len(hits) > _SEARCH_MAX_HITS
        lines = [f"{rel}:{lineno}: {line}" for rel, lineno, line in hits[:_SEARCH_MAX_HITS]]
        if truncated:
            lines.append(f"... (truncated at {_SEARCH_MAX_HITS} matches)")
        return "\n".join(lines)

    # --- sandbox helpers ------------------------------------------------

    @staticmethod
    def _reject_unsafe(path: str) -> str | None:
        """Return an error observation for unsafe paths, else None.

        WHY reject textually up front: a '..' segment could climb out of the
        sandbox and an absolute path bypasses the root entirely, so both are
        refused before any resolution -- giving the model a crisp signal.
        """
        if not path:
            return "error: empty path is not allowed"
        if ".." in Path(path).parts:
            return f"error: path traversal ('..') is not allowed: {path!r}"
        if Path(path).is_absolute():
            return f"error: absolute paths are not allowed: {path!r}"
        return None

    @staticmethod
    def _within(target: Path, root: Path) -> bool:
        """True if *target* resolves to a location inside *root*."""
        try:
            target.resolve().relative_to(root.resolve())
            return True
        except ValueError:
            return False
