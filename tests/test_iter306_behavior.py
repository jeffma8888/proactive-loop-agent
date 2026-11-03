"""Factory iter 557 (ROADMAP #346): ``pla run --decline FILE`` -- a user-curated never-dispatch list.

``--decline FILE`` names goal titles, one per line (compared stripped and case-insensitively;
blank lines and ``#`` lines ignored), that ``run`` never auto-dispatches. Each skip prints
``skipped (declined): TITLE`` and ``run`` acts on the next eligible AUTO goal, or on none.
The slate itself stays unfiltered, ``--json`` keeps its 7 keys, and a missing / directory
path is a usage error (exit 2) that writes nothing -- mirroring ``--baseline``.

Black-box: every behaviour drives ``cli.main([...])`` in-process and asserts observable
stdout/stderr, exit codes and the files under ``--state-dir``. ONE collected item (the
``make readme-headroom`` budget reads binding_headroom=6), paid for by folding a 2-item
parametrize elsewhere; the eight spec behaviours live in private ``_bN_`` helpers.
Offline and deterministic: scripted provider, no subprocess, and the fixture workspace is a
private ``tmp_path`` copy whose every mtime is stamped to one known age (fresh-clone safe).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
from pathlib import Path
from typing import Final

import pytest

from proactive_loop.cli import main

REPO: Final = Path(__file__).resolve().parents[1]
FIXTURE: Final = REPO / "examples" / "fixture_workspace"
SCRIPT: Final = REPO / "examples" / "scripted_responses.json"
README: Final = REPO / "README.md"
SPEC: Final = REPO / "SPEC.md"
MARKER: Final = "PORTFOLIO INTRO"
FLAG: Final = "--decline"
TOP: Final = "Draft a learning plan and project scaffold for the agentic-loop project"
DECLINED: Final = "skipped (declined): "
DONE_PREFIX: Final = "skipped (already done): "
NOTHING: Final = "no auto-dispatchable goal in this slate; nothing to run."
ALL_DONE: Final = "every auto-dispatchable goal in this slate already has a done run ({n} skipped); nothing to run."
ALL_DECLINED: Final = (
    "every auto-dispatchable goal in this slate was declined or already done ({n} skipped); nothing to run."
)
ERR_PREFIX: Final = "error: decline file not found or not a regular file: "
JSON_KEYS: Final = frozenset(
    {"workspace_root", "slate_path", "goal_count", "needs_approval", "top_goal", "dispatched", "deferred"}
)
STAMP_AGE_SEC: Final = 6 * 60 * 60
SPEC_PIN: Final = 94_700


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


def _lines(text: str, prefix: str) -> list[str]:
    return [ln.strip() for ln in text.splitlines() if ln.strip().startswith(prefix)]


def _decline_file(path: Path, *lines: str) -> Path:
    path.write_text("".join(f"{ln}\n" for ln in lines), encoding="utf-8")
    return path


def _no_auto_script(dest: Path) -> Path:
    """The shipped script with the only AUTO goal (TOP) removed from every synthesize."""
    doc = json.loads(SCRIPT.read_text(encoding="utf-8"))
    for resp in doc["responses"]:
        if resp["tag"] == "synthesize":
            goals = [g for g in json.loads(resp["text"]) if g["title"] != TOP]
            resp["text"] = json.dumps(goals)
    dest.write_text(json.dumps(doc), encoding="utf-8")
    return dest


def _b1_help(capsys: pytest.CaptureFixture[str]) -> None:
    capsys.readouterr()
    with pytest.raises(SystemExit) as exc:
        main(["run", "--help"])
    assert exc.value.code == 0
    text = capsys.readouterr().out
    lines = text.splitlines()
    starts = [i for i, ln in enumerate(lines) if re.match(r"^\s+--decline FILE\b", ln)]
    assert len(starts) == 1, f"run --help must list `--decline FILE` exactly once:\n{text}"
    block = [lines[starts[0]]]
    for ln in lines[starts[0] + 1 :]:
        if re.match(r"^\s*-", ln) or not ln.strip():
            break
        block.append(ln)
    joined = ""
    for ln in block:  # argparse may wrap at a hyphen ("case-" / "insensitively"): rejoin it
        piece = ln.strip()
        joined += piece if joined.endswith("-") else (" " + piece if joined else piece)
    flat = " ".join(joined.split())
    body = flat.split("--decline FILE", 1)[1]
    low = body.lower()
    assert "case-insensitive" in low and "strip" in low, body
    assert re.search(r"one (title )?per line", low), body
    assert "blank" in low and "#" in body, body
    assert "skipped (declined): TITLE" in body, body
    assert re.findall(r"--[a-z][a-z-]*", body) == [], f"help names another flag: {body}"


def _b2_b3_match_and_no_match(tmp_path: Path, capsys: pytest.CaptureFixture[str], ws: Path) -> None:
    # B2: a padded, lowercased title declines TOP: no run dir, slate unfiltered, new tail.
    state = tmp_path / "s2"
    dec = _decline_file(tmp_path / "d2.txt", f"  {TOP.lower()}  ")
    rc, out, err = _run(capsys, ws, state, FLAG, str(dec))
    assert rc == 0, err
    assert _lines(out, DECLINED) == [f"{DECLINED}{TOP}"], out
    assert _run_dirs(state) == [], "a declined goal must not create a run dir"
    slate = state / "slate.json"
    assert slate.is_file() and TOP in slate.read_text(encoding="utf-8"), "the slate stays unfiltered"
    assert out.rstrip().splitlines()[-1].strip() == ALL_DECLINED.format(n=1), out
    assert NOTHING not in out and f"auto-dispatching top goal: {TOP}" not in out

    # B3: blank lines, comments and a non-matching title change nothing.
    state = tmp_path / "s3"
    dec = _decline_file(tmp_path / "d3.txt", "", "   ", f"# {TOP}", "#", "Some goal that is not on the slate", "")
    rc, out, err = _run(capsys, ws, state, FLAG, str(dec))
    assert rc == 0, err
    assert not _lines(out, DECLINED) and not _lines(err, DECLINED), out
    assert len(_run_dirs(state)) == 1, "an inert decline file must still dispatch TOP"
    assert f"auto-dispatching top goal: {TOP}" in out


def _b4_with_skip_done(tmp_path: Path, capsys: pytest.CaptureFixture[str], ws: Path) -> None:
    state = tmp_path / "s4"
    assert _run(capsys, ws, state)[0] == 0
    (done_dir,) = _run_dirs(state)
    dec = _decline_file(tmp_path / "d4.txt", TOP)
    inert = _decline_file(tmp_path / "d4-inert.txt", "# nothing declined")

    # Declined AND done: the declined check wins, counted once.
    rc, out, err = _run(capsys, ws, state, FLAG, str(dec), "--skip-done")
    assert rc == 0, err
    assert _lines(out, DECLINED) == [f"{DECLINED}{TOP}"], out
    assert not _lines(out, DONE_PREFIX), out
    assert out.rstrip().splitlines()[-1].strip() == ALL_DECLINED.format(n=1), out
    assert _run_dirs(state) == [done_dir]

    # Nothing declined: the --skip-done-only tail is byte-identical.
    rc, out, err = _run(capsys, ws, state, FLAG, str(inert), "--skip-done")
    assert rc == 0, err
    assert _lines(out, DONE_PREFIX) == [f"{DONE_PREFIX}{TOP} -> {done_dir.name}"], out
    assert not _lines(out, DECLINED)
    assert out.rstrip().splitlines()[-1].strip() == ALL_DONE.format(n=1), out

    # Nothing skipped at all: the genuine-empty tail is byte-identical.
    script = _no_auto_script(tmp_path / "no-auto.json")
    s_empty = tmp_path / "s4-empty"
    rc, out, err = _run(capsys, ws, s_empty, FLAG, str(dec), "--skip-done", script=script)
    assert rc == 0, err
    assert not _lines(out, DECLINED) and not _lines(out, DONE_PREFIX), out
    assert out.rstrip().splitlines()[-1].strip() == NOTHING, out
    assert _run_dirs(s_empty) == []


def _b5_b6_dry_run_and_json(tmp_path: Path, capsys: pytest.CaptureFixture[str], ws: Path) -> None:
    dec = _decline_file(tmp_path / "d5.txt", TOP)

    # B5: --dry-run prints the same skip line and tail, creates no run dir.
    state = tmp_path / "s5"
    rc, out, err = _run(capsys, ws, state, FLAG, str(dec), "--dry-run")
    assert rc == 0, err
    assert _lines(out, DECLINED) == [f"{DECLINED}{TOP}"], out
    assert out.rstrip().splitlines()[-1].strip() == ALL_DECLINED.format(n=1), out
    assert _run_dirs(state) == []

    # B6: --json stays one 7-key object; the skip line moves to stderr.
    state = tmp_path / "s6"
    rc, out, err = _run(capsys, ws, state, FLAG, str(dec), "--json")
    assert rc == 0, err
    doc = json.loads(out)
    assert isinstance(doc, dict) and set(doc) == JSON_KEYS, sorted(doc)
    assert doc["top_goal"] is None
    assert DECLINED not in out, "the skip line must not pollute JSON stdout"
    assert _lines(err, DECLINED) == [f"{DECLINED}{TOP}"], err
    assert _run_dirs(state) == []


def _b7_bad_path(tmp_path: Path, capsys: pytest.CaptureFixture[str], ws: Path) -> None:
    a_dir = tmp_path / "a-dir"
    a_dir.mkdir()
    cases = [tmp_path / "missing.txt", a_dir]
    assert len(cases) == 2
    for i, bad in enumerate(cases):
        state = tmp_path / f"s7-{i}"
        rc, out, err = _run(capsys, ws, state, FLAG, str(bad))
        assert rc == 2, (bad, rc, out, err)
        err_lines = [ln for ln in err.splitlines() if ln.strip()]
        assert len(err_lines) == 1 and err_lines[0].startswith(ERR_PREFIX), err
        assert "Traceback" not in err and "Traceback" not in out
        assert not (state / "slate.json").exists(), "a usage error must write no slate"
        assert _run_dirs(state) == []


def _b8_docs() -> None:
    readme = README.read_text(encoding="utf-8")
    idx = readme.find(MARKER)
    assert idx >= 0
    below = readme[idx:]
    rows = [ln for ln in below.splitlines() if ln.startswith("|") and "`pla run" in ln or ln.startswith("| `run")]
    run_rows = [ln for ln in rows if "--decline FILE" in ln]
    assert run_rows, "README CLI-table run row must name --decline FILE"
    assert any("skipped (declined): TITLE" in ln for ln in run_rows), run_rows
    raw = SPEC.read_bytes()
    assert len(raw) <= SPEC_PIN, len(raw)
    assert "[--decline FILE]" in raw.decode("utf-8")


def test_iter557_run_decline_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _clean_env(monkeypatch)
    ws = _workspace(tmp_path)
    _b1_help(capsys)
    _b2_b3_match_and_no_match(tmp_path, capsys, ws)
    _b4_with_skip_done(tmp_path, capsys, ws)
    _b5_b6_dry_run_and_json(tmp_path, capsys, ws)
    _b7_bad_path(tmp_path, capsys, ws)
    _b8_docs()
