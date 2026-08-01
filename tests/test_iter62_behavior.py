"""Black-box behavior tests for iteration 62 --- the new ``pla run --dry-run``
preview flag: a confirm-before-you-act twin of the product's only autonomous
verb. ``run --dry-run`` performs the identical scan + gate + render + slate-write
path, prints the single goal ``run`` WOULD auto-dispatch (plus a paste-ready
``pla dispatch`` command), then STOPS before building the GoalLoop --- no run
directory, no checkpoint, no artifacts, no loop iteration. Additive argparse
``store_true`` flag on the ``run`` subcommand only; no version bump.

ISOLATION CONTRACT (honored): these tests are written strictly against the
public contract for this iteration --- the spec's "Expected Behaviors"
(``pm.md``), ``README.md``, and ``SPEC.md`` --- and drive ONLY documented public
surfaces: the ``pla`` CLI via ``proactive_loop.cli.main(argv) -> int`` (its
observable stdout / stderr / exit code + the artifacts it writes on disk) and the
public domain API (``proactive_loop.models.GoalSlate`` /
``proactive_loop.scout.gate_slate`` / ``proactive_loop.config.Settings``), the
same public seam the shipped ``tests/test_cli_integration.py`` uses. **No file
under ``src/`` was read, no engineer/reviewer notes were read, and no
``git diff`` was consulted.** Every test is fully offline: zero network, zero API
keys, driven by the bundled ``scripted`` provider + demo fixtures.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from proactive_loop.cli import main
from proactive_loop.config import Settings
from proactive_loop.models import AutonomyDecision, GoalSlate
from proactive_loop.scout import gate_slate

# The bundled demo pair (the exact pair `make demo` and test_cli_integration
# use). Its synthesized slate has exactly ONE top AUTO_DISPATCH goal.
REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "examples" / "fixture_workspace"
SCRIPT = REPO / "examples" / "scripted_responses.json"

# The distinct present-tense dispatch marker of the NON-dry path. The dry-run
# line uses "would auto-dispatch", which does NOT contain this substring.
_DISPATCH_MARKER = "auto-dispatching top goal"
_DRY_PREVIEW_PREFIX = "[dry-run] would auto-dispatch top goal:"
_NOTHING_TO_RUN = "no auto-dispatchable goal in this slate; nothing to run."
_NEEDS_APPROVAL_HEADER = "goal(s) need approval and were NOT auto-run:"

# A synthesized goal id is a 12-char lowercase-hex token (random per scan); the
# state-dir path is per-tmp. Both are normalized away when comparing rendered
# blocks across two independent runs (behavior 8).
_HEX12 = re.compile(r"\b[0-9a-f]{12}\b")


# --------------------------------------------------------------------------
# Helpers --- black-box: drive main(), read back exit code + stdout/stderr.
# --------------------------------------------------------------------------


def _base_args(state_dir: Path) -> list[str]:
    """The demo argument vector into a tmp state dir (no --dry-run)."""
    return [
        "run",
        "--workspace", str(FIXTURE),
        "--provider", "scripted",
        "--scripted-responses", str(SCRIPT),
        "--state-dir", str(state_dir),
    ]


def _run(argv: list[str], capsys) -> tuple[int, str, str]:
    rc = main(argv)
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def _clear_threshold(monkeypatch) -> None:
    """Ensure the CLI's default auto-dispatch threshold (4.0) is in effect so
    it agrees with a bare ``Settings()`` used to independently find the top
    AUTO goal."""
    monkeypatch.delenv("PLA_AUTO_DISPATCH_MIN_SCORE", raising=False)


def _dry_run(tmp_path, capsys, monkeypatch) -> tuple[int, str, str, Path, GoalSlate]:
    """Run `pla run ... --dry-run` into a fresh state dir; return
    (rc, out, err, state_dir, slate)."""
    _clear_threshold(monkeypatch)
    state_dir = tmp_path / "state"
    rc, out, err = _run(_base_args(state_dir) + ["--dry-run"], capsys)
    slate_path = state_dir / "slate.json"
    slate = GoalSlate.model_validate_json(slate_path.read_text())
    return rc, out, err, state_dir, slate


def _top_auto_goal(slate: GoalSlate):
    """The single goal `run` would auto-dispatch: the highest-ranked goal whose
    live gate decision is AUTO_DISPATCH (or None if the slate has none). Derived
    independently of the CLI via the public gate, so the tests encode the
    CONTRACT, not the implementation's own choice."""
    decisions = {d.goal_id: d for d in gate_slate(slate, Settings())}
    for g in slate.ranked():
        if decisions[g.id].decision == AutonomyDecision.AUTO_DISPATCH:
            return g
    return None


