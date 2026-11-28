"""Black-box oracle for foundry iter 590 (factory iter 327): the four remaining
hand-rolled read-only ``--json`` tails -- ``explain`` (whole slate), ``trace``,
``signals --summary`` and ``signals`` -- route through the ``_emit`` seam with
unchanged stdout, stderr and exit codes.

ISOLATION CONTRACT (honored): written only from the iteration spec (pm.md),
README.md, existing tests and the CLI's own output. No implementation source was
read for behaviour, no engineer/reviewer notes and no ``git diff``. The only
reads of ``cli.py`` are the two spec-mandated counts (behaviour 1: a substring
count and an AST ``_emit(`` call count) that test_iter260 already owns.

HEAD parity (behaviour 2) was measured OUTSIDE the suite: 25 argvs run on a
``git archive HEAD`` tree (003b82e) and on the worktree against one shared state
gave identical rc + md5(stdout) + md5(stderr, floats masked). The literals below
(empty-slate forms, guard lines, gate line) are copied from that HEAD run. No
sha, line number or wall-clock bound is pinned (ship hazards H1/H2).

The module collects ONE item, ``test_json_tails_go_through_emit``, which clears every
``PLA_*`` env var and asserts ``iter590_emit_tails``'s returned check count (until
factory iter 602 it was hosted, uncollected, in test_iter317 under the 6-item binding
wall).
"""

from __future__ import annotations

import ast
import json
import os
import re
import shutil
import time
from collections.abc import Callable
from pathlib import Path

import pytest

import proactive_loop.cli as cli
from proactive_loop.cli import main

REPO = Path(__file__).resolve().parents[1]
CLI_PY = REPO / "src" / "proactive_loop" / "cli.py"
SCRIPT = REPO / "examples" / "scripted_responses.json"
FIXTURE = REPO / "examples" / "fixture_workspace"
_TRACE_KEYS = {"index", "kind", "output", "done", "artifacts"}


def _call(capsys: pytest.CaptureFixture[str], argv: list[str]) -> tuple[int, str, str]:
    capsys.readouterr()
    try:
        rc = main(argv)
    except SystemExit as exc:  # argparse paths
        rc = exc.code if isinstance(exc.code, int) else 1
    out, err = capsys.readouterr()
    return rc, out, err


def _one_doc(out: str) -> object:
    """The whole stdout stream is exactly one JSON document (json.loads rejects
    any trailer or second document)."""
    assert out.strip(), "empty --json stdout"
    return json.loads(out)


class _Env:
    def __init__(self, root: Path, capsys: pytest.CaptureFixture[str]) -> None:
        self.ws = root / "ws"
        shutil.copytree(FIXTURE, self.ws)
        stamp = time.time() - 3600  # pinned: every file one hour old (clone-safe)
        for p in [self.ws, *self.ws.rglob("*")]:
            os.utime(p, (stamp, stamp))
        self.state = root / "state"
        rc, _out, err = _call(
            capsys,
            [
                "run",
                "--workspace",
                str(self.ws),
                "--provider",
                "scripted",
                "--scripted-responses",
                str(SCRIPT),
                "--state-dir",
                str(self.state),
            ],
        )
        assert rc == 0, err
        runs = sorted(self.state.glob("run-*"))
        assert len(runs) == 1, runs
        self.run_dir = runs[0]
        assert (self.run_dir / "checkpoint.json").is_file()
        slate = json.loads((self.state / "slate.json").read_text(encoding="utf-8"))
        slate["goals"] = []
        self.empty_slate = root / "empty_slate.json"
        self.empty_slate.write_text(json.dumps(slate), encoding="utf-8")
        self.afile = root / "afile"
        self.afile.write_text("x", encoding="utf-8")
        self.norun = root / "norun"
        self.norun.mkdir()

    def argvs(self) -> dict[str, list[str]]:
        s, w = str(self.state), str(self.ws)
        return {
            "explain": ["explain", "--state-dir", s],
            "trace": ["trace", "--run-dir", str(self.run_dir)],
            "signals": ["signals", "--workspace", w],
            "summary": ["signals", "--workspace", w, "--summary"],
        }


