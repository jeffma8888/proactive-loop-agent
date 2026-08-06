"""Black-box behavior tests for iteration 67 (ships as commit-sequence factory
iter 77).

Feature under test: a new **L2 perception collector**, ``SyntaxErrorCollector``
(``name == "syntax_error"``, ``kind == "syntax_error"``) -- the FIRST
code-PARSING collector. It runs the stdlib parser ``compile(text, path, "exec")``
(PARSE-ONLY, never executes/imports the user code) on every ``*.py`` file under
the workspace and emits ONE ``ContextSignal`` per file that raises a
``SyntaxError``. Signal field contract: ``source == kind == "syntax_error"``,
``summary == "<relpath>: syntax error at line <N>"`` (N = the error's 1-based
line, forward-slashed relpath), ``detail`` = the parser's short ``SyntaxError.msg``
ONLY (the offending source line ``SyntaxError.text`` is DELIBERATELY omitted ->
no content leak), ``weight == 0.9``, ``path == <relpath>``, ``timestamp is None``.
Like every collector it degrades to ``[]`` rather than raising on hostile input,
honors the shared ``_SKIP_DIRS`` / hidden-entry prune, scans ``.py`` ONLY
(``.pyi`` excluded), returns results ordered by relpath ascending, capped to
``max_items`` (default 30). Additive collector (14 -> 15), no version bump.

ISOLATION CONTRACT (honored): these tests are written strictly against the
public contract for this iteration -- the spec's "Expected Behaviors"
(``pm.md``), ``README.md``, and ``SPEC.md`` sections 4.1 / 4.5 -- and drive ONLY
documented public surfaces: the collector API
``proactive_loop.collectors.SyntaxErrorCollector().collect(root)``, the
``proactive_loop.collectors.syntax_error`` submodule (whose ``os.walk`` seam is
the monkeypatch target for the never-raise invariant, mirroring iter-70), the
public registry ``proactive_loop.collectors.all_collectors()``, the
``ContextSignal`` domain model from ``proactive_loop.models``, the public
``proactive_loop.__version__`` string, and the end-to-end CLI entry points
``pla signals``, ``pla collectors [--json]`` and ``pla scan`` via
``proactive_loop.cli.main(argv) -> int`` (observable stdout / stderr / exit
code). **No file under ``src/`` was read, no engineer/reviewer notes were read,
and no ``git diff`` was consulted.** Signal field names, the exact ``summary``
shape, and the fifteen canonical collector names were taken from this
iteration's spec (``pm.md``) and the existing published tests, never from the
implementation. Every test builds its own synthetic ``tmp_path`` workspace and
is fully offline: NO real git repo, NO ``subprocess``, NO network, NO API keys,
NO LLM. The ``signals`` tests pass ``--provider scripted`` (with the committed
``examples/scripted_responses.json`` for ``scan``) to prove the pipeline needs
no live provider.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from proactive_loop import __version__
from proactive_loop.cli import main
from proactive_loop.collectors import SyntaxErrorCollector, all_collectors
from proactive_loop.collectors import syntax_error as syntax_error_mod
from proactive_loop.collectors.syntax_error import (
    SyntaxErrorCollector as SyntaxErrorCollector_direct,
)
from proactive_loop.models import ContextSignal

REPO = Path(__file__).resolve().parents[1]
SPEC = REPO / "SPEC.md"
SCRIPT = REPO / "examples" / "scripted_responses.json"

# ---------------------------------------------------------------------------
# Tester's ground facts -- the spec-declared canonical set (pm.md). Encoded
# here as a constant, NOT imported from the implementation's private catalog,
# so the tests encode the CONTRACT and catch silent drift.
# ---------------------------------------------------------------------------

EXPECTED_COLLECTOR_COUNT = 16

CANONICAL_COLLECTORS = {
    "ci_config",
    "dependencies",
    "git_activity",
    "git_stash",
    "git_state",
    "large_file",
    "license",
    "lockfile_drift",
    "merge_conflict",
    "notes",
    "recent_files",
    "secret_file",
    "syntax_error",
    "test_posture",
    "todos",
    "working_tree",
}

# A deliberately-invalid Python snippet whose offending source line carries a
# distinctive token; used to prove the token never leaks into summary/detail.
_LEAK_TOKEN = "SECRET_LEAK_TOKEN_XYZ"
_BROKEN_SRC = f"{_LEAK_TOKEN} = (\n"  # unclosed "(" -> SyntaxError at line 1


# ---------------------------------------------------------------------------
# Helpers -- all black-box: build synthetic tmp workspaces, drive the public
# collector API / the CLI, read back observable output.
# ---------------------------------------------------------------------------


def _write(path: Path, content: str = _BROKEN_SRC) -> Path:
    """Create *path* (and parents) with text content (default: broken Python)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _run(argv: list[str], capsys) -> tuple[int, str, str]:
    """Invoke the CLI, return (rc, stdout, stderr). Drains capsys first so setup
    output never leaks into the assertion window."""
    capsys.readouterr()
    rc = main(argv)
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def _assert_syntax_signal(
    s: ContextSignal, *, summary: str, path: str
) -> None:
    """Assert the full fixed field contract shared by every syntax_error signal."""
    assert isinstance(s, ContextSignal)
    assert s.source == "syntax_error"
    assert s.kind == "syntax_error"
    assert s.summary == summary
    assert isinstance(s.detail, str) and s.detail, "detail must be a non-empty str"
    assert s.weight == 0.9
    assert s.timestamp is None
    assert s.path == path


