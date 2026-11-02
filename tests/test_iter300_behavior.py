"""Factory iter 551 (ROADMAP #340): ``pla run --skip-done`` closes the L1 -> L2 feedback loop.

Before this flag, two ``pla run`` calls into one ``--state-dir`` re-dispatched the SAME
finished goal twice (two ``done`` run dirs, identical title). ``--skip-done`` is opt-in: it
skips every AUTO_DISPATCH goal whose normalized title (``strip().lower()``) already has a
``done`` run under the state dir, prints ``skipped (already done): TITLE -> RUN_ID``, and acts
on the next eligible AUTO goal or on none. Only ``done`` suppresses; ``--json`` keeps its 7 keys.

Black-box: every behaviour drives ``cli.main([...])`` in-process and asserts observable
stdout/stderr, exit codes and the files under ``--state-dir``. ONE collected item (the
``make readme-headroom`` budget reads binding_headroom=6, so the real budget is zero);
the nine spec behaviours live in private helpers called from it.
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
from typing import Any, Final

import pytest

from proactive_loop.cli import main

REPO: Final = Path(__file__).resolve().parents[1]
FIXTURE: Final = REPO / "examples" / "fixture_workspace"
SCRIPT: Final = REPO / "examples" / "scripted_responses.json"
README: Final = REPO / "README.md"
MARKER: Final = "PORTFOLIO INTRO"
FLAG: Final = "--skip-done"
TOP: Final = "Draft a learning plan and project scaffold for the agentic-loop project"
SECOND: Final = "Write an eval checklist for the agentic-loop harness"
SKIP_PREFIX: Final = "skipped (already done): "
NOTHING: Final = "no auto-dispatchable goal in this slate; nothing to run."
JSON_KEYS: Final = frozenset(
    {"workspace_root", "slate_path", "goal_count", "needs_approval", "top_goal", "dispatched", "deferred"}
)
STAMP_AGE_SEC: Final = 6 * 60 * 60
HEX_ID: Final = re.compile(r"\b[0-9a-f]{12}\b")
NON_DONE: Final = ("failed", "budget_exhausted", "running", "pending")


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


def _checkpoint(run_dir: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((run_dir / "checkpoint.json").read_text(encoding="utf-8"))
    return data


def _write_checkpoint(run_dir: Path, data: dict[str, Any]) -> None:
    (run_dir / "checkpoint.json").write_text(json.dumps(data), encoding="utf-8")


def _skip_lines(text: str) -> list[str]:
    return [ln.strip() for ln in text.splitlines() if ln.strip().startswith(SKIP_PREFIX)]


def _two_auto_script(dest: Path) -> Path:
    """The shipped script, with a second (lower-ranked) learning goal in every synthesize."""
    doc = json.loads(SCRIPT.read_text(encoding="utf-8"))
    for resp in doc["responses"]:
        if resp["tag"] == "synthesize":
            goals = json.loads(resp["text"])
            base = next(g for g in goals if g["title"] == TOP)
            goals.append(dict(base, title=SECOND, impact=4.0, urgency=3.0))
            resp["text"] = json.dumps(goals)
    dest.write_text(json.dumps(doc), encoding="utf-8")
    return dest


def _titles(entries: list[Any]) -> list[str]:
    return [e if isinstance(e, str) else e["title"] for e in entries]


def _b1_b4_b8_default_first_run_skip_json_and_dry_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], ws: Path
) -> None:

    # B1: without the flag, two runs re-dispatch the same goal -> 2 done run dirs (unchanged).
    s1 = tmp_path / "s1"
    outs = []
    for _ in range(2):
        rc, out, _err = _run(capsys, ws, s1)
        assert rc == 0
        assert not _skip_lines(out), "the default path never prints a skip line"
        outs.append(out)
    dirs = _run_dirs(s1)
    assert len(dirs) == 2, f"default behaviour must still re-dispatch: {dirs}"
    assert [_checkpoint(d)["status"] for d in dirs] == ["done", "done"]
    assert {_checkpoint(d)["goal"]["title"] for d in dirs} == {TOP}

    # B2: first --skip-done run on an empty state dir dispatches exactly as a flagless run.
    s2 = tmp_path / "s2"
    rc, out, err = _run(capsys, ws, s2, FLAG)
    assert rc == 0
    dirs = _run_dirs(s2)
    assert len(dirs) == 1 and _checkpoint(dirs[0])["status"] == "done"
    assert not _skip_lines(out) and not _skip_lines(err), "nothing done yet -> nothing skipped"
    assert f"auto-dispatching top goal: {TOP}" in out
    done_id = dirs[0].name

    # B3: the second --skip-done run skips the done goal and creates no run dir.
    (s2 / "slate.json").unlink()
    rc, out, _err = _run(capsys, ws, s2, FLAG)
    assert rc == 0
    assert _run_dirs(s2) == dirs, "a skipped goal must not create a run dir"
    assert _skip_lines(out) == [f"{SKIP_PREFIX}{TOP} -> {done_id}"], out
    assert NOTHING in out
    assert (s2 / "slate.json").is_file(), "the slate is still written on a skip"

    # B4: --json stays one 7-key document; the skip line moves to stderr.
    rc, out, err = _run(capsys, ws, s2, FLAG, "--json")
    assert rc == 0
    doc = json.loads(out)
    assert isinstance(doc, dict) and set(doc) == JSON_KEYS, sorted(doc)
    assert doc["top_goal"] is None and doc["dispatched"] is None
    assert TOP not in _titles(doc["deferred"]), "a skipped goal is not 'deferred'"
    assert len(doc["needs_approval"]) == 2
    assert not _skip_lines(out), "the skip line must not pollute JSON stdout"
    assert _skip_lines(err) == [f"{SKIP_PREFIX}{TOP} -> {done_id}"], err
    assert _run_dirs(s2) == dirs

    # B8: --dry-run honours the skip and creates no run dir.
    rc, out, _err = _run(capsys, ws, s2, FLAG, "--dry-run")
    assert rc == 0
    assert _skip_lines(out) == [f"{SKIP_PREFIX}{TOP} -> {done_id}"], out
    assert NOTHING in out
    assert _run_dirs(s2) == dirs

    # B1 (stdout identity): flagless output is unaffected by the flag's existence -- two
    # fresh flagless runs into fresh state dirs print the same text modulo the run id.
    s3 = tmp_path / "s3"
    _rc, out3, _ = _run(capsys, ws, s3)

    def _norm(text: str, state: Path) -> str:
        return HEX_ID.sub("ID", text.replace(str(state), "S"))

    assert _norm(out3, s3) == _norm(outs[0], s1), "flagless stdout must be stable"


def _b5_b6_b7_only_done_suppresses_normalized_match_and_next_auto_goal(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], ws: Path
) -> None:

    # B5: every non-done status re-dispatches; a garbage / missing checkpoint suppresses nothing.
    assert len(NON_DONE) == 4
    for status in NON_DONE:
        state = tmp_path / f"st-{status}"
        assert _run(capsys, ws, state, FLAG)[0] == 0
        (only,) = _run_dirs(state)
        data = _checkpoint(only)
        data["status"] = status
        _write_checkpoint(only, data)
        junk = state / "run-zzzzzzzzzzzz"
        junk.mkdir()
        (junk / "checkpoint.json").write_text("{not json", encoding="utf-8")
        (state / "run-yyyyyyyyyyyy").mkdir()
        rc, out, _err = _run(capsys, ws, state, FLAG)
        assert rc == 0, f"status {status!r}: the verb must not crash on bad checkpoints"
        assert not _skip_lines(out), f"status {status!r} must not suppress"
        assert f"auto-dispatching top goal: {TOP}" in out
        new = [d for d in _run_dirs(state) if d not in (only, junk, state / "run-yyyyyyyyyyyy")]
        assert len(new) == 1 and _checkpoint(new[0])["status"] == "done", status

    # B6: case / surrounding-whitespace differences in the persisted title still match.
    for variant in (TOP.upper(), f"  {TOP}\t ", f" {TOP.lower()} "):
        state = tmp_path / f"norm-{len(variant)}-{variant[:3].strip() or 'ws'}"
        assert _run(capsys, ws, state, FLAG)[0] == 0
        (only,) = _run_dirs(state)
        data = _checkpoint(only)
        data["goal"]["title"] = variant
        _write_checkpoint(only, data)
        rc, out, _err = _run(capsys, ws, state, FLAG)
        assert rc == 0
        assert _run_dirs(state) == [only], f"normalized match failed for {variant!r}"
        assert _skip_lines(out) == [f"{SKIP_PREFIX}{TOP} -> {only.name}"], out
    # ...but a genuinely different title is not a match (exact on the normalized form).
    state = tmp_path / "norm-diff"
    assert _run(capsys, ws, state, FLAG)[0] == 0
    (only,) = _run_dirs(state)
    data = _checkpoint(only)
    data["goal"]["title"] = TOP + " v2"
    _write_checkpoint(only, data)
    rc, out, _err = _run(capsys, ws, state, FLAG)
    assert rc == 0 and not _skip_lines(out) and len(_run_dirs(state)) == 2

    # B7: with two AUTO goals, a done top goal hands dispatch to the next one in rank order.
    script = _two_auto_script(tmp_path / "two_auto.json")
    state = tmp_path / "two"
    rc, out, _err = _run(capsys, ws, state, "--json", script=script)
    assert rc == 0
    doc = json.loads(out)
    assert doc["top_goal"]["title"] == TOP and _titles(doc["deferred"]) == [SECOND], doc
    (first,) = _run_dirs(state)
    rc, out, err = _run(capsys, ws, state, FLAG, "--json", script=script)
    assert rc == 0
    doc = json.loads(out)
    assert set(doc) == JSON_KEYS
    assert doc["top_goal"]["title"] == SECOND, "the next non-done AUTO goal becomes top_goal"
    assert doc["dispatched"] is not None and doc["dispatched"]["status"] == "done"
    assert _titles(doc["deferred"]) == [], "neither the skipped nor the dispatched goal is deferred"
    assert _skip_lines(err) == [f"{SKIP_PREFIX}{TOP} -> {first.name}"], err
    assert len(_run_dirs(state)) == 2
    # Both AUTO goals now done -> a third run skips both, in rank order, and runs nothing.
    rc, out, _err = _run(capsys, ws, state, FLAG, script=script)
    assert rc == 0
    skips = _skip_lines(out)
    assert [s.split(" -> ")[0] for s in skips] == [f"{SKIP_PREFIX}{TOP}", f"{SKIP_PREFIX}{SECOND}"]
    assert NOTHING in out and len(_run_dirs(state)) == 2


def _b9_skip_done_is_in_run_help_and_the_readme_run_row(capsys: pytest.CaptureFixture[str]) -> None:
    # B9: run --help lists the flag, and its help text names none of the rindex-graded flags.
    with pytest.raises(SystemExit) as excinfo:
        main(["run", "--help"])
    assert excinfo.value.code == 0
    help_text = capsys.readouterr().out
    assert FLAG in help_text
    lines = help_text.splitlines()
    at = next(i for i, ln in enumerate(lines) if ln.strip().startswith(FLAG))
    end = next(
        (i for i in range(at + 1, len(lines)) if lines[i].strip().startswith("-")), len(lines)
    )
    block = " ".join(ln.strip() for ln in lines[at:end]).removeprefix(FLAG)
    for banned in ("--json", "--exclude-path", "--baseline", "--snapshot", "--collector", "--dry-run"):
        assert banned not in block, f"{FLAG} help must not name {banned}: {block!r}"
    assert "done" in block

    readme = README.read_text(encoding="utf-8")
    below = readme[readme.index(MARKER) :]
    rows = [ln for ln in below.splitlines() if ln.startswith("| `run`")]
    assert len(rows) == 1, rows
    row = rows[0]
    assert row.count(f"`{FLAG}`") == 1, "the run row documents the flag once"
    clause = row[row.index(f"`{FLAG}`") :]
    for token in ("opt-in", "strip().lower()", "only `done` suppresses", "skipped (already done)", "unchanged"):
        assert token in clause, f"README run-row clause lacks {token!r}"
    assert f"`{FLAG}`" not in readme[: readme.index(MARKER)], "the human-owned intro is untouched"


def test_run_skip_done_behaviours_b1_through_b9(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _clean_env(monkeypatch)
    ws = _workspace(tmp_path)
    for sub in ("a", "b"):
        (tmp_path / sub).mkdir()
    _b1_b4_b8_default_first_run_skip_json_and_dry_run(tmp_path / "a", capsys, ws)
    _b5_b6_b7_only_done_suppresses_normalized_match_and_next_auto_goal(tmp_path / "b", capsys, ws)
    _b9_skip_done_is_in_run_help_and_the_readme_run_row(capsys)
