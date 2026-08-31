"""Black-box verification of factory iteration 258: a hostile operator path in
``--baseline`` is refused cleanly instead of crashing the ``pla run`` CLI.

MODULE NAME, derived from the repo and never from the state-dir counter. The two
counters differ here (state dir ``iter-258``, offset 22, not guaranteed), so the
name was derived: the highest tracked ``tests/test_iterNN_behavior.py`` was
``235``, +1 = ``236``, and ``git cat-file -e HEAD:tests/test_iter236_behavior.py``
FAILED before a byte was written (measured: ``fatal: path ... does not exist in
'HEAD'``) -- the path is provably free.

ISOLATION CONTRACT, honored. Nothing under ``src/`` was read; no engineer or
reviewer note and no ``IMPLEMENTATION.patch`` was opened; no ``git diff`` was
run. Every assertion drives the public ``proactive_loop.cli.main`` with an argv
list, or the installed ``pla`` console script in its own process, and reads back
only the exit code, captured stdout/stderr, and files the CLI itself wrote.

WHY THIS ITERATION EXISTS (the defect it closes). Iteration 257 added a consumer
of operator paths that runs BEFORE ``main()``'s only ``try:`` -- deliberately, so
the aliased-pair refusal has zero side effects by construction. That placement
put it outside the handler that turns a filesystem fault into a message, and the
comparison resolves both paths. On CPython 3.12 ``pathlib`` converts an ``ELOOP``
``OSError`` into a ``RuntimeError``, which is NOT in the handled tuple; on 3.13
``resolve()`` does not raise at all. So the CI matrix stayed green while ONE leg
dumped a stacktrace on foreseeable input, because no test built a symlink loop.

DISCRIMINATION, MEASURED -- this oracle is two-sided, not decorative. The same
six probes were run against a pristine ``git archive HEAD`` tree (``3e9ee1d``)
extracted to a scratch dir, on the same ``.venv`` interpreter (**Python 3.12.7**):

* behaviors 1, 2 and 3 RAISED ``RuntimeError("Symlink loop from '...loopA.json'")``
  straight out of ``main()`` -- in a real process, rc=1 with 25 stderr lines and
  2 tracebacks;
* behaviors 4, 5 and 6 were already correct at HEAD and are pure regression
  guards here.

So 1-3 are the new contract and 4-6 protect what already worked.

ANTI-MIS-FIX. The plausible wrong repair is to drop ``resolve()`` for
``absolute()`` outright: it removes the crash and leaves every previously
shipped test green, while silently reopening the data-loss hole the guard exists
to close. Behavior 4 is the regression oracle for exactly that, and the reason
it bites is a stdlib fact this module MEASURES in
``test_b4d_the_symlink_case_is_the_discriminator_for_the_plausible_mis_fix``
rather than asserting on faith: for a valid symlink ``link.json`` -> ``b.json``,
``resolve()`` reports the two spellings EQUAL and ``absolute()`` reports them
UNEQUAL, and ``absolute()`` also leaves ``sub/../b.json`` un-normalised.

OFFLINE AND DETERMINISTIC: provider ``scripted`` with the tracked example
script, no network, no API key, no sleeps, no duration asserted anywhere. Every
fixture (workspace, baseline, snapshot, state dir, symlinks) is built inside
``tmp_path``; the only checkout path read is the TRACKED
``examples/scripted_responses.json``, so a throwaway fresh clone verifies
identically -- nothing here reads gitignored local state except the ``pla``
console script, which ``uv sync`` installs and which 127 shipped test modules
already depend on the same way.

FIXTURE HYGIENE, MANDATED BY THE SPEC AND NOT OPTIONAL. A ``--snapshot`` naming
the loop is written through the repo's atomic writer, whose ``os.replace``
REPLACES the symlink with a regular file. A fixture shared between a writing
case and a reading case therefore silently stops being a loop and reports the
OPPOSITE of the truth. So ``_hostile_case`` builds a fresh loop in its own
subdirectory per invocation and asserts ``errno.ELOOP`` before anything is
measured; two cases never share one loop.

Coverage, numbered to match this iteration's spec Expected Behaviors:

1. Hostile ``--baseline`` with a distinct ``--snapshot``: exit 2, EMPTY stdout,
   exactly one ``error: `` line naming the path, no traceback, and ``main()``
   does not raise. Pinned a second time through the REAL process boundary.
2. Hostile path in BOTH flags: still refused as an aliased pair, exit 2, empty
   stdout, the shipped aliased wording, no raise.
3. Hostile ``--snapshot``: the guard is transparent, not fatal -- exit code and
   stderr are identical to the same invocation with ``--baseline`` omitted.
4. Regression / anti-mis-fix: all four resolvable aliasing spellings stay
   refused, including a VALID symlink, plus the stdlib measurement that makes
   that case the discriminator.
5. The guard-not-applicable path (``signals``, which owns ``--baseline`` but not
   ``--snapshot``) is untouched.
6. The happy path is unchanged.

AMBIGUITY NOTES (PM feedback, deliberate readings):

* The spec words behaviors 1-3 as "stderr contains no occurrence of
  ``Traceback``". Taken literally and IN-PROCESS that assertion is **VACUOUS**:
  at HEAD the ``RuntimeError`` propagates out of ``main()`` and nothing is
  printed, so ``"Traceback" not in stderr`` PASSES on the broken tree. The
  discriminating in-process observation is "``main()`` must not raise", so every
  case asserts that FIRST and keeps the literal no-traceback check as a
  secondary. The literal contract is additionally pinned where it is real -- in
  a subprocess, where Python's default excepthook does the printing
  (behavior 1b, measured: 2 tracebacks at HEAD, 0 here).
* Behavior 3 says exit code and stderr must be "identical" with and without
  ``--baseline``. STDOUT is deliberately NOT compared: a run given a baseline
  legitimately reports the suppression, and stdout measured 1264 bytes with the
  flag against 1146 without it on both trees. Comparing it would pin unrelated
  prose.
* Behavior 5 says "unchanged from HEAD". A byte-diff against HEAD is not
  reachable from an in-process test, so the tested reading is the shape the spec
  itself measured there: exit 2, empty stdout, exactly one ``error: `` line, no
  traceback.
"""

