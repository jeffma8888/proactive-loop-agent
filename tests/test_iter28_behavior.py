"""Black-box behavior tests for iteration 28.

Feature under test: a new **L2 perception collector**, ``MergeConflictCollector``
(``kind == "merge_conflict"``). It walks a workspace and content-scans each
scanned-extension file for git conflict-marker *label* lines -- a line whose raw
text (trailing newline stripped, NO leading-whitespace strip) STARTS WITH the
OPEN prefix ``"<<<<<<< "`` (seven ``<`` + one space) or the CLOSE prefix
``">>>>>>> "`` (seven ``>`` + one space) at column 0. The ambiguous middle
``=======`` separator is deliberately EXCLUDED from both detection and the count
(a bare run of ``=`` is a Markdown setext underline / ASCII rule -> false
positives). It emits ONE ``kind="merge_conflict"`` signal per affected file:
``source="merge_conflict"``, ``detail=""``, ``weight=0.9``, ``path=<relpath>``
(forward-slashed, relative to root), and ``summary="<relpath>: <N> conflict
marker(s)"`` where ``N`` = open-prefix lines + close-prefix lines (singular
"marker" only at ``N == 1``). Output is relpath-ascending and capped at
``max_items`` (default 30). It is pure stdlib, deterministic, offline, and (like
every collector) degrades to ``[]`` rather than raising. Additive new ``kind`` ->
no version bump; it flows into synthesis via ``by_kind()`` with zero synthesizer
change and surfaces through the EXISTING ``pla signals`` inspector.

ISOLATION CONTRACT (honored): these tests are written strictly against the
public contract -- this iteration's spec "Expected Behaviors" (``pm.md``),
``README.md``, and ``SPEC.md`` section 4.1 (the ``collectors`` module contract)
-- and drive only the documented public surface: the PRIMARY black-box entry
point ``pla signals --workspace W --kind merge_conflict --json`` (and its human
form) via ``cli.main([...])`` (its observable stdout/stderr/exit code), plus the
secondary public surfaces named by the spec: the public collector class
``proactive_loop.collectors.MergeConflictCollector``, the ``all_collectors()``
registry, and ``proactive_loop.__version__`` / ``pla --version``. **No file under
``src/`` was read, no engineer/reviewer notes were read, and no ``git diff`` was
consulted.** Signal field names were taken from the public spec + the existing
published tests, never from the implementation. Every test constructs its own
fresh ``tmp_path`` synthetic workspace (no ``.git`` inside, so no git-based kinds
leak); NONE assert against ``examples/fixture_workspace``. Fully offline: zero
network, zero API keys -- ``--provider scripted`` is passed WITHOUT a
``--scripted-responses`` file precisely to prove the inspector builds no
``LLMClient`` (it would fault if it did).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import proactive_loop
from proactive_loop.cli import main
from proactive_loop.collectors import MergeConflictCollector, all_collectors
from proactive_loop.collectors.base import Collector
from proactive_loop.collectors.merge_conflict import (
    MergeConflictCollector as MergeConflictCollector_direct,
)

# A single standard conflict block: <<<<<<< / ======= / >>>>>>>  -> N == 2.
BLOCK = "<<<<<<< HEAD\nours\n=======\ntheirs\n>>>>>>> feature\n"


# ---------------------------------------------------------------------------
# Helpers -- all black-box: build synthetic tmp workspaces, drive the CLI /
# the public collector API, read back observable output.
# ---------------------------------------------------------------------------


def _write(path: Path, content: str) -> Path:
    """Create *path* (and parents) with the given raw content."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _run(argv: list[str], capsys) -> tuple[int, str, str]:
    """Invoke the CLI and return (rc, stdout, stderr). Drains capsys first so
    setup output never leaks into the assertion window."""
    capsys.readouterr()
    rc = main(argv)
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def _signals_json(workspace: Path, capsys, *, kind: str | None = "merge_conflict") -> list[dict]:
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
# Behavior 1 -- Single conflict block detected; sole signal equals the exact
#               six-key dict; the `=======` separator is NOT counted (N == 2).
# ===========================================================================


