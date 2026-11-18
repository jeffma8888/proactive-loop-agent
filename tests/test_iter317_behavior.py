"""Black-box oracle for factory iteration 317 (foundry state iter-569) --
``pla runs --older-than DAYS`` narrows the selection by persisted checkpoint age.

The filter keys on the checkpoint's ``created_at``: a run older than DAYS days is
selected (a naive timestamp is read as UTC), a fresh run is not, and a run with no
readable checkpoint is NEVER selected (fail closed on the only destructive path).
It applies to the listing, ``--json``, ``--summary`` and ``--prune`` alike, composes
with ``--status`` / ``--goal``, validates at parse time (exit 2), and is documented
in ``runs --help``, the README ``## CLI`` row and the SPEC usage line.

ISOLATION CONTRACT (honored): written from the iteration spec (``pm.md``),
``README.md``, ``SPEC.md`` and the conventions under ``tests/``. It drives ONLY the
public ``proactive_loop.cli.main(argv)`` entry against a PRIVATE state dir built in
``tmp_path`` (no mtimes involved -- age comes from the persisted ``created_at``).
No implementation logic was read, no engineer/reviewer note, no git diff.

ONE collected item on purpose: binding_headroom is pinned (test_iter263 /
test_iter270), so each behavior is a private ``_bN`` half.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Final

import pytest

from proactive_loop import cli
from proactive_loop.models import CandidateGoal, RunState
from tests.test_iter324_behavior import iter587_trace_newest
from tests.test_iter325_behavior import iter588_run_dir_not_a_directory
from tests.test_iter326_behavior import iter589_scripted_file_faults

REPO: Final = Path(__file__).resolve().parents[1]
README: Final = REPO / "README.md"
SPEC: Final = REPO / "SPEC.md"
CHECKPOINT: Final = "checkpoint.json"
OLD: Final = ["run-naive", "run-old"]
EMPTY: Final = "no runs found under the state dir."


def _write(sd: Path, run_id: str, title: str, created_at: str | None) -> None:
    run_dir = sd / run_id
    run_dir.mkdir(parents=True)
    data = json.loads(RunState(goal=CandidateGoal(title=title), status="done").model_dump_json())
    if created_at is not None:
        data["created_at"] = created_at
    (run_dir / CHECKPOINT).write_text(json.dumps(data), encoding="utf-8")


def _state_dir(root: Path) -> Path:
    sd = root / "state"
    _write(sd, "run-old", "old goal", "2000-01-01T00:00:00Z")
    _write(sd, "run-naive", "naive goal", "2000-01-01T00:00:00")
    _write(sd, "run-new", "new goal", None)
    (sd / "run-broken").mkdir()
    (sd / "run-broken" / CHECKPOINT).write_text("{", encoding="utf-8")
    return sd


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    capsys.readouterr()
    try:
        rc = cli.main(list(argv))
    except SystemExit as exc:  # argparse parse-time exits
        rc = exc.code if isinstance(exc.code, int) else 1
    out, err = capsys.readouterr()
    return rc, out, err


def _ids(rows: object) -> list[str]:
    assert isinstance(rows, list), rows
    return [row["run_id"] for row in rows]


def _b1_b2_listing(capsys: pytest.CaptureFixture[str], sd: Path) -> None:
    rc, out, err = _run(capsys, "runs", "--older-than", "30", "--state-dir", str(sd))
    assert rc == 0, (rc, out, err)
    assert err == "", err  # B2: naive timestamp raises nothing
    assert "run-old" in out and "run-naive" in out, out
    assert "run-new" not in out and "run-broken" not in out, out
    assert out.index("run-naive") < out.index("run-old"), out
    # Same column layout as the plain listing: every filtered line appears verbatim there.
    rc0, plain, _ = _run(capsys, "runs", "--state-dir", str(sd))
    assert rc0 == 0
    plain_lines = plain.splitlines()
    for line in out.splitlines():
        assert line in plain_lines, (line, plain)
    rows = [ln for ln in out.splitlines() if "run-" in ln]
    assert len(rows) == 2, out


def _b3_json(capsys: pytest.CaptureFixture[str], sd: Path) -> None:
    rc, out, _ = _run(capsys, "runs", "--older-than", "30", "--json", "--state-dir", str(sd))
    assert rc == 0
    rows = json.loads(out)
    assert _ids(rows) == OLD, rows
    rc, plain, _ = _run(capsys, "runs", "--json", "--state-dir", str(sd))
    plain_rows = json.loads(plain)
    keys = {frozenset(r) for r in plain_rows}
    assert {frozenset(r) for r in rows} <= keys, (rows, plain_rows)
    assert len(keys) >= 1


def _b4_summary(capsys: pytest.CaptureFixture[str], sd: Path) -> None:
    rc, out, _ = _run(capsys, "runs", "--older-than", "30", "--summary", "--json", "--state-dir", str(sd))
    assert rc == 0, out
    obj = json.loads(out)
    assert obj["runs"] == 2 and obj["by_status"] == {"done": 2}, obj


def _b5_compose(capsys: pytest.CaptureFixture[str], sd: Path) -> None:
    rc, out, _ = _run(capsys, "runs", "--older-than", "30", "--status", "failed", "--state-dir", str(sd))
    assert rc == 0 and out.strip() == EMPTY, (rc, out)
    rc, out, _ = _run(capsys, "runs", "--older-than", "30", "--goal", "old", "--json", "--state-dir", str(sd))
    assert rc == 0 and _ids(json.loads(out)) == ["run-old"], out


def _b6_dry_run(capsys: pytest.CaptureFixture[str], sd: Path) -> None:
    rc, out, _ = _run(capsys, "runs", "--older-than", "30", "--prune", "--json", "--state-dir", str(sd))
    assert rc == 0, out
    obj = json.loads(out)
    assert obj["dry_run"] is True and obj["selected"] == OLD, obj
    assert obj["refused"] == [] and obj["deleted"] == 0, obj
    for rid in ("run-old", "run-naive", "run-new", "run-broken"):
        assert (sd / rid).is_dir(), rid


def _b8_validation(capsys: pytest.CaptureFixture[str], sd: Path) -> None:
    for bad in ("0", "-1", "nan", "inf", "abc"):
        rc, out, err = _run(capsys, "runs", f"--older-than={bad}", "--state-dir", str(sd))
        assert rc == 2, (bad, rc, out, err)
        assert out == "", (bad, out)
        assert "argument --older-than" in err, (bad, err)
        if bad == "0":
            assert "must be a positive number (> 0), got 0" in err, err
    rc, out, _ = _run(capsys, "runs", "--older-than", "0.5", "--json", "--state-dir", str(sd))
    assert rc == 0 and _ids(json.loads(out)) == OLD, out


def _b7_prune_yes(capsys: pytest.CaptureFixture[str], sd: Path) -> None:
    rc, out, err = _run(capsys, "runs", "--older-than", "30", "--prune", "--yes", "--state-dir", str(sd))
    assert rc == 0, (rc, out, err)
    assert out.startswith("pruned 2 run dir(s):"), out
    assert "run-naive" in out and "run-old" in out, out
    remaining = sorted(p.name for p in sd.iterdir() if p.name.startswith("run-"))
    assert remaining == ["run-broken", "run-new"], remaining


def _b10_docs(capsys: pytest.CaptureFixture[str]) -> None:
    rc, out, _ = _run(capsys, "runs", "--help")
    assert rc == 0 and "--older-than DAYS" in out, out
    readme = README.read_text(encoding="utf-8")
    row = next(ln for ln in readme.splitlines() if ln.startswith("| `runs`"))
    assert "`--older-than DAYS`" in row, row
    prune_clause = row.split("`--prune` turns", 1)[1]
    assert "--older-than" in prune_clause.split("deletes nothing", 1)[1].split("is contained", 1)[0], row
    spec = SPEC.read_text(encoding="utf-8")
    usage = next(ln for ln in spec.splitlines() if "`pla runs [" in ln)
    assert "[--older-than DAYS]" in usage, usage


def _iter583_filtered_note(capsys: pytest.CaptureFixture[str], root: Path) -> None:
    """Iter 583: filters that hide every existing run add ONE stderr note; stdout stays as at HEAD."""
    sd = root / "state"
    _write(sd, "run-a", "alpha goal", None)
    _write(sd, "run-b", "beta goal", None)
    rc, out, err = _run(capsys, "runs", "--json", "--state-dir", str(sd))
    assert rc == 0 and err == "", (rc, out, err)
    k = len(json.loads(out))
    assert k == 2, out
    note = f"note: {k} run(s) under the state dir; none matched the filters\n"
    misses = (
        ["--status", "failed"],  # B1
        ["--goal", "zzz-no-such-goal"],  # B2
        ["--older-than", "30"],  # B2: both runs are fresh
        ["--older-than", "30", "--status", "failed"],  # B3: one note, not one per filter
        ["--goal", "zzz-no-such-goal", "--status", "failed"],  # B3
    )
    for argv in misses:
        rc, out, err = _run(capsys, "runs", *argv, "--state-dir", str(sd))
        assert (rc, out, err) == (0, EMPTY + "\n", note), (argv, rc, out, err)
        rc, out, err = _run(capsys, "runs", *argv, "--json", "--state-dir", str(sd))  # B4
        assert rc == 0 and json.loads(out) == [] and out.strip() == "[]", (argv, rc, out)
        assert err == note, (argv, err)
        # B9: deterministic -- the identical invocation is byte-identical on both streams.
        assert _run(capsys, "runs", *argv, "--json", "--state-dir", str(sd)) == (rc, out, err), argv
    # B5: a filter that matches leaves stderr empty in both modes.
    rc, out, err = _run(capsys, "runs", "--goal", "ALPHA", "--state-dir", str(sd))
    assert rc == 0 and err == "" and "run-a" in out and "run-b" not in out, (rc, out, err)
    rc, out, err = _run(capsys, "runs", "--goal", "alpha", "--json", "--state-dir", str(sd))
    assert rc == 0 and err == "" and _ids(json.loads(out)) == ["run-a"], (rc, out, err)
    rc, out, err = _run(capsys, "runs", "--state-dir", str(sd))
    assert rc == 0 and err == "" and "run-a" in out and "run-b" in out, (rc, out, err)
    # B6: empty existing dir and absent dir, unfiltered and filtered -- never a note.
    empty = root / "empty"
    empty.mkdir()
    for target in (empty, root / "absent"):
        for extra in ([], ["--goal", "zzz-no-such-goal"]):
            rc, out, err = _run(capsys, "runs", *extra, "--state-dir", str(target))
            assert (rc, out, err) == (0, EMPTY + "\n", ""), (target, extra, rc, out, err)
            rc, out, err = _run(capsys, "runs", *extra, "--json", "--state-dir", str(target))
            assert rc == 0 and json.loads(out) == [] and err == "", (target, extra, out, err)
    # B7: --summary never notes, even when the filters hide every run.
    for mode in ([], ["--json"]):
        rc, out, err = _run(capsys, "runs", "--summary", "--status", "failed", *mode, "--state-dir", str(sd))
        assert rc == 0 and err == "", (mode, rc, out, err)
    rc, out, _ = _run(capsys, "runs", "--summary", "--goal", "zzz-no-such-goal", "--json", "--state-dir", str(sd))
    assert json.loads(out)["runs"] == 0, out
    # B8: --prune never notes, dry run or --json, matched or not; nothing is deleted.
    for extra in ([], ["--json"]):
        rc, out, err = _run(capsys, "runs", "--prune", "--goal", "zzz-no-such-goal", *extra, "--state-dir", str(sd))
        assert rc == 0 and "none matched" not in err and "note:" not in err, (extra, rc, out, err)
    assert sorted(p.name for p in sd.iterdir()) == ["run-a", "run-b"]


def _iter584_explain_default_slate(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, root: Path
) -> None:
    """iter 584: ``explain`` without ``--slate`` audits ``<state_dir>/slate.json``."""
    from proactive_loop.models import CandidateGoal, GoalSlate

    def run(argv: list[str]) -> tuple[int, str, str]:
        capsys.readouterr()
        rc = cli.main(argv)
        cap = capsys.readouterr()
        return rc, cap.out, cap.err

    d = root / "sd"
    d.mkdir(parents=True)
    goal = CandidateGoal(
        title="Learn RAG evaluation", rationale="study eval before the interview",
        category="learning", impact=5.0, urgency=4.0, confidence=0.9,
        effort_weight=1.0, appropriate_now=True, sources=["file:notes.md"],
        suggested_first_steps=["read the paper"],
    )
    slate = d / "slate.json"
    slate.write_text(GoalSlate(workspace_root=str(root), goals=[goal]).model_dump_json())
    gid = GoalSlate.model_validate_json(slate.read_text()).ranked()[0].id
    base = ["explain", "--state-dir", str(d)]
    # B1 + B2: default == explicit, for plain / --goal-id / --json / both
    for extra in ([], ["--goal-id", gid], ["--json"], ["--goal-id", gid, "--json"]):
        got = run(base + extra)
        want = run(base + ["--slate", str(slate)] + extra)
        assert got == want, (extra, got, want)
        assert got[0] == 0 and got[1].strip(), (extra, got)
    # B4: PLA_STATE_DIR alone selects the default slate
    monkeypatch.setenv("PLA_STATE_DIR", str(d))
    try:
        assert run(["explain"]) == run(base + ["--slate", str(slate)])
    finally:
        monkeypatch.delenv("PLA_STATE_DIR", raising=False)
    # B3: absent default -> rc 2 naming the resolved path, no usage, no traceback
    empty = root / "empty"
    empty.mkdir()
    rc, out, err = run(["explain", "--state-dir", str(empty)])
    assert rc == 2 and out == "", (rc, out, err)
    assert f"error: slate file not found: {empty / 'slate.json'}" in err, err
    assert "usage:" not in err and "Traceback" not in err, err
    # B5: explicit --slate wins; a missing explicit path names P
    missing = root / "nope.json"
    rc, out, err = run(base + ["--slate", str(missing)])
    assert rc == 2 and out == "" and f"slate file not found: {missing}" in err, err
    # B6: help shows --slate optional and names the default
    with pytest.raises(SystemExit) as ex:
        run(["explain", "--help"])
    assert ex.value.code == 0
    helptext = capsys.readouterr().out
    usage = " ".join(helptext.split("\n\n")[0].split())
    assert "[--slate" in usage, usage
    flat = " ".join(helptext.split())
    assert "slate.json" in flat and "state_dir" in flat.replace("state-dir", "state_dir"), flat
    # B7: dispatch / verify still require --slate (argparse usage error)
    for verb in ("dispatch", "verify"):
        capsys.readouterr()
        with pytest.raises(SystemExit) as ex:
            cli.main([verb, "--state-dir", str(d)])
        assert ex.value.code == 2, verb
        verr = capsys.readouterr().err
        assert "usage:" in verr and "--slate" in verr, (verb, verr)


_ITER586_USAGE: Final = r"^  - `pla ([a-z-]+)((?: [^`]*)?)`"
_ITER586_ALLOW: Final = {"dispatch": {"--goal-id", "--title"}, "diff": {"--old", "--new"}}


def _iter586_usage_violations(spec_text: str) -> list[tuple[str, str]]:
    """iter 586 guard: (verb, flag) pairs a SPEC usage line shows unbracketed that
    are neither argparse-required nor allowlisted; also rejects a stale allowlist."""
    import argparse
    import re

    parser = cli.build_parser()
    subs = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    unbracketed: dict[str, set[str]] = {}
    for m in re.finditer(_ITER586_USAGE, spec_text, flags=re.MULTILINE):
        verb, rest = m.group(1), m.group(2)
        assert verb in subs.choices, (verb, m.group(0))  # B6
        prev = None
        while prev != rest:
            prev, rest = rest, re.sub(r"\[[^\[\]]*\]", "", rest)
        unbracketed.setdefault(verb, set()).update(re.findall(r"--[a-z][a-z0-9-]*", rest))
    assert len(unbracketed) >= 10, sorted(unbracketed)  # the regex really matched §4.5
    bad: list[tuple[str, str]] = []
    for verb, flags in sorted(unbracketed.items()):
        required = {
            s for a in subs.choices[verb]._actions if a.required for s in a.option_strings
        }
        bad += [(verb, f) for f in sorted(flags) if f not in required | _ITER586_ALLOW.get(verb, set())]
    for verb, allowed in _ITER586_ALLOW.items():  # B5: the allowlist cannot rot
        acts = {s: a for a in subs.choices[verb]._actions for s in a.option_strings}
        for flag in sorted(allowed):
            assert flag in unbracketed.get(verb, set()), ("stale allowlist", verb, flag)
            assert flag in acts and not acts[flag].required, ("now required", verb, flag)
    return bad


def _iter586_spec_usage_required_flags() -> None:
    """iter 586: SPEC §4.5 ``explain`` shows ``--slate`` optional, and every flag a
    usage line shows outside ``[...]`` is really required (or allowlisted)."""
    import re

    raw = SPEC.read_bytes()
    text = raw.decode("utf-8")
    assert len(raw) < 94_700, len(raw)  # B3
    lines = [ln for ln in text.splitlines() if ln.startswith("  - `pla explain ")]
    assert lines == ["  - `pla explain [--slate FILE] [--goal-id ID]` — read-only, LLM-free auditor"], lines
    assert "pla explain --slate slate.json" not in text  # B1
    start = text.index("  - `pla explain ")
    nxt = text.find("\n  - `pla ", start + 1)
    entry = text[start : nxt if nxt != -1 else len(text)]
    assert "stays required." not in entry, entry  # B2
    assert entry.count("defaults to `<state-dir>/slate.json`") == 1, entry
    assert "Missing slate" in entry, entry
    assert _iter586_usage_violations(text) == []  # B4
    # B8: the ledger bump ships with its row (the ROADMAP byte pin stays owned by
    # test_iter280/308 -- test_iter172 forbids a new module bounding its size)
    roadmap = REPO / "ROADMAP.md"
    t264 = (REPO / "tests" / "test_iter264_behavior.py").read_text()
    m = re.search(r"^EXPECTED_LEDGER_ROWS[^=]*=\s*(\d+)", t264, flags=re.MULTILINE)
    assert m is not None and int(m.group(1)) >= 162, m  # later rows only raise it
    assert "#373" in roadmap.read_text(encoding="utf-8")


def test_runs_older_than_filters_by_checkpoint_age(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    for key in list(os.environ):
        if key.startswith("PLA_"):
            monkeypatch.delenv(key, raising=False)
    sd = _state_dir(tmp_path)
    _b1_b2_listing(capsys, sd)
    _b3_json(capsys, sd)
    _b4_summary(capsys, sd)
    _b5_compose(capsys, sd)
    _b6_dry_run(capsys, sd)
    _b8_validation(capsys, sd)
    _b10_docs(capsys)
    _b7_prune_yes(capsys, sd)  # destructive: last
    _iter583_filtered_note(capsys, tmp_path / "iter583")
    _iter584_explain_default_slate(capsys, monkeypatch, tmp_path / "iter584")
    _iter586_spec_usage_required_flags()
    assert iter587_trace_newest(capsys, tmp_path / "iter587") == 5  # trace newest-run default
    assert iter588_run_dir_not_a_directory(capsys, tmp_path / "iter588") == 5  # --run-dir <file>
    assert iter589_scripted_file_faults(capsys, tmp_path / "iter589") == 3  # script file faults
