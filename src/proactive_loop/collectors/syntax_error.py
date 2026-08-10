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

PARSE ONCE PER CONTENT. Parsing is by far the most expensive thing this
product perceives with: measured with the shipped ``pla signals --timings``
instrument at commit ``f3abb5c``, this collector is 190.60 ms of a 359.24 ms
full collect (53.1%), and ~141 ms of that is the ``compile()`` call itself.
That cost is REPEATED work in the vision's long-lived mode -- ``pla watch``
runs a full collect every tick over a tree that mostly did not change -- so the
parse verdict is memoized in a bounded, module-level map keyed on a digest of
the source (see the parse-memo block below). Output is unchanged: the memo
returns exactly what ``compile`` would have returned for that same source
text.

Pure stdlib (``os`` / ``pathlib`` / ``hashlib`` / builtin ``compile``) only, so
the runtime stays pydantic-v2-only and fully offline; never raises -> ``[]``. A new
``kind="syntax_error"`` flows into the synthesis prompt automatically because
``synthesizer._build_prompt`` iterates ``snapshot.by_kind()``, so this file plus
the two-line registry wiring is the whole cost -- additive, no version bump
(mirrors iters 09/11/16/20/28/37/42/63/70).
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from proactive_loop.collectors.base import BaseCollector
# Reuse the EXACT skip rules RecentFilesCollector uses (the SPEC-sanctioned
# shared seam, mirroring merge_conflict.py / large_file.py) so a broken file
# buried in node_modules/.venv/a hidden dir is invisible here too.
from proactive_loop.collectors.filesystem import _SKIP_DIRS, _is_hidden
from proactive_loop.collectors.large_file import LARGE_FILE_MIN_BYTES
# The MODULE is imported (not its ``read_text`` function) so all three content
# collectors resolve the provider through ONE patchable attribute.
from proactive_loop.collectors import text_source
from proactive_loop.models import ContextSignal


# ---------------------------------------------------------------------------
# Parse memo: one parse per distinct SOURCE CONTENT, process-wide.
#
# WHY MODULE level and not an instance attribute: ``all_collectors()`` builds a
# FRESH ``SyntaxErrorCollector`` on every call, and ``cli._collect`` calls
# ``all_collectors()`` once per invocation -- so ``pla watch`` constructs a new
# instance every tick. An instance memo would therefore never hit in the ONE
# workload this exists to fix, while still passing any test that reuses a single
# collector object: a fail-silent perf regression that measures as a win. The
# state is process-wide, so it is made INSPECTABLE (``parse_memo_stats``) and
# RESETTABLE (``clear_parse_memo``) rather than hidden.
#
# The memo is a pure speed-up, never a semantic change: a verdict is a pure
# function of the source, so a hit, a miss and an eviction all yield byte-
# identical signals.
# ---------------------------------------------------------------------------

# A file's parse outcome: ``None`` == "parses clean", ``(lineno, msg)`` == the
# 1-based error line plus the parser's short message for a ``SyntaxError``.
_Verdict = tuple[int, str] | None

# Hard cap on retained verdicts, so a scan of an unbounded monorepo cannot grow
# this map without limit. 4096 is ~24x this repo's own 173 ``*.py`` files and
# covers a typical service repo outright, at well under 1 MB of small tuples;
# past the cap the oldest entries are evicted, which costs speed and NEVER
# correctness. Read at call time, so a test may lower it.
PARSE_MEMO_MAX_ENTRIES: int = 4096

# 128 bits of digest. Collisions are the only way this memo could serve a wrong
# verdict, and at 2**-128 per pair that is far below the probability of the
# filesystem handing back wrong bytes; a shorter digest saves nothing measurable.
_DIGEST_SIZE: int = 16

_PARSE_MEMO: dict[bytes, _Verdict] = {}
_PARSE_MEMO_COUNTS: dict[str, int] = {"hits": 0, "misses": 0}


def clear_parse_memo() -> None:
    """Empty the parse memo and zero its counters.

    WHY this is public on a module that otherwise exposes one collector class: a
    process-wide cache that cannot be reset is hidden global state -- untestable,
    and a liability in the long-lived ``watch`` process it exists to serve. It
    clears IN PLACE rather than rebinding, so any holder of the dict object sees
    the same emptying.
    """
    _PARSE_MEMO.clear()
    _PARSE_MEMO_COUNTS["hits"] = 0
    _PARSE_MEMO_COUNTS["misses"] = 0


