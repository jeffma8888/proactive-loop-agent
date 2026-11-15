"""Behaviour oracle for factory iter 327 (ROADMAP #363): L0 backoff saturates at the cap.

``_backoff_delay`` must bound the *computation* by ``max_backoff_sec``, not just the
result: an exponent large enough to overflow a float (``base * factor ** (attempt-1)``)
saturates at the cap instead of raising ``OverflowError`` out of the retry layer.

1. default policy (jitter off), attempt 1100 -> exactly ``60.0``, no exception;
2. ``backoff_factor=1e300, max_backoff_sec=7.5``, attempt 3 -> exactly ``7.5``;
3. ``base_backoff_sec=0.0`` stays ``0.0`` even on an overflow-sized exponent;
4. non-overflowing attempts 1..8 are unchanged: ``[1, 2, 4, 8, 16, 32, 60, 60]``;
5. jitter (``0.5``) still applies on the saturated branch: finite, in ``[30, 90]``;
6. end to end, ``with_retry`` survives 1100 throttles at ``max_attempts=1101`` with an
   injected sleep recorder: returns ``"ok"``, 1100 sleeps all ``<= 60``, last ``== 60``.
7. (iter 582) delays saturate at ``threading.TIMEOUT_MAX`` after jitter: a 1e300 cap
   yields a delay the platform accepts, so the first throttle retry cannot overflow.

ISOLATION: written from the spec (pm.md) and the public ``RetryPolicy``/``with_retry``
API only; no src reading. Offline, no git, no mtime, no real sleep. ONE collected item,
because ``make readme-headroom`` read binding_headroom=7 against the pin of 6.
"""

from __future__ import annotations

import inspect
import math
import threading

from proactive_loop.config import RetryPolicy
from proactive_loop.llm.client import LLMThrottleError
from proactive_loop.loop.resilience import _backoff_delay, with_retry


def _iter582_sleepable_saturation() -> None:
    """iter 582: every delay saturates at threading.TIMEOUT_MAX, after jitter."""
    limit = threading.TIMEOUT_MAX

    def accepted(d: float) -> bool:
        # no-wait validator: raises OverflowError exactly where time.sleep(d) would
        return threading.Lock().acquire(True, d)

    # B1. jitter off, 1e300 cap -> exactly TIMEOUT_MAX, a float, no exception
    p1 = RetryPolicy(jitter_frac=0.0, base_backoff_sec=1e300, max_backoff_sec=1e300)
    d1 = _backoff_delay(p1, 1)
    assert isinstance(d1, float) and d1 == limit, d1
    # B2. jitter on: the bound holds AFTER jitter (9.0e9 * 1.1 > TIMEOUT_MAX)
    p2 = RetryPolicy(jitter_frac=0.1, base_backoff_sec=9.0e9, max_backoff_sec=9.0e9)
    d2s = [_backoff_delay(p2, 1) for _ in range(50)]
    assert all(math.isfinite(d) and d <= limit for d in d2s), max(d2s)
    # B3. every returned delay is sleepable on this platform
    for d in [d1, *d2s]:
        assert accepted(d) is True, d
    # B5. end to end: two throttles then "ok", both recorded delays == TIMEOUT_MAX
    calls = {"n": 0}

    def fn() -> str:
        calls["n"] += 1
        if calls["n"] <= 2:
            raise LLMThrottleError("throttled")
        return "ok"

    rec: list[float] = []

    def sleep(d: float) -> None:
        assert accepted(d)
        rec.append(d)

    policy = RetryPolicy(
        max_attempts=3, jitter_frac=0.0, base_backoff_sec=1e300, max_backoff_sec=1e300
    )
    assert with_retry(fn, policy, sleep=sleep) == "ok"
    assert rec == [limit, limit], rec
    # B6. config acceptance unchanged: no new rejection path
    assert RetryPolicy(max_backoff_sec=1e300).max_backoff_sec == 1e300
    assert RetryPolicy(base_backoff_sec=1e300).base_backoff_sec == 1e300
    # B7. the false comment is gone and both texts name the limit
    lines = inspect.getsource(RetryPolicy).splitlines()
    i = next(n for n, ln in enumerate(lines) if ln.strip().startswith("base_backoff_sec"))
    j = i
    while j > 0 and lines[j - 1].strip().startswith("#"):
        j -= 1
    block = "\n".join(lines[j:i])
    assert block, "no comment block above base_backoff_sec"
    assert "merely waits longer" not in block and "TIMEOUT_MAX" in block, block
    assert "merely waits longer" not in "\n".join(lines)
    assert "TIMEOUT_MAX" in (_backoff_delay.__doc__ or "")


def test_backoff_saturates_at_cap_instead_of_overflowing() -> None:
    # 7. (iter 582) saturation at the platform's sleepable maximum
    _iter582_sleepable_saturation()

    # 1. default policy overflows the raw power at attempt 1100 -> saturate at 60.0
    d1 = _backoff_delay(RetryPolicy(jitter_frac=0.0), 1100)
    assert d1 == 60.0 and isinstance(d1, float)

    # 2. huge factor overflows at attempt 3 -> saturate at the custom cap
    p2 = RetryPolicy(jitter_frac=0.0, backoff_factor=1e300, max_backoff_sec=7.5)
    assert _backoff_delay(p2, 3) == 7.5

    # 3. zero base is zero for every attempt, overflow-sized ones included (not max, not nan)
    p3 = RetryPolicy(jitter_frac=0.0, base_backoff_sec=0.0, backoff_factor=1e300)
    for attempt in (1, 2, 3, 50):
        d3 = _backoff_delay(p3, attempt)
        assert d3 == 0.0 and not math.isnan(d3), (attempt, d3)
    assert _backoff_delay(RetryPolicy(jitter_frac=0.0, base_backoff_sec=0.0), 1100) == 0.0

    # 4. non-overflowing schedule is unchanged
    p4 = RetryPolicy(jitter_frac=0.0)
    got4 = [_backoff_delay(p4, a) for a in range(1, 9)]
    assert got4 == [1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 60.0, 60.0]

    # 5. jitter still applies on the saturated branch
    p5 = RetryPolicy(jitter_frac=0.5)
    for _ in range(25):
        d5 = _backoff_delay(p5, 1100)
        assert math.isfinite(d5) and 30.0 <= d5 <= 90.0, d5

    # 6. end to end: 1100 throttles then success, injected sleep, no OverflowError
    calls = {"n": 0}

    def fn() -> str:
        calls["n"] += 1
        if calls["n"] <= 1100:
            raise LLMThrottleError("throttled")
        return "ok"

    sleeps: list[float] = []
    out = with_retry(fn, RetryPolicy(max_attempts=1101, jitter_frac=0.0), sleep=sleeps.append)
    assert out == "ok"
    assert calls["n"] == 1101
    assert len(sleeps) == 1100
    assert all(s <= 60.0 for s in sleeps)
    assert sleeps[-1] == 60.0
