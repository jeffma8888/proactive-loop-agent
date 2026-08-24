r"""text_source: read and decode each file at most ONCE per scan.

WHY this module exists: three collectors -- ``todos``, ``merge_conflict`` and
``syntax_error`` -- each walk the tree and independently ``read_text`` the SAME
files, so one scan pays for the same decode two or three times. Measured on this
repo before this seam existed: one ``cli._collect`` made **578** ``open()`` calls
for a union of **197** distinct files (381 redundant, 66%), with **186** files
read by all three, spending **50.09 ms** on I/O for a **16.70 ms** answer.
Measured AFTER this seam landed (iter-129): **583 -> 200** ``Path.read_text``
calls over 199 distinct paths in one scan -- that read count is the exact,
regime-free result. The wall-clock win is regime-DEPENDENT and labelling it
honestly matters: **-21%** on a one-shot ``pla scan`` / CI invocation
(421 -> 333 ms median of 5 paired samples) but only **-6%** on a warm
``pla watch`` tick (138 -> 129 ms) -- because the two shipped content memos
(``todos._todo_items``, ``syntax_error._parse_verdict``) have already removed
the duplicated CPU from a warm tick; they cannot remove this I/O, because each
one still needs the decoded text to compute its digest key. This module is the
missing half: the I/O.

LIFETIME IS ONE SCAN, and that is the whole safety argument. Nothing is retained
between scans: ``cli._collect`` opens exactly one :func:`scan_scope`, and outside
a scope this module is a pure PASS-THROUGH that reads the file every call. So a
direct ``TodoCollector().collect(root)`` behaves exactly as it did before this
module existed, a ``pla watch`` tick can never serve text from the previous tick,
and there is no ``(path, mtime, size)`` staleness key anywhere -- the shape a
previous roadmap row rejected. Within one scan the cache does make the three
collectors agree on a single point-in-time view of a file that is edited
mid-scan; a scan was never atomic to begin with, so this is strictly more
self-consistent than the three-independent-reads it replaces.

TWO DECODE POLICIES, PRESERVED EXACTLY. ``syntax_error`` reads STRICT UTF-8 and
SKIPS a file whose bytes do not decode ("a syntax-check is only meaningful on
genuinely-decodable Python"), while ``todos`` and ``merge_conflict`` read with
``errors="replace"`` and DO report findings inside such a file. Collapsing those
into one policy would be a correctness regression in either direction: a
replace-only provider makes ``syntax_error`` parse a file it currently refuses,
which can emit a FALSE ``syntax_error`` -- and ``make check`` / CI run ``pla
signals --fail-on-kind syntax_error``, so that turns the PUBLIC build red with
exit 5 -- while a strict-only provider silently DELETES live ``todo`` and
``merge_conflict`` findings. So a MISS always attempts the strict read FIRST: if
it succeeds, the resulting string is byte-identical to what an
``errors="replace"`` read would have produced (the ``errors=`` argument is
unreachable when there are no errors), so all three callers can share that one
string with zero behavior change. Only when the strict read raises
``UnicodeDecodeError`` is a second ``errors="replace"`` read performed, and the
entry is then marked NOT strict-clean: replace-callers are served, and a strict
caller gets ``None`` -- skip, exactly as today.

READS THROUGH ``Path.read_text``, NEVER ``read_bytes().decode()``. ``read_text``
is TEXT mode, so it applies universal-newline translation while a manual decode
does not (for ``b"a\r\nb\r\n"`` they return ``'a\nb\n'`` and ``'a\r\nb\r\n'``
respectively). Both shipped memos digest the DECODED text and both document that
"a CRLF file and its LF twin share ONE entry"; a bytes-based provider would break
that property and leak a trailing CR into user-visible ``todo`` summaries.

Consequence to know: this trades MEMORY for I/O. Where a collector previously
held one file's text at a time, a scan now retains the union of the text its
content collectors admitted -- bounded by :data:`TEXT_CACHE_MAX_BYTES`, past
which retention is DECLINED and the collector simply re-reads (today's behavior).
Pure stdlib, offline, writes nothing to disk.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, overload

# The ONE owner of the re-entrant scope control flow both per-scan caches need --
# see :func:`scan_scope`. Only the control flow is shared; this module keeps its own
# ``_SCOPE`` and its own ``_drop_entries``.
from proactive_loop.collectors.base import _depth_scope

# Ceiling on the decoded text retained for one scan. 32 MiB is 6.7x the 5 MB
# per-file cap the three collectors share (``LARGE_FILE_MIN_BYTES``) -- a bound
# stated against a NAMED CODE CONSTANT instead of against this checkout's own
# measured text volume, which decays on every commit -- so a single
# largest-admissible file always fits while an unbounded monorepo cannot grow the
# process without limit. Read at CALL time, so a test may lower it -- and lowering it must only
# cost speed: past the cap nothing is retained, so the next collector re-reads
# the file exactly as it did before this module existed.
TEXT_CACHE_MAX_BYTES: int = 33_554_432


@dataclass(frozen=True)
class _CachedText:
    """One file's decoded text plus the ONE policy fact a caller needs.

    ``strict_clean`` is False iff the bytes failed a strict UTF-8 decode and the
    text therefore came from an ``errors="replace"`` re-read. Frozen so a caller
    cannot mutate a retained entry through the map.
    """

    text: str
    strict_clean: bool


_CACHE: dict[Path, _CachedText] = {}

# ``hits`` = requests served from a retained entry; ``misses`` = physical reads
# performed (including every read made outside a scope, where there is no cache);
# ``declined`` = reads whose text the byte budget refused to retain; ``bytes`` =
# currently retained decoded bytes. ``entries`` is NOT tracked here: it is
# derived from the map in :func:`text_cache_stats` so it cannot drift from what
# is actually retained. ``bytes`` can be a running total safely because entries
# are never removed INDIVIDUALLY -- retention has exactly one add site and the
# only removal is the wholesale drop in :func:`_drop_entries`.
_COUNTS: dict[str, int] = {"hits": 0, "misses": 0, "declined": 0, "bytes": 0}

# Depth, not a bool, so a nested ``scan_scope`` cannot switch the cache off for
# the outer scan when the inner one exits.
_SCOPE: dict[str, int] = {"depth": 0}


def _drop_entries() -> None:
    """Forget all retained text; leave the activity counters alone.

    Split from :func:`clear_text_cache` on purpose. The retained TEXT must not
    survive a scan (that is the no-staleness argument), but ``hits`` / ``misses``
    / ``declined`` are the record of the scan that just ran -- wiping them at
    scope exit would make this module's own effect, and the byte-budget's
    degrade-to-re-reading path, unobservable to a test or to a diagnosis after
    the fact. Clears IN PLACE so any holder of the dict sees the emptying.
    """
    _CACHE.clear()
    _COUNTS["bytes"] = 0


def clear_text_cache() -> None:
    """Empty the cache and zero every counter; safe to call outside a scope.

    WHY public: a module-level cache that cannot be reset is hidden global state
    -- untestable, and a liability in the long-lived ``watch`` process this
    exists to serve. Mirrors the ``clear_todo_memo`` / ``clear_parse_memo`` seams
    the two content memos already ship, and touches ONLY this cache.
    """
    _drop_entries()
    _COUNTS["hits"] = 0
    _COUNTS["misses"] = 0
    _COUNTS["declined"] = 0


def text_cache_stats() -> dict[str, int]:
    """Return a fresh snapshot: ``entries``, ``bytes``, ``hits``, ``misses``, ``declined``.

    A COPY, so a caller cannot mutate the live counters. ``entries`` is DERIVED
    from the map rather than tracked, and ``bytes`` is never above
    :data:`TEXT_CACHE_MAX_BYTES` as read at the time each entry was admitted.
    """
    return {
        "entries": len(_CACHE),
        "bytes": _COUNTS["bytes"],
        "hits": _COUNTS["hits"],
        "misses": _COUNTS["misses"],
        "declined": _COUNTS["declined"],
    }


@contextmanager
def scan_scope() -> Iterator[None]:
    """Make reads inside the body share ONE decode per path; empty on both edges.

    Entered by ``cli._collect`` around its collector loop -- one seam for every
    front-door verb -- so the sharing is exactly scan-scoped. The cache is
    emptied on ENTRY (a previous scan's text can never be served, whatever left
    it behind) and again in a ``finally``, so a collector that raises, a
    ``KeyboardInterrupt`` mid-scan, or an early ``return`` all leave nothing
    retained; the exception itself propagates untouched. Re-entrant by depth
    count: an inner scope's exit drops the outer scope's retained text, which
    costs re-reads and never correctness.

    The control flow implementing both of those rules is owned by
    ``base._depth_scope``, shared with ``dir_source.walk_scope`` so the invariant is
    written once. Only the control flow is shared: :data:`_SCOPE` and
    :func:`_drop_entries` stay this module's own, so entering this scope never
    activates the walk cache.
    """
    with _depth_scope(_SCOPE, _drop_entries):
        yield


def _text_bytes(text: str) -> int:
    """Size *text* would occupy as UTF-8, without paying for an encode when ASCII.

    ``str.isascii()`` is a flag read on CPython (O(1), set when the string was
    built), and for an ASCII string the character count IS the UTF-8 byte count.
    Only genuinely non-ASCII text pays the O(n) encode -- which matters because
    this runs on the hot path of a change whose entire purpose is to remove work.
    """
    return len(text) if text.isascii() else len(text.encode("utf-8"))


def _decode_once(full: Path) -> _CachedText:
    """Read *full* through ``Path.read_text``, strict first, replace on failure.

    STRICT FIRST is what makes one shared string legal for both decode policies:
    when the strict read succeeds, ``errors="replace"`` was unreachable, so the
    string is byte-identical to what today's replace-callers received. The
    fallback read is the ONLY reason a path is ever read twice in one scan, and
    it happens only for bytes that are not valid UTF-8 -- where today's cost is
    three reads (two replace plus one strict attempt that raises).

    ``OSError`` is deliberately NOT caught: every call site already wraps its
    read in ``except OSError -> skip``, so propagating keeps that per-file
    never-raise discipline where it is documented, and keeps an unreadable file
    out of the cache.
    """
    try:
        return _CachedText(text=full.read_text(encoding="utf-8"), strict_clean=True)
    except UnicodeDecodeError:
        return _CachedText(
            text=full.read_text(encoding="utf-8", errors="replace"),
            strict_clean=False,
        )


def _retain(full: Path, entry: _CachedText) -> None:
    """Retain *entry* under the byte budget, or decline and count the refusal.

    DECLINE rather than evict: a scan-scoped cache is emptied within milliseconds
    anyway, so evicting an earlier file to admit a later one would only move the
    re-read around while making which files are cached depend on walk order. As
    written, the retained set is a deterministic prefix of the scan's read order
    and going over budget costs exactly the re-reads that existed before this
    module. A cap of ``<= 0`` retains nothing, which keeps "``bytes`` never
    exceeds the cap" true for every cap value.
    """
    cap = TEXT_CACHE_MAX_BYTES
    size = _text_bytes(entry.text)
    if cap <= 0 or _COUNTS["bytes"] + size > cap:
        _COUNTS["declined"] += 1
        return
    _CACHE[full] = entry
    _COUNTS["bytes"] += size


def _served(entry: _CachedText, *, strict: bool) -> str | None:
    """Apply the CALLER's decode policy to a cached entry.

    The single place the strict/replace divergence is honored, so the answer a
    collector gets cannot depend on which collector happened to read the file
    first: a strict caller sees ``None`` (skip) for bytes that failed a strict
    decode, and a replace caller sees the replacement-charred text.
    """
    if strict and not entry.strict_clean:
        return None
    return entry.text


@overload
def read_text(full: Path, *, strict: Literal[False]) -> str: ...


@overload
def read_text(full: Path, *, strict: Literal[True]) -> str | None: ...


@overload
def read_text(full: Path, *, strict: bool) -> str | None: ...


def read_text(full: Path, *, strict: bool) -> str | None:
    """Return *full*'s decoded text, reading it at most once per scan.

    *strict* selects the CALLER's policy, not the provider's: ``strict=False``
    always yields a string (the ``errors="replace"`` behavior of ``todos`` and
    ``merge_conflict``), while ``strict=True`` yields ``None`` when the file's
    bytes are not valid UTF-8 (the SKIP behavior of ``syntax_error``). The
    overloads above encode that in the type, so a replace-caller needs no
    ``assert`` to satisfy a type checker. ``OSError`` propagates.

    Outside a :func:`scan_scope` this is a pass-through: the file is read on
    every call and nothing is retained, so a collector used directly -- outside
    the ``cli._collect`` seam -- keeps exactly its pre-cache behavior, including
    seeing an edit made between two ``collect()`` calls.

    Callers must keep their own size guard BEFORE calling: each collector caps
    the bytes it is willing to decode (``max_read_bytes``), and that decision is
    per-collector, so an oversized file must never reach this function.
    """
    active = _SCOPE["depth"] > 0
    if active:
        cached = _CACHE.get(full)
        if cached is not None:
            _COUNTS["hits"] += 1
            return _served(cached, strict=strict)

    entry = _decode_once(full)
    _COUNTS["misses"] += 1
    if active:
        _retain(full, entry)
    return _served(entry, strict=strict)
