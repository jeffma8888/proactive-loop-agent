"""BrokenDocLinkCollector: report Markdown links whose relative target is missing.

WHY this collector exists: the scout's proactivity ceiling is set entirely by
*what its collectors can perceive* (SPEC sections 1, 4.1). Fifteen of the sixteen
collectors shipped before this one answer a question about a SINGLE artifact; only
``lockfile_drift`` relates two. This is the second *relational* collector -- it pairs
a written claim (a relative Markdown link) with the filesystem that disproves it, and
surfaces the resulting contradiction as an L2 signal. A stale relative doc link is the
most common docs-vs-code contradiction in a real repository and no existing collector
could see it, so the product was blind to exactly the defect class its own roadmap
ordering rule ranks first.

It reports a plain *fact* ("this link points at a path that is not there") and makes no
judgement -- the synthesizer LLM decides whether a "fix the docs" goal is warranted,
exactly like its siblings. A new ``kind="broken_link"`` flows into the synthesis prompt
automatically because ``synthesizer._build_prompt`` iterates ``snapshot.by_kind()``, so
this file plus the registry/catalog wiring is the whole cost.

SCOPE, deliberately narrow (each exclusion is a false-positive class, not laziness):

* Inline ``[text](target)`` links and ``![alt](target)`` images only. Reference-style
  links (``[text][ref]`` plus a ``[ref]: target`` definition block) and raw HTML
  ``<a href>`` / ``<img src>`` tags are out of scope.
* Only targets that name a path on disk are tested. A URL scheme, a protocol-relative
  ``//host`` target, a site-root ``/path`` target and a pure ``#fragment`` are skipped
  unread -- the runtime is offline-first, so an absolute URL is NEVER fetched, only
  ignored. The scheme test is generic (``^[A-Za-z][A-Za-z0-9+.-]*:``) rather than a
  hardcoded http/mailto pair, so ``ftp:`` or ``file:`` cannot become a phantom finding
  on a stranger's repo.
* Existence only: no anchor resolution inside a target that does exist, no
  case-sensitivity check, no directory-vs-file distinction.
* Code context is not prose. A link inside a fenced block, or whose DESTINATION sits
  inside a backtick inline-code span, is a code sample and is never reported. The mask
  is tested against the destination, not the whole link: a code-formatted LABEL is
  prose formatting and must not hide a dead target.

EXTRACT ONCE PER CONTENT. Splitting a document into link candidates is a pure
function of its text, and ``pla watch`` calls the whole census once per tick INSIDE
ONE PROCESS, so any cost a tick does not amortize is re-paid for the life of that
process. Measured 2026-09-04 over three consecutive censuses in one process, before
this memo existed: this collector cost 18.9 / 18.8 / 18.6 ms -- dead flat -- while
its memoized siblings amortized theirs away (``syntax_error`` 370.6 -> 10.2 ms,
``merge_conflict`` 32.8 -> 11.4 ms), which left it the third most expensive
collector on a warm tick. That is a DATED record of one past run, not a claim about
whatever tree this checkout holds today. So the text -> link-candidate pass is
memoized on a digest of the decoded text (see the link-memo block below), exactly as
``todos`` does it.

What is NOT memoized is the point of the seam: a broken link is a fact about the
text AND about the filesystem, so every ``.exists()`` probe re-runs on every scan.
Caching this collector's ANSWER would keep reporting a link as fine after its target
was deleted -- the precise false negative it exists to catch -- so the retained value
holds no existence verdict, no resolved path, no root-relative path and no
``ContextSignal``.

Pure stdlib (``re``/``pathlib``) plus the shared internal helpers, so the
runtime stays pydantic-v2-only and fully offline.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from proactive_loop.collectors.base import BaseCollector
# Only the hidden-FILE test is still needed here. dir_source owns the package
# dir-prune policy (noise dirs + hidden DIRS) and applies it during the shared
# traversal, but it prunes DIRECTORIES and sorts filenames only -- it never
# filters hidden FILES -- so a doc named ``.hidden.md`` stays invisible here
# only because this collector keeps testing basenames itself (Behavior 9).
from proactive_loop.collectors.filesystem import _is_hidden
from proactive_loop.collectors.large_file import LARGE_FILE_MIN_BYTES
# Reuse the ONE fenced-block parser rather than hand-rolling a second one: it
# already has the correct same-delimiter semantics (a ``~~~`` line cannot close a
# ``` block) and runs an unterminated fence to end-of-file.
from proactive_loop.collectors.notes import _fence_mask
# The MODULES are imported (not their functions) so every content collector
# resolves each shared per-scan provider through ONE patchable attribute.
from proactive_loop.collectors import dir_source, text_source
from proactive_loop.models import ContextSignal

# One inline link or image, in either of the two destination spellings CommonMark
# allows. The BARE form stops at the first whitespace or ``)`` so a Markdown title
# (``[a](t "Title")``) is tolerated without being mistaken for part of the path; the
# trailing ``[^)]*`` consumes that title. The ANGLE-BRACKET form (``[a](<my doc.md>)``)
# has to be a separate alternative rather than a post-hoc strip, because the bare
# target class excludes whitespace and would otherwise truncate such a destination at
# the space INSIDE the brackets and existence-test the fragment ``<my``. ``)`` is
# excluded from the bracketed class too -- CommonMark permits it there, but allowing it
# lets one unterminated ``<`` swallow the rest of the line, and this collector errs
# toward silence. Link text may not span lines, and nested brackets in the text are
# deliberately not supported -- both would only ever ADD findings.
_LINK_RE = re.compile(
    r"!?\[[^\]\n]*\]\(\s*(?:<(?P<angle>[^>)\n]*)>|(?P<target>[^)\s]*))[^)]*\)"
)

# A run of one or more backticks: the delimiter of an inline code span.
_BACKTICK_RUN_RE = re.compile(r"`+")

# A target that names a URL rather than a path: ``scheme:`` per RFC 3986.
_URL_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")

# One percent-escape: ``%`` plus exactly two hex digits.
_PCT_RE = re.compile(r"%([0-9A-Fa-f]{2})")


def _percent_decode(text: str, *, errors: str = "strict") -> str:
    """Return *text* with UTF-8 percent-escapes decoded, without ``urllib``.

    WHY hand-rolled instead of ``urllib.parse.unquote``: this repo publishes an
    offline-first bar enforced by a blunt module-name oracle that bans the top-level
    name ``urllib`` tree-wide, and that ban list is itself drift-guarded, so the seam
    has to live here rather than in the guard.

    The latin-1 round-trip reassembles the decoded BYTES before one UTF-8 decode, so a
    multi-byte escape (``caf%C3%A9.md``) survives intact instead of becoming mojibake.
    Under the default *errors* a malformed sequence degrades to the original text
    rather than to a mangled path, keeping this collector's err-toward-silence rule.
    ``errors="replace"`` reproduces what ``urllib.parse.unquote`` does with the same
    input (U+FFFD substitution); ``_target_paths`` probes EVERY form it can produce, so
    the two policies cannot disagree about whether a link is broken.
    """
    if "%" not in text:
        return text
    raw = _PCT_RE.sub(lambda m: chr(int(m.group(1), 16)), text)
    try:
        return raw.encode("latin-1").decode("utf-8", errors=errors)
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text


def _code_span_ranges(line: str) -> list[tuple[int, int]]:
    """Return the ``[start, end)`` character ranges of inline code spans in *line*.

    WHY this is not a regex: a code span is delimited by a backtick RUN and closes
    only on a later run of the SAME length (CommonMark), which is a matching problem
    rather than a pattern. An opener with no same-width closer is literal text, so the
    scan retries the next run as an opener instead of giving up on the line -- giving
    up would leave the tail unmasked and re-expose a documented code sample as a
    finding, which is the one direction this collector must not fail in.
    """
    runs = [(m.start(), m.end()) for m in _BACKTICK_RUN_RE.finditer(line)]
    ranges: list[tuple[int, int]] = []
    idx = 0
    while idx < len(runs):
        open_start, open_end = runs[idx]
        width = open_end - open_start
        closer = next(
            (j for j in range(idx + 1, len(runs)) if runs[j][1] - runs[j][0] == width),
            None,
        )
        if closer is None:
            idx += 1
            continue
        ranges.append((open_start, runs[closer][1]))
        idx = closer + 1
    return ranges


def _is_filesystem_target(target: str) -> bool:
    """Return True when *target* names a path this collector may test on disk.

    Everything else is out of scope BY DESIGN rather than unimplemented: a URL, a
    protocol-relative ``//host/x``, a site-root ``/path`` (which is resolved by a
    web server, not by this checkout) and a bare ``#fragment`` are all skipped, so
    none of them can become a finding on any repository.

    A leading ``<`` is rejected for a different reason: a well-formed bracketed
    destination never reaches here with its brackets, because ``_LINK_RE`` captures the
    inside of them -- so a target that still starts with one came from an UNTERMINATED
    ``<`` and is a parse fragment, not a path. Existence-testing such a fragment is
    exactly how the false positive ``broken link -> <my`` was emitted.
    """
    if not target or target.startswith(("#", "/", "<")):
        return False
    return not _URL_SCHEME_RE.match(target)


def _target_paths(target: str) -> tuple[str, ...]:
    """Return the on-disk name(s) *target* may denote, decoded form first.

    The fragment and query are addressing information for a reader, not part of the
    filename, so ``real.md#heading`` must be tested as ``real.md`` (Behavior 5).
    Percent-decoding is what makes ``my%20doc.md`` resolve to the file that is
    actually on disk; without it every space-bearing link in a wiki-style tree would
    be a false positive.

    WHY several forms: the caller reports only when NONE of them exists, so no
    disagreement between two reasonable percent-decoders can ever MANUFACTURE a
    finding -- at worst it costs one, which is the err-toward-silence direction the
    rest of this module commits to. This is not hypothetical. A TRUNCATED escape
    (``a%C3.md``) is the measured input where the strict decode, the lenient decode
    and the raw text are three different strings: ``urllib.parse.unquote`` would pick
    the lenient one (U+FFFD), ``_percent_decode`` picks the raw one, and probing every
    form means the choice cannot change the verdict. Ordered decoded-first so the
    common case costs exactly one ``stat``.
    """
    head = target.split("#", 1)[0].split("?", 1)[0]
    forms: list[str] = []
    for form in (
        _percent_decode(head),
        _percent_decode(head, errors="replace"),
        head,
    ):
        if form and form not in forms:
            forms.append(form)
    return tuple(forms) or ("",)


# ---------------------------------------------------------------------------
# Link memo: one text -> link-candidate extraction per distinct FILE CONTENT,
# process-wide.
#
# WHY MODULE level and not an instance attribute: ``all_collectors()`` builds a
# FRESH ``BrokenDocLinkCollector`` on every call and ``cli._collect`` calls it
# once per invocation, so ``pla watch`` constructs a new instance every tick. An
# instance memo would never hit in the ONE workload this exists to fix, while
# still passing any test that reuses a single collector object -- a fail-silent
# perf regression that measures as a win. Being process-wide, the state is made
# INSPECTABLE (``broken_link_memo_stats``) and RESETTABLE
# (``clear_broken_link_memo``) rather than hidden. This is the fourth instance of
# a shape already shipped by ``todos``, ``syntax_error`` and ``merge_conflict``;
# the maps are deliberately SEPARATE (no shared helper) so no module's oracle can
# be broken by a change made for another.
#
# The memo is a pure speed-up, never a semantic change: the extracted candidates
# are a pure function of the text, so a hit, a miss and an eviction all yield
# byte-identical signals.
# ---------------------------------------------------------------------------

# One link candidate found in a document:
# ``(lineno, column, target, candidate_paths, detail)``.
# Deliberately NOT a ``ContextSignal`` and deliberately NOT resolved: a signal
# carries the CONTAINING file's relative path and a resolution carries a verdict
# about the filesystem, and both differ per file (and per moment) while the text's
# candidates do not. ``candidate_paths`` is what ``_target_paths`` derives from the
# link TEXT alone -- unresolved names, never joined to a base directory -- so
# caching it lets K byte-identical documents share ONE extraction and still each
# probe their own directory and report their own path.
_LinkRef = tuple[int, int, str, tuple[str, ...], str]

# Hard cap on retained per-file candidate lists, so scanning an unbounded monorepo
# cannot grow this map without limit. The bound is stated ABSOLUTELY and never as a
# ratio against whatever tree this checkout holds, because such a ratio decays on
# every commit while claiming to describe today; ``tests/test_source_comment_bounds.py``
# reds that shape. 4096 documents holding links covers a typical service repo
# outright, and past the cap the oldest entries are evicted, which costs speed and
# NEVER correctness. Matches its three siblings' entry cap so all four memos are one
# shape. Read at call time, so a test may lower it.
BROKEN_LINK_MEMO_MAX_ENTRIES: int = 4096

# Hard cap on the number of candidates inside a RETAINED value, because the entry
# cap alone does not bound memory: unlike ``merge_conflict``, whose memoized value
# is a single ``int`` and therefore needs no second cap, this value GROWS with the
# document -- one entry per matched link, each keeping the target plus a stripped
# line slice. The size the reader is bounded by is ``max_read_bytes``, which equals
# the named code constant ``LARGE_FILE_MIN_BYTES`` (5,000,000 bytes), and a document
# built entirely of 12-byte ``[a](b.md)`` links reaches that bound at roughly 400,000
# candidates in ONE value -- about 1,600x this cap -- so without this the true
# ceiling would be 4096 x 5 MB. With it, the map is bounded by
# entries x candidates x line length. 256 is far above what any hand-written document
# carries; the generated tables that blow past it are exactly the values not worth
# retaining. A value with MORE candidates than this is simply not retained --
# retention is an optimization, so declining it costs speed and never correctness:
# the caller always receives the COMPLETE candidate list. (Truncating instead would
# change emitted signals, since ``max_items`` applies only after the global sort.)
# Read at call time, so a test may lower it.
BROKEN_LINK_MEMO_MAX_LINKS_PER_FILE: int = 256

# 128 bits of digest. Collisions are the only way this memo could serve the wrong
# candidates, and at 2**-128 per pair that is far below the probability of the
# filesystem handing back wrong bytes; a shorter digest saves nothing measurable.
_DIGEST_SIZE: int = 16

_BROKEN_LINK_MEMO: dict[bytes, tuple[_LinkRef, ...]] = {}
_BROKEN_LINK_MEMO_COUNTS: dict[str, int] = {"hits": 0, "misses": 0}


def clear_broken_link_memo() -> None:
    """Empty the link memo and zero its counters.

    WHY this is public on a module that otherwise exposes one collector class: a
    process-wide cache that cannot be reset is hidden global state -- untestable,
    and a liability in the long-lived ``watch`` process it exists to serve. It
    clears IN PLACE rather than rebinding, so any holder of the dict object sees
    the same emptying. Touches ONLY this memo: the todo, parse and merge-marker
    memos are separate maps and are unaffected.
    """
    _BROKEN_LINK_MEMO.clear()
    _BROKEN_LINK_MEMO_COUNTS["hits"] = 0
    _BROKEN_LINK_MEMO_COUNTS["misses"] = 0


def broken_link_memo_stats() -> dict[str, int]:
    """Return a fresh snapshot: ``{"hits", "misses", "entries"}``.

    ``hits`` = candidate lists served without re-extracting; ``misses`` =
    extractions performed (whether or not the result was retained); ``entries`` =
    candidate lists currently retained, never above
    ``BROKEN_LINK_MEMO_MAX_ENTRIES``. A COPY is returned so a caller cannot mutate
    the live counters, and ``entries`` is DERIVED from the map (never tracked
    separately) so it cannot drift from what is actually retained.

    Note what these counters do NOT count: existence probes, which re-run for
    every candidate on every scan and are therefore not part of the memo at all.
    """
    return {
        "hits": _BROKEN_LINK_MEMO_COUNTS["hits"],
        "misses": _BROKEN_LINK_MEMO_COUNTS["misses"],
        "entries": len(_BROKEN_LINK_MEMO),
    }


def _remember_refs(digest: bytes, refs: tuple[_LinkRef, ...]) -> None:
    """Retain one candidate list under both caps, evicting the OLDEST entries first.

    FIFO (``dict`` preserves insertion order) rather than LRU: eviction order is
    then a pure function of the insertion sequence, so two identical scans evict
    identically -- deterministic, which access-ordered eviction is not without
    extra bookkeeping this cannot justify. An entry cap of ``<= 0`` disables
    retention entirely (nothing is stored, so nothing can hit), which keeps the
    "entries never exceeds the cap" invariant true for every cap value.
    """
    cap = BROKEN_LINK_MEMO_MAX_ENTRIES
    if cap <= 0:
        return
    if len(refs) > BROKEN_LINK_MEMO_MAX_LINKS_PER_FILE:
        # Over-large value: skipped so aggregate memory is bounded by
        # entries x candidates x line length instead of by one document's size.
        return
    while len(_BROKEN_LINK_MEMO) >= cap:
        del _BROKEN_LINK_MEMO[next(iter(_BROKEN_LINK_MEMO))]
    _BROKEN_LINK_MEMO[digest] = refs


def _link_refs(text: str) -> tuple[_LinkRef, ...]:
    """Return *text*'s link candidates, extracting at most once per distinct text.

    WHY the key is a DIGEST OF THE TEXT and never ``(path, mtime, size)``: this
    memo may only ever return what the extraction pass would return TODAY, and with
    a content digest that proof is definitional -- digest equality IS input
    equality, so an edited document cannot hit a stale entry. An mtime/size key
    cannot promise that (a coarse mtime plus an unchanged size serves a stale
    result), and trading determinism for speed is not a trade worth making here.

    The digest is taken over the DECODED TEXT because that is exactly the argument
    handed to the extraction, so the soundness proof is about the memoized
    function's INPUT rather than about the file -- and no second read is needed,
    which matters because the single ``read_text`` decode is a pinned seam (the
    oversized-file guard's proof counts exactly one read per candidate document).
    Note this is a property of the TEXT, not of the bytes: ``read_text`` applies
    universal-newline translation, so a CRLF document and its LF twin share ONE
    entry -- correctly, since the extraction sees identical input in both cases.
    """
    digest = hashlib.blake2b(text.encode("utf-8"), digest_size=_DIGEST_SIZE).digest()
    if digest in _BROKEN_LINK_MEMO:
        _BROKEN_LINK_MEMO_COUNTS["hits"] += 1
        return _BROKEN_LINK_MEMO[digest]

    refs = _scan_link_refs(text)
    _BROKEN_LINK_MEMO_COUNTS["misses"] += 1
    _remember_refs(digest, refs)
    return refs


def _scan_link_refs(text: str) -> tuple[_LinkRef, ...]:
    """Extract every testable link candidate from *text* -- the memoized work.

    PURE and path-free by construction: it reads nothing but *text* and touches no
    filesystem, which is what makes the digest key sound and what lets one result
    serve every document holding these bytes. A tuple is returned (not a list) so a
    retained value cannot be mutated by a caller through the memo.

    Everything decided here is a property of the text: the fenced-block mask, the
    inline-code mask, whether a target names a path at all, and which on-disk NAMES
    a target may denote. The one thing left to the caller is whether any of those
    names is actually there -- see ``_broken_links_in``.
    """
    lines = text.splitlines()
    in_fence = _fence_mask(lines)

    refs: list[_LinkRef] = []
    for idx, line in enumerate(lines):
        if in_fence[idx]:
            continue
        code_ranges = _code_span_ranges(line)
        for match in _LINK_RE.finditer(line):
            # Exactly one of the two destination alternatives participates; the
            # bracketed one yields the destination WITHOUT its brackets, which is also
            # what the emitted summary should name.
            angle = match.group("angle")
            group = "angle" if angle is not None else "target"
            dest_start, dest_end = match.span(group)
            # WHY the mask is compared against the DESTINATION's span and not against
            # the whole match: a code-formatted LABEL (``[`SPEC.md`](SPEC.md)``, this
            # product's own dominant citation idiom) is prose formatting on the
            # READER's side of the link, yet under a whole-match test those backticks
            # masked the link and hid a dead target from a gate that ARMS this kind.
            # What a code span legitimately hides is a documented sample, and that is
            # decided by where the DESTINATION sits -- so a link wholly inside a code
            # span stays silent, while a backticked label no longer blinds the
            # collector.
            if any(
                dest_start < end and start < dest_end
                for start, end in code_ranges
            ):
                continue  # The destination is inside a code span: a code sample.
            target = angle if angle is not None else match.group("target")
            if not _is_filesystem_target(target):
                continue
            candidates = _target_paths(target)
            if not candidates[0]:
                continue
            refs.append(
                (idx + 1, match.start(), target, candidates, line.strip()[:200])
            )
    return tuple(refs)


@dataclass
class BrokenDocLinkCollector(BaseCollector):
    """Emit one ContextSignal per Markdown link whose relative target is missing.

    WHY a dataclass with defaults: mirrors the sibling collectors so
    ``all_collectors()`` can construct it with no arguments, while a caller scanning
    a doc-heavy tree can still cap how many findings one scan reports.

    WHY *max_read_bytes*: this collector DECODES every ``*.md`` file it walks, so
    without an upper bound one vendored 50 MB generated document is pulled into
    memory on every scan -- and ``pla watch`` repeats that each interval. Files whose
    ``st_size`` EXCEEDS the cap are skipped unread. That is not a blind spot: the cap
    equals ``LARGE_FILE_MIN_BYTES`` and ``LargeFileCollector`` reports at
    ``size >= LARGE_FILE_MIN_BYTES`` from ``st_size`` alone, so skipped-here implies
    reported-there, and the strictly-greater comparison overlaps that inclusive
    ``>=`` by exactly one size so the two ranges leave no gap.
    """

    name: str = "broken_link"
    max_items: int = 30
    max_read_bytes: int = LARGE_FILE_MIN_BYTES

    def _collect(self, root: Path) -> list[ContextSignal]:
        """Walk *root* and return one signal per broken relative Markdown link."""
        if not root.is_dir():
            return []

        # Accumulate (relpath, lineno, column, signal) so ordering is a total
        # function of the filesystem rather than of the traversal's own order.
        found: list[tuple[str, int, int, ContextSignal]] = []

        # The listing arrives ALREADY pruned of noise + hidden DIRS (Behavior 9):
        # dir_source owns the package dir-prune policy and applies it during the
        # traversal, so this collector no longer carries the rule -- and inside
        # the scan scope opened by cli._collect that ONE traversal is shared with
        # every sibling walking the same root instead of being re-paid per
        # collector.
        for dirpath, _dirnames, filenames in dir_source.walk(root):
            for fname in filenames:
                if _is_hidden(fname):
                    continue
                if Path(fname).suffix.lower() != ".md":
                    continue
                full = Path(dirpath) / fname
                # Per-file guard, inside ONE try so the size read is under the same
                # never-raise discipline as the decode: a file that vanishes or
                # denies stat() between the walk and here is skipped and its
                # siblings still emit.
                try:
                    if full.stat().st_size > self.max_read_bytes:
                        continue
                    # Shared per-scan decode, so a doc this collector reads is not
                    # re-read by ``todos``. ``strict=True`` yields None for bytes
                    # that are not valid UTF-8, which is what makes Behavior 11
                    # true by CONSTRUCTION: a file whose text we cannot trust
                    # contributes no signal at all, rather than being scanned with
                    # U+FFFD substituted mid-link. (The spec's acceptance list
                    # named ``strict=False``; that policy would let a mojibake file
                    # still emit findings, contradicting its own Behavior 11, so the
                    # observable behavior wins -- and it matches ``syntax_error``,
                    # the other collector that must not act on suspect text.)
                    text = text_source.read_text(full, strict=True)
                except OSError:
                    continue
                if text is None:
                    continue
                found.extend(_broken_links_in(text, full, root, self.name))

        # Deterministic: sort by (relpath, lineno, column) ascending, then cap -- so
        # WHICH findings survive max_items and their order are independent of
        # traversal order, matching the sibling file-scanning collectors.
        found.sort(key=lambda item: (item[0], item[1], item[2]))
        return [signal for _, _, _, signal in found[: self.max_items]]


def _broken_links_in(
    text: str,
    file_path: Path,
    root: Path,
    source_name: str,
) -> list[tuple[str, int, int, ContextSignal]]:
    """Return *text*'s broken links as ``(relpath, lineno, column, signal)`` tuples.

    This is the thin PATH-AWARE half of the work: everything that depends on
    *file_path* / *root* -- or on what is on disk right now -- lives here, and the
    text -> candidate extraction it wraps is memoized on the text alone. Keeping the
    two apart is what makes the memo correct for repeated content AND safe for a
    long-lived ``watch`` process: the extraction is retained, the ``.exists()``
    probes below are not, so deleting a target that a previous scan resolved turns
    the very next scan's silence into a finding. See ``_link_refs``.

    Resolution is relative to the CONTAINING FILE's directory, which is how a
    Markdown renderer resolves it -- not relative to the workspace root (Behavior 7).
    The emitted ``path`` is the containing file, never the missing target: the target
    does not exist, so it is not addressable, and a reader needs to know which
    document to edit.
    """
    rel = BaseCollector._relative(root, file_path)
    base = file_path.parent

    found: list[tuple[str, int, int, ContextSignal]] = []
    for lineno, column, target, candidates, detail in _link_refs(text):
        try:
            if any((base / candidate).exists() for candidate in candidates):
                continue
        except (OSError, ValueError):
            # An unusable target (embedded NUL, a name the platform rejects)
            # is not evidence of a broken link -- stay silent rather than
            # guess.
            continue
        found.append(
            (
                rel,
                lineno,
                column,
                ContextSignal(
                    source=source_name,
                    kind="broken_link",
                    summary=f"{rel}:{lineno}: broken link -> {target}",
                    detail=detail,
                    path=rel,
                    weight=0.6,
                    timestamp=None,
                ),
            )
        )
    return found
