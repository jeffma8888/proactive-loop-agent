"""Black-box behavior tests for iteration 130 (ships as commit-seq **factory iter
137**) --- ``WorkingTreeCollector`` now derives the branch's unpushed-commit
count from the leading ``## `` header line of a SINGLE
``git status --porcelain --branch`` spawn per scanned directory, deleting the
second ``git rev-list --count @{u}..HEAD`` spawn it used to pay for
(ROADMAP row #154).

ISOLATION CONTRACT (honored): written strictly from this iteration's public
contract --- the spec's numbered "Expected Behaviors" in ``pm.md`` --- plus the
collector's existing PUBLIC test conventions under ``tests/``
(``tests/test_iter11_behavior.py``, ``tests/test_iter85_behavior.py``). **No file
under ``src/`` was read, no engineer or reviewer note was read, and no
``git diff`` was consulted.** Every assertion drives only the public surface
``WorkingTreeCollector(...).collect(path) -> list[ContextSignal]`` and observes
either its returned signals or the spied argv of the module's ``subprocess.run``
seam (the seam the spec names; ``monkeypatch`` auto-restores it).

The observable shapes asserted below --- the unpushed-summary text
``"<N> unpushed commit(s) in <dirname> ahead of upstream"``, its ``detail`` /
``weight`` / ``path=None``, and the per-path signal shapes --- were confirmed by
RUNNING the public collector under stubbed stdout, never by reading the
implementation.

Offline/deterministic: the stub-driven tests never spawn a process at all. The
single real-``git`` test (Behavior 12) builds a bare repo and clones it **by
local filesystem path** --- no network --- and is skipped when ``git`` is absent.
"""

from __future__ import annotations

import os
import re
import subprocess
import types
from pathlib import Path

import pytest

import proactive_loop.collectors.working_tree as working_tree
from proactive_loop.collectors import WorkingTreeCollector
from proactive_loop.models import ContextSignal

# The one-per-repo unpushed-summary signal. <name> is the scanned directory's own
# name, never anything read out of git stdout.
_UNPUSHED_RE = re.compile(
    r"^(?P<n>\d+) unpushed commit\(s\) in (?P<name>.+) ahead of upstream$"
)

_UNPUSHED_DETAIL = "local commits not yet pushed (@{u}..HEAD, local ref only, no network)"
_UNPUSHED_WEIGHT = 0.8

# Header forms observed live in the spec's grammar table that must yield NO
# unpushed-summary signal (Behaviors 4, 5 and 6).
_SILENT_HEADERS = {
    "behind_only": "## main...origin/main [behind 4]\n",
    "in_sync": "## main...origin/main\n",
    "no_upstream": "## main\n",
    "detached": "## HEAD (no branch)\n",
    "unborn": "## No commits yet on main\n",
    "upstream_gone": "## main...origin/main [gone]\n",
    "unborn_gone": "## No commits yet on main...origin/main [gone]\n",
}

# Malformed / exotic first lines that must degrade to silence, never to an error
# (Behavior 9). ``[different]`` is the ``--no-ahead-behind`` form.
_MALFORMED_HEADERS = {
    "empty_stdout": "",
    "bare_marker": "## \n",
    "ahead_not_a_number": "## main...origin/main [ahead notanumber]\n",
    "ahead_blank": "## main...origin/main [ahead ]\n",
    "different": "## main...origin/main [different]\n",
}


# ---------------------------------------------------------------------------
# Helpers -- offline seams + tiny fake repos. monkeypatch auto-restores.
# ---------------------------------------------------------------------------


def _spy_run(monkeypatch, stdout: str, returncode: int = 0) -> list[list[str]]:
    """Replace the module's ``subprocess.run`` seam with a recording spy.

    Returns the list that accumulates each invocation's argv (as ``str``), so a
    test can assert both HOW MANY processes the collector would have started and
    exactly WHICH command each one was.
    """
    calls: list[list[str]] = []

    def _fake_run(cmd, *args, **kwargs):
        calls.append([str(x) for x in cmd])
        return types.SimpleNamespace(returncode=returncode, stdout=stdout)

    monkeypatch.setattr(working_tree.subprocess, "run", _fake_run)
    return calls


def _spy_run_by_dir(monkeypatch, stdout_by_dir: dict[str, str]) -> list[list[str]]:
    """Like :func:`_spy_run` but answers per ``-C <dir>`` target (multi-repo)."""
    calls: list[list[str]] = []

    def _fake_run(cmd, *args, **kwargs):
        parts = [str(x) for x in cmd]
        calls.append(parts)
        target = parts[parts.index("-C") + 1] if "-C" in parts else None
        return types.SimpleNamespace(returncode=0, stdout=stdout_by_dir.get(target, ""))

    monkeypatch.setattr(working_tree.subprocess, "run", _fake_run)
    return calls


