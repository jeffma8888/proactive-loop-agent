"""Black-box oracle for foundry iter 595 (factory iter 331): an explicitly EMPTY
``--workspace ""`` is rejected by ``scan``, ``run``, ``signals`` and ``watch`` with exit 2
and ``error: workspace not found: '' (empty --workspace)`` on stderr, instead of
``Path("")`` silently becoming ``.`` and perceiving the current directory at exit 0.
The rejection is the FIRST check (it beats provider/script and ``--out`` faults), and
explicit non-empty roots (``.``, a missing path, a regular file) behave as before.

ISOLATION CONTRACT (honored): written from the iteration spec (``pm.md``),
``README.md`` and the conventions under ``tests/``. It drives ONLY the public
``proactive_loop.cli.main(argv)`` entry, offline, from a scratch cwd created in
``tmp_path`` (``monkeypatch.chdir``) holding one ``notes.py`` TODO -- so a fail-open
guard would find a real signal and the tests would go red. No ambient mtimes, no real
cwd, no implementation source, engineer/reviewer note or git diff was read.

The module collects ZERO items on purpose (the suite-size binding wall in
test_iter263 b6 / test_iter270 b7 demands >= 6 items of binding headroom, which four
new items broke): ``iter595_empty_workspace`` is called from
``tests/test_iter317_behavior.py::test_runs_older_than_filters_by_checkpoint_age``,
which asserts its returned behaviour-group count.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from proactive_loop.cli import main

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "examples" / "scripted_responses.json"
EMPTY_LINE = "error: workspace not found: '' (empty --workspace)"
VERBS = ("scan", "run", "signals", "watch")


def _call(capsys: pytest.CaptureFixture[str], argv: list[str]) -> tuple[int, str, str]:
    capsys.readouterr()
    try:
        rc = main(argv)
    except SystemExit as exc:  # argparse paths (usage errors, --help)
        rc = exc.code if isinstance(exc.code, int) else 1
    out, err = capsys.readouterr()
    return rc, out, err


def _assert_rejected(rc: int, out: str, err: str, label: str) -> None:
    assert rc == 2, f"{label}: rc={rc} err={err!r}"
    assert err.splitlines().count(EMPTY_LINE) == 1, f"{label}: {err!r}"
    assert out == "", f"{label}: stdout={out!r}"


def _empty_or_absent(sd: Path) -> bool:
    return (not sd.exists()) or (sd.is_dir() and not any(sd.iterdir()))


def _b1_b2_b4_scan_run_watch(
    scratch: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # B1 scan: exit 2, the line once, empty stdout, no slate written.
    sd = scratch / "sd-scan"
    rc, out, err = _call(capsys, ["scan", "--workspace", "", "--state-dir", str(sd),
                                  "--scripted-responses", str(SCRIPT)])
    _assert_rejected(rc, out, err, "scan")
    assert not (sd / "slate.json").exists()
    assert _empty_or_absent(sd)

    # B2 run: no slate, no run dir; a fresh SD stays absent or empty.
    sd = scratch / "sd-run"
    rc, out, err = _call(capsys, ["run", "--workspace", "", "--state-dir", str(sd),
                                  "--scripted-responses", str(SCRIPT)])
    _assert_rejected(rc, out, err, "run")
    assert not (sd / "slate.json").exists()
    assert not list(sd.glob("run-*")) if sd.exists() else True
    assert _empty_or_absent(sd), sorted(p.name for p in sd.iterdir())

    # B4 watch: exit 2, the line, and no scan ever starts on either stream.
    sd = scratch / "sd-watch"
    rc, out, err = _call(capsys, ["watch", "--workspace", "", "--max-scans", "1",
                                  "--state-dir", str(sd), "--scripted-responses", str(SCRIPT)])
    _assert_rejected(rc, out, err, "watch")
    assert "=== scan 1 ===" not in out + err
    assert not (sd / "slate.json").exists()


def _b3_signals_every_mode(
    scratch: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    for extra in ([], ["--summary"], ["--json"]):
        rc, out, err = _call(capsys, ["signals", "--workspace", "", *extra])
        _assert_rejected(rc, out, err, f"signals {extra}")
        assert "notes.py" not in out + err
    # Control: the same cwd IS perceivable when chosen explicitly, so the empty
    # case above is not vacuously empty.
    rc, out, _ = _call(capsys, ["signals", "--workspace", ".", "--json"])
    assert rc == 0
    assert "notes.py" in out


def _b5_first_check(
    scratch: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # No scripted-responses file configured: the workspace line still wins.
    sd = scratch / "sd-noscript"
    rc, out, err = _call(capsys, ["scan", "--workspace", "", "--provider", "scripted",
                                  "--state-dir", str(sd)])
    _assert_rejected(rc, out, err, "scan no-script")
    assert "scripted" not in err
    assert _empty_or_absent(sd)

    # --out into a nonexistent directory: the workspace line wins, nothing written.
    sd = scratch / "sd-out"
    target = scratch / "no" / "such" / "dir" / "slate.json"
    rc, out, err = _call(capsys, ["scan", "--workspace", "", "--state-dir", str(sd),
                                  "--scripted-responses", str(SCRIPT), "--out", str(target)])
    _assert_rejected(rc, out, err, "scan --out")
    assert not target.exists()
    assert not (scratch / "no").exists()
    assert _empty_or_absent(sd)

    # Red control for the ordering claim: with a REAL root, the missing script is
    # the reported fault (so the assertion above is not vacuous).
    rc, _, err = _call(capsys, ["scan", "--workspace", ".", "--provider", "scripted",
                                "--state-dir", str(scratch / "sd-ctl")])
    assert rc != 0
    assert "workspace not found" not in err


def _b6_b7_unchanged(
    scratch: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # B6: explicit "." is a real choice.
    sd = scratch / "sd-dot"
    rc, _, err = _call(capsys, ["scan", "--workspace", ".", "--state-dir", str(sd),
                                "--scripted-responses", str(SCRIPT)])
    assert rc == 0, err
    assert (sd / "slate.json").is_file()
    assert json.loads((sd / "slate.json").read_text(encoding="utf-8"))["workspace_root"] == "."

    # B6: a missing path keeps the existing wording byte-for-byte.
    missing = "/definitely/missing/xyz"
    rc, out, err = _call(capsys, ["scan", "--workspace", missing,
                                  "--state-dir", str(scratch / "sd-miss")])
    assert rc == 2
    assert f"error: workspace not found: {missing}" in err.splitlines()
    assert "(empty --workspace)" not in err

    # B6: a regular file is still not a workspace.
    regular = scratch / "cwd" / "notes.py"
    rc, out, err = _call(capsys, ["scan", "--workspace", str(regular),
                                  "--state-dir", str(scratch / "sd-file")])
    assert rc == 2
    assert f"error: workspace not found: {regular}" in err.splitlines()

    # B7: every verb still REQUIRES --workspace and documents it in --help.
    for verb in VERBS:
        rc, out, _ = _call(capsys, [verb, "--help"])
        assert rc == 0, verb
        assert "--workspace WORKSPACE" in out, verb
        assert "[--workspace" not in out, f"{verb}: --workspace became optional"
        rc, _, err = _call(capsys, [verb])
        assert rc == 2, verb
        assert "the following arguments are required: --workspace" in err, verb

    # B7: the message lives at ONE seam -- exactly one literal in cli.py.
    cli_text = (REPO / "src" / "proactive_loop" / "cli.py").read_text(encoding="utf-8")
    assert cli_text.count("(empty --workspace)") == 1


def iter595_empty_workspace(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, root: Path
) -> int:
    """Run every iter-595 behaviour from a scratch cwd; return the groups checked."""
    for key in ("PLA_STATE_DIR", "PLA_WORKSPACE"):
        monkeypatch.delenv(key, raising=False)
    cwd = root / "cwd"
    cwd.mkdir(parents=True)
    (cwd / "notes.py").write_text("# TODO: fix me\n", encoding="utf-8")
    monkeypatch.chdir(cwd)
    _b1_b2_b4_scan_run_watch(root, capsys)
    _b3_signals_every_mode(root, capsys)
    _b5_first_check(root, capsys)
    _b6_b7_unchanged(root, capsys)
    return 4