# ===========================================================================
# Behavior 1 -- Flags a .py file that fails to parse: EXACTLY one signal with
#   the full field contract; summary carries the relpath + "syntax error at
#   line 1" (the error's 1-based line number).
# ===========================================================================


def test_b01_flags_broken_py_full_field_contract(tmp_path: Path) -> None:
    _write(tmp_path / "broken.py")

    sigs = SyntaxErrorCollector().collect(tmp_path)

    assert len(sigs) == 1, f"exactly one syntax_error signal expected; got {sigs!r}"
    _assert_syntax_signal(
        sigs[0],
        summary="broken.py: syntax error at line 1",
        path="broken.py",
    )
    # The summary explicitly names the file and the 1-based line.
    assert "broken.py" in sigs[0].summary
    assert "syntax error at line 1" in sigs[0].summary


# ===========================================================================
# Behavior 2 -- Ignores valid .py files: a workspace whose only .py files parse
#   cleanly -> [] (zero signals).
# ===========================================================================


def test_b02_valid_py_yields_no_signal(tmp_path: Path) -> None:
    _write(tmp_path / "ok.py", "def ok():\n    return 1\n")
    _write(tmp_path / "pkg" / "also_ok.py", "x = 1\n")

    assert SyntaxErrorCollector().collect(tmp_path) == []


# ===========================================================================
# Behavior 3 -- Parse-only: a syntactically-VALID .py whose module-level code
#   WOULD write a sentinel + raise if executed -> [], no exception, and the
#   sentinel is NEVER created (proves compile-not-exec/import).
# ===========================================================================


def test_b03_parse_only_never_executes(tmp_path: Path) -> None:
    sentinel = tmp_path / "SENTINEL_SIDE_EFFECT"
    # Valid Python (parses), but running it would create the sentinel and exit.
    src = (
        f"open({str(sentinel)!r}, 'w').write('boom')\n"
        "raise SystemExit(1)\n"
    )
    _write(tmp_path / "effect.py", src)

    result = SyntaxErrorCollector().collect(tmp_path)

    assert result == [], f"a valid (parseable) file must emit no signal; got {result!r}"
    assert not sentinel.exists(), (
        "the collector must NOT execute/import the file -- the sentinel side "
        "effect must never occur"
    )


# ===========================================================================
# Behavior 4 -- Only *.py is scanned: invalid Python-looking content behind a
#   non-.py extension (.txt/.js/.pyi) is NOT scanned -> 0 signals.
# ===========================================================================


