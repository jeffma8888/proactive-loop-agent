"""Black-box behavior tests for iteration 46 --- sanitizing the leaked pydantic
``ValidationError`` on corrupt SLATE and CHECKPOINT loads into ONE clean,
dependency-opaque ``error:`` line.

Feature under test (``pm.md`` iter-46, ``SPEC.md`` section 3 "Foundation
contracts"): a schema-invalid OR malformed-JSON slate/checkpoint used to print
the vendor's raw multi-line pydantic dump on stderr (the model class name, the
``[type=...]`` error taxonomy, the version-pinned ``errors.pydantic.dev`` URL,
and a raw ``input_value=`` echo of the user's file bytes). This iteration maps
that ``ValidationError`` at BOTH load seams -- the shared slate helper in
``cli.py`` (covering ``explain`` / ``dispatch`` / ``diff`` old+new) and
``Checkpoint.load()`` (covering ``resume`` / ``trace`` / ``runs``) -- to a
single clean line:

  * slate:      ``error: invalid slate file '<path>': <N> validation error[s][; first at <loc>]``
  * checkpoint: ``error: invalid checkpoint file '<path>': <N> validation error[s][; first at <loc>]``

where ``<path>`` is the path as passed to the CLI (unresolved ``str(Path(arg))``),
``<N>`` is the pydantic error count (``s`` pluralizes), and ``; first at <loc>``
is appended ONLY when the first error's ``loc`` tuple is non-empty (dropped for
the malformed-JSON ``json_invalid`` case, whose ``loc`` is empty). The message
must contain NONE of: ``errors.pydantic.dev``, ``[type=``, ``input_value=``,
``GoalSlate``, ``RunState``. Exit code (1) and the ``error:`` prefix are
UNCHANGED -- this is a message-body-only bug fix; valid loads are byte-stable.

ISOLATION CONTRACT (honored): these tests are written strictly against this
iteration's PUBLIC contract --- the spec's Expected Behaviors (``pm.md``),
``README.md``, and ``SPEC.md`` section 3 --- and drive ONLY documented public
surfaces: the ``pla`` CLI via ``proactive_loop.cli.main(argv) -> int`` (its
observable stdout / stderr / exit code / on-disk artifacts) and the public
``proactive_loop.models.GoalSlate`` for reading a valid slate's goal id.
**No file under ``src/`` was read, no engineer or reviewer notes were read, and
no ``git diff`` was consulted.** The exact message shape, exit codes, and
empty-stdout side-effect below were first calibrated by RUNNING the ``pla`` CLI
(explicitly permitted by the isolation contract), not by reading the source.
Every test is fully offline: zero network, zero API keys, driven through the
scripted-provider seam against the bundled ``examples/fixture_workspace`` +
``examples/scripted_responses.json``, with all writable targets under
``tmp_path``.

AMBIGUITY / PM-FEEDBACK NOTE (behaviors 5 & 9): the spec asks for happy-path
output "byte-identical to the pre-change behavior". Byte-identity to a
*pre-change* binary is not observable from an isolated black-box vantage (no old
binary to diff against), so ``test_b05_*`` / ``test_b09_*`` assert the strongest
observable equivalent: the valid load still exits 0, renders its normal
non-empty output (score math + gate decision for ``explain``; the run
transcript for ``trace``) with a clean (error-free) stderr, and no forbidden
vendor token intrudes.
"""

from __future__ import annotations

import json
from pathlib import Path

from proactive_loop.cli import main
from proactive_loop.models import GoalSlate

# The bundled offline fixtures the demo + integration tests use.
REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "examples" / "fixture_workspace"
SCRIPT = REPO / "examples" / "scripted_responses.json"

# The vendor-leak tokens that MUST NOT survive the sanitizer (the whole point
# of the fix on a PUBLIC portfolio repo).
_FORBIDDEN = ("errors.pydantic.dev", "[type=", "input_value=", "GoalSlate", "RunState")


# ---------------------------------------------------------------------------
# Helpers --- all black-box: build argv, drive main(), read back exit code /
# stdout / stderr / on-disk artifacts.
# ---------------------------------------------------------------------------


