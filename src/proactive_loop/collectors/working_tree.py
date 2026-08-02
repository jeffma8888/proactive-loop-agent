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

Fully offline and pure-stdlib (``subprocess`` to the local ``git`` only). Unpushed
detection reads the local tracking ref (``@{u}..HEAD``) ONLY -- it NEVER runs
``git fetch`` / ``git ls-remote`` or any network operation (SPEC section 5, the
fully-offline non-negotiable).
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

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


def _parse_ahead_count(stdout: str) -> int | None:
    """Parse ``git rev-list --count @{u}..HEAD`` output into an int, or None.

    WHY: when a branch has no configured upstream, rev-list exits non-zero and we
    never reach here; when it succeeds the output is a single integer line.
    Anything unparseable degrades to None (treated as "no unpushed signal") so a
    surprising git build can never crash the scan.
    """
    text = stdout.strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


@dataclass
class WorkingTreeCollector:
    """Emit present-state git signals: dirty paths + unpushed commits.

    Scans *root* and each direct child directory that contains a ``.git`` folder,
    mirroring GitActivityCollector so a workspace of sibling sub-projects is
    covered (present-state parity with the committed-past collector). For each
    repo it reports:

    * one ``kind="working_tree"`` signal per changed path (tracked change or
      untracked file), capped at ``max_items`` per-path signals in total, and
    * at most one summary signal naming how many local commits are unpushed
      (ahead of the branch's upstream), which is independent of the per-path cap.

    WHY a dataclass with defaults: mirrors the sibling collectors so
    ``all_collectors()`` can construct it with no arguments, while a caller
    scanning a very large tree can still cap the number of per-path signals.
    """

    name: str = "working_tree"
    max_items: int = 30

    def collect(self, root: Path) -> list[ContextSignal]:
        """Return working-tree signals for *root* and its direct child repos.

        Never raises: any error (missing dir, git absent, subprocess failure)
        degrades to ``[]``, honouring the Collector contract so one unreadable
        repo can never abort a scan.
        """
        try:
            return self._collect(root)
        except Exception:
            return []

    def _collect(self, root: Path) -> list[ContextSignal]:
        if not root.is_dir():
            return []

        path_signals: list[ContextSignal] = []
        summary_signals: list[ContextSignal] = []
        seen: set[str] = set()

        for directory in self._dirs_to_scan(root):
            path_signals.extend(self._dirty_path_signals(directory, seen))
            unpushed = self._unpushed_signal(directory)
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
    ) -> list[ContextSignal]:
        """One signal per changed path from ``git status --porcelain``.

        A non-zero return code (not a repo) or unavailable git degrades to ``[]``
        for this directory. Duplicate summaries (e.g. root and a nested repo both
        surfacing the same path) are collapsed via *seen*.
        """
        result = _run_git(directory, ["status", "--porcelain"])
        if result is None or result.returncode != 0:
            return []

        signals: list[ContextSignal] = []
        for line in result.stdout.splitlines():
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
        return signals

    def _unpushed_signal(self, directory: Path) -> ContextSignal | None:
        """Summary signal for local commits ahead of the branch's upstream.

        Reads ONLY the local tracking ref via ``git rev-list --count @{u}..HEAD``
        -- no ``git fetch``, no network (SPEC section 5). A repo with no
        configured upstream makes rev-list exit non-zero, so this returns
        ``None`` (Behavior 8). A zero-ahead count also yields ``None`` (nothing
        to nudge about).
        """
        result = _run_git(directory, ["rev-list", "--count", "@{u}..HEAD"])
        if result is None or result.returncode != 0:
            return None
        count = _parse_ahead_count(result.stdout)
        if count is None or count <= 0:
            return None
        return ContextSignal(
            source=self.name,
            kind="working_tree",
            summary=(
                f"{count} unpushed commit(s) in {directory.name} ahead of upstream"
            ),
            detail="local commits not yet pushed (@{u}..HEAD, local ref only, no network)",
            path=None,
            weight=_WEIGHT_UNPUSHED,
            timestamp=None,
        )
