"""Black-box behavior tests for iteration 272 (foundry iter 314).

Feature under test: ``pla runs --summary`` -- ONE aggregate of the persisted
resilience counters over every listed run (run count, per-status histogram,
summed ``iterations`` / ``artifacts`` / ``retries`` / ``parse_errors``), as a
two-line human form or ONE JSON object under ``--json``; refused with ``--prune``.

ISOLATION CONTRACT (honored): written strictly against this iteration's spec
"Expected Behaviors", ``README.md`` and ``SPEC.md``; drives only the public
``pla`` CLI via ``proactive_loop.cli.main([...])``. No file under ``src/`` was
read, no engineer/reviewer notes were read, no ``git diff`` was consulted. Every
test uses a fresh ``tmp_path`` state dir and runs fully offline: the only run
that is not fabricated comes from the scripted (offline) provider, via the
setup helpers ``tests/test_iter04_behavior.py`` already exports.
"""

from __future__ import annotations

import json
import shutil
from collections import Counter
from pathlib import Path

import pytest

from proactive_loop.cli import main
from tests.test_iter04_behavior import _make_run_dir, _produce_demo_run

_NO_CHECKPOINT = "(no checkpoint)"
_EMPTY_LINES = [
    "runs: 0",
    "iterations: 0  artifacts: 0  retries: 0  parse_errors: 0",
]
_SUMMARY_KEYS = {"runs", "by_status", "iterations", "artifacts", "retries", "parse_errors"}
_SUM_FIELDS = ("iterations", "artifacts", "retries", "parse_errors")
_ROW_KEYS = {
    "run_id", "status", "goal", "iterations", "artifacts", "workspace", "retries", "parse_errors",
}
# Non-zero counters planted on the fabricated ``failed`` run so a summary that
# silently dropped the resilience counters (or the second run) cannot pass.
_FAILED_RETRIES = 2
_FAILED_PARSE_ERRORS = 1


# ---------------------------------------------------------------------------
# Setup helpers
# ---------------------------------------------------------------------------


def _listing(state_dir: Path, capsys: pytest.CaptureFixture[str], *extra: str) -> list[dict]:
    """The rows ``runs --json`` reports for ``state_dir`` (stdout drained)."""
    rc = main(["runs", "--state-dir", str(state_dir), "--json", *extra])
    out = capsys.readouterr().out
    assert rc == 0, f"`runs --json` setup must exit 0, got {rc}"
    rows = json.loads(out)
    assert isinstance(rows, list)
    return rows


def _summary_json(state_dir: Path, capsys: pytest.CaptureFixture[str], *extra: str) -> dict:
    rc = main(["runs", "--state-dir", str(state_dir), "--summary", "--json", *extra])
    out, err = capsys.readouterr()
    assert rc == 0, f"`runs --summary --json` must exit 0, got {rc}; stderr={err!r}"
    assert err == "", f"nothing may go to stderr, got {err!r}"
    payload = json.loads(out)
    assert isinstance(payload, dict), f"--summary --json must print ONE object, got {out!r}"
    return payload


def _fabricate_failed_copy(state_dir: Path, source: Path, name: str) -> Path:
    """Copy a real run dir to a sibling ``run-*`` and rewrite its checkpoint's
    top-level ``status`` / ``retries`` / ``parse_errors`` (plain JSON, RunState
    fields) so the fleet gains a second status with non-zero counters."""
    target = state_dir / name
    shutil.copytree(source, target)
    cp = target / "checkpoint.json"
    data = json.loads(cp.read_text())
    data["status"] = "failed"
    data["retries"] = _FAILED_RETRIES
    data["parse_errors"] = _FAILED_PARSE_ERRORS
    cp.write_text(json.dumps(data))
    return target


def _three_run_fleet(
    state_dir: Path, capsys: pytest.CaptureFixture[str]
) -> dict:
    """One real ``done`` run, one fabricated ``failed`` copy of it, one degraded
    checkpoint-less dir. Returns the real run's own listing row (captured
    BEFORE the copies exist) so expected sums are derived from the public
    listing, never hard-coded to the fixture."""
    _produce_demo_run(state_dir)
    capsys.readouterr()  # drain the demo's output
    (base_row,) = _listing(state_dir, capsys)
    source = state_dir / base_row["run_id"]
    _fabricate_failed_copy(state_dir, source, "run-fab1ed00000f")
    _make_run_dir(state_dir, "run-n0checkp01nt", meta={"workspace_root": "/somewhere"})
    return base_row


