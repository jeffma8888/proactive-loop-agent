"""Black-box oracle for factory iteration 315 (foundry state iter-567) -- ``dispatch``
and ``resume`` finish through ONE shared run-report ending.

The contract: under ``--json`` the run summary goes to STDERR and exactly one
nine-key ``DISPATCHED_RUN_KEYS`` document goes to STDOUT; without ``--json`` the
same summary goes to STDOUT and stderr carries no summary. Both verbs follow that
split identically (behaviors 1-3), refusals keep stdout EMPTY under ``--json``
(behavior 4), and the shipped ``cli.py`` has exactly one ending that both verbs
call (behavior 5, AST).

ISOLATION CONTRACT (honored): written from the iteration spec (``pm.md``),
``README.md`` and the conventions under ``tests/``. It drives ONLY the public
``proactive_loop.cli.main(argv)`` entry in a subprocess (real rc / stdout / stderr
file descriptors) against a PRIVATE copy of ``examples/fixture_workspace`` under
``tmp_path`` with the bundled offline scripted provider. The structural half
(behavior 5) is an AST walk over the shipped ``cli.py`` that the spec itself
names; no implementation logic was read, no engineer/reviewer note, no git diff.

ONE collected item on purpose: binding_headroom is pinned ``>= 6`` by
test_iter263 / test_iter270, so each behavior is a private ``_bN`` half.
"""

from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from tests.test_iter158_behavior import DISPATCHED_RUN_KEYS

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "examples" / "fixture_workspace"
SCRIPT = REPO / "examples" / "scripted_responses.json"
CLI = REPO / "src" / "proactive_loop" / "cli.py"
_ENTRY = "import sys; from proactive_loop.cli import main; sys.exit(main(sys.argv[1:]))"
_SUMMARY_PREFIXES = (
    "dispatched :",
    "status     :",
    "iterations :",
    "retries    :",
    "run dir    :",
    "artifacts  :",
)


