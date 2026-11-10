"""Factory iter 565 (ROADMAP #353): paste-ready ``pla dispatch`` hints select by ``--title``.

Every paste-ready hint ``run`` / ``dispatch --dry-run`` prints -- the dry-run top-goal line, the
deferred auto-approved block, the needs-approval ``--yes`` block and the dispatch preview's "run
it for real" command -- now selects the goal with ``--title <shlex-quoted title>`` whenever that
title's normalized (``strip().lower()``) key is unique in the slate, so a hint copied before the
next rescan still resolves. A goal sharing its normalized title with another keeps ``--goal-id``
(``--title`` picks the FIRST match, so a title hint could approve the wrong goal). ``--json``
documents, exit codes and the ``[dry-run] would dispatch goal <id>`` header are unchanged.

Black-box: ``pla run`` / ``pla scan`` / ``pla dispatch`` are driven in-process through
``cli.main``; only exit codes, stdout and the written slate are read. ONE collected item
(``make readme-headroom`` binding_headroom is pinned >= 6 by test_iter263/270), funded by the
engineer's fold of a 2-case parametrize. Offline and deterministic: scripted provider, every
state dir under ``tmp_path``, the fixture workspace a private copy stamped to one known age.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import time
from pathlib import Path
from typing import Final

import pytest

from proactive_loop import cli

REPO: Final = Path(__file__).resolve().parents[1]
FIXTURE: Final = REPO / "examples" / "fixture_workspace"
SCRIPT: Final = REPO / "examples" / "scripted_responses.json"
STAMP_AGE_SEC: Final = 6 * 60 * 60
TOP_PREFIX: Final = "[dry-run] would auto-dispatch top goal: "
PREVIEW_PREFIX: Final = "[dry-run] would dispatch goal "
NEEDS_HEADER: Final = "goal(s) need approval and were NOT auto-run:"
DEFERRED_HEADER: Final = "were auto-approved but NOT run"
RUN_JSON_KEYS: Final = {
    "workspace_root", "slate_path", "goal_count", "needs_approval",
    "top_goal", "dispatched", "deferred",
}  # fmt: skip

QUOTED: Final = "Don't pay $5 fees"
AUTO_TOP: Final = "Draft the alpha learning plan"
SENSITIVE: Final = "Sort out a personal tax question"
LOW: Final = "Refresh portfolio talking points"

Result = tuple[int, str, str]


def _goal(title: str, category: str, impact: float, urgency: float, conf: float = 1.0) -> dict[str, object]:
    return {
        "title": title, "rationale": f"iter-565 fixture: {title}", "category": category,
        "impact": impact, "urgency": urgency, "confidence": conf, "effort_weight": 1.0,
        "appropriate_now": True, "sources": ["notes/journal.md"],
        "suggested_first_steps": ["write the artifact"],
    }  # fmt: skip


# 2 AUTO_DISPATCH (25 / 20, the second carrying a space + apostrophe + `$`) + 2 NEEDS_APPROVAL.
GOALS: Final = [
    _goal(AUTO_TOP, "project", 5.0, 5.0),
    _goal(QUOTED, "project", 5.0, 4.0),
    _goal(SENSITIVE, "finance_legal", 5.0, 2.0),
    _goal(LOW, "career", 1.0, 1.0, 0.5),
]


def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("PLA_"):
            monkeypatch.delenv(key, raising=False)


def _pla(capsys: pytest.CaptureFixture[str], argv: list[str]) -> Result:
    capsys.readouterr()
    try:
        rc = cli.main(argv)
    except SystemExit as exc:
        rc = exc.code if isinstance(exc.code, int) else 2
    out = capsys.readouterr()
    return rc, out.out, out.err


def _workspace(root: Path) -> Path:
    ws = root / "ws"
    shutil.copytree(FIXTURE, ws)
    stamp = time.time() - STAMP_AGE_SEC
    for path in [ws, *ws.rglob("*")]:
        os.utime(path, (stamp, stamp))
    return ws


def _script(path: Path, goals: list[dict[str, object]]) -> Path:
    doc = json.loads(SCRIPT.read_text(encoding="utf-8"))
    for entry in doc["responses"]:
        if entry["tag"] == "synthesize":
            entry["text"] = json.dumps(goals)
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def _run_argv(ws: Path, script: Path, sd: Path, *extra: str) -> list[str]:
    return [
        "run", "--workspace", str(ws), "--provider", "scripted",
        "--scripted-responses", str(script), "--state-dir", str(sd), *extra,
    ]  # fmt: skip


def _block(out: str, header: str) -> list[str]:
    lines = out.splitlines()
    start = next(i for i, ln in enumerate(lines) if header in ln)
    block: list[str] = []
    for ln in lines[start + 1 :]:
        if not ln.strip():
            break
        block.append(ln)
    return block


def _pairs(block: list[str]) -> list[tuple[str, str]]:
    """(title, command line) for every ``  - <title>`` entry and the line right after it."""
    out: list[tuple[str, str]] = []
    for i, ln in enumerate(block):
        if ln.startswith("  - "):
            out.append((ln[4:], block[i + 1]))
    return out


def _selector(cmd: str) -> tuple[str, str]:
    argv = shlex.split(cmd)
    assert argv[:2] == ["pla", "dispatch"], argv
    if "--title" in argv:
        assert "--goal-id" not in argv, argv
        return "--title", argv[argv.index("--title") + 1]
    return "--goal-id", argv[argv.index("--goal-id") + 1]


def _paste(capsys: pytest.CaptureFixture[str], cmd: str, sd: Path) -> Result:
    argv = shlex.split(cmd)
    assert argv[:2] == ["pla", "dispatch"], argv
    return _pla(capsys, [*argv[1:], "--state-dir", str(sd), "--dry-run"])


def _b1_b2_b3_b7_run_hints_print_quoted_title(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ws = _workspace(root)
    script = _script(root / "s.json", GOALS)
    sd = root / "S"
    rc, out, err = _pla(capsys, _run_argv(ws, script, sd, "--dry-run"))
    assert rc == 0, err
    abs_slate = str((sd / "slate.json").resolve())
    lines = out.splitlines()

    # B1: the top-goal line is followed by the exact --title hint, no --goal-id.
    top_i = next(i for i, ln in enumerate(lines) if ln.startswith(TOP_PREFIX))
    assert lines[top_i] == TOP_PREFIX + AUTO_TOP
    assert lines[top_i + 1] == f"  pla dispatch --slate {abs_slate} --title {shlex.quote(AUTO_TOP)}"
    assert "--goal-id" not in lines[top_i + 1]

    # B3: deferred auto-approved block -> --title, no --yes.
    deferred = _pairs(_block(out, DEFERRED_HEADER))
    assert deferred == [
        (QUOTED, f"      pla dispatch --slate {abs_slate} --title {shlex.quote(QUOTED)}")
    ], deferred

    # B2: needs-approval block -> --title ... --yes for every entry, in rank order.
    needs = _pairs(_block(out, NEEDS_HEADER))
    assert needs == [
        (t, f"      pla dispatch --slate {abs_slate} --title {shlex.quote(t)} --yes")
        for t in (SENSITIVE, LOW)
    ], needs
    assert "--goal-id" not in out

    # B7: the quoted title round-trips through shlex and the pasted command selects it.
    assert _selector(deferred[0][1]) == ("--title", QUOTED)
    rc, pout, perr = _paste(capsys, deferred[0][1], sd)
    assert rc == 0, perr
    header = [ln for ln in pout.splitlines() if ln.startswith(PREVIEW_PREFIX)]
    assert len(header) == 1 and header[0].endswith(f": {QUOTED}"), pout


def _b4_b6_dispatch_preview_and_duplicate_fallback(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ws = _workspace(root)
    script = _script(root / "s.json", GOALS)
    sd = root / "S"
    rc, _, err = _pla(capsys, _run_argv(ws, script, sd, "--dry-run"))
    assert rc == 0, err
    slate = sd / "slate.json"
    doc = json.loads(slate.read_text(encoding="utf-8"))
    by_title = {str(g["title"]): str(g["id"]) for g in doc["goals"]}
    abs_slate = str(slate.resolve())

    # B4: --goal-id and --title previews print the same --title real command; --yes only
    # for NEEDS_APPROVAL (whose dry-run already needs --yes, exit 4 otherwise, as before);
    # the header still names the id.
    for title, yes in ((AUTO_TOP, ""), (QUOTED, ""), (SENSITIVE, " --yes")):
        gid = by_title[title]
        want = f"pla dispatch --slate {abs_slate} --title {shlex.quote(title)}{yes}"
        base = ["dispatch", "--dry-run", "--slate", str(slate), "--state-dir", str(sd), *yes.split()]
        by_id = _pla(capsys, [*base, "--goal-id", gid])
        by_t = _pla(capsys, [*base, "--title", title])
        assert by_id[0] == 0 and by_t == by_id, (by_id, by_t)
        cmds = [ln.strip() for ln in by_id[1].splitlines() if ln.strip().startswith("pla dispatch")]
        assert cmds == [want], by_id[1]
        assert f"{PREVIEW_PREFIX}{gid}: {title}" in by_id[1].splitlines()

    # B6: two goals sharing a normalized title fall back to --goal-id; a unique one keeps --title.
    auto = next(g for g in doc["goals"] if g["title"] == AUTO_TOP)
    a = dict(auto, title="Fix X", id="aaaa00000001")
    b = dict(auto, title=" fix x ", id="bbbb00000002")
    dup = dict(doc, goals=[a, b, *doc["goals"]])
    dup_path = root / "dup.json"
    dup_path.write_text(json.dumps(dup), encoding="utf-8")
    abs_dup = str(dup_path.resolve())
    for gid in ("aaaa00000001", "bbbb00000002"):
        rc, out, err = _pla(capsys, ["dispatch", "--dry-run", "--slate", str(dup_path), "--goal-id", gid, "--state-dir", str(sd)])
        assert rc == 0, err
        cmds = [ln.strip() for ln in out.splitlines() if ln.strip().startswith("pla dispatch")]
        assert cmds == [f"pla dispatch --slate {abs_dup} --goal-id {gid}"], out
        assert "--title" not in out
    rc, out, err = _pla(capsys, ["dispatch", "--dry-run", "--slate", str(dup_path), "--goal-id", by_title[AUTO_TOP], "--state-dir", str(sd)])
    assert rc == 0, err
    assert f"pla dispatch --slate {abs_dup} --title {shlex.quote(AUTO_TOP)}" in out


def _b5_b8_hint_survives_rescan_json_unchanged(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ws = _workspace(root)
    sd = root / "S"
    rc, out, err = _pla(capsys, _run_argv(ws, SCRIPT, sd, "--dry-run"))
    assert rc == 0, err
    lines = out.splitlines()
    top_i = next(i for i, ln in enumerate(lines) if ln.startswith(TOP_PREFIX))
    top_title = lines[top_i][len(TOP_PREFIX) :]
    top_hint = lines[top_i + 1]
    assert _selector(top_hint) == ("--title", top_title)
    needs = _pairs(_block(out, NEEDS_HEADER))
    assert needs, out
    old_ids = {g["id"] for g in json.loads((sd / "slate.json").read_text(encoding="utf-8"))["goals"]}

    # B5: rescan into the same state dir -> fresh ids; the copied hints still resolve.
    rc, _, err = _pla(
        capsys,
        ["scan", "--workspace", str(ws), "--provider", "scripted", "--scripted-responses",
         str(SCRIPT), "--state-dir", str(sd)],
    )  # fmt: skip
    assert rc == 0, err
    new_ids = {g["id"] for g in json.loads((sd / "slate.json").read_text(encoding="utf-8"))["goals"]}
    assert new_ids and not (old_ids & new_ids), "rescan must mint fresh ids (precondition)"
    for title, cmd in [(top_title, top_hint), *needs]:
        rc, pout, perr = _paste(capsys, cmd, sd)
        assert rc == 0, (cmd, perr)
        header = [ln for ln in pout.splitlines() if ln.startswith(PREVIEW_PREFIX)]
        assert len(header) == 1 and header[0].endswith(f": {title}"), pout
        assert any(header[0].startswith(f"{PREVIEW_PREFIX}{gid}:") for gid in new_ids), header

    # B8: run --json keeps its documented keys; top_goal keeps its shipped {id, title} shape
    # (the spec says "goal_id" there, but only `dispatched` ever carried that key) and
    # dispatched still carries goal_id; no hint spelling leaks into the document.
    rc, jout, err = _pla(capsys, _run_argv(ws, SCRIPT, root / "J", "--json"))
    assert rc == 0, err
    doc = json.loads(jout)
    assert set(doc) == RUN_JSON_KEYS, sorted(doc)
    assert isinstance(doc["top_goal"], dict) and set(doc["top_goal"]) == {"id", "title"}, doc["top_goal"]
    assert doc["top_goal"]["title"] == top_title
    assert isinstance(doc["dispatched"], dict) and "goal_id" in doc["dispatched"], doc["dispatched"]
    assert "--title" not in jout and "--goal-id" not in jout


def test_b1_to_b8_paste_hints_select_by_unique_title(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _clean_env(monkeypatch)
    _b1_b2_b3_b7_run_hints_print_quoted_title(tmp_path / "b1", capsys)
    _b4_b6_dispatch_preview_and_duplicate_fallback(tmp_path / "b4", capsys)
    _b5_b8_hint_survives_rescan_json_unchanged(tmp_path / "b5", capsys)
