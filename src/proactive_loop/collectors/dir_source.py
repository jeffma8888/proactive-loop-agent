"""dir_source: ONE pruned directory walk per root per scan, served to every caller.

WHY this module exists: the perception layer re-walks the user's workspace once
per collector. Measured on a 3,000-file workspace before this module landed: **13
``os.walk`` traversals, 3,317 directory visits, ~915 ms per scan**, with all 13
roots being the SAME path -- so twelve of them re-derived a dirent listing the
first had already paid for. The four non-walking collectors cost 1-2 ms each while
the cheapest WALKING ones cost 22-43 ms even when they read almost nothing, which
puts roughly a third of the scan in redundant traversal. ``watch`` re-pays that
cost every tick, so the waste scales with the SIZE of the user's project rather
than with anything it contains.

This is the second half of a story ``collectors/text_source.py`` (iter 129) opened
and its own docstring named: that module removed the redundant *content decode* --
one read+decode per path per scan instead of one per collector -- and called the
walk "the missing half: the I/O". This module is that half, one level up from
bytes to dirents. The two are deliberately separate caches with the same shape:
text_source answers "what is IN this file", dir_source answers "what IS there".

WHY sharing is safe here, and why it needed no union computation: every walking
collector imports the SAME two prune rules from the SAME place
(``filesystem._SKIP_DIRS`` / ``filesystem._is_hidden``) and applies the
character-for-character identical in-place prune, so the product has exactly ONE
prune set and there is no set-difference risk to reconcile. ``filesystem.py``
itself is deliberately NOT a caller: its walk prunes ADDITIONALLY for recency, so
it is the one walker whose prune set genuinely differs and a shared listing would
change which files it sees.

Pure stdlib, no network, deterministic: the served order is a total function of
the tree (sorted), never of platform ``os.walk`` enumeration order.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

# The ONE owner of the re-entrant scope control flow both per-scan caches need --
# see :func:`walk_scope`. A private-name import across collector modules, exactly
# like the prune-policy import below, so each rule keeps a single home.
from proactive_loop.collectors.base import _depth_scope

# The ONE home of the package's dir-prune policy. Imported here so that the
# policy question "which parts of a tree are worth looking at" keeps exactly one
# answer, and so a collector converted onto this provider stops needing the rule
# at all -- it inherits an already-pruned listing.
from proactive_loop.collectors.filesystem import _SKIP_DIRS, _is_hidden

# A served triple in ``os.walk``'s OWN shape: ``(dirpath, dirnames, filenames)``.
# The two name lists are deliberately MUTABLE, and deliberately FRESH per call --
# see :func:`_serve`. Keeping the shape identical to ``os.walk`` is what makes a
# conversion a one-line edit at each call site and keeps the remaining walkers a
# mechanical follow-up.
WalkTriple = tuple[str, list[str], list[str]]

# The RETAINED form: fully immutable, so nothing a caller does to a served triple
# can reach back into the cache.
_FrozenTriple = tuple[str, tuple[str, ...], tuple[str, ...]]

# Keyed by the root EXACTLY as the caller spelled it, never ``resolve()``d. Two
# spellings of one directory therefore get two entries (a wasted walk, never a
# wrong answer), and that is the correct trade: every ``dirpath`` string a caller
# receives is derived from the root it passed in, so serving a listing built from
# a different spelling would hand it paths it cannot recognise. Resolving would
# also cost a syscall per call and silently collapse symlinked roots.
_CACHE: dict[Path, tuple[_FrozenTriple, ...]] = {}

# ``hits`` = calls served from a retained listing; ``misses`` = physical
# traversals performed, INCLUDING every call made outside a scope, where there is
# no cache to serve from. Neither ``entries`` nor ``dirs`` is tracked here: both
# are DERIVED from the map in :func:`walk_cache_stats`, so they cannot drift from
# what is actually retained.
_COUNTS: dict[str, int] = {"hits": 0, "misses": 0}

# Depth, not a bool, so an inner :func:`walk_scope` exiting cannot switch the
# cache off for the outer scan that is still running.
_SCOPE: dict[str, int] = {"depth": 0}


def _drop_entries() -> None:
    """Forget every retained listing; leave the activity counters alone.

    Split from :func:`clear_walk_cache` on purpose, mirroring
    ``text_source._drop_entries``. The retained LISTING must not survive a scan
    -- that is the entire no-staleness argument, and it is load-bearing for
    ``watch``, which ticks forever in one process and must never be handed a
    dirent listing from a previous tick. But ``hits`` / ``misses`` are the record
    of the scan that just ran; wiping them at scope exit would make this module's
    own effect unobservable to a test or to a diagnosis after the fact. Clears IN
    PLACE so any holder of the dict sees the emptying.
    """
    _CACHE.clear()


def clear_walk_cache() -> None:
    """Empty the cache and zero every counter; safe to call outside a scope.

    WHY public: a module-level cache that cannot be reset is hidden global state
    -- untestable, and a liability in the long-lived ``watch`` process this exists
    to serve. Mirrors the ``clear_text_cache`` seam ``text_source`` already ships,
    and touches ONLY this cache.
    """
    _drop_entries()
    _COUNTS["hits"] = 0
    _COUNTS["misses"] = 0


def walk_cache_stats() -> dict[str, int]:
    """Return a fresh snapshot: ``entries``, ``dirs``, ``hits``, ``misses``.

    A COPY, so a caller cannot mutate the live counters. ``entries`` is the number
    of distinct roots currently retained and ``dirs`` the number of directory
    visits those listings cover -- both DERIVED from the map rather than tracked,
    so a retention bug cannot hide behind a stale counter.
    """
    return {
        "entries": len(_CACHE),
        "dirs": sum(len(listing) for listing in _CACHE.values()),
        "hits": _COUNTS["hits"],
        "misses": _COUNTS["misses"],
    }


@contextmanager
def walk_scope() -> Iterator[None]:
    """Make every :func:`walk` of one root inside the body share ONE traversal.

    Entered by ``cli._collect`` around its collector loop -- one seam for every
    front-door verb -- so the sharing is exactly scan-scoped. The cache is emptied
    on ENTRY (a previous scan's listing can never be served, whatever left it
    behind) and again in a ``finally``, so a collector that raises, a
    ``KeyboardInterrupt`` mid-scan, or an early ``return`` all leave nothing
    retained; the exception itself propagates untouched. Re-entrant by depth
    count: an inner scope's exit drops the outer scope's retained listings, which
    costs re-traversals and never correctness.

    The control flow implementing both of those rules is owned by
    ``base._depth_scope``, shared with ``text_source.scan_scope`` so the invariant is
    written once. Only the control flow is shared: :data:`_SCOPE` and
    :func:`_drop_entries` stay this module's own, so entering this scope never
    activates the text cache.
    """
    with _depth_scope(_SCOPE, _drop_entries):
        yield


def _walk_pruned(root: Path) -> tuple[_FrozenTriple, ...]:
    """Traverse *root* once, pruning in place, and freeze the result in sorted order.

    The in-place ``dirnames[:]`` assignment is what stops ``os.walk`` descending
    into a pruned directory, so the prune is a TRAVERSAL saving and not a filter
    applied afterwards -- exactly what every converted call site was doing for
    itself. ``sorted`` is applied twice for two different reasons: to ``dirnames``
    so the descent order is itself deterministic, and to the collected triples so
    the served order is a total function of the tree rather than of platform
    enumeration order. A collector's output therefore cannot depend on traversal
    order.

    ``os.walk`` is called through the module attribute so it stays the
    substitution seam the rest of the package already treats it as (see
    ``notes.py``); errors are NOT caught here, because ``os.walk`` already
    swallows per-directory ``OSError`` by default and each caller keeps its own
    documented per-item guard.
    """
    collected: list[_FrozenTriple] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            d for d in dirnames if not _is_hidden(d) and d not in _SKIP_DIRS
        )
        collected.append((dirpath, tuple(dirnames), tuple(sorted(filenames))))
    collected.sort(key=lambda triple: triple[0])
    return tuple(collected)


def _serve(listing: tuple[_FrozenTriple, ...]) -> list[WalkTriple]:
    """Materialise a retained listing as FRESH mutable triples, per call.

    WHY the copy is not waste: ``os.walk``'s contract is that a caller may prune
    by assigning into ``dirnames``, and several collectors in this package still
    do exactly that. Handing out the retained lists would let the first caller's
    in-place prune silently rewrite what every later caller in the same scan sees
    -- a correctness bug that would be invisible in the first caller's own output.
    Rebuilding the lists costs no syscalls at all, which is the only cost this
    module exists to remove, so the copy is orders of magnitude cheaper than the
    traversal it replaces and it makes the shared listing safe to hand to a caller
    that has not been converted.
    """
    return [(dirpath, list(dirnames), list(filenames)) for dirpath, dirnames, filenames in listing]


def walk(root: Path) -> list[WalkTriple]:
    """Return *root*'s pruned tree as ``os.walk``-shaped triples, sorted.

    Inside a :func:`walk_scope` the first call for a given root pays the traversal
    and every later call for that same root is served from it. Outside a scope
    this is a pass-through: the tree is traversed on the spot, nothing is
    retained, and the call is counted as a miss. That degradation is DELIBERATE
    and narrow -- it is a scope check, not a swallowed exception, so a real
    traversal failure still surfaces to the caller exactly as it does today, and a
    collector used directly in a test or by a library consumer keeps working with
    no scope in sight.
    """
    if _SCOPE["depth"] <= 0:
        _COUNTS["misses"] += 1
        return _serve(_walk_pruned(root))

    cached = _CACHE.get(root)
    if cached is not None:
        _COUNTS["hits"] += 1
        return _serve(cached)

    _COUNTS["misses"] += 1
    listing = _walk_pruned(root)
    _CACHE[root] = listing
    return _serve(listing)
