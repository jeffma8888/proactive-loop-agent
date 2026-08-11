"""Black-box behavior tests for iteration 37.

Feature under test: a new **L2 perception collector**, ``LargeFileCollector``
(``name == "large_file"``, ``kind == "large_file"``). It is the *repo-hygiene*
companion to the other filesystem collectors: it walks a workspace and emits one
``kind="large_file"`` signal per file whose ``st_size`` is **at or above** a byte
threshold (``min_bytes``, default ``5_000_000``; inclusive ``size >= min_bytes``),
giving the scout an "accidental blob / oversized artifact" perception axis. Each
signal carries ``source="large_file"``, ``kind="large_file"``, ``detail=""``,
``weight=0.6`` (a fixed mid-range hygiene fact), the file's **absolute** path in
``path`` and ``timestamp=None``; its ``summary`` is exactly
``"<relpath>: <human> (large)"`` where ``<relpath>`` is forward-slashed relative
to the workspace root and ``<human>`` renders the raw byte size with SI (decimal)
units at one decimal place (``n>=1_000_000`` -> ``"5.0 MB"``,
``1_000<=n<1_000_000`` -> ``"2.5 KB"``, ``n<1_000`` -> ``"250 B"``). Output is
ordered by **descending byte size**, ties broken by **ascending relpath**, then
capped at ``max_items`` (default 20). It reuses the shared skip set / hidden
pruning (``_SKIP_DIRS`` / ``_is_hidden``) and skips hidden files too. It reads
ONLY ``st_size`` metadata (never opens content), is pure stdlib, deterministic,
offline, and -- like every collector -- degrades to ``[]`` rather than raising.
Additive new ``kind`` -> no version bump; it flows into synthesis via
``by_kind()`` with zero synthesizer change and surfaces through the EXISTING
``pla signals`` inspector.

ISOLATION CONTRACT (honored): these tests are written strictly against the
public contract -- this iteration's spec "Expected Behaviors" (``pm.md``),
``README.md``, and ``SPEC.md`` section 4.1 (the ``collectors`` module contract)
-- and drive ONLY the documented public surface: the PRIMARY black-box entry
point ``pla signals --workspace W [--kind large_file] --json`` (and its human
form) via ``cli.main([...])`` (its observable stdout/stderr/exit code), and the
public collector API ``LargeFileCollector(...).collect(root)`` named by the spec,
plus the ``proactive_loop.collectors`` package import (``LargeFileCollector``,
``all_collectors``), the ``proactive_loop.collectors.large_file`` submodule
import, the ``Collector`` protocol, the ``ContextSignal`` model, and
``proactive_loop.__version__`` / ``pla --version``. **No file under ``src/`` was
read, no engineer/reviewer notes were read, and no ``git diff`` was consulted.**
Signal field names were taken from the public spec + the existing published
tests, never from the implementation. Every test builds its own fresh
``tmp_path`` synthetic workspace (no ``.git`` inside, so no git-based kinds leak);
only Behavior 11 references ``examples/fixture_workspace`` (to assert the
byte-stability guarantee that it carries NO oversized file). Fully offline: zero
network, zero API keys -- ``--provider scripted`` is passed WITHOUT a
``--scripted-responses`` file precisely to prove the inspector builds no
``LLMClient`` (it would fault if it did). Sparse files (``truncate``) give an
exact ``st_size`` with no multi-MB write, so even the default-threshold CLI paths
stay fast and offline.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import proactive_loop
from proactive_loop.cli import main
from proactive_loop.collectors import LargeFileCollector, all_collectors
from proactive_loop.collectors.base import Collector
from proactive_loop.collectors.large_file import (
    LargeFileCollector as LargeFileCollector_direct,
)
from proactive_loop.models import ContextSignal

DEFAULT_MIN_BYTES = 5_000_000
DEFAULT_MAX_ITEMS = 20


# ---------------------------------------------------------------------------
# Helpers -- all black-box: build synthetic tmp workspaces (sparse files for an
# exact st_size with no multi-MB write), drive the CLI / the public collector
# API, read back observable output.
# ---------------------------------------------------------------------------


def _mk(path: Path, size: int, content: bytes | None = None) -> Path:
    """Create *path* (and parents) with exactly *size* bytes.

    Uses a sparse ``truncate`` by default (instant, exact ``st_size``); pass
    *content* to write real bytes instead (e.g. non-UTF-8 bytes)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if content is not None:
        path.write_bytes(content)
    else:
        with open(path, "wb") as fh:
            fh.truncate(size)
    return path


