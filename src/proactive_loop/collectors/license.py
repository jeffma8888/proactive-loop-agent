"""LicenseCollector: report whether a code-carrying workspace ships an open-source LICENSE file (L2 signal).

WHY this collector exists: the scout's proactivity ceiling is set entirely by
*what its collectors can perceive* (SPEC sections 1, 4.1). The repo-hygiene
perception surface already covers dependencies, tests, CI, secret-shaped files,
oversized blobs, and merge conflicts -- but nothing perceived whether a repo
that ships code carries a license at all. "There is source code here but no
LICENSE" is a high-signal, near-universally-actionable open-source-hygiene gap
that maps cleanly to a concrete, artifact-shaped "add a LICENSE file" goal --
exactly the goal shape the synthesizer is tuned to prefer (v0.1.1 synthesizer
lesson). It is the natural open-source-hygiene sibling of ``secret_file``
(credential hygiene) and ``ci_config`` (automation hygiene), and closes the last
un-perceived axis of basic repo hygiene.

The collector reports only the actionable GAP (``kind="license"``,
``summary="no license file"``) and makes no judgement; the synthesizer LLM
decides whether an "add a LICENSE" goal is warranted, exactly like its siblings.
A present license is NOT emitted as a positive fact -- a satisfied invariant is
not actionable, so surfacing it would only lower signal-to-noise.

Detection mirrors ``ci_config`` exactly:

* **root-anchored** -- a license is a repo-root concept, so at most ONE signal is
  emitted and the check for a license file looks only at ``root`` itself, never a
  subdirectory (per-project license granularity is Out of Scope).
* **presence-only / basename-only** -- a license is recognized purely by its
  (case-folded) file basename via pathlib; the collector NEVER opens file
  content, so it cannot be broken by binary/non-UTF-8 bytes and no license text
  can ever leak into a signal (no SPDX/header parsing -- Out of Scope).
* **source-gated** -- the gap is only reported when there is actually code to
  license; an empty or docs-only directory is never flagged (exactly like
  ``ci_config``'s source gate).

Pure stdlib (os/pathlib) only, keeping the runtime pydantic-v2-only and fully
offline. A new ``kind="license"`` flows into the synthesis prompt automatically
because ``synthesizer._build_prompt`` iterates ``snapshot.by_kind()``, so this
file plus the registry/catalog wiring is the whole cost (additive, no version
bump).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from proactive_loop.collectors.base import BaseCollector
# Reuse the EXACT skip rules the sibling filesystem collectors use (the
# SPEC-sanctioned shared seam) so a source file buried in node_modules/.venv/a
# hidden dir is invisible to the "has source" check here too -- identical to
# ci_config._has_source.
from proactive_loop.collectors.filesystem import _SKIP_DIRS, _is_hidden
from proactive_loop.models import ContextSignal

# Extensions we treat as "code" when deciding whether an un-licensed repo has
# anything to license. Deliberately narrow and language-agnostic, matching the
# sibling ``ci_config._SOURCE_EXTS`` / ``test_posture`` set exactly; anything
# else (docs, config, data) is ignored so a docs-only dir is never flagged.
_SOURCE_EXTS: frozenset[str] = frozenset({".py", ".ts", ".js", ".go", ".rs"})

# Case-folded basenames recognized as an open-source LICENSE file at the repo
# root. Curated + presence-only (we match the NAME, never parse content): the
# GitHub-recognized spellings plus GNU ``COPYING`` and the public-domain
# ``UNLICENSE``, each with the common ``.txt``/``.md`` suffixes. The set may grow
# but the SPEC-mandated members (license, license.txt, license.md, licence,
# copying, unlicense) must remain.
_LICENSE_BASENAMES: frozenset[str] = frozenset(
    {
        "license",
        "license.txt",
        "license.md",
        "license.rst",
        "licence",
        "licence.txt",
        "licence.md",
        "copying",
        "copying.txt",
        "copying.md",
        "unlicense",
        "unlicense.txt",
        "unlicense.md",
    }
)


def _has_license_file(root: Path) -> bool:
    """True iff a FILE directly in *root* has a recognized license basename.

    Root-anchored (never recurses) and matched on the case-folded basename ONLY,
    so a nested ``sub/LICENSE`` does not count and a DIRECTORY named ``LICENSE``
    is ignored. File content is never opened, so a binary/non-UTF-8 file named
    ``LICENSE`` cannot raise here.
    """
    for entry in root.iterdir():
        if entry.is_file() and entry.name.casefold() in _LICENSE_BASENAMES:
            return True
    return False


def _has_source(root: Path) -> bool:
    """True iff any non-pruned file under *root* has a source extension.

    Walks the tree once, pruning noise + hidden dirs in place exactly like the
    sibling collectors, so a source file living ONLY inside ``node_modules``/
    ``.venv``/a hidden dir does not count. Reads only filenames -- never file
    content -- so it cannot raise on undecodable bytes.
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
class LicenseCollector(BaseCollector):
    """Emit at most ONE ContextSignal for the actionable "code but no LICENSE" gap.

    WHY a dataclass with defaults: mirrors the sibling collectors so
    ``all_collectors()`` can construct it with no arguments. ``max_items`` is
    retained for family consistency only -- this collector emits at most one
    root-anchored signal, so it never actually truncates.
    """

    name: str = "license"
    max_items: int = 30

    def _collect(self, root: Path) -> list[ContextSignal]:
        """Return the one missing-license gap signal for *root*, or [] otherwise."""
        if not root.is_dir():
            return []

        # A present license is a satisfied invariant, not an actionable gap, so it
        # short-circuits FIRST: if a license exists we emit nothing (and never walk
        # for source).
        if _has_license_file(root):
            return []

        # No license: the actionable gap only matters if there is code to license.
        # A docs-only or empty dir (no source) is never flagged, mirroring
        # ci_config's source gate.
        if _has_source(root):
            return [self._signal_for(root)]

        return []

    def _signal_for(self, root: Path) -> ContextSignal:
        """Build the single root-anchored missing-license signal.

        The path is the workspace root itself (a license is a repo-root concept,
        not tied to any one file), mirroring the root-anchored idiom of
        ``ci_config``. The weight (0.7) sits below the credential-hygiene
        ``secret_file`` (0.85) and the missing-CI gap (0.8): a missing license is
        important open-source hygiene but lower-stakes than a committable secret
        or an unbuilt repo.
        """
        return ContextSignal(
            source=self.name,
            kind="license",
            summary="no license file",
            detail="",
            path=str(root),
            weight=0.7,
            timestamp=None,
        )
