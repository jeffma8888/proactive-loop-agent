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
) -> int:
    """Call *scan_fn* every *interval_sec* seconds, returning the number of scans.

    *iterations* ``None`` means run forever (the production case: a long-lived
    proactive watcher); a positive int bounds the run for tests and one-off
    batches. *sleep* is injected so tests can drive timing deterministically --
    a fake ``sleep`` that raises can also break an otherwise-infinite loop.

    The wait is placed BETWEEN scans, never after the final one: a bounded run of
    N iterations sleeps N-1 times, so it returns promptly instead of idling for a
    last, pointless interval.
    """
    count = 0
    while iterations is None or count < iterations:
        scan_fn()
        count += 1
        if iterations is not None and count >= iterations:
            break
        sleep(interval_sec)
    return count
