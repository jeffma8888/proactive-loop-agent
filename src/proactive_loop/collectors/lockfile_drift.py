"""LockfileDriftCollector: report dependency-manifest <-> lockfile drift as an L2 signal.

WHY this collector exists: the scout's proactivity ceiling is set entirely by
*what its collectors can perceive* (SPEC sections 1, 4.1). Every collector shipped
so far reports a *per-file* fact; none relates two files. This is the first
*relational* collector -- it PAIRS each dependency manifest with its sibling
lockfile and surfaces a cross-file drift fact the scout was previously blind to:
the lockfile is **missing** (deps declared, nothing pinned) or **stale** (the
manifest was edited more recently than its lockfile, so the pins no longer reflect
the declared deps). It also makes real a nudge the codebase already ADVERTISED but
never backed: ``DependencyCollector``'s own docstring cites
"package.json has deps but no lockfile" as an example synthesizer nudge, yet
``DependencyCollector`` explicitly excludes lockfiles from scope, so nothing
actually detected that case until now.

It reports a plain *fact* ("no lockfile" / "manifest newer than <lock>") and makes
no judgement -- the synthesizer LLM decides whether a "regenerate the lock" goal is
warranted, exactly like its siblings. A new ``kind="lockfile_drift"`` flows into the
synthesis prompt automatically because ``synthesizer._build_prompt`` iterates
``snapshot.by_kind()``, so this file plus the registry/catalog wiring is the whole
cost (additive, no version bump).

Detection is **presence + mtime only** -- it NEVER opens or parses lockfile/manifest
CONTENT (no hash/version comparison), so it cannot be broken by binary/non-UTF-8
files and no file contents can ever leak into a signal. Pure stdlib only (the
traversal comes from ``collectors.dir_source``, which shares one pruned ``os.walk``
per root per scan; the mtime probes are ``pathlib``), keeping the runtime
pydantic-v2-only and fully offline.

KNOWN DESIGN CAVEAT (by design, not a bug): a fresh ``git clone`` resets every file
to checkout time, so the *stale* half goes quiet right after clone -- the always-valid
*lock-missing* half carries the load, and the collector reports a FACT while leaving
the judgement to the synthesizer.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from proactive_loop.collectors import dir_source
from proactive_loop.collectors.base import BaseCollector
from proactive_loop.models import ContextSignal

# Recognized manifest -> ordered lockfile candidates, checked in the SAME directory
# as the manifest. First present candidate wins and names the reported lock. The
# order is load-bearing (it decides which lock a multi-lock repo reports against).
# requirements.txt is intentionally absent: it IS the pin, so it has no lockfile.
_MANIFEST_LOCKS: dict[str, tuple[str, ...]] = {
    "pyproject.toml": ("uv.lock", "poetry.lock", "Pipfile.lock"),
    "package.json": ("package-lock.json", "pnpm-lock.yaml", "yarn.lock"),
}


@dataclass
class LockfileDriftCollector(BaseCollector):
    """Emit one ContextSignal per manifest whose lockfile is missing or stale.

    WHY a dataclass with defaults: mirrors the sibling collectors so
    all_collectors() can construct it with no arguments, while a caller scanning a
    very large tree can still cap the number of drift signals reported.
    """

    name: str = "lockfile_drift"
    max_items: int = 30

    def _collect(self, root: Path) -> list[ContextSignal]:
        """Walk *root* and return one drift signal per missing/stale lockfile."""
        if not root.is_dir():
            return []

        # Collect (relative-path, signal) pairs so we can order deterministically.
        found: list[tuple[str, ContextSignal]] = []
        # Relative paths of manifests whose build raised and was absorbed below.
        # Accumulated rather than logged in the loop: see the single post-loop emit
        # for why ONE aggregated record per scan and not one per manifest.
        absorbed: list[str] = []
        # The listing arrives ALREADY pruned of noise + hidden dirs (Behavior 11):
        # dir_source applies the package's one prune policy during the traversal, so
        # this collector no longer needs the rule -- and inside cli._collect's scan
        # scope the traversal itself is shared with every sibling walking the same
        # root, instead of being re-paid once per collector.
        for dirpath, _dirnames, filenames in dir_source.walk(root):
            for fname in filenames:
                candidates = _MANIFEST_LOCKS.get(fname)
                if candidates is None:
                    continue
                manifest = Path(dirpath) / fname
                # Rendered BEFORE the guard so an absorbed failure can name its
                # manifest; the success path below reuses it rather than paying
                # `_relative` twice, and `_relative` itself cannot raise (it falls
                # back to the absolute path for anything outside *root*).
                rel = self._relative(root, manifest)
                # Per-manifest guard: one unreadable manifest (e.g. a stat that
                # raises OSError) is skipped without aborting the walk; its
                # sibling manifests in the tree still emit (Behavior 10).
                try:
                    signal = self._signal_for(root, manifest, candidates)
                except Exception:
                    # Breadth, `continue` and return value all deliberately
                    # unchanged -- the only addition is the record of WHICH
                    # manifest was absorbed, reported once after the walk.
                    absorbed.append(rel)
                    continue
                if signal is not None:
                    found.append((rel, signal))

        self._log_absorbed(absorbed)

        # Deterministic ordering across platforms / os.walk order (Behavior 13):
        # sort by the manifest's relative path, then cap.
        found.sort(key=lambda pair: pair[0])
        return [signal for _, signal in found[: self.max_items]]

    def _signal_for(
        self, root: Path, manifest: Path, candidates: tuple[str, ...]
    ) -> ContextSignal | None:
        """Build the drift signal for one manifest, or None when the lock is fresh.

        First-present-candidate wins (Behavior 7): the manifest's siblings are
        probed in the fixed candidate order and the first existing lockfile is the
        one compared against. A missing lock always emits; a present-but-fresh lock
        (``lock_mtime >= manifest_mtime``, so equal counts as fresh) emits nothing.
        """
        rel = self._relative(root, manifest)

        lockfile: Path | None = None
        for candidate in candidates:
            sibling = manifest.parent / candidate
            if sibling.is_file():
                lockfile = sibling
                break

        if lockfile is None:
            # Lock-missing: deps are declared but nothing is pinned (Behaviors 3/4).
            return self._make_signal(manifest, f"{rel}: manifest has no lockfile")

        # Lock present: drift only when the manifest is STRICTLY newer than the
        # lock (Behaviors 5/6). Equal mtimes count as fresh so a freshly-regenerated
        # lock is never nagged.
        if manifest.stat().st_mtime > lockfile.stat().st_mtime:
            lockrel = self._relative(root, lockfile)
            return self._make_signal(manifest, f"{rel}: manifest newer than {lockrel}")

        return None

    def _make_signal(self, manifest: Path, summary: str) -> ContextSignal:
        """Build one drift signal.

        The absolute manifest path lives in ``path`` (mirrors the sibling
        collectors); the summary uses the *relative* path so it is stable and
        human-readable. ``weight`` is a fixed mid-range value (mirroring
        ``DependencyCollector``): drift is a durable stack fact, not time-decaying.
        """
        return ContextSignal(
            source=self.name,
            kind="lockfile_drift",
            summary=summary,
            detail="",
            path=str(manifest),
            weight=0.6,
            timestamp=None,
        )
