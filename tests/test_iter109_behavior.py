"""Black-box behavior tests for commit-seq **factory iter 109** (state-dir iter-102).

Feature under test (``pm.md`` ``## Expected Behaviors``, ROADMAP row #108):
``NotesCollector`` must prune noise and hidden directories *while traversing* a
notes-style directory (``notes`` / ``journal`` / ``docs``). The OUTER walk that
LOCATES notes directories already prunes ``_SKIP_DIRS`` members and hidden dirs;
the INNER enumeration of a located notes directory did not, so vendored, build
and hidden subtrees under ``docs/`` were enumerated AND opened, emitting
``note`` signals at the same ``weight`` as real notes (a signal-QUALITY defect,
not only a throughput one). These tests assert the observable contract: no
collected note path carries a pruned path SEGMENT, real notes -- including
legitimately nested ones -- survive, noise files are never READ, ordering and
determinism are unchanged, and the fix is visible at the CLI front door.

ISOLATION CONTRACT (honored): every assertion here is written strictly against
THIS iteration's public contract -- the spec's Expected Behaviors in ``pm.md``,
the product ``README.md``, the roadmap row, and the product's own observable
output -- and drives ONLY the public surface: the public collector call
``NotesCollector(max_items=N).collect(root)`` and the ``pla`` CLI via
``proactive_loop.cli.main([...])`` (observable stdout / stderr / exit code),
plus the public ``all_collectors()`` registry and ``__version__``. **No file
under ``src/`` was read, no engineer or reviewer note was consulted, and no
``git diff`` was inspected** while authoring these assertions. Every test is
fully offline: zero network, zero API keys. Workspaces are synthetic
``tmp_path`` trees whose expected values are DERIVED from the tree the test
itself created (never a hardcoded count taken from
``examples/fixture_workspace``, which moves under you); the only real-FS
reference is the read-only bundled fixture, used solely for the
non-empty/no-pruned-segment regression check in behavior 8.

File naming: the state-dir iteration is 102 but ``tests/test_iter102_behavior.py``
already exists (an earlier commit-seq iteration). This repo names behavior files
after the COMMIT SEQUENCE, which for this iteration is factory iter 109 (HEAD is
``268a588 (factory iter 108)``); ``test_iter109_behavior.py`` was confirmed
unused before creation.
"""

from __future__ import annotations

import json
from pathlib import Path

from proactive_loop import __version__
from proactive_loop.cli import main
from proactive_loop.collectors import NotesCollector, all_collectors

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "examples" / "fixture_workspace"

# Directory names that must never appear as a path SEGMENT of a collected note.
# The first six are the members of the skip contract the module already declares;
# `.hidden` is hidden-ONLY (deliberately not a skip-set member) so the hidden
# rule is proven independent of set membership.
PRUNED_SEGMENTS = (
    "node_modules",
    "build",
    "dist",
    "__pycache__",
    ".git",
    ".venv",
    ".hidden",
)

# The two REAL notes of the spec's reference tree, as workspace-relative POSIX
# paths (the form `ContextSignal.path` uses).
REAL_NOTES = {"docs/design.md", "docs/sub/deep/nested.md"}

# Every noise file of the spec's reference tree.
NOISE_RELPATHS = (
    "docs/node_modules/pkg/readme.md",  # skip-set member
    "docs/build/out.md",  # skip-set member
    "docs/dist/out.md",  # skip-set member
    "docs/__pycache__/c.md",  # skip-set member
    "docs/.git/g.md",  # skip-set member AND hidden
    "docs/.venv/lib/v.md",  # skip-set member AND hidden
    "docs/.hidden/h.md",  # hidden ONLY, not in the skip set
    "docs/sub/node_modules/deep.md",  # skip-set member, two levels down
)

# One ATX heading + one paragraph => every readable file yields >= 1 note signal.
_NOTE_BODY = "# {title}\n\nBody paragraph for {title}.\n"

# Generous cap for exact-SET assertions so `max_items` can never be the reason a
# path is absent. (The default is exercised separately in test_b3_default_ctor.)
_BIG_CAP = 500