def _mkrepo(parent: Path, name: str) -> Path:
    """Create ``parent/name`` holding an empty ``.git`` directory marker."""
    d = parent / name
    (d / ".git").mkdir(parents=True)
    return d


def _collect(root: Path, **kwargs) -> list[ContextSignal]:
    signals = WorkingTreeCollector(**kwargs).collect(root)
    assert isinstance(signals, list), f"collect() must return a list; got {type(signals)!r}"
    for s in signals:
        assert isinstance(s, ContextSignal), f"every element must be a ContextSignal; got {s!r}"
    return signals


def _unpushed(signals: list[ContextSignal]) -> list[ContextSignal]:
    return [s for s in signals if _UNPUSHED_RE.match(s.summary or "")]


def _shape(s: ContextSignal) -> tuple[str, str | None, str | None, float]:
    """The observable identity of a signal: summary, detail, path, weight."""
    return (s.summary, s.detail, s.path, s.weight)


# ---------------------------------------------------------------------------
# Behavior 1 -- ONE spawn per scanned directory; argv carries --branch; the
# rev-list spawn is gone for every input.
# ---------------------------------------------------------------------------


def test_behavior1_single_status_branch_spawn_and_exact_argv(tmp_path, monkeypatch):
    root = _mkrepo(tmp_path, "solo")
    calls = _spy_run(monkeypatch, "## main...origin/main [ahead 3]\n")

    _collect(root)

    assert len(calls) == 1, (
        "the collector must spawn exactly ONE git command per scanned directory; "
        f"got {len(calls)}: {calls!r}"
    )
    assert calls[0] == [
        "git",
        "-C",
        str(root),
        "status",
        "--porcelain",
        "--branch",
    ], f"argv must be `git -C <root> status --porcelain --branch`; got {calls[0]!r}"


@pytest.mark.parametrize(
    "label,stdout",
    sorted(
        {
            "ahead": "## main...origin/main [ahead 3]\n",
            "ahead_behind": "## main...origin/main [ahead 2, behind 7]\n",
            "dirty": "## main...origin/main [ahead 1]\n M app.py\n?? new.py\n",
            **_SILENT_HEADERS,
            **_MALFORMED_HEADERS,
        }.items()
    ),
)
def test_behavior1_no_rev_list_spawn_for_any_input(tmp_path, monkeypatch, label, stdout):
    """No invocation whose argv contains "rev-list" is made for ANY input."""
    root = _mkrepo(tmp_path, "solo")
    calls = _spy_run(monkeypatch, stdout)

    _collect(root)

    assert not any("rev-list" in " ".join(c) for c in calls), (
        f"the second `git rev-list` spawn must be gone (case {label!r}); got {calls!r}"
    )
    assert len(calls) == 1, (
        f"exactly one spawn per directory (case {label!r}); got {len(calls)}: {calls!r}"
    )


# ---------------------------------------------------------------------------
# Behavior 2 -- the ahead count comes from the ## header, and the emitted
# summary/detail/path/weight are byte-identical to today's for that count.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("count", [1, 3, 12, 100])
def test_behavior2_ahead_count_from_header(tmp_path, monkeypatch, count):
    root = _mkrepo(tmp_path, "myrepo")
    _spy_run(monkeypatch, f"## main...origin/main [ahead {count}]\n")

    signals = _collect(root)

    assert len(signals) == 1, (
        f"a clean tree that is ahead by {count} must emit exactly the one "
        f"unpushed summary; got {[s.summary for s in signals]!r}"
    )
    s = signals[0]
    assert s.summary == f"{count} unpushed commit(s) in myrepo ahead of upstream", (
        f"summary text must be unchanged for count {count}; got {s.summary!r}"
    )
    assert s.detail == _UNPUSHED_DETAIL, f"detail must be unchanged; got {s.detail!r}"
    assert s.path is None, f"the unpushed summary is not path-scoped; got {s.path!r}"
    assert s.weight == _UNPUSHED_WEIGHT, (
        f"unpushed weight must stay {_UNPUSHED_WEIGHT}; got {s.weight!r}"
    )


# ---------------------------------------------------------------------------
# Behavior 3 -- "[ahead N, behind M]" reports N; M appears nowhere.
# ---------------------------------------------------------------------------


