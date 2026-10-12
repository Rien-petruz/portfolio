"""Deterministic timer queue shared by live and replay modes.

Simulated order arrivals, expiries and periodic jobs (feature sampling, the
one-second summary, risk checks) are scheduled here rather than with
``asyncio.sleep`` so a replay reproduces exactly the same sequence of events
as live processing would have.

* Live: :meth:`Scheduler.run_forever` sleeps until the next due item.
* Replay: the driver calls :meth:`run_due` before applying each frame.
"""

from __future__ import annotations

import asyncio
import heapq
import itertools
import logging
import time
from collections.abc import Callable
from typing import Any

from .clock import NS_PER_S, Clock

log = logging.getLogger(__name__)


class Scheduler:
    def __init__(self, clock: Clock) -> None:
        self.clock = clock
        self._heap: list[tuple[int, int, Callable[[int], Any]]] = []
        self._seq = itertools.count()
        self._wake: asyncio.Event | None = None
        self.errors = 0
        self.executed = 0
        self.max_late_ns = 0
        self.metrics: Any = None  # LatencyRegistry: per-job durations (live only)

    def call_at(self, t_ns: int, fn: Callable[[int], Any]) -> None:
        """Run ``fn(now_ns)`` at monotonic time ``t_ns`` (or as soon after)."""
        first = not self._heap or t_ns < self._heap[0][0]
        heapq.heappush(self._heap, (t_ns, next(self._seq), fn))
        if first and self._wake is not None:
            self._wake.set()

    def call_later(self, delay_ns: int, fn: Callable[[int], Any]) -> None:
        self.call_at(self.clock.mono() + max(0, delay_ns), fn)

    def every(self, interval_ns: int, fn: Callable[[int], Any], *, start_ns: int | None = None) -> None:
        """Run ``fn(now)`` on a fixed grid. Missed ticks are skipped, not bunched."""
        first = start_ns if start_ns is not None else self.clock.mono() + interval_ns
        due = [first]

        def tick(now: int) -> None:
            try:
                fn(now)
            finally:
                k = max(1, (now - due[0]) // interval_ns + 1)
                due[0] += k * interval_ns
                self.call_at(due[0], tick)

        name = getattr(fn, "__qualname__", "job")
        tick.job_name = name.replace(".<locals>", "")  # type: ignore[attr-defined]
        self.call_at(first, tick)

    def next_due(self) -> int | None:
        return self._heap[0][0] if self._heap else None

    def run_due(self, now_ns: int) -> int:
        n = 0
        heap = self._heap
        while heap and heap[0][0] <= now_ns:
            t, _, fn = heapq.heappop(heap)
            late = now_ns - t
            if late > self.max_late_ns:
                self.max_late_ns = late
            try:
                if self.metrics is not None:
                    t0 = time.perf_counter_ns()
                    fn(now_ns)
                    name = getattr(fn, "job_name", None) or getattr(fn, "__qualname__", "job")
                    self.metrics.record(f"job.{name}", time.perf_counter_ns() - t0)
                else:
                    fn(now_ns)
            except Exception:
                self.errors += 1
                if self.errors <= 20:
                    log.exception("scheduled job failed")
            n += 1
        self.executed += n
        return n

    async def run_forever(self) -> None:
        self._wake = asyncio.Event()
        while True:
            now = self.clock.mono()
            self.run_due(now)
            nxt = self.next_due()
            timeout = 1.0 if nxt is None else max(0.0, (nxt - self.clock.mono()) / NS_PER_S)
            self._wake.clear()
            if timeout > 0:
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout)
                except TimeoutError:
                    pass
            else:
                await asyncio.sleep(0)
