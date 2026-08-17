"""DependencyCollector: surface project dependency manifests as L2 signals.

WHY this collector exists: the scout's proactivity ceiling is set by *what it
can perceive* (SPEC section 1, 4.1). Before this collector the scout saw recent
files, git activity, TODO/FIXME comments, and notes -- it was completely blind
to dependency manifests, so it could never surface an obvious stack-maintenance
nudge ("requirements.txt pins nothing", "package.json has deps but no lockfile").
This collector reports plain *facts* about the stack (which manifest, which
ecosystem, how many declared deps); it makes no judgement -- the synthesizer LLM
decides whether a goal is warranted. A new kind="dependency" flows into the
synthesis prompt automatically because synthesizer._build_prompt iterates
snapshot.by_kind(), so this file plus one registry line is the whole wiring cost.

Pure stdlib only (tomllib for pyproject.toml, json for package.json, line-split
for requirements.txt) so the runtime stays pydantic-v2-only and fully offline.
"""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass
from pathlib import Path

from proactive_loop.collectors import dir_source
from proactive_loop.collectors.base import BaseCollector
from proactive_loop.models import ContextSignal

# The three manifest filenames we recognise. Deliberately narrow (spec Out of
# Scope): no Cargo.toml / go.mod / Pipfile / setup.py / lockfiles, etc.
_MANIFEST_NAMES: frozenset[str] = frozenset(
    {"pyproject.toml", "requirements.txt", "package.json"}
)

# How many dependency names to keep in the human-readable `detail` sample. The
# detail is a best-effort excerpt only; tests assert nothing about its content
# beyond it being a str, so this cap just keeps the prompt bounded.
_DETAIL_SAMPLE: int = 8


@dataclass
class DependencyCollector(BaseCollector):
    """Emit one ContextSignal per dependency manifest found under *root*.

    WHY a dataclass with defaults: mirrors the sibling collectors so
    all_collectors() can construct it with no arguments, while a caller scanning
    a very large tree can still cap the number of manifests reported.
    """

    name: str = "dependencies"
    max_manifests: int = 20

    def _collect(self, root: Path) -> list[ContextSignal]:
        """Walk *root* and return one signal per recognised manifest."""
        if not root.is_dir():
            return []

        # Collect (relative-path, signal) pairs so we can order deterministically.
        found: list[tuple[str, ContextSignal]] = []
        # The listing arrives ALREADY pruned of noise + hidden dirs (spec Behavior 9):
        # dir_source applies the package's one prune policy during the traversal, so
        # this collector no longer needs the rule -- and inside cli._collect's scan
        # scope the traversal itself is shared with every sibling walking the same
        # root, instead of being re-paid once per collector.
        for dirpath, _dirnames, filenames in dir_source.walk(root):
            for fname in filenames:
                if fname not in _MANIFEST_NAMES:
                    continue
                full = Path(dirpath) / fname
                rel = self._relative(root, full)
                # Per-manifest guard: one broken manifest is skipped without
                # aborting the walk; its siblings still emit (spec Behavior 7).
                try:
                    signal = self._signal_for(full, rel, fname)
                except Exception:
                    continue
                found.append((rel, signal))

        # Deterministic ordering across platforms / os.walk order (Behavior 10):
        # sort by the manifest's relative path, then cap.
        found.sort(key=lambda pair: pair[0])
        return [signal for _, signal in found[: self.max_manifests]]

    def _signal_for(self, path: Path, rel: str, fname: str) -> ContextSignal:
        """Build one dependency signal, dispatching on the manifest filename.

        The absolute path lives in `path` (mirrors RecentFilesCollector); the
        summary uses the *relative* path so it is stable and human-readable.
        """
        if fname == "pyproject.toml":
            ecosystem, count, names = "Python", *self._count_pyproject(path)
        elif fname == "requirements.txt":
            ecosystem, count, names = "Python", *self._count_requirements(path)
        else:  # package.json
            ecosystem, count, names = "Node", *self._count_package_json(path)

        return ContextSignal(
            source=self.name,
            kind="dependency",
            summary=f"{ecosystem}: {rel} ({count} deps)",
            detail=", ".join(names[:_DETAIL_SAMPLE]),
            path=str(path),
            # Fixed mid-range weight: a manifest is a durable, always-relevant
            # stack fact, not time-decaying like a recently-modified file.
            weight=0.6,
            timestamp=None,
        )

    @staticmethod
    def _count_pyproject(path: Path) -> tuple[int, list[str]]:
        """Count PEP 621 [project].dependencies only.

        WHY only that array (spec Out of Scope): counting optional-dependencies,
        PEP 735 dependency-groups, or [tool.poetry.dependencies] would make the
        number ambiguous. Absent table -> 0.
        """
        with path.open("rb") as handle:
            data = tomllib.load(handle)
        project = data.get("project", {})
        deps = project.get("dependencies", []) if isinstance(project, dict) else []
        if not isinstance(deps, list):
            return 0, []
        names = [str(dep) for dep in deps]
        return len(names), names

    @staticmethod
    def _count_requirements(path: Path) -> tuple[int, list[str]]:
        """Count real dependency lines in requirements.txt.

        A dependency line = after strip(): non-empty, not starting with '#'
        (comment), and not starting with '-' (option / editable line like
        '-e .' or '-r base.txt'). See spec Behavior 3.
        """
        names: list[str] = []
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or line.startswith("-"):
                continue
            names.append(line)
        return len(names), names

    @staticmethod
    def _count_package_json(path: Path) -> tuple[int, list[str]]:
        """Combined count of `dependencies` + `devDependencies` object keys.

        Missing either object contributes 0 (spec Behaviors 2, 5).
        """
        data = json.loads(path.read_text(encoding="utf-8"))
        names: list[str] = []
        for key in ("dependencies", "devDependencies"):
            section = data.get(key, {})
            if isinstance(section, dict):
                names.extend(str(name) for name in section)
        return len(names), names
