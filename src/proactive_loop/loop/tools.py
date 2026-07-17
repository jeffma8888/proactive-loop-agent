"""Sandboxed tool registry: the ACT phase's only door to the filesystem.

WHY a hard sandbox: the loop hands model-proposed tool calls straight to these
handlers, so any write MUST be confined to a dedicated artifacts directory and
path-traversal / absolute paths MUST be refused. WHY errors are returned rather
than raised: the loop feeds each observation back to the model so it can
recover -- a raised exception would abort an otherwise-recoverable run. Hence
every failure (including an unknown tool) becomes an ``"error: ..."`` string.
"""

from __future__ import annotations

from pathlib import Path

from proactive_loop.models import ensure_dir


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
        }.get(tool)
        if handler is None:
            return (
                f"error: unknown tool {tool!r}; "
                "available tools: write_file, read_file, list_files"
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
