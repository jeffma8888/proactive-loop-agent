"""Black-box behavior tests for iteration 53.

Feature under test: a new **L2 perception collector**, ``GitStashCollector``
(``name == "git_stash"``, ``kind == "git_stash"``). It is the *shelved-work*
member completing the git-perception family alongside ``git_activity`` (the
committed past), ``working_tree`` (the present diff / unpushed count), and
``git_state`` (interrupted operations). It surfaces changes the user
deliberately ``git stash``-ed and then forgot -- invisible to ``git status``
and ``git log`` -- by reading the stash reflog marker file
``.git/logs/refs/stash`` **with ``pathlib`` only** (the same deliberate
discipline as ``git_state``: NO ``subprocess``, NO ``git stash list``, NO
network). It scans ``root`` plus each direct-child dir whose ``.git`` is a
*directory*, emits exactly ONE ``kind="git_stash"`` summary signal per
stash-bearing repo (``weight == 0.6``, ``path is None``, ``timestamp is None``),
sorts output by ``summary`` ascending, caps the signal count at ``max_items``
(default 30), and -- like every collector -- degrades to ``[]`` rather than
raising on any missing / hostile input.

ISOLATION CONTRACT (honored): these tests are written strictly against the
public contract -- this iteration's spec "Expected Behaviors" (``pm.md``),
``README.md``, and ``SPEC.md`` section 4.1 (the ``collectors`` module contract)
-- and drive ONLY the documented public surface: the public collector API
``proactive_loop.collectors.GitStashCollector().collect(root)``, the
``proactive_loop.collectors.git_stash`` submodule import, the
``all_collectors()`` registry, the ``Collector`` protocol from
``proactive_loop.collectors.base``, the ``ContextSignal`` domain model from
``proactive_loop.models``, ``proactive_loop.__version__``, and the PRIMARY
end-to-end entry point ``pla signals --workspace W --kind git_stash --json`` via
``cli.main([...])`` (its observable stdout / exit code). **No file under
``src/`` was read, no engineer/reviewer notes were read, and no ``git diff`` was
consulted.** Signal field names (``source``/``kind``/``summary``/``detail``/
``path``/``weight``/``timestamp``) were taken from this iteration's spec and the
existing published tests, never from the implementation.

Every test builds its own synthetic ``tmp_path`` workspace: it creates a
``.git/`` **directory** and writes a hand-crafted, real tab-delimited
``logs/refs/stash`` reflog file into it (NO real git repo, NO ``subprocess``, NO
network, NO API keys) -- the collector only reads that one marker file. No test
asserts against ``examples/fixture_workspace`` (per the iter-15/16 env-stability
lesson). Fully offline: the CLI tests pass ``--provider scripted`` WITHOUT a
``--scripted-responses`` file precisely to prove the ``signals`` inspector
builds no ``LLMClient`` (it would fault if it did).

The reflog wire format (SPEC-pinned): a line is
``<old-sha> <new-sha> <name> <email> <unix-ts> <tz>\t<message>`` -- the message
is everything AFTER the FIRST tab. The file appends chronologically, so the LAST
non-blank line is the newest stash (``stash@{0}``) and the FIRST is the oldest.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import proactive_loop
from proactive_loop.cli import main
from proactive_loop.collectors import GitStashCollector, all_collectors
from proactive_loop.collectors.base import Collector
from proactive_loop.collectors.git_stash import (
    GitStashCollector as GitStashCollector_direct,
)
from proactive_loop.models import ContextSignal


# ---------------------------------------------------------------------------
# Helpers -- all black-box: build synthetic tmp workspaces, drive the public
# collector API / the CLI, read back observable output.
# ---------------------------------------------------------------------------


def _repo(base: Path, name: str = "repo") -> Path:
    """Create ``base/<name>`` with a ``.git/`` **directory** inside; return it."""
    d = base / name
    (d / ".git").mkdir(parents=True)
    return d


def _line(msg: str, *, old: str = "0" * 40, new: str = "f7a3af3") -> str:
    """Build ONE real tab-delimited stash reflog line whose message is *msg*.

    The old/new SHAs, name, email, ts, tz are all BEFORE the first tab, so they
    are irrelevant to message parsing -- only the text after ``\\t`` is the
    stash message.
    """
    return f"{old} {new} Tester <t@t.com> 1785545283 -0700\t{msg}"


def _reflog(repo_dir: Path, *lines: str, raw: bytes | None = None) -> Path:
    """Write ``<repo>/.git/logs/refs/stash``.

    Pass either ready-made ``lines`` (joined with ``\\n``, trailing newline) or
    ``raw=`` bytes to write verbatim (for the undecodable-bytes case).
    """
    p = repo_dir / ".git" / "logs" / "refs" / "stash"
    p.parent.mkdir(parents=True, exist_ok=True)
    if raw is not None:
        p.write_bytes(raw)
    else:
        text = "\n".join(lines) + ("\n" if lines else "")
        p.write_text(text, encoding="utf-8")
    return p


def _run(argv: list[str], capsys) -> tuple[int, str, str]:
    """Invoke the CLI, return (rc, stdout, stderr). Drains capsys first so setup
    output never leaks into the assertion window."""
    capsys.readouterr()
    rc = main(argv)
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def _signals_json(workspace: Path, capsys, *, kind: str | None = "git_stash") -> list[dict]:
    """Run ``pla signals --workspace W [--kind K] --json`` and return the parsed
    ``signals`` array. ``--provider scripted`` WITHOUT ``--scripted-responses``
    proves the inspector is LLM-free (it would fault building a client)."""
    argv = ["signals", "--workspace", str(workspace), "--provider", "scripted", "--json"]
    if kind is not None:
        argv += ["--kind", kind]
    rc, out, err = _run(argv, capsys)
    assert rc == 0, f"signals must exit 0; stderr={err!r}"
    doc = json.loads(out)  # the ENTIRE stdout must parse as one clean JSON object
    assert isinstance(doc, dict)
    assert set(doc.keys()) == {"workspace_root", "signals"}, doc.keys()
    assert isinstance(doc["signals"], list)
    return doc["signals"]


# ===========================================================================
# Behavior 1 -- A repo whose `.git` is a directory containing a non-blank
#               `.git/logs/refs/stash` -> exactly ONE summary signal with the
#               fixed fields: source/kind == "git_stash", weight == 0.6,
#               path is None, timestamp is None.
# ===========================================================================


def test_b01_single_repo_reflog_one_signal_fixed_fields(tmp_path: Path) -> None:
    repo = _repo(tmp_path, "repo")
    _reflog(repo, _line("WIP on main: 404051f init"))

    sigs = GitStashCollector().collect(tmp_path)

    assert len(sigs) == 1, f"exactly one summary signal expected; got {sigs!r}"
    s = sigs[0]
    assert isinstance(s, ContextSignal)
    assert s.source == "git_stash"
    assert s.kind == "git_stash"
    assert s.weight == 0.6
    assert s.path is None
    assert s.timestamp is None


# ===========================================================================
# Behavior 2 -- Count + latest-message in the summary, with singular/plural
#               pluralization ("entry" at N==1, "entries" otherwise) and the
#               latest = message from the LAST non-blank reflog line.
# ===========================================================================


def test_b02_single_entry_singular_summary(tmp_path: Path) -> None:
    repo = _repo(tmp_path, "repo")
    _reflog(repo, _line("WIP on main: fix login"))

    sigs = GitStashCollector().collect(tmp_path)

    assert len(sigs) == 1
    assert sigs[0].summary == "repo: 1 stash entry (latest: WIP on main: fix login)"
    assert not sigs[0].summary.endswith("entries (latest: WIP on main: fix login)")


def test_b02_multiple_entries_plural_summary_latest_is_last_line(tmp_path: Path) -> None:
    repo = _repo(tmp_path, "myproj")
    # File order is chronological -> LAST line is the newest (stash@{0}).
    _reflog(
        repo,
        _line("On main: wip: first change"),   # oldest
        _line("second stash"),
        _line("WIP on main: 404051f init"),     # newest -> the "latest"
    )

    sigs = GitStashCollector().collect(tmp_path)

    assert len(sigs) == 1
    assert sigs[0].summary == (
        "myproj: 3 stash entries (latest: WIP on main: 404051f init)"
    )


def test_b02_blank_lines_not_counted_latest_is_last_nonblank(tmp_path: Path) -> None:
    repo = _repo(tmp_path, "repo")
    # Interior + trailing blank lines must not inflate N nor become "latest".
    p = repo / ".git" / "logs" / "refs" / "stash"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "\n".join(
            [
                _line("older stash"),
                "",                       # blank interior line
                "   ",                    # whitespace-only interior line
                _line("newest real stash"),
                "",                       # trailing blank line
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    sigs = GitStashCollector().collect(tmp_path)

    assert len(sigs) == 1
    assert sigs[0].summary == "repo: 2 stash entries (latest: newest real stash)"


# ===========================================================================
# Behavior 3 -- Message-parse contract: the message is the substring AFTER the
#               first tab, verbatim (colons/spaces preserved, not truncated).
#               Defensive: a non-blank line WITHOUT a tab degrades to the whole
#               line as the message (never raises).
# ===========================================================================


def test_b03_message_after_first_tab_kept_verbatim(tmp_path: Path) -> None:
    repo = _repo(tmp_path, "repo")
    # A message containing colons and spaces must survive whole (not cut at ':').
    msg = "WIP on main: 404051f init: refactor auth (part 2)"
    _reflog(repo, _line(msg))

    sigs = GitStashCollector().collect(tmp_path)

    assert len(sigs) == 1
    assert sigs[0].summary == f"repo: 1 stash entry (latest: {msg})"
    assert sigs[0].detail == msg


def test_b03_message_after_first_tab_only_first_tab_splits(tmp_path: Path) -> None:
    repo = _repo(tmp_path, "repo")
    # A message that itself contains a tab: only the FIRST tab splits, so the
    # message keeps its internal tab (split("\t", 1)[1]).
    p = repo / ".git" / "logs" / "refs" / "stash"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        f"{'0'*40} f7a3af3 T <t@t.com> 1785545283 -0700\tmsg\twith\ttabs\n",
        encoding="utf-8",
    )

    sigs = GitStashCollector().collect(tmp_path)

    assert len(sigs) == 1
    assert sigs[0].detail == "msg\twith\ttabs"


def test_b03_tabless_line_degrades_to_whole_line_no_raise(tmp_path: Path) -> None:
    repo = _repo(tmp_path, "repo")
    # A non-blank line lacking any tab: treated as a message equal to the whole
    # line -- and it must NOT raise.
    p = repo / ".git" / "logs" / "refs" / "stash"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("a line with no tab at all\n", encoding="utf-8")

    sigs = GitStashCollector().collect(tmp_path)

    assert len(sigs) == 1
    assert sigs[0].detail == "a line with no tab at all"
    assert sigs[0].summary == "repo: 1 stash entry (latest: a line with no tab at all)"


# ===========================================================================
# Behavior 4 -- `detail` = all stash messages, NEWEST-FIRST (reverse of file
#               order), capped at max_items lines.
# ===========================================================================


def test_b04_detail_newest_first_matches_spec_example(tmp_path: Path) -> None:
    repo = _repo(tmp_path, "repo")
    # The exact two-line SPEC example.
    _reflog(
        repo,
        _line("On main: wip: first change"),   # oldest (first line)
        _line("WIP on main: 404051f init"),     # newest (last line)
    )

    sigs = GitStashCollector().collect(tmp_path)

    assert len(sigs) == 1
    assert sigs[0].detail == "WIP on main: 404051f init\nOn main: wip: first change"
    # The first detail line matches the summary's (latest: ...).
    assert sigs[0].summary.endswith("(latest: WIP on main: 404051f init)")


def test_b04_detail_capped_at_max_items_keeps_newest(tmp_path: Path) -> None:
    collector = GitStashCollector()
    assert collector.max_items == 30, "default max_items must be 30"

    repo = _repo(tmp_path, "repo")
    total = 35
    # msg00 (oldest, first line) .. msg34 (newest, last line).
    _reflog(repo, *[_line(f"msg{i:02d}") for i in range(total)])

    sigs = collector.collect(tmp_path)

    assert len(sigs) == 1, "one repo -> one summary signal even with many stashes"
    detail_lines = sigs[0].detail.split("\n")
    assert len(detail_lines) == 30, f"detail capped at max_items=30; got {len(detail_lines)}"
    # Newest-first: msg34, msg33, ..., down to msg05 (the newest 30).
    expected = [f"msg{i:02d}" for i in range(total - 1, total - 1 - 30, -1)]
    assert detail_lines == expected
    # The latest message (newest) is msg34 no matter the cap.
    assert sigs[0].summary.endswith("(latest: msg34)")


# ===========================================================================
# Behavior 5 -- A repo whose `.git` is a directory but with NO
#               `.git/logs/refs/stash` file (the common case) -> zero signals.
# ===========================================================================


def test_b05_no_reflog_file_no_signal(tmp_path: Path) -> None:
    _repo(tmp_path, "repo")  # .git dir exists, but no logs/refs/stash
    assert GitStashCollector().collect(tmp_path) == []


# ===========================================================================
# Behavior 6 -- An empty or whitespace-only reflog -> zero signals.
# ===========================================================================


def test_b06_empty_reflog_no_signal(tmp_path: Path) -> None:
    repo = _repo(tmp_path, "repo")
    (repo / ".git" / "logs" / "refs").mkdir(parents=True, exist_ok=True)
    (repo / ".git" / "logs" / "refs" / "stash").write_text("", encoding="utf-8")
    assert GitStashCollector().collect(tmp_path) == []


def test_b06_whitespace_only_reflog_no_signal(tmp_path: Path) -> None:
    repo = _repo(tmp_path, "repo")
    p = repo / ".git" / "logs" / "refs" / "stash"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n   \n\t\n  \n", encoding="utf-8")  # only blank/whitespace lines
    assert GitStashCollector().collect(tmp_path) == []


# ===========================================================================
# Behavior 7 -- A directory whose `.git` is a regular FILE (worktree/submodule
#               pointer) is skipped -- no signal. Mirrors GitStateCollector.
# ===========================================================================


def test_b07_git_that_is_a_file_is_skipped(tmp_path: Path) -> None:
    d = tmp_path / "worktree"
    d.mkdir()
    (d / ".git").write_text("gitdir: /somewhere/else\n", encoding="utf-8")
    # Even if a bogus reflog somehow existed alongside, a .git-FILE repo is not
    # dereferenced. Here there is no .git dir at all -> definitely no signal.
    assert GitStashCollector().collect(tmp_path) == []


# ===========================================================================
# Behavior 8 -- Scans root + DIRECT children only; deterministic ascending sort.
# ===========================================================================


def test_b08_root_itself_is_scanned(tmp_path: Path) -> None:
    # root is itself a repo with a stash.
    (tmp_path / ".git").mkdir()
    _reflog(tmp_path, _line("root stash"))

    sigs = GitStashCollector().collect(tmp_path)

    assert len(sigs) == 1
    assert sigs[0].summary.endswith("1 stash entry (latest: root stash)")


def test_b08_two_levels_deep_not_surfaced(tmp_path: Path) -> None:
    # root has no .git; root/a has no .git; only root/a/b (TWO levels deep) is a
    # repo with a stash -> NOT surfaced (direct children only).
    deep = tmp_path / "a" / "b"
    (deep / ".git").mkdir(parents=True)
    _reflog(deep, _line("buried stash"))

    assert GitStashCollector().collect(tmp_path) == []


def test_b08_multiple_repos_one_signal_each_sorted_deterministic(tmp_path: Path) -> None:
    # root has no .git; three direct-child repos each carry a stash. Created in
    # a deliberately NON-sorted order to prove the output is summary-sorted.
    for name in ("zeta", "alpha", "mid"):
        repo = _repo(tmp_path, name)
        _reflog(repo, _line(f"{name} wip"))

    sigs = GitStashCollector().collect(tmp_path)

    assert len(sigs) == 3, "one signal per stash-bearing direct-child repo"
    summaries = [s.summary for s in sigs]
    assert summaries == sorted(summaries), f"must be summary-ascending; got {summaries}"
    assert summaries == [
        "alpha: 1 stash entry (latest: alpha wip)",
        "mid: 1 stash entry (latest: mid wip)",
        "zeta: 1 stash entry (latest: zeta wip)",
    ]
    # Deterministic: a second scan is byte-identical.
    assert [s.summary for s in GitStashCollector().collect(tmp_path)] == summaries


# ===========================================================================
# Behavior 9 -- Never raises -> [] (SPEC 4.1 contract): non-directory root, a
#               nonexistent path, an unreadable reflog, and undecodable bytes
#               all degrade gracefully rather than propagating an exception.
# ===========================================================================


def test_b09_nondirectory_root_returns_empty(tmp_path: Path) -> None:
    a_file = tmp_path / "afile.txt"
    a_file.write_text("i am not a directory\n", encoding="utf-8")
    assert GitStashCollector().collect(a_file) == []


def test_b09_nonexistent_path_returns_empty(tmp_path: Path) -> None:
    assert GitStashCollector().collect(tmp_path / "no" / "such" / "dir") == []


def test_b09_unreadable_reflog_never_raises(tmp_path: Path) -> None:
    repo = _repo(tmp_path, "repo")
    reflog = _reflog(repo, _line("secret stash"))
    os.chmod(reflog, 0)
    try:
        sigs = GitStashCollector().collect(tmp_path)  # must NOT raise
    finally:
        os.chmod(reflog, 0o644)  # restore so tmp cleanup can remove it

    assert isinstance(sigs, list)
    if not os.access(reflog, os.R_OK):
        # Only assert the skip when the file is genuinely unreadable (i.e. not
        # running as root, where chmod 000 is bypassed).
        assert sigs == [], "an unreadable reflog must degrade to no signal, never raise"


def test_b09_undecodable_bytes_never_raises(tmp_path: Path) -> None:
    repo = _repo(tmp_path, "repo")
    # Non-UTF-8 bytes: with errors="replace" the read degrades gracefully; the
    # collector must return a list and never propagate a UnicodeDecodeError.
    _reflog(repo, raw=b"\xff\xfe\x00\x01 not utf8 \x80\x81\xff")

    sigs = GitStashCollector().collect(tmp_path)

    assert isinstance(sigs, list), "undecodable bytes must degrade to a list, never raise"


# ===========================================================================
# Behavior 10 -- The emitted git_stash SIGNAL COUNT is capped at max_items
#                (default 30): with >30 distinct stash-bearing repos, exactly
#                the 30 lexicographically-smallest summaries are returned.
# ===========================================================================


def test_b10_signal_count_capped_at_max_items(tmp_path: Path) -> None:
    collector = GitStashCollector()
    assert collector.max_items == 30

    total = 35
    # root has no .git; 35 direct-child repos, one stash each. Names zero-padded
    # so the ascending-summary sort is predictable.
    for i in range(total):
        repo = _repo(tmp_path, f"r{i:02d}")
        _reflog(repo, _line("wip"))

    sigs = collector.collect(tmp_path)

    assert len(sigs) == 30, f"signal count capped at max_items=30; got {len(sigs)}"
    summaries = [s.summary for s in sigs]
    expected = sorted(f"r{i:02d}: 1 stash entry (latest: wip)" for i in range(total))[:30]
    assert summaries == expected, "the 30 lexicographically-smallest summaries, ascending"
    # Deterministic across repeated calls.
    assert [s.summary for s in collector.collect(tmp_path)] == summaries


# ===========================================================================
# Behavior 11 -- Registry + end-to-end CLI integration. all_collectors()
#                returns 15 collectors, one of them named "git_stash"; the class is
#                exported from proactive_loop.collectors; and the new kind flows
#                out through the existing `pla signals` inspector.
# ===========================================================================


def test_b11_registry_has_fifteen_with_git_stash(capsys) -> None:
    collectors = all_collectors()

    assert len(collectors) == 17, f"registry must now list 17 collectors; got {len(collectors)}"
    matches = [c for c in collectors if c.name == "git_stash"]
    assert len(matches) == 1, "exactly one git_stash collector in the registry"
    assert type(matches[0]) is GitStashCollector
    # Package alias and direct-submodule import are the same class object.
    assert GitStashCollector is GitStashCollector_direct

    # Every registered collector still satisfies the Collector duck-type.
    for c in collectors:
        assert isinstance(c.name, str) and c.name
        assert callable(getattr(c, "collect", None))
    assert isinstance(GitStashCollector(), Collector) or hasattr(
        GitStashCollector(), "collect"
    )

    # Additive kind => NO version bump.
    assert proactive_loop.__version__ == "0.1.1", proactive_loop.__version__


def test_b11_cli_signals_json_emits_git_stash(tmp_path: Path, capsys) -> None:
    repo = _repo(tmp_path, "repo")
    _reflog(
        repo,
        _line("On main: wip: first change"),
        _line("WIP on main: 404051f init"),
    )

    sigs = _signals_json(tmp_path, capsys)

    assert len(sigs) == 1
    assert sigs[0] == {
        "source": "git_stash",
        "kind": "git_stash",
        "summary": "repo: 2 stash entries (latest: WIP on main: 404051f init)",
        "detail": "WIP on main: 404051f init\nOn main: wip: first change",
        "path": None,
        "weight": 0.6,
    }


def test_b11_cli_signals_json_empty_when_no_stash(tmp_path: Path, capsys) -> None:
    # A repo with a .git dir but NO stash reflog -> nothing for the git_stash kind.
    _repo(tmp_path, "repo")

    argv = ["signals", "--workspace", str(tmp_path), "--provider", "scripted",
            "--kind", "git_stash", "--json"]
    rc, out, err = _run(argv, capsys)

    assert rc == 0, err
    doc = json.loads(out)
    assert doc["signals"] == [], f"no stash -> no git_stash signal; got {doc!r}"
    assert isinstance(doc["workspace_root"], str) and doc["workspace_root"]
