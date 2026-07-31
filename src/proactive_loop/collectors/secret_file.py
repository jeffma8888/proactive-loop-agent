"""SecretFileCollector: flag secret-shaped files by basename as an L2 security-hygiene signal.

WHY this collector exists: the scout's proactivity ceiling is set entirely by
*what its collectors can perceive* (SPEC sections 1, 4.1). The existing collectors
see file recency, git activity/state, uncommitted/unpushed work, TODO/FIXME
comments, notes, dependency manifests, test posture, committed merge-conflict
markers, and oversized blobs -- but none of them says "there is a secret-shaped
file here (a ``.env``, an SSH private key, a cert/key) that must be gitignored /
moved / removed before it leaks." For a proactivity agent scanning a workspace
that may become a *public* repo (literally this product's own situation), a
committable credentials file is the single highest-stakes hazard. A new
``kind="secret_file"`` signal flows into synthesis via ``WorkspaceSnapshot.by_kind()``
with ZERO synthesizer change, so the scout can rank + gate a concrete
"gitignore/remove the secret-shaped file X" goal -- a genuinely new class of
proactive goal. This is the security companion to ``large_file`` (blob hygiene)
and ``merge_conflict`` (VCS hygiene).

The decision is **basename-only** and NEVER reads file content: no opening/decoding
bytes, no entropy heuristic, no regex secret-value detection, no MIME sniffing
(SPEC Out of Scope). Because it never opens content, it structurally cannot raise
on binary/undecodable bytes, and a secret VALUE can never leak into a signal --
only the filename can. This is also the hard line that dissolves the objections
that sank the iter-31 content-scanning attempt. Pure stdlib (``os``/``pathlib``)
only, so the runtime stays pydantic-v2-only and offline.

The ONE deliberate departure from the ``large_file`` template: hidden FILES are
scanned (``large_file`` does ``if _is_hidden(fname): continue``). The flagship
targets -- ``.env``, ``.envrc``, ``.netrc``, ``.npmrc``, ``.pypirc``,
``.git-credentials``, and every ``.env.*`` variant -- are all hidden, so skipping
hidden files would silently drop exactly what this collector exists to catch. Only
hidden/skip **directories** are pruned (consistent with every sibling collector).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# Reuse the EXACT dir-prune rules the sibling collectors use (the SPEC-sanctioned
# shared seam) so a secret-shaped file buried in node_modules/.venv/.git or under
# any hidden dir is invisible here too (spec Behavior 10). NOTE: we import
# _is_hidden ONLY for the DIRECTORY prune -- hidden FILES are intentionally kept
# (spec Behavior 9), the single place the large_file template must NOT be copied.
from proactive_loop.collectors.filesystem import _SKIP_DIRS, _is_hidden
from proactive_loop.models import ContextSignal

# --- Match / exclusion sets: the single source of truth (spec Behaviors 2-4) ----
#
# Kept as module-level constants so the intent is legible and the tester can rely
# on them. The set is deliberately conservative (exact names + one dotenv prefix +
# a curated key/cert suffix list) for near-zero false positives; broadening it
# (substring "secret"/"token", suffix ".env", etc.) is a future increment, not this
# one (SPEC Out of Scope). Comparison is always against the case-folded basename.

# EXACT case-folded basenames that are secret-shaped on their own.
_EXACT_NAMES: frozenset[str] = frozenset(
    {
        ".env",
        ".envrc",
        "credentials",
        ".netrc",
        ".npmrc",
        ".pypirc",
        ".git-credentials",
        "id_rsa",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
    }
)

# dotenv variants (e.g. ``.env.local``, ``.env.production``) -- a PREFIX match.
_PREFIX: str = ".env."

# Key/cert file extensions -- a SUFFIX match (str.endswith accepts a tuple).
_MATCH_SUFFIXES: tuple[str, ...] = (".pem", ".key", ".p12", ".pfx", ".keystore", ".jks")

# Suffixes that DEMOTE a matched name to safe: public keys, docs, and the
# example/template families a repo intentionally commits. Checked AFTER a match --
# an excluded name is never flagged even if it matched (spec Behavior 3, e.g.
# ``.env.example`` matches the ``.env.`` prefix but is a template).
_EXCLUDE_SUFFIXES: tuple[str, ...] = (
    ".example",
    ".sample",
    ".template",
    ".dist",
    ".md",
    ".pub",
)


def _is_secret_shaped(name: str) -> bool:
    """Return True iff *name* is a secret-shaped basename (MATCH and not EXCLUDE).

    The whole decision is on the case-folded basename only -- never file content --
    so it is deterministic, offline, and cannot raise on binary bytes. Match FIRST
    (exact / dotenv-prefix / key-cert-suffix), THEN apply the exclusion, so a
    template like ``.env.example`` (which matches the ``.env.`` prefix) is demoted
    to safe (spec Behaviors 2-4).
    """
    folded = name.casefold()
    matched = (
        folded in _EXACT_NAMES
        or folded.startswith(_PREFIX)
        or folded.endswith(_MATCH_SUFFIXES)
    )
    return matched and not folded.endswith(_EXCLUDE_SUFFIXES)


@dataclass
class SecretFileCollector:
    """Emit one ContextSignal per secret-shaped file (by basename) under *root*.

    WHY a dataclass with defaults: mirrors the sibling collectors so
    all_collectors() can construct it with no arguments, while a caller can cap
    ``max_items`` on a very large tree. The match/exclusion sets are fixed module
    constants (no CLI flag, no per-instance knob) -- only ``max_items`` is
    ctor-overridable, keeping the conservative curated set immutable.
    """

    name: str = "secret_file"
    max_items: int = 20

    def collect(self, root: Path) -> list[ContextSignal]:
        """Walk *root* and return one signal per secret-shaped file.

        Never raises: any filesystem error degrades to ``[]``, honouring the
        Collector contract so one unreadable tree can never abort a scan.
        """
        try:
            return self._collect(root)
        except Exception:
            return []

    def _collect(self, root: Path) -> list[ContextSignal]:
        if not root.is_dir():
            return []

        # (relpath, absolute-path) pairs, so we can order deterministically by
        # ascending forward-slashed relpath regardless of os.walk traversal order.
        candidates: list[tuple[str, Path]] = []
        for dirpath, dirnames, filenames in os.walk(root):
            # Prune noise + hidden DIRS in place so os.walk never descends into
            # them (spec Behavior 10), identical to the sibling collectors.
            dirnames[:] = [
                d for d in dirnames if not _is_hidden(d) and d not in _SKIP_DIRS
            ]
            # Consider ALL files -- hidden included (spec Behavior 9). This is the
            # one line where the large_file template ("if _is_hidden(fname):
            # continue") must NOT be copied: .env / .netrc / .env.* are hidden yet
            # are the flagship targets. We iterate `filenames` only, never
            # `dirnames`, so a dir literally named `credentials`/`secrets.pem` is
            # never flagged (spec Behavior 11).
            for fname in filenames:
                if not _is_secret_shaped(fname):
                    continue
                full = Path(dirpath) / fname
                candidates.append((self._relative(root, full), full))

        # Ascending forward-slashed relpath, then truncate to the first max_items
        # (spec Behavior 8).
        candidates.sort(key=lambda pair: pair[0])
        return [
            self._signal_for(rel, full) for rel, full in candidates[: self.max_items]
        ]

    @staticmethod
    def _relative(root: Path, path: Path) -> str:
        """Path of *path* relative to *root*, always forward-slashed (Behavior 6)."""
        try:
            return path.relative_to(root).as_posix()
        except ValueError:
            return path.as_posix()

    def _signal_for(self, rel: str, full: Path) -> ContextSignal:
        """Build one secret-file signal.

        The absolute path lives in `path` (mirrors the sibling collectors); the
        deterministic forward-slashed relative path is carried in `summary`. No
        file size or content is included -- the signal is purely about presence.
        """
        return ContextSignal(
            source=self.name,
            kind="secret_file",
            summary=f"{rel}: secret-shaped file",
            detail="",
            path=str(full),
            # Fixed, high, non-decaying hazard weight -- a committable secret is
            # the highest-stakes hygiene fact, above large_file's 0.6.
            weight=0.85,
            timestamp=None,
        )
