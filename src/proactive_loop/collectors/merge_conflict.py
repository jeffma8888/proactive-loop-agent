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
PUBLIC repo the unambiguous signal is the correct one.

SCAN ONCE PER CONTENT. This collector line-scans EVERY line of every
scanned-extension file it walks -- the widest extension set of the three text
collectors -- and in the vision's long-lived mode that whole pass is repeated
work: ``pla watch`` runs a full collect every tick over a tree that mostly did
not change. Its two memoized siblings (``todos``' item memo, ``syntax_error``'s
parse memo) already collapse on a second sweep while this collector still paid
the full per-line cost every tick, so the marker COUNT is now memoized in a
bounded, module-level map keyed on a digest of the decoded text (see the
marker-memo block below). Output is unchanged: a hit returns exactly the count
the line scan would have produced for that same text.

Pure stdlib (``os``/``pathlib``/``hashlib``) only, so the runtime stays
pydantic-v2-only and fully offline; never raises -> ``[]``.
"""

from __future__ import annotations

import hashlib
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


# ---------------------------------------------------------------------------
# Marker memo: one per-line marker scan per distinct FILE CONTENT, process-wide.
#
# WHY MODULE level and not an instance attribute: ``all_collectors()`` builds a
# FRESH ``MergeConflictCollector`` on every call and ``cli._collect`` calls
# ``all_collectors()`` once per invocation, so ``pla watch`` constructs a new
# instance every tick. An instance memo would therefore never hit in the ONE
# workload this exists to fix, while still passing any test that reuses a single
# collector object: a fail-silent perf regression that measures as a win. Being
# process-wide, the state is made INSPECTABLE (``merge_conflict_memo_stats``) and
# RESETTABLE (``clear_merge_conflict_memo``) rather than hidden. This mirrors the
# seams ``syntax_error`` and ``todos`` already ship; all three are deliberately
# SEPARATE maps with no shared helper -- the convention ``todos.py`` documents --
# so no module's oracle can be broken by a change made for another.
#
# WHY ONE cap here where ``todos`` needs TWO: ``todos`` retains a per-file item
# LIST whose length grows with the file, so its entry cap alone does not bound
# memory and it exports a second per-value item cap. The value retained here is a
# single ``int``, so ``MERGE_CONFLICT_MEMO_MAX_ENTRIES`` bounds this map
# completely -- that asymmetry is the whole reason the two shapes differ.
#
# The memo is a pure speed-up, never a semantic change: a marker count is a pure
# function of the text (``_count_markers`` reads nothing but its ``str``
# argument), so a hit, a miss and an eviction all yield byte-identical signals.
# ---------------------------------------------------------------------------

# Hard cap on retained marker counts, so scanning an unbounded monorepo cannot
# grow this map without limit. 4096 marker counts, each a single ``int``, keep
# this map well under 1 MB, and 4096 scanned files covers a typical service repo
# outright. The bound is absolute rather than a ratio against this checkout's own
# scanned-file count, which would decay on every commit -- see
# ``tests/test_source_comment_bounds.py``. Past the cap the oldest entries are
# evicted, which costs speed and NEVER correctness. Read at call time, so a test
# may lower it.
MERGE_CONFLICT_MEMO_MAX_ENTRIES: int = 4096

# 128 bits of digest -- the same size both sibling memos use, restated here rather
# than imported, because another collector's PRIVATE constant is not this module's
# dependency to take (the separate-maps convention above). Collisions are the only
# way this memo could serve a wrong count, and at 2**-128 per pair that is far
# below the probability of the filesystem handing back wrong bytes; a shorter
# digest saves nothing measurable.
_DIGEST_SIZE: int = 16

_MARKER_MEMO: dict[bytes, int] = {}
_MARKER_MEMO_COUNTS: dict[str, int] = {"hits": 0, "misses": 0}


def clear_merge_conflict_memo() -> None:
    """Empty the marker memo and zero its counters.

    WHY this is public on a module that otherwise exposes one collector class: a
    process-wide cache that cannot be reset is hidden global state -- untestable,
    and a liability in the long-lived ``watch`` process it exists to serve. It
    clears IN PLACE rather than rebinding, so any holder of the dict object sees
    the same emptying. Touches ONLY this memo: ``todos``' item memo and
    ``syntax_error``'s parse memo are separate maps and are unaffected.
    """
    _MARKER_MEMO.clear()
    _MARKER_MEMO_COUNTS["hits"] = 0
    _MARKER_MEMO_COUNTS["misses"] = 0


def merge_conflict_memo_stats() -> dict[str, int]:
    """Return a fresh snapshot: ``{"hits", "misses", "entries"}``.

    ``hits`` = marker counts served without scanning; ``misses`` = line scans
    performed (whether or not the result was retained); ``entries`` = counts
    currently retained, never above ``MERGE_CONFLICT_MEMO_MAX_ENTRIES``. A COPY is
    returned so a caller cannot mutate the live counters, and ``entries`` is
    DERIVED from the map (never tracked separately) so it cannot drift from what
    is actually retained.
    """
    return {
        "hits": _MARKER_MEMO_COUNTS["hits"],
        "misses": _MARKER_MEMO_COUNTS["misses"],
        "entries": len(_MARKER_MEMO),
    }


def _remember_count(digest: bytes, count: int) -> None:
    """Retain one marker count under the cap, evicting the OLDEST entries first.

    FIFO (``dict`` preserves insertion order) rather than LRU: eviction order is
    then a pure function of the insertion sequence, so two identical scans evict
    identically -- deterministic, which access-ordered eviction is not without
    extra bookkeeping this cannot justify. A cap of ``<= 0`` disables retention
    entirely (nothing is stored, so nothing can hit), which keeps the "entries
    never exceeds the cap" invariant true for every cap value.
    """
    cap = MERGE_CONFLICT_MEMO_MAX_ENTRIES
    if cap <= 0:
        return
    while len(_MARKER_MEMO) >= cap:
        del _MARKER_MEMO[next(iter(_MARKER_MEMO))]
    _MARKER_MEMO[digest] = count


def _memoized_count_markers(text: str) -> int:
    """Return ``_count_markers(text)``, line-scanning once per distinct content.

    WHY the key is a DIGEST OF THE DECODED TEXT and never ``(path, mtime, size)``:
    this memo may only ever return what the scan would return TODAY, and with a
    content digest that proof is DEFINITIONAL -- ``_count_markers`` reads nothing
    but its ``str`` argument, so digest equality IS input equality and an edited
    file cannot hit a stale entry. An mtime/size key cannot promise that (a coarse
    mtime plus an unchanged size serves a stale count), and trading determinism
    for speed is not a trade worth making where ``make check`` / CI arm
    ``pla signals --fail-on-kind merge_conflict`` and a wrong count is a red
    PUBLIC build.

    WHY the digest is taken over the DECODED TEXT rather than the raw file bytes:
    ``text`` is exactly the argument handed to the scan, so digest equality
    implies an identical scan input and therefore an identical count -- the
    soundness proof is about the memoized function's INPUT, not about the file.
    (Digesting raw bytes would need a second read: the single
    ``text_source.read_text`` decode per candidate is a pinned seam.) Note this
    is a property of the TEXT and not of the bytes: ``read_text`` applies
    universal-newline translation, so a CRLF file and its LF twin share ONE entry
    -- correctly, because the scan sees the identical string in both cases.

    WHY the COUNT and not the signal: a ``ContextSignal`` carries the file's
    RELATIVE PATH, which differs per file while the count does not. Caching the
    path-free count is precisely what lets K byte-identical marked files share ONE
    scan and still each report their own path and their own count.

    WHY this WRAPS ``_count_markers`` instead of memoizing inside it: the scan
    stays a pure, path-free function of one ``str``, which is the property the
    soundness argument above rests on, and its existing unit tests keep measuring
    the SCAN rather than the cache.
    """
    digest = hashlib.blake2b(text.encode("utf-8"), digest_size=_DIGEST_SIZE).digest()
    if digest in _MARKER_MEMO:
        _MARKER_MEMO_COUNTS["hits"] += 1
        return _MARKER_MEMO[digest]

    count = _count_markers(text)
    # Counted BEFORE retention, so ``misses`` records scans performed and stays
    # truthful when a ``<= 0`` cap declines to retain anything.
    _MARKER_MEMO_COUNTS["misses"] += 1
    _remember_count(digest, count)
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
                # The line scan is memoized on a digest of this text (see the
                # marker-memo block), so a repeated collect over an unchanged
                # tree still reads but never re-scans. Semantically identical
                # to calling ``_count_markers(text)`` directly.
                count = _memoized_count_markers(text)
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
