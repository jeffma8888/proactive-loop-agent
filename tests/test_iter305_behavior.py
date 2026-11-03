"""Factory iter 556 (ROADMAP #345): the exit-code 1/2 contract matches the measured input faults.

``pla --help`` renders ``_EXIT_CODES``, the canonical exit-code contract scripts branch on. Before
this change code 1 claimed "a missing or malformed input file" while four of five file flags
actually exit 2. Now code 1 names the malformed slate / ``checkpoint.json`` and the missing or
malformed ``--scripted-responses`` script, and code 2 names the missing / wrong-kind ``--slate`` /
``--baseline`` paths and a malformed ``--baseline`` / ``--snapshot`` document. Prose only: no exit
code changes.

Black-box: drives ``proactive_loop.cli.main([...])`` in-process and reads the public ``--help``
text, the ``main()`` docstring and the README section below the human-owned marker. ONE collected
item (``make readme-headroom`` read binding_headroom=6), paid for by folding a 2-item static
parametrize elsewhere; the spec behaviours live in private ``_bN_`` helpers called from it.
Offline and deterministic: every input is built under ``tmp_path``.
"""

from __future__ import annotations

import contextlib
import io
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Final

from proactive_loop.cli import _EXIT_CODES, main

REPO: Final = Path(__file__).resolve().parents[1]
README: Final = REPO / "README.md"
MARKER: Final = "PORTFOLIO INTRO \u2014 human-owned"


