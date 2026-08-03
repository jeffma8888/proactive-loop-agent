"""Black-box behavior tests for commit-seq factory iter 92 (state-dir iter-82).

Feature under test (pm.md / SPEC 4.1): ``NotesCollector`` must scan its
notes-style directories (``notes`` / ``journal`` / ``docs``) in DETERMINISTIC
ascending-path order, so that with two or more such directories BOTH the emission
order AND which headings survive the ``max_items`` cap become a total,
``os.walk``-order-independent function of the filesystem. The fix sorts the
DIRECTORIES, never the emitted signals -- within-file heading source order and
within-dir file order (``sorted(rglob("*.md"))``) are preserved.

ISOLATION CONTRACT (honored): these tests drive ONLY the public interface --
``NotesCollector(max_items=N).collect(root)`` and the ``pla`` CLI via
``proactive_loop.cli.main([...])`` -- and the public registries
(``all_collectors()`` / ``ToolRegistry`` / ``VALID_PROVIDERS`` / ``__version__``).
No file under ``src/`` was read, no engineer/reviewer notes were read, and no
``git diff`` was consulted; the assertions encode pm.md's Expected Behaviors, not
the implementation. To control filesystem-traversal order the tests monkeypatch
``proactive_loop.collectors.notes.os.walk`` (the seam iters 79/80/84/85 used) to
force the top-level notes sub-directory yield order. Workspaces are synthetic
``tmp_path``; the only real-FS reference is the bundled read-only fixture
(``examples/fixture_workspace``) for the single-dir byte-stability check (B5).

File naming: the prompt's state-dir iteration is 82, but ``tests/test_iter82_
behavior.py`` already exists (an earlier commit-seq iteration). The repo names
behavior files after the COMMIT SEQUENCE, which for this iteration is factory
iter 92 (pm.md header + ROADMAP row #92); ``test_iter92_behavior.py`` was confirmed
unused before creation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from proactive_loop import __version__
from proactive_loop.cli import build_parser, main
from proactive_loop.collectors import NotesCollector, all_collectors
from proactive_loop.llm.providers import VALID_PROVIDERS
from proactive_loop.loop.tools import ToolRegistry

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "examples" / "fixture_workspace"


# ---------------------------------------------------------------------------
# Black-box helpers.
# ---------------------------------------------------------------------------


def _write(root: Path, subdir: str, name: str, content: str) -> None:
    d = root / subdir
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(content, encoding="utf-8")


def _make_fake_walk(top_order):
    """A fake ``os.walk`` yielding the root then each named top-level sub-dir (with
    its real files) in ``top_order`` -- forces the notes-dir ENCOUNTER order so a
    determinism regression (dependence on walk order) is observable."""

    def fake_walk(top, *args, **kwargs):
        top = Path(top)
        yield (str(top), list(top_order), [])
        for name in top_order:
            d = top / name
            files = sorted(p.name for p in d.iterdir() if p.is_file())
            yield (str(d), [], files)

    return fake_walk


def _collect(root: Path, *, max_items: int, walk_order, monkeypatch):
    monkeypatch.setattr(
        "proactive_loop.collectors.notes.os.walk", _make_fake_walk(walk_order)
    )
    return NotesCollector(max_items=max_items).collect(root)


def _run(argv, capsys):
    """Invoke the CLI and return (rc, stdout, stderr). Drains capsys first."""
    capsys.readouterr()
    rc = main(argv)
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def _two_dir_workspace(tmp_path: Path) -> Path:
    """A workspace with a ``docs/`` and a ``notes/`` dir, each holding one md file
    with two headings -> 4 note signals total (docs sorts before notes)."""
    _write(tmp_path, "docs", "d.md", "# docs-h1\n\nb1\n\n# docs-h2\n\nb2\n")
    _write(tmp_path, "notes", "n.md", "# notes-h1\n\nb1\n\n# notes-h2\n\nb2\n")
    return tmp_path


# ===========================================================================
# Behavior 1 -- Cross-dir cap-selection is DETERMINISTIC (load-bearing).
# With max_items < total heading count, the surviving signals are the first
# N by (dir path asc, file path asc, heading source order) -- byte-identical
# regardless of os.walk's top-level yield order.
# ===========================================================================


def test_b1_cap_selection_identical_under_both_walk_orders(tmp_path, monkeypatch):
    ws = _two_dir_workspace(tmp_path)
    forward = _collect(ws, max_items=2, walk_order=["docs", "notes"], monkeypatch=monkeypatch)
    reverse = _collect(ws, max_items=2, walk_order=["notes", "docs"], monkeypatch=monkeypatch)
    fwd = [(s.summary, s.path) for s in forward]
    rev = [(s.summary, s.path) for s in reverse]
    assert fwd == rev, (
        f"cross-dir cap selection depends on os.walk order (non-deterministic): "
        f"forward={fwd} reverse={rev}"
    )


def test_b1_cap_keeps_ascending_first_dir_signals(tmp_path, monkeypatch):
    ws = _two_dir_workspace(tmp_path)
    # max_items=2 over 4 headings: the two survivors must be the docs/ dir's
    # (docs < notes), NOT whatever os.walk happens to yield first.
    for order in (["docs", "notes"], ["notes", "docs"]):
        sigs = _collect(ws, max_items=2, walk_order=order, monkeypatch=monkeypatch)
        assert [s.summary for s in sigs] == ["docs-h1", "docs-h2"], (
            f"cap must keep the ascending-first dir (docs) signals; order={order} "
            f"got {[s.summary for s in sigs]}"
        )
        assert all(s.path == "docs/d.md" for s in sigs), [s.path for s in sigs]


def test_b1_three_notes_dirs_total_order(tmp_path, monkeypatch):
    # docs < journal < notes -> with max_items=2 only the docs signals survive,
    # under any forced walk order.
    _write(tmp_path, "docs", "d.md", "# d1\n\nx\n\n# d2\n\nx\n")
    _write(tmp_path, "journal", "j.md", "# j1\n\nx\n")
    _write(tmp_path, "notes", "n.md", "# n1\n\nx\n")
    for order in (["docs", "journal", "notes"], ["notes", "journal", "docs"], ["journal", "notes", "docs"]):
        sigs = _collect(tmp_path, max_items=2, walk_order=order, monkeypatch=monkeypatch)
        assert [s.summary for s in sigs] == ["d1", "d2"], (
            f"total order (docs<journal<notes) violated; order={order} "
            f"got {[s.summary for s in sigs]}"
        )


# ===========================================================================
# Behavior 2 -- Cross-dir emission order is DETERMINISTIC (no cap).
# With max_items large enough that no cap fires, emit the ascending-first dir's
# signals, then the next dir's -- byte-identical under opposite walk orders.
# ===========================================================================


def test_b2_full_emission_order_identical_under_both_walk_orders(tmp_path, monkeypatch):
    ws = _two_dir_workspace(tmp_path)
    forward = _collect(ws, max_items=20, walk_order=["docs", "notes"], monkeypatch=monkeypatch)
    reverse = _collect(ws, max_items=20, walk_order=["notes", "docs"], monkeypatch=monkeypatch)
    fwd = [(s.summary, s.path) for s in forward]
    rev = [(s.summary, s.path) for s in reverse]
    assert fwd == rev, f"full emission order depends on walk order: fwd={fwd} rev={rev}"


def test_b2_emission_is_docs_then_notes(tmp_path, monkeypatch):
    ws = _two_dir_workspace(tmp_path)
    for order in (["docs", "notes"], ["notes", "docs"]):
        sigs = _collect(ws, max_items=20, walk_order=order, monkeypatch=monkeypatch)
        assert [s.summary for s in sigs] == [
            "docs-h1",
            "docs-h2",
            "notes-h1",
            "notes-h2",
        ], f"cross-dir order must follow ascending dir path; order={order} got {[s.summary for s in sigs]}"


# ===========================================================================
# Behavior 3 -- Within-file heading order stays SOURCE order (discriminates the
# WRONG fix: sorting the emitted signals by summary would alphabetize headings).
# ===========================================================================


def test_b3_within_file_headings_stay_source_order(tmp_path, monkeypatch):
    _write(tmp_path, "notes", "z.md", "# Zebra\n\nz\n\n# Apple\n\na\n")
    sigs = _collect(tmp_path, max_items=20, walk_order=["notes"], monkeypatch=monkeypatch)
    summaries = [s.summary for s in sigs]
    assert summaries == ["Zebra", "Apple"], (
        f"within-file headings must stay SOURCE order (not alphabetized); got {summaries}"
    )
    assert summaries != ["Apple", "Zebra"], "signals were re-sorted by summary (wrong fix)"


# ===========================================================================
# Behavior 4 -- Within-dir file order stays ascending path (sorted rglob).
# ===========================================================================


def test_b4_within_dir_files_stay_ascending_path(tmp_path, monkeypatch):
    _write(tmp_path, "notes", "b.md", "# BeeHead\n\nx\n")
    _write(tmp_path, "notes", "a.md", "# AyeHead\n\nx\n")
    sigs = _collect(tmp_path, max_items=20, walk_order=["notes"], monkeypatch=monkeypatch)
    pairs = [(s.summary, s.path) for s in sigs]
    assert pairs == [("AyeHead", "notes/a.md"), ("BeeHead", "notes/b.md")], (
        f"files within a notes dir must stay ascending path (a.md before b.md); got {pairs}"
    )


# ===========================================================================
# Behavior 5 -- Single notes dir is byte-identical (backward compatible):
# sorting a one-element list is a no-op. The bundled fixture has exactly one
# notes dir -> `pla signals --kind note` still prints its 5 note signals.
# ===========================================================================


def test_b5_fixture_single_dir_still_five_note_signals(capsys):
    rc, out, err = _run(
        ["signals", "--workspace", str(FIXTURE), "--kind", "note"], capsys
    )
    assert rc == 0, f"signals must exit 0; stderr={err!r}"
    assert "## note (5)" in out, f"fixture must still emit exactly 5 note signals; got:\n{out}"
    for expected in (
        "Job search notes",
        "Learning agentic loops",
        "Personal project ideas",
        "Reminders",
        "Working Journal",
    ):
        assert expected in out, f"missing fixture note {expected!r}; got:\n{out}"
    assert "notes/journal.md" in out, f"fixture notes must come from notes/journal.md; got:\n{out}"


def test_b5_single_dir_direct_collect_walk_order_independent(tmp_path, monkeypatch):
    # A one-notes-dir workspace: output identical under any (trivial) walk order.
    _write(tmp_path, "notes", "n.md", "# One\n\nx\n\n# Two\n\ny\n")
    a = _collect(tmp_path, max_items=20, walk_order=["notes"], monkeypatch=monkeypatch)
    assert [s.summary for s in a] == ["One", "Two"]


# ===========================================================================
# Behavior 6 -- Graceful degradation preserved (never raises).
# ===========================================================================


def test_b6_missing_root_returns_empty(tmp_path):
    assert NotesCollector().collect(tmp_path / "does_not_exist") == []


def test_b6_file_as_root_returns_empty(tmp_path):
    f = tmp_path / "afile"
    f.write_text("hi", encoding="utf-8")
    assert NotesCollector().collect(f) == []


def test_b6_workspace_without_notes_dirs_returns_empty(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print(1)\n", encoding="utf-8")
    assert NotesCollector().collect(tmp_path) == []


def test_b6_fenced_code_heading_suppression_unchanged(tmp_path):
    # iter-81 behavior: a `# ...` line INSIDE a fenced code block is NOT a heading.
    _write(tmp_path, "notes", "a.md", "# Real\n\ntext\n\n```\n# NotAHeading\n```\n")
    summaries = {s.summary for s in NotesCollector().collect(tmp_path)}
    assert "Real" in summaries, f"real heading dropped; got {summaries}"
    assert "NotAHeading" not in summaries, f"fenced-code heading suppression regressed; got {summaries}"


# ===========================================================================
# Behavior 7 -- No registry / version drift.
# ===========================================================================


def test_b7_collector_count_unchanged():
    assert len(all_collectors()) == 15, "collector set changed (expected 15)"


def test_b7_tool_count_unchanged():
    assert len(ToolRegistry.tool_names()) == 14, "tool set changed (expected 14)"


def test_b7_provider_count_unchanged():
    assert len(VALID_PROVIDERS) == 7, "provider set changed (expected 7)"


def test_b7_verb_count_unchanged():
    subactions = [
        a for a in build_parser()._subparsers._group_actions if hasattr(a, "choices")
    ]
    assert subactions, "no subparser choices found"
    assert len(subactions[0].choices) == 14, "CLI verb set changed (expected 14)"


def test_b7_version_unchanged():
    assert __version__ == "0.1.1", f"unexpected version bump: {__version__!r}"
