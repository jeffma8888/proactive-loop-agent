"""Tests for the periodic scan trigger.

The scheduler's only interesting behavior is timing, so every test injects a
fake ``sleep`` and asserts on call counts -- never on the wall clock. Two shapes
are covered: a bounded run (exactly N scans, N-1 waits, correct interval) and an
otherwise-infinite run that a raising ``sleep`` breaks after N scans.
"""

from __future__ import annotations

import pytest

from proactive_loop.scheduler import run_periodic


def test_fixed_iterations_scans_exactly_n_times():
    """iterations=N -> scan_fn runs exactly N times and returns N."""
    scans = 0
    sleeps: list[float] = []

    def scan() -> None:
        nonlocal scans
        scans += 1

    total = run_periodic(scan, 7.0, iterations=4, sleep=sleeps.append)

    assert scans == 4
    assert total == 4
    # The wait sits BETWEEN scans, so a 4-iteration run sleeps 3 times, each
    # for the requested interval -- and never after the final scan.
    assert sleeps == [7.0, 7.0, 7.0]


def test_single_iteration_never_sleeps():
    """A one-shot bounded run performs one scan and no waiting at all."""
    calls: list[float] = []
    scans = 0

    def scan() -> None:
        nonlocal scans
        scans += 1

    total = run_periodic(scan, 30.0, iterations=1, sleep=calls.append)

    assert scans == 1
    assert total == 1
    assert calls == []


def test_forever_runs_until_sleep_raises():
    """iterations=None loops forever; a raising fake sleep bounds it for the test."""

    class _StopClock(Exception):
        pass

    scans = 0
    sleep_calls = 0

    def scan() -> None:
        nonlocal scans
        scans += 1

    def fake_sleep(_seconds: float) -> None:
        nonlocal sleep_calls
        sleep_calls += 1
        if sleep_calls >= 3:  # break the otherwise-infinite loop deterministically
            raise _StopClock

    with pytest.raises(_StopClock):
        run_periodic(scan, 5.0, iterations=None, sleep=fake_sleep)

    # scan, sleep, scan, sleep, scan, sleep(raises) -> exactly 3 scans.
    assert scans == 3
    assert sleep_calls == 3


def test_forever_passes_interval_to_sleep():
    """The configured interval is what gets handed to sleep on each wait."""

    class _StopClock(Exception):
        pass

    intervals: list[float] = []

    def fake_sleep(seconds: float) -> None:
        intervals.append(seconds)
        if len(intervals) >= 2:
            raise _StopClock

    with pytest.raises(_StopClock):
        run_periodic(lambda: None, 12.5, iterations=None, sleep=fake_sleep)

    assert intervals == [12.5, 12.5]