# ---------------------------------------------------------------------------
# Black-box helpers (public constructors / public CLI only; no src/ read).
# ---------------------------------------------------------------------------
def _write(root: Path, relpath: str, title: str) -> Path:
    p = root / relpath
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_NOTE_BODY.format(title=title), encoding="utf-8")
    return p


def _tree(root: Path) -> Path:
    """The spec's reference tree: 2 real notes + 8 noise notes, all under docs/."""
    _write(root, "docs/design.md", "design")
    _write(root, "docs/sub/deep/nested.md", "nested")
    for i, rel in enumerate(NOISE_RELPATHS):
        _write(root, rel, "noise%d" % i)
    return root


def _pruned_segment_in(path: str) -> str | None:
    """Return the offending SEGMENT of *path*, or None.

    WHY segments and not substrings: a legitimate ``docs/build-notes.md`` or
    ``docs/distilled/x.md`` contains the text "build"/"dist" but must SURVIVE, so
    a substring check would let an over-pruning fix pass (and would also let a
    correct fix look broken).
    """
    for seg in path.split("/"):
        if seg in PRUNED_SEGMENTS:
            return seg
    return None


def _collect(root: Path, *, max_items: int = _BIG_CAP):
    return NotesCollector(max_items=max_items).collect(root)


def _paths(signals) -> set[str]:
    return {(s.path or "") for s in signals}


def _offenders(paths) -> list[tuple[str, str]]:
    out = []
    for p in sorted(paths):
        seg = _pruned_segment_in(p)
        if seg is not None:
            out.append((p, seg))
    return out


def _run(argv, capsys):
    """Invoke the CLI and return (rc, stdout, stderr). Drains capsys first."""
    capsys.readouterr()
    rc = main(argv)
    cap = capsys.readouterr()
    return (rc if isinstance(rc, int) else 0), cap.out, cap.err


def _cli_note_paths(ws, capsys) -> set[str]:
    rc, out, err = _run(
        ["signals", "--workspace", str(ws), "--kind", "note", "--json"], capsys
    )
    assert rc == 0, "pla signals --kind note --json must exit 0; stderr=%r" % err
    doc = json.loads(out)
    assert "signals" in doc, "listing --json must carry a signals array; got %r" % sorted(doc)
    return {(s.get("path") or "") for s in doc["signals"]}


# ===========================================================================
# Behavior 1 -- Noise subtrees produce NO signals. No returned signal's path
# contains any of the pruned path SEGMENTS.
# ===========================================================================
def test_b1_no_signal_path_contains_a_pruned_segment(tmp_path):
    signals = _collect(_tree(tmp_path))
    assert signals, "the tree holds two readable notes; collect() must not return []"
    bad = _offenders(_paths(signals))
    assert bad == [], (
        "notes collected from pruned subtrees (path, offending segment): %r; "
        "the inner notes-dir traversal must PRUNE noise/hidden dirs" % (bad,)
    )


def test_b1_lookalike_names_are_not_pruned(tmp_path):
    """Over-pruning guard: pruning is per SEGMENT, so substring lookalikes live."""
    _write(tmp_path, "docs/build-notes.md", "build-notes")
    _write(tmp_path, "docs/distilled/summary.md", "distilled")
    _write(tmp_path, "docs/node_modules_backup/x.md", "backup")
    _write(tmp_path, "docs/build/out.md", "real-noise")
    got = _paths(_collect(tmp_path))
    assert got == {
        "docs/build-notes.md",
        "docs/distilled/summary.md",
        "docs/node_modules_backup/x.md",
    }, (
        "exactly the three lookalikes must survive and only the true skip-set dir "
        "`build/` must be pruned; got %r" % (sorted(got),)
    )


# ===========================================================================
# Behavior 2 -- Real notes survive, including nested ones (the fix must prune
# specific directories, NOT stop recursing).
# ===========================================================================
def test_b2_real_notes_survive_including_nested(tmp_path):
    got = _paths(_collect(_tree(tmp_path)))
    assert "docs/design.md" in got, "the top-level real note must survive; got %r" % (sorted(got),)
    assert "docs/sub/deep/nested.md" in got, (
        "a note in a legitimate nested dir must survive -- the fix must not stop "
        "recursing; got %r" % (sorted(got),)
    )


