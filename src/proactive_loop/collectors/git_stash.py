"""GitStashCollector: surface forgotten ``git stash`` entries as signals.

WHY this collector exists: the product's headline thesis (SPEC section 1) is a
proactivity layer that scans the working context and proposes what the user
*forgot to do*. The git-perception family has three complementary members, each
blind to one whole class of state. ``GitActivityCollector`` reads only ``git
log`` — the committed *past*. ``WorkingTreeCollector`` (iter-11) reads the
*present* (uncommitted diff + unpushed local commits). ``GitStateCollector``
(iter-16) reads *interrupted* operations (merge / rebase / cherry-pick / revert,
detached HEAD). NONE of them can see **stashed** work — changes the user
deliberately shelved with ``git stash`` and then forgot. A stale stash holds
real edits, is invisible in ``git status`` and ``git log``, and silently rots.
Surfacing "repo X has 3 stashed changesets, latest: 'wip: refactor auth'" is a
high-signal proactive nudge the agent literally cannot produce without this.

WHY pure ``pathlib`` and NOT ``subprocess``: exactly like ``GitStateCollector``,
the distinctness is the *mechanism*. Git records each stash push as a reflog
line appended to ``.git/logs/refs/stash``, so we read that marker file directly
with stdlib ``pathlib`` — no ``git`` executable, no ``subprocess``, no network.
That also means it works even when ``git`` is absent, and it structurally cannot
inspect stashed *content* (we only ever read the reflog's one-line-per-entry
messages, never ``.git/objects``).

It reports plain *facts* (how many stash entries a repo has and their messages);
it makes no judgement — the synthesizer LLM decides whether to propose "review
or drop the stale stash". A new ``kind="git_stash"`` flows into synthesis
automatically because the synthesizer iterates ``snapshot.by_kind()``, so this
file plus one registry line is the whole wiring cost (proven zero-synthesizer-
change by iters 09/11/16/28/37/42) — additive, non-breaking, no version bump.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from proactive_loop.collectors.base import BaseCollector
from proactive_loop.models import ContextSignal

# Every git_stash signal carries the same fixed weight. Shelved work is a real
# but *lower-urgency* fact than an interrupted operation (git_state, 0.8): a
# stash blocks nothing and corrupts nothing — it just quietly rots — so it sits
# below the interrupted-op headline while still being a durable, non-decaying
# present-state fact (a flat weight is clearer than a fabricated recency curve).
_WEIGHT = 0.6


@dataclass
class GitStashCollector(BaseCollector):
    """Detect forgotten ``git stash`` entries by reading the stash reflog.

    Scans ``root`` and each *direct* child directory that is itself a git repo
    (``.git`` is a directory), mirroring the child-repo strategy of the other
    three git collectors. For each repo that has a non-empty
    ``.git/logs/refs/stash`` reflog it emits exactly ONE ``kind="git_stash"``
    summary signal (count + latest message in ``summary``, all messages
    newest-first in ``detail``). Output is sorted by ``summary`` ascending
    (deterministic across calls) and capped at ``max_items``.

    Pure stdlib ``pathlib`` only — no ``subprocess``, no ``git`` invocation, no
    network. Never raises; any error degrades to ``[]`` (Collector contract,
    SPEC section 4.1).
    """

    name: str = "git_stash"
    max_items: int = 30

    def _collect(self, root: Path) -> list[ContextSignal]:
        """Return git_stash signals for *root* and its direct child repos."""
        if not root.is_dir():
            return []

        signals: list[ContextSignal] = []
        for directory in self._dirs_to_scan(root):
            signal = self._signal_for_repo(directory)
            if signal is not None:
                signals.append(signal)

        # Deterministic ordering: sort by summary ascending so repeated calls
        # yield an identical ordered list, then apply the per-signal cap.
        signals.sort(key=lambda s: s.summary)
        return signals[: self.max_items]

    @staticmethod
    def _dirs_to_scan(root: Path) -> list[Path]:
        """*root* itself, plus EVERY direct child directory, in ``iterdir`` order.

        WHY only root + direct children: a workspace often nests several
        sub-projects, each its own repo; scanning each direct child lets the
        scout surface stashes across all of them. A reflog two levels deep is
        NOT surfaced -- only the top level and its direct children are
        inspected.

        WHY this permissive flavor is safe here, and must not be merged with
        the strict one: ``_collect`` sorts every signal by ``summary`` before
        applying ``max_items``, so the order of this list is unobservable in
        the output and an arbitrary ``iterdir`` order cannot make the slate
        non-deterministic. That is what buys the cheap unfiltered walk --
        whether a candidate dir is really a repo holding a stash is decided in
        ``_signal_for_repo``, so a non-repo child costs one ``stat`` and
        yields ``None``. ``GitActivityCollector`` and ``WorkingTreeCollector``
        instead take their cross-repo output order FROM the directory order,
        so their walks must be ``sorted()`` and ``.git``-gated; folding the two
        flavors together would change the directory set scanned here -- see
        roadmap row #163.
        """
        dirs: list[Path] = [root]
        try:
            for child in root.iterdir():
                if child.is_dir():
                    dirs.append(child)
        except OSError:
            pass
        return dirs

    def _signal_for_repo(self, directory: Path) -> ContextSignal | None:
        """Emit one git_stash signal for *directory*, or ``None`` if it has none.

        Skips (returns ``None``) unless ``directory/.git`` is a *directory* and
        holds a non-empty ``logs/refs/stash`` reflog. A ``.git`` that is a
        regular file is a git-worktree/submodule pointer (``gitdir: …``);
        resolving it is out of scope, so such a dir is skipped, not dereferenced.
        """
        git_dir = directory / ".git"
        if not git_dir.is_dir():
            return None

        reflog = git_dir / "logs" / "refs" / "stash"
        if not reflog.is_file():
            return None

        try:
            # errors="replace" keeps a non-UTF-8 reflog from raising — bad bytes
            # degrade to replacement chars rather than aborting the whole scan.
            raw = reflog.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None

        # The file appends chronologically (one line per `git stash push`), so
        # file order is oldest→newest. Skip blank/whitespace-only lines.
        messages = [
            self._parse_message(line) for line in raw.splitlines() if line.strip()
        ]
        if not messages:
            return None

        # Newest first: the last reflog line is stash@{0} (the latest stash).
        newest_first = list(reversed(messages))
        newest = newest_first[0]

        count = len(messages)
        noun = "entry" if count == 1 else "entries"
        summary = f"{directory.name}: {count} stash {noun} (latest: {newest})"
        # detail lists every message newest-first, capped at max_items lines.
        detail = "\n".join(newest_first[: self.max_items])

        return ContextSignal(
            source=self.name,
            kind="git_stash",
            summary=summary,
            detail=detail,
            path=None,
            weight=_WEIGHT,
            timestamp=None,
        )

    @staticmethod
    def _parse_message(line: str) -> str:
        """Extract the stash message from one reflog line.

        A stash reflog line is
        ``<old-sha> <new-sha> <name> <email> <ts> <tz>\\t<message>`` — the
        message is everything AFTER the FIRST tab, preserved verbatim (it may
        itself contain spaces and colons, e.g. ``WIP on main: 404051f init``).
        Defensive: a line lacking a tab is treated as a message equal to the
        whole line, so a malformed reflog degrades instead of raising.
        """
        parts = line.split("\t", 1)
        return parts[1] if len(parts) > 1 else parts[0]