def parse_memo_stats() -> dict[str, int]:
    """Return a fresh snapshot: ``{"hits", "misses", "entries"}``.

    ``hits`` = verdicts served without parsing; ``misses`` = parses performed AND
    recorded; ``entries`` = verdicts currently retained, never above
    ``PARSE_MEMO_MAX_ENTRIES``. A COPY is returned so a caller cannot mutate the
    live counters, and ``entries`` is DERIVED from the map (never tracked
    separately) so it cannot drift from what is actually retained.
    """
    return {
        "hits": _PARSE_MEMO_COUNTS["hits"],
        "misses": _PARSE_MEMO_COUNTS["misses"],
        "entries": len(_PARSE_MEMO),
    }


def _remember_verdict(digest: bytes, verdict: _Verdict) -> None:
    """Retain one verdict under the cap, evicting the OLDEST entries first.

    FIFO (``dict`` preserves insertion order) rather than LRU: eviction order is
    then a pure function of the insertion sequence, so two identical scans evict
    identically -- deterministic, which access-ordered eviction is not without
    extra bookkeeping this cannot justify. A cap of ``<= 0`` disables retention
    entirely (nothing is stored, so nothing can hit), which keeps the "entries
    never exceeds the cap" invariant true for every cap value.
    """
    cap = PARSE_MEMO_MAX_ENTRIES
    if cap <= 0:
        return
    while len(_PARSE_MEMO) >= cap:
        del _PARSE_MEMO[next(iter(_PARSE_MEMO))]
    _PARSE_MEMO[digest] = verdict


def _parse_verdict(text: str, filename: str) -> _Verdict:
    """Return *text*'s parse verdict, compiling at most once per distinct source.

    WHY the key is a DIGEST OF THE SOURCE and never ``(path, mtime, size)``: this
    memo may only ever return what the parser would return TODAY, and with a
    content digest that proof is definitional -- digest equality IS content
    equality, so an edited file cannot hit a stale entry. An mtime/size key
    cannot promise that (a coarse mtime plus an unchanged size serves a stale
    verdict), and trading determinism for speed is not a trade worth making here.

    WHY the digest is taken over the DECODED TEXT rather than the raw file
    bytes: ``text`` is exactly the argument handed to ``compile``, so digest
    equality implies identical compiler input and therefore an identical
    verdict -- the soundness proof is about the memoized function's INPUT, not
    about the file. (Digesting raw bytes would need a second read: the single
    ``Path.read_text`` decode is a pinned seam, since the oversized-file
    guard's proof counts exactly one read per candidate.) Note this is a
    property of the TEXT and not of the bytes: ``read_text`` applies
    universal-newline translation, so a CRLF file and its LF twin share ONE
    entry -- correctly, because ``compile`` sees the identical source in both
    cases.

    WHY the VERDICT and not the signal: a ``ContextSignal`` carries the file's
    relative path, which differs per file while the verdict does not. Caching the
    verdict is precisely what lets K byte-identical broken files share ONE parse
    and still each report their own path.
    """
    digest = hashlib.blake2b(text.encode("utf-8"), digest_size=_DIGEST_SIZE).digest()
    if digest in _PARSE_MEMO:
        _PARSE_MEMO_COUNTS["hits"] += 1
        return _PARSE_MEMO[digest]

    try:
        # Parse-only: builds a code object, NEVER runs the code (no
        # exec/eval/import). This is the load-bearing safety property.
        compile(text, filename, "exec")
    except SyntaxError as exc:
        # Only ``lineno``/``msg`` are kept -- and NEVER ``exc.text`` (the
        # offending source line) or ``exc.filename``, so the retained verdict
        # holds no file content and nothing path-specific.
        verdict: _Verdict = (exc.lineno or 0, exc.msg or "")
    except (ValueError, MemoryError, RecursionError):
        # Pathological / oversized source degrades to "skipped", never a crash --
        # and is deliberately NOT retained: a MemoryError or RecursionError is a
        # property of the RUNTIME, not of the bytes, so memoizing it could let a
        # transient failure mask a real SyntaxError in a later collect.
        return None
    else:
        verdict = None

    _PARSE_MEMO_COUNTS["misses"] += 1
    _remember_verdict(digest, verdict)
    return verdict