def _needs_approval_block(out: str) -> list[str]:
    """The rendered NEEDS_APPROVAL block: from the `N goal(s) need approval...`
    header up to (but not including) the final decision line, trailing blanks
    trimmed."""
    lines = out.splitlines()
    start = next(i for i, ln in enumerate(lines) if _NEEDS_APPROVAL_HEADER in ln)
    block = [lines[start]]
    for ln in lines[start + 1:]:
        if (_DRY_PREVIEW_PREFIX in ln
                or ln.startswith(_DISPATCH_MARKER)
                or _NOTHING_TO_RUN in ln):
            break
        block.append(ln)
    while block and not block[-1].strip():
        block.pop()
    return block


def _norm(text: str, state_dir: Path) -> str:
    """Erase the two volatile parts (per-tmp state-dir path, random goal ids)
    so two independent runs' rendered blocks can be compared byte-for-byte."""
    return _HEX12.sub("<ID>", text.replace(str(state_dir), "<SD>"))


# --------------------------------------------------------------------------
# Behavior 1 --- flag exists on `run` help ONLY, default-off.
# --------------------------------------------------------------------------


def test_b01_run_help_lists_dry_run(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["run", "--help"])
    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert "--dry-run" in out, f"`pla run --help` must document --dry-run; got:\n{out}"


def test_b01_scan_help_omits_dry_run(capsys):
    """The flag is on `run` ONLY --- `scan --help` must NOT list it."""
    with pytest.raises(SystemExit) as excinfo:
        main(["scan", "--help"])
    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert "--dry-run" not in out, f"--dry-run must not leak onto `scan`; got:\n{out}"


def test_b01_scan_rejects_dry_run_arg(capsys):
    """Passing --dry-run to another verb is an argparse usage error (exit 2)."""
    with pytest.raises(SystemExit) as excinfo:
        main([
            "scan",
            "--workspace", str(FIXTURE),
            "--provider", "scripted",
            "--scripted-responses", str(SCRIPT),
            "--dry-run",
        ])
    assert excinfo.value.code == 2


# --------------------------------------------------------------------------
# Behavior 2 --- dry-run on a slate WITH an auto-dispatchable goal exits 0.
# --------------------------------------------------------------------------


def test_b02_dry_run_exits_zero(tmp_path, capsys, monkeypatch):
    rc, _out, _err, _sd, slate = _dry_run(tmp_path, capsys, monkeypatch)
    assert rc == 0
    # Precondition sanity: the demo slate really does have a top AUTO goal.
    assert _top_auto_goal(slate) is not None, (
        "demo pair must synthesize at least one AUTO_DISPATCH goal for this test"
    )


# --------------------------------------------------------------------------
# Behavior 3 --- prints the ranked table AND the dry-run preview line.
# --------------------------------------------------------------------------


def test_b03_dry_run_prints_table_and_preview_line(tmp_path, capsys, monkeypatch):
    rc, out, _err, _sd, slate = _dry_run(tmp_path, capsys, monkeypatch)
    assert rc == 0
    assert "DECISION" in out, f"dry-run must print the ranked gate table; got:\n{out}"
    top = _top_auto_goal(slate)
    expected = f"{_DRY_PREVIEW_PREFIX} {top.title}"
    assert expected in out, (
        f"dry-run must print the preview line {expected!r}; got:\n{out}"
    )