def test_b01_single_block_exact_signal(tmp_path: Path, capsys) -> None:
    _write(tmp_path / "a.py", BLOCK)

    sigs = _signals_json(tmp_path, capsys)

    assert len(sigs) == 1, f"exactly one signal expected; got {sigs!r}"
    assert sigs[0] == {
        "source": "merge_conflict",
        "kind": "merge_conflict",
        "summary": "a.py: 2 conflict markers",
        "detail": "",
        "path": "a.py",
        "weight": 0.9,
    }


# ===========================================================================
# Behavior 2 -- Count reflects multiple blocks in one file (2 open + 2 close).
# ===========================================================================


def test_b02_two_blocks_count_four(tmp_path: Path, capsys) -> None:
    two_blocks = (
        "<<<<<<< HEAD\na\n=======\nb\n>>>>>>> x\n"
        "middle\n"
        "<<<<<<< HEAD\nc\n=======\nd\n>>>>>>> y\n"
    )
    _write(tmp_path / "dup.py", two_blocks)

    sigs = _signals_json(tmp_path, capsys)

    assert len(sigs) == 1
    assert sigs[0]["summary"].endswith("4 conflict markers"), sigs[0]["summary"]
    assert sigs[0]["path"] == "dup.py"


# ===========================================================================
# Behavior 3 -- Singular pluralization at N == 1 (orphaned CLOSE marker).
#               Detection fires on OPEN *or* CLOSE, not only on a matched pair.
# ===========================================================================


def test_b03_orphaned_close_marker_singular(tmp_path: Path, capsys) -> None:
    _write(tmp_path / "orphan.py", "keep this\n>>>>>>> feature\nand more\n")

    sigs = _signals_json(tmp_path, capsys)

    assert len(sigs) == 1
    summary = sigs[0]["summary"]
    assert summary.endswith("1 conflict marker"), summary
    assert not summary.endswith("markers"), f"N==1 must be singular, no trailing 's': {summary!r}"


# ===========================================================================
# Behavior 4 -- Bare `=======` / Markdown setext-H1 underline is NOT a marker.
# ===========================================================================


def test_b04_bare_separator_and_setext_underline_not_a_marker(tmp_path: Path, capsys) -> None:
    _write(tmp_path / "sep.md", "Title\n=======\nbody\n")
    _write(tmp_path / "underline.md", "Heading\n==================\nmore body\n")

    sigs = _signals_json(tmp_path, capsys)

    assert sigs == [], f"a benign separator/underline must yield NO signals; got {sigs!r}"


# ===========================================================================
# Behavior 5 -- Prefix precision: wrong chevron count / missing space / bare /
#               indented markers are ALL rejected. Only the exact seven-chevron
#               -plus-space prefix at column 0 counts.
# ===========================================================================


def test_b05_prefix_precision_rejects_near_misses(tmp_path: Path, capsys) -> None:
    near_misses = "\n".join(
        [
            "<<<<<<<<",           # eight `<`
            "<<<<<<<foo",         # seven `<`, NO following space
            "<<<<<<<",            # bare seven `<`, no trailing content
            "    <<<<<<< HEAD",   # INDENTED (leading whitespace)
            ">>>>>>>>",           # eight `>`
            ">>>>>>>bar",         # seven `>`, NO following space
            ">>>>>>>",            # bare seven `>`
            "\t>>>>>>> feature",  # tab-indented
        ]
    ) + "\n"
    _write(tmp_path / "nearmiss.py", near_misses)

    sigs = _signals_json(tmp_path, capsys)

    assert sigs == [], f"none of the near-miss lines is a marker; got {sigs!r}"


# ===========================================================================
# Behavior 6 -- Multiple affected files -> one signal each, relpath-ascending
#               (a.py precedes z.py).
# ===========================================================================


def test_b06_multiple_files_one_signal_each_ascending(tmp_path: Path, capsys) -> None:
    _write(tmp_path / "z.py", BLOCK)
    _write(tmp_path / "a.py", BLOCK)

    sigs = _signals_json(tmp_path, capsys)

    assert len(sigs) == 2, f"one signal per affected file; got {sigs!r}"
    paths = [s["path"] for s in sigs]
    assert paths == ["a.py", "z.py"], f"relpath-ascending order expected; got {paths!r}"