def _relpath(sig) -> str:
    """The forward-slashed relpath carried at the head of the summary."""
    return (sig["summary"] if isinstance(sig, dict) else sig.summary).split(":", 1)[0]


def _run(argv: list[str], capsys) -> tuple[int, str, str]:
    """Invoke the CLI and return (rc, stdout, stderr). Drains capsys first so
    setup output never leaks into the assertion window."""
    capsys.readouterr()
    rc = main(argv)
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def _signals_json(workspace: Path, capsys, *, kind: str | None = "large_file") -> list[dict]:
    """Run `pla signals --workspace W [--kind K] --json` and return the parsed
    `signals` array. `--provider scripted` WITHOUT `--scripted-responses` proves
    the inspector is LLM-free (it would fault building a client otherwise)."""
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
# Behavior 1 -- Threshold hit -> one signal (driven end-to-end through the
#               default-threshold `pla signals` CLI with a real 5 MB file).
# ===========================================================================


def test_b01_threshold_hit_one_signal_via_cli(tmp_path: Path, capsys) -> None:
    _mk(tmp_path / "blob.bin", DEFAULT_MIN_BYTES)  # exactly the default threshold

    sigs = _signals_json(tmp_path, capsys)

    assert len(sigs) == 1, f"exactly one large_file signal expected; got {sigs!r}"
    assert sigs[0]["kind"] == "large_file"
    assert sigs[0]["source"] == "large_file"


# ===========================================================================
# Behavior 2 -- Inclusive boundary: size == min_bytes IS flagged; min_bytes-1
#               is NOT. A workspace whose only file is one byte below -> [].
# ===========================================================================


def test_b02_inclusive_boundary(tmp_path: Path) -> None:
    _mk(tmp_path / "at_threshold.bin", 100)
    _mk(tmp_path / "below.bin", 99)

    sigs = LargeFileCollector(min_bytes=100).collect(tmp_path)

    rels = sorted(_relpath(s) for s in sigs)
    assert rels == ["at_threshold.bin"], (
        f"only the >= threshold file must be flagged (>=, not >); got {rels!r}"
    )


def test_b02_sole_below_threshold_file_yields_empty(tmp_path: Path) -> None:
    _mk(tmp_path / "below.bin", 99)
    assert LargeFileCollector(min_bytes=100).collect(tmp_path) == []


# ===========================================================================
# Behavior 3 -- Fixed signal fields: source/kind == "large_file", detail == "",
#               weight == 0.6 (a fixed, non-decaying hygiene weight).
# ===========================================================================


def test_b03_fixed_fields_via_api(tmp_path: Path) -> None:
    _mk(tmp_path / "big.bin", 500)
    sigs = LargeFileCollector(min_bytes=100).collect(tmp_path)
    assert len(sigs) == 1
    s = sigs[0]
    assert isinstance(s, ContextSignal)
    assert s.source == "large_file"
    assert s.kind == "large_file"
    assert s.detail == ""
    assert s.weight == 0.6


def test_b03_fixed_fields_via_cli(tmp_path: Path, capsys) -> None:
    _mk(tmp_path / "blob.bin", DEFAULT_MIN_BYTES)
    s = _signals_json(tmp_path, capsys)[0]
    assert s["source"] == "large_file"
    assert s["kind"] == "large_file"
    assert s["detail"] == ""
    assert s["weight"] == 0.6


# ===========================================================================
# Behavior 4 -- Deterministic summary "<relpath>: <human> (large)" with a
#               forward-slashed relpath and SI (decimal, 1-dp) human size.
# ===========================================================================


@pytest.mark.parametrize(
    ("size", "expected_human"),
    [
        (250, "250 B"),
        (999, "999 B"),
        (1_000, "1.0 KB"),
        (2_500, "2.5 KB"),
        (999_999, "1000.0 KB"),   # still KB just below the MB rollover
        (1_000_000, "1.0 MB"),
        (5_000_000, "5.0 MB"),
        (12_345_678, "12.3 MB"),
    ],
)
def test_b04_human_size_si_units(tmp_path: Path, size: int, expected_human: str) -> None:
    _mk(tmp_path / "f.bin", size)
    sigs = LargeFileCollector(min_bytes=1).collect(tmp_path)
    assert len(sigs) == 1
    assert sigs[0].summary == f"f.bin: {expected_human} (large)", sigs[0].summary