def _pla(cwd: Path, *argv: str) -> tuple[int, str, str]:
    env = {**os.environ, "PYTHONPATH": str(REPO / "src")}
    env.pop("PLA_SCRIPTED_RESPONSES", None)
    proc = subprocess.run(
        [sys.executable, "-c", _ENTRY, *argv],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(cwd),
        timeout=120,
        check=False,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _summary(text: str) -> str:
    """The run-summary block of a stream, from its ``dispatched :`` line to the end."""
    lines = text.splitlines()
    starts = [i for i, ln in enumerate(lines) if ln.startswith("dispatched :")]
    assert len(starts) == 1, text
    block = lines[starts[0] :]
    for prefix in _SUMMARY_PREFIXES:
        assert sum(ln.startswith(prefix) for ln in block) == 1, (prefix, text)
    return "\n".join(block)


def _doc(stdout: str) -> dict[str, object]:
    doc = json.loads(stdout)  # the WHOLE stdout is one document
    assert isinstance(doc, dict), stdout
    assert frozenset(doc) == DISPATCHED_RUN_KEYS, sorted(doc)
    return doc


def _setup(root: Path) -> tuple[list[str], dict[str, str]]:
    """Scan a private workspace copy; return the common flags and goal ids by gate."""
    root.mkdir(parents=True)
    shutil.copytree(FIXTURE, root / "ws")
    common = ["--state-dir", "st", "--scripted-responses", str(SCRIPT)]
    rc, _out, err = _pla(root, "scan", "--workspace", "ws", *common)
    assert rc == 0, err
    slate = json.loads((root / "st" / "slate.json").read_text(encoding="utf-8"))
    by_gate: dict[str, str] = {}
    for goal in slate["goals"]:
        rc, _o, _e = _pla(root, "dispatch", "--slate", "st/slate.json", "--goal-id", goal["id"],
                          "--dry-run", *common)
        by_gate.setdefault({0: "allowed", 3: "blocked", 4: "approval"}[rc], goal["id"])
    assert set(by_gate) == {"allowed", "blocked", "approval"}, by_gate
    return common, by_gate


def _b1_b2_b3_split(root: Path, common: list[str], gid: str) -> None:
    disp = ["dispatch", "--slate", "st/slate.json", "--goal-id", gid, *common]
    # B1: human dispatch -> summary on stdout, none on stderr.
    rc, out, err = _pla(root, *disp)
    assert rc == 0, err
    human = _summary(out)
    assert f"(id={gid})" in human and "status     : done" in human, out
    assert "dispatched :" not in err, err
    # B2: --json dispatch -> one nine-key doc on stdout, the SAME summary on stderr.
    rc, out, err = _pla(root, *disp, "--json")
    assert rc == 0, err
    doc = _doc(out)
    assert doc["goal_id"] == gid and doc["status"] == "done", doc
    assert _summary(err) == human, (err, human)
    run_dir = str(doc["run_dir"])
    assert (root / run_dir).is_dir(), run_dir
    # B3: resume (already-done fall-through) follows the same split, both modes.
    res = ["resume", "--run-dir", run_dir, *common]
    rc, r_out, r_err = _pla(root, *res)
    assert rc == 0, r_err
    r_human = _summary(r_out)
    assert "dispatched :" not in r_err, r_err
    assert f"(id={gid})" in r_human and "status     : done" in r_human, r_out
    rc, rj_out, rj_err = _pla(root, *res, "--json")
    assert rc == 0, rj_err
    r_doc = _doc(rj_out)
    assert _summary(rj_err) == r_human, (rj_err, r_human)
    assert r_doc["goal_id"] == gid and r_doc["run_dir"] == run_dir, r_doc
    assert r_doc["status"] == "done", r_doc
    # Deterministic for identical inputs: a second resume repeats both streams.
    assert _pla(root, *res) == (0, r_out, r_err)


def _b4_refusals_keep_stdout_empty(root: Path, common: list[str], ids: dict[str, str]) -> None:
    cases = [
        (["dispatch", "--slate", "st/slate.json", "--goal-id", ids["blocked"]], 3),
        (["dispatch", "--slate", "st/slate.json", "--goal-id", ids["approval"]], 4),
        (["dispatch", "--slate", "st/slate.json", "--goal-id", "no-such-goal"], 2),
    ]
    (root / "empty_run").mkdir()
    cases.append((["resume", "--run-dir", "empty_run"], 2))
    for argv, want in cases:
        rc, out, err = _pla(root, *argv, *common, "--json")
        assert rc == want, (argv, rc, err)
        assert out == "", (argv, out)
        assert err.strip(), argv
        # Same stderr with or without --json -- the refusal never reaches the ending.
        assert _pla(root, *argv, *common)[::2] == (want, err), argv


def _calls(fn: ast.FunctionDef, name: str) -> int:
    return sum(
        isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == name
        for n in ast.walk(fn)
    )


def _b5_structure() -> None:
    src = CLI.read_text(encoding="utf-8")
    tree = ast.parse(src)
    every = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)}
    top = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    assert "_dispatch_goal" not in every  # (a)
    assert "_report_dispatched" in top, sorted(top)  # (b)
    assert "as_json" in [a.arg for a in top["_report_dispatched"].args.kwonlyargs]
    for verb in ("_cmd_dispatch", "_cmd_resume"):  # (c)
        fn = top[verb]
        assert _calls(fn, "_report_dispatched") == 1, verb
        assert _calls(fn, "_render_run_summary") == 0, verb
        assert "print(json.dumps(" not in (ast.get_source_segment(src, fn) or "?"), verb
    assert _calls(top["_cmd_dispatch"], "_execute_goal") == 1  # (d)
    assert src.count("print(json.dumps(") == 10  # (e)


def test_iter315_dispatch_and_resume_share_one_run_report_ending(tmp_path: Path) -> None:
    _b5_structure()
    root = tmp_path / "flow"
    common, ids = _setup(root)
    _b1_b2_b3_split(root, common, ids["allowed"])
    _b4_refusals_keep_stdout_empty(root, common, ids)
