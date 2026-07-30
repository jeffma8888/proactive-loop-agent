"""GitStateCollector: surface *interrupted / dangling* git operations as signals.

WHY this collector exists: the product's headline thesis (SPEC section 1) is a
proactivity layer that scans the working context and proposes what to act on.
Its two existing git collectors are each blind to one whole class of state.
``GitActivityCollector`` reads only ``git log`` — the committed *past*.
``WorkingTreeCollector`` (iter-11) reads the present diff + unpushed count. But
NEITHER detects an operation you walked away from mid-flight: an unfinished
merge, rebase, cherry-pick, or revert, or a detached HEAD. That half-done state
is the *highest-urgency* git signal precisely because it silently blocks or
corrupts everything you do next (commit onto a detached HEAD and the work is
orphaned; a half-finished rebase rots), yet it is invisible to both existing git
collectors. This is the "you-left-this-half-done" moment a proactive reminder
exists for.

WHY pure ``pathlib`` and NOT ``subprocess``: this collector's whole distinctness
is its *mechanism*. Interrupted-operation state lives in well-known marker files
inside ``.git/`` (``MERGE_HEAD``, ``rebase-merge/``, ``CHERRY_PICK_HEAD``, …), so
we read those markers directly with stdlib ``pathlib`` — no ``git`` executable, no
``subprocess``, no network. That also means it works even when ``git`` is absent.

It reports plain *facts* (which interrupted state exists, in which repo dir); it
makes no judgement — the synthesizer LLM decides whether to propose "finish or
abort the in-progress <op>". A new ``kind="git_state"`` flows into synthesis
automatically because the synthesizer iterates ``snapshot.by_kind()``, so this
file plus one registry line is the whole wiring cost (proven zero-synthesizer-
change by iters 09/11/16) — additive, non-breaking, no version bump.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from proactive_loop.models import ContextSignal

# Every git_state signal carries the same fixed weight: an interrupted/dangling
# operation is a durable, high-urgency present-state fact (it blocks or corrupts
# the next action), not a time-decaying one, so a flat weight is clearer than a
# fabricated recency curve. Sits at the same level as WorkingTreeCollector's
# unpushed-commits headline (0.8).
_WEIGHT = 0.8


@dataclass
class GitStateCollector:
    """Detect interrupted/dangling git operations by reading ``.git`` markers.

    Scans ``root`` and each *direct* child directory that is itself a git repo
    (``.git`` is a directory), mirroring the child-repo strategy of
    ``GitActivityCollector``/``WorkingTreeCollector``. For each repo it emits one
    ``kind="git_state"`` signal per detected state (merge / rebase / cherry-pick
    / revert / detached-HEAD); states are detected independently, so one repo may
    emit several signals. Output is sorted by ``summary`` ascending (deterministic
    across calls) and capped at ``max_items``.

    Pure stdlib ``pathlib`` only — no ``subprocess``, no network. Never raises;
    any error degrades to ``[]`` (Collector contract, SPEC section 4.1).
    """

    name: str = "git_state"
    max_items: int = 30

    def collect(self, root: Path) -> list[ContextSignal]:
        """Return git_state signals for *root* and its direct child repos.

        Never raises: any error (missing dir, unreadable marker, OS error)
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

        signals: list[ContextSignal] = []
        for directory in self._dirs_to_scan(root):
            signals.extend(self._signals_for_repo(directory))

        # Deterministic ordering: sort by summary ascending so repeated calls
        # yield an identical ordered list, then apply the cap.
        signals.sort(key=lambda s: s.summary)
        return signals[: self.max_items]

    @staticmethod
    def _dirs_to_scan(root: Path) -> list[Path]:
        """*root* itself, plus each of its direct child directories.

        WHY only root + direct children: a workspace often nests several
        sub-projects, each its own repo; scanning each direct child lets the
        scout surface interrupted operations across all of them (identical
        strategy to GitActivity/WorkingTree). A marker two levels deep is NOT
        surfaced — only the top level and its direct children are inspected.
        Whether a candidate dir is actually a repo (``.git`` is a directory) is
        decided in ``_signals_for_repo`` so a non-repo dir simply yields ``[]``.
        """
        dirs: list[Path] = [root]
        try:
            for child in root.iterdir():
                if child.is_dir():
                    dirs.append(child)
        except OSError:
            pass
        return dirs

    def _signals_for_repo(self, directory: Path) -> list[ContextSignal]:
        """Emit one signal per interrupted/dangling state found in *directory*.

        Skips (returns ``[]``) unless ``directory/.git`` is a *directory*. A
        ``.git`` that is a regular file is a git-worktree/submodule pointer
        (``gitdir: …``); resolving it is out of scope, so such a dir is skipped.
        """
        git_dir = directory / ".git"
        if not git_dir.is_dir():
            return []

        name = directory.name
        signals: list[ContextSignal] = []

        # Interrupted operations. Each is an independent fact; no cross-state
        # suppression (a rebase legitimately detaches HEAD, so a rebase + a raw-
        # SHA HEAD may co-emit — the synthesizer judges, not this collector).
        if (git_dir / "MERGE_HEAD").is_file():
            signals.append(
                self._signal(
                    f"Unfinished merge in progress in {name}",
                    "A merge was started but not completed (.git/MERGE_HEAD is "
                    "present). Finish it with a commit or abort with "
                    "'git merge --abort' before starting other work.",
                )
            )
        if (git_dir / "rebase-merge").is_dir() or (git_dir / "rebase-apply").is_dir():
            signals.append(
                self._signal(
                    f"Unfinished rebase in progress in {name}",
                    "A rebase is in progress (.git/rebase-merge or "
                    ".git/rebase-apply is present). Continue it with "
                    "'git rebase --continue' or abort with 'git rebase --abort'.",
                )
            )
        if (git_dir / "CHERRY_PICK_HEAD").is_file():
            signals.append(
                self._signal(
                    f"Unfinished cherry-pick in progress in {name}",
                    "A cherry-pick is in progress (.git/CHERRY_PICK_HEAD is "
                    "present). Continue it or abort with "
                    "'git cherry-pick --abort'.",
                )
            )
        if (git_dir / "REVERT_HEAD").is_file():
            signals.append(
                self._signal(
                    f"Unfinished revert in progress in {name}",
                    "A revert is in progress (.git/REVERT_HEAD is present). "
                    "Continue it or abort with 'git revert --abort'.",
                )
            )
        if self._head_is_detached(git_dir):
            signals.append(
                self._signal(
                    f"Detached HEAD in {name}",
                    "HEAD is detached: it points at a raw commit, not a branch. "
                    "New commits made here are easily orphaned — create a branch "
                    "to keep any work you do.",
                )
            )
        return signals

    @staticmethod
    def _head_is_detached(git_dir: Path) -> bool:
        """True iff ``.git/HEAD`` names a raw commit rather than a branch ref.

        An attached HEAD reads ``ref: refs/heads/<branch>``; a detached HEAD
        holds a bare object name (a 40/64-char SHA). Empty/unreadable HEAD is
        treated as not-detached (nothing to nudge about).
        """
        head = git_dir / "HEAD"
        if not head.is_file():
            return False
        try:
            content = head.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            return False
        return bool(content) and not content.startswith("ref:")

    def _signal(self, summary: str, detail: str) -> ContextSignal:
        """Build a git_state ContextSignal with the collector's fixed fields."""
        return ContextSignal(
            source=self.name,
            kind="git_state",
            summary=summary,
            detail=detail,
            path=None,
            weight=_WEIGHT,
            timestamp=None,
        )
