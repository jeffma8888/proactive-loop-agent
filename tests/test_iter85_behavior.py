"""Black-box behavior tests for iteration 75 (ships as commit-seq **factory iter
85**) --- ``WorkingTreeCollector`` now scans direct child git repos in
deterministic ASCENDING NAME order (``sorted(root.iterdir())``), so a multi-repo
workspace's cross-repo **unpushed-commit summary** signals no longer vary by
filesystem/OS enumeration order (ROADMAP row #85). This mirrors the fix the
sibling ``GitActivityCollector`` received in iter-84.

ISOLATION CONTRACT (honored): these tests were written strictly from this
iteration's public contract --- the spec's "Expected Behaviors" (``pm.md``),
``README.md``, ``ROADMAP.md`` --- and the collector's existing PUBLIC
conventions in ``tests/test_iter11_behavior.py`` / ``tests/test_iter11_helpers.py``.
They drive ONLY the public surface
``WorkingTreeCollector().collect(path) -> list[ContextSignal]``. The two
module-level seams that are monkeypatched (``subprocess.run`` and ``Path.iterdir``
on ``proactive_loop.collectors.working_tree``) are the seams the spec names
explicitly; ``monkeypatch`` auto-restores both. **No file under ``src/`` was
read, no engineer/reviewer note was read, and no ``git diff`` was consulted.**
Every test is fully offline/deterministic: NO ``git`` binary, network, or real
repo is required --- ``subprocess.run`` is always stubbed, so each "repo" is
merely a directory holding an empty ``.git`` marker. The observable signal shape
(unpushed-summary text ``"<N> unpushed commit(s) in <name> ahead of upstream"``;
per-path ``kind``/``source``/``weight``) was confirmed by running the public
collector under the stubbed seams, never from the implementation.
"""

from __future__ import annotations

import argparse
import re
import types
from pathlib import Path

import proactive_loop.collectors.working_tree as working_tree
from proactive_loop import __version__
from proactive_loop.collectors import WorkingTreeCollector, all_collectors
from proactive_loop.models import ContextSignal

# The one-per-repo unpushed-summary signal; the embedded <name> is the child
# directory's own name (NOT anything read from git stdout).
_UNPUSHED_RE = re.compile(
    r"^\d+ unpushed commit\(s\) in (?P<name>.+) ahead of upstream$"
)


# ---------------------------------------------------------------------------
# Helpers --- offline seams + tiny fake repos. monkeypatch auto-restores.
# ---------------------------------------------------------------------------


def _make_run(porcelain_by_dir: dict[str, str], ahead_by_dir: dict[str, int]):
    """Build a fake ``subprocess.run`` that behaves like ``git -C <dir> ...``.

    The collector runs exactly ONE git command per scanned directory:
      * ``git -C <dir> status --porcelain --branch`` -> working-tree state, plus
        the branch's ahead-of-upstream count in the leading ``## `` header line

    ``porcelain_by_dir`` maps ``str(dir)`` -> porcelain stdout (default ""
    == clean tree, so no per-path signals). ``ahead_by_dir`` maps ``str(dir)``
    -> unpushed count; a dir NOT in the map behaves like "no upstream
    configured", so it emits no unpushed-summary signal. Both are answered by the
    SINGLE status stdout, which this double synthesizes exactly as git does:
    ``## <branch>...<upstream> [ahead N]`` when the dir has a count, and a bare
    ``## <branch>`` (no ``...upstream``, hence nothing to be ahead of) when it
    does not. NO real subprocess (hence no ``git`` binary) is ever spawned --- the
    collector reads only ``.returncode`` and ``.stdout``.

    Any OTHER git command fails closed (returncode 1). That is deliberate: if the
    collector ever regressed to asking a second command for the unpushed count,
    that query would answer "no upstream" and every ahead_by_dir expectation
    below would go red rather than silently still passing.
    """

    def _header_for(target: str | None) -> str:
        """The ``--branch`` header line git would print for *target*."""
        if target in ahead_by_dir:
            return f"## main...origin/main [ahead {ahead_by_dir[target]}]\n"
        return "## main\n"

    def _fake_run(cmd, *args, **kwargs):
        parts = [str(x) for x in cmd]
        target = parts[parts.index("-C") + 1] if "-C" in parts else None
        joined = " ".join(parts)
        if "status" in joined:
            return types.SimpleNamespace(
                returncode=0,
                stdout=_header_for(target) + porcelain_by_dir.get(target, ""),
            )
        return types.SimpleNamespace(returncode=1, stdout="")

    return _fake_run


def _stub_git(
    monkeypatch,
    porcelain_by_dir: dict[str, str] | None = None,
    ahead_by_dir: dict[str, int] | None = None,
) -> None:
    monkeypatch.setattr(
        working_tree.subprocess,
        "run",
        _make_run(porcelain_by_dir or {}, ahead_by_dir or {}),
    )


