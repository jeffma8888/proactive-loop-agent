"""Black-box behavior tests for iteration 74 (ships as commit-seq **factory iter
84**) --- ``GitActivityCollector`` now scans direct child git repos in
deterministic ASCENDING NAME order, so a multi-repo workspace's cross-repo
commit-signal order no longer varies by filesystem/OS (ROADMAP row #84).

ISOLATION CONTRACT (honored): these tests were written strictly from this
iteration's public contract --- the spec's "Expected Behaviors" (``pm.md``),
``README.md``, ``ROADMAP.md`` --- and the collector's existing PUBLIC
conventions in ``tests/test_collectors.py`` / ``tests/test_iter74_behavior.py``.
They drive ONLY the public surface
``GitActivityCollector().collect(path) -> list[ContextSignal]``. The two
module-level seams that are monkeypatched (``subprocess.run`` and
``Path.iterdir`` on ``proactive_loop.collectors.git_activity``) are the seams
the spec names explicitly; ``monkeypatch`` auto-restores both. **No file under
``src/`` was read, no engineer/reviewer note was read, and no ``git diff`` was
consulted.** Every test is fully offline/deterministic: NO ``git`` binary,
network, or real repo is required --- ``subprocess.run`` is always stubbed, so
each "repo" is merely a directory holding an empty ``.git`` marker.
"""

from __future__ import annotations

import argparse
import re
import types
from pathlib import Path

import pytest

import proactive_loop.collectors.git_activity as git_activity
from proactive_loop import __version__
from proactive_loop.collectors import GitActivityCollector, all_collectors
from proactive_loop.models import ContextSignal

# ``git log --pretty=format:%H\x1f%ai\x1f%s\x1f%an`` -> hash, author-date,
# subject, author, separated by the ASCII unit separator.
SEP = "\x1f"


# ---------------------------------------------------------------------------
# Helpers --- offline seams + tiny fake repos. monkeypatch auto-restores.
# ---------------------------------------------------------------------------


def _line(commit_hash: str, date: str, subject: str, author: str) -> str:
    """One well-formed ``git log`` output line (4 \\x1f-separated fields)."""
    return SEP.join([commit_hash, date, subject, author])


def _stub_by_dir(
    monkeypatch,
    commits_by_path: dict[str, list[tuple[str, str, str, str]]],
) -> None:
    """Stub the module-level ``subprocess.run`` to behave like ``git -C <dir> log``.

    ``commits_by_path`` maps ``str(dir)`` -> a list of ``(hash, date, subject,
    author)`` commit tuples in the order ``git log`` emits them (newest-first).
    A directory NOT in the map behaves like a non-repo: return code 1 + empty
    stdout, so the collector emits nothing for it. This lets each fake repo have
    its own distinct commits. NO real subprocess (hence no ``git`` binary) is
    ever spawned --- the collector reads only ``.returncode`` and ``.stdout``.
    """

    def _fake_run(*args, **kwargs):
        cmd = args[0]
        target = cmd[cmd.index("-C") + 1]  # the ``-C <dir>`` argument value
        commits = commits_by_path.get(str(target))
        if commits is None:
            return types.SimpleNamespace(returncode=1, stdout="")
        stdout = "".join(_line(*c) + "\n" for c in commits)
        return types.SimpleNamespace(returncode=0, stdout=stdout)

    monkeypatch.setattr(git_activity.subprocess, "run", _fake_run)


def _mkrepo(parent: Path, name: str) -> Path:
    """Create ``parent/name`` with an empty ``.git`` directory marker."""
    d = parent / name
    (d / ".git").mkdir(parents=True)
    return d


def _collect(root: Path) -> list[ContextSignal]:
    signals = GitActivityCollector().collect(root)
    assert isinstance(signals, list), f"collect() must return a list; got {type(signals)!r}"
    return signals


_NAME_RE = re.compile(r"^Commit in (?P<name>[^:]+): ")


def _names(signals: list[ContextSignal]) -> list[str]:
    """Ordered list of the directory names embedded in each signal's summary
    (summary shape: ``"Commit in <dir-name>: <subject>"``)."""
    out: list[str] = []
    for s in signals:
        m = _NAME_RE.match(s.summary)
        assert m is not None, f"unexpected summary shape: {s.summary!r}"
        out.append(m.group("name"))
    return out


# ===========================================================================
# Behavior 1 --- Cross-repo order is sorted by child directory name.
# ===========================================================================


