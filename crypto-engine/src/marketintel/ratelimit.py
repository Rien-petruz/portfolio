"""Rate limiters and backoff policy (pure, injectable clocks for testing)."""

from __future__ import annotations

import asyncio
import random
import time
from collections import deque
from collections.abc import Callable


class SlidingWindowLimiter:
    """At most ``limit`` acquisitions in any trailing ``window_s`` seconds.

    Used for Binance's per-IP connection-attempt limit (300 per 5 minutes).
    """

    def __init__(self, limit: int, window_s: float, clock: Callable[[], float] = time.monotonic) -> None:
        if limit < 1:
            raise ValueError("limit must be >= 1")
        self.limit = limit
        self.window_s = window_s
        self._clock = clock
        self._stamps: deque[float] = deque()
        self._lock = asyncio.Lock()
        self.waits = 0

    def _prune(self, now: float) -> None:
        cutoff = now - self.window_s
        while self._stamps and self._stamps[0] <= cutoff:
            self._stamps.popleft()

    def try_acquire(self) -> float:
        """Record an attempt and return 0, or return seconds to wait."""
        now = self._clock()
        self._prune(now)
        if len(self._stamps) < self.limit:
            self._stamps.append(now)
            return 0.0
        return self._stamps[0] + self.window_s - now

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                wait = self.try_acquire()
                if wait <= 0:
                    return
                self.waits += 1
                await asyncio.sleep(wait)

    @property
    def in_window(self) -> int:
        self._prune(self._clock())
        return len(self._stamps)


class Backoff:
    """Exponential backoff with "equal jitter".

    delay_n = d/2 + U(0, d/2) where d = min(cap, base * 2**n). The floor of d/2
    guarantees spacing after repeated failures; the jitter de-synchronises
    shards that dropped at the same moment (thundering herd).
    """

    def __init__(self, base_s: float, cap_s: float, rng: random.Random | None = None) -> None:
        self.base_s = base_s
        self.cap_s = cap_s
        self.attempt = 0
        self._rng = rng or random.Random()

    def next_delay(self) -> float:
        d = min(self.cap_s, self.base_s * (2 ** min(self.attempt, 30)))
        self.attempt += 1
        half = d / 2
        return half + self._rng.uniform(0, half)

    def reset(self) -> None:
        self.attempt = 0
