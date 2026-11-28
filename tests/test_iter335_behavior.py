"""Black-box oracle for foundry iter 600 (factory iter 335): an EMPTY value for
``--state-dir`` (every verb), ``--slate`` (``dispatch``/``explain``/``verify``),
``--run-dir`` (``resume``/``trace``) and ``diff --old``/``--new`` is a usage error at
parse time -- exit 2, empty stdout, ``error: argument <FLAG>: ... must not be empty``
on stderr -- instead of ``Path("")`` silently becoming ``.`` or the default slate.
Non-empty values, omitted flags, whitespace-only values and ``PLA_STATE_DIR=""`` keep
their behaviour.

ISOLATION CONTRACT (honored): written from the iteration spec (``pm.md``),
``README.md`` and the conventions under ``tests/``. It drives ONLY the public
``proactive_loop.cli.main(argv)`` / ``build_parser()`` entries, offline (scripted
provider), from a scratch cwd created in ``tmp_path`` (``monkeypatch.chdir``) -- no
ambient mtimes, no real cwd. No implementation source, engineer/reviewer note or git
diff was read.

The module collects ONE item, ``test_empty_path_flags_exit_2``, which clears every
``PLA_*`` env var and asserts ``iter600_empty_path_flags``'s returned check count (until
factory iter 602 it was hosted, uncollected, in test_iter317 under the 6-item binding
wall).

Spec ambiguity noted: behaviour 3 names a goal titled ``x``; a real scan does not
propose that title, so the auto-dispatch goal's REAL title from a scripted scan is used
(the fallback is then provably reachable -- see the positive control).
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import pytest

from proactive_loop import cli
from proactive_loop.cli import main

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "examples" / "scripted_responses.json"
NEEDLE = "must not be empty"
ECHO = "dispatching from slate:"
MARKER = "PORTFOLIO INTRO"

VECTORS: tuple[tuple[str, list[str]], ...] = (
    ("--state-dir", ["runs", "--state-dir", ""]),
    ("--state-dir", ["scan", "--state-dir", "", "--provider", "scripted"]),
    ("--slate", ["dispatch", "--slate", "", "--title", "x"]),
    ("--slate", ["explain", "--slate", ""]),
    ("--slate", ["verify", "--slate", "", "--snapshot", "s.json"]),
    ("--run-dir", ["resume", "--run-dir", ""]),
    ("--run-dir", ["trace", "--run-dir", ""]),
    ("--old", ["diff", "--old", "", "--new", "b.json"]),
    ("--new", ["diff", "--old", "a.json", "--new", ""]),
)


def _call(capsys: pytest.CaptureFixture[str], argv: list[str]) -> tuple[int, str, str]:
    capsys.readouterr()
    try:
        rc = main(argv)
    except SystemExit as exc:  # argparse paths (usage errors, --help, --version)
        rc = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
    out, err = capsys.readouterr()
    return rc, out, err


def _assert_rejected(rc: int, out: str, err: str, flag: str, label: str) -> None:
    assert rc == 2, f"{label}: rc={rc} out={out!r} err={err!r}"
    assert out == "", f"{label}: stdout={out!r}"
    assert "usage:" in err, f"{label}: {err!r}"
    hits = [ln for ln in err.splitlines() if f"error: argument {flag}:" in ln and NEEDLE in ln]
    assert len(hits) == 1, f"{label}: no '{flag}' empty-value line in {err!r}"
    # the flag-specific line is the ONLY error line: no downstream fault leaked out
    errors = [ln for ln in err.splitlines() if "error:" in ln]
    assert errors == hits, f"{label}: extra error lines {errors!r}"


def _verbs() -> list[str]:
    parser = cli.build_parser()
    subs = [a for a in parser._actions if isinstance(a, argparse._SubParsersAction)]
    assert len(subs) == 1, subs
    verbs = sorted(subs[0].choices)
    assert len(verbs) >= 10, verbs  # a live roster, never a hardcoded count
    return verbs


def _scan_default(capsys: pytest.CaptureFixture[str], cwd: Path) -> str:
    """Scan a tmp workspace into the DEFAULT ``./.pla_runs``; return the auto title."""
    ws = cwd.parent / "ws"
    ws.mkdir()
    (ws / "README.md").write_text("# demo\n\nTODO: add tests\n", encoding="utf-8")
    rc, out, err = _call(capsys, ["scan", "--workspace", str(ws),
                                  "--state-dir", ".pla_runs", "--scripted-responses", str(SCRIPT)])
    assert rc == 0, (rc, out, err)
    assert (cwd / ".pla_runs" / "slate.json").is_file()
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0].isdigit() and parts[1] == "auto_dispatch":
            return line.split(parts[3], 1)[1].strip()
    raise AssertionError(f"no auto_dispatch goal in scan output: {out!r}")


def _b1_vectors(capsys: pytest.CaptureFixture[str]) -> None:
    for flag, argv in VECTORS:
        rc, out, err = _call(capsys, argv)
        _assert_rejected(rc, out, err, flag, " ".join(repr(a) for a in argv))


def _b2_b7_every_verb(capsys: pytest.CaptureFixture[str]) -> None:
    for verb in _verbs():
        rc, out, err = _call(capsys, [verb, "--state-dir", ""])
        assert rc == 2, f"{verb}: rc={rc} err={err!r}"
        assert NEEDLE in err, f"{verb}: {err!r}"
        assert out == "", f"{verb}: stdout={out!r}"
        rc, out, _ = _call(capsys, [verb, "--help"])  # B7
        assert rc == 0, verb
        assert "--state-dir" in out, verb
    for argv in (["--help"], ["--version"]):
        rc, out, err = _call(capsys, argv)
        assert rc == 0, (argv, err)
        assert out.strip(), argv


def _b3_fallback_refused(capsys: pytest.CaptureFixture[str], cwd: Path, auto: str) -> None:
    runs_dir = cwd / ".pla_runs"
    # Positive control: the default slate IS reachable when --slate is omitted.
    rc, out, err = _call(capsys, ["dispatch", "--title", auto, "--dry-run",
                                  "--scripted-responses", str(SCRIPT)])
    assert rc == 0, (rc, out, err)
    assert any(ln.startswith(ECHO) for ln in err.splitlines()), err
    assert list(runs_dir.glob("run-*")) == []
    rc, out, err = _call(capsys, ["explain"])
    assert rc == 0 and out.strip(), (rc, out, err)
    # The empty value refuses that fallback.
    rc, out, err = _call(capsys, ["dispatch", "--slate", "", "--title", auto,
                                  "--scripted-responses", str(SCRIPT)])
    _assert_rejected(rc, out, err, "--slate", "dispatch default slate")
    assert ECHO not in err
    assert list(runs_dir.glob("run-*")) == [], sorted(p.name for p in runs_dir.iterdir())
    rc, out, err = _call(capsys, ["explain", "--slate", ""])
    _assert_rejected(rc, out, err, "--slate", "explain default slate")


def _b4_no_side_effect(capsys: pytest.CaptureFixture[str], root: Path) -> None:
    bare = root / "bare"
    bare.mkdir()
    prev = Path.cwd()
    os.chdir(bare)
    try:
        for argv in (["runs", "--state-dir", ""],
                     ["scan", "--state-dir", "", "--provider", "scripted", "--workspace", "."]):
            rc, out, err = _call(capsys, argv)
            _assert_rejected(rc, out, err, "--state-dir", argv[0])
            assert "scripted" not in "\n".join(
                ln for ln in err.splitlines() if "error:" in ln), err
            assert not (bare / ".pla_runs").exists(), argv
        assert list(bare.iterdir()) == []
    finally:
        os.chdir(prev)


def _b5_non_empty_unchanged(capsys: pytest.CaptureFixture[str], cwd: Path, auto: str) -> None:
    sd = cwd / ".pla_runs"
    slate = str(sd / "slate.json")
    # --slate real path == omitted --slate (594 default).
    rc_a, out_a, _ = _call(capsys, ["explain"])
    rc_b, out_b, err_b = _call(capsys, ["explain", "--slate", slate])
    assert rc_a == rc_b == 0, err_b
    assert out_a == out_b and NEEDLE not in err_b
    # A real dispatch, then trace newest == trace --run-dir <that run>.
    rc, out, err = _call(capsys, ["dispatch", "--slate", slate, "--title", auto,
                                  "--scripted-responses", str(SCRIPT), "--yes"])
    assert rc == 0, (rc, out, err)
    runs = sorted(sd.glob("run-*"))
    assert len(runs) == 1, runs
    rc_a, out_a, err_a = _call(capsys, ["trace"])
    rc_b, out_b, err_b = _call(capsys, ["trace", "--run-dir", str(runs[0])])
    assert rc_a == rc_b == 0, (err_a, err_b)
    assert out_a == out_b and out_a.strip()
    rc, out, err = _call(capsys, ["runs", "--state-dir", str(sd)])
    assert rc == 0 and runs[0].name in out, (rc, out, err)
    # diff with real paths: identical slates compare clean; a missing one keeps its message.
    rc, out, err = _call(capsys, ["diff", "--old", slate, "--new", slate])
    assert rc == 0, (rc, out, err)
    missing = str(cwd / "nope.json")
    rc, out, err = _call(capsys, ["diff", "--old", missing, "--new", slate])
    assert rc != 0 and NEEDLE not in err
    assert f"slate file not found: {missing}" in err, err
    rc, out, err = _call(capsys, ["resume", "--run-dir", str(cwd / "no-run")])
    assert rc != 0 and NEEDLE not in err, err


def _b6_whitespace_and_env(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, cwd: Path
) -> None:
    rc, out, err = _call(capsys, ["runs", "--state-dir", " "])
    assert NEEDLE not in err and "error: argument --state-dir" not in err, (rc, err)
    monkeypatch.setenv("PLA_STATE_DIR", "")
    try:
        rc, out, err = _call(capsys, ["runs"])
        assert rc == 0, (rc, out, err)  # empty env == unset: default ./.pla_runs applies
        assert NEEDLE not in err
        assert "run-" in out, out  # the default state dir's run from B5 is listed
    finally:
        monkeypatch.delenv("PLA_STATE_DIR", raising=False)


def _b8_readme() -> None:
    text = (REPO / "README.md").read_text(encoding="utf-8")
    marker = text.find(MARKER)
    assert marker != -1
    body = " ".join(text[marker:].split())
    flat = "".join(text.split())
    i = flat.find("AnEMPTYvaluefor`--state-dir`")
    assert i != -1 and i > "".join(text[:marker].split()).__len__(), "sentence missing below marker"
    for token in ("`--state-dir`", "`--slate`", "`--run-dir`", "`--new`", "exit 2"):
        assert token in body, token
    assert NEEDLE.replace(" ", "") in flat[i : i + 600]


def iter600_empty_path_flags(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, root: Path
) -> int:
    """Run every iter-600 behaviour from a scratch cwd; return the groups checked."""
    for key in list(os.environ):
        if key.startswith("PLA_"):
            monkeypatch.delenv(key, raising=False)
    cwd = root / "cwd"
    cwd.mkdir(parents=True)
    monkeypatch.chdir(cwd)
    _b1_vectors(capsys)
    _b2_b7_every_verb(capsys)
    _b4_no_side_effect(capsys, root)
    auto = _scan_default(capsys, cwd)
    _b3_fallback_refused(capsys, cwd, auto)
    _b5_non_empty_unchanged(capsys, cwd, auto)
    _b6_whitespace_and_env(capsys, monkeypatch, cwd)
    _b8_readme()
    return 8


def test_empty_path_flags_exit_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Own collected item (no longer hosted in test_iter317), so a regression is reported
    under THIS behavior's name and cannot hide the other harnesses."""
    for key in list(os.environ):
        if key.startswith("PLA_"):
            monkeypatch.delenv(key, raising=False)
    assert iter600_empty_path_flags(capsys, monkeypatch, tmp_path / "h") == 8
