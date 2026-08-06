"""Black-box behavior tests for state-dir iteration 99 (ships as commit-sequence
**factory iter 106**): a PRE-READ BYTE-SIZE CAP in the three whole-tree text
collectors.

``TodoCollector``, ``MergeConflictCollector`` and ``SyntaxErrorCollector`` each
gain a ``max_read_bytes: int`` dataclass field whose default is the single
shared threshold ``proactive_loop.collectors.large_file.LARGE_FILE_MIN_BYTES``
(5,000,000). Before decoding a candidate file each collector stats it and SKIPS
any file whose ``st_size`` is STRICTLY greater than the cap, so one scan can no
longer pull an unbounded blob into memory up to three times. The perception
surface loses no FILE: ``LargeFileCollector`` reports every file at or above the
same threshold from ``st_size`` alone, so skipped-here implies reported-there
(the ranges overlap by exactly one size, at the boundary).

ISOLATION CONTRACT (honored): every assertion here is written strictly against
THIS iteration's public contract --- the spec's "Expected Behaviors" (``pm.md``)
--- and drives ONLY the documented public surface: the public collector
constructors and their ``collect(root)`` method, the public module constant
``LARGE_FILE_MIN_BYTES``, the registry helper ``all_collectors()``, observable
``ContextSignal`` fields, and runtime introspection (``dataclasses.fields``,
``__doc__``). **No file under ``src/`` was read, no engineer or reviewer note
was consulted, and no ``git diff`` was inspected** to author these assertions.
Every test is fully offline (zero network, zero API keys) and runs on
``tmp_path`` fixtures plus the bundled ``examples/fixture_workspace``. Over-cap
cases LOWER ``max_read_bytes`` to tens/hundreds of bytes rather than writing
megabytes; the one default-threshold case uses a sparse ``truncate`` for an
exact ``st_size`` (the technique ``tests/test_iter37_behavior.py`` already
uses), so no test writes 5 MB to disk.

DELIBERATE OMISSION: this file asserts NO collector-count and NO CLI-verb-count
literal. The spec's Out of Scope forbids changing either, and the operator's
learnings record a 41-site count cascade that has already cost two iterations;
adding a 27th hardcoded ``== 16`` would widen it for zero oracle value here.
Registry coverage is asserted by NAME MEMBERSHIP instead.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from proactive_loop.collectors import (
    LargeFileCollector,
    MergeConflictCollector,
    SyntaxErrorCollector,
    TodoCollector,
    all_collectors,
)
from proactive_loop.collectors import merge_conflict as merge_conflict_mod
from proactive_loop.collectors import syntax_error as syntax_error_mod
from proactive_loop.collectors import todos as todos_mod
from proactive_loop.collectors.large_file import LARGE_FILE_MIN_BYTES

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "examples" / "fixture_workspace"

# The spec-declared shared threshold, encoded as the tester's ground fact rather
# than imported, so a silent change to the constant is caught (behavior 1).
EXPECTED_MIN_BYTES = 5_000_000

# The three capped collectors, paired with their module (for docstring checks).
CAPPED = (
    (TodoCollector, todos_mod, "todos"),
    (MergeConflictCollector, merge_conflict_mod, "merge_conflict"),
    (SyntaxErrorCollector, syntax_error_mod, "syntax_error"),
)

# One ``.py`` payload that trips ALL THREE collectors at once:
#   * ``# TODO:`` comment      -> TodoCollector
#   * <<<<<<< / >>>>>>> markers -> MergeConflictCollector (N == 2)
#   * the markers + ``def f(:`` are invalid Python -> SyntaxErrorCollector
# Using one payload proves a skip is caused by the SIZE CAP, not by content:
# the identical bytes are detected when the same file is under the cap.
TRIP = (
    "# TODO: trip every collector\n"
    "<<<<<<< HEAD\n"
    "def f(:\n"
    "=======\n"
    "ok = 1\n"
    ">>>>>>> feature\n"
)


# ---------------------------------------------------------------------------
# Helpers -- black-box: build synthetic tmp workspaces, drive the public
# collector API, read back observable ContextSignal fields.
# ---------------------------------------------------------------------------


def _write(path: Path, content: str = TRIP) -> Path:
    """Create *path* (and parents) with text content (default: the TRIP payload)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _write_exact(path: Path, size: int, content: str = TRIP) -> Path:
    """Create *path* with EXACTLY *size* bytes: *content* then newline padding.

    Newlines are inert for all three collectors (they add no todo, no conflict
    marker, and keep an invalid module invalid), so padding cannot change WHICH
    signals the file would produce -- only its ``st_size``."""
    raw = content.encode("utf-8")
    assert len(raw) <= size, f"content ({len(raw)}B) does not fit in size={size}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw + b"\n" * (size - len(raw)))
    assert path.stat().st_size == size
    return path


