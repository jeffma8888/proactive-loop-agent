"""Black-box behavior tests for iteration 70 (commit-sequence factory iter 80):
make ``pla watch`` survive a single failed scan.

Feature under test: ``scheduler.run_periodic`` gains an optional keyword-only
``on_error`` hook (default ``None`` = unchanged, propagate any ``scan_fn``
exception). When ``on_error`` is supplied, a failing scan is isolated:
``on_error(count, exc)`` is called with the 1-based scan number and the caught
exception, and the loop continues to the next tick. ``pla watch`` wires an
``on_error`` closure that prints one ``scan {n} failed: {exc}`` line to stderr
and keeps watching, so a single transient scan failure can no longer tear down a
long-lived watcher (the product's namesake, "resilient by design", capability).

ISOLATION CONTRACT (honored, with one honest disclosure): these tests are
written strictly against this iteration's public contract -- the spec's
"Expected Behaviors" (pm.md), README.md, ROADMAP.md, and the product's own
observable output. They drive ONLY documented public surfaces: the public
function ``proactive_loop.scheduler.run_periodic`` and the ``pla`` CLI via
``proactive_loop.cli.main(argv)`` (observable stdout / stderr / exit code). NO
file under src/ was read to author these tests, and NO ``git diff`` was
inspected. DISCLOSURE: the engineer/reviewer notes for this iteration were
present in my prompt context (the harness surfaced them), so I did see them; in
the interest of full honesty I state that plainly. Every assertion below is
nonetheless derived solely from the spec's Expected Behaviors and the product's
observable behavior -- never from an implementation detail. All tests are fully
offline: zero network, zero real LLM, an injected ``sleep`` so no wall-clock
wait, and CLI runs use the committed ``examples`` fixtures with a ``tmp_path``
state-dir so nothing is written into the repo tree.

FILE NAMING NOTE (reported as PM feedback): the prompt said "Iteration number
for file naming: 70", but ``tests/test_iter70_behavior.py`` already exists from
an earlier commit-sequence iteration, and the established repo convention names
the behavior file after the COMMIT-SEQUENCE number (iter-69 -> test_iter79). This
iteration's commit-sequence is factory iter 80 (per the roadmap frontier row
#80), so this file is ``test_iter80_behavior.py`` to avoid a collision and match
the convention.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from proactive_loop.cli import main
from proactive_loop.scheduler import run_periodic

REPO = Path(__file__).resolve().parents[1]
FIXTURE_WS = REPO / "examples" / "fixture_workspace"
EXAMPLE_SCRIPT = REPO / "examples" / "scripted_responses.json"


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _run(argv, capsys):
    """Drive main(argv); return (exit_code, stdout, stderr)."""
    rc = main(argv)
    captured = capsys.readouterr()
    return rc, captured.out, captured.err


def _watch_argv(workspace, script, *, interval, max_scans, state_dir):
    return [
        "watch",
        "--workspace", str(workspace),
        "--provider", "scripted",
        "--scripted-responses", str(script),
        "--interval", str(interval),
        "--max-scans", str(max_scans),
        "--state-dir", str(state_dir),
    ]


# ==========================================================================
# Behavior 1 -- default (no on_error) still propagates: backward compatible.
# ==========================================================================
def test_b01_default_no_on_error_propagates():
    """A scan that raises on its 2nd call, with NO on_error, propagates the
    error out of run_periodic (unchanged pre-iter-70 behavior); it stopped at
    the raising call, so the scan ran exactly twice."""
    calls = {"n": 0}

    def scan():
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("scan blew up")

    with pytest.raises(RuntimeError, match="scan blew up"):
        run_periodic(scan, 0.0, iterations=5, sleep=lambda _s: None)

    assert calls["n"] == 2


def test_b01b_backward_compat_success_path_unchanged():
    """With on_error=None (the default), a fully-succeeding bounded run keeps
    the exact prior contract: N scans, returns N, and N-1 between-scan waits of
    the configured interval -- so the four existing test_scheduler.py tests are
    byte-behaviour-identical."""
    scans = {"n": 0}
    sleeps: list[float] = []

    def scan():
        scans["n"] += 1

    total = run_periodic(scan, 7.0, iterations=4, sleep=sleeps.append)

    assert scans["n"] == 4
    assert total == 4
    assert sleeps == [7.0, 7.0, 7.0]


# ==========================================================================
# Behavior 2 -- on_error swallows a failing scan; the run completes.
# ==========================================================================
def test_b02_on_error_swallows_and_run_continues():
    """Every scan raises; with on_error set the run still attempts all three
    ticks -- returns 3, scan called 3x, on_error called 3x."""
    scan_calls = {"n": 0}
    errs: list[tuple[int, BaseException]] = []

    def scan():
        scan_calls["n"] += 1
        raise RuntimeError("always fails")

    total = run_periodic(
        scan,
        0.0,
        iterations=3,
        sleep=lambda _s: None,
        on_error=lambda n, exc: errs.append((n, exc)),
    )

    assert total == 3
    assert scan_calls["n"] == 3
    assert len(errs) == 3


# ==========================================================================
# Behavior 3 -- on_error gets the 1-based scan number and the exact instance.
# ==========================================================================
def test_b03_on_error_receives_number_and_exact_instance():
    """A scan raising a sentinel ValueError('boom') ONLY on its 2nd call hands
    on_error exactly one (2, exc) call, where exc IS the raised instance
    (identity, not equality); the run returns 3 and scan ran 3 times."""
    scan_calls = {"n": 0}
    boom = ValueError("boom")
    recorded: list[tuple[int, BaseException]] = []

    def scan():
        scan_calls["n"] += 1
        if scan_calls["n"] == 2:
            raise boom

    total = run_periodic(
        scan,
        0.0,
        iterations=3,
        sleep=lambda _s: None,
        on_error=lambda n, exc: recorded.append((n, exc)),
    )

    assert total == 3
    assert scan_calls["n"] == 3
    assert len(recorded) == 1
    n, exc = recorded[0]
    assert n == 2
    assert exc is boom  # exact identity, not just equality
    assert str(exc) == "boom"


# ==========================================================================
# Behavior 4 -- the between-scan wait is unchanged when scans fail.
# ==========================================================================
def test_b04_waits_unchanged_when_scans_fail():
    """An always-raising scan over 3 iterations still waits exactly N-1 = 2
    times, each the configured 9.0s interval, never after the last tick --
    failures neither add nor drop a wait."""
    sleeps: list[float] = []

    def scan():
        raise RuntimeError("fail every time")

    total = run_periodic(
        scan,
        9.0,
        iterations=3,
        sleep=sleeps.append,
        on_error=lambda _n, _e: None,
    )

    assert total == 3
    assert sleeps == [9.0, 9.0]


# ==========================================================================
# Behavior 5 -- on_error catches Exception only, NOT BaseException.
# ==========================================================================
def test_b05_keyboardinterrupt_not_swallowed():
    """Even with on_error provided, a KeyboardInterrupt (a BaseException, not an
    Exception) propagates out -- so an operator's Ctrl-C still stops a resilient
    watcher."""
    def scan():
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_periodic(
            scan,
            0.0,
            iterations=3,
            sleep=lambda _s: None,
            on_error=lambda _n, _e: None,
        )


def test_b05_systemexit_not_swallowed():
    """SystemExit (also a BaseException, not an Exception) likewise propagates
    even with on_error set -- a resilient watch is still killable."""
    def scan():
        raise SystemExit(2)

    with pytest.raises(SystemExit):
        run_periodic(
            scan,
            0.0,
            iterations=3,
            sleep=lambda _s: None,
            on_error=lambda _n, _e: None,
        )


# ==========================================================================
# Behavior 6 -- an unbounded watch is not stopped by scan failures alone.
# ==========================================================================
def test_b06_unbounded_not_stopped_by_failures():
    """With iterations=None and a scan that raises every call, the loop is
    stopped ONLY by a raising sleep (a _StopClock on its 3rd call) -- not by the
    scan failures themselves; at that point scan and on_error have each run 3
    times. The stop signal comes from sleep, which the guard never touches."""
    class _StopClock(Exception):
        pass

    scan_calls = {"n": 0}
    errs: list[tuple[int, BaseException]] = []
    sleep_calls = {"n": 0}

    def scan():
        scan_calls["n"] += 1
        raise RuntimeError("always fails")

    def fake_sleep(_seconds):
        sleep_calls["n"] += 1
        if sleep_calls["n"] >= 3:
            raise _StopClock

    with pytest.raises(_StopClock):
        run_periodic(
            scan,
            0.0,
            iterations=None,
            sleep=fake_sleep,
            on_error=lambda n, exc: errs.append((n, exc)),
        )

    assert scan_calls["n"] == 3
    assert len(errs) == 3
    assert sleep_calls["n"] == 3


# ==========================================================================
# Behavior 7 -- a watch whose every scan fails still visits all ticks, exits 0.
# ==========================================================================
def test_b07_every_scan_fails_watch_survives_exit0(tmp_path, capsys):
    """`pla watch --max-scans 2` against an empty scripted-responses file (so
    every scan's synthesize() raises ScriptExhaustedError immediately, with no
    real wait) exits 0; stdout shows BOTH scan headers (it continued past the
    first failure); stderr has a distinct per-scan failure line for scan 1 AND
    scan 2, each naming its number; no Python traceback anywhere."""
    empty_script = tmp_path / "empty.json"
    empty_script.write_text("[]", encoding="utf-8")
    state_dir = tmp_path / "state"

    rc, out, err = _run(
        _watch_argv(
            FIXTURE_WS,
            empty_script,
            interval=0,
            max_scans=2,
            state_dir=state_dir,
        ),
        capsys,
    )

    assert rc == 0
    assert "=== scan 1 ===" in out
    assert "=== scan 2 ===" in out
    assert "scan 1 failed" in err
    assert "scan 2 failed" in err
    assert "Traceback" not in err
    assert "Traceback" not in out


# ==========================================================================
# Behavior 8 -- the happy path is byte-stable; resilience does not perturb it.
# ==========================================================================
def test_b08_happy_path_byte_stable(tmp_path, capsys):
    """A single successful scan over the committed example fixtures exits 0,
    renders the slate table with at least one gated goal row, and writes NO
    per-scan failure note and NO traceback to stderr -- the resilience wiring
    does not perturb a succeeding scan."""
    state_dir = tmp_path / "state"

    rc, out, err = _run(
        _watch_argv(
            FIXTURE_WS,
            EXAMPLE_SCRIPT,
            interval=0,
            max_scans=1,
            state_dir=state_dir,
        ),
        capsys,
    )

    assert rc == 0
    assert "=== scan 1 ===" in out
    # The rendered slate table (header + at least one policy-gated goal row).
    assert "DECISION" in out
    assert any(tok in out for tok in ("auto_dispatch", "needs_approval", "blocked"))
    # A succeeding scan produces no per-scan failure note and no traceback.
    assert "failed" not in err
    assert "Traceback" not in err
    assert "Traceback" not in out