@dataclass
class SyntaxErrorCollector(BaseCollector):
    """Emit one ContextSignal per ``*.py`` file that fails to PARSE under *root*.

    WHY a dataclass with defaults: mirrors the sibling collectors so
    ``all_collectors()`` can construct it with no arguments, while a caller
    scanning a very large tree can still cap the number of files reported.

    WHY *max_read_bytes*: parsing requires DECODING the whole file first, and the
    ``MemoryError``/``RecursionError`` guard in ``_check_file`` is REACTIVE -- it
    only fires after the bytes are already in memory. Capping ``st_size`` makes the
    module docstring's "oversized source degrades to skipped" claim PROACTIVE and
    true. This is not a blind spot: the cap equals ``LARGE_FILE_MIN_BYTES``, and
    ``LargeFileCollector`` reports at ``size >= LARGE_FILE_MIN_BYTES`` from
    ``st_size`` alone, so every file skipped here is already reported there as a
    ``kind="large_file"`` signal -- skipped-here implies reported-there. The
    comparison is STRICTLY greater, deliberately overlapping that inclusive ``>=``
    by exactly one size so the ranges leave no gap.
    """

    name: str = "syntax_error"
    max_items: int = 30
    max_read_bytes: int = LARGE_FILE_MIN_BYTES

    def _collect(self, root: Path) -> list[ContextSignal]:
        """Walk *root* and return one signal per un-parseable ``*.py`` file."""
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
        parse failure of decodable Python: an unreadable file, a file LARGER than
        *max_read_bytes*, a non-UTF-8 / undecodable file, a NUL-byte file, or
        pathological input.
        """
        # Read STRICT UTF-8 (unlike merge_conflict's errors="replace"): a
        # syntax-check is only meaningful on genuinely-decodable Python, so a
        # non-UTF-8 file is "not a reportable Python file", not a crash.
        #
        # The size read sits inside the SAME try as the decode, so a file that
        # vanishes or denies stat() between the walk and here is SKIPPED exactly
        # like an unreadable one -- never an exception escaping to abort the walk.
        # Skipping oversized source BEFORE the read is what makes the module
        # docstring's "oversized source degrades to skipped" guarantee proactive:
        # the reactive MemoryError/RecursionError branch (now in
        # ``_parse_verdict``) can only help once the whole file is already decoded.
        try:
            if full.stat().st_size > self.max_read_bytes:
                return None
            # Shared per-scan decode (see text_source), with this collector's
            # STRICT policy preserved: the provider attempts a strict read first,
            # so a decodable file yields the identical string the plain
            # ``read_text`` above produced, and undecodable bytes yield None --
            # the same SKIP the ``UnicodeDecodeError`` clause below used to give.
            # That clause is KEPT: it is the guarantee that a future direct read
            # here can never leak a decode error into the walk.
            text = text_source.read_text(full, strict=True)
        except (OSError, UnicodeDecodeError):
            return None
        if text is None:
            # Not decodable UTF-8 -> "not a reportable Python file", never a
            # crash and never a signal (the file's bytes are still scanned by
            # todos/merge_conflict, which report replacement-charred text).
            return None

        # A NUL byte decodes fine as UTF-8, but `compile` rejects it -- and on
        # CPython 3.13 it raises SyntaxError ("source code string cannot contain
        # null bytes"), NOT ValueError. Guarding here (rather than relying on the
        # exception type, which varies by version) keeps a binary-ish ".py" from
        # masquerading as a real syntax error: a NUL-containing file is not
        # decodable Python, so it is SKIPPED, satisfying the no-false-positive bar.
        if "\x00" in text:
            return None

        # The parse itself is memoized on a digest of this source, so a repeated
        # collect over an unchanged tree reads but never re-compiles. Passing
        # ``str(full)`` stays correct on a memo HIT (where ``compile`` is not
        # called at all) because the verdict is read only for its line number and
        # message, both properties of the SOURCE and never of this argument.
        verdict = _parse_verdict(text, str(full))
        if verdict is None:
            return None
        lineno, msg = verdict
        return self._signal_for(root, full, lineno, msg)

    def _signal_for(
        self, root: Path, full: Path, lineno: int, msg: str
    ) -> tuple[str, ContextSignal]:
        """Build one syntax-error signal for *full* from its parse verdict.

        Takes the VERDICT (1-based error line + the parser's short message)
        rather than the ``SyntaxError`` object, because a memoized verdict has no
        exception object behind it -- and this method never read anything else
        off the exception anyway. ``summary`` = relpath + the error line ONLY;
        ``detail`` = the parser's ``msg`` ONLY. ``SyntaxError.text`` (the
        offending SOURCE line) is DELIBERATELY never included, so no file content
        leaks into the slate.
        """
        rel = self._relative(root, full)
        signal = ContextSignal(
            source=self.name,
            kind="syntax_error",
            summary=f"{rel}: syntax error at line {lineno}",
            detail=msg,
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