def _call(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rc = main(argv)
        except SystemExit as exc:  # argparse paths
            code = exc.code
            rc = code if isinstance(code, int) else (0 if code is None else 1)
    return int(rc), out.getvalue(), err.getvalue()


def _help(columns: str) -> str:
    env = dict(os.environ, COLUMNS=columns)
    proc = subprocess.run(
        [sys.executable, "-m", "proactive_loop", "--help"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=120,
        cwd=REPO,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


def _exit_block(text: str) -> str:
    idx = text.lower().find("exit codes:")
    assert idx >= 0, text
    return text[idx:]


def _flat(text: str) -> str:
    return " ".join(text.split())


def _workspace(root: Path) -> Path:
    ws = root / "ws"
    ws.mkdir(parents=True)
    (ws / "NOTES.md").write_text("# notes\n\nTODO: write the docs\n", encoding="utf-8")
    return ws


def _b1_b2_help_codes_1_and_2(meanings: dict[int, str]) -> None:
    one, two = meanings[1], meanings[2]
    # Behavior 1: code 1 no longer claims every missing/malformed input file.
    assert "missing or malformed input file" not in one, one
    assert "slate" in one and "checkpoint.json" in one, one
    assert "--scripted-responses" in one, one
    assert "--provider" in one, one
    assert "model-boundary" in one and "retry budget" in one, one
    assert "--fail-on-kind" in one and "fails closed" in one, one
    # Behavior 2: code 2 names the wrong-path and malformed-document faults.
    assert "a path you passed does not exist" in two, two
    assert "wrong kind of path" in two, two
    for needle in ("--slate", "--baseline", "not a directory", "--snapshot"):
        assert needle in two, (needle, two)
    assert "not valid JSON" in two and "not one JSON object" in two, two
    assert "--run-dir" in two and "checkpoint.json" in two, two
    assert "argparse" in two, two
    assert "nothing to act on" in two, two


def _b3_b6_fault_matrix(root: Path, meanings: dict[int, str]) -> None:
    root.mkdir(parents=True)
    ws = _workspace(root)
    good_slate = root / "slate.json"
    script = root / "script.json"
    script.write_bytes((REPO / "examples" / "scripted_responses.json").read_bytes())
    rc, _, err = _call(["scan", "--workspace", str(ws), "--provider", "scripted",
                        "--scripted-responses", str(script), "--state-dir", str(root / "s0"),
                        "--out", str(good_slate)])
    assert rc == 0 and good_slate.is_file(), err
    missing = root / "missing.json"
    a_dir = root / "a_dir"
    a_dir.mkdir()
    bad = root / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    arr = root / "arr.json"
    arr.write_text("[1, 2]", encoding="utf-8")
    empty_run = root / "empty_run"
    empty_run.mkdir()
    state = root / "state"
    rows: list[tuple[list[str], int, str, str]] = [
        (["explain", "--slate", str(missing)], 2, "--slate", "slate file not found"),
        (["explain", "--slate", str(a_dir)], 2, "--slate", "slate file not found"),
        (["explain", "--slate", str(bad)], 1, "slate", "invalid slate file"),
        (["signals", "--workspace", str(ws), "--baseline", str(missing)], 2, "--baseline",
         "baseline file not found"),
        (["signals", "--workspace", str(ws), "--baseline", str(bad)], 2, "--baseline",
         "not valid JSON"),
        (["signals", "--workspace", str(ws), "--baseline", str(arr)], 2, "--baseline",
         "one JSON object"),
        (["verify", "--slate", str(good_slate), "--snapshot", str(bad)], 2, "--snapshot",
         "not valid JSON"),
        (["run", "--workspace", str(ws), "--provider", "scripted", "--state-dir", str(state),
          "--scripted-responses", str(missing)], 1, "--scripted-responses", ""),
        (["run", "--workspace", str(ws), "--provider", "scripted", "--state-dir", str(state),
          "--scripted-responses", str(bad)], 1, "--scripted-responses", ""),
        (["scan", "--workspace", str(ws), "--provider", "scripted", "--scripted-responses",
          str(script), "--state-dir", str(root / "s1"), "--out", str(a_dir)], 2, "--out", ""),
        (["resume", "--state-dir", str(state), "--run-dir", str(empty_run)], 2, "--run-dir",
         "checkpoint"),
    ]
    for argv, want_rc, phrase, err_hint in rows:
        rc, _out, err = _call(argv)
        assert rc == want_rc, (argv, rc, err)
        assert phrase in meanings[rc], (argv, phrase, meanings[rc])
        assert err_hint in err, (argv, err_hint, err)
        # Behavior 6: an operator error is one line on stderr, never a traceback.
        assert "Traceback" not in err, (argv, err)


def _b4_main_docstring() -> None:
    doc = main.__doc__ or ""
    flat = _flat(doc)
    assert "missing/malformed input file" not in flat, doc
    assert "not-found / no-checkpoint (a handler returned it explicitly)" not in flat, doc
    bullets = dict(re.findall(r"\* ``(\d)`` -- (.*?)(?= \* ``\d`` -- | WHY |$)", flat))
    # Behavior 7: the docstring lists the same code set as _EXIT_CODES.
    assert sorted(bullets) == ["0", "1", "2", "3", "4", "5"], sorted(bullets)
    one, two = bullets["1"], bullets["2"]
    assert "--scripted-responses" in one and "checkpoint.json" in one, one
    assert "--baseline" in two and "--slate" in two and "--snapshot" in two, two
    assert "malformed" in two and "--run-dir" in two and "argparse" in two, two
    assert "--baseline" not in one, one


def _b5_readme_rows() -> None:
    text = README.read_text(encoding="utf-8")
    assert MARKER in text
    below = text.split(MARKER, 1)[1]
    row1 = next(line for line in below.splitlines() if line.startswith("| 1 |"))
    row2 = next(line for line in below.splitlines() if line.startswith("| 2 |"))
    assert "--baseline" in row2 and "--snapshot" in row2, row2
    assert "not valid JSON" in row2 and "one JSON object" in row2, row2
    assert "slate" in row1 and "checkpoint.json" in row1, row1
    assert "--scripted-responses" in row1, row1


def _b6_b7_help_deterministic_and_code_set(meanings: dict[int, str]) -> None:
    assert sorted(meanings) == [0, 1, 2, 3, 4, 5], sorted(meanings)
    narrow, wide = _exit_block(_help("40")), _exit_block(_help("200"))
    assert narrow == wide
    assert all(len(line) <= 80 for line in wide.splitlines()), wide
    flat_help = _flat(wide)
    for code in (1, 2):
        assert _flat(meanings[code]) in flat_help, (code, meanings[code])


def test_b1_to_b7_exit_codes_1_and_2_describe_the_measured_input_faults(tmp_path: Path) -> None:
    meanings = {int(code): str(text) for code, text in _EXIT_CODES}
    _b1_b2_help_codes_1_and_2(meanings)
    _b3_b6_fault_matrix(tmp_path / "matrix", meanings)
    _b4_main_docstring()
    _b5_readme_rows()
    _b6_b7_help_deterministic_and_code_set(meanings)
