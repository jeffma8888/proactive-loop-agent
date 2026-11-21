"""Black-box oracle for foundry iter 594 (factory iter 330; first drafted in foundry iter
593): ``pla dispatch`` treats
``--slate`` as optional and, when it is omitted, reads ``<state_dir>/slate.json`` --
the file ``scan``/``run`` just wrote -- echoing ``dispatching from slate: PATH`` on
stderr. Safety is unchanged: argv-shape faults still win, the gate still re-runs
(BLOCKED exit 3, NEEDS_APPROVAL exit 4 without ``--yes``), ``--dry-run`` creates no
run dir and ``--json`` keeps stdout one nine-key document. ``verify`` still REQUIRES
``--slate``.

ISOLATION CONTRACT (honored): written from the iteration spec (``pm.md``),
``README.md``, ``SPEC.md`` and the conventions under ``tests/``. It drives ONLY the
public ``proactive_loop.cli.main(argv)`` entry, offline (scripted provider), against
PRIVATE ``tmp_path`` state dirs and a workspace created fresh in ``tmp_path`` (no
dependence on fixture mtimes). No implementation source, engineer/reviewer note or
git diff was read.

The module collects ZERO items on purpose (the suite-size wall sits at binding
headroom): ``iter593_dispatch_default_slate`` is called from
``tests/test_iter317_behavior.py::test_runs_older_than_filters_by_checkpoint_age``,
which asserts its returned check count.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from proactive_loop.cli import main
from tests.test_iter158_behavior import DISPATCHED_RUN_KEYS  # roster owner: never re-type it

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "examples" / "scripted_responses.json"
ECHO = "dispatching from slate:"


def _call(capsys: pytest.CaptureFixture[str], argv: list[str]) -> tuple[int, str, str]:
    capsys.readouterr()
    try:
        rc = main(argv)
    except SystemExit as exc:  # argparse paths (usage errors, --help)
        rc = exc.code if isinstance(exc.code, int) else 1
    out, err = capsys.readouterr()
    return rc, out, err


def _s() -> list[str]:
    return ["--scripted-responses", str(SCRIPT)]


def _echo_lines(err: str) -> list[str]:
    return [ln for ln in err.splitlines() if ln.startswith(ECHO)]


def _runs(d: Path) -> list[str]:
    return sorted(p.name for p in d.glob("run-*"))


def _scan(capsys: pytest.CaptureFixture[str], root: Path) -> tuple[Path, dict[str, str]]:
    """Scan a fresh tmp workspace into ``root/state``; return (state dir, decision->title)."""
    ws = root / "ws"
    ws.mkdir(parents=True)
    (ws / "README.md").write_text("# demo\n\nTODO: add tests\n", encoding="utf-8")
    state = root / "state"
    rc, out, err = _call(capsys, ["scan", "--workspace", str(ws), "--state-dir", str(state), *_s()])
    assert rc == 0, (rc, out, err)
    assert (state / "slate.json").is_file(), out
    titles: dict[str, str] = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0].isdigit():
            decision = parts[1]
            title = line.split(parts[3], 1)[1].strip()  # text after CATEGORY
            titles.setdefault(decision, title)
    assert {"auto_dispatch", "needs_approval", "blocked"} <= set(titles), out
    return state, titles


def _clone_state(src: Path, dst: Path) -> Path:
    dst.mkdir(parents=True)
    shutil.copy2(src / "slate.json", dst / "slate.json")
    return dst


def _b1_default_equals_explicit(
    capsys: pytest.CaptureFixture[str], state: Path, titles: dict[str, str], root: Path
) -> None:
    auto = titles["auto_dispatch"]
    a = _clone_state(state, root / "b1_default")
    b = _clone_state(state, root / "b1_explicit")
    rc_a, out_a, err_a = _call(
        capsys, ["dispatch", "--state-dir", str(a), *_s(), "--title", auto, "--yes", "--json"]
    )
    rc_b, out_b, err_b = _call(
        capsys,
        [
            "dispatch", "--state-dir", str(b), *_s(), "--slate", str(b / "slate.json"),
            "--title", auto, "--yes", "--json",
        ],
    )
    assert rc_a == 0 and rc_b == 0, (rc_a, err_a, rc_b, err_b)
    doc_a, doc_b = json.loads(out_a), json.loads(out_b)
    assert set(doc_a) == DISPATCHED_RUN_KEYS and set(doc_b) == DISPATCHED_RUN_KEYS, (doc_a, doc_b)  # B6 json shape
    assert doc_a["goal_id"] == doc_b["goal_id"] and doc_a["status"] == doc_b["status"], (doc_a, doc_b)
    assert Path(doc_a["run_dir"]).name == f"run-{doc_a['goal_id']}" == Path(doc_b["run_dir"]).name
    assert _runs(a) == _runs(b) == [f"run-{doc_a['goal_id']}"]
    # B1: exactly one echo line, naming str(Path) of the resolved default
    assert _echo_lines(err_a) == [f"{ECHO} {a / 'slate.json'}"], err_a
    assert ECHO not in out_a  # B6: the echo goes to stderr only
    # B2: an explicit --slate never echoes
    assert _echo_lines(err_b) == [], err_b
    # human (non --json) default path also echoes exactly once and runs the same goal
    c = _clone_state(state, root / "b1_human")
    rc_c, out_c, err_c = _call(capsys, ["dispatch", "--state-dir", str(c), *_s(), "--title", auto, "--yes"])
    assert rc_c == 0, (rc_c, out_c, err_c)
    assert _echo_lines(err_c) == [f"{ECHO} {c / 'slate.json'}"], err_c
    assert _runs(c) == [f"run-{doc_a['goal_id']}"]


def _b2_explicit_wins(
    capsys: pytest.CaptureFixture[str], state: Path, titles: dict[str, str], root: Path
) -> None:
    """An explicit P wins over <T>/slate.json: the goal is looked up in P only."""
    d = _clone_state(state, root / "b2")
    blocked_title = titles["blocked"]
    raw = json.loads((d / "slate.json").read_text(encoding="utf-8"))
    # P = a slate holding ONLY the blocked goal; the default lacks it entirely
    p_doc = dict(raw, goals=[g for g in raw["goals"] if g["title"] == blocked_title])
    default_doc = dict(raw, goals=[g for g in raw["goals"] if g["title"] != blocked_title])
    assert len(p_doc["goals"]) == 1 and len(default_doc["goals"]) == len(raw["goals"]) - 1
    p = root / "b2_explicit.json"
    p.write_text(json.dumps(p_doc), encoding="utf-8")
    (d / "slate.json").write_text(json.dumps(default_doc), encoding="utf-8")
    rc, out, err = _call(
        capsys, ["dispatch", "--state-dir", str(d), *_s(), "--slate", str(p), "--title", blocked_title]
    )
    assert rc == 3, (rc, out, err)  # found in P (BLOCKED), not "not found" in the default
    assert _echo_lines(err) == [], err
    assert _runs(d) == []
    # control: the same title against the default (which lacks it) is NOT a BLOCKED refusal
    rc2, _out2, err2 = _call(capsys, ["dispatch", "--state-dir", str(d), *_s(), "--title", blocked_title])
    assert rc2 not in (0, 3), (rc2, err2)
    assert _runs(d) == []


def _b3_absent_default(capsys: pytest.CaptureFixture[str], titles: dict[str, str], root: Path) -> None:
    empty = root / "b3_empty"
    empty.mkdir()
    for extra in ([], ["--json"], ["--yes"]):
        rc, out, err = _call(
            capsys,
            ["dispatch", "--state-dir", str(empty), *_s(), "--title", titles["auto_dispatch"], *extra],
        )
        assert rc == 2 and out == "", (extra, rc, out, err)
        assert f"error: slate file not found: {empty / 'slate.json'}" in err, err
        assert _echo_lines(err) == [], err
        assert "Traceback" not in err, err
        assert _runs(empty) == [], extra


def _b4_env_state_dir(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    state: Path,
    titles: dict[str, str],
    root: Path,
) -> None:
    d = _clone_state(state, root / "b4")
    monkeypatch.setenv("PLA_STATE_DIR", str(d))
    try:
        rc, out, err = _call(capsys, ["dispatch", *_s(), "--title", titles["needs_approval"]])
        assert rc == 4, (rc, out, err)
        assert _echo_lines(err) == [f"{ECHO} {d / 'slate.json'}"], err
        assert _runs(d) == []
        # the env-resolved default also feeds a real run
        rc, out, err = _call(capsys, ["dispatch", *_s(), "--title", titles["auto_dispatch"], "--yes"])
        assert rc == 0, (rc, out, err)
        assert _echo_lines(err) == [f"{ECHO} {d / 'slate.json'}"], err
        assert len(_runs(d)) == 1, _runs(d)
    finally:
        monkeypatch.delenv("PLA_STATE_DIR", raising=False)


def _b5_argv_shape_first(capsys: pytest.CaptureFixture[str], state: Path, root: Path) -> None:
    empty = root / "b5_empty"
    empty.mkdir()
    for d in (empty, state):  # absent default AND present default
        base = ["dispatch", "--state-dir", str(d), *_s()]
        for sel in ([], ["--goal-id", "x", "--title", "y"]):
            rc, out, err = _call(capsys, base + sel)
            assert rc == 2 and out == "", (d, sel, rc, out, err)
            assert "dispatch needs exactly one of --goal-id or --title" in err, err
            assert "slate file not found" not in err and _echo_lines(err) == [], err
        rc, out, err = _call(capsys, base + ["--title", "y", "--dry-run", "--json"])
        assert rc == 2 and out == "", (d, rc, out, err)
        assert "--dry-run cannot be combined with --json" in err, err
        assert "slate file not found" not in err and _echo_lines(err) == [], err
    assert _runs(empty) == [] and list(empty.iterdir()) == []


def _b6_downstream(
    capsys: pytest.CaptureFixture[str], state: Path, titles: dict[str, str], root: Path
) -> None:
    d = _clone_state(state, root / "b6")
    base = ["dispatch", "--state-dir", str(d), *_s()]
    rc, out, err = _call(capsys, base + ["--title", titles["needs_approval"]])
    assert rc == 4 and len(_echo_lines(err)) == 1, (rc, out, err)
    rc, out, err = _call(capsys, base + ["--title", titles["needs_approval"], "--json"])
    assert rc == 4 and out == "", (rc, out, err)  # refusal keeps --json stdout empty
    rc, out, err = _call(capsys, base + ["--title", titles["blocked"], "--yes"])
    assert rc == 3 and len(_echo_lines(err)) == 1, (rc, out, err)
    # --dry-run with the default == --dry-run with the explicit path (today's preview)
    rc, out, err = _call(capsys, base + ["--title", titles["auto_dispatch"], "--dry-run"])
    rc_x, out_x, err_x = _call(
        capsys, base + ["--slate", str(d / "slate.json"), "--title", titles["auto_dispatch"], "--dry-run"]
    )
    assert rc == 0 and rc_x == 0 and out.strip(), (rc, out, err, rc_x, err_x)
    assert out == out_x, (out, out_x)
    assert ECHO not in out and len(_echo_lines(err)) == 1 and _echo_lines(err_x) == []
    assert _runs(d) == [], _runs(d)


def _b7_help_and_verify(capsys: pytest.CaptureFixture[str], state: Path) -> None:
    rc, out, _err = _call(capsys, ["dispatch", "--help"])
    assert rc == 0, out
    usage = " ".join(out.split("\n\n")[0].split())
    assert "[--slate" in usage, usage
    flat = " ".join(out.split())
    assert "slate.json" in flat, flat
    assert "state_dir" in flat.replace("state-dir", "state_dir"), flat
    rc, out, err = _call(capsys, ["verify", "--state-dir", str(state)])
    assert rc == 2 and out == "", (rc, out, err)
    assert "usage:" in err and "--slate" in err, err


def _b8_docs() -> None:
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    marker = readme.index("PORTFOLIO INTRO")
    rows = [ln for ln in readme[marker:].splitlines() if ln.startswith("| `dispatch`")]
    assert len(rows) == 1, rows
    row = rows[0]
    for tok in ("--slate", "--goal-id", "required", "optional", "<state-dir>/slate.json"):
        assert tok in row, (tok, row)
    spec = (REPO / "SPEC.md").read_bytes()
    assert b"pla dispatch [--slate FILE] --goal-id ID|--title T [--yes]" in spec
    assert len(spec) < 94_700, len(spec)


def iter593_dispatch_default_slate(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, root: Path
) -> int:
    """Run every iter-593 behaviour; return the number of behaviour groups checked."""
    monkeypatch.delenv("PLA_STATE_DIR", raising=False)
    state, titles = _scan(capsys, root)
    _b1_default_equals_explicit(capsys, state, titles, root)
    _b2_explicit_wins(capsys, state, titles, root)
    _b3_absent_default(capsys, titles, root)
    _b4_env_state_dir(capsys, monkeypatch, state, titles, root)
    _b5_argv_shape_first(capsys, state, root)
    _b6_downstream(capsys, state, titles, root)
    _b7_help_and_verify(capsys, state)
    _b8_docs()
    return 8
