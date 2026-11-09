"""Factory iter 563 (ROADMAP #351): ``pla dispatch --title TITLE`` selects a goal by normalized title.

``--title`` is an exact-match alternative to the per-scan random ``--goal-id``: both sides are
compared ``strip().lower()``, never as a prefix, substring or fuzzy guess, the first occurrence
wins on a duplicate, exactly one of the two selectors is required (handler-enforced, exit 2,
checked before any filesystem probe), and every gate decision is unchanged.

Black-box: ``pla scan`` / ``pla dispatch`` are driven in-process through ``cli.main`` and only
their exit codes, stdout and stderr are asserted; goal ids and titles are read from the written
slate, never hardcoded. ONE collected item (``make readme-headroom`` reads binding_headroom=6, and test_iter263/270
pin it >= 6), funded by folding the 2-item test_iter124::test_b09 ``plant_broken`` parametrize.
Offline and deterministic: scripted provider, every state dir under ``tmp_path``, and the fixture
workspace is a private copy stamped to one known age (fresh-clone safe).
"""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from typing import Final

import pytest

from proactive_loop import cli

REPO: Final = Path(__file__).resolve().parents[1]
FIXTURE: Final = REPO / "examples" / "fixture_workspace"
SCRIPT: Final = REPO / "examples" / "scripted_responses.json"
README: Final = REPO / "README.md"
SPEC: Final = REPO / "SPEC.md"
MARKER: Final = "PORTFOLIO INTRO"
STAMP_AGE_SEC: Final = 6 * 60 * 60
SELECTOR_ERR: Final = "error: dispatch needs exactly one of --goal-id or --title\n"
DRY_JSON_ERR: Final = "error: --dry-run cannot be combined with --json\n"

Result = tuple[int, str, str]


def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("PLA_"):
            monkeypatch.delenv(key, raising=False)


def _pla(capsys: pytest.CaptureFixture[str], *argv: str) -> Result:
    """Run ``pla`` in-process; an argparse ``SystemExit`` is folded into the exit code."""
    capsys.readouterr()
    try:
        rc = cli.main(list(argv))
    except SystemExit as exc:  # argparse usage errors (e.g. an unknown --title on old src)
        rc = exc.code if isinstance(exc.code, int) else 2
    out = capsys.readouterr()
    return rc, out.out, out.err


def _scan(capsys: pytest.CaptureFixture[str], root: Path) -> tuple[Path, Path, list[dict[str, object]]]:
    ws = root / "ws"
    shutil.copytree(FIXTURE, ws)
    stamp = time.time() - STAMP_AGE_SEC
    for path in [ws, *ws.rglob("*")]:
        os.utime(path, (stamp, stamp))
    sd = root / "state"
    slate = root / "slate.json"
    rc, _, err = _pla(
        capsys,
        "scan", "--workspace", str(ws), "--provider", "scripted",
        "--scripted-responses", str(SCRIPT), "--out", str(slate), "--state-dir", str(sd),
    )  # fmt: skip
    assert rc == 0, err
    goals = json.loads(slate.read_text(encoding="utf-8"))["goals"]
    assert len(goals) >= 4, goals
    return slate, sd, goals


def _dispatch(capsys: pytest.CaptureFixture[str], slate: Path, sd: Path, *extra: str) -> Result:
    return _pla(capsys, "dispatch", "--slate", str(slate), "--state-dir", str(sd), *extra)


def _run_dirs(sd: Path) -> list[str]:
    return sorted(p.name for p in sd.glob("run-*")) if sd.exists() else []


