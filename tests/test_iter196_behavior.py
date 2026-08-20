"""Black-box behavior tests for state-dir iteration 192 (ships as ``factory iter 194``).

Feature under test: ``_out_dir_guard`` -- the structural pre-check on ``watch
--out-dir DIR`` -- is the NEWEST member of this repo's three-guard CLI path-guard
family and the ONLY one no test named. Measured over ``git ls-files tests`` during
the PM stage, two-sided so a zero could not come from a broken matcher:
``--out-dir is not a directory`` -> 0 hits, ``--out-dir parent is not a
directory`` -> 0 hits, ``_out_dir_guard`` -> 0 hits, while the shared substring
``is not a directory`` -> 17 hits (the three SIBLING guards, pinned verbatim).

So both of this guard's rejection messages were unpinned on a PUBLIC repo, where
this codebase's governing rule is that a trusted fail-open gate is worse than no
gate: the wording could drift, the guard could stop rejecting, or it could start
rejecting a LEGAL path, all with a green build. The failure it protects against is
user-visible and its own docstring describes it -- without the guard a bad
``--out-dir`` surfaces only at the first tick's write, as a raw ``[Errno 20] Not a
directory`` leaked AFTER a successful-looking table was already printed, and on a
long-lived watcher that repeats every tick.

WHAT THIS MODULE ADDS: an oracle only. Nothing under ``src/`` moves this
iteration, so every assertion below describes SHIPPED behavior.

HOW IT VERIFIES, INDEPENDENTLY
Every assertion drives the public CLI entry point ``proactive_loop.cli.main(argv)
-> int`` as a BLACK BOX and reads back the exit code, captured stdout/stderr and
on-disk artifacts. Nothing here imports ``_out_dir_guard``, reproduces its ancestor
walk, or reads its source, so this file cannot agree with the implementation merely
by sharing a bug with it.

TWO-SIDED ON PURPOSE. Behaviors 1, 2 and 6 are the REJECT half; behavior 5 is the
ACCEPT half, which fails if a future edit widens the guard into rejecting a legal
all-new nested path. A reject-only module would be satisfied by a guard that
refuses everything.

FOUR TRAPS THIS FILE RESPECTS
1. THE ACCEPT PATH NEEDS THE BUNDLED OFFLINE DRIVER. Measured: with the default
   provider and no ``--scripted-responses``, the tick FAILS but ``watch`` still
   exits 0 -- the per-tick handler is resilient BY DESIGN -- printing ``scan 1
   failed: provider is 'scripted' but no scripted_responses_path was configured``
   to stderr while creating NO directory and NO slate. An accept-path test written
   without the driver would therefore assert almost nothing and would fail on the
   directory/slate assertions for a reason unrelated to the guard.
2. SUBSTRING DIRECTION IN BEHAVIOR 2. The guard must name the deepest EXISTING
   ancestor ``F``, not the literal parent ``F/sub`` which does not exist. Those two
   are checked in the only direction that is meaningful: ``str(F)`` is a PREFIX of
   ``str(F / "sub")``, so asserting ``str(F) in stderr`` would also pass for the
   wrong message; asserting the longer ``str(F / "sub")`` is ABSENT cannot.
3. AMBIENT TREE. Every writable target -- ``--out-dir`` and ``--state-dir`` alike --
   is redirected under ``tmp_path`` in every single case, so no test writes into the
   checkout and a fresh clone re-verifies every ship. The only repo paths read are
   the two git-TRACKED bundled fixtures, asserted present by behavior 5's
   precondition test rather than assumed.
4. NO LIVE MONITOR LOOP. Every invocation is bounded by ``--interval 0
   --max-scans 1``: no sleeps, no clock dependence, no network, no randomness.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from proactive_loop.cli import main

REPO = Path(__file__).resolve().parents[1]
#: The repo's only offline, copy-pasteable driver and its fixture workspace. Both
#: are TRACKED by git (behavior 5's precondition test asserts they are present),
#: so the accept path survives a fresh clone.
FIXTURE_WS = REPO / "examples" / "fixture_workspace"
SCRIPT = REPO / "examples" / "scripted_responses.json"

#: The bytes of the regular file every rejection case points ``--out-dir`` at.
#: A module constant so behavior 3 can prove the rejection was side-effect-free by
#: comparing against a value the run could not have influenced.
_PLAIN_BYTES = b"out-dir-guard fixture: this must stay a REGULAR file\n"

#: Substrings that betray a tick having run. Behavior 4 asserts neither reaches
#: stdout on a rejection, i.e. the guard returns BEFORE any scan work.
_TICK_HEADER = "=== scan 1 ==="
_SLATE_TRAILER = "slate written:"


# ---------------------------------------------------------------------------
# Helpers -- black-box only: build argv, drive main(), read exit code, stdout,
# stderr and on-disk artifacts. The guards return 2 rather than raising, but
# SystemExit is tolerated so these tests stay correct either way.
# ---------------------------------------------------------------------------


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    """Drive ``main(argv)`` and return ``(exit_code, stdout, stderr)``."""
    try:
        rc = main(argv)
    except SystemExit as exc:  # pragma: no cover -- guards return, they do not raise
        rc = int(exc.code or 0)
    captured = capsys.readouterr()
    return rc, captured.out, captured.err


def _watch_argv(
    *,
    workspace: Path,
    out_dir: Path,
    state_dir: Path,
    scripted: bool = False,
) -> list[str]:
    """A bounded single-tick ``watch`` argv with every writable target redirected.

    ``scripted=True`` adds the bundled offline driver, which trap 1 in the module
    docstring makes mandatory for the ACCEPT path and unnecessary for the reject
    paths (the guard returns before any LLM client is built, so a rejection
    consumes no scripted response).
    """
    argv = [
        "watch",
        "--workspace", str(workspace),
        "--out-dir", str(out_dir),
        "--interval", "0",
        "--max-scans", "1",
        "--state-dir", str(state_dir),
    ]
    if scripted:
        # APPENDED, never spliced at an index: an earlier draft inserted these at
        # argv[2:2], which lands BETWEEN ``--workspace`` and its value and makes
        # argparse consume ``--provider`` as the workspace. That exits 2 with a
        # usage error -- indistinguishable at a glance from the guard rejecting a
        # legal path, i.e. a harness bug wearing the failure it is meant to detect.
        # argparse is order-insensitive for optionals, so appending is equivalent
        # and carries no index arithmetic to get wrong.
        argv += ["--provider", "scripted", "--scripted-responses", str(SCRIPT)]
    return argv


def _assert_clean_rejection(rc: int, out: str, err: str, expected_msg: str) -> None:
    """The rejection invariant every path guard in this CLI already honors: exit 2,
    0-byte stdout, stderr is EXACTLY one ``error: <msg>`` line, no leaked errno and
    no traceback. Shape borrowed from the sibling guards' own oracle so this guard
    is held to the identical bar rather than a weaker one of its own."""
    assert rc == 2, f"a rejected --out-dir must exit 2; got {rc}; stderr={err!r}"
    assert out == "", f"stdout must be empty on rejection; got:\n{out!r}"
    assert err.splitlines() == [expected_msg], (
        f"stderr must be exactly one line equal to {expected_msg!r}; got:\n{err!r}"
    )
    combined = out + err
    assert "[Errno" not in combined, (
        f"the guard exists to PREVENT a leaked OS errno; got:\n{combined!r}"
    )
    assert "Traceback" not in combined, f"no traceback allowed; got:\n{combined!r}"


@pytest.fixture
def plain_file(tmp_path: Path) -> Path:
    """A regular FILE, inside ``tmp_path``, of known bytes -- the thing an
    ``--out-dir`` may never be."""
    target = tmp_path / "plain.txt"
    target.write_bytes(_PLAIN_BYTES)
    return target


def _reject_file_case(
    plain_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> tuple[int, str, str]:
    """Case 1: ``--out-dir`` IS the existing plain file."""
    return _run(
        _watch_argv(
            workspace=FIXTURE_WS, out_dir=plain_file, state_dir=tmp_path / "state-1"
        ),
        capsys,
    )


def _reject_chain_case(
    plain_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> tuple[int, str, str]:
    """Case 2: the plain file sits in the PARENT CHAIN of an absent target."""
    return _run(
        _watch_argv(
            workspace=FIXTURE_WS,
            out_dir=plain_file / "sub" / "stream",
            state_dir=tmp_path / "state-2",
        ),
        capsys,
    )


# ===========================================================================
# Behavior 1 -- an existing plain FILE as --out-dir is rejected, exit 2, with
# one exact message naming the path as pathlib renders it.
# ===========================================================================


def test_b01a_out_dir_that_is_an_existing_plain_file_is_rejected(
    plain_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc, out, err = _reject_file_case(plain_file, tmp_path, capsys)
    _assert_clean_rejection(
        rc, out, err, f"error: --out-dir is not a directory: {plain_file}"
    )


def test_b01b_the_existing_file_branch_fires_not_the_parent_chain_branch(
    plain_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Pins WHICH of the guard's two clauses answered. The message for an existing
    non-directory must not mention a parent -- collapsing the two clauses into one
    ancestor-walk message would still exit 2 and would still be a regression,
    because it would stop telling the user that the path they typed is the file."""
    _rc, _out, err = _reject_file_case(plain_file, tmp_path, capsys)
    assert "parent" not in err, (
        "--out-dir pointing AT an existing file must report the path itself, not a "
        f"parent; got:\n{err!r}"
    )