# --------------------------------------------------------------------------
# Behavior 4 --- prints a paste-ready `pla dispatch` command for the top goal.
# --------------------------------------------------------------------------


def test_b04_dry_run_prints_paste_ready_dispatch_command(tmp_path, capsys, monkeypatch):
    rc, out, _err, state_dir, slate = _dry_run(tmp_path, capsys, monkeypatch)
    assert rc == 0
    top = _top_auto_goal(slate)
    slate_path = str(state_dir / "slate.json")
    needed = ["pla dispatch", "--slate", slate_path, "--goal-id", top.id]
    matches = [ln for ln in out.splitlines() if all(s in ln for s in needed)]
    assert matches, (
        "dry-run must print one paste-ready command line containing all of "
        f"{needed!r} (with the TOP goal's id, disambiguating it from the "
        f"needs-approval --yes lines); got:\n{out}"
    )


# --------------------------------------------------------------------------
# Behavior 5 --- dry-run does NOT execute (present-tense marker absent).
# --------------------------------------------------------------------------


def test_b05_dry_run_does_not_execute(tmp_path, capsys, monkeypatch):
    rc, out, _err, _sd, _slate = _dry_run(tmp_path, capsys, monkeypatch)
    assert rc == 0
    assert _DISPATCH_MARKER not in out, (
        f"dry-run must NOT print the non-dry marker {_DISPATCH_MARKER!r}; got:\n{out}"
    )
    # ...yet it DID print the distinct dry-run phrasing (which never contains it).
    assert _DRY_PREVIEW_PREFIX in out


# --------------------------------------------------------------------------
# Behavior 6 --- writes the slate (faithful mirror) but NO run dir / checkpoint /
# artifacts.
# --------------------------------------------------------------------------


def test_b06_dry_run_writes_slate_but_no_run_side_effects(tmp_path, capsys, monkeypatch):
    rc, _out, _err, state_dir, slate = _dry_run(tmp_path, capsys, monkeypatch)
    assert rc == 0
    # Slate was written and is a valid GoalSlate (already parsed in _dry_run).
    assert (state_dir / "slate.json").is_file()
    assert isinstance(slate, GoalSlate) and slate.goals
    # The core safety property: NO dispatch, NO loop iteration => no run dir,
    # no checkpoint, no artifacts anywhere under the state dir.
    assert list(state_dir.glob("run-*")) == [], "dry-run must create NO run directory"
    assert list(state_dir.rglob("checkpoint.json")) == [], "dry-run must write NO checkpoint"
    assert [p for p in state_dir.rglob("artifacts") if p.is_dir()] == [], (
        "dry-run must create NO artifacts dir"
    )


# --------------------------------------------------------------------------
# Behavior 7 --- dry-run on a slate with ZERO auto-dispatchable goals prints the
# existing "nothing to run" message and creates no run dir.
#
# NOTE (PM feedback): the spec's suggested threshold `9.99` is TOO LOW for the
# demo fixture --- its top auto-eligible (non-sensitive, appropriate_now) goal
# scores 18.00, so 9.99 still auto-dispatches it. The correct way to force ZERO
# auto-dispatchable goals is a threshold above EVERY goal's score (max is the
# sensitive goal at 25.00). We use `99.99` (finite, so it is not rejected by the
# `+inf` guard) --- the most reasonable reading of "above every goal's score".
# --------------------------------------------------------------------------


