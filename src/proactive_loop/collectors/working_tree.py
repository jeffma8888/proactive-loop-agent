"""WorkingTreeCollector: surface present-state git work as context signals.

WHY this collector exists: the product's core thesis (SPEC section 1) is to scan
the user's *working* context and proactively propose what to act on. Before this
collector the git perception was half-blind -- GitActivityCollector reads only
``git log``, i.e. the committed *past*. The single most actionable everyday
developer signal -- "you have modified files, untracked files, and unpushed
commits sitting in your working tree right now" -- was invisible to the scout.
That is exactly the present-state moment where a proactive nudge ("commit / push
/ finish this change") is worth the most. This collector reports plain *facts*
about the working tree (which paths changed, how many commits are unpushed); it
makes no judgement -- the synthesizer LLM decides whether a goal is warranted. A
new ``kind="working_tree"`` flows into synthesis automatically because the
synthesizer iterates ``snapshot.by_kind()``, so this file plus one registry line
is the whole wiring cost (proven zero-synthesizer-change by iter-09).

Fully offline and pure-stdlib (``subprocess`` to the local ``git`` only). ONE
``git status --porcelain --branch`` per scanned directory carries BOTH facts: the
changed paths, and -- in its ``## `` header -- how far the branch is ahead of its
upstream. WHY one command and not two: a scan pays a whole process start-up per
git invocation per directory on EVERY tick (no cache can remove it, because the
answer must be current), and ``--branch`` adds no measurable cost to a status
walk the collector already performs, so the ahead count is free where a second
process was not. Unpushed detection still reads the local remote-tracking ref
ONLY -- it NEVER runs ``git fetch`` / ``git ls-remote`` or any network operation
(SPEC section 5, the fully-offline non-negotiable).
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from proactive_loop.collectors.base import BaseCollector
from proactive_loop.models import ContextSignal

# Relevance weights, all bounded in (0, 1]. Ordered so a tracked change (real
# edits at risk of being lost) always outranks a mere untracked file, and an
# unpushed-commits headline sits between the two. WHY these fixed values: a
# dirty path is a durable present-state fact, not a time-decaying one, so a flat
# per-category weight is clearer than a fabricated recency curve.
_WEIGHT_TRACKED = 0.9
_WEIGHT_UNTRACKED = 0.5
_WEIGHT_UNPUSHED = 0.8

# subprocess timeout (seconds); mirrors GitActivityCollector so a wedged git
# call can never hang a scan.
_TIMEOUT = 10

# The whole grammar this collector depends on inside a ``--branch`` header line,
# e.g. ``## main...origin/main [ahead 3, behind 1]``. Named constants because the
# same three tokens are used to RECOGNISE the header (so it is never mistaken for
# a changed path) and to READ the count out of it.
_BRANCH_HEADER_PREFIX = "## "
_UPSTREAM_SEPARATOR = "..."
_AHEAD_TOKEN = "ahead "


def _run_git(
    directory: Path, args: list[str]
) -> subprocess.CompletedProcess[str] | None:
    """Run ``git -C <directory> <args>`` and return the result, or None on failure.

    WHY return None instead of raising: the Collector contract says a collector
    must never raise. A missing ``git`` executable, a timeout, or an OS error all
    degrade to None so the caller can skip that directory and continue the scan.
    """
    try:
        return subprocess.run(
            ["git", "-C", str(directory), *args],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None


def _classify_porcelain_line(line: str) -> tuple[str, str] | None:
    """Classify one ``git status --porcelain`` line.

    Returns ``(category, display_path)`` where ``category`` is ``"untracked"`` or
    ``"tracked"``, or ``None`` for a line that should be skipped (blank, too
    short, malformed, or an ignored ``!!`` entry). WHY a pure helper: the
    porcelain grammar is the one fiddly part of this collector, so isolating it
    keeps it unit-testable without a real git repo and honours the "skip a
    malformed line, never crash" contract.

    Porcelain v1 format is ``XY <path>`` where ``XY`` is the two-char status
    code: ``??`` = untracked, anything else = a tracked-file change (modified,
    staged, deleted, renamed, ...). Rename lines carry ``old -> new``; the raw
    remainder is kept as the display path (rename-target parsing is out of scope
    per the spec).
    """
    # Shortest meaningful line is "XY p" (code, space, one-char path) = 4 chars.
    if len(line) < 4:
        return None
    code = line[:2]
    path = line[3:].strip()
    if not path:
        return None
    if code == "!!":
        # Ignored files only appear with --ignored, which we never pass; guard
        # anyway so a caller-configured git alias can't leak them in.
        return None
    category = "untracked" if code == "??" else "tracked"
    return category, path


def _parse_ahead_count(text: str) -> int | None:
    """Parse a bare ahead-count token into an int, or None if unparseable.

    Fed the digits that follow ``ahead `` in a ``--branch`` header (see
    ``_parse_branch_header_ahead``). Anything unparseable -- empty, blank,
    non-numeric, or more than one token -- degrades to None (treated as "no
    unpushed signal") so a surprising git build can never crash the scan.
    """
    stripped = text.strip()
    if not stripped:
        return None
    try:
        return int(stripped)
    except ValueError:
        return None


def _parse_branch_header_ahead(line: str) -> int | None:
    """Ahead-of-upstream count carried by a ``--branch`` header line, or None.

    ``git status --porcelain --branch`` prefixes its output with exactly one
    metadata line, e.g. ``## main...origin/main [ahead 3, behind 1]``. None means
    "no unpushed signal" and covers exactly the cases in which an explicit
    ``git rev-list --count @{u}..HEAD`` would exit non-zero or answer zero: no
    upstream configured (``## main``), a detached HEAD (``## HEAD (no branch)``),
    an unborn branch (``## No commits yet on main``), a vanished upstream ref
    (``[gone]``), an in-sync branch (no bracket), or an unparseable count.

    WHY key the count on the ``ahead `` token rather than on "a bracket is
    present": ``[gone]`` (the upstream ref was deleted, or the repo is a clone of
    an empty remote) and ``[different]`` (emitted under ``--no-ahead-behind``,
    which this collector never passes) are real bracket forms that carry NO
    count, so a bracket-keyed parser would mis-read them as a divergence report.

    WHY a pure helper: the header grammar is the one fiddly part of reading the
    count out of the status output, so it stays unit-testable with no git repo,
    honouring the same "skip a malformed line, never crash" contract as
    ``_classify_porcelain_line``.
    """
    if not line.startswith(_BRANCH_HEADER_PREFIX):
        return None
    body = line[len(_BRANCH_HEADER_PREFIX):]
    refs, bracket, divergence = body.rpartition(" [")
    if not bracket or not divergence.endswith("]"):
        # No divergence bracket at all: either in sync with the upstream, or no
        # upstream/branch to be ahead of. Both mean "no signal".
        return None
    if _UPSTREAM_SEPARATOR not in refs:
        # A bracket with no ``branch...upstream`` pair in front of it is not a
        # divergence report. ``git check-ref-format`` forbids both ``..`` and
        # ``[`` inside a refname, so the separator can never be part of a branch
        # name and the bracket can never be anything but git's own metadata.
        return None
    for token in divergence[:-1].split(","):
        stripped = token.strip()
        if stripped.startswith(_AHEAD_TOKEN):
            return _parse_ahead_count(stripped[len(_AHEAD_TOKEN):])
    return None


@dataclass
class WorkingTreeCollector(BaseCollector):
    """Emit present-state git signals: dirty paths + unpushed commits.

    Scans *root* and each direct child directory that contains a ``.git`` folder,
    mirroring GitActivityCollector so a workspace of sibling sub-projects is
    covered (present-state parity with the committed-past collector). For each
    repo it reports:

    * one ``kind="working_tree"`` signal per changed path (tracked change or
      untracked file), capped at ``max_items`` per-path signals in total, and
    * at most one summary signal naming how many local commits are unpushed
      (ahead of the branch's upstream), which is independent of the per-path cap.

    Both come from a SINGLE ``git status --porcelain --branch`` per directory, so
    the number of git processes a scan starts is one per repo, not two.

    WHY a dataclass with defaults: mirrors the sibling collectors so
    ``all_collectors()`` can construct it with no arguments, while a caller
    scanning a very large tree can still cap the number of per-path signals.
    """

    name: str = "working_tree"
    max_items: int = 30

    def _collect(self, root: Path) -> list[ContextSignal]:
        """Return working-tree signals for *root* and its direct child repos."""
        if not root.is_dir():
            return []

        path_signals: list[ContextSignal] = []
        summary_signals: list[ContextSignal] = []
        seen: set[str] = set()

        for directory in self._dirs_to_scan(root):
            dirty, ahead = self._dirty_path_signals(directory, seen)
            path_signals.extend(dirty)
            unpushed = self._unpushed_signal(directory, ahead)
            if unpushed is not None:
                summary_signals.append(unpushed)

        # Deterministic, value-first ordering: sort by descending weight then
        # summary so that if the per-path cap bites we keep the highest-value
        # signals (tracked changes ahead of untracked files) in a stable order.
        path_signals.sort(key=lambda s: (-s.weight, s.summary))

        # The per-path cap applies ONLY to per-changed-path signals; the unpushed
        # summary is a separate, always-included headline and does not count
        # against it.
        return path_signals[: self.max_items] + summary_signals

    @staticmethod
    def _dirs_to_scan(root: Path) -> list[Path]:
        """*root* itself, plus each direct child directory holding a ``.git``.

        WHY scan children: a workspace often nests several sub-projects, each its
        own repo; scanning each lets the scout see dirty/unpushed state across
        all of them (identical strategy to GitActivityCollector).
        """
        dirs: list[Path] = [root]
        # Scan child repos in ascending name order (`sorted`) so a multi-repo
        # workspace's cross-repo unpushed-summary signal order is deterministic
        # (filesystem iterdir order is arbitrary); the `sorted()` stays INSIDE
        # the try/except so an OSError raised while it eagerly consumes the
        # iterator degrades to root-only exactly as before.
        try:
            for child in sorted(root.iterdir()):
                if (
                    child.is_dir()
                    and (child / ".git").exists()
                    and child not in dirs
                ):
                    dirs.append(child)
        except OSError:
            pass
        return dirs

    def _dirty_path_signals(
        self, directory: Path, seen: set[str]
    ) -> tuple[list[ContextSignal], int | None]:
        """Signals per changed path, PLUS the ahead count, from one git spawn.

        Returns ``(path_signals, ahead)``. WHY the pair rather than two methods:
        ``git status --porcelain --branch`` answers both questions in one process,
        and splitting the result across two callers would mean either spawning
        twice again or caching git output across the scan (which the spec forbids).
        A non-zero return code (not a repo) or unavailable git degrades to
        ``([], None)`` for this directory. Duplicate summaries (e.g. root and a
        nested repo both surfacing the same path) are collapsed via *seen*.
        ``ahead`` is ``None`` whenever the header reports no upstream to be ahead
        of, or a count that will not parse; see ``_parse_branch_header_ahead``.
        """
        result = _run_git(directory, ["status", "--porcelain", "--branch"])
        if result is None or result.returncode != 0:
            return [], None

        ahead: int | None = None
        signals: list[ContextSignal] = []
        for line in result.stdout.splitlines():
            if line.startswith(_BRANCH_HEADER_PREFIX):
                # The header is metadata, never a changed path, and it MUST be
                # consumed here: `_classify_porcelain_line` special-cases only
                # `??` and `!!`, so left alone it would emit a bogus
                # "uncommitted change" signal for a path named after the branch
                # and its upstream. A porcelain data line can never be mistaken
                # for it, because a data line's first two bytes are always a
                # status code, and git prints exactly one header, first.
                ahead = _parse_branch_header_ahead(line)
                continue
            classified = _classify_porcelain_line(line)
            if classified is None:
                continue
            category, display = classified
            if category == "untracked":
                summary = f"Untracked file in {directory.name}: {display}"
                detail = "untracked (not yet added to git)"
                weight = _WEIGHT_UNTRACKED
            else:
                summary = f"Uncommitted change in {directory.name}: {display}"
                detail = "tracked change not yet committed"
                weight = _WEIGHT_TRACKED
            if summary in seen:
                continue
            seen.add(summary)
            signals.append(
                ContextSignal(
                    source=self.name,
                    kind="working_tree",
                    summary=summary,
                    detail=detail,
                    path=display,
                    weight=weight,
                    timestamp=None,
                )
            )
        return signals, ahead

    def _unpushed_signal(
        self, directory: Path, ahead: int | None
    ) -> ContextSignal | None:
        """Summary signal for *ahead* local commits, or None when there is none.

        *ahead* is the count read from the ``## `` header of this directory's
        single ``git status --porcelain --branch`` -- a purely local comparison
        against the remote-tracking ref, with no ``git fetch`` and no network
        (SPEC section 5, Behavior 8). ``None`` (no upstream configured, detached
        HEAD, unborn branch, vanished upstream ref, unparseable count) and a
        zero-or-negative count both yield ``None``: nothing to nudge about.
        """
        if ahead is None or ahead <= 0:
            return None
        return ContextSignal(
            source=self.name,
            kind="working_tree",
            summary=(
                f"{ahead} unpushed commit(s) in {directory.name} ahead of upstream"
            ),
            detail="local commits not yet pushed (@{u}..HEAD, local ref only, no network)",
            path=None,
            weight=_WEIGHT_UNPUSHED,
            timestamp=None,
        )