# ===========================================================================
# Behavior 3 -- EXACTLY the readable notes are represented (set equality).
# ===========================================================================
def test_b3_distinct_paths_equal_exactly_the_real_notes(tmp_path):
    got = _paths(_collect(_tree(tmp_path)))
    assert got == REAL_NOTES, (
        "distinct collected paths must be exactly %r; got %r"
        % (sorted(REAL_NOTES), sorted(got))
    )


def test_b3_default_ctor_same_result(tmp_path):
    """Same contract through the DEFAULT constructor (no max_items argument).

    The reference tree yields 10 headings at most, under the documented default
    cap of 20, so the cap cannot mask or manufacture a pruning result here.
    """
    got = _paths(NotesCollector().collect(_tree(tmp_path)))
    assert got == REAL_NOTES, sorted(got)


# ===========================================================================
# Behavior 4 -- Pruning happens DURING traversal: noise files are never OPENED.
# Two-sided detector: it must also FIRE on the real notes, so an implementation
# that reads through some other API cannot pass trivially.
# ===========================================================================
def test_b4_noise_files_are_never_read(tmp_path, monkeypatch):
    ws = _tree(tmp_path)
    real_read_text = Path.read_text
    seen_raw: list[str] = []

    def recording_read_text(self, *args, **kwargs):
        seen_raw.append(str(self))
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", recording_read_text)
    try:
        signals = _collect(ws)
    finally:
        monkeypatch.undo()

    ws_resolved = ws.resolve()
    read_rel: set[str] = set()
    for raw in seen_raw:
        try:
            read_rel.add(Path(raw).resolve().relative_to(ws_resolved).as_posix())
        except ValueError:
            continue  # a read outside the workspace is none of this test's business

    # (a) the detector FIRED -- without this half the guard is fail-open.
    assert REAL_NOTES <= read_rel, (
        "the Path.read_text instrumentation recorded no read for one of the real "
        "notes (%r), so a zero-noise-reads result would be meaningless; recorded %r"
        % (sorted(REAL_NOTES - read_rel), sorted(read_rel))
    )
    # (b) zero reads under any pruned directory -- a cosmetic post-filter, which
    # still opens all 8 noise files to parse their headings, fails here.
    bad = _offenders(read_rel)
    assert bad == [], (
        "noise files were OPENED and parsed before being discarded (path, segment): "
        "%r -- the walk must prune, not filter" % (bad,)
    )
    # Sanity: the same call still produced the two real notes.
    assert _paths(signals) == REAL_NOTES, sorted(_paths(signals))


# ===========================================================================
# Behavior 5 -- Hidden directories are pruned at ANY depth, whether or not they
# are skip-set members (so a fix that only checks the notes dir's immediate
# children fails).
# ===========================================================================
def test_b5_hidden_and_nested_noise_pruned_at_depth(tmp_path):
    got = _paths(_collect(_tree(tmp_path)))
    assert "docs/.hidden/h.md" not in got, (
        "`.hidden` is hidden but NOT a skip-set member; it must still be pruned"
    )
    assert "docs/sub/node_modules/deep.md" not in got, (
        "a skip-set dir two levels below the notes dir must be pruned, not only "
        "an immediate child"
    )
    assert "docs/.git/g.md" not in got
    assert "docs/.venv/lib/v.md" not in got
    # ...while legitimate nesting still recurses.
    assert "docs/sub/deep/nested.md" in got


def test_b5_hidden_and_noise_three_levels_deep_pruned(tmp_path):
    ws = _tree(tmp_path)
    _write(ws, "docs/sub/deep/.secret/s.md", "secret")
    _write(ws, "docs/sub/deep/build/gen.md", "generated")
    got = _paths(_collect(ws))
    assert got == REAL_NOTES, (
        "a hidden dir and a skip-set dir three levels deep must both be pruned; "
        "got %r" % (sorted(got),)
    )