@pytest.mark.parametrize("ext", ["txt", "js", "pyi"])
def test_b04_only_py_scanned(tmp_path: Path, ext: str) -> None:
    _write(tmp_path / f"broken.{ext}")
    assert SyntaxErrorCollector().collect(tmp_path) == [], (
        f"a .{ext} file must not be scanned"
    )


def test_b04_pyi_excluded_next_to_a_real_py(tmp_path: Path) -> None:
    # A broken .pyi is ignored while the broken .py sibling still emits.
    _write(tmp_path / "stub.pyi")
    _write(tmp_path / "real.py")
    sigs = SyntaxErrorCollector().collect(tmp_path)
    assert [s.path for s in sigs] == ["real.py"], (
        f"only the .py must be reported (.pyi excluded); got {[s.path for s in sigs]!r}"
    )


# ===========================================================================
# Behavior 5 -- Multiple broken files: one signal each, ordered by relpath
#   ascending; max_items=k caps to the k lexicographically-smallest relpaths.
# ===========================================================================


def test_b05_multiple_broken_ordered_ascending(tmp_path: Path) -> None:
    for name in ("zeta.py", "alpha.py", "mid.py"):
        _write(tmp_path / name)

    sigs = SyntaxErrorCollector().collect(tmp_path)

    assert [s.path for s in sigs] == ["alpha.py", "mid.py", "zeta.py"], (
        f"signals must be ordered by relpath ascending; got {[s.path for s in sigs]!r}"
    )


def test_b05_capped_to_max_items_keeps_smallest_relpaths(tmp_path: Path) -> None:
    for name in ("zeta.py", "alpha.py", "mid.py"):
        _write(tmp_path / name)

    sigs = SyntaxErrorCollector(max_items=2).collect(tmp_path)

    assert [s.path for s in sigs] == ["alpha.py", "mid.py"], (
        f"max_items=2 must keep the two smallest relpaths; got {[s.path for s in sigs]!r}"
    )


# ===========================================================================
# Behavior 6 -- Non-decodable / binary .py degrades cleanly: invalid UTF-8
#   bytes or NUL bytes -> skipped (0 signals), never raises.
# ===========================================================================


def test_b06_nul_byte_py_skipped(tmp_path: Path) -> None:
    (tmp_path / "nul.py").write_bytes(b"def f(:\x00\n")
    assert SyntaxErrorCollector().collect(tmp_path) == []


def test_b06_invalid_utf8_py_skipped(tmp_path: Path) -> None:
    (tmp_path / "badutf.py").write_bytes(b"\xff\xfe def f(:\n")
    assert SyntaxErrorCollector().collect(tmp_path) == []


def test_b06_binary_skipped_but_broken_sibling_survives(tmp_path: Path) -> None:
    (tmp_path / "nul.py").write_bytes(b"def f(:\x00\n")
    _write(tmp_path / "broken.py")
    sigs = SyntaxErrorCollector().collect(tmp_path)
    assert [s.path for s in sigs] == ["broken.py"], (
        f"the undecodable file must be skipped while the decodable broken .py "
        f"still emits; got {[s.path for s in sigs]!r}"
    )


# ===========================================================================
# Behavior 7 -- Skip-dirs and hidden entries are pruned: a broken .py under
#   .venv/node_modules/__pycache__/.git/hidden-dir, and a hidden file
#   .broken.py, are NOT scanned -> 0 signals.
# ===========================================================================


_SKIP_DIR_NAMES = ["node_modules", ".venv", "__pycache__", ".git", ".hidden"]


@pytest.mark.parametrize("skip_dir", _SKIP_DIR_NAMES)
def test_b07_broken_py_in_skipped_dir_is_invisible(tmp_path: Path, skip_dir: str) -> None:
    d = tmp_path / skip_dir
    d.mkdir()
    _write(d / "broken.py")
    assert SyntaxErrorCollector().collect(tmp_path) == [], (
        f"a broken .py inside {skip_dir!r} must be pruned"
    )