def test_eb1_cross_repo_order_sorted_by_child_name_real_fs(monkeypatch, tmp_path) -> None:
    """Multiple direct-child git repos created in a non-alphabetical order surface
    with their names in ASCENDING order (real filesystem enumeration)."""
    created = ["zebra", "mango", "apple", "banana"]
    children = [_mkrepo(tmp_path, n) for n in created]
    commits = {
        str(c): [("h" + c.name, "2024-01-01 00:00:00 +0000", "Work in " + c.name, "A")]
        for c in children
    }
    # root (tmp_path) NOT in the map -> no root signals; only children.
    _stub_by_dir(monkeypatch, commits)

    names = _names(_collect(tmp_path))
    assert names == ["apple", "banana", "mango", "zebra"], names


def test_eb1_cross_repo_order_sorted_even_when_enumeration_reversed(
    monkeypatch, tmp_path
) -> None:
    """DISCRIMINATING: even when ``iterdir`` yields children in a deliberately
    reverse-alphabetical order, ``collect()`` emits them in ascending name
    order. Without the ``sorted(root.iterdir())`` fix the children come out in
    raw enumeration order and this test fails."""
    created = ["zebra", "mango", "apple", "banana"]
    children = [_mkrepo(tmp_path, n) for n in created]
    commits = {
        str(c): [("h" + c.name, "2024-01-01 00:00:00 +0000", "Work in " + c.name, "A")]
        for c in children
    }
    _stub_by_dir(monkeypatch, commits)

    # Force the enumeration to a NON-sorted (reverse-alphabetical) order.
    forced = [tmp_path / "zebra", tmp_path / "mango", tmp_path / "banana", tmp_path / "apple"]
    orig_iterdir = git_activity.Path.iterdir

    def _fake_iterdir(self):
        if self == tmp_path:
            return iter(forced)
        return orig_iterdir(self)

    monkeypatch.setattr(git_activity.Path, "iterdir", _fake_iterdir)

    names = _names(_collect(tmp_path))
    assert names == ["apple", "banana", "mango", "zebra"], (
        "children must be scanned in ascending name order regardless of "
        f"filesystem enumeration order; got {names}"
    )


# ===========================================================================
# Behavior 2 --- Determinism / repeatability.
# ===========================================================================


def test_eb2_collect_is_repeatable(monkeypatch, tmp_path) -> None:
    """Two calls on the same unchanged workspace return the identical ordered
    list of summaries."""
    children = [_mkrepo(tmp_path, n) for n in ["delta", "charlie", "echo", "bravo"]]
    commits = {
        str(c): [("h" + c.name, "2024-02-02 12:00:00 +0000", "Edit " + c.name, "A")]
        for c in children
    }
    _stub_by_dir(monkeypatch, commits)

    first = [s.summary for s in _collect(tmp_path)]
    second = [s.summary for s in _collect(tmp_path)]
    assert first == second, (first, second)
    assert _names(_collect(tmp_path)) == ["bravo", "charlie", "delta", "echo"]


# ===========================================================================
# Behavior 3 --- Within-repo commit order unchanged (newest-first).
# ===========================================================================


def test_eb3_within_repo_order_is_newest_first_not_alphabetical(
    monkeypatch, tmp_path
) -> None:
    """Within ONE repo, commits stay in git-log (newest-first) order; the
    directory-level sort must NOT reorder commits within a repo. Subjects are
    chosen so newest-first != alphabetical, so a wrong 'sort ALL signals by
    summary' implementation would fail this."""
    # git log emits newest-first: Zulu (newest) -> Mike -> Alpha (oldest).
    commits = [
        ("hZ", "2024-03-03 03:00:00 +0000", "Zulu newest", "A"),
        ("hM", "2024-02-02 02:00:00 +0000", "Mike middle", "A"),
        ("hA", "2024-01-01 01:00:00 +0000", "Alpha oldest", "A"),
    ]
    # root (tmp_path) is itself the single repo.
    _stub_by_dir(monkeypatch, {str(tmp_path): commits})

    subjects = [s.summary.split(": ", 1)[1] for s in _collect(tmp_path)]
    assert subjects == ["Zulu newest", "Mike middle", "Alpha oldest"], subjects
    assert subjects != sorted(subjects), "within-repo order must NOT be alphabetical"


# ===========================================================================
# Behavior 4 --- Root is scanned first, then children ascending.
# ===========================================================================