def _b1_b2_b3_title_resolves_exactly_like_goal_id_normalized_and_first_wins(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _clean_env(monkeypatch)
    slate, sd, goals = _scan(capsys, tmp_path)
    auto = goals[1]
    title, gid = str(auto["title"]), str(auto["id"])
    assert auto["category"] == "learning", auto

    # B1: byte-identical to --goal-id, keeping the run-<id> dir and the --goal-id paste form.
    by_id = _dispatch(capsys, slate, sd, "--goal-id", gid, "--dry-run")
    assert by_id[0] == 0, by_id
    by_title = _dispatch(capsys, slate, sd, "--title", title, "--dry-run")
    assert by_title == by_id
    assert f"run-{gid}" in by_title[1]
    assert f"--goal-id {gid}" in by_title[1]

    # B2: outer whitespace + other case still matches exactly the same goal.
    assert _dispatch(capsys, slate, sd, "--title", f"  {title.upper()} ", "--dry-run") == by_id

    # B2: strict prefix and substring are NOT matches -- exit 2, empty stdout, repr'd argument.
    before = _run_dirs(sd)
    for partial in ("Draft a learning", title[6:-4], f"{title} x"):
        assert partial.strip().lower() != title.strip().lower()
        rc, out, err = _dispatch(capsys, slate, sd, "--title", partial, "--dry-run")
        assert (rc, out, err) == (2, "", f"error: goal title {partial!r} not found in slate\n")
    rc, out, err = _dispatch(capsys, slate, sd, "--title", "Draft a learning")  # real dispatch path
    assert (rc, out, err) == (2, "", "error: goal title 'Draft a learning' not found in slate\n")
    assert _run_dirs(sd) == before, "a title miss must not create a run dir"

    # B3: duplicate normalized titles -> the FIRST goal in `goals` wins, in either order.
    for case, (first, second) in enumerate([("Fix X", " fix x"), (" fix x", "Fix X")]):
        dup = json.loads(slate.read_text(encoding="utf-8"))
        a = dict(auto, title=first, id=f"aaaa0000000{case}")
        b = dict(auto, title=second, id=f"bbbb0000000{case}")
        dup["goals"] = [a, b, *dup["goals"]]
        dup_path = tmp_path / f"dup{case}.json"
        dup_path.write_text(json.dumps(dup), encoding="utf-8")
        rc, out, err = _dispatch(capsys, dup_path, sd, "--title", "fix x", "--dry-run")
        assert rc == 0, err
        assert f"run-{a['id']}" in out and str(b["id"]) not in out, out


def _b4_b5_b7_selector_refusals_gate_unchanged_and_documented(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _clean_env(monkeypatch)
    slate, sd, goals = _scan(capsys, tmp_path)
    needs, auto, blocked = goals[0], goals[1], goals[3]
    assert needs["category"] == "finance_legal" and blocked["appropriate_now"] is False

    # B4: neither / both -> exit 2, empty stdout, exact line; checked before the slate probe.
    missing = tmp_path / "nope" / "slate.json"
    both = ("--goal-id", str(auto["id"]), "--title", str(auto["title"]))
    for path in (slate, missing):
        for sel in ((), both):
            for tail in ((), ("--dry-run",), ("--json",)):
                got = _dispatch(capsys, path, sd, *sel, *tail)
                assert got == (2, "", SELECTOR_ERR), (path, sel, tail, got)
        # The --dry-run + --json refusal is checked first and keeps its own message.
        assert _dispatch(capsys, path, sd, "--dry-run", "--json") == (2, "", DRY_JSON_ERR)
    assert _run_dirs(sd) == []

    # B5: the gate is unchanged -- NEEDS_APPROVAL exits 4 without --yes, BLOCKED exits 3, and
    # each title result is identical to its --goal-id twin (with and without --dry-run).
    for goal, code in ((needs, 4), (blocked, 3)):
        for tail in ((), ("--dry-run",)):
            by_title = _dispatch(capsys, slate, sd, "--title", str(goal["title"]), *tail)
            assert by_title[0] == code and by_title[1] == "", (goal["title"], tail, by_title)
            assert by_title == _dispatch(capsys, slate, sd, "--goal-id", str(goal["id"]), *tail)
    needs_err = _dispatch(capsys, slate, sd, "--title", str(needs["title"]))[2]
    assert "needs approval" in needs_err and "--yes" in needs_err, needs_err
    rc, out, _ = _dispatch(capsys, slate, sd, "--title", str(needs["title"]), "--yes", "--dry-run")
    assert rc == 0 and f"run-{needs['id']}" in out, out
    assert _dispatch(capsys, slate, sd, "--title", str(blocked["title"]), "--yes")[0] == 3
    assert _run_dirs(sd) == []

    # B6 spot check: --goal-id miss keeps its message.
    assert _dispatch(capsys, slate, sd, "--goal-id", "zzz") == (2, "", "error: goal id 'zzz' not found in slate\n")

    # B7: help, README dispatch row (below the human-owned marker) and SPEC usage line.
    rc, help_out, _ = _pla(capsys, "dispatch", "--help")
    assert rc == 0
    flat = " ".join(help_out.split())
    assert "--title TITLE" in flat
    title_help = flat.split("--title TITLE", 2)[-1].split("--yes")[0]
    assert "exact" in title_help and "strip().lower()" in title_help and "--goal-id" in title_help
    assert "exclusive" in title_help or "exactly one" in flat
    readme = README.read_text(encoding="utf-8")
    below = readme[readme.index(MARKER) :]
    rows = [line for line in below.splitlines() if line.startswith("| `dispatch`")]
    assert len(rows) == 1, rows
    assert "--title TITLE" in rows[0] and "exactly one of" in rows[0]
    assert "`pla dispatch --slate slate.json --goal-id ID|--title T [--yes]`" in SPEC.read_text(encoding="utf-8")


def test_iter311_dispatch_by_title_b1_to_b7(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """One collected item: each half gets its own tmp subtree (own workspace, slate, state dir)."""
    (tmp_path / "select").mkdir()
    (tmp_path / "refuse").mkdir()
    _b1_b2_b3_title_resolves_exactly_like_goal_id_normalized_and_first_wins(tmp_path / "select", capsys, monkeypatch)
    _b4_b5_b7_selector_refusals_gate_unchanged_and_documented(tmp_path / "refuse", capsys, monkeypatch)