def test_b07_hidden_file_is_invisible(tmp_path: Path) -> None:
    _write(tmp_path / ".broken.py")
    assert SyntaxErrorCollector().collect(tmp_path) == [], (
        "a hidden .broken.py file must be pruned"
    )


def test_b07_visible_sibling_still_emits_next_to_skipped(tmp_path: Path) -> None:
    (tmp_path / "node_modules").mkdir()
    _write(tmp_path / "node_modules" / "broken.py")
    _write(tmp_path / "broken.py")
    sigs = SyntaxErrorCollector().collect(tmp_path)
    assert [s.path for s in sigs] == ["broken.py"], (
        f"a pruned dir must not suppress a legitimate top-level broken .py; "
        f"got {[s.path for s in sigs]!r}"
    )


# ===========================================================================
# Behavior 8 -- detail carries the parser diagnostic; summary stays
#   deterministic and leak-free. detail is a NON-EMPTY string (version-variable
#   msg, NOT pinned); summary == "<rel>: syntax error at line <N>" and the
#   offending source line's distinctive token never appears in summary/detail.
# ===========================================================================


def test_b08_detail_nonempty_summary_deterministic_and_leak_free(tmp_path: Path) -> None:
    _write(tmp_path / "broken.py")  # contains _LEAK_TOKEN in the offending line

    sig = SyntaxErrorCollector().collect(tmp_path)[0]

    # detail = the parser's short msg; we assert only that it is NON-EMPTY
    # (its exact wording is CPython-version-variable, deliberately not pinned).
    assert isinstance(sig.detail, str) and sig.detail
    # summary is the deterministic shape from a known error line.
    assert sig.summary == "broken.py: syntax error at line 1"
    # No content leak: the offending source line's distinctive token must NOT
    # appear anywhere in the emitted signal's summary or detail.
    assert _LEAK_TOKEN not in sig.summary, "summary must not leak the source line"
    assert _LEAK_TOKEN not in sig.detail, "detail must not leak the source line"


def test_b08_line_number_reflects_the_error_location(tmp_path: Path) -> None:
    # The error is on line 3; the summary must name line 3, not line 1.
    _write(tmp_path / "multi.py", "a = 1\nb = 2\ndef f(:\n    pass\n")

    sig = SyntaxErrorCollector().collect(tmp_path)[0]

    assert sig.summary == "multi.py: syntax error at line 3", (
        f"the summary must reflect the 1-based error line (3); got {sig.summary!r}"
    )


# ===========================================================================
# Behavior 9 -- Degrades on a bad root: a non-existent root or a root that is a
#   file (not a directory) -> [] and never raises.
# ===========================================================================


def test_b09_nonexistent_root_empty() -> None:
    assert SyntaxErrorCollector().collect(Path("/does/not/exist/iter77")) == []


def test_b09_root_is_a_file_empty(tmp_path: Path) -> None:
    f = _write(tmp_path / "single.py", "x = 1\n")
    assert SyntaxErrorCollector().collect(f) == []


# ===========================================================================
# Behavior 10 -- Registry + catalog integration (drift-guarded at 15):
#   "syntax_error" is in all_collectors() (len 15), the class is exported;
#   `pla collectors` lists it, `--json` includes its {name, description} object,
#   the catalog name-set equals the live registry, and the SPEC "array of 15
#   {name, description}" collectors count equals len(all_collectors()).
# ===========================================================================


def test_b10_registry_membership_and_count() -> None:
    names = [c.name for c in all_collectors()]
    assert names.count("syntax_error") == 1, (
        f"exactly one syntax_error collector expected; got {names!r}"
    )
    assert len(all_collectors()) == EXPECTED_COLLECTOR_COUNT
    assert {c.name for c in all_collectors()} == CANONICAL_COLLECTORS


