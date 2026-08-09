"""CiConfigCollector: report the workspace's continuous-integration posture as an L2 signal.

WHY this collector exists: the scout's proactivity ceiling is set entirely by
*what its collectors can perceive* (SPEC sections 1, 4.1). The automation-posture
triad had two of three axes covered -- `DependencyCollector` sees what a repo
*depends on* (iter-09) and `TestPostureCollector` sees *whether it has tests*
(iter-16) -- but the scout was blind to the third: *whether the repo has CI at
all*. A repo with real source code but no CI configuration is a high-signal,
near-universally-actionable maintenance goal ("wire up CI"), and the synthesizer
can only propose it if a collector first surfaces the fact. This collector closes
that gap, completing the deps / tests / **CI** triad of orthogonal repo-health
axes.

It reports a plain *fact* -- "CI is configured (with system X)" or, the actionable
case, "there is source code but no CI" -- and makes no judgement; the synthesizer
LLM decides whether a "set up CI" goal is warranted, exactly like its siblings. A
new kind="ci_config" flows into the synthesis prompt automatically because
synthesizer._build_prompt iterates snapshot.by_kind(), so this file plus the
registry/catalog wiring is the whole cost (additive, no version bump).

Detection is **presence-only** and **root-anchored**: CI configuration is a
repo-root concept (source commonly lives in `src/` while CI lives at the repo
root), so a single root-level signal is emitted -- never one per subdirectory
(per-project CI granularity is SPEC Out of Scope). Markers are matched purely by
path/basename via pathlib; the collector NEVER opens file content, so it cannot be
broken by binary/non-UTF-8 files and no CI-file contents can ever leak into a
signal. Pure stdlib (os/pathlib) only, keeping the runtime pydantic-v2-only and
fully offline.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from proactive_loop.collectors.base import BaseCollector
# Reuse the EXACT skip rules the sibling filesystem collectors use (the
# SPEC-sanctioned shared seam) so a source file buried in node_modules/.venv/a
# hidden dir is invisible to the "has source" check here too.
from proactive_loop.collectors.filesystem import _SKIP_DIRS, _is_hidden
from proactive_loop.models import ContextSignal

# Extensions we treat as "code" when deciding whether a CI-less repo has anything
# to build. Deliberately narrow and language-agnostic, matching the sibling
# `test_posture._CANDIDATE_EXTS`; anything else (docs, config, data) is ignored.
_SOURCE_EXTS: frozenset[str] = frozenset({".py", ".ts", ".js", ".go", ".rs"})

# File suffixes that count as a GitHub Actions workflow inside
# `.github/workflows/`. Matches the `*.yml`/`*.yaml` glob presence-only (we never
# read the file), so an empty workflows dir -- or one holding only a README -- is
# correctly NOT treated as configured CI.
_GHA_WORKFLOW_EXTS: frozenset[str] = frozenset({".yml", ".yaml"})


def _detect_ci_system(root: Path) -> str | None:
    """Return the label of the FIRST recognized CI system rooted at *root*, else None.

    Detection is presence-only (pathlib `is_dir`/`is_file`/`iterdir`, never
    opening content) and the order below is FIXED and load-bearing: the first
    match wins and names the reported `<system>`, so a repo carrying markers for
    two systems reports deterministically (GitHub Actions before GitLab, etc.).
    """
    # 1. GitHub Actions: `.github/workflows/` must be a directory holding at least
    #    one `*.yml`/`*.yaml` FILE -- a bare/empty dir is not configured CI.
    workflows = root / ".github" / "workflows"
    if workflows.is_dir():
        for entry in workflows.iterdir():
            if entry.is_file() and entry.suffix in _GHA_WORKFLOW_EXTS:
                return "GitHub Actions"

    # 2..7. Single well-known root files, each identified by a fixed basename.
    #    Ordered most-common first; the first present file names the system.
    for filename, system in (
        (".gitlab-ci.yml", "GitLab CI"),
        (".circleci/config.yml", "CircleCI"),
        ("azure-pipelines.yml", "Azure Pipelines"),
        ("Jenkinsfile", "Jenkins"),
        (".travis.yml", "Travis CI"),
        ("bitbucket-pipelines.yml", "Bitbucket Pipelines"),
    ):
        if (root / filename).is_file():
            return system

    return None


def _has_source(root: Path) -> bool:
    """True iff any non-pruned file under *root* has a source extension.

    Walks the tree once, pruning noise + hidden dirs in place exactly like the
    sibling collectors, so a source file that lives ONLY inside `node_modules`/
    `.venv`/a hidden dir does not count (SPEC skip rule). Reads only filenames --
    never file content -- so it cannot raise on undecodable bytes.
    """
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames if not _is_hidden(d) and d not in _SKIP_DIRS
        ]
        for fname in filenames:
            if Path(fname).suffix in _SOURCE_EXTS:
                return True
    return False


@dataclass
class CiConfigCollector(BaseCollector):
    """Emit at most ONE ContextSignal describing the workspace's CI posture.

    WHY a dataclass with defaults: mirrors the sibling collectors so
    all_collectors() can construct it with no arguments. `max_items` is retained
    for family consistency only -- this collector emits at most one root-anchored
    signal, so it never actually truncates.
    """

    name: str = "ci_config"
    max_items: int = 30

    def _collect(self, root: Path) -> list[ContextSignal]:
        """Return one CI-posture signal for *root*, or [] when there is nothing to say."""
        if not root.is_dir():
            return []

        # A configured CI system is the positive fact and short-circuits FIRST:
        # if CI exists we never need to walk for source (and never touch content).
        system = _detect_ci_system(root)
        if system is not None:
            return [self._signal_for(root, f"CI configured ({system})", 0.5)]

        # No CI marker: the actionable gap only matters if there is code to build.
        # A CI-less repo with real source gets the higher weight (0.8 > the 0.5 of
        # an already-configured repo) so the synthesizer sees the missing-CI gap as
        # the more pressing fact.
        if _has_source(root):
            return [self._signal_for(root, "no CI configured", 0.8)]

        # No CI and no source (e.g. a docs-only or empty dir): nothing to act on.
        return []

    def _signal_for(self, root: Path, summary: str, weight: float) -> ContextSignal:
        """Build the single root-anchored CI-posture signal.

        The path is the workspace root itself (CI config is a repo-root concept,
        not tied to any one file), mirroring the root-anchored idiom.
        """
        return ContextSignal(
            source=self.name,
            kind="ci_config",
            summary=summary,
            detail="",
            path=str(root),
            weight=weight,
            timestamp=None,
        )
