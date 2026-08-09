"""TestPostureCollector: surface source directories that have no tests as L2 signals.

WHY this collector exists: the scout's proactivity ceiling is set entirely by
*what its collectors can perceive* (SPEC sections 1, 4.1). Before this collector
the six existing collectors saw recent files, git history, uncommitted/unpushed
work, TODO/FIXME comments, notes, and dependency manifests -- none of them
noticed the single most universal actionable quality gap: **source code with
zero tests.** This collector walks the tree once and emits one deterministic
signal per top-level project directory that contains source files, reporting the
`(src, test)` file counts and flagging the untested case. It reports plain
*facts* (counts, and whether tests exist); it makes no judgement -- the
synthesizer LLM decides whether an "add tests to X" goal is warranted, exactly
like DependencyCollector. A new kind="test_posture" flows into the synthesis
prompt automatically because synthesizer._build_prompt iterates
snapshot.by_kind(), so this file plus the two-line registry wiring is the whole
cost.

Classification is purely filename/extension/directory-name heuristics (SPEC Out
of Scope): no reading of pyproject.toml/package.json for a configured runner, no
import parsing, no coverage. Pure stdlib (os/pathlib) only, so the runtime stays
pydantic-v2-only and fully offline.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from proactive_loop.collectors.base import BaseCollector
# Reuse the EXACT skip rules RecentFilesCollector uses (the SPEC-sanctioned
# shared seam, mirroring dependencies.py) so a file buried in node_modules/.venv/
# a hidden dir is invisible here too.
from proactive_loop.collectors.filesystem import _SKIP_DIRS, _is_hidden
from proactive_loop.models import ContextSignal

# File extensions we treat as "code". Deliberately narrow and language-agnostic;
# anything else (docs, config, data) is ignored entirely.
_CANDIDATE_EXTS: frozenset[str] = frozenset({".py", ".ts", ".js", ".go", ".rs"})

# Directory names that, when they appear anywhere in a candidate's path, mark it
# as a test file regardless of the file's own name (spec test-file rule (e)).
_TEST_DIR_NAMES: frozenset[str] = frozenset({"tests", "test", "__tests__"})

# The project key used for candidates that sit directly in `root`.
_ROOT_PROJECT: str = "."


def _is_test_file(rel: Path) -> bool:
    """Classify a candidate whose path relative to root is *rel* as test vs source.

    A candidate is a TEST file if ANY of the spec's five forms match:
      (a) its name starts with ``test_``            (e.g. ``test_foo.py``)
      (b) its stem ends with ``_test``              (e.g. ``foo_test.go``)
      (c) its name contains ``.test.``              (e.g. ``widget.test.js``)
      (d) its name contains ``.spec.``              (e.g. ``widget.spec.ts``)
      (e) any intermediate directory is a test dir  (e.g. ``pkg/tests/help.py``)
    Otherwise it is a SOURCE file. WHY name+dir heuristics only: they are
    language-agnostic and require no parsing, keeping the collector deterministic
    and offline (spec Out of Scope).
    """
    name = rel.name
    if name.startswith("test_"):
        return True
    if rel.stem.endswith("_test"):
        return True
    if ".test." in name or ".spec." in name:
        return True
    # Intermediate dirs = every path segment except the filename itself.
    return any(part in _TEST_DIR_NAMES for part in rel.parts[:-1])


@dataclass
class TestPostureCollector(BaseCollector):
    """Emit one ContextSignal per top-level project dir that has source files.

    WHY a dataclass with defaults: mirrors the sibling collectors so
    all_collectors() can construct it with no arguments, while a caller scanning
    a very large tree can still cap the number of projects reported.

    Attribution is by top-level segment only (the direct child of *root*, or
    ``"."`` for files directly in *root*), matching the GitActivityCollector
    "root and each direct child dir" idiom; finer per-nested-subproject
    granularity is a future increment (spec Out of Scope).
    """

    name: str = "test_posture"
    max_items: int = 20

    def _collect(self, root: Path) -> list[ContextSignal]:
        """Walk *root* and return one signal per project with source files."""
        if not root.is_dir():
            return []

        # project key -> [source_count, test_count]. A dict keyed by the stable
        # project key makes the result independent of os.walk traversal order.
        counts: dict[str, list[int]] = {}

        for dirpath, dirnames, filenames in os.walk(root):
            # Prune noise + hidden dirs in place, identical to the sibling
            # collectors, so os.walk never descends into them (spec Skip rule).
            dirnames[:] = [
                d for d in dirnames if not _is_hidden(d) and d not in _SKIP_DIRS
            ]
            for fname in filenames:
                full = Path(dirpath) / fname
                if full.suffix not in _CANDIDATE_EXTS:
                    continue  # not code -> ignored entirely
                try:
                    rel = full.relative_to(root)
                except ValueError:
                    continue
                project = rel.parts[0] if len(rel.parts) > 1 else _ROOT_PROJECT
                bucket = counts.setdefault(project, [0, 0])
                if _is_test_file(rel):
                    bucket[1] += 1
                else:
                    bucket[0] += 1

        # Emit only projects that actually contain source files; a project with
        # tests but no source is nothing to act on (spec Behavior: S > 0 only).
        signals: list[ContextSignal] = []
        for project in sorted(counts):
            src, test = counts[project]
            if src == 0:
                continue
            signals.append(self._signal_for(root, project, src, test))

        # Deterministic ordering is already ascending-by-project (sorted keys);
        # cap to keep the synthesis prompt bounded on very large trees.
        return signals[: self.max_items]

    def _signal_for(
        self, root: Path, project: str, src: int, test: int
    ) -> ContextSignal:
        """Build one test-posture signal for *project* with *src*/*test* counts.

        The path is the absolute project directory (``root`` itself for the
        ``"."`` root project); the summary carries the counts and appends
        ``" (untested)"`` iff the project has zero test files. Untested projects
        get a higher weight (0.7 vs 0.4) so the synthesizer sees quality debt as
        more pressing than an already-covered project.
        """
        untested = test == 0
        suffix = " (untested)" if untested else ""
        project_dir = root if project == _ROOT_PROJECT else root / project
        return ContextSignal(
            source=self.name,
            kind="test_posture",
            summary=f"{project}: {src} src, {test} test files{suffix}",
            detail="",
            path=str(project_dir),
            weight=0.7 if untested else 0.4,
            timestamp=None,
        )
