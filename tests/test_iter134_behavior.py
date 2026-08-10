"""Black-box behavior tests for iteration 134 --- crash-safe writes for the two
remaining JSON writers.

Feature under test: the product's headline L0 promise ("atomic JSON checkpoints
-> resumable runs") was implemented in full by exactly ONE of three writers.
This iteration finishes the idiom. ``Checkpoint.save`` keeps its temp-sibling +
``os.replace`` swap but gains the ``try``/``finally`` temp cleanup it lacked, so
a failed swap can no longer strand ``checkpoint.json.tmp`` in a documented,
user-visible run dir. The once-per-run ``meta.json`` writer stops writing the
target in place and becomes a temp sibling + ONE ``os.replace`` + the same
cleanup, so the one file recording ``workspace_root`` (which a later ``resume``
can get nowhere else) can never be left truncated on disk. Success bytes,
schemas, exit codes and the pre-existing tolerant degrade paths are unchanged.

ISOLATION CONTRACT (honored): every assertion below is written against THIS
iteration's spec (``pm.md`` "Expected Behaviors" 1-11) and drives only public
or spec-authorized surfaces --- the ``pla`` CLI through
``proactive_loop.cli.main(argv) -> int`` (its stdout / exit codes / on-disk
artifacts), the public ``proactive_loop.loop.Checkpoint`` +
``proactive_loop.models`` persistence seam (the same seam
``tests/test_iter71_behavior.py`` and ``tests/test_iter04_behavior.py`` use),
and the private imports this iteration's spec EXPLICITLY authorizes
(``from proactive_loop.cli import _write_meta, _read_meta``; in-tree precedent:
``tests/test_iter122_behavior.py`` imports ``_write_slate``,
``tests/test_iter113_behavior.py`` imports ``_TOOL_CATALOG``). **No file under
``src/`` was read, no engineer or reviewer notes were read, and no ``git diff``
was consulted.**

Fully offline and deterministic: zero network, zero API keys, the scripted
provider seam only, no sleeps. Every writer under test is pointed at a
``tmp_path`` directory; the only in-repo paths read are the two bundled
``examples/`` fixtures that ``make demo`` itself uses (behavior 11).

Failure injection is NARROW BY CONSTRUCTION (spec handoff note): ``os.replace``
and ``Path.unlink`` are swapped by direct attribute assignment inside a
``try``/``finally`` context manager that always restores them, because a
``Path.unlink`` left raising past the call under test breaks pytest's own
``tmp_path`` housekeeping.

AMBIGUITY NOTES (PM feedback):
* Behaviors 4/5 say "the temp-file unlink also raising" without naming the call.
  A cleanup could route through ``Path.unlink``, ``os.unlink`` or ``os.remove``,
  so all three are patched and the test asserts only that AT LEAST ONE fired
  (i.e. cleanup was attempted) rather than which one --- pinning the syscall
  would encode an implementation choice, and asserting nothing would let both
  tests pass vacuously.
* Behavior 10b says the truncated-``meta.json`` row carries "an empty
  ``workspace`` value". Tested as the falsy reading (``not row["workspace"]``),
  which admits both ``""`` and a missing/None value, with the observed row in
  the failure message.
"""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

import pytest

from proactive_loop.cli import _read_meta, _write_meta, _write_slate, main
from proactive_loop.loop import Checkpoint
from proactive_loop.models import (
    CandidateGoal,
    GoalSlate,
    LoopStep,
    RunState,
    RunStatus,
    StepKind,
)

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "examples" / "scripted_responses.json"
FIXTURE = REPO / "examples" / "fixture_workspace"

_CHECKPOINT_NAME = "checkpoint.json"
_META_NAME = "meta.json"
_TMP_SUFFIX = ".tmp"


# ---------------------------------------------------------------------------
# Helpers --- public models in, observable disk state / stdout / exit codes out.
# ---------------------------------------------------------------------------


@contextmanager
def _patched(target: Any, name: str, value: Any) -> Iterator[None]:
    """Swap one attribute for the duration of the block, ALWAYS restoring it.

    Direct attribute assignment (not ``monkeypatch``) so the restore happens at
    the closing brace of the call under test, never later: a ``Path.unlink``
    left raising would break pytest's ``tmp_path`` teardown.
    """
    original = getattr(target, name)
    setattr(target, name, value)
    try:
        yield
    finally:
        setattr(target, name, original)


def _raiser(message: str) -> Callable[..., None]:
    def _boom(*args: object, **kwargs: object) -> None:
        raise OSError(message)

    return _boom


@contextmanager
def _replace_raises(message: str = "boom") -> Iterator[None]:
    with _patched(os, "replace", _raiser(message)):
        yield