def _write_sparse(path: Path, size: int, content: str = TRIP) -> Path:
    """Create *path* with real *content* at the head and an exact ``st_size`` of
    *size*, via a sparse ``truncate`` -- instant, no multi-MB write."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(content.encode("utf-8"))
        fh.truncate(size)
    assert path.stat().st_size == size
    return path


def _relpaths(sigs) -> set[str]:
    """The relpath each of the three CAPPED collectors points at.
    ``merge_conflict``/``syntax_error`` carry ``path=<relpath>``; ``todos``
    carries ``path=<relpath>:<lineno>``."""
    return {(s.path or "").split(":", 1)[0] for s in sigs}


def _lf_relpaths(sigs) -> set[str]:
    """The relpath each ``large_file`` signal points at. NOTE the deliberate
    asymmetry, confirmed against ``tests/test_iter37_behavior.py``:
    ``large_file`` carries an ABSOLUTE ``path`` and puts the relpath at the head
    of its ``summary``, so it needs its own accessor."""
    return {(s.summary or "").split(":", 1)[0] for s in sigs}


def _fingerprint(sigs) -> list[tuple[str, str, str, float]]:
    """A byte-identical comparison key: (kind, summary, path, weight) in emission
    order. Two runs with the same fingerprint emitted the same signals."""
    return [(s.kind, s.summary, s.path or "", s.weight) for s in sigs]


# ===========================================================================
# Behavior 1 -- `LARGE_FILE_MIN_BYTES` is a public module-level constant equal
#               to 5,000,000, and it is the SINGLE home of the threshold:
#               LargeFileCollector's `min_bytes` default is sourced from it.
# ===========================================================================


def test_b01_large_file_min_bytes_is_public_constant() -> None:
    assert isinstance(LARGE_FILE_MIN_BYTES, int), (
        f"LARGE_FILE_MIN_BYTES must be an int; got {type(LARGE_FILE_MIN_BYTES)!r}"
    )
    assert LARGE_FILE_MIN_BYTES == EXPECTED_MIN_BYTES, (
        f"the shared threshold must stay 5_000_000; got {LARGE_FILE_MIN_BYTES}"
    )


def test_b01_large_file_default_sourced_from_constant() -> None:
    assert LargeFileCollector().min_bytes == LARGE_FILE_MIN_BYTES, (
        "LargeFileCollector().min_bytes must equal the shared constant"
    )
    field = {f.name: f for f in dataclasses.fields(LargeFileCollector)}["min_bytes"]
    assert field.default == LARGE_FILE_MIN_BYTES, (
        f"the dataclass DEFAULT itself must be the constant; got {field.default!r}"
    )


# ===========================================================================
# Behavior 2 -- Each of the three text collectors exposes a `max_read_bytes: int`
#               dataclass field defaulting to LARGE_FILE_MIN_BYTES; all three
#               still construct with NO arguments, so every existing call site
#               (including `all_collectors()`) is unchanged.
# ===========================================================================


@pytest.mark.parametrize(("cls", "_mod", "name"), CAPPED, ids=[c[2] for c in CAPPED])
def test_b02_max_read_bytes_field_default(cls, _mod, name: str) -> None:
    fields = {f.name: f for f in dataclasses.fields(cls)}
    assert "max_read_bytes" in fields, (
        f"{cls.__name__} must expose a max_read_bytes dataclass field; "
        f"got fields {sorted(fields)}"
    )
    field = fields["max_read_bytes"]
    assert field.default == LARGE_FILE_MIN_BYTES, (
        f"{cls.__name__}.max_read_bytes default must equal LARGE_FILE_MIN_BYTES "
        f"({LARGE_FILE_MIN_BYTES}); got {field.default!r}"
    )
    assert field.type in ("int", int), (
        f"{cls.__name__}.max_read_bytes must be annotated int; got {field.type!r}"
    )


@pytest.mark.parametrize(("cls", "_mod", "name"), CAPPED, ids=[c[2] for c in CAPPED])
def test_b02_zero_arg_construction_and_instance_default(cls, _mod, name: str) -> None:
    inst = cls()  # must NOT require the new field
    assert inst.name == name
    assert inst.max_read_bytes == LARGE_FILE_MIN_BYTES
    assert isinstance(inst.max_read_bytes, int)


@pytest.mark.parametrize(("cls", "_mod", "name"), CAPPED, ids=[c[2] for c in CAPPED])
def test_b02_registry_instances_carry_the_default(cls, _mod, name: str) -> None:
    matches = [c for c in all_collectors() if c.name == name]
    assert len(matches) == 1, f"exactly one {name} collector in the registry"
    assert type(matches[0]) is cls
    assert matches[0].max_read_bytes == LARGE_FILE_MIN_BYTES, (
        f"the registered zero-arg {name} instance must carry the default cap"
    )


@pytest.mark.parametrize(("cls", "_mod", "name"), CAPPED, ids=[c[2] for c in CAPPED])
def test_b02_cap_is_constructor_overridable(cls, _mod, name: str) -> None:
    assert cls(max_read_bytes=64).max_read_bytes == 64


# ===========================================================================
# Behaviors 3/4/5 -- Over-cap files are SKIPPED and the walk CONTINUES: a tree
#   holding big.py (st_size > cap) and small.py (under cap), both carrying the
#   identical trigger payload, yields signals for small.py ONLY. The control
#   (same tree, cap raised) reports BOTH, proving content is not the cause.
# ===========================================================================


def _two_file_tree(root: Path) -> None:
    _write_exact(root / "big.py", 4096)
    _write(root / "small.py")


@pytest.mark.parametrize(
    ("cls", "name"),
    [(TodoCollector, "todos"), (MergeConflictCollector, "merge_conflict"),
     (SyntaxErrorCollector, "syntax_error")],
    ids=["b03_todos", "b04_merge_conflict", "b05_syntax_error"],
)
def test_b03_b04_b05_over_cap_file_skipped_walk_continues(
    cls, name: str, tmp_path: Path
) -> None:
    _two_file_tree(tmp_path)

    sigs = cls(max_read_bytes=1024).collect(tmp_path)

    rels = _relpaths(sigs)
    assert "small.py" in rels, (
        f"{name}: the under-cap file must still be reported (the walk must "
        f"continue past a skipped file); got {[s.summary for s in sigs]!r}"
    )
    assert "big.py" not in rels, (
        f"{name}: no signal may name the over-cap file; got "
        f"{[s.summary for s in sigs]!r}"
    )
    assert not any("big.py" in (s.summary or "") for s in sigs), (
        f"{name}: 'big.py' must not appear in any summary either"
    )
    assert all(s.source == name for s in sigs)


@pytest.mark.parametrize(
    ("cls", "name"),
    [(TodoCollector, "todos"), (MergeConflictCollector, "merge_conflict"),
     (SyntaxErrorCollector, "syntax_error")],
    ids=["b03_todos", "b04_merge_conflict", "b05_syntax_error"],
)
def test_b03_b04_b05_control_raised_cap_reports_both(
    cls, name: str, tmp_path: Path
) -> None:
    """CONTROL for the three skip tests: the identical tree with a cap above both
    file sizes reports BOTH files, so the skip above is caused by SIZE, not by
    the payload or the filename."""
    _two_file_tree(tmp_path)

    rels = _relpaths(cls(max_read_bytes=1_000_000).collect(tmp_path))

    assert {"big.py", "small.py"} <= rels, (
        f"{name}: with the cap raised above both sizes BOTH files must be "
        f"reported; got {sorted(rels)}"
    )


# ===========================================================================
# Behavior 6 -- NO READ HAPPENS (the real perf assertion): with `Path.read_text`
#   counted, each collector performs ZERO read_text calls targeting the over-cap
#   file, while still reading the under-cap file exactly once.
# ===========================================================================


@pytest.mark.parametrize(
    ("cls", "name"),
    [(TodoCollector, "todos"), (MergeConflictCollector, "merge_conflict"),
     (SyntaxErrorCollector, "syntax_error")],
    ids=["todos", "merge_conflict", "syntax_error"],
)
def test_b06_over_cap_file_is_never_read(
    cls, name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _two_file_tree(tmp_path)

    reads: list[str] = []
    real_read_text = Path.read_text

    def _counting_read_text(self: Path, *args, **kwargs):  # type: ignore[no-untyped-def]
        reads.append(self.name)
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", _counting_read_text)
    sigs = cls(max_read_bytes=1024).collect(tmp_path)
    monkeypatch.undo()

    assert reads.count("big.py") == 0, (
        f"{name}: the over-cap file must NEVER be decoded; read_text targets "
        f"were {reads!r}"
    )
    assert reads.count("small.py") == 1, (
        f"{name}: the under-cap file must be read exactly once; read_text "
        f"targets were {reads!r}"
    )
    assert "small.py" in _relpaths(sigs)


# ===========================================================================
# Behavior 7 -- Boundary is STRICTLY greater: st_size == max_read_bytes is READ
#   and reported; st_size == max_read_bytes + 1 is skipped. (Deliberate mirror
#   of LargeFileCollector's INCLUSIVE `>=`, so at exactly the threshold a file
#   is BOTH read here AND flagged there -- the ranges overlap, leaving no gap.)
# ===========================================================================


CAP = 512


@pytest.mark.parametrize(
    ("cls", "name"),
    [(TodoCollector, "todos"), (MergeConflictCollector, "merge_conflict"),
     (SyntaxErrorCollector, "syntax_error")],
    ids=["todos", "merge_conflict", "syntax_error"],
)
def test_b07_boundary_exact_is_read_over_by_one_is_skipped(
    cls, name: str, tmp_path: Path
) -> None:
    _write_exact(tmp_path / "exact.py", CAP)
    _write_exact(tmp_path / "over.py", CAP + 1)

    rels = _relpaths(cls(max_read_bytes=CAP).collect(tmp_path))

    assert "exact.py" in rels, (
        f"{name}: a file of size EXACTLY max_read_bytes ({CAP}) must be read "
        f"and reported (the guard is strictly greater); got {sorted(rels)}"
    )
    assert "over.py" not in rels, (
        f"{name}: a file of size max_read_bytes + 1 ({CAP + 1}) must be skipped; "
        f"got {sorted(rels)}"
    )


def test_b07_boundary_overlaps_large_file_inclusive_threshold(tmp_path: Path) -> None:
    """At EXACTLY the shared threshold both sides fire: the text collectors still
    read the file AND LargeFileCollector still flags it (`size >= min_bytes`), so
    the two ranges overlap by one size and no size falls in a gap."""
    _write_sparse(tmp_path / "edge.py", LARGE_FILE_MIN_BYTES, content="x = 1\n")

    flagged = LargeFileCollector().collect(tmp_path)
    assert _lf_relpaths(flagged) == {"edge.py"}, (
        "LargeFileCollector's threshold is inclusive, so a file of size exactly "
        f"LARGE_FILE_MIN_BYTES must be flagged; got {[s.summary for s in flagged]!r}"
    )
    # ...and the text collectors do NOT skip it at that exact size: proven by the
    # boundary test above at a lowered cap (identical `>` predicate).


# ===========================================================================
# Behavior 8 -- Composition invariant at the DEFAULTS: an oversized file yields
#   NO signal from any of the three text collectors, and EXACTLY ONE
#   kind="large_file" signal from LargeFileCollector. Skipped-here implies
#   reported-there, so the perception surface loses no FILE.
# ===========================================================================


def test_b08_oversized_file_invisible_to_text_collectors_at_defaults(
    tmp_path: Path,
) -> None:
    _write_sparse(tmp_path / "huge.py", LARGE_FILE_MIN_BYTES + 1)

    for cls, _mod, name in CAPPED:
        sigs = cls().collect(tmp_path)  # DEFAULT settings, no override
        assert sigs == [], (
            f"{name} at its default cap must emit nothing for a file of size "
            f"LARGE_FILE_MIN_BYTES + 1; got {[s.summary for s in sigs]!r}"
        )


def test_b08_oversized_file_is_reported_by_large_file(tmp_path: Path) -> None:
    _write_sparse(tmp_path / "huge.py", LARGE_FILE_MIN_BYTES + 1)

    sigs = LargeFileCollector().collect(tmp_path)

    assert len(sigs) == 1, (
        f"exactly one large_file signal expected; got {[s.summary for s in sigs]!r}"
    )
    assert sigs[0].kind == "large_file"
    assert sigs[0].source == "large_file"
    assert _lf_relpaths(sigs) == {"huge.py"}


def test_b08_skipped_here_implies_reported_there(tmp_path: Path) -> None:
    """The invariant stated as one assertion: the SET of files the text
    collectors skip for being oversized is a SUBSET of the set LargeFileCollector
    reports."""
    _write_sparse(tmp_path / "huge.py", LARGE_FILE_MIN_BYTES + 1)
    _write(tmp_path / "small.py")

    reported_by_large_file = _lf_relpaths(LargeFileCollector().collect(tmp_path))
    for cls, _mod, name in CAPPED:
        seen = _relpaths(cls().collect(tmp_path))
        skipped = {"huge.py"} - seen
        assert skipped <= reported_by_large_file, (
            f"{name} skipped {sorted(skipped)} but large_file did not report it "
            f"(it reported {sorted(reported_by_large_file)}) -- that would be a "
            "blind spot"
        )
        assert "small.py" in seen, f"{name} must still report the ordinary file"


# ===========================================================================
# Behavior 9 -- Never-raise contract preserved: a candidate whose stat() raises
#   OSError (broken symlink, deleted mid-walk) is silently skipped and the
#   collector still returns signals for the rest of the tree.
# ===========================================================================


@pytest.mark.parametrize(
    ("cls", "name"),
    [(TodoCollector, "todos"), (MergeConflictCollector, "merge_conflict"),
     (SyntaxErrorCollector, "syntax_error")],
    ids=["todos", "merge_conflict", "syntax_error"],
)
def test_b09_broken_symlink_skipped_siblings_survive(
    cls, name: str, tmp_path: Path
) -> None:
    _write(tmp_path / "good.py")
    (tmp_path / "broken.py").symlink_to(tmp_path / "nonexistent_target.py")

    sigs = cls().collect(tmp_path)  # must NOT raise

    rels = _relpaths(sigs)
    assert "good.py" in rels, (
        f"{name}: the walk must continue past an unstattable entry; got "
        f"{sorted(rels)}"
    )
    assert "broken.py" not in rels, (
        f"{name}: a broken symlink must be silently skipped; got {sorted(rels)}"
    )


@pytest.mark.parametrize(
    ("cls", "name"),
    [(TodoCollector, "todos"), (MergeConflictCollector, "merge_conflict"),
     (SyntaxErrorCollector, "syntax_error")],
    ids=["todos", "merge_conflict", "syntax_error"],
)
def test_b09_injected_stat_oserror_skipped_siblings_survive(
    cls, name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Deterministic injection: stat() raises EIO for exactly one candidate (the
    'deleted mid-walk' / unreadable-inode case). That file is skipped, nothing
    propagates, and every sibling is still reported."""
    _write(tmp_path / "boom.py")
    _write(tmp_path / "good.py")

    real_stat = Path.stat

    def _flaky_stat(self: Path, *args, **kwargs):  # type: ignore[no-untyped-def]
        if self.name == "boom.py":
            raise OSError(5, "injected I/O error")
        return real_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", _flaky_stat)
    try:
        sigs = cls().collect(tmp_path)  # must NOT raise
    finally:
        monkeypatch.undo()

    rels = _relpaths(sigs)
    assert "good.py" in rels, (
        f"{name}: siblings must survive a per-file stat() OSError; got "
        f"{sorted(rels)}"
    )
    assert "boom.py" not in rels, (
        f"{name}: the unstattable file must be skipped, not reported; got "
        f"{sorted(rels)}"
    )


