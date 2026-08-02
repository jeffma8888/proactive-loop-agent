"""Periodic scan trigger: the clock that makes proactivity *proactive*.

WHY this is a single tiny function and not a daemon/cron wrapper: the only thing
"being proactive on a schedule" adds over a one-shot scan is a timer, and a timer
worth testing must have its wait injected. Everything else (what a scan does,
where results go) already belongs to the CLI. Keeping the loop this small means
its one interesting property -- "scan_fn runs exactly N times" -- is trivially
verifiable with a fake ``sleep``.
"""

from __future__ import annotations

import time
from typing import Callable


def run_periodic(
    scan_fn: Callable[[], object],
    interval_sec: float,
    *,
    iterations: int | None = None,
    sleep: Callable[[float], object] = time.sleep,
    on_error: Callable[[int, Exception], None] | None = None,
) -> int:
    """Call *scan_fn* every *interval_sec* seconds, returning the number of scans.

    *iterations* ``None`` means run forever (the production case: a long-lived
    proactive watcher); a positive int bounds the run for tests and one-off
    batches. *sleep* is injected so tests can drive timing deterministically --
    a fake ``sleep`` that raises can also break an otherwise-infinite loop.

    The wait is placed BETWEEN scans, never after the final one: a bounded run of
    N iterations sleeps N-1 times, so it returns promptly instead of idling for a
    last, pointless interval.

    *on_error* makes the loop resilient by design (the product's L0 promise): when
    it is ``None`` (the default) any exception ``scan_fn`` raises PROPAGATES -- the
    exact prior contract, so every existing caller is unchanged. When provided, a
    single failing scan is isolated: ``on_error(scan_number, exc)`` is called with
    the 1-based number of the scan that raised and the exception instance, then the
    loop CONTINUES to the next tick, so one transient scan failure (e.g. an
    exhausted retry inside a long-lived watcher) can never tear down the whole run.
    Only ``Exception`` is caught, never ``BaseException``, so a
    ``KeyboardInterrupt``/``SystemExit`` still stops even a resilient loop; and the
    guard wraps ONLY ``scan_fn()``, never ``sleep()``, so a raising injected
    ``sleep`` can still break an otherwise-infinite loop.
    """
    count = 0
    while iterations is None or count < iterations:
        # Increment BEFORE the scan so a failing scan still counts as an attempt,
        # and the number handed to on_error matches the scan that raised.
        count += 1
        try:
            scan_fn()
        except Exception as exc:  # noqa: BLE001 - deliberate: isolate one failing scan
            # Resilient by design: with on_error set, one bad scan degrades the run
            # (surfaced via the hook) but never aborts a long-lived watcher; with no
            # hook the exact prior propagate contract is preserved. Exception, NOT
            # BaseException, so Ctrl-C / SystemExit still stop the loop.
            if on_error is None:
                raise
            on_error(count, exc)
        if iterations is not None and count >= iterations:
            break
        sleep(interval_sec)
    return count