# ---------------------------------------------------------------------------
# Item budget: tests/test_iter270_behavior.py::test_b7 (shipped, foundry iter 312)
# requires binding_headroom >= 20, and the gauge reports binding_at - live - 1 with
# binding_at=6099, i.e. live <= 6078; the tree before this module collected 6074, so
# this oracle owns exactly FOUR collected items. Every Expected Behavior is still asserted -- several per item -- so the
# budget is spent on assertions, not on `def test_` lines.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Behaviors 1 + 3 (empty case) -- absent or empty state dir: two zero lines, or
# one JSON object with an empty histogram.
# ---------------------------------------------------------------------------


def test_b1_b3_empty_aggregate_human_and_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    absent = tmp_path / "absent"
    assert not absent.exists()

    for state_dir in (absent, empty):
        rc = main(["runs", "--state-dir", str(state_dir), "--summary"])
        out, err = capsys.readouterr()
        assert rc == 0, f"`runs --summary` on {state_dir.name} state dir must exit 0, got {rc}"
        assert err == "", f"nothing may go to stderr, got {err!r}"
        assert out.splitlines() == _EMPTY_LINES, f"unexpected stdout:\n{out}"
        assert out.endswith("\n") and out.count("\n") == 2, f"exactly two lines, got {out!r}"

        payload = _summary_json(state_dir, capsys)
        assert payload == {
            "runs": 0,
            "by_status": {},
            "iterations": 0,
            "artifacts": 0,
            "retries": 0,
            "parse_errors": 0,
        }, payload


# ---------------------------------------------------------------------------
# Behaviors 2 + 3 -- populated aggregate: human two-line form and the JSON object.
# ---------------------------------------------------------------------------


def test_b2_b3_populated_aggregate_human_and_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    state_dir = tmp_path / "state"
    base = _three_run_fleet(state_dir, capsys)
    # The failed copy shares the real run's iterations/artifacts and adds the
    # planted counters; the degraded dir contributes zeros.
    want = {
        "iterations": 2 * base["iterations"],
        "artifacts": 2 * base["artifacts"],
        "retries": 2 * base["retries"] + _FAILED_RETRIES,
        "parse_errors": 2 * base["parse_errors"] + _FAILED_PARSE_ERRORS,
    }
    assert want["retries"] > 0 and want["parse_errors"] > 0, "planted counters must be visible"

    # Behavior 2 -- human form.
    rc = main(["runs", "--state-dir", str(state_dir), "--summary"])
    out, err = capsys.readouterr()
    assert rc == 0 and err == "", f"rc={rc} stderr={err!r}"
    lines = out.splitlines()
    assert len(lines) == 2, f"exactly two lines expected, got:\n{out}"
    # Statuses sorted ascending as strings: '(' < 'd' < 'f'.
    assert lines[0] == f"runs: 3 ({_NO_CHECKPOINT} 1, done 1, failed 1)", lines[0]
    expected = "  ".join(f"{field}: {want[field]}" for field in _SUM_FIELDS)
    assert lines[1] == expected, f"line 2 mismatch:\n got: {lines[1]!r}\nwant: {expected!r}"
    assert "   " not in lines[1], "fields are separated by exactly TWO spaces"

    # Behavior 3 -- JSON form.
    payload = _summary_json(state_dir, capsys)
    assert set(payload) == _SUMMARY_KEYS, f"exact key set violated: {sorted(payload)}"
    assert payload["runs"] == 3 and type(payload["runs"]) is int
    for field in _SUM_FIELDS:
        assert type(payload[field]) is int, f"{field} must be a JSON integer, got {payload[field]!r}"
        assert payload[field] == want[field], field
    assert payload["by_status"] == {_NO_CHECKPOINT: 1, "done": 1, "failed": 1}
    assert list(payload["by_status"]) == sorted(payload["by_status"]), "by_status keys sorted"
    assert all(type(v) is int for v in payload["by_status"].values())


# ---------------------------------------------------------------------------
# Behaviors 4 + 5 -- --status composes with --summary, and the summary agrees
# with the listing for every selection.
# ---------------------------------------------------------------------------