def test_behavior3_ahead_and_behind_reports_ahead_only(tmp_path, monkeypatch):
    root = _mkrepo(tmp_path, "myrepo")
    _spy_run(monkeypatch, "## main...origin/main [ahead 2, behind 7]\n")

    signals = _collect(root)

    assert [s.summary for s in signals] == [
        "2 unpushed commit(s) in myrepo ahead of upstream"
    ], f"only the AHEAD count (2) may be reported; got {[s.summary for s in signals]!r}"
    for s in signals:
        assert "7" not in (s.summary or ""), f"behind count leaked into summary {s.summary!r}"
        assert "behind" not in (s.summary or ""), f"'behind' leaked into summary {s.summary!r}"
        assert "behind" not in (s.detail or ""), f"'behind' leaked into detail {s.detail!r}"
        assert "7" not in (s.detail or ""), f"behind count leaked into detail {s.detail!r}"


# ---------------------------------------------------------------------------
# Behaviors 4, 5, 6 -- behind-only, in-sync and every no-upstream form are all
# silent. Asserted separately per form via parametrize ids.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("label,stdout", sorted(_SILENT_HEADERS.items()))
def test_behaviors4_5_6_silent_header_forms(tmp_path, monkeypatch, label, stdout):
    root = _mkrepo(tmp_path, "myrepo")
    _spy_run(monkeypatch, stdout)

    signals = _collect(root)

    assert _unpushed(signals) == [], (
        f"header form {label!r} ({stdout.strip()!r}) must emit NO unpushed summary; "
        f"got {[s.summary for s in signals]!r}"
    )
    assert signals == [], (
        f"header form {label!r} on an otherwise clean tree must emit nothing at all; "
        f"got {[s.summary for s in signals]!r}"
    )


# ---------------------------------------------------------------------------
# Behavior 7 -- the header line is NEVER mistaken for a changed path. (Before
# this change the porcelain classifier would have reported a tracked change to a
# path literally named "main...origin/main [ahead 3]".)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "label,stdout",
    sorted(
        {
            "ahead": "## main...origin/main [ahead 3]\n",
            "ahead_behind": "## main...origin/main [ahead 2, behind 7]\n",
            **_SILENT_HEADERS,
        }.items()
    ),
)
def test_behavior7_header_is_never_a_path_signal(tmp_path, monkeypatch, label, stdout):
    root = _mkrepo(tmp_path, "myrepo")
    _spy_run(monkeypatch, stdout)

    signals = _collect(root)

    for s in signals:
        assert "##" not in (s.summary or ""), (
            f"the ## header leaked into a summary (case {label!r}): {s.summary!r}"
        )
        if s.path is None:
            continue
        for token in ("##", "main", "origin", "ahead", "behind", "gone", "..."):
            assert token not in s.path, (
                f"header token {token!r} became a changed PATH (case {label!r}): {s.path!r}"
            )


# ---------------------------------------------------------------------------
# Behavior 8 -- per-path signals are byte-for-byte what they are without a
# header, plus the unpushed summary.
# ---------------------------------------------------------------------------


def test_behavior8_path_signals_unchanged_by_header(tmp_path, monkeypatch):
    paths_only = " M app.py\n?? new.py\n"

    root_bare = _mkrepo(tmp_path, "myrepo")
    _spy_run(monkeypatch, paths_only)
    baseline = [_shape(s) for s in _collect(root_bare)]

    monkeypatch.undo()

    root_hdr = _mkrepo(tmp_path / "second", "myrepo")
    _spy_run(monkeypatch, "## main...origin/main [ahead 1]\n" + paths_only)
    with_header = _collect(root_hdr)

    assert [_shape(s) for s in with_header if s.path is not None] == baseline, (
        "the per-path signals (summary, detail, path, weight and ORDER) must be "
        "exactly those emitted for the same porcelain body with no header; "
        f"baseline={baseline!r} got={[_shape(s) for s in with_header]!r}"
    )
    assert [s.summary for s in with_header] == [
        "Uncommitted change in myrepo: app.py",
        "Untracked file in myrepo: new.py",
        "1 unpushed commit(s) in myrepo ahead of upstream",
    ], f"the unpushed summary is appended after the path signals; got {[s.summary for s in with_header]!r}"