def _run(argv: list[str], capsys) -> tuple[int, str, str]:
    try:
        rc = main(argv)
    except SystemExit as exc:  # defensive: main() returns an int, but tolerate exit()
        rc = exc.code if isinstance(exc.code, int) else 1
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def _produce_valid_slate(dest: Path, capsys) -> Path:
    """Produce a real, valid slate file offline via ``scan --out``."""
    rc, _out, err = _run(
        [
            "scan",
            "--workspace", str(FIXTURE),
            "--provider", "scripted",
            "--scripted-responses", str(SCRIPT),
            "--out", str(dest),
        ],
        capsys,
    )
    assert rc == 0, f"valid slate production must succeed; rc={rc}, err={err!r}"
    assert dest.is_file(), f"slate must be written to {dest}"
    return dest


def _first_goal_id(slate_path: Path) -> str:
    """Read a real goal id from a valid slate via the public model (allowed)."""
    return GoalSlate.model_validate_json(slate_path.read_text()).goals[0].id


def _make_type_invalid_slate(good: Path, dest: Path) -> Path:
    """Valid JSON, but wrong-typed fields -> a multi-error pydantic dump.

    Mirrors the spec's live repro: a non-numeric ``impact`` plus an invalid
    ``category`` enum on the first goal.
    """
    data = json.loads(good.read_text())
    data["goals"][0]["impact"] = "NOTANUMBER"
    data["goals"][0]["category"] = "code_quality"  # not a valid GoalCategory member
    dest.write_text(json.dumps(data), encoding="utf-8")
    return dest


def _make_malformed_slate(dest: Path) -> Path:
    """Not valid JSON at all -> a single ``json_invalid`` error (empty loc)."""
    dest.write_text("{ this is not json ", encoding="utf-8")
    return dest


def _make_corrupt_checkpoint_run(state_dir: Path, run_name: str = "run-corrupt") -> Path:
    """A run dir whose ``checkpoint.json`` is valid JSON but shape-invalid.

    ``{"status": "NOT_A_STATUS"}`` fails RunState validation (bad status enum +
    missing required fields), reproducing the spec's schema-invalid checkpoint.
    """
    run_dir = state_dir / run_name
    (run_dir / "artifacts").mkdir(parents=True)
    (run_dir / "checkpoint.json").write_text('{"status": "NOT_A_STATUS"}', encoding="utf-8")
    (run_dir / "meta.json").write_text(
        json.dumps({"workspace_root": str(FIXTURE), "artifacts_dir": str(run_dir / "artifacts")}),
        encoding="utf-8",
    )
    return run_dir


def _produce_valid_run(state_dir: Path, capsys) -> Path:
    """Produce a genuine, DONE run dir (with a valid checkpoint) via ``pla run``."""
    rc, _out, err = _run(
        [
            "run",
            "--workspace", str(FIXTURE),
            "--provider", "scripted",
            "--scripted-responses", str(SCRIPT),
            "--state-dir", str(state_dir),
        ],
        capsys,
    )
    assert rc == 0, f"a valid run must succeed; rc={rc}, err={err!r}"
    run_dirs = sorted(state_dir.glob("run-*"))
    assert len(run_dirs) == 1, f"run must create exactly one run dir; got {run_dirs}"
    return run_dirs[0]


def _assert_clean_load_error(
    rc: int, out: str, err: str, *, kind_phrase: str, path: Path
) -> None:
    """The cross-cutting corrupt-load invariant (behaviors 1-4, 6, 7):

    exit 1, EMPTY stdout, stderr is EXACTLY one line that starts with ``error: ``
    and contains ``<kind_phrase>`` + the file path + ``validation error``, and
    contains NONE of the leaky pydantic vendor tokens (no multi-line dump).
    """
    assert rc == 1, f"corrupt load must exit 1; got {rc}; stderr={err!r}"
    assert out == "", f"stdout must be empty (0 bytes) on a corrupt load; got:\n{out!r}"
    lines = err.splitlines()
    assert len(lines) == 1, f"stderr must be exactly ONE line (no pydantic dump); got:\n{err!r}"
    line = lines[0]
    assert line.startswith("error: "), f"line must keep the 'error: ' prefix; got:\n{line!r}"
    assert kind_phrase in line, f"line must contain {kind_phrase!r}; got:\n{line!r}"
    assert str(path) in line, f"line must name the file path {str(path)!r}; got:\n{line!r}"
    assert "validation error" in line, f"line must state the validation-error count; got:\n{line!r}"
    for token in _FORBIDDEN:
        assert token not in err, f"leaked forbidden vendor token {token!r} in:\n{err!r}"
    assert "Traceback" not in err, f"no traceback allowed; got:\n{err!r}"