@contextmanager
def _unlink_raises(message: str = "cleanup") -> Iterator[list[str]]:
    """Every plausible temp-removal route raises; returns the call log."""
    calls: list[str] = []

    def _boom_path(self: Path, *args: object, **kwargs: object) -> None:
        calls.append(str(self))
        raise OSError(message)

    def _boom_os(path: object, *args: object, **kwargs: object) -> None:
        calls.append(str(path))
        raise OSError(message)

    with _patched(Path, "unlink", _boom_path):
        with _patched(os, "unlink", _boom_os):
            with _patched(os, "remove", _boom_os):
                yield calls


@contextmanager
def _replace_recorder() -> Iterator[list[tuple[Path, Path]]]:
    """Record every (src, dst) pair, then perform the REAL replace."""
    real = os.replace
    seen: list[tuple[Path, Path]] = []

    def _spy(src: Any, dst: Any, *args: object, **kwargs: object) -> None:
        seen.append((Path(os.fspath(src)), Path(os.fspath(dst))))
        real(src, dst, *args, **kwargs)

    with _patched(os, "replace", _spy):
        yield seen


def _goal(title: str = "Audit the checkpoint writer") -> CandidateGoal:
    return CandidateGoal(
        title=title,
        rationale="black-box crash-safe-write probe",
        suggested_first_steps=["read the writer"],
    )


def _state(title: str = "Audit the checkpoint writer", *, iterations_used: int = 2) -> RunState:
    return RunState(
        goal=_goal(title),
        status=RunStatus.DONE,
        steps=[
            LoopStep(index=0, kind=StepKind.PLAN, output="thought: probe the writer"),
            LoopStep(index=1, kind=StepKind.CHECK, output="reason: complete", done=True),
        ],
        iterations_used=iterations_used,
        llm_calls_used=2,
    )


def _slate(root: Path, title: str = "Slate guarantee still holds") -> GoalSlate:
    return GoalSlate(workspace_root=str(root), goals=[_goal(title)])


def _names(directory: Path) -> list[str]:
    return sorted(p.name for p in directory.iterdir())


def _tmp_residue(directory: Path) -> list[str]:
    return [n for n in _names(directory) if n.endswith(_TMP_SUFFIX)]


def _meta_mapping(workspace_root: Path, artifacts_dir: Path) -> dict[str, str]:
    return {"workspace_root": str(workspace_root), "artifacts_dir": str(artifacts_dir)}


def _run(argv: list[str], capsys: Any) -> tuple[int, str, str]:
    capsys.readouterr()
    rc = main(argv)
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


# ===========================================================================
# Behavior 1 --- Checkpoint success leaves no temp.
# ===========================================================================


def test_b01_checkpoint_success_leaves_no_temp_and_round_trips(tmp_path):
    path = tmp_path / _CHECKPOINT_NAME
    state = _state("Round trip goal")

    Checkpoint(path).save(state)

    assert path.is_file(), f"checkpoint must exist; dir holds {_names(tmp_path)}"
    assert _tmp_residue(tmp_path) == [], f"leaked temp file: {_names(tmp_path)}"
    assert not (tmp_path / f"{_CHECKPOINT_NAME}{_TMP_SUFFIX}").exists()
    loaded = Checkpoint(path).load()
    assert loaded is not None, "a saved checkpoint must load back"
    assert loaded.model_dump_json() == state.model_dump_json(), (
        "the JSON round trip must equal the saved state"
    )


# ===========================================================================
# Behavior 2 --- Checkpoint temp cleanup on a failed swap.
# ===========================================================================


def test_b02_failed_swap_raises_and_cleans_the_temp(tmp_path):
    path = tmp_path / _CHECKPOINT_NAME

    with _replace_raises("boom"):
        with pytest.raises(OSError) as excinfo:
            Checkpoint(path).save(_state("Failed swap goal"))

    assert "boom" in str(excinfo.value), f"got {excinfo.value!r}"
    assert excinfo.type is OSError, (
        f"the primary OSError must propagate unwrapped, got {excinfo.type!r}"
    )
    assert _tmp_residue(tmp_path) == [], (
        f"a failed swap must leave no temp behind; dir holds {_names(tmp_path)}"
    )


# ===========================================================================
# Behavior 3 --- A failed swap preserves the previous snapshot.
# ===========================================================================


def test_b03_failed_swap_preserves_the_previous_snapshot(tmp_path):
    path = tmp_path / _CHECKPOINT_NAME
    state_a = _state("State A survives", iterations_used=1)
    Checkpoint(path).save(state_a)
    prior = path.read_bytes()

    with _replace_raises("boom"):
        with pytest.raises(OSError):
            Checkpoint(path).save(_state("State B never lands", iterations_used=9))

    assert path.read_bytes() == prior, "the previous snapshot's bytes must survive"
    loaded = Checkpoint(path).load()
    assert loaded is not None
    assert loaded.goal.title == "State A survives", f"got {loaded.goal.title!r}"
    assert loaded.iterations_used == 1, f"got {loaded.iterations_used}"
    assert _tmp_residue(tmp_path) == [], f"dir holds {_names(tmp_path)}"


