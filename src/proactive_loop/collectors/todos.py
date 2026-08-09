"""TodoCollector: surfaces TODO/FIXME/XXX comments and Markdown checkboxes.

Scans source files (*.py, *.ts, *.js, *.md) for actionable items.
WHY include markdown checkboxes: project notes often use `- [ ]`, `* [ ]`,
or `+ [ ]` to track tasks; surfacing them gives the synthesizer richer
intent signals. All three GFM unordered-list bullets are treated alike.

SCAN ONCE PER CONTENT. This collector matches two regexes against EVERY line of
every scanned-extension file, and in the vision's long-lived mode that whole pass
is repeated work: ``pla watch`` runs a full collect each tick over a tree that
mostly did not change. Measured on this repo (189 scanned files, 3,170 KB of
decoded text) a full ``collect`` is 79.77 ms, of which the per-line regex pass is
55.76 ms (70%) while read+decode is 18.96 ms and a blake2b digest of the same
text is 3.58 ms. So the per-line extraction is memoized in a bounded,
module-level map keyed on a digest of the decoded text (see the todo-memo block
below), which turns the repeated cost into read+decode+digest and saves ~52 ms
per tick. Output is unchanged: a hit returns exactly the items the regex pass
would have produced for that same text.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path

from proactive_loop.collectors.base import BaseCollector
from proactive_loop.collectors.large_file import LARGE_FILE_MIN_BYTES
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


# ---------------------------------------------------------------------------
# Todo memo: one per-line scan per distinct FILE CONTENT, process-wide.
#
# WHY MODULE level and not an instance attribute: ``all_collectors()`` builds a
# FRESH ``TodoCollector`` on every call and ``cli._collect`` calls it once per
# invocation, so ``pla watch`` constructs a new instance every tick. An instance
# memo would never hit in the ONE workload this exists to fix, while still
# passing any test that reuses a single collector object -- a fail-silent perf
# regression that measures as a win. Being process-wide, the state is made
# INSPECTABLE (``todo_memo_stats``) and RESETTABLE (``clear_todo_memo``) rather
# than hidden. This mirrors the seam ``syntax_error`` already ships; the two
# memos are deliberately SEPARATE maps (no shared helper) so neither module's
# oracle can be broken by a change made for the other.
#
# The memo is a pure speed-up, never a semantic change: the extracted items are
# a pure function of the text, so a hit, a miss and an eviction all yield
# byte-identical signals.
# ---------------------------------------------------------------------------

# One actionable item found in a file: ``(lineno, summary, detail, weight)``.
# Deliberately NOT a ``ContextSignal``: a signal carries the file's relative
# path, which differs per file while the extracted items do not. Caching the
# path-free items is precisely what lets K byte-identical files share ONE scan
# and still each report their own path.
_TodoItem = tuple[int, str, str, float]

# Hard cap on retained per-file item lists, so scanning an unbounded monorepo
# cannot grow this map without limit. 4096 is ~21x this repo's own 189 scanned
# files and covers a typical service repo outright; past the cap the oldest
# entries are evicted, which costs speed and NEVER correctness. Read at call
# time, so a test may lower it.
TODO_MEMO_MAX_ENTRIES: int = 4096

# Hard cap on the number of items inside a RETAINED value, because the entry cap
# alone does not bound memory: one value holds a line slice per matched line, so
# without this a single generated checklist could retain O(``max_read_bytes``)
# of strings and the true ceiling would be 4096 x 5 MB. 256 is ~8x the densest
# file in this repo (33 items). A value with MORE items than this is simply not
# retained -- retention is an optimization, so declining it costs speed and never
# correctness: the caller always receives the COMPLETE item list. (Truncating the
# list instead would change emitted signals, since ``max_items`` applies only
# after the global sort.) Read at call time, so a test may lower it.
TODO_MEMO_MAX_ITEMS_PER_FILE: int = 256

# 128 bits of digest. Collisions are the only way this memo could serve the wrong
# items, and at 2**-128 per pair that is far below the probability of the
# filesystem handing back wrong bytes; a shorter digest saves nothing measurable.
_DIGEST_SIZE: int = 16

_TODO_MEMO: dict[bytes, tuple[_TodoItem, ...]] = {}
_TODO_MEMO_COUNTS: dict[str, int] = {"hits": 0, "misses": 0}


def clear_todo_memo() -> None:
    """Empty the todo memo and zero its counters.

    WHY this is public on a module that otherwise exposes one collector class: a
    process-wide cache that cannot be reset is hidden global state -- untestable,
    and a liability in the long-lived ``watch`` process it exists to serve. It
    clears IN PLACE rather than rebinding, so any holder of the dict object sees
    the same emptying. Touches ONLY this memo: ``syntax_error``'s parse memo is a
    separate map and is unaffected.
    """
    _TODO_MEMO.clear()
    _TODO_MEMO_COUNTS["hits"] = 0
    _TODO_MEMO_COUNTS["misses"] = 0


def todo_memo_stats() -> dict[str, int]:
    """Return a fresh snapshot: ``{"hits", "misses", "entries"}``.

    ``hits`` = item lists served without scanning; ``misses`` = per-line scans
    performed (whether or not the result was retained); ``entries`` = item lists
    currently retained, never above ``TODO_MEMO_MAX_ENTRIES``. A COPY is returned
    so a caller cannot mutate the live counters, and ``entries`` is DERIVED from
    the map (never tracked separately) so it cannot drift from what is actually
    retained.
    """
    return {
        "hits": _TODO_MEMO_COUNTS["hits"],
        "misses": _TODO_MEMO_COUNTS["misses"],
        "entries": len(_TODO_MEMO),
    }


def _remember_items(digest: bytes, items: tuple[_TodoItem, ...]) -> None:
    """Retain one item list under both caps, evicting the OLDEST entries first.

    FIFO (``dict`` preserves insertion order) rather than LRU: eviction order is
    then a pure function of the insertion sequence, so two identical scans evict
    identically -- deterministic, which access-ordered eviction is not without
    extra bookkeeping this cannot justify. An entry cap of ``<= 0`` disables
    retention entirely (nothing is stored, so nothing can hit), which keeps the
    "entries never exceeds the cap" invariant true for every cap value.
    """
    cap = TODO_MEMO_MAX_ENTRIES
    if cap <= 0:
        return
    if len(items) > TODO_MEMO_MAX_ITEMS_PER_FILE:
        # Over-large value: skipped so aggregate memory is bounded by
        # entries x items x line length -- each item keeps a stripped line plus
        # a summary derived from it, so roughly 2x the matched lines' own text
        # per entry -- instead of by one file's size alone.
        return
    while len(_TODO_MEMO) >= cap:
        del _TODO_MEMO[next(iter(_TODO_MEMO))]
    _TODO_MEMO[digest] = items


def _todo_items(text: str) -> tuple[_TodoItem, ...]:
    """Return *text*'s actionable items, scanning at most once per distinct text.

    WHY the key is a DIGEST OF THE TEXT and never ``(path, mtime, size)``: this
    memo may only ever return what the regex pass would return TODAY, and with a
    content digest that proof is definitional -- digest equality IS input
    equality, so an edited file cannot hit a stale entry. An mtime/size key
    cannot promise that (a coarse mtime plus an unchanged size serves a stale
    result), and trading determinism for speed is not a trade worth making here.

    The digest is taken over the DECODED TEXT because that is exactly the
    argument handed to the scan, so the soundness proof is about the memoized
    function's INPUT rather than about the file -- and no second read is needed,
    which matters because the single ``read_text`` decode is a pinned seam (the
    oversized-file guard's proof counts exactly one read per candidate). Note
    this is a property of the TEXT, not of the bytes: ``read_text`` applies
    universal-newline translation, so a CRLF file and its LF twin share ONE
    entry -- correctly, since the scan sees identical input in both cases.
    """
    digest = hashlib.blake2b(text.encode("utf-8"), digest_size=_DIGEST_SIZE).digest()
    if digest in _TODO_MEMO:
        _TODO_MEMO_COUNTS["hits"] += 1
        return _TODO_MEMO[digest]

    items = _scan_items(text)
    _TODO_MEMO_COUNTS["misses"] += 1
    _remember_items(digest, items)
    return items


def _scan_items(text: str) -> tuple[_TodoItem, ...]:
    """Match both regexes against every line of *text* -- the memoized work.

    PURE and path-free by construction: it reads nothing but *text*, which is
    what makes the digest key sound and what lets one result serve every file
    holding these bytes. A tuple is returned (not a list) so a retained value
    cannot be mutated by a caller through the memo.
    """
    items: list[_TodoItem] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        # Check for TODO/FIXME/XXX pattern.
        m = _INLINE_TAG_RE.search(line)
        if m:
            tag = m.group(1).upper()
            description = m.group(2).strip()
            summary = f"{tag}: {description}" if description else tag
            items.append((lineno, summary, line.strip(), 1.0))
            continue  # Don't double-count a line that is also a checkbox.

        # Check for Markdown unchecked checkbox.
        m2 = _CHECKBOX_RE.match(line)
        if m2:
            task_text = m2.group(1).strip()
            items.append((lineno, f"TODO: {task_text}", line.strip(), 0.8))

    return tuple(items)


@dataclass
class TodoCollector(BaseCollector):
    """Emit one ContextSignal per TODO/FIXME/XXX comment or Markdown checkbox.

    Caps results at *max_items* to keep the synthesizer prompt concise.

    WHY *max_read_bytes*: this collector DECODES every scanned-extension file it
    walks, so without an upper bound one vendored blob (a 50 MB generated ``.md``
    or checked-in ``.py``) is pulled into memory on every scan -- and ``pla watch``
    repeats that each interval. Files whose ``st_size`` EXCEEDS the cap are skipped
    unread. This is not a blind spot: the cap equals ``LARGE_FILE_MIN_BYTES``, and
    ``LargeFileCollector`` reports at ``size >= LARGE_FILE_MIN_BYTES`` from
    ``st_size`` alone, so every file skipped here is already reported there as a
    ``kind="large_file"`` signal -- skipped-here implies reported-there. The
    comparison is STRICTLY greater, deliberately overlapping that inclusive ``>=``
    by exactly one size so the two ranges leave no gap.
    """

    name: str = "todos"
    max_items: int = 30
    max_read_bytes: int = LARGE_FILE_MIN_BYTES

    def _collect(self, root: Path) -> list[ContextSignal]:
        """Scan *root* recursively for actionable todo items."""
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
                # Per-file guard, inside ONE try so the size read is under the
                # same never-raise discipline as the decode: a file that vanishes
                # or denies stat() between the walk and here is skipped, and its
                # siblings still emit. Oversized files are skipped BEFORE any
                # decode, so nothing above the cap is ever pulled into memory --
                # and, since the memo is populated only from a text that was
                # read, an oversized file adds no memo entry either.
                try:
                    if full.stat().st_size > self.max_read_bytes:
                        continue
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

    This is the thin PATH-AWARE half of the extraction: everything that depends
    on *file_path* / *root* lives here, and the per-line matching it wraps is
    memoized on the text alone. Keeping the two apart is what makes the cache
    correct for repeated content -- see ``_todo_items``.
    """
    try:
        rel = str(file_path.relative_to(root))
    except ValueError:
        rel = str(file_path)

    return [
        (
            rel,
            lineno,
            ContextSignal(
                source=source_name,
                kind="todo",
                summary=summary,
                detail=detail,
                path=f"{rel}:{lineno}",
                weight=weight,
            ),
        )
        for lineno, summary, detail, weight in _todo_items(text)
    ]