# ===========================================================================
# Behavior 1 --- type-invalid slate via `explain` -> clean line.
# ===========================================================================


def test_b01_explain_type_invalid_slate_clean_line(tmp_path, capsys):
    good = _produce_valid_slate(tmp_path / "good.json", capsys)
    bad = _make_type_invalid_slate(good, tmp_path / "typebad.json")

    rc, out, err = _run(
        ["explain", "--slate", str(bad), "--goal-id", "g1",
         "--provider", "scripted", "--scripted-responses", str(SCRIPT)],
        capsys,
    )

    _assert_clean_load_error(rc, out, err, kind_phrase="invalid slate file", path=bad)


# ===========================================================================
# Behavior 2 --- malformed (non-JSON) slate via `explain` -> clean line.
# Proves the raw-file-byte echo on `json_invalid` is also sanitized, and the
# empty-loc case omits the "; first at ..." clause.
# ===========================================================================


def test_b02_explain_malformed_slate_clean_line(tmp_path, capsys):
    bad = _make_malformed_slate(tmp_path / "malformed.json")

    rc, out, err = _run(
        ["explain", "--slate", str(bad), "--goal-id", "g1",
         "--provider", "scripted", "--scripted-responses", str(SCRIPT)],
        capsys,
    )

    _assert_clean_load_error(rc, out, err, kind_phrase="invalid slate file", path=bad)
    # The malformed file's raw bytes must NOT be echoed back onto stderr.
    assert "this is not json" not in err, f"raw file bytes must not be echoed; got:\n{err!r}"
    # Empty loc -> the "; first at" clause is dropped.
    assert "; first at" not in err, f"empty-loc case must omit the '; first at' clause; got:\n{err!r}"


# ===========================================================================
# Behavior 3 --- corrupt slate via `diff` names the CORRECT file (both sites).
# ===========================================================================


def test_b03a_diff_old_bad_names_old_file(tmp_path, capsys):
    good = _produce_valid_slate(tmp_path / "good.json", capsys)
    bad_old = _make_type_invalid_slate(good, tmp_path / "bad_old.json")

    rc, out, err = _run(
        ["diff", "--old", str(bad_old), "--new", str(good),
         "--provider", "scripted", "--scripted-responses", str(SCRIPT)],
        capsys,
    )

    _assert_clean_load_error(rc, out, err, kind_phrase="invalid slate file", path=bad_old)
    assert str(good) not in err, f"the error must attribute to the OLD (bad) file, not the good one; got:\n{err!r}"


def test_b03b_diff_new_bad_names_new_file(tmp_path, capsys):
    good = _produce_valid_slate(tmp_path / "good.json", capsys)
    bad_new = _make_type_invalid_slate(good, tmp_path / "bad_new.json")

    rc, out, err = _run(
        ["diff", "--old", str(good), "--new", str(bad_new),
         "--provider", "scripted", "--scripted-responses", str(SCRIPT)],
        capsys,
    )

    _assert_clean_load_error(rc, out, err, kind_phrase="invalid slate file", path=bad_new)
    assert str(good) not in err, f"the error must attribute to the NEW (bad) file, not the good one; got:\n{err!r}"


# ===========================================================================
# Behavior 4 --- corrupt slate via `dispatch` -> clean line (dispatch load site).
# ===========================================================================


def test_b04_dispatch_type_invalid_slate_clean_line(tmp_path, capsys):
    good = _produce_valid_slate(tmp_path / "good.json", capsys)
    bad = _make_type_invalid_slate(good, tmp_path / "typebad.json")

    rc, out, err = _run(
        ["dispatch", "--slate", str(bad), "--goal-id", "g1",
         "--provider", "scripted", "--scripted-responses", str(SCRIPT),
         "--state-dir", str(tmp_path / "state")],
        capsys,
    )

    _assert_clean_load_error(rc, out, err, kind_phrase="invalid slate file", path=bad)
    # The load fails before any dispatch -> no run dir is created.
    assert not list((tmp_path / "state").glob("run-*")), "a corrupt slate must dispatch nothing"


# ===========================================================================
# Behavior 5 (legality) --- valid slate via `explain` still loads unchanged.
# ===========================================================================


