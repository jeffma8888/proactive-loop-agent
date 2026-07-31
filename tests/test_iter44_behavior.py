"""Black-box behavior tests for iteration 44 --- pre-flight validation of the
OUTPUT-path CLI args, mirroring the existing ``--workspace`` INPUT guard.

Feature under test (SPEC section 4.5, ``pm.md`` iter-44): ``scan --out`` and the
``--state-dir`` of ``run`` / ``dispatch`` are now validated BEFORE any client
build / collect / synthesize / render / file write. A bad output target fails
fast with a single ``error: <msg>`` line on stderr and **exit 2** (was: run the
whole expensive pipeline, print a success-looking slate table, then leak a raw
OS errno at the late write and exit 1). Structural typing only:

  * ``--out`` that IS a directory                       -> ``error: --out is a directory: <path>``
  * ``--out`` whose parent chain contains a plain file  -> ``error: --out parent is not a directory: <deepest-existing-ancestor>``
  * ``--state-dir`` that exists but is not a directory  -> ``error: --state-dir is not a directory: <path>``

A fully-absent parent chain (parents made on demand) and an ``--out`` pointing
AT a plain file stay legal; the guards never pre-detect write permission. When
``--out`` is given, ``scan`` guards ONLY ``--out`` (the ``--out`` XOR
``--state-dir`` design) so a bad ``--state-dir`` is irrelevant. Additive; no
``__version__`` bump; happy paths unchanged.

ISOLATION CONTRACT (honored): these tests are written strictly against this
iteration's PUBLIC contract --- the spec's Expected Behaviors (``pm.md``),
``README.md``, and ``SPEC.md`` section 4.5 --- and drive ONLY documented public
surfaces: the ``pla`` CLI via ``proactive_loop.cli.main(argv) -> int`` (its
observable stdout / stderr / exit code / on-disk artifacts) and the public
``proactive_loop.models.GoalSlate`` for re-parsing written slates.
**No file under ``src/`` was read, no engineer or reviewer notes were read, and
no ``git diff`` was consulted.** The exact rejection messages, exit codes, and
side-effect absence below were first calibrated by RUNNING the ``pla`` CLI
(explicitly permitted by the isolation contract), not by reading the source.
Every test is fully offline: zero network, zero API keys, driven through the
scripted-provider seam against the bundled ``examples/fixture_workspace`` +
``examples/scripted_responses.json``, with all writable targets under
``tmp_path``.

AMBIGUITY / PM-FEEDBACK NOTE (behavior 12): the spec asks for stdout
"byte-identical to the pre-change behavior". Byte-identity to a *pre-change*
binary is not observable from an isolated black-box vantage (there is no old
binary to diff against), so ``test_b12_*`` asserts the observable equivalent:
the bare happy path still exits 0 and renders a normal, non-empty ranked table
with the ``slate written:`` trailer, and the guard does not intrude. This is
the strongest black-box statement of "happy path unchanged".
"""

from __future__ import annotations

from pathlib import Path

import pytest

from proactive_loop.cli import main
from proactive_loop.models import GoalSlate

# The bundled offline fixtures the demo + integration tests use.
REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "examples" / "fixture_workspace"
SCRIPT = REPO / "examples" / "scripted_responses.json"

# The bundled fixture's scripted synthesize response yields exactly four goals.
_EXPECTED_GOALS = 4


# ---------------------------------------------------------------------------
# Helpers --- all black-box: build argv, drive main(), read back exit code /
# stdout / stderr / on-disk artifacts. The output guards RETURN 2 (they do not
# raise), exactly like the --workspace guard; _run tolerates a SystemExit too
# so the tests stay correct regardless of the return-vs-raise mechanism.
# ---------------------------------------------------------------------------


def _run(argv: list[str], capsys) -> tuple[int, str, str]:
    try:
        rc = main(argv)
    except SystemExit as exc:  # defensive: guards return 2, but tolerate exit()
        rc = exc.code if isinstance(exc.code, int) else 1
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def _scan_argv(*, out: str | None = None, state_dir: str | None = None) -> list[str]:
    argv = [
        "scan",
        "--workspace", str(FIXTURE),
        "--provider", "scripted",
        "--scripted-responses", str(SCRIPT),
    ]
    if state_dir is not None:
        argv += ["--state-dir", state_dir]
    if out is not None:
        argv += ["--out", out]
    return argv