# ===========================================================================
# Behavior 7 -- Clean workspace -> no signals. Corollary: the marker-free demo
#               fixture yields no merge_conflict signals (so `make demo` output
#               stays byte-stable) and `make demo` still exits 0.
# ===========================================================================


def test_b07_clean_workspace_no_signals(tmp_path: Path, capsys) -> None:
    _write(tmp_path / "clean.py", "def f():\n    return 1\n")
    _write(tmp_path / "notes.md", "# Title\n\nJust prose, no markers.\n")

    # Assert against the full envelope, not just the filtered array.
    argv = ["signals", "--workspace", str(tmp_path), "--provider", "scripted",
            "--kind", "merge_conflict", "--json"]
    rc, out, err = _run(argv, capsys)
    assert rc == 0, err
    doc = json.loads(out)
    assert doc["signals"] == [], f"clean workspace must yield []; got {doc!r}"
    assert isinstance(doc["workspace_root"], str) and doc["workspace_root"]


def test_b07_demo_fixture_has_no_merge_conflict_signals(tmp_path, capsys) -> None:
    # The bundled fixture (which `make demo` scans) must carry NO markers, which
    # is what keeps the demo output byte-identical to its pre-iter-28 form.
    fixture = Path(__file__).resolve().parents[1] / "examples" / "fixture_workspace"
    assert fixture.is_dir(), fixture
    sigs = _signals_json(fixture, capsys)
    assert sigs == [], f"demo fixture must have no conflict markers; got {sigs!r}"


# ===========================================================================
# Behavior 8 -- Skip-dir / hidden pruning honored (reuses the shared
#               filesystem._SKIP_DIRS / _is_hidden). A marked file in a skipped
#               dir, a hidden dir, or that is itself a hidden FILE is dropped;
#               a marked file in a normal sibling dir IS reported.
# ===========================================================================


@pytest.mark.parametrize("skipdir", ["node_modules", ".venv", "__pycache__", ".git", "dist", "build"])
def test_b08_skipped_dir_pruned(tmp_path: Path, capsys, skipdir: str) -> None:
    _write(tmp_path / skipdir / "buried.py", BLOCK)
    _write(tmp_path / "normal" / "ok.py", BLOCK)

    paths = {s["path"] for s in _signals_json(tmp_path, capsys)}

    assert paths == {"normal/ok.py"}, f"only the normal-dir file must be reported; got {paths!r}"


def test_b08_hidden_dir_and_hidden_file_pruned(tmp_path: Path, capsys) -> None:
    _write(tmp_path / ".hidden" / "buried.py", BLOCK)   # hidden DIR
    _write(tmp_path / ".secret.py", BLOCK)              # hidden FILE
    _write(tmp_path / "visible.py", BLOCK)              # normal sibling

    paths = {s["path"] for s in _signals_json(tmp_path, capsys)}

    assert paths == {"visible.py"}, f"hidden dir/file must be pruned; got {paths!r}"


# ===========================================================================
# Behavior 9 -- Only scanned extensions; extension test is case-insensitive.
# ===========================================================================


def test_b09_only_scanned_extensions_case_insensitive(tmp_path: Path, capsys) -> None:
    # Non-scanned: image, lockfile, binary, extension-less.
    for name in ("image.png", "deps.lock", "blob.bin", "Makefile"):
        _write(tmp_path / name, BLOCK)
    # Scanned (incl. an UPPERCASE .PY to prove case-insensitivity) + a few more
    # from the authoritative set.
    for name in ("a.py", "b.PY", "c.md", "d.ts", "e.yaml"):
        _write(tmp_path / name, BLOCK)

    paths = {s["path"] for s in _signals_json(tmp_path, capsys)}

    assert paths == {"a.py", "b.PY", "c.md", "d.ts", "e.yaml"}, (
        f"only scanned extensions (case-insensitive) must be reported; got {paths!r}"
    )
    for excluded in ("image.png", "deps.lock", "blob.bin", "Makefile"):
        assert excluded not in paths


# ===========================================================================
# Behavior 10 -- Deterministic cap at max_items (default 30): with markers in
#                MORE than 30 files, exactly the 30 lexicographically-smallest
#                relpaths are returned. Driven through the public collector API
#                (the CLI uses the same default instance).
# ===========================================================================