# ===========================================================================
# Behavior 2 -- a plain file in the PARENT CHAIN is rejected, and the message
# names the deepest EXISTING ancestor rather than the literal parent.
# ===========================================================================


def test_b02a_a_plain_file_in_the_parent_chain_is_rejected(
    plain_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc, out, err = _reject_chain_case(plain_file, tmp_path, capsys)
    _assert_clean_rejection(
        rc, out, err, f"error: --out-dir parent is not a directory: {plain_file}"
    )


def test_b02b_the_message_names_the_deepest_existing_ancestor_not_the_literal_parent(
    plain_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The target is ``F/sub/stream`` where only ``F`` exists, so the guard walks up
    to ``F``. Asserted in the ONLY direction that discriminates: ``str(F)`` is a
    PREFIX of ``str(F / "sub")``, so ``str(F) in err`` would also pass for the wrong
    message, whereas the longer literal parent must be ABSENT."""
    literal_parent = plain_file / "sub"
    _rc, _out, err = _reject_chain_case(plain_file, tmp_path, capsys)
    assert str(literal_parent) not in err, (
        f"the message must name the deepest EXISTING ancestor {str(plain_file)!r}, "
        f"never the non-existent literal parent {str(literal_parent)!r}; got:\n{err!r}"
    )


# ===========================================================================
# Behavior 3 -- a rejection is side-effect-free: nothing created, truncated or
# renamed, and no stream slate anywhere.
# ===========================================================================


def test_b03a_a_rejection_leaves_the_offending_file_byte_identical(
    plain_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Both rejection cases, against the SAME file, so an open-for-write on either
    clause would show up as truncation."""
    _reject_file_case(plain_file, tmp_path, capsys)
    assert plain_file.read_bytes() == _PLAIN_BYTES, (
        "case 1 must not touch the file it refused to use as a directory"
    )
    _reject_chain_case(plain_file, tmp_path, capsys)
    assert plain_file.read_bytes() == _PLAIN_BYTES, (
        "case 2 must not touch the ancestor it refused to write beneath"
    )
    assert plain_file.is_file(), (
        "the offending path must still be a regular file, not replaced by a directory"
    )


def test_b03b_a_rejection_writes_no_stream_slate_anywhere(
    plain_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Recursive over the whole ``tmp_path``, not just the refused target: a guard
    that rejected but still wrote the tick's slate somewhere else would pass a
    narrower check."""
    _reject_file_case(plain_file, tmp_path, capsys)
    _reject_chain_case(plain_file, tmp_path, capsys)
    strays = sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("slate-*.json"))
    assert strays == [], f"a rejection must create no slate anywhere under tmp; found {strays}"


# ===========================================================================
# Behavior 4 -- the rejection PRECEDES all scan work, even though a bounded
# single tick was requested.
# ===========================================================================


def test_b04_a_rejection_precedes_all_scan_work(
    plain_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--max-scans 1 --interval 0`` was supplied in both cases, so an empty stdout
    with neither the tick header nor the slate trailer is positive evidence that the
    guard returned before the scan body -- not merely that the scan printed nothing."""
    for label, (_rc, out, _err) in (
        ("case 1", _reject_file_case(plain_file, tmp_path, capsys)),
        ("case 2", _reject_chain_case(plain_file, tmp_path, capsys)),
    ):
        assert out == "", f"{label}: stdout must be empty; got:\n{out!r}"
        assert _TICK_HEADER not in out, (
            f"{label}: no tick may run before the guard; found {_TICK_HEADER!r}"
        )
        assert _SLATE_TRAILER not in out, (
            f"{label}: no slate may be announced before the guard; found {_SLATE_TRAILER!r}"
        )


# ===========================================================================
# Behavior 5 -- THE ACCEPT HALF. A fully-absent nested --out-dir is LEGAL and is
# created on demand. This is what fails if the guard is ever widened.
# ===========================================================================


def test_b05a_the_bundled_offline_driver_precondition_is_present(tmp_path: Path) -> None:
    """Asserted rather than assumed, so a checkout missing either tracked fixture
    fails HERE with a plain message instead of surfacing as a bogus guard defect
    three tests later (trap 1)."""
    assert FIXTURE_WS.is_dir(), (
        f"the tracked fixture workspace must exist at {FIXTURE_WS}; the accept path "
        "cannot be driven offline without it"
    )
    assert SCRIPT.is_file(), (
        f"the tracked offline driver must exist at {SCRIPT}; without it a watch tick "
        "FAILS while still exiting 0, so the accept path would assert nothing"
    )


def _accept_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> tuple[int, str, str, Path]:
    """Behavior 5's invocation: ``D/a/b/c`` where ``D`` exists and ``a``, ``b``,
    ``c`` are all absent, driven by the bundled offline driver."""
    existing = tmp_path / "existing"
    existing.mkdir()
    nested = existing / "a" / "b" / "c"
    rc, out, err = _run(
        _watch_argv(
            workspace=FIXTURE_WS,
            out_dir=nested,
            state_dir=tmp_path / "state-accept",
            scripted=True,
        ),
        capsys,
    )
    return rc, out, err, nested


def test_b05b_a_fully_absent_nested_out_dir_is_accepted_and_created(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc, _out, err, nested = _accept_run(tmp_path, capsys)
    assert rc == 0, (
        f"an all-new nested --out-dir is LEGAL (the writer creates parents on "
        f"demand); got exit {rc}; stderr={err!r}"
    )
    assert nested.is_dir(), (
        f"the accepted --out-dir must exist as a DIRECTORY after the run; {nested} "
        f"exists={nested.exists()}"
    )


def test_b05c_the_accepted_run_writes_exactly_one_stream_slate(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """One tick, so exactly one stream slate. Also the check that distinguishes a
    genuinely accepted run from the resilient exit-0 of a FAILED tick (trap 1),
    which creates no directory and no slate at all."""
    _rc, _out, _err, nested = _accept_run(tmp_path, capsys)
    slates = sorted(p.name for p in nested.glob("slate-*.json")) if nested.exists() else []
    assert slates == ["slate-001.json"], (
        f"one accepted tick must write exactly one stream slate named slate-001.json; "
        f"found {slates}"
    )


def test_b05d_the_accepted_run_writes_nothing_to_stderr(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A legal path must produce no diagnostic at all -- neither a guard message nor
    a per-tick ``scan 1 failed:`` note."""
    _rc, _out, err, _nested = _accept_run(tmp_path, capsys)
    assert err == "", f"an accepted --out-dir must emit no diagnostic; got:\n{err!r}"


# ===========================================================================
# Behavior 6 -- guard ORDER: the workspace guard wins over the --out-dir guard.
# ===========================================================================


def _precedence_run(
    plain_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> tuple[int, str, str, Path]:
    """BOTH inputs are invalid at once: a missing workspace AND an --out-dir that is
    an existing plain file."""
    missing_ws = tmp_path / "no-such-workspace"
    rc, out, err = _run(
        _watch_argv(
            workspace=missing_ws, out_dir=plain_file, state_dir=tmp_path / "state-6"
        ),
        capsys,
    )
    return rc, out, err, missing_ws


def test_b06a_the_workspace_guard_wins_over_the_out_dir_guard(
    plain_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc, out, err, missing_ws = _precedence_run(plain_file, tmp_path, capsys)
    _assert_clean_rejection(rc, out, err, f"error: workspace not found: {missing_ws}")


def test_b06b_no_out_dir_diagnostic_appears_when_the_workspace_is_missing(
    plain_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The deliberate ordering: the workspace is the front-door guard, so a run with
    two defects reports the workspace and stops. Reporting both, or reporting the
    --out-dir one instead, would be the regression this pins."""
    _rc, out, err, _missing_ws = _precedence_run(plain_file, tmp_path, capsys)
    combined = out + err
    assert "--out-dir" not in combined, (
        "with a missing workspace the --out-dir guard must not have run at all; got:\n"
        f"{combined!r}"
    )