def test_eb4_root_scanned_first_then_children_ascending(monkeypatch, tmp_path) -> None:
    """When root is itself a repo AND has child repos, ALL of root's own commit
    signals appear BEFORE any child's; children then follow ascending."""
    child_bbb = _mkrepo(tmp_path, "bbb")
    child_aaa = _mkrepo(tmp_path, "aaa")
    commits = {
        str(tmp_path): [
            ("hr1", "2024-05-05 05:00:00 +0000", "Root newest", "A"),
            ("hr2", "2024-04-04 04:00:00 +0000", "Root older", "A"),
        ],
        str(child_aaa): [("ha", "2024-01-01 00:00:00 +0000", "In aaa", "A")],
        str(child_bbb): [("hb", "2024-01-01 00:00:00 +0000", "In bbb", "A")],
    }
    _stub_by_dir(monkeypatch, commits)

    names = _names(_collect(tmp_path))
    root_name = tmp_path.name
    # root's two signals (both carry root_name) first, then aaa, then bbb.
    assert names == [root_name, root_name, "aaa", "bbb"], names


# ===========================================================================
# Behavior 5 --- Degradation and dedup preserved (backward-compatible).
# ===========================================================================


def test_eb5a_child_enumeration_oserror_preserves_root_signals(
    monkeypatch, tmp_path
) -> None:
    """(a) If enumerating children raises OSError, it is swallowed and root's own
    commit signals survive."""
    _stub_by_dir(
        monkeypatch,
        {str(tmp_path): [("hr", "2024-06-06 06:00:00 +0000", "Root commit", "A")]},
    )

    def _raising_iterdir(self, *args, **kwargs):
        raise OSError("cannot enumerate children")

    monkeypatch.setattr(git_activity.Path, "iterdir", _raising_iterdir)

    signals = _collect(tmp_path)
    assert len(signals) == 1
    assert signals[0].summary.endswith("Root commit")
    assert signals[0].path == str(tmp_path)


def test_eb5b_single_child_repo_surfaces_its_commits(monkeypatch, tmp_path) -> None:
    """(b) A single-child-repo workspace still surfaces that child's commits."""
    child = _mkrepo(tmp_path, "solo")
    # root not a repo -> only the child's commit surfaces.
    _stub_by_dir(monkeypatch, {str(child): [("hs", "2024-07-07 07:00:00 +0000", "Solo work", "A")]})

    signals = _collect(tmp_path)
    assert len(signals) == 1
    assert signals[0].summary == "Commit in solo: Solo work"
    assert signals[0].source == "git_activity"
    assert signals[0].kind == "git_commit"


def test_eb5c_dedup_by_summary_within_same_dir_unchanged(monkeypatch, tmp_path) -> None:
    """(c) Two commits in the SAME dir sharing an identical subject collapse to a
    single signal (dedup-by-summary unchanged)."""
    subject = "Identical subject"
    commits = [
        ("hone", "2024-01-15 10:30:00 -0700", subject, "Alice"),
        ("htwo", "2024-01-16 11:00:00 -0700", subject, "Bob"),
    ]
    _stub_by_dir(monkeypatch, {str(tmp_path): commits})

    signals = _collect(tmp_path)
    assert len(signals) == 1, "identical summaries must dedup to a single signal"
    assert signals[0].summary == f"Commit in {tmp_path.name}: {subject}"


# ===========================================================================
# Behavior 6 --- Fields, counts, and version frozen (behavior-only).
# ===========================================================================


def test_eb6_signal_fields_source_and_kind(monkeypatch, tmp_path) -> None:
    """Emitted signals keep source='git_activity', kind='git_commit'."""
    child = _mkrepo(tmp_path, "repo1")
    _stub_by_dir(
        monkeypatch,
        {
            str(tmp_path): [("hr", "2024-01-01 00:00:00 +0000", "Root", "A")],
            str(child): [("hc", "2024-01-01 00:00:00 +0000", "Child", "A")],
        },
    )
    signals = _collect(tmp_path)
    assert signals, "expected at least one signal"
    for s in signals:
        assert s.source == "git_activity", s.source
        assert s.kind == "git_commit", s.kind


def test_eb6_registry_counts_and_version_frozen() -> None:
    """Behavior-only change -> the live registry and version are unchanged: 15
    collectors, 14 tools, 7 providers, 14 CLI subcommands, __version__ 0.1.1.
    A future collector/tool/verb/provider/env-var add self-flags here."""
    from proactive_loop.cli import build_parser
    from proactive_loop.llm.providers import VALID_PROVIDERS
    from proactive_loop.loop.tools import ToolRegistry

    assert len(all_collectors()) == 15
    assert len(ToolRegistry.tool_names()) == 14
    assert len(VALID_PROVIDERS) == 7

    parser = build_parser()
    sub_actions = [
        a
        for a in parser._subparsers._group_actions
        if isinstance(a, argparse._SubParsersAction)
    ]
    assert len(sub_actions) == 1
    assert len(sub_actions[0].choices) == 14
    assert __version__ == "0.1.1"