from __future__ import annotations

import errno
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from proactive_loop.cli import main

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "examples" / "scripted_responses.json"

#: The prefix the shipped CLI uses when it refuses an unreadable baseline. Taken
#: from the spec, which measured it from the sibling ``--baseline <nonexistent>``
#: invocation that has been shipped since iteration 230.
BASELINE_REFUSAL = "error: baseline file not found or not a regular file: "

#: The shipped aliased-pair wording introduced by iteration 257.
ALIASED_WORDING = "--baseline and --snapshot must name different files:"


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    """argv in -> (exit code, stdout, stderr), and ``main`` MUST NOT raise.

    A refusal may either RETURN 2 or raise ``SystemExit(2)`` (argparse does the
    latter) -- both are legitimate. Anything else escaping ``main`` is the very
    defect this iteration closes, so it is reported as a failed assertion with
    the exception in the message rather than as a test error.
    """
    try:
        rc = main(argv)
    except SystemExit as exc:
        rc = exc.code if isinstance(exc.code, int) else 1
    except BaseException as exc:  # noqa: BLE001 -- this IS the contract under test
        captured = capsys.readouterr()
        raise AssertionError(
            "main() must not let an exception escape to the operator; the CLI has to "
            f"fail legibly instead. Got {type(exc).__name__}: {exc}\n"
            f"stdout={captured.out!r}\nstderr={captured.err!r}"
        ) from exc
    captured = capsys.readouterr()
    return rc, captured.out, captured.err


def _workspace(root: Path) -> Path:
    """A minimal workspace the shipped collectors find one signal in."""
    ws = root / "ws"
    ws.mkdir(parents=True)
    (ws / "module.py").write_text("# todo: give the collectors one marker\n", encoding="utf-8")
    return ws


def _valid_baseline(root: Path) -> Path:
    path = root / "b.json"
    path.write_text(json.dumps({"signals": []}), encoding="utf-8")
    return path