# ===========================================================================
# Behavior 10 -- No regression for ordinary trees: where every file is under the
#   cap the three collectors emit BYTE-IDENTICAL signals (same summaries, same
#   paths, same order) as with an effectively-infinite cap, and `max_items`
#   still caps as before.
# ===========================================================================


NO_CAP = 10**12


@pytest.mark.parametrize(
    ("cls", "name"),
    [(TodoCollector, "todos"), (MergeConflictCollector, "merge_conflict"),
     (SyntaxErrorCollector, "syntax_error")],
    ids=["todos", "merge_conflict", "syntax_error"],
)
def test_b10_default_cap_is_inert_on_the_bundled_fixture(cls, name: str) -> None:
    assert FIXTURE.is_dir(), f"bundled fixture workspace missing: {FIXTURE}"

    default = _fingerprint(cls().collect(FIXTURE))
    uncapped = _fingerprint(cls(max_read_bytes=NO_CAP).collect(FIXTURE))

    assert default == uncapped, (
        f"{name}: on a tree with no oversized file the default cap must change "
        f"NOTHING; default={default!r} uncapped={uncapped!r}"
    )


@pytest.mark.parametrize(
    ("cls", "name"),
    [(TodoCollector, "todos"), (MergeConflictCollector, "merge_conflict"),
     (SyntaxErrorCollector, "syntax_error")],
    ids=["todos", "merge_conflict", "syntax_error"],
)
def test_b10_default_cap_is_inert_on_a_synthetic_tree(
    cls, name: str, tmp_path: Path
) -> None:
    for sub in ("a.py", "b.py", "pkg/c.py"):
        _write(tmp_path / sub)

    default = _fingerprint(cls().collect(tmp_path))
    uncapped = _fingerprint(cls(max_read_bytes=NO_CAP).collect(tmp_path))

    assert default == uncapped, (
        f"{name}: capped and uncapped output must be identical (order included) "
        f"for an all-small tree; default={default!r} uncapped={uncapped!r}"
    )
    assert len(default) >= 3, (
        f"{name}: the fixture must actually produce signals, else this test is "
        f"vacuous; got {default!r}"
    )


def test_b10_max_items_cap_still_applies_alongside_the_read_cap(
    tmp_path: Path,
) -> None:
    for sub in ("a.py", "b.py", "c.py", "d.py"):
        _write(tmp_path / sub)

    for cls, _mod, name in CAPPED:
        capped = cls(max_items=2).collect(tmp_path)
        assert len(capped) == 2, (
            f"{name}: max_items must still cap emission independently of the "
            f"read cap; got {len(capped)} signals"
        )


# ===========================================================================
# Acceptance-criteria check -- the documented composition property is discoverable
# at runtime (`help()`), so a reader learns WHY the cap is not a blind spot.
# ===========================================================================


@pytest.mark.parametrize(("cls", "mod", "name"), CAPPED, ids=[c[2] for c in CAPPED])
def test_docstring_documents_composition_with_large_file(cls, mod, name: str) -> None:
    text = f"{mod.__doc__ or ''}\n{cls.__doc__ or ''}"
    assert "large_file" in text, (
        f"{name}: the module or class docstring must name large_file, stating the "
        "composition property (skipped-here implies reported-there) that makes "
        "this cap safe"
    )