def test_b10_class_exported_and_same_object() -> None:
    assert SyntaxErrorCollector is SyntaxErrorCollector_direct
    match = [c for c in all_collectors() if c.name == "syntax_error"]
    assert len(match) == 1 and isinstance(match[0], SyntaxErrorCollector)


def test_b10_defaults() -> None:
    c = SyntaxErrorCollector()
    assert c.name == "syntax_error"
    assert c.max_items == 30


def test_b10_collectors_human_lists_syntax_error(capsys) -> None:
    rc, out, err = _run(["collectors"], capsys)
    assert rc == 0, f"pla collectors (human) must exit 0; stderr={err!r}"
    lines = [ln for ln in out.splitlines() if ln.strip().startswith("syntax_error")]
    assert lines, f"human output must list syntax_error; got:\n{out}"
    desc = lines[0].strip()[len("syntax_error"):].strip()
    assert desc, f"syntax_error must carry a non-empty description; line={lines[0]!r}"


def test_b10_collectors_json_15_objects_includes_syntax_error(capsys) -> None:
    rc, out, err = _run(["collectors", "--json"], capsys)
    assert rc == 0, f"pla collectors --json must exit 0; stderr={err!r}"
    doc = json.loads(out)
    assert isinstance(doc, dict) and "collectors" in doc
    entries = doc["collectors"]
    assert isinstance(entries, list)
    assert len(entries) == EXPECTED_COLLECTOR_COUNT, (
        f"catalog must list {EXPECTED_COLLECTOR_COUNT} collectors; got {len(entries)}"
    )
    for e in entries:
        assert set(e.keys()) == {"name", "kind", "description"}, (
            f"each entry must have EXACTLY {{name, kind, description}}; got {sorted(e.keys())}"
        )
        assert isinstance(e["name"], str) and e["name"]
        assert isinstance(e["description"], str) and e["description"].strip()
    names = [e["name"] for e in entries]
    assert "syntax_error" in names, "syntax_error must be catalogued"
    assert names == sorted(names), f"catalog must be name-ascending; got {names}"
    # Drift-guard: catalog name-set == live registry name-set == canonical 15.
    registry_names = {c.name for c in all_collectors()}
    assert set(names) == registry_names == CANONICAL_COLLECTORS, (
        f"catalog name-set must equal the live registry; catalog={set(names)} "
        f"registry={registry_names}"
    )


def test_b10_spec_collectors_count_matches_registry() -> None:
    spec = SPEC.read_text(encoding="utf-8")
    matches = re.findall(r"array of (\d+)\s+`\{name, description\}` objects", spec)
    assert len(matches) == 1, (
        f"expected EXACTLY one collectors count-anchor in SPEC; found {matches!r}"
    )
    assert int(matches[0]) == len(all_collectors()) == EXPECTED_COLLECTOR_COUNT, (
        f"SPEC 'array of N {{name, description}}' count ({matches[0]}) must equal the "
        f"live collector count ({len(all_collectors())})"
    )


def test_b10_version_unchanged() -> None:
    assert __version__ == "0.1.1", (
        f"adding this collector must NOT bump the version; got {__version__!r}"
    )


# ===========================================================================
# Behavior 11 -- New kind flows through the pipeline: `pla signals --kind
#   syntax_error --json` on a broken-py workspace emits the six-key signal dict
#   with kind == "syntax_error"; a `pla scan` over such a workspace exits 0.
# ===========================================================================


