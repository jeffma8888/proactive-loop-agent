"""Black-box oracle for factory iteration 316 (foundry state iter-568) -- the
exit-code-2 contract is published TRUTHFULLY and COMPLETELY.

README ``### Exit codes`` row 2, the ``pla --help`` ``exit codes:`` epilog and the
``cli.main`` docstring all state the real exit-2 conditions: ``--out`` exits 2 when
it IS a directory, ``--state-dir`` / ``--out-dir`` when it is NOT one, an unreadable
``run --decline`` file exits 2, and a ``--goal-id`` / ``--title`` matching no goal
in the slate exits 2 (behaviors 1-4). Behavior 5 proves every clause black-box:
each fault really exits 2 with exactly one ``error:`` line on stderr.

ISOLATION CONTRACT (honored): written from the iteration spec (``pm.md``),
``README.md`` and the conventions under ``tests/``. It drives ONLY the public
``proactive_loop.cli.main(argv)`` entry in a subprocess against a PRIVATE copy of
``examples/fixture_workspace`` under ``tmp_path`` with the bundled offline
scripted provider, and reads ``main.__doc__`` (public API). No implementation
logic was read, no engineer/reviewer note, no git diff.

ONE collected item on purpose: binding_headroom is pinned ``>= 6`` by
test_iter263 / test_iter270, so each behavior is a private ``_bN`` half.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
README = REPO / "README.md"
FIXTURE = REPO / "examples" / "fixture_workspace"
SCRIPT = REPO / "examples" / "scripted_responses.json"
_ENTRY = "import sys; from proactive_loop.cli import main; sys.exit(main(sys.argv[1:]))"
_DOC_ENTRY = "from proactive_loop.cli import main; print(main.__doc__)"


def _run(cwd: Path, *argv: str, code: str = _ENTRY) -> tuple[int, str, str]:
    env = {**os.environ, "PYTHONPATH": str(REPO / "src")}
    env.pop("PLA_SCRIPTED_RESPONSES", None)
    proc = subprocess.run(
        [sys.executable, "-c", code, *argv],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(cwd),
        timeout=120,
        check=False,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _collapse(text: str) -> str:
    return " ".join(text.split())


def _readme_row2() -> str:
    text = README.read_text(encoding="utf-8")
    section = text.split("### Exit codes", 1)[1]
    rows = [ln for ln in section.splitlines() if ln.startswith("| 2 |") or ln.startswith("| `2` |")]
    assert len(rows) == 1, rows
    return rows[0]


def _b1_b2_readme(row: str) -> None:
    # B1: --out IS a directory; --state-dir / --out-dir is NOT.
    assert "(`--out` is a directory, or `--state-dir` / `--out-dir` is not a directory)" in row, row
    assert "(`--out` or `--state-dir` is not a directory)" not in row, row
    # B2: the two missing faults are named; the stale phrase is gone.
    assert "a `run --decline` file cannot be read" in row, row
    assert "a `--goal-id` / `--title` matches no goal in the slate" in row, row
    assert "a goal id is not in the slate" not in row, row
    # Unchanged neighbours of the row survive.
    for needle in ("`--workspace`", "`--slate`", "checkpoint.json", "argparse", "`--baseline`", "`--snapshot`"):
        assert needle in row, (needle, row)


def _b3_epilog(cwd: Path) -> None:
    rc, out, err = _run(cwd, "--help")
    assert rc == 0, err
    epilog = out.split("exit codes:", 1)[1]
    for line in epilog.splitlines():
        assert len(line) <= 78, (len(line), line)
    lines = epilog.splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.strip().startswith("2 "))
    end = next(i for i, ln in enumerate(lines) if i > start and ln.strip().startswith("3 "))
    entry = _collapse("\n".join(lines[start:end]))
    for needle in (
        "an --out that is a directory",
        "a --state-dir or --out-dir that is not a directory",
        "a run --decline file that cannot be read",
        "a --goal-id or --title matches no goal in the slate",
        # test_iter305 needles still hold
        "--slate",
        "--baseline",
        "not a directory",
        "--snapshot",
        "not valid JSON",
        "not one JSON object",
        "--run-dir",
        "checkpoint.json",
        "argparse",
        "nothing to act on",
    ):
        assert needle in entry, (needle, entry)


def _b4_docstring(cwd: Path) -> None:
    rc, out, err = _run(cwd, code=_DOC_ENTRY)
    assert rc == 0, err
    bullets = [b for b in out.split("* ") if b.startswith("``2`` --")]
    assert len(bullets) == 1, out
    bullet = _collapse(bullets[0].split("* ``3``")[0])
    for needle in ("--goal-id", "--title", "run --decline"):
        assert needle in bullet, (needle, bullet)


def _exits2(cwd: Path, expect: str, *argv: str) -> str:
    rc, _out, err = _run(cwd, *argv)
    assert rc == 2, (argv, rc, err)
    errors = [ln for ln in err.splitlines() if ln.startswith("error:")]
    assert len(errors) == 1, (argv, err)
    assert "Traceback" not in err, err
    assert errors[0].startswith(expect), (expect, errors[0])
    return errors[0]


def _b5_fault_matrix(root: Path) -> None:
    root.mkdir()
    ws = root / "ws"
    shutil.copytree(FIXTURE, ws)
    common = ("--provider", "scripted", "--scripted-responses", str(SCRIPT))
    slate = root / "slate.json"
    rc, _out, err = _run(root, "scan", *common, "--workspace", str(ws), "--out", str(slate),
                         "--state-dir", str(root / "st"))
    assert rc == 0, err
    goals = json.loads(slate.read_text(encoding="utf-8"))["goals"]
    real_id = next(g["id"] for g in goals if g.get("appropriate_now", True))
    a_dir = root / "adir"
    a_dir.mkdir()
    a_file = root / "afile"
    a_file.write_text("x", encoding="utf-8")
    # (a) --out IS a directory
    _exits2(root, "error: --out is a directory:", "scan", *common, "--workspace", str(ws),
            "--out", str(a_dir), "--state-dir", str(root / "st"))
    # (b) --state-dir is NOT a directory
    _exits2(root, "error: --state-dir is not a directory:", "dispatch", *common, "--slate", str(slate),
            "--goal-id", real_id, "--state-dir", str(a_file), "--yes")
    # (c) --title matches no goal
    line = _exits2(root, "error: goal title 'no such goal' not found in slate", "dispatch",
                   "--slate", str(slate), "--title", "no such goal", "--dry-run")
    assert line == "error: goal title 'no such goal' not found in slate", line
    # (d) --goal-id matches no goal
    line = _exits2(root, "error: goal id 'nope' not found in slate", "dispatch",
                   "--slate", str(slate), "--goal-id", "nope", "--dry-run")
    assert line == "error: goal id 'nope' not found in slate", line
    # (e) missing --decline file
    _exits2(root, "error: decline file not found or not a regular file:", "run", *common,
            "--workspace", str(ws), "--state-dir", str(root / "st"), "--decline", str(root / "missing.txt"))
    # (f) undecodable --decline file
    bad = root / "bad.txt"
    bad.write_bytes(b"\xff\xfe")
    _exits2(root, "error: decline file unreadable:", "run", *common,
            "--workspace", str(ws), "--state-dir", str(root / "st"), "--decline", str(bad))


def test_b01_exit2_contract_is_published_true_and_every_clause_holds(tmp_path: Path) -> None:
    _b1_b2_readme(_readme_row2())
    _b3_epilog(tmp_path)
    _b4_docstring(tmp_path)
    _b5_fault_matrix(tmp_path / "m")