# ---------------------------------------------------------------------------
# Behavior 9 -- malformed / exotic headers degrade to silence, never to an
# exception, and never to a path signal derived from that line.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("label,stdout", sorted(_MALFORMED_HEADERS.items()))
def test_behavior9_malformed_header_degrades_to_silence(tmp_path, monkeypatch, label, stdout):
    root = _mkrepo(tmp_path, "myrepo")
    _spy_run(monkeypatch, stdout)

    signals = _collect(root)  # must not raise

    assert _unpushed(signals) == [], (
        f"malformed header {label!r} must emit NO unpushed summary; "
        f"got {[s.summary for s in signals]!r}"
    )
    assert signals == [], (
        f"malformed header {label!r} must emit no signal at all (no path signal "
        f"derived from the header line); got {[s.summary for s in signals]!r}"
    )


def test_behavior9_malformed_header_still_yields_real_path_signals(tmp_path, monkeypatch):
    """A malformed header must not swallow the porcelain body below it."""
    root = _mkrepo(tmp_path, "myrepo")
    _spy_run(monkeypatch, "## main...origin/main [ahead notanumber]\n M app.py\n")

    signals = _collect(root)

    assert [s.summary for s in signals] == ["Uncommitted change in myrepo: app.py"], (
        "an unparsable ahead token must cost only the unpushed summary, not the "
        f"path signals below it; got {[s.summary for s in signals]!r}"
    )


# ---------------------------------------------------------------------------
# Behavior 10 -- non-zero rc, and a missing git binary, still degrade to [].
# ---------------------------------------------------------------------------


def test_behavior10_non_zero_returncode_yields_empty(tmp_path, monkeypatch):
    root = _mkrepo(tmp_path, "notarepo")
    _spy_run(monkeypatch, "", returncode=1)

    assert _collect(root) == [], "a non-zero git return code must degrade to []"


def test_behavior10_run_returning_none_yields_empty(tmp_path, monkeypatch):
    root = _mkrepo(tmp_path, "notarepo")

    def _none_run(cmd, *args, **kwargs):
        return None

    monkeypatch.setattr(working_tree.subprocess, "run", _none_run)

    assert _collect(root) == [], "a missing git binary (run -> None) must degrade to []"


# ---------------------------------------------------------------------------
# Behavior 11 -- multi-repo parity: one spawn per directory, both --branch.
# ---------------------------------------------------------------------------


def test_behavior11_multi_repo_one_spawn_each(tmp_path, monkeypatch):
    root = _mkrepo(tmp_path, "wsroot")
    child = _mkrepo(root, "childrepo")
    (root / "plaindir").mkdir()  # not a repo -> never scanned

    calls = _spy_run_by_dir(
        monkeypatch,
        {
            str(root): "## main...origin/main [ahead 1]\n",
            str(child): "## main...origin/main [ahead 2]\n",
        },
    )

    signals = _collect(root)

    assert len(calls) == 2, (
        "exactly two git invocations for root + one child repo (one per "
        f"directory); got {len(calls)}: {calls!r}"
    )
    assert [c[-3:] for c in calls] == [
        ["status", "--porcelain", "--branch"],
        ["status", "--porcelain", "--branch"],
    ], f"both invocations must be `status --porcelain --branch`; got {calls!r}"
    assert [c[c.index('-C') + 1] for c in calls] == [str(root), str(child)], (
        f"one invocation per scanned directory, root first; got {calls!r}"
    )
    assert [s.summary for s in signals] == [
        "1 unpushed commit(s) in wsroot ahead of upstream",
        "2 unpushed commit(s) in childrepo ahead of upstream",
    ], f"per-repo unpushed summaries must be unchanged; got {[s.summary for s in signals]!r}"


def test_behavior11_identical_summaries_are_both_emitted(tmp_path, monkeypatch):
    """Two same-named nested repos ahead by the same N: the collector emits BOTH
    identical summaries (any collapsing of duplicates is a downstream concern,
    not this collector's). Pins the observed behavior so the header change
    cannot alter it."""
    root = _mkrepo(tmp_path, "dup")
    child = _mkrepo(root, "dup")

    hdr = "## main...origin/main [ahead 4]\n"
    calls = _spy_run_by_dir(monkeypatch, {str(root): hdr, str(child): hdr})

    signals = _collect(root)

    assert len(calls) == 2, f"one spawn per directory; got {calls!r}"
    assert [s.summary for s in signals] == [
        "4 unpushed commit(s) in dup ahead of upstream",
        "4 unpushed commit(s) in dup ahead of upstream",
    ], f"both identical per-repo summaries are emitted; got {[s.summary for s in signals]!r}"


# ---------------------------------------------------------------------------
# Behavior 13 -- the per-path cap counts neither the header nor the summary.
# ---------------------------------------------------------------------------