def test_b11_signals_json_surfaces_syntax_error(tmp_path: Path, capsys) -> None:
    _write(tmp_path / "broken.py")

    rc, out, err = _run(
        [
            "signals",
            "--workspace", str(tmp_path),
            "--provider", "scripted",
            "--kind", "syntax_error",
            "--json",
        ],
        capsys,
    )
    assert rc == 0, f"pla signals --json must exit 0; stderr={err!r}"
    doc = json.loads(out)
    assert isinstance(doc, dict) and isinstance(doc.get("signals"), list)
    hits = [s for s in doc["signals"] if s.get("kind") == "syntax_error"]
    assert len(hits) == 1, f"expected one syntax_error signal in JSON; got {doc['signals']!r}"
    sig = hits[0]
    assert set(sig.keys()) == {"source", "kind", "summary", "detail", "path", "weight"}, (
        f"the signal dict must carry exactly the six keys; got {sorted(sig.keys())}"
    )
    assert sig["source"] == "syntax_error"
    assert sig["kind"] == "syntax_error"
    assert sig["summary"] == "broken.py: syntax error at line 1"
    assert sig["path"] == "broken.py"
    assert sig["weight"] == 0.9
    assert isinstance(sig["detail"], str) and sig["detail"]
    assert _LEAK_TOKEN not in sig["detail"] and _LEAK_TOKEN not in sig["summary"]


def test_b11_signals_unrelated_kind_excludes_syntax_error(tmp_path: Path, capsys) -> None:
    _write(tmp_path / "broken.py")

    rc, out, err = _run(
        [
            "signals",
            "--workspace", str(tmp_path),
            "--provider", "scripted",
            "--kind", "todo",
        ],
        capsys,
    )
    assert rc == 0, f"pla signals must exit 0; stderr={err!r}"
    assert "syntax_error" not in out, (
        f"a `todo` filter must not surface syntax_error; got:\n{out}"
    )


def test_b11_scan_over_broken_workspace_exits_zero(tmp_path: Path, capsys) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    _write(ws / "broken.py")
    state = tmp_path / "state"
    out_slate = tmp_path / "slate.json"

    rc, out, err = _run(
        [
            "scan",
            "--workspace", str(ws),
            "--provider", "scripted",
            "--scripted-responses", str(SCRIPT),
            "--state-dir", str(state),
            "--out", str(out_slate),
        ],
        capsys,
    )
    assert rc == 0, (
        f"a scan over a workspace with a broken .py must synthesize with no error "
        f"(new kind flows via by_kind, zero synthesizer change); rc={rc}, stderr={err!r}"
    )
    assert out_slate.exists(), "the scan must still produce a goal slate"


# ===========================================================================
# Behavior 12 -- Never raises under hostile input: a directory named x.py, a
#   dangling symlink, and os.walk raising all degrade to [] / skipped without
#   raising. (The registry-driven TestGracefulDegradation in test_collectors.py
#   auto-covers the never-raise invariant for the new collector too.)
#
#   AMBIGUITY NOTE (PM feedback): the spec's Behavior 12 lists "a symlink" among
#   things that "degrade to skipped". Empirically a VALID file-symlink pointing
#   at a readable broken .py is FOLLOWED by os.walk and reported (harmless -- it
#   names a real broken file). The load-bearing invariant that always holds is
#   "never raises"; a DANGLING symlink (missing target) is the one genuinely
#   skipped, which is what these tests pin.
# ===========================================================================


def test_b12_directory_named_py_never_raises(tmp_path: Path) -> None:
    (tmp_path / "x.py").mkdir()  # a directory, not a file
    assert SyntaxErrorCollector().collect(tmp_path) == []


def test_b12_dangling_symlink_degrades(tmp_path: Path) -> None:
    _write(tmp_path / "broken.py")  # a real broken file must still emit
    try:
        os.symlink(str(tmp_path / "missing_target.py"), str(tmp_path / "dangling.py"))
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unsupported on this platform")

    sigs = SyntaxErrorCollector().collect(tmp_path)  # must not raise

    paths = {s.path for s in sigs}
    assert "dangling.py" not in paths, "a dangling symlink must be skipped, not reported"
    assert "broken.py" in paths, "the real broken sibling must still emit"


def test_b12_oswalk_raises_degrades_to_empty(tmp_path: Path, monkeypatch) -> None:
    _write(tmp_path / "broken.py")

    def _boom(*_a, **_k):
        raise OSError("simulated os.walk failure")

    monkeypatch.setattr(syntax_error_mod.os, "walk", _boom)

    assert SyntaxErrorCollector().collect(tmp_path) == []