def _b1_counts() -> None:
    text = CLI_PY.read_text(encoding="utf-8")
    assert text.count("print(json.dumps") == 6, text.count("print(json.dumps")
    tree = ast.parse(text)
    emits = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_emit"
    ]
    assert len(emits) == 16, len(emits)
    t260 = (REPO / "tests" / "test_iter260_behavior.py").read_text(encoding="utf-8")
    for name, value in (("EXPECTED_PRINT_JSON_DUMPS", 6), ("EXPECTED_EMIT_CALL_SITES", 16)):
        m = re.search(rf"^{name}[^=]*=\s*(\d+)", t260, flags=re.MULTILINE)
        assert m is not None and int(m.group(1)) == value, (name, m)
    assert "foundry iter 327" in t260


def _b2_b3_outputs(env: _Env, capsys: pytest.CaptureFixture[str]) -> None:
    a = env.argvs()
    # a. explain whole slate: human and JSON views agree on the goals.
    hrc, hout, herr = _call(capsys, a["explain"])
    jrc, jout, jerr = _call(capsys, [*a["explain"], "--json"])
    assert (hrc, herr, jrc, jerr) == (0, "", 0, ""), (herr, jerr)
    goals = _one_doc(jout)
    assert isinstance(goals, list) and goals, goals
    for g in goals:
        assert isinstance(g, dict)
        assert f"(id={g['id']})" in hout, g["id"]
        assert str(g["title"]) in hout
    assert not hout.lstrip().startswith(("[", "{"))
    # b. empty-goals slate (literals measured on the HEAD tree).
    assert _call(capsys, ["explain", "--slate", str(env.empty_slate), "--json"]) == (0, "[]\n", "")
    assert _call(capsys, ["explain", "--slate", str(env.empty_slate)]) == (
        0,
        "(no goals in slate)\n",
        "",
    )
    # c. trace: list of dicts with exactly the five keys, kind a plain string.
    hrc, hout, herr = _call(capsys, a["trace"])
    jrc, jout, jerr = _call(capsys, [*a["trace"], "--json"])
    assert (hrc, herr, jrc, jerr) == (0, "", 0, ""), (herr, jerr)
    rows = _one_doc(jout)
    assert isinstance(rows, list) and rows
    for i, row in enumerate(rows):
        assert isinstance(row, dict) and set(row) == _TRACE_KEYS, row
        assert type(row["kind"]) is str and row["kind"] in {"plan", "act", "check"}, row
        assert row["index"] == i
    assert hout.strip() and not hout.lstrip().startswith(("[", "{"))
    # d. signals listing + summary, human and JSON.
    for key in ("signals", "summary"):
        hrc, hout, herr = _call(capsys, a[key])
        jrc, jout, jerr = _call(capsys, [*a[key], "--json"])
        assert (hrc, herr, jrc, jerr) == (0, "", 0, ""), (key, herr, jerr)
        doc = _one_doc(jout)
        assert isinstance(doc, dict) and doc, (key, doc)
        assert hout.strip() and not hout.lstrip().startswith(("[", "{")), key
        if key == "summary":
            assert isinstance(doc["summary"], dict) and doc["total"] == sum(doc["summary"].values())
            assert str(doc["total"]) in hout
        # e. --timings: stdout is the same single document, table on stderr only.
        trc, tout, terr = _call(capsys, [*a[key], "--json", "--timings"])
        assert trc == 0 and tout == jout, key
        assert terr.startswith("collector timings (ms):"), terr
        assert "collector timings" not in tout


