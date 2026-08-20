"""Iteration 192 (factory iter 194) -- black-box oracle for the ``watch --out-dir``
path guard, the only unguarded member of this repo's 3-guard CLI path-guard family.

WHAT THIS ITERATION CLAIMS (restated from the PM spec so this file stands alone)
``watch --out-dir P`` rejects a ``P`` that cannot become a directory BEFORE any scan
work runs, with a single-line ``error:`` message naming the offending path, and it does
NOT over-reject a legal fully-absent nested target. Two rejection wordings exist and
neither was named by any test: ``--out-dir is not a directory: <P>`` when ``P`` itself
is an existing non-directory, and ``--out-dir parent is not a directory: <A>`` when a
non-directory sits in ``P``'s parent chain -- where ``A`` is the DEEPEST EXISTING
ancestor, not ``P``'s literal parent. The sibling guards (``--out``, ``--snapshot``,
``--state-dir``) are pinned verbatim elsewhere; this module pins the third one, and it
pins it TWO-SIDED so a future widening that starts rejecting a legal path also reds.

HOW THIS FILE VERIFIES IT, INDEPENDENTLY
Every assertion drives the public CLI entry point (``proactive_loop.cli.main``) with an
argv list and reads back the exit code, the captured stdout/stderr, and on-disk files.
Nothing here imports the guard, the stream writer or the settings loader, and nothing
reads implementation source: a wording change, a fail-open, or a widened guard must be
observable from OUTSIDE the process or it is not pinned at all.

Four traps this file respects on purpose.
1. THE ACCEPT PATH NEEDS THE BUNDLED OFFLINE DRIVER. With the default provider and no
   ``--scripted-responses``, a watch tick FAILS but the command still exits 0 -- the
   per-tick handler is resilient by design -- printing ``scan 1 failed: ...`` to stderr
   while creating NO directory and NO slate. An accept-path test written without the
   driver would therefore assert almost nothing AND would fail its directory/slate
   assertions for a reason that has nothing to do with the guard. Behavior 5 uses the
   same invocation ``tests/test_iter135_behavior.py`` uses, whose two fixtures
   (``examples/fixture_workspace``, ``examples/scripted_responses.json``) are TRACKED
   by git so the precondition survives a fresh clone.
2. A REJECTING GUARD FABRICATES PASSING CONTROLS. When the subject under test refuses
   almost everything, a harness pointed at the wrong path still produces exit 2 plus one
   ``error:`` line -- exactly the shape a rejection assertion is looking for. So
   ``test_b00`` asserts the two bundled fixtures exist before any behavior runs, and
   every rejection assertion pins the message TEXT, never merely its shape.
3. AMBIENT TREE. Every writable target -- ``--out-dir`` and ``--state-dir`` alike -- is
   inside ``tmp_path`` in every single invocation, so no test writes into the checkout
   and no assertion depends on a gitignored path.
4. NO CLOCK, NO NETWORK, NO LOOP. Every invocation is bounded by ``--interval 0
   --max-scans 1``, so nothing drives a live monitor and the driver's 2 ``synthesize``
   entries are never exhausted. CI also runs 3.12 and 3.13, and 3.13 strips the common
   leading docstring indent at compile time, so nothing here asserts on indentation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from proactive_loop.cli import main

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "examples" / "scripted_responses.json"
FIXTURE_WS = REPO / "examples" / "fixture_workspace"

# Written into the offending plain file so behavior 3 can prove byte-identity
# rather than mere existence.
_FILE_BODY = "sentinel body -- a rejected run must not touch these bytes\n"

# The two wordings this module exists to pin.
_MSG_SELF = "--out-dir is not a directory"
_MSG_PARENT = "--out-dir parent is not a directory"

# Stdout markers that prove scan work ran; neither may appear on a rejection.
_TICK_HEADER = "=== scan 1 ==="
_SLATE_TRAILER = "slate written:"


# ---------------------------------------------------------------------------
# Helpers -- black-box only: build argv, drive main(), read back the exit code,
# stdout, stderr and on-disk artifacts. The guards return 2 rather than raising,
# but SystemExit is tolerated so these tests stay correct either way.
# ---------------------------------------------------------------------------


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    try:
        rc = main(argv)
    except SystemExit as exc:  # defensive: guards return 2, but tolerate exit()
        rc = exc.code if isinstance(exc.code, int) else 1
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def _reject_argv(*, workspace: Path, out_dir: Path, state_dir: Path) -> list[str]:
    """A rejection is decided before any LLM client is built, so the scripted
    driver is deliberately ABSENT here: if the guard ever stopped firing, the run
    would fail on the missing provider config instead of writing a slate, and the
    message assertions below would still catch it."""
    return [
        "watch",
        "--workspace", str(workspace),
        "--out-dir", str(out_dir),
        "--interval", "0",
        "--max-scans", "1",
        "--state-dir", str(state_dir),
    ]


def _accept_argv(*, out_dir: Path, state_dir: Path) -> list[str]:
    """The bundled offline driver invocation, with writable targets redirected."""
    return [
        "watch",
        "--workspace", str(FIXTURE_WS),
        "--provider", "scripted",
        "--scripted-responses", str(SCRIPT),
        "--interval", "0",
        "--max-scans", "1",
        "--state-dir", str(state_dir),
        "--out-dir", str(out_dir),
    ]


def _assert_clean_rejection(rc: int, out: str, err: str, expected_msg: str) -> None:
    """The rejection invariant every sibling path guard already honors: exit 2,
    0-byte stdout, stderr is EXACTLY one ``error: <msg>`` line, no leaked errno,
    no traceback."""
    assert rc == 2, f"rejection must exit 2; got {rc}; stderr={err!r}"
    assert out == "", f"stdout must be empty on rejection; got:\n{out!r}"
    assert err.splitlines() == [expected_msg], (
        f"stderr must be exactly one line equal to {expected_msg!r}; got:\n{err!r}"
    )
    combined = out + err
    assert "[Errno" not in combined, (
        f"a rejection must not leak an OS errno; got:\n{combined!r}"
    )
    assert "Traceback" not in combined, (
        f"a rejection must not leak a traceback; got:\n{combined!r}"
    )


@pytest.fixture()
def ws(tmp_path: Path) -> Path:
    """A minimal EXISTING workspace, so the workspace guard cannot pre-empt the
    ``--out-dir`` guard in behaviors 1-4."""
    root = tmp_path / "ws"
    (root / "sub").mkdir(parents=True)
    (root / "sub" / "a.py").write_text("x = 1\n", encoding="utf-8")
    (root / "notes.md").write_text("- TODO: alpha here\n", encoding="utf-8")
    return root


@pytest.fixture()
def occupied(tmp_path: Path) -> Path:
    """An existing REGULAR FILE standing where a directory is required."""
    target = tmp_path / "occupied"
    target.write_text(_FILE_BODY, encoding="utf-8")
    return target


def _reject_on_file(
    ws_dir: Path, occupied_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> tuple[int, str, str, str]:
    """Behavior 1's invocation: ``--out-dir`` IS the plain file."""
    rc, out, err = _run(
        _reject_argv(
            workspace=ws_dir, out_dir=occupied_file, state_dir=tmp_path / "state-self"
        ),
        capsys,
    )
    return rc, out, err, f"error: {_MSG_SELF}: {occupied_file}"