# ===========================================================================
# Behavior 4 --- Cleanup failure never masks the primary error.
# ===========================================================================


def test_b04_cleanup_failure_never_masks_the_primary_error(tmp_path):
    path = tmp_path / _CHECKPOINT_NAME

    with _replace_raises("primary"):
        with _unlink_raises("cleanup") as unlink_calls:
            with pytest.raises(OSError) as excinfo:
                Checkpoint(path).save(_state("Primary error wins"))

    message = str(excinfo.value)
    assert "primary" in message, f"the primary error must win, got {message!r}"
    assert "cleanup" not in message, f"the cleanup error must be swallowed, got {message!r}"
    assert unlink_calls, (
        "cleanup must be ATTEMPTED on the failure path (no unlink/remove call observed)"
    )


# ===========================================================================
# Behavior 5 --- Cleanup failure never breaks the success path.
# ===========================================================================


def test_b05_cleanup_failure_never_breaks_the_success_path(tmp_path):
    path = tmp_path / _CHECKPOINT_NAME
    state = _state("Success despite cleanup failure")

    with _unlink_raises("cleanup") as unlink_calls:
        Checkpoint(path).save(state)  # must NOT raise

    assert unlink_calls, "cleanup must be attempted on the success path too"
    assert path.is_file(), f"the checkpoint must exist; dir holds {_names(tmp_path)}"
    loaded = Checkpoint(path).load()
    assert loaded is not None and loaded.goal.title == "Success despite cleanup failure"


# ===========================================================================
# Behavior 6 --- meta.json is written atomically.
# ===========================================================================


