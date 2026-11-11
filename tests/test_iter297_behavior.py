"""Black-box behavior oracle for foundry iter 548: five ``--json`` tails join ``_emit``.

Module name DERIVED FROM THE REPO, not from the state dir: the highest tracked
``tests/test_iterNN_behavior.py`` was 296, and ``git cat-file -e
HEAD:tests/test_iter297_behavior.py`` FAILED before this file was written.

Feature under test: ``pla runs`` (non-summary), ``explain``, ``verify``, ``diff``
and ``trend`` render their ``--json``/human output through the shipped
``_emit(as_json=, payload=, human=)`` seam instead of five hand-written tails.
User-visible output must not move.

ONE collected item, on purpose: ``make readme-headroom`` read
``binding_headroom=7`` at HEAD, and the spec caps this module at one item. Every
behavior is an in-function block, and each failure message names its verb.

What it grades, per the PM's Expected Behaviors:

* EB1-5 (self-relative byte identity, durable after the commit lands): every
  ``--json`` stdout equals ``json.dumps(json.loads(out), indent=2) + "\\n"``.
  That pins one document, ``indent=2`` and no trailer. The human form is non-JSON
  and deterministic. The armed gates (``verify --fail-on-unresolved``,
  ``diff --fail-on-change``, ``trend --fail-on-persist``) leave stdout
  byte-identical to the unarmed run, print exactly one ``gate:`` line and exit 5.
  The ``runs`` empty dir prints ``[]``. ``explain`` with an unknown id exits 2.
  ``diff`` echoes raw ``./`` arguments.
* EB6 (structural, ``ast`` over the shipped ``cli.py``): ``_emit`` has 12 call
  sites. There are 11 ``print(json.dumps(`` sites. Each of the five ``_cmd_*``
  functions holds exactly one ``_emit`` call and no ``print(json.dumps(``.
  No open-coded dispatch tail survives inside them.
* EB7 (laziness): the side not taken is patched to raise, and stdout must stay
  byte-identical. A companion call proves each patch really fires.

Fully offline and free of ambient state. Fixtures are built in ``tmp_path``:
the tracked fixture workspace is copied and its mtimes are stamped to NOW with
``os.utime``, then the offline scripted provider runs ``pla run`` in-process.
Stream slates are written straight from ``GoalSlate``.
"""

from __future__ import annotations

import ast
import json
import os
import shutil
import time
from pathlib import Path
from typing import Final

import pytest

from proactive_loop import cli
from proactive_loop.cli import main
from proactive_loop.models import CandidateGoal, GoalSlate
from tests.test_iter125_behavior import clear_pla_env
from tests.test_iter260_behavior import _dispatch_tail_census

REPO: Final[Path] = Path(__file__).resolve().parents[1]
CLI_SRC: Final[Path] = REPO / "src" / "proactive_loop" / "cli.py"
FIXTURE: Final[Path] = REPO / "examples" / "fixture_workspace"
SCRIPT: Final[Path] = REPO / "examples" / "scripted_responses.json"

FIVE_CMDS: Final[tuple[str, ...]] = (
    "_cmd_runs", "_cmd_explain", "_cmd_verify", "_cmd_diff", "_cmd_trend",
)
#: verb -> (human renderer, json payload builder) whose discarded side must stay unevaluated.
LAZY: Final[dict[str, tuple[str, str]]] = {
    "explain": ("_render_explain", "_explain_json_payload"),
    "verify": ("_render_verify", "_verify_json_payload"),
    "diff": ("_render_diff", "_diff_json_payload"),
    "trend": ("_render_trend", "_trend_json_payload"),
}


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    capsys.readouterr()
    try:
        rc = main(argv)
    except SystemExit as exc:
        code = exc.code
        rc = code if isinstance(code, int) else (0 if code is None else 1)
    out, err = capsys.readouterr()
    return int(rc), out, err


def _is_json(text: str) -> bool:
    try:
        json.loads(text)
    except ValueError:
        return False
    return True


def _canonical(verb: str, out: str) -> object:
    doc = json.loads(out)  # exactly one JSON document, or this raises
    assert out == json.dumps(doc, indent=2) + "\n", f"{verb}: --json stdout is not indent=2 + one newline"
    return doc


def _boom(*_a: object, **_k: object) -> object:
    raise AssertionError("discarded rendering was evaluated")


def _count_json_dumps_prints(node: ast.AST) -> int:
    n = 0
    for sub in ast.walk(node):
        if (
            isinstance(sub, ast.Call)
            and isinstance(sub.func, ast.Name)
            and sub.func.id == "print"
            and sub.args
            and isinstance(sub.args[0], ast.Call)
            and isinstance(sub.args[0].func, ast.Attribute)
            and sub.args[0].func.attr == "dumps"
            and isinstance(sub.args[0].func.value, ast.Name)
            and sub.args[0].func.value.id == "json"
        ):
            n += 1
    return n


