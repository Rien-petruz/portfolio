import random

import pytest

from marketintel.ratelimit import Backoff, SlidingWindowLimiter


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_sliding_window_limits_connection_attempts():
    clk = FakeClock()
    lim = SlidingWindowLimiter(3, 300, clock=clk)
    assert [lim.try_acquire() for _ in range(3)] == [0, 0, 0]
    assert lim.try_acquire() == pytest.approx(300)
    clk.t = 299.9
    assert lim.try_acquire() == pytest.approx(0.1)
    clk.t = 300.0
    assert lim.try_acquire() == 0
    assert lim.in_window == 1


async def test_async_acquire_waits():
    lim = SlidingWindowLimiter(2, 0.1)
    await lim.acquire()
    await lim.acquire()
    import time
    t0 = time.monotonic()
    await lim.acquire()
    assert time.monotonic() - t0 >= 0.08
    assert lim.waits == 1


def test_backoff_grows_with_jitter_and_caps():
    b = Backoff(0.5, 8.0, random.Random(3))
    delays = [b.next_delay() for _ in range(10)]
    for n, d in enumerate(delays):
        full = min(8.0, 0.5 * 2**n)
        assert full / 2 <= d <= full
    assert max(delays) <= 8.0
    b.reset()
    assert b.next_delay() <= 0.5
    # Jitter actually varies between instances (de-synchronises shards).
    x = [Backoff(1, 10, random.Random(i)).next_delay() for i in range(20)]
    assert len(set(x)) > 1