def test_b04_summary_anchor_root(tmp_path: Path) -> None:
    # Spec concrete anchor: a 5_000_000-byte blob.bin at root.
    _mk(tmp_path / "blob.bin", 5_000_000)
    sigs = LargeFileCollector().collect(tmp_path)  # default min_bytes == 5_000_000
    assert len(sigs) == 1
    assert sigs[0].summary == "blob.bin: 5.0 MB (large)"


def test_b04_summary_anchor_nested_forward_slashed(tmp_path: Path) -> None:
    # Spec concrete anchor: a 5_000_000-byte file at data/blob.bin -> POSIX
    # separators in the relpath on every OS.
    _mk(tmp_path / "data" / "blob.bin", 5_000_000)
    sigs = LargeFileCollector().collect(tmp_path)
    assert len(sigs) == 1
    assert sigs[0].summary == "data/blob.bin: 5.0 MB (large)"
    # Belt-and-suspenders: never a backslash in the relpath portion.
    assert "\\" not in _relpath({"summary": sigs[0].summary})


# ===========================================================================
# Behavior 5 -- Ordering by descending byte size, ties broken by ascending
#               forward-slashed relpath; then truncated to max_items (the
#               LARGEST files survive the cap).
# ===========================================================================


def test_b05_order_desc_size_then_asc_relpath(tmp_path: Path) -> None:
    _mk(tmp_path / "big.bin", 900)
    _mk(tmp_path / "mid.bin", 500)
    _mk(tmp_path / "a.bin", 300)   # size tie with b.bin -> a precedes b
    _mk(tmp_path / "b.bin", 300)

    sigs = LargeFileCollector(min_bytes=100).collect(tmp_path)
    order = [_relpath(s) for s in sigs]
    assert order == ["big.bin", "mid.bin", "a.bin", "b.bin"], order


def test_b05_cap_keeps_largest(tmp_path: Path) -> None:
    # Five distinct sizes 1000..1004; max_items=2 keeps the two LARGEST.
    for i in range(5):
        _mk(tmp_path / f"f{i}.bin", 1000 + i)
    sigs = LargeFileCollector(min_bytes=100, max_items=2).collect(tmp_path)
    assert len(sigs) == 2, f"cap must be exactly max_items=2; got {len(sigs)}"
    assert [_relpath(s) for s in sigs] == ["f4.bin", "f3.bin"], (
        "the two largest files, descending"
    )


# ===========================================================================
# Behavior 6 -- Skip rules: files under a shared skip dir, under any hidden
#               dir, or that are themselves hidden files are NEVER flagged; a
#               sibling in a normal dir IS.
# ===========================================================================


@pytest.mark.parametrize(
    "skipdir", ["node_modules", ".venv", "__pycache__", ".git", ".tox", "dist", "build"]
)
def test_b06_skipped_dir_pruned(tmp_path: Path, skipdir: str) -> None:
    _mk(tmp_path / skipdir / "buried.bin", 500)
    _mk(tmp_path / "normal" / "ok.bin", 500)

    rels = {_relpath(s) for s in LargeFileCollector(min_bytes=100).collect(tmp_path)}
    assert rels == {"normal/ok.bin"}, f"only the normal-dir file may be flagged; got {rels!r}"


def test_b06_hidden_dir_and_hidden_file_pruned(tmp_path: Path) -> None:
    _mk(tmp_path / ".hiddendir" / "buried.bin", 500)  # under a hidden dir
    _mk(tmp_path / ".secret.bin", 500)                # a hidden FILE
    _mk(tmp_path / "visible.bin", 500)                # a normal sibling

    rels = {_relpath(s) for s in LargeFileCollector(min_bytes=100).collect(tmp_path)}
    assert rels == {"visible.bin"}, f"hidden dir/file must be pruned; got {rels!r}"


# ===========================================================================
# Behavior 7 -- the COLLECTOR builds `path` as the file's ABSOLUTE path (non-empty
#               string); the forward-slashed relpath lives only in `summary`;
#               timestamp None. Published through the CLI it is re-spelled
#               workspace-relative at the one `cli._collect` seam (iter 139), so
#               the absoluteness contract below is asserted where it still holds:
#               on the collector, called directly.
# ===========================================================================


