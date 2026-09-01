"""TodoCollector: surfaces TODO/FIXME/XXX comments and Markdown checkboxes.

Scans source files (*.py, *.ts, *.js, *.md) for actionable items.
WHY include markdown checkboxes: project notes often use `- [ ]`, `* [ ]`,
or `+ [ ]` to track tasks; surfacing them gives the synthesizer richer
intent signals. All three GFM unordered-list bullets are treated alike.

SCAN ONCE PER CONTENT. This collector matches two regexes against EVERY line of
every scanned-extension file, and in the vision's long-lived mode that whole pass
is repeated work: ``pla watch`` runs a full collect each tick over a tree that
mostly did not change. Profiled once when this memo shipped (factory iter 130,
on a ~190-file tree holding ~3.2 MB of decoded text): a full ``collect`` was
79.77 ms, of which the per-line regex pass was 55.76 ms (70%) while read+decode
was 18.96 ms and a blake2b digest of the same text was 3.58 ms. That is a DATED
record of one past run, not a claim about whatever tree this checkout holds
today. So the per-line extraction is memoized in a bounded,
module-level map keyed on a digest of the decoded text (see the todo-memo block
below), which turns the repeated cost into read+decode+digest and saves ~52 ms
per tick. Output is unchanged: a hit returns exactly the items the regex pass
would have produced for that same text.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from proactive_loop.collectors.base import BaseCollector
# Only the FILE-level rule is imported. The DIRECTORY prune this module used to
# restate is now inherited: ``dir_source`` applies it during the one shared
# traversal, so a converted collector stops needing the rule at all. That is
# strictly stronger than importing it -- the rule cannot be mis-applied at a call
# site that no longer has one. (Row #178's hoist was the necessary step: this
# module once hand-copied the set and the copy HAD drifted, missing ".tox",
# invisibly, because every prune site ANDs the hidden rule and ".tox" is
# dot-prefixed. The set now has exactly one home and one applier.)
from proactive_loop.collectors.filesystem import _is_hidden
from proactive_loop.collectors.large_file import LARGE_FILE_MIN_BYTES
# The MODULES are imported (not their functions) so every collector resolves the
# two shared per-scan providers through ONE patchable attribute each -- a test can
# instrument or assert either seam in a single place.
from proactive_loop.collectors import dir_source, text_source
from proactive_loop.models import ContextSignal

# Matches TODO / FIXME / XXX anywhere in a line (case-insensitive).
_INLINE_TAG_RE = re.compile(r"\b(TODO|FIXME|XXX)\b[:\s]*(.*)", re.IGNORECASE)

# Matches a Markdown unchecked task item. GitHub-Flavored Markdown treats
# `-`, `*`, and `+` as interchangeable unordered-list bullets, so accept any
# of them before the `[ ]` box: `- [ ] text`, `* [ ] text`, `+ [ ] text`.
_CHECKBOX_RE = re.compile(r"^\s*[-*+]\s+\[\s\]\s+(.*)")

# Cheap prefilter for _CHECKBOX_RE, and like TODO_PREFILTER_TOKENS it is DERIVED
# rather than guessed: it is a literal SUBPATTERN of the regex it guards, lifted
# from between that pattern's bullet and its trailing text. A match of
# _CHECKBOX_RE therefore IMPLIES a match of this one, so this gate is provably
# weaker than what it guards and a skip can only ever remove work, never a
# signal. Searching the WHOLE text (not a line) only widens it further, since
# `\s` also matches the `\n` no single line can contain. The derivation is
# pinned two-sided by the suite -- this pattern's own text AND its presence
# inside ``_CHECKBOX_RE.pattern`` -- so the two cannot drift apart if either is
# edited alone.
#
# WHY NOT a hand-enumerated box (`"[ ]" in text or "[\t] " ...`): it would be
# UNSOUND. In a str pattern `\s` also matches NBSP and the U+2000 block, and
# ``str.splitlines()`` does NOT split on those, so `- [\xa0] x` really does
# reach _CHECKBOX_RE as ONE line and really does match it. Being the guarded
# regex's own subpattern is a proof; zero losses over some corpus is not.
_CHECKBOX_PREFILTER_RE: Final[re.Pattern[str]] = re.compile(r"\[\s\]")

# Cheap substring prefilter for _INLINE_TAG_RE, derived MECHANICALLY rather than
# guessed: one token per tag alternative, each the longest contiguous run of
# letters whose IGNORECASE match class is closed under ``str.lower`` -- `todo` of
# TODO, `xme` of FIXME, `xxx` of XXX. The letter `i` is DROPPED for cause, which
# is the whole reason this constant is derived instead of spelled: U+0131 LATIN
# SMALL LETTER DOTLESS I matches `i` under re.IGNORECASE, yet neither
# ``"\u0131".lower()`` nor ``.casefold()`` is `i`, so a prefilter keyed on the
# full word `fixme` would SKIP a line the regex matches and silently drop a real
# L2 signal. That is a soundness claim, not a comment: it is RE-DERIVED over
# codepoints 0x80..0x10FFFF, two-sided, by
# ``tests/test_iter181_behavior.py``. Guarding the two regexes separately (rather
# than one prefilter over the whole loop) is what lets each gate be as strong as
# its own regex allows; see ``_CHECKBOX_PREFILTER_RE`` for the other one.
TODO_PREFILTER_TOKENS: Final[tuple[str, ...]] = ("todo", "xme", "xxx")

_SCAN_EXTENSIONS: frozenset[str] = frozenset({".py", ".ts", ".js", ".md"})


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
# cannot grow this map without limit. The bound is stated ABSOLUTELY and never as
# a ratio against this checkout's own file count: that ratio decays on every
# commit while claiming to describe today, so it is banned by
# ``tests/test_source_comment_bounds.py``. Together with
# ``TODO_MEMO_MAX_ITEMS_PER_FILE`` below, 4096 entries bound this map at
# 4096 x 256 = 1,048,576 retained items, and 4096 item-bearing files covers a
# typical service repo outright; past the cap the oldest entries are evicted,
# which costs speed and NEVER correctness. Read at call time, so a test may
# lower it.
TODO_MEMO_MAX_ENTRIES: int = 4096

# Hard cap on the number of items inside a RETAINED value, because the entry cap
# alone does not bound memory: one value holds a line slice per matched line, so
# without this a single generated checklist could retain O(``max_read_bytes``)
# of strings and the true ceiling would be 4096 x 5 MB. 256 items is far above
# what any hand-maintained source file carries, while the generated checklists
# that blow past it are exactly the values not worth retaining -- a bound stated
# without measuring this checkout, which is what keeps it true next commit.
# A value with MORE items than this is simply not
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

    The two regexes are prefiltered INDEPENDENTLY, once per text rather than once
    per line, so each gate can be as strong as its OWN regex allows: a single
    prefilter over the whole loop would have to be the weaker of the two and
    could only skip a text both regexes agree to skip. Each prefilter is provably
    WEAKER than the regex it guards -- ``TODO_PREFILTER_TOKENS`` holds a
    substring of every alternative ``_INLINE_TAG_RE`` can match, and
    ``_CHECKBOX_PREFILTER_RE`` is a literal subpattern of ``_CHECKBOX_RE`` (see
    each constant for its derivation and soundness argument) -- so a skip can
    only ever remove work, never a signal.

    Two DATED records of past runs, kept because they measure DIFFERENT gates and
    neither is a claim about whatever tree this checkout holds today; the suite
    asserts the SKIPS and the equivalence, never a duration. Factory iter 181,
    when these two prefilters replaced an unguarded per-line pass, over a
    246-file / 99,538-line corpus with the memo bypassed: 82.15 ms -> 54.25 ms,
    at 0 output mismatches across 426 items. Factory iter 238, when the checkbox
    gate stopped being the measured-useless `"[" in text` -- almost every source
    file holds some literal `[` -- over a 286-file / 5.86 MB corpus, memo
    bypassed: that gate's reach fell from 282 of 286 texts to 11 and this
    function went 75.9 ms -> 50.2 ms (-34%), losing 0 checkbox items. Stated
    against BOTH denominators, because either alone misprices it: -4.6% of that
    corpus's 555 ms full scan, but -9.6% of its ~268 ms REDUCIBLE surface, since
    52% of the scan is ``compile()`` inside ``syntax_error``, whose parse memo is
    digest-keyed and so re-parses every distinct text.
    """
    # ONE lowercase copy per call, never per line: the tokens are ASCII and
    # case-stable by construction, so a single folded haystack answers all three.
    lowered = text.lower()
    scan_inline = any(token in lowered for token in TODO_PREFILTER_TOKENS)
    scan_checkbox = _CHECKBOX_PREFILTER_RE.search(text) is not None
    if not scan_inline and not scan_checkbox:
        # Neither regex can match anywhere in this text, so even splitlines is
        # wasted work -- the common case for source files with no open items.
        return ()

    items: list[_TodoItem] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        # Check for TODO/FIXME/XXX pattern.
        if scan_inline:
            m = _INLINE_TAG_RE.search(line)
            if m:
                tag = m.group(1).upper()
                description = m.group(2).strip()
                summary = f"{tag}: {description}" if description else tag
                items.append((lineno, summary, line.strip(), 1.0))
                continue  # Don't double-count a line that is also a checkbox.

        # Check for Markdown unchecked checkbox.
        if scan_checkbox:
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
        # regardless of the order the shared traversal serves entries in.
        found: list[tuple[str, int, ContextSignal]] = []

        # The listing arrives ALREADY pruned of noise + hidden DIRS: dir_source
        # owns the package dir-prune policy and applies it during the traversal,
        # so this collector no longer carries the rule -- and inside the scan
        # scope opened by cli._collect that ONE traversal is shared with every
        # sibling walking the same root instead of being re-paid per collector.
        for dirpath, _dirnames, filenames in dir_source.walk(root):
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
                    # Shared per-scan decode: inside ``cli._collect``'s scope the
                    # first content collector to reach this path pays the read and
                    # the other two are served the SAME string. ``strict=False``
                    # keeps this collector's errors="replace" policy exactly -- it
                    # never returns None, so an undecodable file still reports its
                    # todos with U+FFFD in place of the bad bytes, as today. Outside
                    # a scope the provider reads the file on every call.
                    text = text_source.read_text(full, strict=False)
                except OSError:
                    continue
                found.extend(_extract_todos(text, full, root, self.name))

        # Deterministic: sort by (relpath, lineno) ascending, then cap -- so which
        # todos survive the cap and their order are a total, traversal-order-independent
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