def test_behavior13_per_path_cap_excludes_header_and_summary(tmp_path, monkeypatch):
    root = _mkrepo(tmp_path, "caprepo")
    _spy_run(monkeypatch, "## main...origin/main [ahead 5]\n M a.py\n M b.py\n")

    signals = _collect(root, max_items=1)

    assert [s.summary for s in signals] == [
        "Uncommitted change in caprepo: a.py",
        "5 unpushed commit(s) in caprepo ahead of upstream",
    ], (
        "max_items=1 caps the PER-PATH signals at 1 and never counts the header "
        f"or the unpushed summary; got {[s.summary for s in signals]!r}"
    )
    assert len([s for s in signals if s.path is not None]) == 1, (
        f"exactly one per-path signal under max_items=1; got {[s.path for s in signals]!r}"
    )


# ---------------------------------------------------------------------------
# Behavior 12 -- real-git equivalence, fully offline (bare repo cloned by local
# filesystem path). Skipped when git is unavailable.
# ---------------------------------------------------------------------------


def _git_available() -> bool:
    try:
        result = subprocess.run(["git", "--version"], capture_output=True, timeout=5)
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


_needs_git = pytest.mark.skipif(not _git_available(), reason="git is not available on this system")

_HEADER_AHEAD_RE = re.compile(r"^## \S+\.\.\.\S+ \[(?:[^\]]*?\bahead (?P<n>\d+))")


def _git_env() -> dict[str, str]:
    """Deterministic identity, and a git that cannot see the developer's global
    or system config (so no alias/hook/config can change the result)."""
    return {
        **os.environ,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "t@test.com",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "t@test.com",
        "GIT_TERMINAL_PROMPT": "0",
    }


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        env=_git_env(),
        timeout=30,
    )
    assert result.returncode == 0, (
        f"test setup `git {' '.join(args)}` failed rc={result.returncode}: "
        f"{result.stderr.strip()!r}"
    )
    return result.stdout


def _commit(work: Path, name: str) -> None:
    (work / name).write_text(f"{name}\n", encoding="utf-8")
    _git(work, "add", name)
    _git(work, "-c", "commit.gpgsign=false", "commit", "-m", f"add {name}")


def _ahead_from_status(work: Path) -> int:
    """Parse the ahead count out of `status --porcelain --branch`'s header --
    derived here independently of the implementation."""
    first = _git(work, "status", "--porcelain", "--branch").splitlines()[0]
    m = _HEADER_AHEAD_RE.match(first)
    return int(m.group("n")) if m else 0


def _ahead_from_rev_list(work: Path) -> int:
    result = subprocess.run(
        ["git", "-C", str(work), "rev-list", "--count", "@{u}..HEAD"],
        capture_output=True,
        text=True,
        env=_git_env(),
        timeout=30,
    )
    return int(result.stdout.strip()) if result.returncode == 0 else 0


@_needs_git
def test_behavior12_real_git_header_equals_rev_list_offline(tmp_path):
    origin = tmp_path / "origin.git"
    origin.mkdir()
    _git(origin, "init", "--bare", "-b", "main")

    work = tmp_path / "clone"
    # Clone by LOCAL FILESYSTEM PATH -- no network is involved.
    clone = subprocess.run(
        ["git", "clone", str(origin), str(work)],
        capture_output=True,
        text=True,
        env=_git_env(),
        timeout=60,
    )
    assert clone.returncode == 0, f"local clone failed: {clone.stderr.strip()!r}"

    _commit(work, "first.txt")
    _git(work, "push", "-u", "origin", "main")  # establishes upstream, ahead == 0

    for expected in (0, 1, 3):
        while _ahead_from_rev_list(work) < expected:
            _commit(work, f"c{_ahead_from_rev_list(work) + 1}.txt")

        from_status = _ahead_from_status(work)
        from_rev_list = _ahead_from_rev_list(work)
        assert from_status == from_rev_list == expected, (
            "the ahead count parsed from `status --porcelain --branch` must equal "
            f"`rev-list --count @{{u}}..HEAD`; header={from_status} "
            f"rev-list={from_rev_list} expected={expected}"
        )

        signals = _collect(work)
        summaries = [s.summary for s in _unpushed(signals)]
        if expected == 0:
            assert summaries == [], (
                f"a synced clone must emit no unpushed summary; got {summaries!r}"
            )
        else:
            assert summaries == [
                f"{expected} unpushed commit(s) in clone ahead of upstream"
            ], f"real-git ahead={expected} must be reported; got {summaries!r}"