def _force_iterdir(monkeypatch, root: Path, forced: list[Path]) -> None:
    """Force ``root.iterdir()`` to yield *forced* (in that exact order); all
    other paths delegate to the real ``iterdir``. The real FS won't reliably
    return a non-sorted order, so forcing it is the only way to PROVE the
    ascending-sort fix (and to write a discriminating test)."""
    orig_iterdir = working_tree.Path.iterdir

    def _fake_iterdir(self):
        if self == root:
            return iter(forced)
        return orig_iterdir(self)

    monkeypatch.setattr(working_tree.Path, "iterdir", _fake_iterdir)


def _mkrepo(parent: Path, name: str) -> Path:
    """Create ``parent/name`` with an empty ``.git`` directory marker."""
    d = parent / name
    (d / ".git").mkdir(parents=True)
    return d


def _collect(root: Path) -> list[ContextSignal]:
    signals = WorkingTreeCollector().collect(root)
    assert isinstance(signals, list), f"collect() must return a list; got {type(signals)!r}"
    for s in signals:
        assert isinstance(s, ContextSignal)
    return signals


def _unpushed_names(signals: list[ContextSignal]) -> list[str]:
    """Ordered child-dir names extracted from the unpushed-summary signals only."""
    out: list[str] = []
    for s in signals:
        m = _UNPUSHED_RE.match(s.summary or "")
        if m is not None:
            out.append(m.group("name"))
    return out


def _summaries(signals: list[ContextSignal]) -> list[str]:
    return [s.summary for s in signals]


# ===========================================================================
# Behavior 1 --- Deterministic cross-repo unpushed-summary order (the core fix).
# ===========================================================================


def test_eb1_cross_repo_unpushed_order_sorted_real_fs(monkeypatch, tmp_path) -> None:
    """Multiple direct-child git repos (each clean but >=1 unpushed commit)
    created in a non-alphabetical order surface with their names in ASCENDING
    order under real filesystem enumeration."""
    root = tmp_path
    children = [_mkrepo(root, n) for n in ["zebra", "mango", "apple", "banana"]]
    _stub_git(monkeypatch, ahead_by_dir={str(c): 2 for c in children})

    names = _unpushed_names(_collect(root))
    assert names == ["apple", "banana", "mango", "zebra"], names


def test_eb1_cross_repo_unpushed_order_sorted_even_when_enumeration_reversed(
    monkeypatch, tmp_path
) -> None:
    """DISCRIMINATING: even when ``iterdir`` yields the children in a deliberately
    reverse-alphabetical order, ``collect()`` emits their unpushed-summary
    signals in ascending name order. Without the ``sorted(root.iterdir())`` fix
    the children come out in the raw (reversed) enumeration order and this
    assertion fails."""
    root = tmp_path
    children = [_mkrepo(root, n) for n in ["zebra", "mango", "apple", "banana"]]
    _stub_git(monkeypatch, ahead_by_dir={str(c): 2 for c in children})

    # Force enumeration to reverse-alphabetical order.
    forced = [root / "zebra", root / "mango", root / "banana", root / "apple"]
    _force_iterdir(monkeypatch, root, forced)

    names = _unpushed_names(_collect(root))
    assert names == ["apple", "banana", "mango", "zebra"], (
        "children must be scanned in ascending name order regardless of "
        f"filesystem enumeration order; got {names}"
    )


# ===========================================================================
# Behavior 2 --- Deterministic across repeated calls.
# ===========================================================================


def test_eb2_repeated_calls_identical_order(monkeypatch, tmp_path) -> None:
    """Two successive collect() calls on the same unchanged multi-repo tree
    return the full ordered list of summary strings identically."""
    root = tmp_path
    children = [_mkrepo(root, n) for n in ["delta", "charlie", "echo", "bravo"]]
    _stub_git(monkeypatch, ahead_by_dir={str(c): 3 for c in children})

    first = _summaries(_collect(root))
    second = _summaries(_collect(root))
    assert first == second, (first, second)
    assert _unpushed_names(_collect(root)) == ["bravo", "charlie", "delta", "echo"]


# ===========================================================================
# Behavior 3 --- Root is still scanned first regardless of its own name.
# ===========================================================================


def test_eb3_root_scanned_first_then_children_ascending(monkeypatch, tmp_path) -> None:
    """Root is itself a repo with an unpushed commit AND has child repos; root's
    OWN unpushed-summary appears BEFORE any child's even though root's directory
    name ("zzz_root") sorts AFTER the children alphabetically."""
    root = tmp_path / "zzz_root"
    (root / ".git").mkdir(parents=True)
    child_aaa = _mkrepo(root, "aaa")
    child_mmm = _mkrepo(root, "mmm")
    _stub_git(
        monkeypatch,
        ahead_by_dir={str(root): 5, str(child_aaa): 2, str(child_mmm): 3},
    )
    # Force children reverse-alphabetical to prove the sort orders them anyway.
    _force_iterdir(monkeypatch, root, [root / "mmm", root / "aaa"])

    names = _unpushed_names(_collect(root))
    assert names == ["zzz_root", "aaa", "mmm"], names


