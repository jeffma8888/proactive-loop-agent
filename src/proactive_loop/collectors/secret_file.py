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
that sank the iter-31 content-scanning attempt. Pure stdlib (``pathlib``) only,
so the runtime stays pydantic-v2-only and offline.

The ONE deliberate departure from the ``large_file`` template: hidden FILES are
scanned (``large_file`` skips a hidden basename explicitly). The flagship
targets -- ``.env``, ``.envrc``, ``.netrc``, ``.npmrc``, ``.pypirc``,
``.git-credentials``, and every ``.env.*`` variant -- are all hidden, so skipping
hidden files would silently drop exactly what this collector exists to catch. The
**directory** prune (noise dirs + hidden dirs, consistent with every sibling
collector) is not implemented here at all: it is INHERITED from
``collectors.dir_source``, which owns the single dir-prune policy for the package
and serves this collector an already-pruned listing.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# The shared per-scan traversal provider. It applies the package dir-prune policy
# (noise dirs + hidden dirs) DURING the walk, so a secret-shaped file buried in
# node_modules/.venv/.git or under any hidden dir is invisible here too (spec
# Behavior 10) with no prune rule left in this module. It prunes DIRECTORIES only,
# which is exactly what this collector needs: hidden FILES stay visible (spec
# Behavior 9), the single place the large_file template must NOT be copied.
from proactive_loop.collectors import dir_source
from proactive_loop.collectors.base import BaseCollector
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
class SecretFileCollector(BaseCollector):
    """Emit one ContextSignal per secret-shaped file (by basename) under *root*.

    WHY a dataclass with defaults: mirrors the sibling collectors so
    all_collectors() can construct it with no arguments, while a caller can cap
    ``max_items`` on a very large tree. The match/exclusion sets are fixed module
    constants (no CLI flag, no per-instance knob) -- only ``max_items`` is
    ctor-overridable, keeping the conservative curated set immutable.
    """

    name: str = "secret_file"
    max_items: int = 20

    def _collect(self, root: Path) -> list[ContextSignal]:
        """Walk *root* and return one signal per secret-shaped file."""
        if not root.is_dir():
            return []

        # (relpath, absolute-path) pairs, so we can order deterministically by
        # ascending forward-slashed relpath regardless of the traversal order the
        # provider happens to serve.
        candidates: list[tuple[str, Path]] = []
        # The listing arrives ALREADY pruned of noise + hidden DIRS (spec Behavior
        # 10): dir_source applies the package dir-prune policy during the traversal,
        # so this collector no longer carries the rule -- and inside the scan scope
        # opened by cli._collect the traversal itself is shared with every sibling
        # walking the same root instead of being re-paid once per collector.
        for dirpath, _dirnames, filenames in dir_source.walk(root):
            # Consider ALL files -- hidden included (spec Behavior 9). This is the
            # one place where the large_file template (skip a hidden basename) must
            # NOT be copied: .env / .netrc / .env.* are hidden yet are the flagship
            # targets. We iterate `filenames` only, never the directory names, so a
            # dir literally named `credentials`/`secrets.pem` is never flagged (spec
            # Behavior 11).
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
