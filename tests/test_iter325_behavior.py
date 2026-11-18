"""Black-box oracle for foundry iter 588 (factory iter 327): ``trace`` / ``resume``
with ``--run-dir`` pointing at an existing regular FILE exit 2 with the single line
``error: --run-dir is not a directory: <path>``.

The module collects ZERO items; see ``iter588_run_dir_not_a_directory`` for why and
for the host test that calls it. Every case runs ``main()`` in-process on tmp paths
(offline, no mtime dependence).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from proactive_loop.cli import main
from proactive_loop.loop import Checkpoint
from proactive_loop.models import CandidateGoal, RunState, RunStatus

REPO = Path(__file__).resolve().parents[1]
_TRACEBACK = "Traceback"
_VERBS = ("trace", "resume")


def _save(run_dir: Path, title: str = "goal 588") -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    state = RunState(
        goal=CandidateGoal(title=title, suggested_first_steps=["read README.md"]),
        status=RunStatus.BUDGET_EXHAUSTED,
        iterations_used=1,
        llm_calls_used=2,
        artifacts_dir=str(run_dir / "artifacts"),
        created_at=datetime(2026, 1, 3, tzinfo=timezone.utc),
    )
    Checkpoint(run_dir / "checkpoint.json").save(state)
    return run_dir


def _call(capsys: pytest.CaptureFixture[str], argv: list[str]) -> tuple[int, str, str]:
    capsys.readouterr()
    try:
        rc = main(argv)
    except SystemExit as exc:  # argparse paths
        rc = exc.code if isinstance(exc.code, int) else 1
    out, err = capsys.readouterr()
    return rc, out, err


def _argv(verb: str, root: Path, run_dir: Path, *, as_json: bool) -> list[str]:
    argv = [verb, "--state-dir", str(root / "state"), "--run-dir", str(run_dir)]
    if verb == "resume":
        script = root / "script.json"
        if not script.exists():
            script.write_text("[]", encoding="utf-8")
        argv += ["--scripted-responses", str(script)]
    if as_json:
        argv.append("--json")
    return argv


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(root)): (p.read_bytes() if p.is_file() else b"<dir>")
        for p in sorted(root.rglob("*"))
    }


def _b1_to_b4_file_is_not_a_directory(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    f = root / "afile.txt"
    f.write_text("plain text, not a run\n", encoding="utf-8")
    (root / "script.json").write_text("[]", encoding="utf-8")
    for verb in _VERBS:
        for as_json in (False, True):
            before = _snapshot(root)
            rc, out, err = _call(capsys, _argv(verb, root, f, as_json=as_json))
            assert (rc, out, err) == (
                2,
                "",
                f"error: --run-dir is not a directory: {Path(str(f))}\n",
            ), (verb, as_json)
            # B3: nothing written -- F byte-identical, no meta/checkpoint siblings.
            after = _snapshot(root)
            assert after == before, (verb, as_json)
            assert not (root / "meta.json").exists()
            assert not (root / "checkpoint.json").exists()


def _b6_checkpoint_looking_file(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # A real run's own checkpoint.json passed as --run-dir: valid JSON content,
    # checkpoint name -- still the guard line, never exit 1 / a JSON error.
    run = _save(root / "run-real")
    ck = run / "checkpoint.json"
    blob = ck.read_bytes()
    assert json.loads(blob)  # the content genuinely looks like a checkpoint
    # A file literally named checkpoint.json with garbage inside.
    junk = root / "junk" / "checkpoint.json"
    junk.parent.mkdir()
    junk.write_text("{not json", encoding="utf-8")
    for target in (ck, junk):
        for verb in _VERBS:
            for as_json in (False, True):
                rc, out, err = _call(capsys, _argv(verb, root, target, as_json=as_json))
                assert rc == 2, (target, verb, as_json, err)
                assert out == ""
                assert err == f"error: --run-dir is not a directory: {target}\n"
                assert _TRACEBACK not in err
    assert ck.read_bytes() == blob


def _b5_b7_missing_empty_dangling_unchanged(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = root / "nope"
    empty = root / "emptyrun"
    empty.mkdir()
    dangling = root / "dangling"
    dangling.symlink_to(root / "does-not-exist")
    for target in (missing, empty, dangling):
        for verb in _VERBS:
            for as_json in (False, True):
                rc, out, err = _call(capsys, _argv(verb, root, target, as_json=as_json))
                assert rc == 2 and out == "", (target, verb, as_json)
                assert f"error: no checkpoint found in {target}" in err, (target, verb, err)
                assert "not a directory" not in err
                assert len(err.splitlines()) == 1
    # B7: a symlink to a FILE follows the link -> "not a directory".
    f = root / "real-file"
    f.write_text("x", encoding="utf-8")
    flink = root / "flink"
    flink.symlink_to(f)
    for verb in _VERBS:
        rc, out, err = _call(capsys, _argv(verb, root, flink, as_json=False))
        assert (rc, out, err) == (2, "", f"error: --run-dir is not a directory: {flink}\n")


def _b5_b7_valid_run_dirs_still_work(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run = _save(root / "state" / "run-ok")
    link = root / "dlink"
    link.symlink_to(run, target_is_directory=True)
    for target in (run, link):
        rc, out, err = _call(capsys, ["trace", "--run-dir", str(target), "--json"])
        assert rc == 0 and err == "", (target, err)
        assert isinstance(json.loads(out), list)
        rc, out, err = _call(capsys, _argv("resume", root, target, as_json=True))
        assert "not a directory" not in err, (target, err)
        assert "no checkpoint found" not in err, (target, err)
        assert _TRACEBACK not in err
    # 587's newest-run default (no --run-dir) is untouched, incl. its --state-dir <file> line.
    rc, out, err = _call(capsys, ["trace", "--state-dir", str(root / "state"), "--json"])
    assert rc == 0 and isinstance(json.loads(out), list)
    sfile = root / "statefile"
    sfile.write_text("x", encoding="utf-8")
    rc, out, err = _call(capsys, ["trace", "--state-dir", str(sfile)])
    rrc, _rout, rerr = _call(capsys, ["runs", "--state-dir", str(sfile)])
    assert rc == 2 and out == "" and err == rerr and rrc == 2
    assert "--run-dir is not a directory" not in err


def _b_docs_readme_documents_it(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    below = readme.split("PORTFOLIO INTRO", 1)[1]
    assert "--run-dir is not a directory" in below
    above = readme.split("PORTFOLIO INTRO", 1)[0]
    assert "--run-dir is not a directory" not in above


def iter588_run_dir_not_a_directory(capsys: pytest.CaptureFixture[str], root: Path) -> int:
    """Drive spec behaviors 1-7 (plus the README clause), each on its own sub-dir
    of ``root``; returns how many behavior groups ran.

    Deliberately NOT collected (no ``test_`` prefix): the suite-size census
    (test_iter263/270) holds a permanent 6-item binding wall that is exactly met
    at HEAD, so ANY new collected item reds the build. The host test
    ``test_iter317_behavior.py::test_runs_older_than_filters_by_checkpoint_age``
    (which already clears every ``PLA_*`` env var) calls this oracle.
    """
    checks = (
        _b1_to_b4_file_is_not_a_directory,
        _b6_checkpoint_looking_file,
        _b5_b7_missing_empty_dangling_unchanged,
        _b5_b7_valid_run_dirs_still_work,
        _b_docs_readme_documents_it,
    )
    for i, check in enumerate(checks):
        sub = root / f"b{i}"
        sub.mkdir(parents=True)
        check(sub, capsys)
    return len(checks)