def _run_argv(*, state_dir: str | None = None) -> list[str]:
    argv = [
        "run",
        "--workspace", str(FIXTURE),
        "--provider", "scripted",
        "--scripted-responses", str(SCRIPT),
    ]
    if state_dir is not None:
        argv += ["--state-dir", state_dir]
    return argv


def _dispatch_argv(*, slate: str, goal_id: str, state_dir: str) -> list[str]:
    return [
        "dispatch",
        "--slate", slate,
        "--goal-id", goal_id,
        "--provider", "scripted",
        "--scripted-responses", str(SCRIPT),
        "--state-dir", state_dir,
    ]


def _produce_valid_slate(dest: Path, capsys) -> Path:
    """Produce a real, valid slate file offline via ``scan --out`` (which never
    touches --state-dir for the slate), so the dispatch tests dispatch from a
    genuine GoalSlate JSON."""
    rc, out, err = _run(_scan_argv(out=str(dest)), capsys)
    assert rc == 0, f"slate production must succeed; rc={rc}, err={err!r}"
    assert dest.is_file(), f"slate must be written to {dest}"
    return dest


def _assert_clean_rejection(rc: int, out: str, err: str, expected_msg: str) -> None:
    """The cross-cutting rejection invariant (holds for behaviors 1-7): exit 2,
    0-byte stdout, stderr is EXACTLY one line equal to ``error: <msg>``, no
    ``[Errno ...]`` substring, no traceback."""
    assert rc == 2, f"rejection must exit 2; got {rc}; stderr={err!r}"
    assert out == "", f"stdout must be empty (0 bytes) on rejection; got:\n{out!r}"
    assert err.splitlines() == [expected_msg], (
        f"stderr must be exactly one line equal to {expected_msg!r}; got:\n{err!r}"
    )
    combined = out + err
    assert "[Errno" not in combined, f"no leaked OS errno allowed; got:\n{combined!r}"
    assert "Traceback" not in combined, f"no traceback allowed; got:\n{combined!r}"


def _no_run_dirs(state_root: Path) -> bool:
    return not list(state_root.glob("run-*")) if state_root.is_dir() else True


# ===========================================================================
# Behavior 1 --- `scan --out <D>` where <D> is an existing directory ->
# `error: --out is a directory: <D>`; <D> still has no slate.json afterward.
# ===========================================================================


def test_b01_scan_out_is_existing_directory(tmp_path, capsys):
    d = tmp_path / "adir"
    d.mkdir()

    rc, out, err = _run(_scan_argv(out=str(d), state_dir=str(tmp_path / "st")), capsys)

    _assert_clean_rejection(rc, out, err, f"error: --out is a directory: {d}")
    # No filesystem side effect: <D> is untouched and gained no slate.json.
    assert not (d / "slate.json").exists(), "no slate may be written into the rejected dir"
    assert list(d.iterdir()) == [], "the existing directory must be left unchanged (empty)"
    assert not (tmp_path / "st").exists(), "the (unused) state dir must not be created"


# ===========================================================================
# Behavior 2 --- `scan --out <F>/slate.json` where <F> is an existing regular
# file -> `error: --out parent is not a directory: <F>`; <F> byte-unchanged.
# ===========================================================================


def test_b02_scan_out_parent_is_file(tmp_path, capsys):
    f = tmp_path / "afile"
    f.write_bytes(b"ORIGINAL-CONTENT")
    before = f.read_bytes()

    rc, out, err = _run(_scan_argv(out=str(f / "slate.json"), state_dir=str(tmp_path / "st")), capsys)

    _assert_clean_rejection(rc, out, err, f"error: --out parent is not a directory: {f}")
    assert f.read_bytes() == before, "the pre-existing file must be byte-for-byte unchanged"
    assert f.is_file(), "the file target must remain a plain file"


