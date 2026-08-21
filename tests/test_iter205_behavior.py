"""Black-box behavior tests for state-dir iteration 228 (ships as ``factory iter 202``).

Feature under test: ``proactive_loop.cli._read_meta`` maps a malformed
``meta.json`` to ONE named ``ValueError``, so ``pla resume``'s exit-1 line
identifies the file it could not parse instead of echoing a bare JSON offset --
while ``pla runs`` keeps tolerating that same file exactly as it does today.

THE DEFECT THIS PINS.  One corrupt file was tolerated by one verb and
anonymously fatal to another: ``runs`` degrades a bad run's metadata and still
prints that run's row, while ``resume`` died on ``error: Expecting value: line 1
column 1 (char 0)`` -- a message naming neither the file, the run dir nor the
failing step, on the one verb whose whole job is recovering a run that already
failed once.  Four unrelated faults (a corrupt ``meta.json``, a corrupt
``checkpoint.json``, a bad ``--scripted-responses`` script, a model-boundary
failure) all exit 1 through the same boundary, so an unnamed one is
indistinguishable from the other three.

MODULE NAME -- DERIVED FROM THE REPO, NEVER FROM A COUNTER.  Three counters
disagree this iteration: the state dir is ``iter-228``, the newest commit is
``747c860 (factory iter 201)``, and the highest tracked
``tests/test_iterNN_behavior.py`` is 204.  So the name is 204 + 1 = 205, proved
free two-sided before a byte was written: ``git cat-file -e
HEAD:tests/test_iter204_behavior.py`` SUCCEEDS while ``git cat-file -e
HEAD:tests/test_iter205_behavior.py`` exits 128, and no ``tests/test_iter205*``
existed in the working tree.  A name taken from 228 would have SILENTLY
OVERWRITTEN a shipped oracle (the iter-172 / iter-186 destroyed-oracle
failures); the state-dir-to-repo offset here is -26.

ISOLATION CONTRACT (honored): every assertion is written against this
iteration's spec ("Expected Behaviors" in ``pm.md``), the published
``README.md``, the repo's own ``tests/`` conventions, and the product's
OBSERVABLE output obtained by RUNNING it.  **No file under ``src/`` was read, no
engineer's or reviewer's note was consulted, and no ``git diff`` was
inspected.**

WHY FOUR REAL SUBPROCESSES, AND ONLY FOUR.  Behaviors 1-3 are claims about the
SEPARATION of two streams (exactly one ``error: `` line on stderr, an
exactly-empty stdout, no traceback anywhere), and an in-process ``capsys``
capture cannot falsify them honestly -- so they spend ONE real ``pla``
console-script invocation, shared by every assertion about it through a
module-scoped fixture (the iter-114 / iter-152 / iter-163 / iter-173
convention).  Behavior 4 spends one ``pla runs``, behavior 8 one ``pla
resume``, and one seed ``pla run`` builds the resumable run dir the other three
copy from.  Behaviors 5-7 call ``_read_meta`` directly and cost no process at
all (``tests/test_iter134_behavior.py`` imports that same private helper; the
in-tree precedent for an authorized private import is
``tests/test_iter122_behavior.py``'s ``_write_slate``).

TWO-SIDED BY CONSTRUCTION -- three controls keep this module from passing
vacuously.  (a) Behavior 8 is the control for behaviors 1-3: the SAME seed run
dir, copied the SAME way, differing ONLY in that ``meta.json`` is absent rather
than corrupt, exits **0** -- so the exit 1 is attributable to the corruption and
not to a copied run dir being unresumable.  (b) ``json.loads`` is fired at the
planted bytes, so a fixture that was accidentally VALID could never report
green.  (c) Behavior 4 asserts the listing's tolerance alongside a direct
``_read_meta`` call on the very file that listing tolerated, which proves the
listing survived a file that is genuinely fatal to read rather than one that
happens to parse.

Offline and deterministic: the bundled scripted provider only -- no network, no
API key, no clock.  Every invocation is rooted at a PRIVATE copy of
``examples/fixture_workspace`` under a ``tmp_path_factory`` dir and writes its
state there, so nothing is written inside the product repo and no run is rooted
at the in-repo fixture (the iter-142 shared-mutable-tree hazard).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from proactive_loop.cli import _read_meta

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "examples" / "fixture_workspace"
SCRIPT = REPO / "examples" / "scripted_responses.json"

_META_NAME = "meta.json"
_CHECKPOINT_NAME = "checkpoint.json"

#: The planted malformed payload.  Spelled here once so every behavior plants
#: the identical bytes, and asserted unparseable by ``json.loads`` below rather
#: than assumed to be bad.
_CORRUPT_BYTES = "not json at all"

#: Spec behavior 1 -- the message this iteration introduces.  Kept as the exact
#: prefix, not a loose substring, because the whole point is that the file is
#: named BEFORE the decoder's own text.
_NAMED_PREFIX = "invalid run metadata file '"

#: Spec behavior 2 -- the underlying decoder reason that must survive naming.
_DECODER_REASON = "Expecting value"

_ERROR_PREFIX = "error: "
_TRACEBACK_MARKER = "Traceback (most recent call last)"


# ---------------------------------------------------------------------------
# Helpers (iter-114 / iter-152 / iter-163 / iter-173 console-script convention)
# ---------------------------------------------------------------------------


def _console_script() -> Path:
    """The installed ``pla`` console script."""
    bindir = Path(sys.executable).parent
    candidates = [bindir / "pla", bindir / "pla.exe"]
    which = shutil.which("pla")
    if which:
        candidates.append(Path(which))
    script = next((c for c in candidates if c.is_file()), None)
    assert script is not None, (
        "the `pla` console script must be installed (declared in pyproject and "
        f"installed by `uv sync`); searched {[str(c) for c in candidates]}"
    )
    return script


def _run(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Invoke the real CLI in its own process so stdout/stderr are real fds."""
    return subprocess.run(
        [str(_console_script()), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=120,
    )


def _offline(state_dir: Path) -> list[str]:
    """The flags that pin every invocation to the bundled offline provider."""
    return [
        "--provider",
        "scripted",
        "--scripted-responses",
        str(SCRIPT),
        "--state-dir",
        str(state_dir),
    ]


def _isolated_workspace(root: Path) -> Path:
    """A private copy of the offline fixture workspace under ``root``.

    Never run the product against the in-repo fixture: it carries no ``.git`` of
    its own, so git-family collectors resolve upward into this repo and a
    sibling xdist worker can flip what they report mid-test.
    """
    dest = root / "workspace"
    shutil.copytree(FIXTURE, dest)
    return dest


def _error_lines(stderr: str) -> list[str]:
    """Every non-blank stderr line that opens with the product's error prefix."""
    return [
        line for line in stderr.splitlines() if line.strip().startswith(_ERROR_PREFIX)
    ]


def _plant_corrupt_meta(run_dir: Path) -> Path:
    """Overwrite ``run_dir/meta.json`` with unparseable bytes; return its path."""
    meta = run_dir / _META_NAME
    meta.write_text(_CORRUPT_BYTES, encoding="utf-8")
    return meta


def _copy_run_dir(seed: Path, dest_root: Path, name: str) -> Path:
    """A private copy of the seed run dir.

    ``resume`` MUTATES the checkpoint it resumes, so no two behaviors may share
    one run dir or they would be order-dependent under ``-n auto``.
    """
    dest = dest_root / name
    shutil.copytree(seed, dest)
    return dest


# ---------------------------------------------------------------------------
# Fixtures -- one seed run, then one process per stream-level behavior
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def seed_run_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A real, resumable run dir, obtained by RUNNING the product once.

    The path is read out of the ``run --json`` document that created it, never
    composed from a goal id: goal ids are not stable across two scans of one
    workspace, so a hand-built ``run-<id>`` path is a broken test.
    """
    root = tmp_path_factory.mktemp("seed")
    workspace = _isolated_workspace(root)
    state_dir = root / "state"
    proc = _run(
        "run",
        "--workspace",
        str(workspace),
        *_offline(state_dir),
        "--json",
        cwd=root,
    )
    assert proc.returncode == 0, f"seed run failed rc={proc.returncode}: {proc.stderr}"
    document = json.loads(proc.stdout)
    dispatched = document.get("dispatched")
    assert dispatched, f"the seed run dispatched nothing: {document}"
    run_dir = Path(dispatched["run_dir"])
    # A seed whose checkpoint or metadata is missing would make every behavior
    # below vacuous, so both halves are asserted rather than assumed.
    assert (run_dir / _CHECKPOINT_NAME).is_file(), f"no checkpoint in {run_dir}"
    assert (run_dir / _META_NAME).is_file(), f"no metadata in {run_dir}"
    return run_dir


@pytest.fixture(scope="module")
def corrupt_resume(
    seed_run_dir: Path, tmp_path_factory: pytest.TempPathFactory
) -> tuple[subprocess.CompletedProcess[str], Path]:
    """ONE ``resume`` over a run dir whose ``meta.json`` is unparseable.

    Behaviors 1, 2 and 3 are three claims about this single invocation, so they
    share it instead of paying for three processes.
    """
    root = tmp_path_factory.mktemp("corrupt")
    run_dir = _copy_run_dir(seed_run_dir, root, "run-corrupt-meta")
    meta = _plant_corrupt_meta(run_dir)
    assert (run_dir / _CHECKPOINT_NAME).is_file(), "the checkpoint must stay intact"
    proc = _run(
        "resume",
        "--run-dir",
        str(run_dir),
        *_offline(root / "state"),
        cwd=root,
    )
    return proc, meta


@pytest.fixture(scope="module")
def missing_meta_resume(
    seed_run_dir: Path, tmp_path_factory: pytest.TempPathFactory
) -> subprocess.CompletedProcess[str]:
    """The CONTROL for behaviors 1-3: same seed, same copy, no ``meta.json``.

    ``cwd`` is a private workspace copy because a metadata-less resume falls
    back to ``.`` for its workspace root -- pointing that at the product repo
    would run the loop over the tree the suite is grading.
    """
    root = tmp_path_factory.mktemp("nometa")
    workspace = _isolated_workspace(root)
    run_dir = _copy_run_dir(seed_run_dir, root, "run-no-meta")
    (run_dir / _META_NAME).unlink()
    return _run(
        "resume",
        "--run-dir",
        str(run_dir),
        *_offline(root / "state"),
        cwd=workspace,
    )


# ===========================================================================
# Behavior 0 (vacuity guard) -- the planted payload really is unparseable
# ===========================================================================


def test_b00_the_planted_payload_is_genuinely_unparseable() -> None:
    """A fixture that accidentally PARSED would make every claim below green."""
    with pytest.raises(ValueError):
        json.loads(_CORRUPT_BYTES)


# ===========================================================================
# Behavior 1 -- resume over a corrupt meta.json exits 1 and NAMES the file
# ===========================================================================


def test_b01_resume_over_a_corrupt_meta_exits_one(
    corrupt_resume: tuple[subprocess.CompletedProcess[str], Path],
) -> None:
    proc, _meta = corrupt_resume
    assert proc.returncode == 1, (
        f"expected the operational-fault exit 1, got {proc.returncode}; "
        f"stderr={proc.stderr!r}"
    )


def test_b01_stderr_carries_exactly_one_error_line(
    corrupt_resume: tuple[subprocess.CompletedProcess[str], Path],
) -> None:
    proc, _meta = corrupt_resume
    lines = _error_lines(proc.stderr)
    assert len(lines) == 1, f"expected one `error: ` line, got {lines!r}"


def test_b01_that_line_names_the_metadata_file_before_the_reason(
    corrupt_resume: tuple[subprocess.CompletedProcess[str], Path],
) -> None:
    proc, meta = corrupt_resume
    (line,) = _error_lines(proc.stderr)
    assert line.startswith(f"{_ERROR_PREFIX}{_NAMED_PREFIX}"), (
        f"the error line must open `{_ERROR_PREFIX}{_NAMED_PREFIX}`; got {line!r}"
    )
    assert str(meta) in line, f"{str(meta)!r} is not named in {line!r}"


# ===========================================================================
# Behavior 2 -- naming the file does not HIDE the decoder's reason
# ===========================================================================


def test_b02_the_named_line_still_carries_the_decoder_reason(
    corrupt_resume: tuple[subprocess.CompletedProcess[str], Path],
) -> None:
    proc, _meta = corrupt_resume
    (line,) = _error_lines(proc.stderr)
    assert _DECODER_REASON in line, (
        f"{_DECODER_REASON!r} must survive the rename, so the cause is still "
        f"readable; got {line!r}"
    )


# ===========================================================================
# Behavior 3 -- one clean error line: no traceback, empty stdout
# ===========================================================================


def test_b03_no_traceback_reaches_stderr(
    corrupt_resume: tuple[subprocess.CompletedProcess[str], Path],
) -> None:
    proc, _meta = corrupt_resume
    assert _TRACEBACK_MARKER not in proc.stderr, (
        f"a foreseeable input fault must never print a traceback; "
        f"stderr={proc.stderr!r}"
    )


def test_b03_stdout_is_exactly_empty(
    corrupt_resume: tuple[subprocess.CompletedProcess[str], Path],
) -> None:
    proc, _meta = corrupt_resume
    assert proc.stdout == "", f"stdout must stay empty on the refusal; got {proc.stdout!r}"


# ===========================================================================
# Behavior 4 -- the LISTING's tolerance of the same file is unchanged
# ===========================================================================


def test_b04_runs_still_exits_zero_over_a_corrupt_meta(
    seed_run_dir: Path, tmp_path: Path
) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    run_dir = _copy_run_dir(seed_run_dir, state_dir, "run-listed")
    _plant_corrupt_meta(run_dir)
    proc = _run("runs", "--state-dir", str(state_dir), cwd=tmp_path)
    assert proc.returncode == 0, (
        f"one unreadable metadata file must not abort the listing; "
        f"rc={proc.returncode} stderr={proc.stderr!r}"
    )


def test_b04_the_listing_still_prints_that_runs_row(
    seed_run_dir: Path, tmp_path: Path
) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    run_dir = _copy_run_dir(seed_run_dir, state_dir, "run-listed-row")
    _plant_corrupt_meta(run_dir)
    proc = _run("runs", "--state-dir", str(state_dir), cwd=tmp_path)
    assert run_dir.name in proc.stdout, (
        f"the row for {run_dir.name!r} must survive its unreadable metadata; "
        f"stdout={proc.stdout!r}"
    )


def test_b04_control_the_tolerated_file_is_genuinely_fatal_to_read(
    seed_run_dir: Path, tmp_path: Path
) -> None:
    """Without this control, behavior 4 would also pass on a file that PARSES."""
    run_dir = _copy_run_dir(seed_run_dir, tmp_path, "run-control")
    _plant_corrupt_meta(run_dir)
    with pytest.raises(ValueError):
        _read_meta(run_dir)


# ===========================================================================
# Behavior 5 -- the helper itself raises ONE named ValueError
# ===========================================================================


def test_b05_read_meta_raises_value_error_naming_the_path(tmp_path: Path) -> None:
    meta = _plant_corrupt_meta(tmp_path)
    with pytest.raises(ValueError) as excinfo:
        _read_meta(tmp_path)
    message = str(excinfo.value)
    assert message.startswith(_NAMED_PREFIX), f"got {message!r}"
    assert str(meta) in message, f"{str(meta)!r} is not named in {message!r}"


def test_b05_the_decoder_reason_is_kept_in_the_helpers_message(tmp_path: Path) -> None:
    _plant_corrupt_meta(tmp_path)
    with pytest.raises(ValueError) as excinfo:
        _read_meta(tmp_path)
    assert _DECODER_REASON in str(excinfo.value), f"got {str(excinfo.value)!r}"


def test_b05_the_raw_decoder_error_does_not_leak(tmp_path: Path) -> None:
    """A bare ``json.JSONDecodeError`` is what the old message came from.

    ``JSONDecodeError`` IS a ``ValueError``, so ``pytest.raises(ValueError)``
    alone cannot tell the named error from the unnamed one it replaced.  This
    is the assertion that can.
    """
    _plant_corrupt_meta(tmp_path)
    with pytest.raises(ValueError) as excinfo:
        _read_meta(tmp_path)
    assert not isinstance(excinfo.value, json.JSONDecodeError), (
        f"the decoder's own exception escaped unnamed: {excinfo.value!r}"
    )


def test_b05_the_named_error_reports_no_chained_context(tmp_path: Path) -> None:
    """The one-line stderr of behavior 3 needs context SUPPRESSED, not absent.

    Measured trap: ``raise ... from None`` does NOT clear ``__context__`` -- it
    sets ``__suppress_context__``.  Asserting ``__context__ is None`` fails on
    correct code, so the pair below is what to assert.
    """
    _plant_corrupt_meta(tmp_path)
    with pytest.raises(ValueError) as excinfo:
        _read_meta(tmp_path)
    assert excinfo.value.__cause__ is None, f"got {excinfo.value.__cause__!r}"
    assert excinfo.value.__suppress_context__, (
        "context must be suppressed, or the printed failure grows a second frame"
    )


# ===========================================================================
# Behavior 6 -- an ABSENT meta.json still returns {} (unchanged)
# ===========================================================================


def test_b06_a_dir_with_no_meta_still_returns_empty(tmp_path: Path) -> None:
    assert not (tmp_path / _META_NAME).exists(), "fixture must start with no metadata"
    assert _read_meta(tmp_path) == {}, f"got {_read_meta(tmp_path)!r}"


# ===========================================================================
# Behavior 7 -- a VALID meta.json round-trips unchanged
# ===========================================================================


def test_b07_a_valid_meta_returns_exactly_what_json_loads_returns(
    tmp_path: Path,
) -> None:
    payload = {
        "workspace_root": str(tmp_path / "ws"),
        "artifacts_dir": str(tmp_path / "ws" / "artifacts"),
    }
    meta = tmp_path / _META_NAME
    meta.write_text(json.dumps(payload), encoding="utf-8")
    expected = json.loads(meta.read_text(encoding="utf-8"))
    assert _read_meta(tmp_path) == expected, f"got {_read_meta(tmp_path)!r}"


def test_b07_extra_keys_survive_because_this_is_about_parseability(
    tmp_path: Path,
) -> None:
    """The named error is a PARSE failure, not schema validation."""
    payload = {"workspace_root": str(tmp_path), "artifacts_dir": str(tmp_path), "x": 1}
    (tmp_path / _META_NAME).write_text(json.dumps(payload), encoding="utf-8")
    assert _read_meta(tmp_path) == payload, f"got {_read_meta(tmp_path)!r}"


# ===========================================================================
# Behavior 8 -- resume with NO meta.json is unchanged (and is the CONTROL)
# ===========================================================================


def test_b08_resume_without_a_meta_file_is_not_rejected(
    missing_meta_resume: subprocess.CompletedProcess[str],
) -> None:
    proc = missing_meta_resume
    assert proc.returncode == 0, (
        f"an absent meta.json must still resume; rc={proc.returncode} "
        f"stderr={proc.stderr!r}"
    )


def test_b08_the_new_error_path_stays_out_of_the_absent_case(
    missing_meta_resume: subprocess.CompletedProcess[str],
) -> None:
    proc = missing_meta_resume
    assert _NAMED_PREFIX not in proc.stderr, (
        f"a MISSING file is not a MALFORMED one; stderr={proc.stderr!r}"
    )


def test_b08_the_control_and_the_corrupt_run_differ_only_in_that_file(
    missing_meta_resume: subprocess.CompletedProcess[str],
    corrupt_resume: tuple[subprocess.CompletedProcess[str], Path],
) -> None:
    """The two exit codes are what make behaviors 1-3 non-vacuous.

    Same seed run dir, same copy mechanics, same flags: the ONLY difference is
    whether ``meta.json`` is corrupt or absent, and the exit codes differ.  So
    the exit 1 is attributable to the corruption rather than to the copy.
    """
    corrupt_proc, _meta = corrupt_resume
    assert (missing_meta_resume.returncode, corrupt_proc.returncode) == (0, 1), (
        f"control rc={missing_meta_resume.returncode}, "
        f"corrupt rc={corrupt_proc.returncode}"
    )
