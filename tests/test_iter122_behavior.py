"""Black-box behavior tests for iteration 122 --- atomic slate writes.

Feature under test: the CLI's single slate writer ``_write_slate`` gains the
crash-safe write the product already documents for ``Checkpoint.save`` --- write
a temp sibling in the destination's OWN directory, then ONE atomic
``os.replace`` onto the target --- plus the temp-file cleanup the in-tree idiom
is missing, so a kill or a failed swap can never leave a truncated slate or a
stray ``.tmp`` in a user-supplied directory. Destination bytes, stdout, exit
codes and parent-creation-on-demand all stay exactly as they were.

ISOLATION CONTRACT (honored): written strictly against this iteration's spec
(``pm.md`` "Expected Behaviors" 1-9); drives only documented public surfaces ---
the ``pla`` CLI via ``proactive_loop.cli.main(argv) -> int`` (its observable
stdout / stderr / exit codes / on-disk artifacts) and the public
``proactive_loop.models`` schema as the parse oracle --- plus the ONE private
import the spec explicitly authorizes (``from proactive_loop.cli import
_write_slate``; in-tree precedent: ``tests/test_iter25_behavior.py`` imports
``_CliLogHandler``, ``tests/test_iter113_behavior.py`` imports
``_TOOL_CATALOG``, ``tests/test_iter56_helpers.py`` imports ``_render_html``).
**No file under ``src/`` was read, no engineer or reviewer notes were read, and
no ``git diff`` was consulted.** Behavior 9 reads ``_write_slate.__doc__``, a
runtime attribute of the imported callable, not the source file.

Fully offline and deterministic: zero network, zero API keys, the scripted
provider seam only, no sleeps. Synthetic ``tmp_path`` workspaces throughout
(never the in-repo tree), so the git_activity / working_tree / test_posture
collectors cannot leak repo state (iter-15 lesson), and every ``watch`` is
bounded by a small ``--max-scans`` (an unbounded run would hang the suite).

AMBIGUITY NOTE (PM feedback, behavior 9): the spec requires the docstring to
name the mechanism and its scope while claiming "nothing stronger", listing
``fsync``, power-loss durability and locking/concurrency as the over-claims.
Taken literally that forbids the TOKENS, so a docstring DISCLAIMING them (e.g.
"does not fsync") would also go red even though it is more truthful --- a
positive-only claim is the only wording that satisfies both this guard and the
spec. The scope vocabulary is tested as an alternation
("crash"/"kill"/"interrupt") rather than one exact word, so the guard pins the
CLAIM, not a phrasing.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from proactive_loop.cli import _write_slate, main
from proactive_loop.models import CandidateGoal, GoalSlate

_TMP_SUFFIX = ".tmp"

# Behavior 9: over-claims the docstring must NOT make. "lock"/"concurrent" are
# matched on WORD boundaries so an innocent "blocking" can never trip them.
_OVERCLAIM_SUBSTRINGS = ("fsync", "power")
_OVERCLAIM_PATTERNS = (r"\block(s|ed|ing)?\b", r"\bconcurren\w*")


# ---------------------------------------------------------------------------
# Helpers --- black-box: hand-build public models, drive main(), read back
# stdout / stderr / exit code / on-disk artifacts. Local copies of the
# iter-120 watch helpers (a local copy is lower risk than a cross-module
# test import).
# ---------------------------------------------------------------------------


def _goal(title: str) -> CandidateGoal:
    """One goal built through the public model, no scoring edge cases."""
    return CandidateGoal(
        title=title,
        rationale="black-box atomic-write probe",
        category="learning",
        impact=5.0,
        urgency=4.0,
        confidence=0.9,
        effort_weight=1.0,
        appropriate_now=True,
        sources=["foo.py"],
        suggested_first_steps=["do a thing"],
    )


def _slate(root: Path, *titles: str) -> GoalSlate:
    return GoalSlate(workspace_root=str(root), goals=[_goal(t) for t in titles])


def _workspace(tmp_path: Path) -> Path:
    """A minimal, real, synthetic workspace directory (one source file)."""
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "foo.py").write_text("print('hi')\n", encoding="utf-8")
    return ws


def _goal_dict(title: str) -> dict:
    """One goal dict matching the documented synthesize JSON contract."""
    return {
        "title": title,
        "rationale": "black-box atomic-write probe",
        "category": "learning",
        "impact": 5.0,
        "urgency": 5.0,
        "confidence": 1.0,
        "effort_weight": 1.0,
        "appropriate_now": True,
        "sources": ["foo.py"],
        "suggested_first_steps": ["do a thing"],
    }


def _script(tmp_path: Path, titles: list[str], *, name: str = "script.json") -> Path:
    """One ``synthesize`` response per title (one per scan tick)."""
    responses = [
        {"tag": "synthesize", "text": json.dumps([_goal_dict(t)])} for t in titles
    ]
    path = tmp_path / name
    path.write_text(json.dumps({"responses": responses}), encoding="utf-8")
    return path


def _run(argv: list[str], capsys) -> tuple[int, str, str]:
    """Drive main() and return (exit_code, stdout, stderr)."""
    capsys.readouterr()
    rc = main(argv)
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def _names(directory: Path) -> list[str]:
    return sorted(p.name for p in directory.iterdir())


def _tmp_residue(directory: Path) -> list[str]:
    return [n for n in _names(directory) if n.endswith(_TMP_SUFFIX)]


def _error_lines(err: str) -> list[str]:
    return [ln for ln in err.splitlines() if ln.startswith("error:")]


def _scan_argv(ws: Path, script: Path, *, state_dir: Path, out: Path) -> list[str]:
    return [
        "scan",
        "--workspace", str(ws),
        "--provider", "scripted",
        "--scripted-responses", str(script),
        "--state-dir", str(state_dir),
        "--out", str(out),
    ]


def _watch_argv(
    ws: Path, script: Path, *, state_dir: Path, out_dir: Path, max_scans: str
) -> list[str]:
    return [
        "watch",
        "--workspace", str(ws),
        "--provider", "scripted",
        "--scripted-responses", str(script),
        "--interval", "0",
        "--state-dir", str(state_dir),
        "--max-scans", max_scans,
        "--out-dir", str(out_dir),
    ]


def _boom_scenario(tmp_path: Path, monkeypatch) -> tuple[Path, bytes]:
    """Behaviors 6-8: a target already holding known bytes, with the atomic
    swap forced to fail. Returns (target, prior_bytes)."""
    out = tmp_path / "dest" / "slate.json"
    out.parent.mkdir(parents=True)
    prior = b'{"prior": "bytes that must survive a failed swap"}'
    out.write_bytes(prior)

    def _boom(src, dst, *args, **kwargs):
        raise OSError("boom")

    monkeypatch.setattr(os, "replace", _boom)
    return out, prior


# ===========================================================================
# Behavior 1 --- Destination content is unchanged (exact indent-2 JSON).
# ===========================================================================


def test_b01_destination_content_is_exact_indent2_json(tmp_path):
    slate = _slate(tmp_path, "Content fidelity goal")
    out = tmp_path / "dest" / "slate.json"

    _write_slate(slate, out)

    text = out.read_text(encoding="utf-8")
    expected = slate.model_dump_json(indent=2)
    assert text == expected, (
        "atomic write must not alter the destination bytes; "
        f"got {text[:120]!r} want {expected[:120]!r}"
    )
    # Round trip: the file is canonical indent-2 JSON, no added/removed newline.
    assert text == GoalSlate.model_validate_json(text).model_dump_json(indent=2)
    assert '\n  "' in text, f"2-space indent must survive; got {text[:80]!r}"
    assert not text.endswith("\n"), "no trailing newline may be added"


def test_b01b_scan_out_still_writes_canonical_json_with_clean_stdout(tmp_path, capsys):
    ws = _workspace(tmp_path)
    script = _script(tmp_path, ["Scan canonical goal"])
    out = tmp_path / "dest" / "slate.json"

    rc, out_s, err = _run(
        _scan_argv(ws, script, state_dir=tmp_path / "state", out=out), capsys
    )

    assert rc == 0, f"scan --out must still exit 0; stderr={err!r}"
    assert _error_lines(err) == [], f"no error lines expected; got {err!r}"
    text = out.read_text(encoding="utf-8")
    assert text == GoalSlate.model_validate_json(text).model_dump_json(indent=2)
    assert _TMP_SUFFIX not in out_s, (
        f"stdout must never mention a temp file; got:\n{out_s}"
    )
    assert _tmp_residue(out.parent) == [], f"leaked temp file: {_names(out.parent)}"


# ===========================================================================
# Behavior 2 --- No temp sibling survives a successful write.
# ===========================================================================


def test_b02_no_temp_sibling_survives_a_successful_write(tmp_path):
    dest = tmp_path / "dest"
    out = dest / "slate.json"

    _write_slate(_slate(tmp_path, "Residue goal"), out)

    assert _names(dest) == ["slate.json"], f"got {_names(dest)}"
    assert _tmp_residue(dest) == []


def test_b02b_overwriting_an_existing_slate_leaves_one_file(tmp_path):
    dest = tmp_path / "dest"
    out = dest / "slate.json"
    _write_slate(_slate(tmp_path, "First goal"), out)
    second = _slate(tmp_path, "Second goal")

    _write_slate(second, out)

    assert _names(dest) == ["slate.json"], f"got {_names(dest)}"
    assert out.read_text(encoding="utf-8") == second.model_dump_json(indent=2)


# ===========================================================================
# Behavior 3 --- The shipped per-tick stream is unaffected.
# ===========================================================================


def test_b03_watch_out_dir_stream_is_unaffected(tmp_path, capsys):
    ws = _workspace(tmp_path)
    script = _script(tmp_path, ["Tick one goal", "Tick two goal", "Tick three goal"])
    out_dir = tmp_path / "stream"

    rc, out_s, err = _run(
        _watch_argv(
            ws, script, state_dir=tmp_path / "state", out_dir=out_dir, max_scans="3"
        ),
        capsys,
    )

    assert rc == 0, f"watch --out-dir must exit 0; stderr={err!r}"
    assert _names(out_dir) == [
        "slate-001.json",
        "slate-002.json",
        "slate-003.json",
    ], f"got {_names(out_dir)}"
    assert _tmp_residue(out_dir) == [], f"leaked temp file: {_names(out_dir)}"
    assert list(out_dir.rglob("slate.json")) == [], "must not write a fixed slate.json"
    for path in sorted(out_dir.iterdir()):
        parsed = GoalSlate.model_validate_json(path.read_text(encoding="utf-8"))
        assert parsed.workspace_root, f"{path.name} must parse as a GoalSlate"


# ===========================================================================
# Behavior 4 --- Parents are still created on demand.
# ===========================================================================


def test_b04_absent_parent_chain_is_created_on_demand(tmp_path):
    out = tmp_path / "a" / "b" / "c" / "slate.json"
    assert not (tmp_path / "a").exists(), "arrange: the chain must be fully absent"

    _write_slate(_slate(tmp_path, "Deep parent goal"), out)

    assert out.is_file(), "the whole parent chain must be created on demand"
    assert _names(out.parent) == ["slate.json"], f"got {_names(out.parent)}"


def test_b04b_cli_guards_still_pass_an_all_new_path(tmp_path, capsys):
    """Both --out and --out-dir guards return None for an all-new path, i.e.
    no exit-2 usage error is reported for a path that does not exist yet."""
    ws = _workspace(tmp_path)

    out = tmp_path / "new_a" / "new_b" / "slate.json"
    rc, _out_s, err = _run(
        _scan_argv(
            ws, _script(tmp_path, ["New path goal"]), state_dir=tmp_path / "s1", out=out
        ),
        capsys,
    )
    assert rc == 0, f"scan --out on an all-new path must exit 0; stderr={err!r}"
    assert _error_lines(err) == [], f"unexpected usage error: {err!r}"
    assert out.is_file()

    out_dir = tmp_path / "new_c" / "new_d"
    rc2, _out_s2, err2 = _run(
        _watch_argv(
            ws,
            _script(tmp_path, ["New dir goal"], name="script2.json"),
            state_dir=tmp_path / "s2",
            out_dir=out_dir,
            max_scans="1",
        ),
        capsys,
    )
    assert rc2 == 0, f"watch --out-dir on an all-new path must exit 0; stderr={err2!r}"
    assert _error_lines(err2) == [], f"unexpected usage error: {err2!r}"
    assert _names(out_dir) == ["slate-001.json"], f"got {_names(out_dir)}"


# ===========================================================================
# Behavior 5 --- The write is temp-sibling-then-ONE-rename.
# ===========================================================================


def test_b05_exactly_one_replace_from_a_same_directory_sibling(tmp_path, monkeypatch):
    calls: list[tuple[str, str]] = []
    real_replace = os.replace

    def _spy(src, dst, *args, **kwargs):
        calls.append((os.fspath(src), os.fspath(dst)))
        return real_replace(src, dst, *args, **kwargs)

    out = tmp_path / "dest" / "slate.json"
    slate = _slate(tmp_path, "Atomic rename goal")
    monkeypatch.setattr(os, "replace", _spy)

    _write_slate(slate, out)

    monkeypatch.undo()
    assert len(calls) == 1, f"exactly one os.replace expected; got {calls}"
    src, dst = calls[0]
    assert Path(dst) == out, f"replace destination must be the target; got {dst!r}"
    assert Path(src).parent == out.parent, (
        f"the temp source must be a SIBLING of the target (same filesystem); "
        f"got {src!r} for target {str(out)!r}"
    )
    assert Path(src).name != out.name, "the temp source must not be the target itself"
    assert out.read_text(encoding="utf-8") == slate.model_dump_json(indent=2)


# ===========================================================================
# Behavior 6 --- A failed swap leaves the previous file byte-for-byte intact.
# ===========================================================================


def test_b06_failed_swap_leaves_previous_bytes_intact(tmp_path, monkeypatch):
    out, prior = _boom_scenario(tmp_path, monkeypatch)

    with pytest.raises(OSError):
        _write_slate(_slate(tmp_path, "Never lands"), out)

    monkeypatch.undo()
    assert out.read_bytes() == prior, (
        "a failed swap must never truncate or partially rewrite the target; "
        f"got {out.read_bytes()!r}"
    )


# ===========================================================================
# Behavior 7 --- A failed swap leaves no temp file.
# ===========================================================================


def test_b07_failed_swap_leaves_no_temp_file(tmp_path, monkeypatch):
    out, _prior = _boom_scenario(tmp_path, monkeypatch)

    with pytest.raises(OSError):
        _write_slate(_slate(tmp_path, "Never lands"), out)

    monkeypatch.undo()
    assert _tmp_residue(out.parent) == [], (
        f"cleanup must run on the failure path too; found {_names(out.parent)}"
    )
    assert _names(out.parent) == ["slate.json"], f"got {_names(out.parent)}"


# ===========================================================================
# Behavior 8 --- Cleanup never masks the real error.
# ===========================================================================


def test_b08_cleanup_never_masks_the_real_error(tmp_path, monkeypatch):
    out, _prior = _boom_scenario(tmp_path, monkeypatch)

    with pytest.raises(OSError) as excinfo:
        _write_slate(_slate(tmp_path, "Never lands"), out)

    monkeypatch.undo()
    assert type(excinfo.value) is OSError, (
        f"the swap's own OSError must propagate unwrapped; got {excinfo.value!r}"
    )
    assert str(excinfo.value) == "boom", (
        f"cleanup must not replace the primary error; got {str(excinfo.value)!r}"
    )


# ===========================================================================
# Behavior 9 --- The WHY is documented in code, and not over-claimed.
# ===========================================================================


def test_b09_docstring_names_the_mechanism_and_its_scope():
    doc = _write_slate.__doc__ or ""
    low = doc.lower()

    assert "os.replace" in doc, f"__doc__ must name the mechanism; got {doc!r}"
    assert "same filesystem" in low, (
        f"__doc__ must scope atomicity to the same filesystem; got {doc!r}"
    )
    assert "atomic" in low, f"__doc__ must state the guarantee; got {doc!r}"
    assert any(word in low for word in ("crash", "kill", "interrupt")), (
        f"__doc__ must name what it protects against; got {doc!r}"
    )


def test_b09b_docstring_claims_nothing_stronger():
    doc = _write_slate.__doc__ or ""
    low = doc.lower()

    for token in _OVERCLAIM_SUBSTRINGS:
        assert token not in low, (
            f"__doc__ must not claim {token!r} (not provided); got {doc!r}"
        )
    for pattern in _OVERCLAIM_PATTERNS:
        assert re.search(pattern, low) is None, (
            f"__doc__ must not claim {pattern!r} (not provided); got {doc!r}"
        )
