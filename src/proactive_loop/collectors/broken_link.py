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

Pure stdlib (``os``/``re``/``pathlib``) plus the shared internal helpers, so the
runtime stays pydantic-v2-only and fully offline.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from proactive_loop.collectors.base import BaseCollector
# Reuse the EXACT skip rules the sibling filesystem collectors use, as
# ``lockfile_drift`` and ``notes`` do, so a doc buried in node_modules/.venv/a
# hidden dir is invisible here too (Behavior 9).
from proactive_loop.collectors.filesystem import _SKIP_DIRS, _is_hidden
from proactive_loop.collectors.large_file import LARGE_FILE_MIN_BYTES
# Reuse the ONE fenced-block parser rather than hand-rolling a second one: it
# already has the correct same-delimiter semantics (a ``~~~`` line cannot close a
# ``` block) and runs an unterminated fence to end-of-file.
from proactive_loop.collectors.notes import _fence_mask
# The MODULE is imported (not its ``read_text`` function) so every content
# collector resolves the shared per-scan provider through ONE patchable attribute.
from proactive_loop.collectors import text_source
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
        # function of the filesystem rather than of os.walk enumeration order.
        found: list[tuple[str, int, int, ContextSignal]] = []

        for dirpath, dirnames, filenames in os.walk(root):
            # Prune noise + hidden dirs in place, identical to the sibling
            # collectors, so os.walk never descends into them (Behavior 9).
            dirnames[:] = [
                d for d in dirnames if not _is_hidden(d) and d not in _SKIP_DIRS
            ]
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
        # os.walk order, matching the sibling file-scanning collectors.
        found.sort(key=lambda item: (item[0], item[1], item[2]))
        return [signal for _, _, _, signal in found[: self.max_items]]


def _broken_links_in(
    text: str,
    file_path: Path,
    root: Path,
    source_name: str,
) -> list[tuple[str, int, int, ContextSignal]]:
    """Return *text*'s broken links as ``(relpath, lineno, column, signal)`` tuples.

    Resolution is relative to the CONTAINING FILE's directory, which is how a
    Markdown renderer resolves it -- not relative to the workspace root (Behavior 7).
    The emitted ``path`` is the containing file, never the missing target: the target
    does not exist, so it is not addressable, and a reader needs to know which
    document to edit.
    """
    rel = BaseCollector._relative(root, file_path)
    lines = text.splitlines()
    in_fence = _fence_mask(lines)
    base = file_path.parent

    found: list[tuple[str, int, int, ContextSignal]] = []
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
            # repo's own dominant citation idiom) is prose formatting on the READER's
            # side of the link, yet under a whole-match test those backticks masked the
            # link and hid a dead target from a gate that ARMS this kind. What a code
            # span legitimately hides is a documented sample, and that is decided by
            # where the DESTINATION sits -- so a link wholly inside a code span stays
            # silent, while a backticked label no longer blinds the collector.
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
            try:
                if any((base / candidate).exists() for candidate in candidates):
                    continue
            except (OSError, ValueError):
                # An unusable target (embedded NUL, a name the platform rejects)
                # is not evidence of a broken link -- stay silent rather than
                # guess.
                continue
            lineno = idx + 1
            found.append(
                (
                    rel,
                    lineno,
                    match.start(),
                    ContextSignal(
                        source=source_name,
                        kind="broken_link",
                        summary=f"{rel}:{lineno}: broken link -> {target}",
                        detail=line.strip()[:200],
                        path=rel,
                        weight=0.6,
                        timestamp=None,
                    ),
                )
            )
    return found
