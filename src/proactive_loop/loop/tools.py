"""Sandboxed tool registry: the ACT phase's only door to the filesystem.

WHY a hard sandbox: the loop hands model-proposed tool calls straight to these
handlers, so any write MUST be confined to a dedicated artifacts directory and
path-traversal / absolute paths MUST be refused. WHY errors are returned rather
than raised: the loop feeds each observation back to the model so it can
recover -- a raised exception would abort an otherwise-recoverable run. Hence
every failure (including an unknown tool) becomes an ``"error: ..."`` string.
"""

from __future__ import annotations

import fnmatch
import os
from pathlib import Path

from proactive_loop.collectors.filesystem import _SKIP_DIRS, _is_hidden
from proactive_loop.models import ensure_dir

# Cap on hits returned by search_files / find_files: keep observations bounded
# so a broad query or glob on a large workspace cannot flood the model's
# context window.
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
            "append_file": self._append_file,
            "find_files": self._find_files,
            "stat_file": self._stat_file,
            "head_file": self._head_file,
            "remove_file": self._remove_file,
            "move_file": self._move_file,
        }.get(tool)
        if handler is None:
            return (
                f"error: unknown tool {tool!r}; "
                "available tools: write_file, read_file, list_files, "
                "search_files, append_file, find_files, stat_file, "
                "head_file, remove_file, move_file"
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

    def _append_file(self, args: dict) -> str:
        """Append *content* to *path* under artifacts_dir; refuse escapes.

        WHY a distinct append primitive: ``write_file`` overwrites, so growing
        an artifact across PLAN->ACT->CHECK steps otherwise forces a
        read-then-rewrite of the whole file through the prompt -- burning
        context tokens and inviting clobber/truncation bugs. Append opens the
        target in ``"a"`` mode so an existing artifact is *extended*, and
        creates the file (and parents) when absent, mirroring ``write_file``'s
        exact sandbox guards (``_reject_unsafe`` + resolved ``_within``) so it
        can never escape the artifacts dir.
        """
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
        # Append mode ("a"), never write_text, so an existing artifact is
        # extended rather than clobbered.
        with target.open("a") as f:
            f.write(content)
        rel = str(target.relative_to(self.artifacts_dir))
        if rel not in self._artifacts:
            self._artifacts.append(rel)
        return f"appended {len(content)} chars to artifacts/{rel}"

    def _remove_file(self, args: dict) -> str:
        """Delete a file under artifacts_dir ONLY; refuse escapes/dirs/missing.

        WHY a destructive verb: ``write_file``/``append_file`` complete
        create/update but the sandbox could never REMOVE a file, so a
        multi-iteration goal that scaffolds the wrong artifact had no clean
        recourse -- ``write_file(path, "")`` merely leaves a stale 0-byte file.
        ``remove_file`` closes the write-side CRUD gap (create/update/read/
        DELETE) and is the mutation mirror of how the read side was completed
        across iters 13/21/26/29.

        Guard order is load-bearing for a destructive op and mirrors
        ``write_file``: ``_reject_unsafe`` (empty/``..``/absolute) FIRST, then
        the *resolved* ``_within`` gate BEFORE any ``unlink`` (so a symlink
        escaping the sandbox can never delete through the link), then existence
        and directory checks. It resolves ONLY against ``artifacts_dir`` -- it
        never touches the read-only ``workspace_root`` -- so a workspace-only
        path degrades to ``no such artifact`` rather than a deletion. Dropping
        the relpath from the tracked ``artifacts()`` list is conditional on
        membership, so an untracked on-disk artifact is still removable without
        raising. Never raises: every failure is an ``"error: ..."`` observation.
        """
        path = str(args.get("path", ""))
        rejection = self._reject_unsafe(path)
        if rejection is not None:
            return rejection
        target = self.artifacts_dir / path
        # Belt-and-suspenders against symlink tricks: confirm the *resolved*
        # target is still inside the sandbox BEFORE any unlink (load-bearing for
        # a destructive op -- must fire before touching disk).
        if not self._within(target, self.artifacts_dir):
            return f"error: refusing to remove outside artifacts dir: {path!r}"
        if not target.exists():
            return f"error: no such artifact: {path!r}"
        if target.is_dir():
            return f"error: refusing to remove a directory: {path!r}"
        target.unlink()
        rel = str(target.relative_to(self.artifacts_dir))
        # Conditional on membership: an untracked on-disk artifact (written
        # directly, not via write_file) is still removable without a KeyError.
        if rel in self._artifacts:
            self._artifacts.remove(rel)
        return f"removed artifacts/{rel}"

    def _move_file(self, args: dict) -> str:
        """Atomically relocate/rename ONE file under artifacts_dir; refuse
        escapes, directories, a missing src, and any existing dst.

        WHY a dedicated move verb: ``write_file``/``append_file``/``read_file``/
        ``remove_file`` gave the sandbox create/update/read/DELETE, but a goal
        that scaffolds an artifact under the wrong name still had NO clean
        relocate -- only ``read_file`` -> ``write_file(new)`` -> ``remove_file(old)``
        (three calls, non-atomic, doubling the byte payload back through the
        model, and leaving a window where both copies exist). ``move_file``
        closes that gap with a single atomic rename, completing the write-side
        mutation family create/update/read/**move**/delete.

        Guard order is load-bearing for a mutation and mirrors ``remove_file``:
        ``_reject_unsafe`` (empty/``..``/absolute) on BOTH ``src`` and ``dst``
        FIRST (src before dst), then the *resolved* ``_within`` gate on src and
        on dst BEFORE any disk write -- so a symlink escaping the sandbox on
        EITHER side can never move a file out of, or write one through the link
        into, an external location. Only after both paths are proven in-sandbox
        do the state checks run: src must exist, src must not be a directory
        (single files only), and dst must NOT already exist (never a silent
        clobber). It resolves ONLY against ``artifacts_dir`` -- never the
        read-only ``workspace_root`` -- so a workspace-only src degrades to
        ``no such artifact``. Missing ``dst`` parent dirs are created, the move
        is ``os.replace`` (atomic rename), and the tracked ``artifacts()`` list
        is updated: the src relpath is dropped IF tracked (conditional on
        membership, so an untracked on-disk src still moves without a KeyError)
        and the dst relpath is appended if absent. Never raises: every failure
        is an ``"error: ..."`` observation the loop can relay back to the model.
        """
        src = str(args.get("src", ""))
        dst = str(args.get("dst", ""))
        # _reject_unsafe on src BEFORE dst (shared empty/``..``/absolute message,
        # src checked first) -- purely textual, so a ``..``/absolute src never
        # reaches path resolution.
        rejection = self._reject_unsafe(src)
        if rejection is not None:
            return rejection
        rejection = self._reject_unsafe(dst)
        if rejection is not None:
            return rejection
        src_target = self.artifacts_dir / src
        dst_target = self.artifacts_dir / dst
        # Belt-and-suspenders against symlink tricks: confirm BOTH the resolved
        # src and the resolved dst are inside the sandbox BEFORE any disk write.
        # The dst gate must fire here (before ensure_dir/os.replace) so a symlink
        # dst can never write a file THROUGH the link outside the sandbox.
        if not self._within(src_target, self.artifacts_dir):
            return f"error: refusing to move outside artifacts dir: {src!r}"
        if not self._within(dst_target, self.artifacts_dir):
            return f"error: refusing to move outside artifacts dir: {dst!r}"
        if not src_target.exists():
            return f"error: no such artifact: {src!r}"
        if src_target.is_dir():
            return f"error: refusing to move a directory: {src!r}"
        # No silent clobber: an existing dst is refused (this also covers a
        # src == dst move, which resolves to the same existing path).
        if dst_target.exists():
            return f"error: destination already exists: {dst!r}"
        ensure_dir(dst_target.parent)
        os.replace(src_target, dst_target)
        src_rel = str(src_target.relative_to(self.artifacts_dir))
        dst_rel = str(dst_target.relative_to(self.artifacts_dir))
        # Drop src IF tracked (untracked on-disk src still moves cleanly), then
        # append dst if not already present -- mirrors write_file's dedupe.
        if src_rel in self._artifacts:
            self._artifacts.remove(src_rel)
        if dst_rel not in self._artifacts:
            self._artifacts.append(dst_rel)
        return f"moved artifacts/{src_rel} -> artifacts/{dst_rel}"

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

    def _head_file(self, args: dict) -> str:
        """Return the first *max_lines* lines of *path* -- a bounded top-of-file
        peek so a goal can judge relevance BEFORE committing context to a full
        ``read_file``.

        WHY this tool exists: ``read_file`` is the sandbox's ONLY unbounded
        reader -- it pulls the WHOLE file into a single observation, so on a
        large log / config / source file it floods the model's context budget in
        one ACT step. ``stat_file`` (iter-26) can *measure* that hazard ("how
        big?") but cannot READ a window. ``head_file`` fills exactly that gap: a
        cheap, bounded peek at the top of a file, completing the sandbox's
        bounded-observation family as find / list / grep / describe / PEEK /
        read.

        Resolution precedence is ``artifacts_dir`` FIRST then ``workspace_root``
        -- IDENTICAL to ``read_file`` / ``stat_file`` -- so ``head_file(x)`` and
        ``read_file(x)`` always read the SAME copy. For a file with ``<=
        max_lines`` lines the return is BYTE-IDENTICAL to ``read_file`` (no
        trailer); for a longer file it is the first *max_lines* lines with their
        original terminators preserved, followed by a single trailer line
        ``... (showing first {max_lines} of {total} lines)`` -- emitted ONLY when
        the file is actually truncated (``total > max_lines``).

        ``max_lines`` defaults to 40 and accepts an int or an integer-valued
        string; a non-positive or non-integer value is rejected (nothing read).
        Path-safety errors (empty / traversal / absolute) are reported BEFORE
        ``max_lines`` validation, mirroring the check order the other tools use.

        Read-only by construction: it reads but never writes, so ``artifacts()``
        is unaffected. Never raises -- an unsafe / empty / bad-arg / missing path
        degrades to an ``"error: ..."`` observation, and an undecodable (binary)
        file surfaces as an ``"error:"`` via ``execute()``'s never-raise wrapper
        (mirroring ``read_file``'s decode behavior).
        """
        path = str(args.get("path", ""))
        # Tool-specific empty/missing-path error BEFORE _reject_unsafe (which
        # would emit the generic "empty path" message), mirroring stat_file.
        if not path:
            return "error: head_file requires a non-empty 'path'"
        # Path-safety (traversal/absolute) is validated BEFORE max_lines so an
        # unsafe path is still reported even alongside a bad max_lines.
        rejection = self._reject_unsafe(path)
        if rejection is not None:
            return rejection
        # max_lines must be a positive integer (int or integer-valued string);
        # a bool, float, None, non-numeric string, or other type is rejected and
        # NOTHING is read on rejection.
        max_lines = self._coerce_positive_int(args.get("max_lines", 40))
        if max_lines is None:
            return "error: head_file 'max_lines' must be a positive integer"
        # Precedence: artifacts_dir FIRST, then workspace_root (see docstring) --
        # identical to read_file, so head_file and read_file read the SAME copy.
        # A symlink escaping both roots fails _within and is never read (falls
        # through to "not found").
        for root in (self.artifacts_dir, self.workspace_root):
            candidate = root / path
            if self._within(candidate, root) and candidate.is_file():
                # read_text() (NOT read_bytes) so a short file is byte-identical
                # to read_file, sharing the same universal-newline handling; an
                # undecodable file raises here and execute()'s wrapper turns it
                # into an "error:" observation.
                text = candidate.read_text()
                # splitlines(keepends=True) preserves each line's terminator and
                # round-trips exactly ("".join(lines) == text), so the
                # not-truncated path returns the file verbatim.
                lines = text.splitlines(keepends=True)
                total = len(lines)
                if total <= max_lines:
                    return text
                head = "".join(lines[:max_lines])
                # total > max_lines means the last kept line is NOT the file's
                # final line, so it always carries a terminator -> the trailer
                # begins on a fresh line.
                return f"{head}... (showing first {max_lines} of {total} lines)"
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

    def _find_files(self, args: dict) -> str:
        """Recursive basename-glob file discovery over a sandbox directory.

        WHY this tool exists: ``search_files`` greps file *content* and
        ``read_file`` needs a path you already know, so neither can answer the
        first question a goal asks against an unfamiliar repo -- "where is the
        ``Makefile``?", "find every ``test_*.py``", "is there a ``pyproject.toml``
        anywhere here?". A file's *name* rarely appears inside another file, and
        an empty or name-only-relevant file has no greppable content at all, so
        content search cannot fill this gap. ``find_files`` walks the tree and
        matches each file's *basename* against a shell glob (``*``/``?``/``[seq]``),
        completing the discovery triad (list one dir / grep content / find by name).

        Read-only by construction: it lists names but never writes and never
        reads file *content* (matching is on the name only), so ``artifacts()``
        is unaffected and it can never fault on a binary/undecodable file. Never
        raises -- every failure (empty pattern, unsafe/missing path) degrades to
        an observation string the loop can relay back to the model.

        Determinism: matching case-folds BOTH operands and uses
        ``fnmatch.fnmatchcase`` (NOT ``fnmatch.fnmatch``, which normalizes case
        via ``os.path.normcase`` and is therefore OS-dependent), so results do
        not depend on the host filesystem's native case sensitivity. The pattern
        matches the basename ONLY -- a pattern containing ``/`` can never match a
        bare filename and so yields the no-match sentinel (documented boundary).
        """
        pattern = str(args.get("pattern", ""))
        if not pattern:
            return "error: find_files requires a non-empty 'pattern'"
        path = str(args.get("path", "."))
        rejection = self._reject_unsafe(path)
        if rejection is not None:
            return rejection

        # Resolve against workspace_root FIRST, then artifacts_dir -- identical
        # precedence to _list_files/_search_files. Only the first root under
        # which *path* is an existing directory is walked (no cross-root merge).
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

        pattern_lower = pattern.lower()
        relpaths: list[str] = []
        # followlinks=False so os.walk never descends INTO a symlinked dir;
        # symlinked *files* still surface in filenames and are guarded below.
        for dirpath, dirnames, filenames in os.walk(search_root, followlinks=False):
            # Prune noise/hidden dirs in place (shared skip set from the
            # filesystem collector) and sort so descent order is deterministic.
            dirnames[:] = sorted(
                d for d in dirnames
                if not _is_hidden(d) and d not in _SKIP_DIRS
            )
            for fname in filenames:
                if _is_hidden(fname):
                    continue
                # Case-fold both sides then fnmatchcase (see docstring) so
                # case-insensitivity is deterministic on every platform. Match
                # the basename only -- the documented boundary.
                if not fnmatch.fnmatchcase(fname.lower(), pattern_lower):
                    continue
                full = Path(dirpath) / fname
                # Escape guard: a symlinked file resolving outside the sandbox
                # root must never be listed (blocks symlink-based name leaks).
                if not self._within(full, base_root):
                    continue
                relpaths.append(full.relative_to(search_root).as_posix())

        if not relpaths:
            return f"(no files matching {pattern!r})"
        # os.walk emits a directory's own files BEFORE descending, so raw walk
        # order is not strict relpath order. Sort to honor the pinned contract
        # (relpath ascending), byte-stable across repeat calls.
        relpaths.sort()
        truncated = len(relpaths) > _SEARCH_MAX_HITS
        lines = relpaths[:_SEARCH_MAX_HITS]
        if truncated:
            lines.append(f"... (truncated at {_SEARCH_MAX_HITS} matches)")
        return "\n".join(lines)

    def _stat_file(self, args: dict) -> str:
        """Describe ONE path in a single bounded line -- the read-only triage
        primitive that lets a goal decide whether a path is worth a full read.

        WHY this tool exists: the loop's only ways to learn about a *specific*
        path are ``read_file`` (which pulls the WHOLE file into one observation
        -- the single unbounded reader, so it can flood the model's context) or
        ``list_files`` (a directory listing only). Neither answers the cheap
        triage question "what IS this path, and how big?" before committing the
        context budget to reading it. ``stat_file`` returns a single bounded
        line -- for a file its type / byte size / line count / extension, for a
        directory its type / direct-entry count -- completing the discovery
        family as find / list / grep / DESCRIBE / read.

        Read-only by construction: it stats and (for a file) reads bytes to
        count lines but never writes, so ``artifacts()`` is unaffected.
        Deterministic: it reports NO mtime / timestamp / permission field, and
        the line count is a *byte-level* ``splitlines()`` that never decodes --
        so it can never fault on a binary file and is OS-independent. Never
        raises -- every failure (empty path, unsafe path, missing path) degrades
        to an ``"error: ..."`` observation the loop can relay back to the model.

        Root precedence is ``artifacts_dir`` FIRST, then ``workspace_root`` --
        IDENTICAL to ``read_file`` (and deliberately the OPPOSITE of
        ``list_files``/``search_files``/``find_files``), so ``stat_file(x)`` and
        ``read_file(x)`` always resolve the SAME copy and the reported
        bytes/lines match what ``read_file`` returns.
        """
        path = str(args.get("path", ""))
        # Tool-specific empty/missing-path error BEFORE _reject_unsafe (which
        # would emit the generic "empty path" message), mirroring how
        # search_files/find_files check their required arg first.
        if not path:
            return "error: stat_file requires a non-empty 'path'"
        rejection = self._reject_unsafe(path)
        if rejection is not None:
            return rejection
        # Echo the input path back, normalized to POSIX "/" separators.
        relpath = Path(path).as_posix()
        # Precedence: artifacts_dir FIRST, then workspace_root (see docstring).
        # Only the first root under which the resolved path is within-root AND
        # exists is described; a symlink escaping both roots fails _within and
        # so is never described (falls through to "no such path").
        for root in (self.artifacts_dir, self.workspace_root):
            candidate = root / path
            if not self._within(candidate, root):
                continue
            if candidate.is_file():
                data = candidate.read_bytes()
                suffix = Path(path).suffix
                ext = suffix if suffix else "(none)"
                # Byte-level splitlines(): never decodes, so a binary file
                # cannot fault the count and the result is OS-independent.
                return (
                    f"{relpath}  type=file  bytes={len(data)}  "
                    f"lines={len(data.splitlines())}  ext={ext}"
                )
            if candidate.is_dir():
                # Direct children only (files + subdirs, INCLUDING hidden
                # entries and skip-dirs), non-recursive -- mirrors list_files'
                # unfiltered listing.
                entries = len(list(candidate.iterdir()))
                return f"{relpath}  type=dir  entries={entries}"
        return f"error: no such path: {path!r}"

    # --- sandbox helpers ------------------------------------------------

    @staticmethod
    def _coerce_positive_int(value: object) -> int | None:
        """Coerce *value* to a strictly-positive int, else return ``None``.

        Accepts a genuine ``int`` or an integer-valued ``str`` (e.g. ``"3"``);
        rejects ``bool`` (an int subclass, but a boolean count is a caller
        error, so ``True``/``False`` are NOT silently treated as ``1``/``0``),
        ``float``, ``None``, non-numeric strings, and every other type. Used to
        validate ``head_file``'s ``max_lines`` (must be a positive integer).
        """
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            n = value
        elif isinstance(value, str):
            try:
                n = int(value)
            except ValueError:
                return None
        else:
            return None
        return n if n > 0 else None

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
