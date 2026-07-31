"""Black-box behavior tests for iteration 38 --- parse-time validation of
``pla watch``'s two numeric knobs, ``--interval`` and ``--max-scans``.

Feature under test (SPEC section 4.5, ``pm.md``): ``watch`` is the product's
namesake proactive loop --- the one verb a person leaves running unattended ---
yet its ``--interval`` / ``--max-scans`` were the last two front-door numeric
args NOT guarded at parse time. This iteration closes both:

  * ``--interval`` is validated **non-negative** at parse time (``>= 0``; ``0``
    stays legal so offline tests drive ``watch`` with a bounded ``--max-scans``
    and no real wait). A negative interval is now an argparse usage error
    (exit 2) BEFORE any client/collect/render --- it no longer half-runs then
    leaks ``time.sleep``'s builtin ``sleep length must be non-negative`` errno
    string on the second tick.
  * ``--max-scans`` is validated a **positive int** (``>= 1``), reusing the
    iter-27 ``_positive_int`` validator. ``0`` / ``-1`` are now usage errors
    (exit 2) --- they no longer silently run zero scans and REPORT success
    (exit 0).

Every valid input behaves exactly as before (additive, backward-compatible;
``__version__`` stays ``0.1.1``).

ISOLATION CONTRACT (honored): these tests are written strictly against the
public contract for this iteration --- the spec's "Expected Behaviors"
(``pm.md``), ``README.md``, and ``SPEC.md`` section 4.5 --- and drive ONLY
documented public surfaces: the ``pla`` CLI via
``proactive_loop.cli.main(argv) -> int`` (its observable stdout / stderr /
exit codes / on-disk artifacts) and the public ``build_parser()`` for the
parser-level defaults check the spec authorizes. **No file under ``src/`` was
read, no engineer/reviewer notes were read, and no ``git diff`` was consulted.**
Every test is fully offline: zero network, zero API keys, driven through the
scripted provider seam. Synthetic ``tmp_path`` workspaces are used throughout
(never the in-repo tree), so the git / working_tree / test_posture collectors
cannot leak repo state (iter-15 lesson), and no ``watch`` is EVER invoked
without a bounded, VALID ``--max-scans`` on a happy path (an unbounded run
would hang the suite).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from proactive_loop.cli import build_parser, main


# ---------------------------------------------------------------------------
# Helpers --- all black-box: build a synthetic workspace + scripted script,
# drive main(), read back stdout / stderr / exit code / on-disk artifacts.
# (Mirrors tests/test_iter18_behavior.py conventions.)
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
        "rationale": "black-box iter38 watch-guard probe",
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
    responses (the scout consumes exactly one synthesize response per scan, so
    a ``--max-scans N`` run needs at least N of them). Each body is a 1-goal
    JSON array. Per iter-36, every entry is an object carrying ``text``."""
    responses = [
        {"tag": "synthesize", "text": json.dumps([_goal_dict(f"iter38 goal {i}")])}
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
    interval: str,
    max_scans: str,
) -> list[str]:
    """A fully-specified ``watch`` argv. Both numeric knobs are always passed
    explicitly so each test isolates exactly the value under test."""
    return [
        "watch",
        "--provider", "scripted",
        "--scripted-responses", str(script),
        "--state-dir", str(state_dir),
        "--workspace", str(ws),
        "--interval", interval,
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
    main()'s try-boundary (same mechanism iter-27 ``--top`` / iter-18 ``test_b06``
    rely on). Returns (exit_code, stdout, stderr)."""
    with pytest.raises(SystemExit) as excinfo:
        main(argv)
    cap = capsys.readouterr()
    code = excinfo.value.code
    return (code if isinstance(code, int) else 1), cap.out, cap.err


def _header_count(out: str) -> int:
    return out.count("=== scan ")


# ===========================================================================
# Behavior 1 --- Negative interval is rejected at PARSE time with NO side
# effects: exit 2 (not 1), no scan ran, stderr says "non-negative", and the
# old leaked-builtin "sleep length must be non-negative" message is GONE.
# ===========================================================================


def test_b01_negative_interval_rejected_at_parse_time_no_side_effects(tmp_path, capsys):
    ws = _workspace(tmp_path)
    script = _script(tmp_path, 2)

    rc, out, err = _run_usage_error(
        _argv(ws, script, tmp_path / "state", interval="-5", max_scans="2"),
        capsys,
    )

    # A parse-time USAGE error (exit 2), NOT the old exit-1 runtime crash.
    assert rc == 2, f"negative --interval must exit 2 (parse-time), got {rc}; stderr={err!r}"
    # Zero scans ran: no tick header ever reached stdout.
    assert _header_count(out) == 0, f"no scan may run on rejection; stdout=\n{out}"
    assert "=== scan 1 ===" not in out, out
    # The rejection is actionable and names the constraint.
    assert "non-negative" in err, f"stderr must explain the non-negative rule; got:\n{err}"
    # The old leaked builtin errno string must be gone (that was the defect).
    assert "sleep length must be non-negative" not in err, (
        f"the leaked time.sleep builtin message must NOT appear; got:\n{err}"
    )


# ===========================================================================
# Behavior 2 --- `--interval 0` stays legal (load-bearing regression guard):
# exit 0, exactly two ordered scan headers. The guard MUST be `>= 0`.
# ===========================================================================


def test_b02_interval_zero_stays_legal_two_scans(tmp_path, capsys):
    ws = _workspace(tmp_path)
    script = _script(tmp_path, 2)

    rc, out, err = _run_ok(
        _argv(ws, script, tmp_path / "state", interval="0", max_scans="2"),
        capsys,
    )

    assert rc == 0, f"--interval 0 must stay legal (exit 0); stderr={err!r}"
    assert "=== scan 1 ===" in out and "=== scan 2 ===" in out, out
    assert _header_count(out) == 2, f"exactly two scans expected; stdout=\n{out}"
    assert out.index("=== scan 1 ===") < out.index("=== scan 2 ==="), out


# ===========================================================================
# Behavior 3 --- A positive fractional interval is accepted: exit 0, one scan.
# (With --max-scans 1 there is no sleep, so no real wait occurs.)
# ===========================================================================


def test_b03_positive_fractional_interval_accepted_one_scan(tmp_path, capsys):
    ws = _workspace(tmp_path)
    script = _script(tmp_path, 1)

    rc, out, err = _run_ok(
        _argv(ws, script, tmp_path / "state", interval="3.5", max_scans="1"),
        capsys,
    )

    assert rc == 0, f"positive fractional --interval must be accepted; stderr={err!r}"
    assert "=== scan 1 ===" in out, out
    assert _header_count(out) == 1, f"exactly one scan expected; stdout=\n{out}"
    assert "=== scan 2 ===" not in out, out


# ===========================================================================
# Behavior 4 --- Non-numeric interval stays an exit-2 usage error (regression
# guard). Exact stderr wording is NOT asserted --- only the parse-time exit-2.
# ===========================================================================


def test_b04_non_numeric_interval_is_usage_error_exit2(tmp_path, capsys):
    ws = _workspace(tmp_path)
    script = _script(tmp_path, 1)

    rc, out, err = _run_usage_error(
        _argv(ws, script, tmp_path / "state", interval="abc", max_scans="1"),
        capsys,
    )

    assert rc == 2, f"non-numeric --interval must exit 2; got {rc}; stderr={err!r}"
    assert _header_count(out) == 0, f"no scan may run on rejection; stdout=\n{out}"


# ===========================================================================
# Behavior 5 --- Zero / negative --max-scans is rejected at parse time: exit 2,
# no scan ran, stderr says "positive integer". (Was a silent zero-scan exit 0.)
# ===========================================================================


@pytest.mark.parametrize("bad", ["0", "-1"])
def test_b05_zero_or_negative_max_scans_rejected_at_parse_time(bad, tmp_path, capsys):
    ws = _workspace(tmp_path)
    script = _script(tmp_path, 2)

    rc, out, err = _run_usage_error(
        _argv(ws, script, tmp_path / "state", interval="0", max_scans=bad),
        capsys,
    )

    assert rc == 2, f"--max-scans {bad} must exit 2 (parse-time), got {rc}; stderr={err!r}"
    assert _header_count(out) == 0, (
        f"--max-scans {bad} must run zero scans on rejection (not silently no-op "
        f"with exit 0); stdout=\n{out}"
    )
    assert "positive integer" in err, (
        f"stderr must explain the positive-integer rule; got:\n{err}"
    )


# ===========================================================================
# Behavior 6 --- Non-integer --max-scans stays an exit-2 usage error
# (regression guard; preserves iter-18 test_b06).
# ===========================================================================


def test_b06_non_integer_max_scans_is_usage_error_exit2(tmp_path, capsys):
    ws = _workspace(tmp_path)
    script = _script(tmp_path, 1)

    rc, out, err = _run_usage_error(
        _argv(ws, script, tmp_path / "state", interval="0", max_scans="not-an-int"),
        capsys,
    )

    assert rc == 2, f"non-integer --max-scans must exit 2; got {rc}; stderr={err!r}"
    assert _header_count(out) == 0, f"no scan may run on rejection; stdout=\n{out}"


# ===========================================================================
# Behavior 7 --- Omitted numeric args preserve the unbounded/hourly production
# defaults (regression guard; preserves iter-18 test_b05). Non-string argparse
# defaults bypass the `type=` validators entirely.
# ===========================================================================


def test_b07_omitted_numeric_args_preserve_defaults():
    parser = build_parser()
    args = parser.parse_args(["watch", "--workspace", "."])

    # Omitted --max-scans -> unbounded (run until interrupted).
    assert args.max_scans is None
    # Omitted --interval -> hourly, as a float (default bypasses the validator).
    assert args.interval == 3600.0
    assert isinstance(args.interval, float)


# ===========================================================================
# Behavior 8 --- A valid bounded run remains a live monitor (regression guard):
# it writes NO slate file into --state-dir and prints no `slate written:`
# trailer. watch's ephemeral-view contract (iter-18) is unchanged by this
# feature.
# ===========================================================================


def test_b08_valid_bounded_run_writes_no_slate_file(tmp_path, capsys):
    ws = _workspace(tmp_path)
    script = _script(tmp_path, 1)
    state_dir = tmp_path / "fresh_state"  # deliberately fresh + empty

    rc, out, err = _run_ok(
        _argv(ws, script, state_dir, interval="0", max_scans="1"),
        capsys,
    )

    assert rc == 0, f"a valid bounded watch must exit 0; stderr={err!r}"
    # No slate.json persisted anywhere under the state dir (recursively).
    slates = list(state_dir.rglob("slate.json")) if state_dir.exists() else []
    assert slates == [], f"watch must not persist a slate; found {slates}"
    # And it never prints the scan-only trailer.
    assert "slate written:" not in out, out