def test_b02b_scan_out_parent_is_file_deep_chain(tmp_path, capsys):
    """Extra non-existent components below the file -> SAME message naming the
    DEEPEST EXISTING ANCESTOR (<F>), not the missing intermediate."""
    f = tmp_path / "afile"
    f.write_bytes(b"ORIGINAL-CONTENT")
    before = f.read_bytes()

    rc, out, err = _run(
        _scan_argv(out=str(f / "deeper" / "slate.json"), state_dir=str(tmp_path / "st")),
        capsys,
    )

    _assert_clean_rejection(rc, out, err, f"error: --out parent is not a directory: {f}")
    assert f.read_bytes() == before, "the pre-existing file must be byte-for-byte unchanged"
    assert not (f / "deeper").exists(), "no path components may be created under the rejected file"


# ===========================================================================
# Behavior 3 --- `scan` with NO --out and `--state-dir <F>` (existing regular
# file); the default slate target is <state-dir>/slate.json ->
# `error: --state-dir is not a directory: <F>`; no slate written.
# ===========================================================================


def test_b03_scan_no_out_state_dir_is_file(tmp_path, capsys):
    f = tmp_path / "statefile"
    f.write_bytes(b"ORIGINAL-STATE")
    before = f.read_bytes()

    rc, out, err = _run(_scan_argv(state_dir=str(f)), capsys)

    _assert_clean_rejection(rc, out, err, f"error: --state-dir is not a directory: {f}")
    assert f.read_bytes() == before, "the pre-existing state file must be byte-for-byte unchanged"
    assert f.is_file(), "the state-dir target must remain a plain file (no dir replaced it)"


# ===========================================================================
# Behavior 4 --- `run --state-dir <F>` (existing regular file) ->
# `error: --state-dir is not a directory: <F>`; no run dir, no slate created.
# ===========================================================================


def test_b04_run_state_dir_is_file(tmp_path, capsys):
    f = tmp_path / "statefile"
    f.write_bytes(b"ORIGINAL-STATE")
    before = f.read_bytes()

    rc, out, err = _run(_run_argv(state_dir=str(f)), capsys)

    _assert_clean_rejection(rc, out, err, f"error: --state-dir is not a directory: {f}")
    assert f.read_bytes() == before, "the pre-existing state file must be byte-for-byte unchanged"
    # No run dir / slate anywhere under tmp_path (the file cannot contain them).
    assert not list(tmp_path.glob("run-*")), "no run directory may be created on rejection"
    assert not list(tmp_path.glob("**/slate.json")), "no slate may be written on rejection"


# ===========================================================================
# Behavior 5 --- `dispatch --slate <VALID> --goal-id <ABSENT> --state-dir <F>`
# (F an existing regular file) -> `error: --state-dir is not a directory: <F>`.
# The state-dir guard fires BEFORE the goal is looked up, so an ABSENT goal-id
# still loses to the state-dir error. No run dir created.
# ===========================================================================


def test_b05_dispatch_state_dir_file_wins_over_absent_goal(tmp_path, capsys):
    slate = _produce_valid_slate(tmp_path / "valid_slate.json", capsys)
    f = tmp_path / "statefile"
    f.write_bytes(b"ORIGINAL-STATE")
    before = f.read_bytes()

    rc, out, err = _run(
        _dispatch_argv(slate=str(slate), goal_id="absent-goal-xyz", state_dir=str(f)),
        capsys,
    )

    _assert_clean_rejection(rc, out, err, f"error: --state-dir is not a directory: {f}")
    assert f.read_bytes() == before, "the pre-existing state file must be byte-for-byte unchanged"
    assert not list(tmp_path.glob("run-*")), "no run directory may be created on rejection"


def test_b05b_dispatch_state_dir_file_wins_even_with_real_goal(tmp_path, capsys):
    """Reinforcement: the state-dir guard fires before the goal lookup / gate /
    client build, so even a REAL goal-id from the slate loses to the bad
    state-dir. (The spec's `<ANY>` covers a present goal too.)"""
    slate = _produce_valid_slate(tmp_path / "valid_slate.json", capsys)
    real_id = GoalSlate.model_validate_json(slate.read_text()).goals[0].id
    f = tmp_path / "statefile"
    f.write_bytes(b"ORIGINAL-STATE")

    rc, out, err = _run(
        _dispatch_argv(slate=str(slate), goal_id=real_id, state_dir=str(f)),
        capsys,
    )

    _assert_clean_rejection(rc, out, err, f"error: --state-dir is not a directory: {f}")
    assert not (tmp_path / f"run-{real_id}").exists(), "no run dir may be created on rejection"


