"""Black-box oracle for foundry iter 589 (factory iter 327): a ``--scripted-responses``
file that is missing, a directory, not UTF-8, empty or not valid JSON is reported as
ONE ``error:`` line that names the file (exit 1), for both ``scan`` and ``run``.

The module collects ONE item, ``test_bad_scripted_responses_file_is_named``, which
clears every ``PLA_*`` env var and asserts ``iter589_scripted_file_faults``'s returned
check count (until factory iter 602 it was hosted, uncollected, in test_iter317 under
the 6-item binding wall). Every case runs ``main()`` in-process on tmp paths (offline,
no mtime dependence).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from proactive_loop.cli import main
from proactive_loop.llm.client import ScriptedLLMClient

REPO = Path(__file__).resolve().parents[1]
_VERBS = ("scan", "run")


def _call(capsys: pytest.CaptureFixture[str], argv: list[str]) -> tuple[int, str, str]:
    capsys.readouterr()
    try:
        rc = main(argv)
    except SystemExit as exc:  # argparse paths
        rc = exc.code if isinstance(exc.code, int) else 1
    out, err = capsys.readouterr()
    return rc, out, err


def _workspace(root: Path) -> Path:
    ws = root / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "README.md").write_text("# demo\n\nTODO: add tests\n", encoding="utf-8")
    return ws


def _argv(verb: str, root: Path, script: Path, *, as_json: bool) -> list[str]:
    argv = [
        verb,
        "--workspace",
        str(_workspace(root)),
        "--provider",
        "scripted",
        "--scripted-responses",
        str(script),
        "--state-dir",
        str(root / "state"),
    ]
    if as_json:
        argv.append("--json")
    return argv


def _faults(root: Path) -> list[tuple[str, Path, str, tuple[str, ...]]]:
    """(name, path, required first-line prefix, required substrings)."""
    missing = root / "missing.json"
    adir = root / "adir"
    adir.mkdir()
    bad = root / "bad.json"
    bad.write_text("{bad", encoding="utf-8")
    empty = root / "empty.json"
    empty.write_bytes(b"")
    nonutf = root / "nonutf.json"
    nonutf.write_bytes(b"\xff\xfe[")
    return [
        ("missing", missing, "error: scripted responses file not found: ", ()),
        ("dir", adir, "error: scripted responses file is not a file: ", ()),
        (
            "bad",
            bad,
            "error: scripted responses file ",
            (" is not valid JSON: ", "line 1 column 2"),
        ),
        (
            "empty",
            empty,
            "error: scripted responses file ",
            (" is not valid JSON: ", "Expecting value"),
        ),
        ("nonutf", nonutf, "error: scripted responses file ", (" is not valid UTF-8",)),
    ]


def _b1_to_b7_faults_name_the_file(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    for name, path, prefix, needles in _faults(root):
        for verb in _VERBS:
            rc, out, err = _call(capsys, _argv(verb, root, path, as_json=False))
            ctx = (name, verb, err)
            assert rc == 1, ctx
            lines = err.splitlines()
            assert len(lines) == 1, ctx
            assert lines[0].startswith(prefix), ctx
            assert str(path) in lines[0], ctx
            for needle in needles:
                assert needle in lines[0], ctx
            for banned in ("Traceback", "Errno", "codec can't decode"):
                assert banned not in err, ctx
            # B6: --json keeps exit 1 and still names the file.
            jrc, _jout, jerr = _call(capsys, _argv(verb, root, path, as_json=True))
            assert jrc == 1, (name, verb, "json", jerr)
            assert str(path) in jerr, (name, verb, "json", jerr)
            assert "Traceback" not in jerr
            # B7: nothing written on a fault.
            assert not (root / "state" / "slate.json").exists(), ctx


def _b8_controls_unchanged(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    noresp = root / "noresp.json"
    noresp.write_text('{"x": 1}', encoding="utf-8")
    strs = root / "strs.json"
    strs.write_text('["x"]', encoding="utf-8")
    for verb in _VERBS:
        rc, out, err = _call(capsys, _argv(verb, root, noresp, as_json=False))
        assert rc == 1, (verb, err)
        # Exact text measured on a `git archive HEAD` tree at 2139f4d (byte-identical).
        assert err == (
            f"error: scripted responses file {noresp} is an object without a 'responses' "
            "key; expected a list or {'responses': [...]}\n"
        ), (verb, err)
        rc, out, err = _call(capsys, _argv(verb, root, strs, as_json=False))
        assert rc == 1, (verb, err)
        assert err == (
            f"error: scripted responses file {strs}: entry at index 0 must be an "
            "object/dict, got str\n"
        ), (verb, err)
    good = REPO / "examples" / "scripted_responses.json"
    rc, out, err = _call(capsys, _argv("scan", root / "good", good, as_json=True))
    assert rc == 0, err
    assert isinstance(json.loads(out), (dict, list))
    assert (root / "good" / "state" / "slate.json").is_file()


def _b9_direct_api(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bad = root / "bad.json"
    bad.write_text("{bad", encoding="utf-8")
    with pytest.raises(ValueError) as vinfo:
        ScriptedLLMClient.from_file(bad)
    assert str(bad) in str(vinfo.value)
    assert isinstance(vinfo.value.__cause__, json.JSONDecodeError)
    missing = root / "missing.json"
    with pytest.raises(OSError) as oinfo:
        ScriptedLLMClient.from_file(missing)
    assert str(missing) in str(oinfo.value)
    assert "Errno" not in str(oinfo.value)


def iter589_scripted_file_faults(capsys: pytest.CaptureFixture[str], root: Path) -> int:
    """Drive spec behaviors 1-9, each group on its own sub-dir of ``root``; returns
    how many behavior groups ran.

    Called by ``test_bad_scripted_responses_file_is_named``, this module's one collected test.
    """
    checks = (_b1_to_b7_faults_name_the_file, _b8_controls_unchanged, _b9_direct_api)
    for i, check in enumerate(checks):
        sub = root / f"b{i}"
        sub.mkdir(parents=True)
        check(sub, capsys)
    return len(checks)


def test_bad_scripted_responses_file_is_named(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Own collected item (no longer hosted in test_iter317), so a regression is reported
    under THIS behavior's name and cannot hide the other harnesses."""
    for key in list(os.environ):
        if key.startswith("PLA_"):
            monkeypatch.delenv(key, raising=False)
    assert iter589_scripted_file_faults(capsys, tmp_path / "h") == 3