def test_b4_b5_status_filter_composes_and_matches_the_listing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    state_dir = tmp_path / "state"
    base = _three_run_fleet(state_dir, capsys)

    # Behavior 4 -- the filter narrows the aggregate to that status alone.
    failed = _summary_json(state_dir, capsys, "--status", "failed")
    assert failed["runs"] == 1 and failed["by_status"] == {"failed": 1}
    assert failed["retries"] == base["retries"] + _FAILED_RETRIES
    assert failed["parse_errors"] == base["parse_errors"] + _FAILED_PARSE_ERRORS
    done = _summary_json(state_dir, capsys, "--status", "done")
    assert done["runs"] == 1 and done["by_status"] == {"done": 1}
    assert done["retries"] == base["retries"] and done["iterations"] == base["iterations"]
    # A status with no runs yields the behavior-1 empty aggregate, human form too.
    rc = main(["runs", "--state-dir", str(state_dir), "--summary", "--status", "pending"])
    out, err = capsys.readouterr()
    assert rc == 0 and err == "", f"rc={rc} stderr={err!r}"
    assert out.splitlines() == _EMPTY_LINES, out

    # Behavior 5 -- self-consistency with `runs --json` under the same selection.
    for selection in ((), ("--status", "done"), ("--status", "failed"), ("--status", "pending")):
        rows = _listing(state_dir, capsys, *selection)
        payload = _summary_json(state_dir, capsys, *selection)
        assert payload["runs"] == len(rows), selection
        for field in _SUM_FIELDS:
            assert payload[field] == sum(row[field] for row in rows), (selection, field)
        assert payload["by_status"] == dict(Counter(row["status"] for row in rows)), selection


# ---------------------------------------------------------------------------
# Behaviors 6 + 7 + 8 -- --summary refuses --prune and deletes nothing; the
# default listing paths are untouched; --summary is in --help.
# ---------------------------------------------------------------------------


def test_b6_b7_b8_prune_refusal_default_paths_and_help(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    state_dir = tmp_path / "state"
    _three_run_fleet(state_dir, capsys)
    before = sorted(p.name for p in state_dir.glob("run-*"))
    assert len(before) == 3

    # Behavior 6 -- refusal with --prune, with or without --yes: exit 2, one
    # stderr line, empty stdout, every run dir still present.
    for confirm in ((), ("--yes",)):
        rc = main(["runs", "--state-dir", str(state_dir), "--summary", "--prune", *confirm])
        out, err = capsys.readouterr()
        assert rc == 2, f"--summary with --prune {confirm} must exit 2, got {rc}"
        assert out == "", f"nothing may go to stdout, got {out!r}"
        assert err.splitlines() == ["error: --summary cannot be combined with --prune"], err
        after = sorted(p.name for p in state_dir.glob("run-*"))
        assert after == before, f"refusal must delete no run dir: before={before} after={after}"

    # Behavior 7 -- `runs --json` is still an ARRAY of eight-key rows.
    rows = _listing(state_dir, capsys)
    assert len(rows) == 3
    for row in rows:
        assert set(row) == _ROW_KEYS, f"row key set drifted: {sorted(row)}"
    assert sorted(row["status"] for row in rows) == [_NO_CHECKPOINT, "done", "failed"]
    only_failed = _listing(state_dir, capsys, "--status", "failed")
    assert [row["status"] for row in only_failed] == ["failed"]
    # Human table still lists every run and is not the two-line summary.
    rc = main(["runs", "--state-dir", str(state_dir)])
    out, err = capsys.readouterr()
    assert rc == 0 and err == "", f"rc={rc} stderr={err!r}"
    assert not out.startswith("runs: "), "human table must not be replaced by the summary"
    for row in rows:
        assert row["run_id"] in out, f"{row['run_id']} missing from the human table:\n{out}"
    # --prune stays a dry run by default and still works without --summary.
    rc = main(["runs", "--state-dir", str(state_dir), "--prune"])
    capsys.readouterr()
    assert rc == 0
    assert sorted(p.name for p in state_dir.glob("run-*")) == sorted(r["run_id"] for r in rows)

    # Behavior 8 -- discoverable.
    with pytest.raises(SystemExit) as exc:
        main(["runs", "--help"])
    out = capsys.readouterr().out
    assert exc.value.code == 0
    assert "--summary" in out, f"`runs --help` must document --summary:\n{out}"
    assert "--prune" in out and "--status" in out