# ===========================================================================
# Behavior 6 (regression guard) --- `dispatch --slate <VALID> --goal-id <BOGUS>
# --state-dir <GOOD>` (GOOD a valid dir) -> the pre-existing
# `error: goal id '<BOGUS>' not found in slate`, exit 2. A good state-dir must
# NOT mask the goal-not-found path.
# ===========================================================================


def test_b06_dispatch_good_state_dir_preserves_goal_not_found(tmp_path, capsys):
    slate = _produce_valid_slate(tmp_path / "valid_slate.json", capsys)
    good = tmp_path / "goodstate"  # absent-but-legal state dir
    bogus = "no-such-goal-42"

    rc, out, err = _run(
        _dispatch_argv(slate=str(slate), goal_id=bogus, state_dir=str(good)),
        capsys,
    )

    _assert_clean_rejection(rc, out, err, f"error: goal id '{bogus}' not found in slate")
    assert _no_run_dirs(good), "goal-not-found must create no run dir"


# ===========================================================================
# Behavior 7 (regression guard) --- `dispatch --slate <MISSING> --goal-id <ANY>
# --state-dir <F>` (MISSING a non-existent slate, F a bad file) -> the
# pre-existing `error: slate file not found: <MISSING>`, exit 2. The
# slate-not-found check runs FIRST, before the slate load / state-dir guard.
# ===========================================================================


def test_b07_dispatch_missing_slate_wins_over_bad_state_dir(tmp_path, capsys):
    missing = tmp_path / "does_not_exist.json"
    assert not missing.exists()
    f = tmp_path / "statefile"
    f.write_bytes(b"ORIGINAL-STATE")
    before = f.read_bytes()

    rc, out, err = _run(
        _dispatch_argv(slate=str(missing), goal_id="anything", state_dir=str(f)),
        capsys,
    )

    _assert_clean_rejection(rc, out, err, f"error: slate file not found: {missing}")
    assert not missing.exists(), "the missing slate must not be conjured into existence"
    assert f.read_bytes() == before, "the bad state file must be byte-for-byte unchanged"


# ===========================================================================
# Behavior 8 (legality) --- `scan --out <N>/a/b/slate.json` with a fully-absent
# parent chain -> exit 0; the slate IS created (parents made on demand); stdout
# is the normal ranked table + `slate written: <path>` trailer.
# ===========================================================================


def test_b08_scan_out_absent_parent_chain_is_legal(tmp_path, capsys):
    out_path = tmp_path / "newN" / "a" / "b" / "slate.json"
    assert not (tmp_path / "newN").exists()

    rc, out, err = _run(_scan_argv(out=str(out_path), state_dir=str(tmp_path / "st")), capsys)

    assert rc == 0, f"a fully-absent parent chain is legal; rc={rc}, err={err!r}"
    assert out_path.is_file(), "the slate must be created with parents made on demand"
    slate = GoalSlate.model_validate_json(out_path.read_text())
    assert len(slate.goals) == _EXPECTED_GOALS, "the persisted slate must hold the full slate"
    assert out.strip() != "", "the normal ranked table must render to stdout"
    assert f"slate written: {out_path}" in out, "the table trailer must name the written path"


# ===========================================================================
# Behavior 9 (legality) --- `scan --out <F>` where <F> is an existing plain file
# whose parent is a directory -> exit 0; <F> overwritten with valid slate JSON.
# ===========================================================================


def test_b09_scan_out_overwrites_existing_plain_file(tmp_path, capsys):
    f = tmp_path / "target.json"
    f.write_text("JUNK-BEFORE-OVERWRITE")

    rc, out, err = _run(_scan_argv(out=str(f), state_dir=str(tmp_path / "st")), capsys)

    assert rc == 0, f"pointing --out AT a plain file is legal; rc={rc}, err={err!r}"
    slate = GoalSlate.model_validate_json(f.read_text())  # re-parses as a GoalSlate
    assert len(slate.goals) == _EXPECTED_GOALS, "the file must be overwritten with the full slate"
    assert f"slate written: {f}" in out