def _emit_calls(node: ast.AST) -> int:
    return sum(
        1
        for sub in ast.walk(node)
        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name) and sub.func.id == "_emit"
    )


def test_iter297_five_tails_route_through_emit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    clear_pla_env(monkeypatch)
    monkeypatch.chdir(tmp_path)

    # ---- fixtures: a real offline run (slate + snapshot + one run dir) ----
    ws = tmp_path / "ws"
    shutil.copytree(FIXTURE, ws)
    now = time.time()
    for path in ws.rglob("*"):
        if path.is_file():
            os.utime(path, (now, now))
    rc, _, err = _run(
        ["run", "--workspace", str(ws), "--provider", "scripted", "--scripted-responses",
         str(SCRIPT), "--state-dir", "st", "--snapshot", "snap.json", "--json"],
        capsys,
    )
    assert rc == 0, f"fixture run: rc={rc} err={err}"
    slate = json.loads((tmp_path / "st" / "slate.json").read_text(encoding="utf-8"))
    gid = slate["goals"][0]["id"]
    mutated = json.loads(json.dumps(slate))
    mutated["goals"][0]["sources"] = ["nope/missing.md"]
    mutated["goals"][0]["title"] = "A changed title"
    (tmp_path / "mut.json").write_text(json.dumps(mutated), encoding="utf-8")
    stream = tmp_path / "stream"
    stream.mkdir()
    for name, titles in {"slate-001.json": ("A", "B"), "slate-002.json": ("A",), "slate-003.json": ("A", "C")}.items():
        (stream / name).write_text(
            GoalSlate(goals=[CandidateGoal(title=t) for t in titles]).model_dump_json(), encoding="utf-8"
        )
    (tmp_path / "empty_st").mkdir()

    # ---- EB1 runs ----
    rc, out, err = _run(["runs", "--state-dir", "st", "--json"], capsys)
    assert rc == 0, f"runs: rc={rc} err={err}"
    rows = _canonical("runs", out)
    assert isinstance(rows, list) and len(rows) >= 1, f"runs: expected a non-empty array, got {rows!r}"
    rc, out, _ = _run(["runs", "--state-dir", "empty_st", "--json"], capsys)
    assert (rc, out) == (0, "[]\n"), f"runs: empty state dir must print exactly '[]\\n', got {(rc, out)!r}"
    rc, human, _ = _run(["runs", "--state-dir", "st"], capsys)
    assert rc == 0 and human.strip() and not _is_json(human), f"runs: human table broken: {human!r}"
    assert _run(["runs", "--state-dir", "st"], capsys)[1] == human, "runs: human table not deterministic"

    # ---- EB2-5: each verb's --json is one canonical document; human is non-JSON + stable ----
    argvs: dict[str, list[str]] = {
        "explain": ["explain", "--slate", "st/slate.json", "--goal-id", gid],
        "verify": ["verify", "--slate", "st/slate.json", "--snapshot", "snap.json"],
        "diff": ["diff", "--old", "./st/slate.json", "--new", "./mut.json"],
        "trend": ["trend", "--dir", str(stream)],
    }
    captured: dict[tuple[str, bool], str] = {}
    for verb, argv in argvs.items():
        rc, out, err = _run([*argv, "--json"], capsys)
        assert rc == 0 and err == "", f"{verb} --json: rc={rc} err={err!r}"
        doc = _canonical(verb, out)
        assert isinstance(doc, dict), f"{verb}: --json must be one object, got {type(doc).__name__}"
        rc, human, err = _run(argv, capsys)
        assert rc == 0 and human.strip() and not _is_json(human), f"{verb}: human form broken: {human!r}"
        assert _run(argv, capsys)[1] == human, f"{verb}: human form not deterministic"
        assert _run([*argv, "--json"], capsys)[1] == out, f"{verb}: --json not deterministic"
        captured[(verb, True)], captured[(verb, False)] = out, human

    # EB4: raw-argument echo keeps the leading ./ ; --dir mode is canonical too.
    diff_doc = json.loads(captured[("diff", True)])
    assert (diff_doc["old"], diff_doc["new"]) == ("./st/slate.json", "./mut.json"), f"diff: raw echo lost: {diff_doc}"
    rc, out, err = _run(["diff", "--dir", str(stream), "--json"], capsys)
    assert rc == 0, f"diff --dir: rc={rc} err={err}"
    assert isinstance(_canonical("diff --dir", out), dict)
    rc, out, _ = _run(["diff", "--dir", str(stream)], capsys)
    assert rc == 0 and out.strip() and not _is_json(out), f"diff --dir human broken: {out!r}"

    # EB2: unknown goal id.
    rc, out, err = _run(["explain", "--slate", "st/slate.json", "--goal-id", "zzz", "--json"], capsys)
    assert (rc, out) == (2, ""), f"explain unknown id: {(rc, out)!r}"
    assert "error: goal id 'zzz' not found in slate" in err, f"explain unknown id stderr: {err!r}"

    # EB3-5: armed gates print stdout in full first, one gate line, exit 5.
    gates: dict[str, tuple[list[str], list[str]]] = {
        "verify": (["verify", "--slate", "mut.json", "--snapshot", "snap.json"], ["--fail-on-unresolved"]),
        "diff": (["diff", "--old", "./st/slate.json", "--new", "./mut.json"], ["--fail-on-change"]),
        "trend": (["trend", "--dir", str(stream)], ["--fail-on-persist", "2"]),
    }
    for verb, (argv, flag) in gates.items():
        for render in ([], ["--json"]):
            rc0, base, _ = _run([*argv, *render], capsys)
            rc, out, err = _run([*argv, *render, *flag], capsys)
            assert rc == 5, f"{verb} {flag} {render}: expected exit 5, got {rc} ({err!r})"
            assert out == base and out.strip(), f"{verb} {flag} {render}: stdout moved under the gate"
            gate_lines = [ln for ln in err.splitlines() if ln.startswith("gate: ")]
            assert len(gate_lines) == 1, f"{verb} {flag}: expected one gate line, got {err!r}"
            if render:
                _canonical(f"{verb} gated", out)
    rc, _, err = _run(["trend", "--dir", str(stream), "--fail-on-persist", "4"], capsys)
    assert rc == 0 and "gate:" not in err, f"trend: un-tripped gate must exit 0: {(rc, err)!r}"

    # ---- EB7 laziness: the discarded side raises, stdout stays byte-identical ----
    for verb, (renderer, builder) in LAZY.items():
        argv = argvs[verb]
        assert hasattr(cli, renderer) and hasattr(cli, builder), f"{verb}: {renderer}/{builder} missing"
        with monkeypatch.context() as m:
            m.setattr(cli, renderer, _boom)
            rc, out, err = _run([*argv, "--json"], capsys)
            assert (rc, out) == (0, captured[(verb, True)]), f"{verb} --json evaluated {renderer}: {err!r}"
            with pytest.raises(AssertionError, match="discarded rendering"):
                main(argv)  # the patch really fires on the human branch
        with monkeypatch.context() as m:
            m.setattr(cli, builder, _boom)
            rc, out, err = _run(argv, capsys)
            assert (rc, out) == (0, captured[(verb, False)]), f"{verb} human evaluated {builder}: {err!r}"
            with pytest.raises(AssertionError, match="discarded rendering"):
                main([*argv, "--json"])  # the patch really fires on the json branch
        capsys.readouterr()

    # ---- EB6 structural census over the shipped cli.py ----
    tree = ast.parse(CLI_SRC.read_text(encoding="utf-8"))
    assert _emit_calls(tree) == 12, f"_emit call sites: {_emit_calls(tree)} != 12"
    assert CLI_SRC.read_text(encoding="utf-8").count("print(json.dumps(") == 10, "print(json.dumps( text count != 10"
    census = _dispatch_tail_census(tree)
    funcs = {
        n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name in FIVE_CMDS
    }
    assert sorted(funcs) == sorted(FIVE_CMDS), f"missing command functions: {set(FIVE_CMDS) - set(funcs)}"
    for name, fn in funcs.items():
        # ``_cmd_explain`` held TWO sites at HEAD; only the ``--goal-id`` one-object tail
        # (EB2) is in scope, so the whole-slate array site survives -- that is what
        # kept the file-wide count at 16 - 5 = 11 (10 since dispatch + resume shared
        # one `_report_dispatched` ending, foundry iter 567).
        allowed = 1 if name == "_cmd_explain" else 0
        assert _count_json_dumps_prints(fn) == allowed, f"{name}: open-coded print(json.dumps( sites != {allowed}"
        # ``_cmd_runs`` already owned one ``_emit`` for ``--summary`` (iter 314); the list tail adds one.
        want = 2 if name == "_cmd_runs" else 1
        assert _emit_calls(fn) == want, f"{name}: expected exactly {want} _emit( call(s), got {_emit_calls(fn)}"
        span = range(fn.lineno, (fn.end_lineno or fn.lineno) + 1)
        inside = [hit for hit in census if hit[0] in span]
        assert inside == [], f"{name}: open-coded dispatch tail(s) survive: {inside}"
    renderers = {r for _, r in census}
    assert renderers <= {"_render_prune", "_render_explain"}, f"unexpected open-coded tails: {sorted(renderers)}"
