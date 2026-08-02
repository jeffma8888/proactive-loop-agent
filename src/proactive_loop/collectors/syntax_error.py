"""SyntaxErrorCollector: surface Python files that will not PARSE as L2 signals.

WHY this collector exists: the scout's proactivity ceiling is set entirely by
*what its collectors can perceive* (SPEC sections 1, 4.1). A high-urgency,
zero-ambiguity hazard was invisible to every existing collector -- a ``*.py``
file that is *broken at the parse level* (a stray colon, an unclosed bracket, a
bad indent): code that cannot even be imported, that silently breaks a test run
or a deploy. This is a genuine PERCEPTION HOLE, not a near-copy of an existing
collector, because it introduces a categorically new MECHANISM and SIGNAL CLASS:

  * ``TodoCollector`` / ``MergeConflictCollector`` *grep* for a marker string;
    they never understand the file as code.
  * ``TestPostureCollector`` / ``LargeFileCollector`` count files or bytes.
  * ``SecretFileCollector`` matches by basename.

None of them PARSE. This collector runs the stdlib parser -- ``compile(src, fn,
"exec")`` -- and emits one ``kind="syntax_error"`` signal per file that raises a
``SyntaxError``. A ``SyntaxError`` is DETERMINISTIC and unambiguous (the parser
either accepts the source or it does not), so unlike a regex secret/style scan
this carries ZERO false positives: it stays SILENT on a healthy repo and fires
only on a genuine "this file can't even run" problem -- the same
quiet-until-a-real-problem profile that ``git_state`` / ``merge_conflict`` /
``secret_file`` established.

PARSE-ONLY is the load-bearing SAFETY property. ``compile(..., "exec")`` builds
a code object but NEVER runs the user's code -- no ``exec`` / ``eval`` /
``import`` / subprocess -- so scanning a workspace can never trigger a side
effect from the code being scanned. Critical on a "safe by design" public repo
and on a *dispatched* proactive loop.

NO content leak. The signal carries only the RELATIVE, forward-slashed path plus
the error's 1-based line number (``summary``) and the parser's short diagnostic
message (``detail`` = ``SyntaxError.msg``, e.g. "invalid syntax"). It DELIBERATELY
omits ``SyntaxError.text`` -- the offending source line -- so no file content
ever reaches the slate.

Pure stdlib (``os`` / ``pathlib`` / builtin ``compile``) only, so the runtime
stays pydantic-v2-only and fully offline; never raises -> ``[]``. A new
``kind="syntax_error"`` flows into the synthesis prompt automatically because
``synthesizer._build_prompt`` iterates ``snapshot.by_kind()``, so this file plus
the two-line registry wiring is the whole cost -- additive, no version bump
(mirrors iters 09/11/16/20/28/37/42/63/70).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# Reuse the EXACT skip rules RecentFilesCollector uses (the SPEC-sanctioned
# shared seam, mirroring merge_conflict.py / large_file.py) so a broken file
# buried in node_modules/.venv/a hidden dir is invisible here too.
from proactive_loop.collectors.filesystem import _SKIP_DIRS, _is_hidden
from proactive_loop.models import ContextSignal


@dataclass
class SyntaxErrorCollector:
    """Emit one ContextSignal per ``*.py`` file that fails to PARSE under *root*.

    WHY a dataclass with defaults: mirrors the sibling collectors so
    ``all_collectors()`` can construct it with no arguments, while a caller
    scanning a very large tree can still cap the number of files reported.
    """

    name: str = "syntax_error"
    max_items: int = 30

    def collect(self, root: Path) -> list[ContextSignal]:
        """Walk *root* and return one signal per un-parseable ``*.py`` file.

        Never raises: any filesystem, decode, or parser error degrades to ``[]``,
        honouring the Collector contract so one broken tree can never abort a
        scan.
        """
        try:
            return self._collect(root)
        except Exception:
            return []

    def _collect(self, root: Path) -> list[ContextSignal]:
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
                # A hidden FILE (name starting with '.') is skipped too, so
                # `.broken.py` is never scanned.
                if _is_hidden(fname):
                    continue
                # `compile` only understands Python, so scope is `*.py` ONLY
                # (case-insensitive). `.pyi` stubs are intentionally excluded.
                if Path(fname).suffix.lower() != ".py":
                    continue
                pair = self._check_file(root, Path(dirpath) / fname)
                if pair is not None:
                    found.append(pair)

        # Deterministic: sort by relpath ascending, then cap at max_items (so the
        # kept set is the max_items lexicographically-smallest relpaths).
        found.sort(key=lambda pair: pair[0])
        return [signal for _, signal in found[: self.max_items]]

    def _check_file(
        self, root: Path, full: Path
    ) -> tuple[str, ContextSignal] | None:
        """Parse-check one ``*.py`` file; return its ``(rel, signal)`` or None.

        Returns None (SKIP, not a signal) for anything that is not a genuine
        parse failure of decodable Python: an unreadable file, a non-UTF-8 /
        undecodable file, a NUL-byte file, or pathological input.
        """
        # Read STRICT UTF-8 (unlike merge_conflict's errors="replace"): a
        # syntax-check is only meaningful on genuinely-decodable Python, so a
        # non-UTF-8 file is "not a reportable Python file", not a crash.
        try:
            text = full.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None

        # A NUL byte decodes fine as UTF-8, but `compile` rejects it -- and on
        # CPython 3.13 it raises SyntaxError ("source code string cannot contain
        # null bytes"), NOT ValueError. Guarding here (rather than relying on the
        # exception type, which varies by version) keeps a binary-ish ".py" from
        # masquerading as a real syntax error: a NUL-containing file is not
        # decodable Python, so it is SKIPPED, satisfying the no-false-positive bar.
        if "\x00" in text:
            return None

        try:
            # Parse-only: builds a code object, NEVER runs the code (no
            # exec/eval/import). This is the load-bearing safety property.
            compile(text, str(full), "exec")
        except SyntaxError as exc:
            return self._signal_for(root, full, exc)
        except (ValueError, MemoryError, RecursionError):
            # Pathological / oversized source degrades to "skipped", never a crash.
            return None
        return None

    def _signal_for(
        self, root: Path, full: Path, exc: SyntaxError
    ) -> tuple[str, ContextSignal]:
        """Build one syntax-error signal for *full*.

        ``summary`` = relpath + the 1-based error line ONLY; ``detail`` = the
        parser's short ``msg`` ONLY. ``exc.text`` (the offending SOURCE line) is
        DELIBERATELY never included, so no file content leaks into the slate.
        """
        rel = self._relative(root, full)
        lineno = exc.lineno or 0
        signal = ContextSignal(
            source=self.name,
            kind="syntax_error",
            summary=f"{rel}: syntax error at line {lineno}",
            detail=(exc.msg or ""),
            path=rel,
            weight=0.9,
            timestamp=None,
        )
        return rel, signal

    @staticmethod
    def _relative(root: Path, full: Path) -> str:
        """Path of *full* relative to *root*, always forward-slashed."""
        try:
            return full.relative_to(root).as_posix()
        except ValueError:
            return full.as_posix()