# ===========================================================================
# Behavior 10 (legality) --- `run --state-dir <N>` where <N> does not exist ->
# exit 0; <N> is created as a directory; the run proceeds (stdout non-empty).
# ===========================================================================


def test_b10_run_absent_state_dir_is_created(tmp_path, capsys):
    n = tmp_path / "brand_new_state"
    assert not n.exists()

    rc, out, err = _run(_run_argv(state_dir=str(n)), capsys)

    assert rc == 0, f"an absent state-dir is legal (created on demand); rc={rc}, err={err!r}"
    assert n.is_dir(), "the absent state-dir must be created as a directory"
    assert out.strip() != "", "the run must render output to stdout"


# ===========================================================================
# Behavior 11 (legality) --- `run --state-dir <D>` where <D> is an existing
# directory -> exit 0; runs normally (stdout non-empty).
# ===========================================================================


def test_b11_run_existing_state_dir_is_legal(tmp_path, capsys):
    d = tmp_path / "existing_state"
    d.mkdir()

    rc, out, err = _run(_run_argv(state_dir=str(d)), capsys)

    assert rc == 0, f"an existing state directory is legal; rc={rc}, err={err!r}"
    assert d.is_dir()
    assert out.strip() != "", "the run must render output to stdout"


# ===========================================================================
# Behavior 12 (legality / happy-path unchanged) --- bare `scan` and bare `run`
# (no --out, DEFAULT --state-dir) -> exit 0; a normal, non-empty ranked table.
# Run under monkeypatch.chdir(tmp_path) so the default `.pla_runs` stays
# hermetic. (See module AMBIGUITY NOTE re: "byte-identical".)
# ===========================================================================


def test_b12_bare_scan_default_state_dir_happy_path(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)

    rc, out, err = _run(_scan_argv(), capsys)  # no --out, no --state-dir

    assert rc == 0, f"the bare happy path must stay exit 0; rc={rc}, err={err!r}"
    assert out.strip() != "", "the normal ranked table must render"
    assert "slate written:" in out, "the table trailer must appear on the happy path"
    # Default slate target is <state-dir>/slate.json = .pla_runs/slate.json (cwd).
    assert (tmp_path / ".pla_runs" / "slate.json").is_file(), (
        "the bare scan must persist the slate to the default state dir"
    )


def test_b12_bare_run_default_state_dir_happy_path(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)

    rc, out, err = _run(_run_argv(), capsys)  # no --state-dir

    assert rc == 0, f"the bare happy path must stay exit 0; rc={rc}, err={err!r}"
    assert out.strip() != "", "the run must render output to stdout"
    assert (tmp_path / ".pla_runs").is_dir(), "the default state dir must be created"


# ===========================================================================
# Behavior 13 (legality / --out XOR --state-dir) --- `scan --out <T>
# --state-dir <F>` where <T> is a legal writable slate target and <F> is an
# existing regular file -> exit 0; the slate is written to <T>; NO error. When
# --out is given, scan guards ONLY --out, so a bad --state-dir is irrelevant.
# ===========================================================================


def test_b13_scan_out_given_ignores_bad_state_dir(tmp_path, capsys):
    f = tmp_path / "badstatefile"
    f.write_bytes(b"ORIGINAL-STATE")
    before = f.read_bytes()
    t = tmp_path / "t13" / "slate.json"  # legal target, absent parent chain

    rc, out, err = _run(_scan_argv(out=str(t), state_dir=str(f)), capsys)

    assert rc == 0, f"a bad --state-dir is irrelevant when --out is given; rc={rc}, err={err!r}"
    assert err == "" or "error:" not in err, f"no error must be emitted; got:\n{err!r}"
    assert t.is_file(), "the slate must be written to the --out target"
    slate = GoalSlate.model_validate_json(t.read_text())
    assert len(slate.goals) == _EXPECTED_GOALS
    assert f"slate written: {t}" in out
    assert f.read_bytes() == before, "the (untouched) bad state file must be byte-for-byte unchanged"