def _reject_in_parent_chain(
    ws_dir: Path, occupied_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> tuple[int, str, str, str]:
    """Behavior 2's invocation: the plain file sits two levels up the chain, so
    the literal parent (``<file>/sub``) does not exist and the message must name
    the deepest EXISTING ancestor instead."""
    target = occupied_file / "sub" / "stream"
    rc, out, err = _run(
        _reject_argv(
            workspace=ws_dir, out_dir=target, state_dir=tmp_path / "state-chain"
        ),
        capsys,
    )
    return rc, out, err, f"error: {_MSG_PARENT}: {occupied_file}"


# ===========================================================================
# Behavior 0 (precondition) --- the bundled offline fixtures exist.
#
# A guard that REJECTS makes a wrong-path harness look like a passing control,
# so the accept path's inputs are asserted before anything is driven.
# ===========================================================================


def test_b00_bundled_offline_driver_fixtures_are_present() -> None:
    assert FIXTURE_WS.is_dir(), (
        f"behavior 5 needs the tracked fixture workspace at {FIXTURE_WS}; "
        "without it every run hits the WORKSPACE guard and the accept-path "
        "assertions would measure a different guard entirely"
    )
    assert SCRIPT.is_file(), (
        f"behavior 5 needs the tracked scripted driver at {SCRIPT}; without it a "
        "tick fails while the command still exits 0, creating no directory and "
        "no slate"
    )


# ===========================================================================
# Behavior 1 --- `--out-dir` is an existing plain FILE -> rejected with
# `error: --out-dir is not a directory: <F>`, full rejection invariant.
# ===========================================================================


def test_b01a_existing_plain_file_as_out_dir_is_rejected_verbatim(
    ws: Path, occupied: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc, out, err, expected = _reject_on_file(ws, occupied, tmp_path, capsys)
    _assert_clean_rejection(rc, out, err, expected)


def test_b01b_the_self_message_names_the_path_as_passed(
    ws: Path, occupied: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The offending path must be echoed so a user can act on the message."""
    _rc, _out, err, _expected = _reject_on_file(ws, occupied, tmp_path, capsys)
    assert _MSG_SELF in err, f"expected the wording {_MSG_SELF!r}; got:\n{err!r}"
    assert str(occupied) in err, (
        f"the message must name the offending path {str(occupied)!r}; got:\n{err!r}"
    )


# ===========================================================================
# Behavior 2 --- an existing plain file in the PARENT CHAIN -> rejected with
# `error: --out-dir parent is not a directory: <A>`, naming the DEEPEST
# EXISTING ancestor rather than the literal (non-existent) parent.
# ===========================================================================


def test_b02a_non_directory_in_the_parent_chain_is_rejected_verbatim(
    ws: Path, occupied: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc, out, err, expected = _reject_in_parent_chain(ws, occupied, tmp_path, capsys)
    _assert_clean_rejection(rc, out, err, expected)


def test_b02b_the_parent_message_names_the_deepest_existing_ancestor(
    ws: Path, occupied: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`<file>/sub` does not exist, so naming it would send the user chasing a
    path that is not there; the guard must walk up to `<file>` itself."""
    _rc, _out, err, _expected = _reject_in_parent_chain(ws, occupied, tmp_path, capsys)
    literal_parent = occupied / "sub"
    assert err.strip() == f"error: {_MSG_PARENT}: {occupied}", (
        f"expected the deepest EXISTING ancestor {str(occupied)!r} to be named; "
        f"got:\n{err!r}"
    )
    assert str(literal_parent) not in err, (
        f"the non-existent literal parent {str(literal_parent)!r} must not be "
        f"named; got:\n{err!r}"
    )


def test_b02c_the_two_rejection_wordings_are_distinct(
    ws: Path, occupied: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A single collapsed message would lose the which-path-is-wrong signal."""
    _rc1, _o1, err_self, _e1 = _reject_on_file(ws, occupied, tmp_path, capsys)
    _rc2, _o2, err_parent, _e2 = _reject_in_parent_chain(ws, occupied, tmp_path, capsys)
    assert err_self.strip() != err_parent.strip(), (
        "the self-case and parent-chain-case messages must differ; both were "
        f"{err_self.strip()!r}"
    )
    assert _MSG_PARENT not in err_self, (
        f"the self case must not use the parent wording; got:\n{err_self!r}"
    )


# ===========================================================================
# Behavior 3 --- a rejection is SIDE-EFFECT-FREE: the offending file keeps its
# bytes and its type, and no slate is written anywhere under tmp_path.
# ===========================================================================


def test_b03a_file_rejection_leaves_the_offending_file_byte_identical(
    ws: Path, occupied: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _reject_on_file(ws, occupied, tmp_path, capsys)
    assert occupied.is_file(), (
        f"{occupied} must still be a regular file after a rejection; "
        "nothing may be replaced by a directory"
    )
    assert occupied.read_bytes() == _FILE_BODY.encode("utf-8"), (
        f"a rejected run must not truncate or rewrite {occupied}; got "
        f"{occupied.read_bytes()!r}"
    )


def test_b03b_parent_chain_rejection_leaves_the_offending_file_byte_identical(
    ws: Path, occupied: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _reject_in_parent_chain(ws, occupied, tmp_path, capsys)
    assert occupied.is_file(), (
        f"{occupied} must still be a regular file after a parent-chain rejection"
    )
    assert occupied.read_bytes() == _FILE_BODY.encode("utf-8"), (
        f"a rejected run must not touch {occupied}; got {occupied.read_bytes()!r}"
    )


def test_b03c_neither_rejection_writes_a_slate_anywhere(
    ws: Path, occupied: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Recursive, not scoped to `--out-dir`: a guard that returned too late could
    have written the stream somewhere else entirely."""
    _reject_on_file(ws, occupied, tmp_path, capsys)
    _reject_in_parent_chain(ws, occupied, tmp_path, capsys)
    strays = sorted(str(p) for p in tmp_path.rglob("slate-*.json"))
    assert strays == [], (
        f"a rejected run must create no slate under {tmp_path}; found {strays}"
    )


# ===========================================================================
# Behavior 4 --- a rejection PRECEDES all scan work: no tick header and no
# slate trailer on stdout, even though `--max-scans 1 --interval 0` was given.
# ===========================================================================


def test_b04a_file_rejection_prints_no_tick_header_and_no_slate_trailer(
    ws: Path, occupied: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _rc, out, _err, _expected = _reject_on_file(ws, occupied, tmp_path, capsys)
    assert _TICK_HEADER not in out, (
        f"a rejection must precede scan work, so {_TICK_HEADER!r} must not be "
        f"printed; got:\n{out!r}"
    )
    assert _SLATE_TRAILER not in out, (
        f"a rejection must print no {_SLATE_TRAILER!r} trailer; got:\n{out!r}"
    )
    assert out == "", f"stdout must be entirely empty on rejection; got:\n{out!r}"


def test_b04b_parent_chain_rejection_prints_no_tick_header_and_no_slate_trailer(
    ws: Path, occupied: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _rc, out, _err, _expected = _reject_in_parent_chain(ws, occupied, tmp_path, capsys)
    assert _TICK_HEADER not in out, (
        f"a parent-chain rejection must precede scan work, so {_TICK_HEADER!r} "
        f"must not be printed; got:\n{out!r}"
    )
    assert _SLATE_TRAILER not in out, (
        f"a parent-chain rejection must print no {_SLATE_TRAILER!r} trailer; "
        f"got:\n{out!r}"
    )
    assert out == "", f"stdout must be entirely empty on rejection; got:\n{out!r}"


# ===========================================================================
# Behavior 5 --- the guard does NOT over-reject: a fully-absent nested
# `--out-dir` is LEGAL, is created, and receives exactly one slate. This is the
# fail-closed half of the two-sided proof.
# ===========================================================================


def test_b05a_fully_absent_nested_out_dir_is_accepted_and_created(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "streams"
    root.mkdir()
    target = root / "a" / "b" / "c"
    assert not target.exists(), f"the harness must start with {target} absent"
    rc, _out, err = _run(
        _accept_argv(out_dir=target, state_dir=tmp_path / "state-accept"), capsys
    )
    assert rc == 0, (
        f"a fully-absent nested --out-dir under an existing directory is legal and "
        f"must exit 0; got {rc}; stderr={err!r}"
    )
    assert target.is_dir(), (
        f"{target} must be created by the run; the guard must not reject a path it "
        "is expected to make"
    )


def test_b05b_accepted_out_dir_receives_exactly_one_slate(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "streams"
    root.mkdir()
    target = root / "a" / "b" / "c"
    rc, _out, err = _run(
        _accept_argv(out_dir=target, state_dir=tmp_path / "state-accept"), capsys
    )
    assert rc == 0, f"the accept path must exit 0; got {rc}; stderr={err!r}"
    slates = sorted(p.name for p in target.glob("slate-*.json"))
    assert slates == ["slate-001.json"], (
        f"one bounded scan must leave exactly ['slate-001.json'] in {target}; "
        f"found {slates}"
    )


def test_b05c_the_accept_path_emits_no_guard_message_on_stderr(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "streams"
    root.mkdir()
    target = root / "a" / "b" / "c"
    _rc, _out, err = _run(
        _accept_argv(out_dir=target, state_dir=tmp_path / "state-accept"), capsys
    )
    assert err == "", (
        f"a legal --out-dir must produce no stderr at all; got:\n{err!r}"
    )
    assert _MSG_SELF not in err and _MSG_PARENT not in err, (
        f"neither rejection wording may appear on the accept path; got:\n{err!r}"
    )


# ===========================================================================
# Behavior 6 --- the WORKSPACE guard still wins over the `--out-dir` guard,
# pinning the deliberate ordering of the two checks.
# ===========================================================================


def test_b06a_workspace_guard_wins_over_the_out_dir_guard(
    occupied: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing_ws = tmp_path / "no-such-workspace"
    assert not missing_ws.exists(), "the harness must start with the workspace absent"
    rc, out, err = _run(
        _reject_argv(
            workspace=missing_ws, out_dir=occupied, state_dir=tmp_path / "state-order"
        ),
        capsys,
    )
    _assert_clean_rejection(rc, out, err, f"error: workspace not found: {missing_ws}")


def test_b06b_the_out_dir_message_never_appears_when_the_workspace_is_missing(
    occupied: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing_ws = tmp_path / "no-such-workspace"
    _rc, out, err = _run(
        _reject_argv(
            workspace=missing_ws, out_dir=occupied, state_dir=tmp_path / "state-order"
        ),
        capsys,
    )
    combined = out + err
    assert _MSG_SELF not in combined, (
        f"the --out-dir message must be suppressed while the workspace is "
        f"missing; got:\n{combined!r}"
    )
    assert _MSG_PARENT not in combined, (
        f"the --out-dir parent message must be suppressed while the workspace is "
        f"missing; got:\n{combined!r}"
    )
