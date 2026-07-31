"""Black-box behavior tests for iteration 40 --- hardening ``pla watch``'s
``--interval`` parse-time validator (``_non_negative_float``) to reject
**non-finite** floats (``nan`` / ``inf`` / ``-inf``) with a ``SystemExit(2)``
usage error and ZERO side effects.

Feature under test (SPEC section 4.5, ``pm.md`` iter-40): the iter-38 guard
validated ``--interval`` as ``>= 0`` but let non-finite floats slip through
(``float("nan") < 0.0`` and ``float("inf") < 0.0`` are both ``False``), so a
fat-fingered ``--interval nan`` / ``inf`` rendered scan #1's full slate (a side
effect) and THEN detonated downstream in ``scheduler.run_periodic``'s
``time.sleep``, leaking a raw Python builtin string. This iteration closes that
subset: the validator now applies a **finite check placed BEFORE the ``< 0.0``
check**, so non-finite input is rejected at parse time (argparse exit 2) with
zero scans, and the finite-negative / non-numeric / ``0`` / positive-fractional
cases behave exactly as the iter-38 contract promised (additive, backward
compatible; ``__version__`` stays ``0.1.1``).

ISOLATION CONTRACT (honored): these tests are written strictly against this
iteration's PUBLIC contract --- the spec's "Expected Behaviors" (``pm.md``),
``README.md``, and ``SPEC.md`` section 4.5 --- and drive ONLY documented public
surfaces: the ``pla`` CLI via ``proactive_loop.cli.main(argv) -> int`` (its
observable stdout / stderr / exit code / on-disk artifacts) and the public
``build_parser()`` for the parser-default check the spec authorizes. **No file
under ``src/`` was read, no engineer or reviewer notes were read, and no
``git diff`` was consulted.** Every test is fully offline: zero network, zero
API keys, driven through the scripted-provider seam, on synthetic ``tmp_path``
workspaces (never the in-repo tree, so the git / working_tree / test_posture
collectors cannot leak repo state --- iter-15 lesson). Every ``watch`` argv
passes an explicit, VALID ``--max-scans`` so no test can hang on an unbounded
run.

AMBIGUITY NOTE (behavior 3, valuable PM feedback): the spec writes behavior 3 as
"Same argv with ``--interval -inf``", i.e. the two-token form
``["--interval", "-inf"]``. But ``-inf`` does NOT match argparse's
``_negative_number_matcher`` (``^-\\d+$|^-\\d*\\.\\d+$``), so argparse classifies
``-inf`` as an (unknown) *option string*, refuses to consume it as
``--interval``'s value, and errors ``argument --interval: expected one argument``
BEFORE ``_non_negative_float`` ever runs. That is still ``SystemExit(2)`` with
zero side effects, but its stderr does NOT contain ``finite`` --- because the
validator is never reached. The only argv form that routes a ``-inf`` *string*
to the validator (and therefore exercises the spec's real intent: that the
finite check fires BEFORE the ``< 0.0`` check) is the ``=``-joined single token
``--interval=-inf``. So ``test_b03_*`` asserts the intent via ``--interval=-inf``
(reaches the validator, stderr says ``finite``), and ``test_b03b_*`` documents
the two-token interception (exit 2 / zero side effects, but no ``finite``). This
was verified empirically against the real CLI before writing the tests.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from proactive_loop.cli import build_parser, main


# ---------------------------------------------------------------------------
# Helpers --- all black-box: build a synthetic workspace + scripted script,
# drive main(), read back stdout / stderr / exit code / on-disk artifacts.
# (Mirrors tests/test_iter38_behavior.py conventions exactly.)
# ---------------------------------------------------------------------------


def _workspace(tmp_path: Path) -> Path:
    """A minimal, real, synthetic workspace directory (one source file)."""
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "foo.py").write_text("print('hi')\n", encoding="utf-8")
    return ws


def _goal_dict(title: str) -> dict:
    """One goal dict matching the documented synthesize JSON contract
    (examples/scripted_responses.json shape); ``learning`` is non-sensitive so
    it renders cleanly in the gated table."""
    return {
        "title": title,
        "rationale": "black-box iter40 non-finite-interval probe",
        "category": "learning",
        "impact": 5.0,
        "urgency": 5.0,
        "confidence": 1.0,
        "effort_weight": 1.0,
        "appropriate_now": True,
        "sources": ["foo.py"],
        "suggested_first_steps": ["do a thing"],
    }


def _script(tmp_path: Path, n: int, *, name: str = "script.json") -> Path:
    """Write a scripted-responses file with ``n`` distinct ``synthesize``
    responses (the scout consumes exactly one synthesize response per scan, so a
    ``--max-scans N`` run needs at least N of them). Each body is a 1-goal JSON
    array. Per iter-36, every entry is an object carrying ``text``."""
    responses = [
        {"tag": "synthesize", "text": json.dumps([_goal_dict(f"iter40 goal {i}")])}
        for i in range(1, n + 1)
    ]
    path = tmp_path / name
    path.write_text(json.dumps({"responses": responses}), encoding="utf-8")
    return path


def _argv(
    ws: Path,
    script: Path,
    state_dir: Path,
    *,
    interval_tokens: list[str],
    max_scans: str,
) -> list[str]:
    """A fully-specified ``watch`` argv. ``interval_tokens`` is the literal
    interval fragment (e.g. ``["--interval", "nan"]`` or the ``=``-joined
    ``["--interval=-inf"]``); ``--max-scans`` is ALWAYS an explicit valid value
    so no test can hang on an unbounded run."""
    return [
        "watch",
        "--provider", "scripted",
        "--scripted-responses", str(script),
        "--state-dir", str(state_dir),
        "--workspace", str(ws),
        *interval_tokens,
        "--max-scans", max_scans,
    ]


def _run_ok(argv: list[str], capsys) -> tuple[int, str, str]:
    """Drive main() expecting a normal return (valid inputs). Returns
    (exit_code, stdout, stderr)."""
    rc = main(argv)
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def _run_usage_error(argv: list[str], capsys) -> tuple[int, str, str]:
    """Drive main() expecting an argparse PARSE-TIME usage error. A ``type=``
    validator failure raises ``SystemExit(2)`` inside ``parse_args`` --- OUTSIDE
    main()'s try-boundary (the iter-38 / iter-27 pattern). Returns
    (exit_code, stdout, stderr)."""
    with pytest.raises(SystemExit) as excinfo:
        main(argv)
    cap = capsys.readouterr()
    code = excinfo.value.code
    return (code if isinstance(code, int) else 1), cap.out, cap.err


def _header_count(out: str) -> int:
    return out.count("=== scan ")


# ===========================================================================
# Behavior 1 --- `--interval nan` is rejected at PARSE time with NO side
# effects: exit 2, zero scan headers (scan #1 must NOT render), stderr names
# `finite`, and the previously-leaked builtin `Invalid value NaN` + any
# `Traceback` are GONE.
# ===========================================================================


def test_b01_nan_interval_rejected_at_parse_time_no_side_effects(tmp_path, capsys):
    ws = _workspace(tmp_path)
    script = _script(tmp_path, 2)

    rc, out, err = _run_usage_error(
        _argv(ws, script, tmp_path / "state", interval_tokens=["--interval", "nan"], max_scans="2"),
        capsys,
    )

    assert rc == 2, f"--interval nan must exit 2 (parse-time), got {rc}; stderr={err!r}"
    # Zero side effects: scan #1 must NOT render before the guard fires.
    assert _header_count(out) == 0, f"no scan may run on rejection; stdout=\n{out}"
    assert "=== scan 1 ===" not in out, out
    # The rejection names the finite constraint.
    assert "finite" in err, f"stderr must explain the finite rule; got:\n{err}"
    # The old leaked builtin string and any traceback must be gone (the defect).
    assert "Invalid value NaN" not in err, (
        f"the leaked time.sleep builtin 'Invalid value NaN' must NOT appear; got:\n{err}"
    )
    assert "Traceback" not in err, f"no traceback may leak on rejection; got:\n{err}"


# ===========================================================================
# Behavior 2 --- `--interval inf` is rejected at parse time with no side
# effects: exit 2, zero scan headers, stderr names `finite`, and the old
# `OverflowError`-flavored traceback path is gone.
# ===========================================================================


def test_b02_inf_interval_rejected_at_parse_time_no_side_effects(tmp_path, capsys):
    ws = _workspace(tmp_path)
    script = _script(tmp_path, 2)

    rc, out, err = _run_usage_error(
        _argv(ws, script, tmp_path / "state", interval_tokens=["--interval", "inf"], max_scans="2"),
        capsys,
    )

    assert rc == 2, f"--interval inf must exit 2 (parse-time), got {rc}; stderr={err!r}"
    assert _header_count(out) == 0, f"no scan may run on rejection; stdout=\n{out}"
    assert "=== scan 1 ===" not in out, out
    assert "finite" in err, f"stderr must explain the finite rule; got:\n{err}"
    assert "Traceback" not in err, f"no traceback may leak on rejection; got:\n{err}"


# ===========================================================================
# Behavior 3 --- `--interval=-inf` is reported as non-finite: the finite check
# fires BEFORE the `< 0.0` check, so `-inf` is rejected as NON-FINITE (stderr
# names `finite`), not merely as negative. Uses the `=`-joined form because the
# two-token form never reaches the validator (see module AMBIGUITY NOTE +
# test_b03b). Pins the ordering the spec calls out.
# ===========================================================================


def test_b03_negative_inf_interval_reported_as_non_finite(tmp_path, capsys):
    ws = _workspace(tmp_path)
    script = _script(tmp_path, 2)

    rc, out, err = _run_usage_error(
        _argv(ws, script, tmp_path / "state", interval_tokens=["--interval=-inf"], max_scans="2"),
        capsys,
    )

    assert rc == 2, f"--interval=-inf must exit 2 (parse-time), got {rc}; stderr={err!r}"
    assert _header_count(out) == 0, f"no scan may run on rejection; stdout=\n{out}"
    assert "=== scan 1 ===" not in out, out
    # Ordering pin: -inf is rejected as NON-FINITE (finite check runs first),
    # NOT via the `< 0.0` finite-negative branch (which says "non-negative").
    assert "finite" in err, (
        f"-inf must be rejected as non-finite (finite check before < 0.0); got:\n{err}"
    )


# ===========================================================================
# Behavior 3b (PM feedback / ambiguity documentation) --- the LITERAL two-token
# `--interval -inf` from the spec text is intercepted by argparse's own
# argument-consumption BEFORE the validator (because "-inf" fails argparse's
# negative-number regex), so it is still exit 2 with ZERO side effects, but its
# stderr does NOT contain `finite`. Documents that both `-inf` forms are safe
# (no half-run, no leaked builtin), just via different mechanisms.
# ===========================================================================


def test_b03b_two_token_negative_inf_is_exit2_zero_side_effects(tmp_path, capsys):
    ws = _workspace(tmp_path)
    script = _script(tmp_path, 2)

    rc, out, err = _run_usage_error(
        _argv(ws, script, tmp_path / "state", interval_tokens=["--interval", "-inf"], max_scans="2"),
        capsys,
    )

    # Still a clean parse-time usage error with zero side effects...
    assert rc == 2, f"two-token --interval -inf must exit 2; got {rc}; stderr={err!r}"
    assert _header_count(out) == 0, f"no scan may run on rejection; stdout=\n{out}"
    assert "=== scan 1 ===" not in out, out
    # ...and it must never half-run then leak a raw builtin/traceback.
    assert "Traceback" not in err, f"no traceback may leak; got:\n{err}"
    assert "Invalid value NaN" not in err, err


# ===========================================================================
# Behavior 4 --- Regression: a finite NEGATIVE interval keeps the UNCHANGED
# iter-38 message. `--interval -5` -> exit 2, zero scans, stderr says
# `non-negative` and does NOT say `finite` (proves the new finite branch does
# not swallow the finite-negative case, and the negative branch's exact message
# is untouched).
# ===========================================================================


def test_b04_finite_negative_interval_keeps_iter38_message(tmp_path, capsys):
    ws = _workspace(tmp_path)
    script = _script(tmp_path, 2)

    rc, out, err = _run_usage_error(
        _argv(ws, script, tmp_path / "state", interval_tokens=["--interval", "-5"], max_scans="2"),
        capsys,
    )

    assert rc == 2, f"--interval -5 must exit 2 (parse-time), got {rc}; stderr={err!r}"
    assert _header_count(out) == 0, f"no scan may run on rejection; stdout=\n{out}"
    assert "non-negative" in err, f"finite-negative must keep the non-negative message; got:\n{err}"
    assert "finite" not in err, (
        f"a finite negative must NOT be reported as non-finite (branch mixup); got:\n{err}"
    )


# ===========================================================================
# Behavior 5 --- Regression: a non-numeric interval stays an exit-2 usage error.
# `--interval abc` -> exit 2, zero scans. (Exact wording not asserted.)
# ===========================================================================


def test_b05_non_numeric_interval_is_usage_error_exit2(tmp_path, capsys):
    ws = _workspace(tmp_path)
    script = _script(tmp_path, 1)

    rc, out, err = _run_usage_error(
        _argv(ws, script, tmp_path / "state", interval_tokens=["--interval", "abc"], max_scans="1"),
        capsys,
    )

    assert rc == 2, f"non-numeric --interval must exit 2; got {rc}; stderr={err!r}"
    assert _header_count(out) == 0, f"no scan may run on rejection; stdout=\n{out}"


# ===========================================================================
# Behavior 6 --- Regression: `--interval 0` stays legal (load-bearing offline
# test-drive knob). exit 0, exactly two ordered scan headers.
# ===========================================================================


def test_b06_interval_zero_stays_legal_two_ordered_scans(tmp_path, capsys):
    ws = _workspace(tmp_path)
    script = _script(tmp_path, 2)

    rc, out, err = _run_ok(
        _argv(ws, script, tmp_path / "state", interval_tokens=["--interval", "0"], max_scans="2"),
        capsys,
    )

    assert rc == 0, f"--interval 0 must stay legal (exit 0); stderr={err!r}"
    assert "=== scan 1 ===" in out and "=== scan 2 ===" in out, out
    assert _header_count(out) == 2, f"exactly two scans expected; stdout=\n{out}"
    assert out.index("=== scan 1 ===") < out.index("=== scan 2 ==="), out


# ===========================================================================
# Behavior 7 --- Regression: a valid POSITIVE FRACTIONAL interval is accepted.
# `--interval 3.5 --max-scans 1` -> exit 0, exactly one scan. (max-scans 1 => no
# sleep => no real wait.)
# ===========================================================================


def test_b07_positive_fractional_interval_accepted_one_scan(tmp_path, capsys):
    ws = _workspace(tmp_path)
    script = _script(tmp_path, 1)

    rc, out, err = _run_ok(
        _argv(ws, script, tmp_path / "state", interval_tokens=["--interval", "3.5"], max_scans="1"),
        capsys,
    )

    assert rc == 0, f"positive fractional --interval must be accepted; stderr={err!r}"
    assert "=== scan 1 ===" in out, out
    assert _header_count(out) == 1, f"exactly one scan expected; stdout=\n{out}"
    assert "=== scan 2 ===" not in out, out


# ===========================================================================
# Behavior 8 --- Regression: omitting `--interval` preserves the hourly
# production default (the non-string default bypasses the `type=` validator, so
# the "run forever, hourly" default is unchanged).
# ===========================================================================


def test_b08_omitted_interval_preserves_hourly_default():
    parser = build_parser()
    args = parser.parse_args(["watch", "--workspace", "."])

    assert args.interval == 3600.0, f"omitted --interval must default to 3600.0; got {args.interval!r}"
    assert isinstance(args.interval, float), f"the default must be a float; got {type(args.interval)}"