def test_b07_dry_run_nothing_to_run_when_no_auto_goal(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("PLA_AUTO_DISPATCH_MIN_SCORE", "99.99")
    state_dir = tmp_path / "state"
    rc, out, _err = _run(_base_args(state_dir) + ["--dry-run"], capsys)
    assert rc == 0
    assert _NOTHING_TO_RUN in out, (
        f"with no AUTO goal, dry-run must print {_NOTHING_TO_RUN!r}; got:\n{out}"
    )
    assert list(state_dir.glob("run-*")) == [], "nothing-to-run must create NO run dir"


# --------------------------------------------------------------------------
# Behavior 8 --- the needs-approval listing is identical under dry-run vs not
# (the block precedes the dispatch branch and is unchanged).
# --------------------------------------------------------------------------


def test_b08_needs_approval_block_identical_under_dry_run(tmp_path, capsys, monkeypatch):
    _clear_threshold(monkeypatch)
    # Dry-run.
    sd_dry = tmp_path / "dry"
    _rc, out_dry, _err = _run(_base_args(sd_dry) + ["--dry-run"], capsys)
    # Plain run (into a separate state dir --- it dispatches for real).
    sd_plain = tmp_path / "plain"
    _rc2, out_plain, _err2 = _run(_base_args(sd_plain), capsys)

    block_dry = _norm("\n".join(_needs_approval_block(out_dry)), sd_dry)
    block_plain = _norm("\n".join(_needs_approval_block(out_plain)), sd_plain)
    assert block_dry, "fixture must contain NEEDS_APPROVAL goals for this test"
    assert block_dry == block_plain, (
        "the needs-approval block must render IDENTICALLY with/without --dry-run.\n"
        f"--dry-run:\n{block_dry}\n\nplain:\n{block_plain}"
    )


# --------------------------------------------------------------------------
# Behavior 9 --- backward-compatible regression: plain `run` is byte-unchanged
# (dispatches, one run dir, slate + artifacts + checkpoint, exit 0).
# --------------------------------------------------------------------------


def test_b09_plain_run_unchanged(tmp_path, capsys, monkeypatch):
    _clear_threshold(monkeypatch)
    state_dir = tmp_path / "state"
    rc, out, _err = _run(_base_args(state_dir), capsys)
    assert rc == 0
    assert _DISPATCH_MARKER in out, "plain run must still print the dispatch marker"
    assert _DRY_PREVIEW_PREFIX not in out, "plain run must NOT print the dry-run preview"
    run_dirs = list(state_dir.glob("run-*"))
    assert len(run_dirs) == 1, "plain run must dispatch exactly one goal -> one run dir"
    assert (state_dir / "slate.json").is_file()
    assert (run_dirs[0] / "checkpoint.json").is_file()
    assert (run_dirs[0] / "artifacts").is_dir()


# --------------------------------------------------------------------------
# Behavior 10 --- existing exit-2 front-door guards still fire under --dry-run.
# --------------------------------------------------------------------------


def test_b10_missing_workspace_still_exits_2_under_dry_run(tmp_path, capsys, monkeypatch):
    _clear_threshold(monkeypatch)
    missing = tmp_path / "nope"  # does not exist
    rc, _out, err = _run([
        "run",
        "--workspace", str(missing),
        "--provider", "scripted",
        "--scripted-responses", str(SCRIPT),
        "--state-dir", str(tmp_path / "state"),
        "--dry-run",
    ], capsys)
    assert rc == 2
    assert f"error: workspace not found: {missing}" in err, (
        f"missing workspace must fail fast on stderr; got err:\n{err}"
    )


def test_b10_nondir_statedir_still_exits_2_under_dry_run(tmp_path, capsys, monkeypatch):
    _clear_threshold(monkeypatch)
    bad_state = tmp_path / "state_file"
    bad_state.write_text("i am a file, not a dir")
    rc, _out, err = _run([
        "run",
        "--workspace", str(FIXTURE),
        "--provider", "scripted",
        "--scripted-responses", str(SCRIPT),
        "--state-dir", str(bad_state),
        "--dry-run",
    ], capsys)
    assert rc == 2
    assert "not a directory" in err, (
        f"non-directory --state-dir must fail fast with exit 2; got err:\n{err}"
    )