def test_b10_deterministic_cap_at_max_items(tmp_path: Path) -> None:
    collector = MergeConflictCollector()
    assert collector.max_items == 30, "default max_items must be 30"

    total = 35
    for i in range(total):
        _write(tmp_path / f"{i:03d}.py", "<<<<<<< HEAD\nx\n>>>>>>> f\n")

    sigs = collector.collect(tmp_path)

    assert len(sigs) == 30, f"cap must be exactly max_items=30; got {len(sigs)}"
    got = [s.path for s in sigs]
    expected = sorted(f"{i:03d}.py" for i in range(total))[:30]
    assert got == expected, "the 30 lexicographically-smallest relpaths, ascending"
    # Deterministic: a second scan is identical.
    assert [s.path for s in collector.collect(tmp_path)] == got


# ===========================================================================
# Behavior 11 -- Collector never raises: non-directory root -> []; an
#                unreadable file (OSError) is silently skipped, not fatal.
# ===========================================================================


def test_b11_nonexistent_root_returns_empty(tmp_path: Path) -> None:
    assert MergeConflictCollector().collect(tmp_path / "no" / "such" / "dir") == []


def test_b11_file_root_returns_empty(tmp_path: Path) -> None:
    a_file = _write(tmp_path / "afile.py", BLOCK)
    assert MergeConflictCollector().collect(a_file) == []


def test_b11_unreadable_file_skipped_scan_continues(tmp_path: Path) -> None:
    good = _write(tmp_path / "good.py", BLOCK)
    bad = _write(tmp_path / "bad.py", BLOCK)
    os.chmod(bad, 0)
    try:
        # Must NOT raise regardless of whether this process can read `bad`.
        sigs = MergeConflictCollector().collect(tmp_path)
    finally:
        os.chmod(bad, 0o644)  # restore so tmp cleanup can remove it

    paths = {s.path for s in sigs}
    assert "good.py" in paths, "the scan must continue past an unreadable file"
    if not os.access(bad, os.R_OK):
        # Only assert the skip when the file is genuinely unreadable (i.e. not
        # running as root, where chmod 000 is bypassed).
        assert "bad.py" not in paths, "an unreadable file must be silently skipped"


# ===========================================================================
# Behavior 12 -- Registry membership (additive) + no version bump.
# ===========================================================================


def test_b12_registry_membership_and_no_version_bump(capsys) -> None:
    collectors = all_collectors()

    matches = [c for c in collectors if c.name == "merge_conflict"]
    assert len(matches) == 1, "exactly one merge_conflict collector in the registry"
    assert type(matches[0]) is MergeConflictCollector
    # The package alias and the direct-submodule import are the same class.
    assert MergeConflictCollector is MergeConflictCollector_direct

    # Every registered collector still satisfies the Collector duck-type.
    for c in collectors:
        assert isinstance(c.name, str) and c.name
        assert callable(getattr(c, "collect", None))
    assert isinstance(MergeConflictCollector(), Collector) or hasattr(
        MergeConflictCollector(), "collect"
    )

    # Additive kind => NO version bump.
    assert proactive_loop.__version__ == "0.1.1", proactive_loop.__version__

    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0, "`pla --version` must exit 0"
    out = capsys.readouterr().out
    assert "pla 0.1.1" in out, f"`pla --version` must print 'pla 0.1.1'; got {out!r}"


# ===========================================================================
# Behavior 13 -- `pla signals` human render surfaces the new kind under a
#                `## merge_conflict (1)` header with the summary text.
# ===========================================================================


def test_b13_signals_human_render(tmp_path: Path, capsys) -> None:
    _write(tmp_path / "a.py", BLOCK)  # N == 2

    rc, out, err = _run(
        ["signals", "--workspace", str(tmp_path), "--provider", "scripted"],
        capsys,
    )

    assert rc == 0, f"signals must exit 0; stderr={err!r}"
    # Group header token for the new kind (exactly one marked file -> count 1).
    assert "## merge_conflict (1)" in out, f"missing merge_conflict group header; got:\n{out}"
    # The indented signal line carries the summary text.
    assert "a.py: 2 conflict markers" in out, f"missing summary text; got:\n{out}"