def _symlink_loop(root: Path) -> Path:
    """Build an absolute two-hop symlink loop and PROVE the OS refuses it.

    The precondition is mandatory, not decorative: if an earlier case wrote
    through this path the symlink is gone and the "hostile" case would quietly
    measure a benign one.
    """
    a = root / "loopA.json"
    b = root / "loopB.json"
    a.symlink_to(b)
    b.symlink_to(a)
    with pytest.raises(OSError) as excinfo:
        os.stat(a)
    assert excinfo.value.errno == errno.ELOOP, (
        "fixture precondition failed: loopA.json must be an unresolvable symlink loop, "
        f"but os.stat raised {excinfo.value!r}"
    )
    return a


def _hostile_case(tmp_path: Path, name: str) -> tuple[Path, Path, Path, Path]:
    """A FRESH per-case sandbox -> (root, workspace, valid baseline, symlink loop)."""
    root = tmp_path / name
    root.mkdir(parents=True)
    return root, _workspace(root), _valid_baseline(root), _symlink_loop(root)


def _run_argv(root: Path, *extra: str) -> list[str]:
    return [
        "run",
        "--dry-run",
        "--workspace",
        str(root / "ws"),
        "--provider",
        "scripted",
        "--scripted-responses",
        str(SCRIPT),
        "--state-dir",
        str(root / "state"),
        *extra,
    ]


def _error_lines(stderr: str) -> list[str]:
    """The stderr lines carrying the failure, excluding argparse's usage block."""
    return [line for line in stderr.splitlines() if "error:" in line]


def _console_script() -> Path:
    """The installed ``pla`` console script (same convention as 127 shipped modules)."""
    bindir = Path(sys.executable).parent
    candidates = [bindir / "pla", bindir / "pla.exe"]
    which = shutil.which("pla")
    if which:
        candidates.append(Path(which))
    script = next((c for c in candidates if c.is_file()), None)
    assert script is not None, (
        "the `pla` console script must be installed (declared in pyproject, installed by "
        f"`uv sync`); searched {[str(c) for c in candidates]}"
    )
    return script


# ---------------------------------------------------------------------------
# Behavior 1 -- a hostile --baseline with a distinct --snapshot refuses cleanly
# ---------------------------------------------------------------------------


def test_b1_hostile_baseline_with_distinct_snapshot_is_a_clean_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, _ws, _baseline, loop = _hostile_case(tmp_path, "b1")
    snapshot = root / "out.json"

    rc, out, err = _run(
        _run_argv(root, "--baseline", str(loop), "--snapshot", str(snapshot)), capsys
    )

    assert rc == 2, f"an operator path the OS refuses is a usage error; got rc={rc}\nstderr={err}"
    assert out == "", f"a usage error must write NOTHING to stdout; got {out!r}"
    lines = _error_lines(err)
    assert len(lines) == 1, f"expected exactly ONE error line, got {len(lines)}: {lines!r}"
    assert lines[0].startswith(BASELINE_REFUSAL), (
        "the refusal must reuse the shipped unreadable-baseline wording (behavior 10 of "
        f"tests/test_iter230_behavior.py); got {lines[0]!r}"
    )
    assert str(loop) in lines[0], f"the refusal must name the offending path; got {lines[0]!r}"
    assert "Traceback" not in err, f"no stacktrace may reach the operator:\n{err}"
    assert not snapshot.exists(), "a refused run must not have written the snapshot"
    assert not (root / "state").exists(), "a refused run must not create the state dir"