def test_b06_meta_is_never_created_by_a_partial_write(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    workspace_root = tmp_path / "ws"
    artifacts_dir = run_dir / "artifacts"

    with _replace_raises("boom"):
        with pytest.raises(OSError) as excinfo:
            _write_meta(run_dir, workspace_root, artifacts_dir)

    assert "boom" in str(excinfo.value), f"got {excinfo.value!r}"
    assert not (run_dir / _META_NAME).exists(), (
        f"a failed swap must never create the target; dir holds {_names(run_dir)}"
    )
    assert _tmp_residue(run_dir) == [], f"leaked temp file: {_names(run_dir)}"


# ===========================================================================
# Behavior 7 --- meta.json success contract is byte-for-byte unchanged.
# ===========================================================================


def test_b07_meta_success_bytes_and_schema_are_unchanged(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    workspace_root = tmp_path / "ws"
    artifacts_dir = run_dir / "artifacts"
    expected = _meta_mapping(workspace_root, artifacts_dir)

    _write_meta(run_dir, workspace_root, artifacts_dir)

    meta = run_dir / _META_NAME
    text = meta.read_text(encoding="utf-8")
    assert json.loads(text) == expected, f"got {text!r}"
    assert set(json.loads(text)) == {"workspace_root", "artifacts_dir"}, (
        f"exactly two keys, no others; got {sorted(json.loads(text))}"
    )
    assert text == json.dumps(expected, indent=2), (
        f"indent-2 rendering must be unchanged; got {text!r}"
    )
    assert _tmp_residue(run_dir) == [], f"leaked temp file: {_names(run_dir)}"
    assert _read_meta(run_dir) == expected, f"got {_read_meta(run_dir)!r}"


# ===========================================================================
# Behavior 8 --- A failed rewrite preserves the previous, complete meta.json.
# ===========================================================================


def test_b08_failed_rewrite_preserves_the_previous_meta(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    ws_a, art_a = tmp_path / "ws_a", run_dir / "artifacts_a"
    ws_b, art_b = tmp_path / "ws_b", run_dir / "artifacts_b"
    _write_meta(run_dir, ws_a, art_a)
    prior = (run_dir / _META_NAME).read_bytes()

    with _replace_raises("boom"):
        with pytest.raises(OSError):
            _write_meta(run_dir, ws_b, art_b)

    assert (run_dir / _META_NAME).read_bytes() == prior, (
        "the previous complete meta.json must survive a failed rewrite"
    )
    assert _read_meta(run_dir) == _meta_mapping(ws_a, art_a), f"got {_read_meta(run_dir)!r}"
    assert _tmp_residue(run_dir) == [], f"leaked temp file: {_names(run_dir)}"


# ===========================================================================
# Behavior 9 --- Directory created on demand; temp is a SIBLING of the target.
# ===========================================================================


def test_b09a_both_writers_create_their_directory_on_demand(tmp_path):
    run_dir = tmp_path / "absent" / "run"
    assert not run_dir.exists(), "arrange: the run dir must be fully absent"

    _write_meta(run_dir, tmp_path / "ws", run_dir / "artifacts")

    assert (run_dir / _META_NAME).is_file(), "_write_meta must create its dir on demand"

    cp_path = tmp_path / "absent2" / "run" / _CHECKPOINT_NAME
    assert not cp_path.parent.exists(), "arrange: the checkpoint parent must be absent"

    Checkpoint(cp_path).save(_state("On-demand parent goal"))

    assert cp_path.is_file(), "Checkpoint.save must create its parent on demand"
    assert _tmp_residue(cp_path.parent) == [], f"dir holds {_names(cp_path.parent)}"


def test_b09b_each_writer_swaps_exactly_once_within_one_directory(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    with _replace_recorder() as seen:
        Checkpoint(run_dir / _CHECKPOINT_NAME).save(_state("Sibling swap goal"))
    assert len(seen) == 1, f"Checkpoint.save must call os.replace exactly once; got {seen}"
    src, dst = seen[0]
    assert src.parent == dst.parent, (
        f"the temp must be a SIBLING of the target (one filesystem); got {src} -> {dst}"
    )
    assert dst.name == _CHECKPOINT_NAME, f"got {dst.name!r}"

    with _replace_recorder() as seen_meta:
        _write_meta(run_dir, tmp_path / "ws", run_dir / "artifacts")
    assert len(seen_meta) == 1, f"_write_meta must call os.replace exactly once; got {seen_meta}"
    msrc, mdst = seen_meta[0]
    assert msrc.parent == mdst.parent, (
        f"the temp must be a SIBLING of the target; got {msrc} -> {mdst}"
    )
    assert mdst.name == _META_NAME, f"got {mdst.name!r}"


# ===========================================================================
# Behavior 10 --- Tolerant degrade paths unchanged (no collateral damage).
# ===========================================================================


def test_b10a_read_meta_on_a_dir_with_no_meta_returns_empty(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    assert _read_meta(run_dir) == {}, f"got {_read_meta(run_dir)!r}"


def test_b10b_runs_json_tolerates_a_truncated_meta(tmp_path, capsys):
    state_dir = tmp_path / "state"
    run_dir = state_dir / "run-0001"
    run_dir.mkdir(parents=True)
    Checkpoint(run_dir / _CHECKPOINT_NAME).save(_state("Truncated meta goal"))
    (run_dir / _META_NAME).write_text('{"workspace_root": "/tmp/w', encoding="utf-8")

    rc, out, err = _run(["runs", "--state-dir", str(state_dir), "--json"], capsys)

    assert rc == 0, f"a truncated meta.json must not fail `runs --json`; stderr:\n{err}"
    rows = json.loads(out)
    assert isinstance(rows, list) and len(rows) == 1, f"got {out!r}"
    row = rows[0]
    assert row["run_id"] == "run-0001", f"got {row!r}"
    assert not row.get("workspace"), (
        f"a truncated meta must degrade to an empty workspace; row={row!r}"
    )


def test_b10c_slate_writer_still_leaves_no_temp_on_a_failed_swap(tmp_path):
    dest = tmp_path / "dest"
    dest.mkdir()
    out = dest / "slate.json"

    with _replace_raises("boom"):
        with pytest.raises(OSError):
            _write_slate(_slate(tmp_path), out)

    assert _tmp_residue(dest) == [], (
        f"the iter-122 slate guarantee must still hold; dir holds {_names(dest)}"
    )


# ===========================================================================
# Behavior 11 --- End-to-end offline run leaves no litter.
# ===========================================================================


def test_b11_end_to_end_demo_run_leaves_no_tmp_litter(tmp_path, capsys):
    state_dir = tmp_path / "pla_runs"

    rc, out, err = _run(
        [
            "run",
            "--workspace", str(FIXTURE),
            "--provider", "scripted",
            "--scripted-responses", str(SCRIPT),
            "--state-dir", str(state_dir),
        ],
        capsys,
    )

    assert rc == 0, f"the offline demo run must exit 0, got {rc}; stderr:\n{err}"
    litter = [str(p) for p in state_dir.rglob("*") if p.name.endswith(_TMP_SUFFIX)]
    assert litter == [], f"a clean run must leave no .tmp litter; found {litter}"

    metas = sorted(state_dir.rglob(_META_NAME))
    checkpoints = sorted(state_dir.rglob(_CHECKPOINT_NAME))
    assert len(metas) == 1, f"exactly one meta.json expected; got {metas}"
    assert len(checkpoints) == 1, f"exactly one checkpoint.json expected; got {checkpoints}"
    for path in (*metas, *checkpoints):
        parsed = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(parsed, dict) and parsed, f"{path.name} must parse as a JSON object"