def _b4_laziness(env: _Env, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    a = env.argvs()
    payloads = ["_explain_json_payload", "_signals_json_payload", "_signals_summary_payload"]
    if hasattr(cli, "_trace_json_payload"):  # spec: "for example `_trace_json_payload`"
        payloads.append("_trace_json_payload")
    # (argv key, --json?, function that must NOT run)
    cases: list[tuple[str, bool, str]] = [
        ("explain", True, "_render_explain"),
        ("trace", True, "_render_trace"),
        ("signals", True, "_render_signals"),
        ("summary", True, "_render_signals_summary"),
        ("explain", False, "_explain_json_payload"),
        ("signals", False, "_signals_json_payload"),
        ("summary", False, "_signals_summary_payload"),
    ]
    if "_trace_json_payload" in payloads:
        cases.append(("trace", False, "_trace_json_payload"))
    for key, as_json, fname in cases:
        assert callable(getattr(cli, fname)), fname
        argv = [*a[key], "--json"] if as_json else a[key]
        expected = _call(capsys, argv)
        assert expected[0] == 0, (key, expected[2])

        def _boom(*_a: object, _f: str = fname, **_k: object) -> object:
            raise AssertionError(f"{_f} must not run on this branch")

        with monkeypatch.context() as mp:
            mp.setattr(cli, fname, _boom)
            got = _call(capsys, argv)
        assert got == expected, (key, as_json, fname, got[2])
        # Control: the patched function IS on the other branch's path.
        other = a[key] if as_json else [*a[key], "--json"]
        with monkeypatch.context() as mp:
            mp.setattr(cli, fname, _boom)
            try:
                crc, _o, _e = _call(capsys, other)
            except AssertionError:
                crc = -1
        assert crc != 0, (key, fname, "patch had no effect on the taken branch")


def _b5_guards(env: _Env, capsys: pytest.CaptureFixture[str]) -> None:
    missing = env.state.parent / "missing.json"
    for extra in ([], ["--json"]):
        assert _call(capsys, ["explain", "--slate", str(missing), *extra]) == (
            2,
            "",
            f"error: slate file not found: {missing}\n",
        )
        assert _call(capsys, ["explain", "--state-dir", str(env.state), "--goal-id", "nope", *extra]) == (
            2,
            "",
            "error: goal id 'nope' not found in slate\n",
        )
        assert _call(capsys, ["trace", "--run-dir", str(env.norun), *extra]) == (
            2,
            "",
            f"error: no checkpoint found in {env.norun}\n",
        )
        assert _call(capsys, ["trace", "--run-dir", str(env.afile), *extra]) == (
            2,
            "",
            f"error: --run-dir is not a directory: {env.afile}\n",
        )
    # --fail-on-kind gate: the stdout view comes first and is unchanged, the
    # gate line is on stderr, exit 5 (todo=10 measured on the HEAD tree).
    a = env.argvs()
    for key in ("signals", "summary"):
        for extra in ([], ["--json"]):
            base = _call(capsys, [*a[key], *extra])
            rc, out, err = _call(capsys, [*a[key], *extra, "--fail-on-kind", "todo"])
            assert (rc, out) == (5, base[1]), (key, extra, err)
            assert err == "gate: fail-on-kind tripped -- todo=10\n", err
    rc, out, err = _call(capsys, [*a["signals"], "--json", "--fail-on-kind", "secret_file"])
    assert (rc, err) == (0, "") and isinstance(_one_doc(out), dict)


def _b6_census_untouched() -> None:
    text = CLI_PY.read_text(encoding="utf-8")
    site = "print(json.dumps(payload, indent=2), file=result_stream)"
    assert text.count(site) == 3
    t260 = (REPO / "tests" / "test_iter260_behavior.py").read_text(encoding="utf-8")
    assert 'SURVIVING_RENDERERS: Final[frozenset[str]] = frozenset({"_render_prune"})' in t260


def iter590_emit_tails(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, root: Path
) -> int:
    """Drive spec behaviours 1-6 on a fresh tmp state; returns how many behaviour
    groups ran; called by ``test_json_tails_go_through_emit``."""
    root.mkdir(parents=True, exist_ok=True)
    _b1_counts()
    env = _Env(root, capsys)
    checks: list[Callable[[], None]] = [
        lambda: _b2_b3_outputs(env, capsys),
        lambda: _b4_laziness(env, capsys, monkeypatch),
        lambda: _b5_guards(env, capsys),
        _b6_census_untouched,
    ]
    for check in checks:
        check()
    return 1 + len(checks)


def test_json_tails_go_through_emit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Own collected item (no longer hosted in test_iter317), so a regression is reported
    under THIS behavior's name and cannot hide the other harnesses."""
    for key in list(os.environ):
        if key.startswith("PLA_"):
            monkeypatch.delenv(key, raising=False)
    assert iter590_emit_tails(capsys, monkeypatch, tmp_path / "h") == 5