def test_b05_explain_valid_slate_still_loads(tmp_path, capsys):
    good = _produce_valid_slate(tmp_path / "good.json", capsys)
    goal_id = _first_goal_id(good)

    rc, out, err = _run(
        ["explain", "--slate", str(good), "--goal-id", goal_id,
         "--provider", "scripted", "--scripted-responses", str(SCRIPT)],
        capsys,
    )

    assert rc == 0, f"a valid slate must load (exit 0); rc={rc}, err={err!r}"
    assert out.strip() != "", "the normal explain output must render to stdout"
    # The normal explain block shows the score math and the gate decision.
    assert "score" in out, f"explain must render the score math; got:\n{out!r}"
    assert "decision" in out, f"explain must render the gate decision; got:\n{out!r}"
    assert "error:" not in err, f"the happy path must emit no error line; got:\n{err!r}"
    for token in _FORBIDDEN[:3]:  # URL / taxonomy / input echo never belong in normal output
        assert token not in (out + err), f"no vendor token {token!r} on the happy path"


# ===========================================================================
# Behavior 6 --- schema-invalid checkpoint via `trace` -> clean line.
# ===========================================================================


def test_b06_trace_corrupt_checkpoint_clean_line(tmp_path, capsys):
    run_dir = _make_corrupt_checkpoint_run(tmp_path / "state")
    ckpt = run_dir / "checkpoint.json"

    rc, out, err = _run(["trace", "--run-dir", str(run_dir)], capsys)

    _assert_clean_load_error(rc, out, err, kind_phrase="invalid checkpoint file", path=ckpt)
    assert "RunState" not in err, f"the model class name must not leak; got:\n{err!r}"


# ===========================================================================
# Behavior 7 --- schema-invalid checkpoint via `resume` -> clean line.
# ===========================================================================


def test_b07_resume_corrupt_checkpoint_clean_line(tmp_path, capsys):
    run_dir = _make_corrupt_checkpoint_run(tmp_path / "state")
    ckpt = run_dir / "checkpoint.json"

    rc, out, err = _run(
        ["resume", "--run-dir", str(run_dir),
         "--provider", "scripted", "--scripted-responses", str(SCRIPT),
         "--state-dir", str(tmp_path / "state")],
        capsys,
    )

    _assert_clean_load_error(rc, out, err, kind_phrase="invalid checkpoint file", path=ckpt)


# ===========================================================================
# Behavior 8 --- `runs` degradation preserved (no crash, no leak).
# ===========================================================================


def test_b08_runs_degrades_corrupt_checkpoint_no_leak(tmp_path, capsys):
    state = tmp_path / "state"
    _make_corrupt_checkpoint_run(state, run_name="run-corrupt")

    rc, out, err = _run(["runs", "--state-dir", str(state)], capsys)

    assert rc == 0, f"`runs` must tolerate a corrupt checkpoint (exit 0); rc={rc}, err={err!r}"
    # The corrupt run is still LISTED, degraded to the existing marker.
    assert "run-corrupt" in out, f"the corrupt run must still be listed; got:\n{out!r}"
    assert "(no checkpoint)" in out, f"the corrupt run must degrade to the '(no checkpoint)' marker; got:\n{out!r}"
    # No error line, and no vendor leak, anywhere.
    assert "error:" not in err, f"`runs` must emit no error line for the corrupt run; got:\n{err!r}"
    combined = out + err
    for token in _FORBIDDEN:
        assert token not in combined, f"leaked forbidden vendor token {token!r} in:\n{combined!r}"


# ===========================================================================
# Behavior 9 (legality) --- valid checkpoint via `trace` still loads unchanged.
# ===========================================================================


def test_b09_trace_valid_checkpoint_still_loads(tmp_path, capsys):
    run_dir = _produce_valid_run(tmp_path / "state", capsys)

    rc, out, err = _run(["trace", "--run-dir", str(run_dir)], capsys)

    assert rc == 0, f"a valid checkpoint must trace (exit 0); rc={rc}, err={err!r}"
    assert out.strip() != "", "the normal transcript must render to stdout"
    assert "run dir" in out, f"trace must render the run-dir header; got:\n{out!r}"
    assert "status" in out, f"trace must render the run status; got:\n{out!r}"
    assert "error:" not in err, f"the happy path must emit no error line; got:\n{err!r}"
    for token in _FORBIDDEN[:3]:
        assert token not in (out + err), f"no vendor token {token!r} on the happy path"