def test_b07_path_is_absolute_relpath_in_summary(tmp_path: Path) -> None:
    f = _mk(tmp_path / "data" / "blob.bin", 500)
    sigs = LargeFileCollector(min_bytes=100).collect(tmp_path)
    assert len(sigs) == 1
    s = sigs[0]
    assert isinstance(s.path, str) and s.path, f"path must be a non-empty string: {s.path!r}"
    assert os.path.isabs(s.path), f"path must be absolute: {s.path!r}"
    assert Path(s.path).resolve() == f.resolve(), "path must point at the source file"
    # The relpath is NOT the path field; it is carried in summary, forward-slashed.
    assert s.summary.startswith("data/blob.bin:"), s.summary
    assert s.timestamp is None, f"timestamp must be None; got {s.timestamp!r}"


def test_b07_path_is_workspace_relative_via_cli(tmp_path: Path, capsys) -> None:
    """Through the CLI the same signal is published workspace-relative, not absolute:
    `cli._collect` owns the namespace of every published `path` (iter 139). Still the
    same file -- resolving it against the workspace lands back on it."""
    f = _mk(tmp_path / "blob.bin", DEFAULT_MIN_BYTES)
    s = _signals_json(tmp_path, capsys)[0]
    assert s["path"] == "blob.bin", s["path"]
    assert not os.path.isabs(s["path"])
    assert (tmp_path / s["path"]).resolve() == f.resolve()
    assert s["summary"] == "blob.bin: 5.0 MB (large)"


# ===========================================================================
# Behavior 8 -- Never raises -> degrades to []. Missing root, file-as-root, a
#               vanished/unstattable entry (siblings still emit), and hostile
#               content (zero-byte, non-UTF-8 bytes) never throw.
# ===========================================================================


def test_b08_missing_root_returns_empty(tmp_path: Path) -> None:
    assert LargeFileCollector().collect(tmp_path / "no" / "such" / "dir") == []
    assert LargeFileCollector().collect(Path("/no/such/dir_xyz_qqq_zzz")) == []


def test_b08_file_as_root_returns_empty(tmp_path: Path) -> None:
    f = _mk(tmp_path / "afile.bin", DEFAULT_MIN_BYTES)
    assert LargeFileCollector().collect(f) == []


def test_b08_unstattable_entry_skipped_siblings_emit(tmp_path: Path) -> None:
    # A broken symlink cannot be stat()'d (its target is missing): the collector
    # must skip it (guarded try/except OSError) and still emit its good sibling.
    _mk(tmp_path / "good.bin", 500)
    os.symlink(tmp_path / "does_not_exist_target", tmp_path / "broken.bin")

    sigs = LargeFileCollector(min_bytes=100).collect(tmp_path)  # must NOT raise

    rels = {_relpath(s) for s in sigs}
    assert "good.bin" in rels, "the walk must continue past an unstattable entry"
    assert "broken.bin" not in rels, "an unstattable entry must be silently skipped"


def test_b08_hostile_content_never_raises(tmp_path: Path) -> None:
    # Metadata-only: a zero-byte file and a non-UTF-8-bytes file must never
    # cause an exception (the collector reads st_size, never content).
    _mk(tmp_path / "empty.bin", 0)
    _mk(tmp_path / "binary.bin", 0, content=b"\xff\xfe\x00\x01\x80\x81" * 100)
    _mk(tmp_path / "big_binary.bin", 0, content=b"\x00\xff" * 300)  # 600 bytes, non-UTF-8
    sigs = LargeFileCollector(min_bytes=100).collect(tmp_path)  # must NOT raise
    rels = {_relpath(s) for s in sigs}
    # The 600-byte non-UTF-8 file IS flagged (size-only decision, no decode).
    assert "big_binary.bin" in rels
    assert "empty.bin" not in rels  # zero bytes < threshold


# ===========================================================================
# Behavior 9 -- Constructor-overridable knobs (dataclass fields) + all_collectors()
#               registers the zero-argument instance with the defaults.
# ===========================================================================


def test_b09_default_knobs() -> None:
    c = LargeFileCollector()
    assert c.name == "large_file"
    assert c.min_bytes == DEFAULT_MIN_BYTES
    assert c.max_items == DEFAULT_MAX_ITEMS


def test_b09_min_bytes_override(tmp_path: Path) -> None:
    _mk(tmp_path / "f.bin", 100)
    assert len(LargeFileCollector(min_bytes=100).collect(tmp_path)) == 1
    assert LargeFileCollector(min_bytes=101).collect(tmp_path) == []