# ===========================================================================
# Behavior 6 -- Determinism survives (row #92 guarantee): two consecutive calls
# are identical, and surviving paths keep today's ascending `sorted(...)` order.
# ===========================================================================
def test_b6_two_calls_are_identical_and_paths_ascending(tmp_path):
    ws = _tree(tmp_path)
    first = [(s.path, s.summary) for s in _collect(ws)]
    second = [(s.path, s.summary) for s in _collect(ws)]
    assert first == second, (
        "two collect() calls on an unchanged tree must be identical; %r != %r"
        % (first, second)
    )
    distinct: list[str] = []
    for p, _summary in first:
        if p not in distinct:
            distinct.append(p or "")
    assert distinct == sorted(distinct), (
        "the sequence of distinct paths must stay ascending (unchanged sorted() "
        "emission order); got %r" % (distinct,)
    )


def test_b6_ordering_unchanged_on_a_noise_free_tree(tmp_path):
    """Regression anchor: on a tree with NO noise, emission order is untouched."""
    _write(tmp_path, "docs/a.md", "A")
    _write(tmp_path, "docs/b.md", "B")
    _write(tmp_path, "docs/sub/c.md", "C")
    ordered = [s.path for s in _collect(tmp_path)]
    assert ordered == ["docs/a.md", "docs/b.md", "docs/sub/c.md"], ordered


# ===========================================================================
# Behavior 7 -- End-to-end through the shipped CLI: the fix is visible at the
# product's front door, not only in a unit call.
# ===========================================================================
def test_b7_cli_signals_kind_note_json_has_no_pruned_paths(tmp_path, capsys):
    ws = _tree(tmp_path)
    paths = _cli_note_paths(ws, capsys)
    bad = _offenders(paths)
    assert bad == [], (
        "`pla signals --kind note --json` still emits notes from pruned subtrees "
        "(path, segment): %r" % (bad,)
    )
    assert REAL_NOTES <= paths, (
        "the CLI must still emit both real notes; got %r" % (sorted(paths),)
    )


# ===========================================================================
# Behavior 8 -- No regression in the committed fixture workspace: its ONE
# notes-style dir (`notes/`, holding only `journal.md`, no subdirectories) must
# be bit-identically unaffected.
# ===========================================================================
def test_b8_committed_fixture_note_signals_unaffected(capsys):
    paths = _cli_note_paths(FIXTURE, capsys)
    assert paths, "the fixture workspace must still surface note signals (non-empty)"
    assert "notes/journal.md" in paths, (
        "the fixture's only notes-dir file must survive the prune; got %r"
        % (sorted(paths),)
    )
    assert _offenders(paths) == [], _offenders(paths)


# ===========================================================================
# Anchors -- this is a traversal fix, so nothing count-coupled may move.
# ===========================================================================
def test_anchor_collector_count_and_version_unchanged():
    assert len(all_collectors()) == 17, (
        "a pruning fix inside one collector must not change the collector count "
        "(README carve-out number); got %d" % len(all_collectors())
    )
    assert __version__ == "0.1.1", "an internal traversal fix must not bump the version"


def test_anchor_all_three_notes_dir_names_still_collected(tmp_path):
    """The `_NOTES_DIRS` vocabulary (notes/journal/docs) is out of scope."""
    _write(tmp_path, "docs/a.md", "A")
    _write(tmp_path, "notes/b.md", "B")
    _write(tmp_path, "journal/c.md", "C")
    got = _paths(_collect(tmp_path))
    assert got == {"docs/a.md", "notes/b.md", "journal/c.md"}, sorted(got)


def test_anchor_max_items_cap_semantics_unchanged(tmp_path):
    body = "\n\n".join("# H%d\n\nbody %d." % (i, i) for i in range(10))
    d = tmp_path / "notes"
    d.mkdir()
    (d / "big.md").write_text(body, encoding="utf-8")
    signals = NotesCollector(max_items=3).collect(tmp_path)
    assert len(signals) == 3, "max_items must still cap the emitted signals"
    assert [s.summary for s in signals] == ["H0", "H1", "H2"], [s.summary for s in signals]


def test_anchor_non_md_and_outside_notes_dirs_still_ignored(tmp_path):
    _write(tmp_path, "README.md", "root readme")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "notes.txt").write_text("# Not markdown\n\nbody\n", encoding="utf-8")
    assert _collect(tmp_path) == [], (
        "markdown outside a notes dir and non-.md files inside one stay ignored"
    )
