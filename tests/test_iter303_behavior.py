"""Factory iter 554 (ROADMAP #343): an all-skipped ``pla run --skip-done`` names the skip.

Before this fix, a ``run --skip-done`` whose every AUTO_DISPATCH goal already had a ``done``
run printed ``skipped (already done): ...`` and THEN the false tail
``no auto-dispatchable goal in this slate; nothing to run.`` -- there was one, it was skipped.
The tail now reads ``every auto-dispatchable goal in this slate already has a done run
(N skipped); nothing to run.``; the genuinely-empty slate keeps the OLD line byte-for-byte.

Black-box: every behaviour drives ``cli.main([...])`` in-process and asserts observable
stdout/stderr, exit codes and files under ``--state-dir``. ONE collected item (the
``make readme-headroom`` budget reads binding_headroom=6); the spec behaviours live in private
helpers called from it. Offline and deterministic: scripted provider only, and the fixture
workspace is a private ``tmp_path`` copy whose every mtime is stamped to one known age.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from typing import Any, Final

import pytest

from proactive_loop.cli import main

REPO: Final = Path(__file__).resolve().parents[1]
FIXTURE: Final = REPO / "examples" / "fixture_workspace"
SCRIPT: Final = REPO / "examples" / "scripted_responses.json"
README: Final = REPO / "README.md"
SPEC: Final = REPO / "SPEC.md"
MARKER: Final = "PORTFOLIO INTRO"
FLAG: Final = "--skip-done"
TOP: Final = "Draft a learning plan and project scaffold for the agentic-loop project"
SECOND: Final = "Write an eval checklist for the agentic-loop harness"
SKIP_PREFIX: Final = "skipped (already done): "
OLD: Final = "no auto-dispatchable goal in this slate; nothing to run."
NEW: Final = "every auto-dispatchable goal in this slate already has a done run ({n} skipped); nothing to run."
NEW_STEM: Final = "already has a done run"
DRY_DISPATCH: Final = "[dry-run] would auto-dispatch"
JSON_KEYS: Final = frozenset(
    {"workspace_root", "slate_path", "goal_count", "needs_approval", "top_goal", "dispatched", "deferred"}
)
STAMP_AGE_SEC: Final = 6 * 60 * 60


def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("PLA_"):
            monkeypatch.delenv(key, raising=False)


def _workspace(root: Path) -> Path:
    dest = root / "ws"
    shutil.copytree(FIXTURE, dest)
    stamp = time.time() - STAMP_AGE_SEC
    for path in [dest, *dest.rglob("*")]:
        os.utime(path, (stamp, stamp))
    return dest


def _run(
    capsys: pytest.CaptureFixture[str], ws: Path, state: Path, *extra: str, script: Path = SCRIPT
) -> tuple[int, str, str]:
    capsys.readouterr()
    rc = main(
        [
            "run",
            "--workspace",
            str(ws),
            "--provider",
            "scripted",
            "--scripted-responses",
            str(script),
            "--state-dir",
            str(state),
            *extra,
        ]
    )
    out = capsys.readouterr()
    return rc, out.out, out.err


def _run_dirs(state: Path) -> list[Path]:
    return sorted(p for p in state.glob("run-*") if p.is_dir()) if state.exists() else []


def _lines(text: str) -> list[str]:
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def _skip_lines(text: str) -> list[str]:
    return [ln for ln in _lines(text) if ln.startswith(SKIP_PREFIX)]


def _rewrite_synth(dest: Path, edit: Any) -> Path:
    doc = json.loads(SCRIPT.read_text(encoding="utf-8"))
    for resp in doc["responses"]:
        if resp["tag"] == "synthesize":
            resp["text"] = json.dumps(edit(json.loads(resp["text"])))
    dest.write_text(json.dumps(doc), encoding="utf-8")
    return dest


def _two_auto(goals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    base = next(g for g in goals if g["title"] == TOP)
    return [*goals, dict(base, title=SECOND, impact=4.0, urgency=3.0)]


def _no_auto(goals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [g for g in goals if g["title"] != TOP]


def _assert_new_tail(text: str, n: int, where: str) -> None:
    lines = _lines(text)
    skips = [i for i, ln in enumerate(lines) if ln.startswith(SKIP_PREFIX)]
    assert len(skips) == n, f"{where}: expected {n} skip lines: {lines}"
    hits = [i for i, ln in enumerate(lines) if ln == NEW.format(n=n)]
    assert len(hits) == 1, f"{where}: NEW({n}) tail missing or repeated: {lines}"
    assert hits[0] > max(skips), f"{where}: the NEW tail must follow every skip line"
    assert OLD not in text, f"{where}: the false OLD tail is still printed"


def _b1_b3_b4_single_auto_all_skipped(tmp_path: Path, capsys: pytest.CaptureFixture[str], ws: Path) -> None:
    state = tmp_path / "s1"
    rc, out, _err = _run(capsys, ws, state, FLAG)
    assert rc == 0
    (done,) = _run_dirs(state)
    (state / "slate.json").unlink()

    # B1: all-skipped human run -> skip line, then NEW(1); no OLD; no new run dir; slate written.
    rc, out, err = _run(capsys, ws, state, FLAG)
    assert rc == 0
    assert _skip_lines(out) == [f"{SKIP_PREFIX}{TOP} -> {done.name}"], out
    _assert_new_tail(out, 1, "B1 stdout")
    assert OLD not in err and NEW_STEM not in err, err
    assert _run_dirs(state) == [done]
    assert (state / "slate.json").is_file()

    # B3: --json keeps the 7-key document; skip + NEW on stderr, neither tail on stdout.
    rc, out, err = _run(capsys, ws, state, FLAG, "--json")
    assert rc == 0
    doc = json.loads(out)
    assert isinstance(doc, dict) and set(doc) == JSON_KEYS, sorted(doc)
    assert doc["top_goal"] is None and doc["dispatched"] is None and doc["deferred"] == []
    assert NEW_STEM not in out and OLD not in out and SKIP_PREFIX not in out
    _assert_new_tail(err, 1, "B3 stderr")
    assert _run_dirs(state) == [done]

    # B4: --dry-run prints NEW(1), never OLD, no would-dispatch line, no run dir.
    rc, out, err = _run(capsys, ws, state, FLAG, "--dry-run")
    assert rc == 0
    _assert_new_tail(out, 1, "B4 stdout")
    assert DRY_DISPATCH not in out + err
    assert OLD not in err
    assert _run_dirs(state) == [done]


def _b2_b6_two_auto(tmp_path: Path, capsys: pytest.CaptureFixture[str], ws: Path) -> None:
    script = _rewrite_synth(tmp_path / "two.json", _two_auto)
    state = tmp_path / "s2"
    # First --skip-done: nothing done -> top goal dispatched, neither tail.
    rc, out, err = _run(capsys, ws, state, FLAG, script=script)
    assert rc == 0 and len(_run_dirs(state)) == 1
    assert f"auto-dispatching top goal: {TOP}" in out
    assert OLD not in out + err and NEW_STEM not in out + err

    # B6: one of two AUTO goals done -> the other is previewed / dispatched; neither tail.
    rc, out, err = _run(capsys, ws, state, FLAG, "--dry-run", script=script)
    assert rc == 0 and len(_run_dirs(state)) == 1
    assert DRY_DISPATCH in out and SECOND in out
    assert len(_skip_lines(out)) == 1
    assert OLD not in out + err and NEW_STEM not in out + err
    rc, out, err = _run(capsys, ws, state, FLAG, script=script)
    assert rc == 0 and len(_run_dirs(state)) == 2
    assert f"auto-dispatching top goal: {SECOND}" in out
    assert OLD not in out + err and NEW_STEM not in out + err

    # B2: both done -> two skip lines in rank order, then NEW(2).
    rc, out, err = _run(capsys, ws, state, FLAG, script=script)
    assert rc == 0 and len(_run_dirs(state)) == 2
    assert [s.split(" -> ")[0] for s in _skip_lines(out)] == [f"{SKIP_PREFIX}{TOP}", f"{SKIP_PREFIX}{SECOND}"]
    _assert_new_tail(out, 2, "B2 stdout")
    assert NEW.format(n=1) not in out


def _b5_b7_no_auto_and_flagless(tmp_path: Path, capsys: pytest.CaptureFixture[str], ws: Path) -> None:
    # B5: a slate with no AUTO goal keeps OLD, with or without the flag (and under --dry-run).
    script = _rewrite_synth(tmp_path / "none.json", _no_auto)
    cases = ((), (FLAG,), (FLAG, "--dry-run"), ("--dry-run",))
    assert len(cases) == 4
    for i, extra in enumerate(cases):
        state = tmp_path / f"none{i}"
        rc, out, err = _run(capsys, ws, state, *extra, script=script)
        assert rc == 0, extra
        assert OLD in _lines(out), f"{extra}: the genuinely-empty tail must stay OLD: {out}"
        assert NEW_STEM not in out + err and SKIP_PREFIX not in out + err, extra
        assert _run_dirs(state) == [], extra

    # B7: flagless never skips and never prints the skipped wording, even into a done state dir.
    state = tmp_path / "flagless"
    outs = []
    for _ in range(2):
        rc, out, err = _run(capsys, ws, state)
        assert rc == 0
        assert SKIP_PREFIX not in out + err and NEW_STEM not in out + err and OLD not in out + err
        outs.append(out)
    assert len(_run_dirs(state)) == 2, "flagless re-dispatches (unchanged)"
    rc, out, err = _run(capsys, ws, state, "--json")
    assert rc == 0 and set(json.loads(out)) == JSON_KEYS
    assert json.loads(out)["top_goal"]["title"] == TOP
    assert SKIP_PREFIX not in out + err and NEW_STEM not in out + err


def _b8_docs() -> None:
    readme = README.read_text(encoding="utf-8")
    at = readme.index(MARKER)
    assert NEW_STEM not in readme[:at], "the human-owned intro is untouched"
    rows = [ln for ln in readme[at:].splitlines() if ln.startswith("| `run`")]
    assert len(rows) == 1, rows
    clause = rows[0][rows[0].index(f"`{FLAG}`") :]
    for token in (NEW_STEM, "opt-in", "strip().lower()", "only `done` suppresses", "skipped (already done)", "unchanged"):
        assert token in clause, f"README run-row --skip-done clause lacks {token!r}"
    spec = SPEC.read_text(encoding="utf-8")
    at = spec.index(f"`{FLAG}` (opt-in)")
    end = spec.find("\n  - ", at)
    sentence = " ".join(spec[at : end if end != -1 else None].split())
    assert "all-skip" in sentence or NEW_STEM in sentence, f"SPEC --skip-done clause names the all-skip tail: {sentence}"


def test_run_skip_done_all_skipped_tail_behaviours_b1_through_b8(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _clean_env(monkeypatch)
    ws = _workspace(tmp_path)
    for sub in ("a", "b", "c"):
        (tmp_path / sub).mkdir()
    _b1_b3_b4_single_auto_all_skipped(tmp_path / "a", capsys, ws)
    _b2_b6_two_auto(tmp_path / "b", capsys, ws)
    _b5_b7_no_auto_and_flagless(tmp_path / "c", capsys, ws)
    _b8_docs()