def test_b09_max_items_override(tmp_path: Path) -> None:
    for i in range(5):
        _mk(tmp_path / f"f{i}.bin", 200 + i)
    assert len(LargeFileCollector(min_bytes=100, max_items=2).collect(tmp_path)) == 2


def test_b09_registry_uses_zero_arg_defaults() -> None:
    matches = [c for c in all_collectors() if c.name == "large_file"]
    assert len(matches) == 1
    assert matches[0].min_bytes == DEFAULT_MIN_BYTES
    assert matches[0].max_items == DEFAULT_MAX_ITEMS


# ===========================================================================
# Behavior 10 -- Registered + wired: exactly one large_file collector, exported
#                from the package and importable as a submodule; bare
#                `pla signals` includes large_file alongside other kinds; and an
#                oversized-free workspace degrades (json [], human marker, rc 0).
# ===========================================================================


def test_b10_registered_and_exported() -> None:
    matches = [c for c in all_collectors() if c.name == "large_file"]
    assert len(matches) == 1, "exactly one large_file collector in the registry"
    assert type(matches[0]) is LargeFileCollector
    assert LargeFileCollector is LargeFileCollector_direct
    assert isinstance(LargeFileCollector(), Collector)


def test_b10_bare_signals_includes_large_file_alongside_others(tmp_path: Path, capsys) -> None:
    _mk(tmp_path / "blob.bin", DEFAULT_MIN_BYTES)  # oversized -> large_file
    (tmp_path / "mod.py").write_text("def f():\n    return 1\n")  # a normal source file

    sigs = _signals_json(tmp_path, capsys, kind=None)  # NO --kind: all collectors

    kinds = {s["kind"] for s in sigs}
    assert "large_file" in kinds, f"bare signals must include large_file; kinds={kinds!r}"
    assert len(kinds) >= 2, f"large_file must appear ALONGSIDE other kinds; kinds={kinds!r}"


def test_b10_no_oversized_file_degrades_json(tmp_path: Path, capsys) -> None:
    (tmp_path / "small.txt").write_text("tiny")
    argv = ["signals", "--workspace", str(tmp_path), "--provider", "scripted",
            "--kind", "large_file", "--json"]
    rc, out, err = _run(argv, capsys)
    assert rc == 0, err
    doc = json.loads(out)
    assert doc["signals"] == [], f"no oversized file -> []; got {doc!r}"


def test_b10_no_oversized_file_degrades_human(tmp_path: Path, capsys) -> None:
    (tmp_path / "small.txt").write_text("tiny")
    rc, out, err = _run(
        ["signals", "--workspace", str(tmp_path), "--provider", "scripted",
         "--kind", "large_file"],
        capsys,
    )
    assert rc == 0, err
    assert "(no signals collected)" in out, f"expected empty marker; got:\n{out}"


def test_b10_signals_human_render_surfaces_kind(tmp_path: Path, capsys) -> None:
    _mk(tmp_path / "blob.bin", DEFAULT_MIN_BYTES)
    rc, out, err = _run(
        ["signals", "--workspace", str(tmp_path), "--provider", "scripted",
         "--kind", "large_file"],
        capsys,
    )
    assert rc == 0, f"signals must exit 0; stderr={err!r}"
    assert "## large_file (1)" in out, f"missing large_file group header; got:\n{out}"
    assert "blob.bin: 5.0 MB (large)" in out, f"missing summary text; got:\n{out}"


# ===========================================================================
# Behavior 11 -- Backward compatible / byte-stable: the demo fixture carries NO
#                oversized file (so `make demo` output is unchanged), and the
#                additive collector does NOT bump __version__ / `pla --version`.
# ===========================================================================


def test_b11_demo_fixture_has_no_large_file_signals(tmp_path: Path, capsys) -> None:
    fixture = Path(__file__).resolve().parents[1] / "examples" / "fixture_workspace"
    assert fixture.is_dir(), fixture
    # Default threshold (what `make demo` uses): the largest fixture file is ~2 KB.
    sigs = _signals_json(fixture, capsys)
    assert sigs == [], f"demo fixture must have no oversized file; got {sigs!r}"


def test_b11_no_version_bump(capsys) -> None:
    assert proactive_loop.__version__ == "0.1.1", proactive_loop.__version__
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0, "`pla --version` must exit 0"
    out = capsys.readouterr().out
    assert "pla 0.1.1" in out, f"`pla --version` must print 'pla 0.1.1'; got {out!r}"