def test_b1b_the_real_process_prints_no_traceback_and_exits_two(tmp_path: Path) -> None:
    """The literal 'no Traceback in stderr' contract, pinned where it is REAL.

    In-process the check is vacuous (see the module ambiguity note): the escaping
    ``RuntimeError`` is what prints the traceback, and only a real process runs
    the default excepthook. Measured against the pristine HEAD tree this exact
    invocation gave rc=1 with 2 tracebacks; it must now give rc=2 with none.
    """
    root, _ws, _baseline, loop = _hostile_case(tmp_path, "b1b")

    result = subprocess.run(
        [
            str(_console_script()),
            *_run_argv(root, "--baseline", str(loop), "--snapshot", str(root / "out.json")),
        ],
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode == 2, (
        f"the real CLI must exit 2, not crash; got rc={result.returncode}\n"
        f"stderr={result.stderr}"
    )
    assert result.stdout == "", f"a usage error must write NOTHING to stdout; got {result.stdout!r}"
    assert "Traceback" not in result.stderr, (
        f"the real process must not dump a stacktrace:\n{result.stderr}"
    )
    lines = _error_lines(result.stderr)
    assert len(lines) == 1, f"expected exactly ONE error line, got {len(lines)}: {lines!r}"
    assert lines[0].startswith(BASELINE_REFUSAL), f"unexpected wording: {lines[0]!r}"


# ---------------------------------------------------------------------------
# Behavior 2 -- a hostile path in BOTH flags is still an aliased pair
# ---------------------------------------------------------------------------


def test_b2_hostile_path_in_both_flags_is_refused_as_an_aliased_pair(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, _ws, _baseline, loop = _hostile_case(tmp_path, "b2")

    rc, out, err = _run(_run_argv(root, "--baseline", str(loop), "--snapshot", str(loop)), capsys)

    assert rc == 2, f"an aliased pair is a usage error; got rc={rc}\nstderr={err}"
    assert out == "", f"a usage error must write NOTHING to stdout; got {out!r}"
    assert "Traceback" not in err, f"no stacktrace may reach the operator:\n{err}"
    assert ALIASED_WORDING in err, (
        "one path in both flags is the aliasing the iter-257 guard exists to refuse, so the "
        f"shipped aliased wording must survive an unresolvable path; got:\n{err}"
    )
    assert loop.is_symlink(), "the refusal must not have written through the symlink"


# ---------------------------------------------------------------------------
# Behavior 3 -- a hostile --snapshot makes the guard transparent, not fatal
# ---------------------------------------------------------------------------


def test_b3_hostile_snapshot_behaves_exactly_as_if_baseline_were_absent(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Two FRESH sandboxes on purpose: each invocation writes through its own loop."""
    with_root, _ws1, baseline, with_loop = _hostile_case(tmp_path, "b3-with-baseline")
    rc_with, out_with, err_with = _run(
        _run_argv(with_root, "--baseline", str(baseline), "--snapshot", str(with_loop)), capsys
    )

    without_root, _ws2, _baseline2, without_loop = _hostile_case(tmp_path, "b3-without-baseline")
    rc_without, out_without, err_without = _run(
        _run_argv(without_root, "--snapshot", str(without_loop)), capsys
    )

    assert "Traceback" not in err_with, f"no stacktrace may reach the operator:\n{err_with}"
    assert rc_with == rc_without, (
        "the guard must not change how a hostile --snapshot is handled: "
        f"rc={rc_with} with --baseline vs rc={rc_without} without it\n"
        f"stderr with={err_with!r}\nstderr without={err_without!r}"
    )
    assert err_with == err_without, (
        "stderr must be identical with and without --baseline for a hostile --snapshot; "
        f"with={err_with!r} without={err_without!r}"
    )
    # Non-vacuity: the comparison would be worthless if both sides were refusals.
    assert rc_with == 0, (
        "control: a hostile --snapshot is NOT the guard's business, so this invocation is "
        f"expected to succeed on both sides; got rc={rc_with}\nstderr={err_with!r}"
    )
    assert out_with != "", "the succeeding run must still report to stdout"
    assert out_without != "", "the baseline-free control must still report to stdout"


# ---------------------------------------------------------------------------
# Behavior 4 -- regression / anti-mis-fix: symlink following is preserved
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("case", "spell_baseline", "spell_snapshot"),
    [
        ("byte-identical", "b.json", "b.json"),
        ("dot-slash", "b.json", "./b.json"),
        ("dot-dot", "b.json", "sub/../b.json"),
        ("valid-symlink", "link.json", "b.json"),
    ],
)
def test_b4_every_resolvable_aliasing_spelling_stays_refused(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    case: str,
    spell_baseline: str,
    spell_snapshot: str,
) -> None:
    """No symlink loop here -- these are the paths the OS CAN resolve.

    ``valid-symlink`` is the case an unconditional ``absolute()`` would silently
    stop refusing, which is why it is a named parameter rather than a footnote.
    """
    root = tmp_path / f"b4-{case}"
    root.mkdir(parents=True)
    _workspace(root)
    baseline = _valid_baseline(root)
    (root / "link.json").symlink_to(baseline)
    (root / "sub").mkdir()
    before = baseline.read_bytes()

    rc, out, err = _run(
        _run_argv(root, "--baseline", str(root / spell_baseline), "--snapshot", str(root / spell_snapshot)),
        capsys,
    )

    assert rc == 2, f"{case}: aliasing must stay a usage error; got rc={rc}\nstderr={err}"
    assert out == "", f"{case}: a usage error must write NOTHING to stdout; got {out!r}"
    assert ALIASED_WORDING in err, (
        f"{case}: the two spellings name ONE file, so the guard must still refuse them. "
        "A fix that compares un-resolved paths reopens the data-loss hole while leaving "
        f"the crash fixed. stderr:\n{err}"
    )
    assert "Traceback" not in err, f"{case}: no stacktrace may reach the operator:\n{err}"
    assert baseline.read_bytes() == before, f"{case}: the refusal must not touch the baseline"


def test_b4d_the_symlink_case_is_the_discriminator_for_the_plausible_mis_fix(
    tmp_path: Path,
) -> None:
    """MEASURE the stdlib fact that makes behavior 4's symlink case bite.

    Pure ``pathlib``, no product code: this documents WHY swapping ``resolve()``
    for ``absolute()`` is a real regression and not a style preference, so a
    future reader does not have to take the claim on faith.
    """
    baseline = _valid_baseline(tmp_path)
    link = tmp_path / "link.json"
    link.symlink_to(baseline)
    (tmp_path / "sub").mkdir()

    assert link.resolve() == baseline.resolve(), (
        "precondition: resolve() must see the symlink and its target as ONE file"
    )
    assert link.absolute() != baseline.absolute(), (
        "absolute() cannot see through a symlink, so a guard built on it would let the "
        "aliased pair through -- this is the regression behavior 4 catches"
    )
    assert (tmp_path / "sub" / ".." / "b.json").absolute() != baseline.absolute(), (
        "absolute() normalises nothing either, so the 'sub/../b.json' spelling would also "
        "slip past an absolute()-only comparison"
    )


# ---------------------------------------------------------------------------
# Behavior 5 -- the guard-not-applicable path is untouched
# ---------------------------------------------------------------------------


def test_b5_signals_owns_only_baseline_and_is_unaffected(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, ws, _baseline, loop = _hostile_case(tmp_path, "b5")

    rc, out, err = _run(["signals", "--workspace", str(ws), "--baseline", str(loop)], capsys)

    assert rc == 2, f"`signals` must still refuse an unreadable baseline; got rc={rc}\n{err}"
    assert out == "", f"a usage error must write NOTHING to stdout; got {out!r}"
    lines = _error_lines(err)
    assert len(lines) == 1, f"expected exactly ONE error line, got {len(lines)}: {lines!r}"
    assert lines[0].startswith("error: "), f"unexpected wording: {lines[0]!r}"
    assert "Traceback" not in err, f"no stacktrace may reach the operator:\n{err}"
    assert ALIASED_WORDING not in err, (
        "`signals` has no --snapshot, so the aliased-pair guard must not fire for it"
    )
    assert root is not None


# ---------------------------------------------------------------------------
# Behavior 6 -- the happy path is unchanged
# ---------------------------------------------------------------------------


def test_b6_the_happy_path_is_unchanged(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, _ws, baseline, _loop = _hostile_case(tmp_path, "b6")
    snapshot = root / "out.json"

    rc, out, err = _run(
        _run_argv(root, "--baseline", str(baseline), "--snapshot", str(snapshot)), capsys
    )

    assert rc == 0, f"a distinct, readable pair must succeed; got rc={rc}\nstderr={err}"
    assert out != "", "the run must report to stdout"
    assert err == "", f"the happy path must keep stderr empty; got {err!r}"
    assert snapshot.is_file(), "the run must have written the snapshot document"
    json.loads(snapshot.read_text(encoding="utf-8"))