# ===========================================================================
# Behavior 4 --- Membership preserved --- order-only change, nothing added/dropped.
# ===========================================================================


def test_eb4_membership_identical_regardless_of_enumeration_order(
    monkeypatch, tmp_path
) -> None:
    """The SET of emitted summary strings is identical whether ``iterdir``
    returns the children sorted or reverse-sorted; sorting can only reorder,
    never add or drop, a signal."""
    root = tmp_path
    names = ["kilo", "alpha", "tango", "foxtrot"]
    children = [_mkrepo(root, n) for n in names]
    _stub_git(monkeypatch, ahead_by_dir={str(c): 2 for c in children})

    ascending = [root / n for n in sorted(names)]
    reversed_ = list(reversed(ascending))

    _force_iterdir(monkeypatch, root, reversed_)
    rev_summaries = _summaries(_collect(root))

    _force_iterdir(monkeypatch, root, ascending)
    asc_summaries = _summaries(_collect(root))

    assert set(rev_summaries) == set(asc_summaries)
    assert len(rev_summaries) == len(asc_summaries) == 4
    # And the emitted order is ascending in BOTH cases (superset-order change).
    assert _unpushed_names(_collect(root)) == ["alpha", "foxtrot", "kilo", "tango"]


# ===========================================================================
# Behavior 5 --- Per-changed-path signals unchanged (weight-then-summary order).
# ===========================================================================


def test_eb5_per_path_signals_unchanged_and_weight_ordered(monkeypatch, tmp_path) -> None:
    """For one repo with a tracked (modified) change AND an untracked file, the
    tracked-change signal (weight 0.9) precedes the untracked-file signal
    (weight 0.5): output stays ordered by descending weight. The fix does not
    touch the per-path sort."""
    root = tmp_path
    (root / ".git").mkdir()
    # git status --porcelain: " M <path>" == tracked/modified, "?? <path>" == untracked.
    _stub_git(
        monkeypatch,
        porcelain_by_dir={str(root): " M app.py\n?? new.py\n"},
    )

    signals = _collect(root)
    assert len(signals) == 2, [s.summary for s in signals]

    tracked_idx = next(i for i, s in enumerate(signals) if "app.py" in (s.summary or ""))
    untracked_idx = next(i for i, s in enumerate(signals) if "new.py" in (s.summary or ""))
    assert tracked_idx < untracked_idx, [s.summary for s in signals]

    tracked = signals[tracked_idx]
    untracked = signals[untracked_idx]
    assert tracked.weight == 0.9, tracked.weight
    assert untracked.weight == 0.5, untracked.weight
    assert tracked.weight > untracked.weight
    for s in signals:
        assert s.kind == "working_tree", s.kind
        assert s.source == "working_tree", s.source


# ===========================================================================
# Behavior 6 --- OSError during child enumeration still degrades to root-only.
# ===========================================================================


def test_eb6_oserror_during_enumeration_preserves_root_signal(monkeypatch, tmp_path) -> None:
    """If ``root.iterdir()`` raises OSError, collect() still returns root's OWN
    unpushed-summary and raises no exception (the sorted(...) stays inside the
    pre-existing try/except OSError; sorted() eagerly materializes the iterator,
    so an OSError raised during consumption is caught exactly as before)."""
    root = tmp_path
    (root / ".git").mkdir()
    _stub_git(monkeypatch, ahead_by_dir={str(root): 4})

    def _raising_iterdir(self, *args, **kwargs):
        raise OSError("cannot enumerate children")

    monkeypatch.setattr(working_tree.Path, "iterdir", _raising_iterdir)

    signals = _collect(root)  # must not raise
    names = _unpushed_names(signals)
    assert names == [root.name], names


# ===========================================================================
# Behavior 7 --- Registry / count / version invariants unchanged (zero-drift).
# ===========================================================================


def test_eb7_registry_counts_and_version_frozen() -> None:
    """Behavior-only, order-only change -> the live registry and version are
    unchanged: 15 collectors, 14 tools, 7 providers, 15 CLI subcommands,
    __version__ 0.1.1. A future collector/tool/verb/provider add self-flags here."""
    from proactive_loop.cli import build_parser
    from proactive_loop.llm.providers import VALID_PROVIDERS
    from proactive_loop.loop.tools import ToolRegistry

    assert len(all_collectors()) == 16
    assert len(ToolRegistry.tool_names()) == 14
    assert len(VALID_PROVIDERS) == 7

    parser = build_parser()
    sub_actions = [
        a
        for a in parser._subparsers._group_actions
        if isinstance(a, argparse._SubParsersAction)
    ]
    assert len(sub_actions) == 1
    assert len(sub_actions[0].choices) == 15
    assert __version__ == "0.1.1"
