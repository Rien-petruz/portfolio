"""Event-loop lag monitor.

A task sleeps for a fixed interval and records how late it wakes up. Lateness
means something hogged the loop (CPU-heavy callback, GC pause, blocking call),
which directly delays market-data receipt. This is the primary overload signal.
"""

from __future__ import annotations

import asyncio

from ..clock import NS_PER_MS, mono_ns
from .latency import WindowedLatency


class LoopLagMonitor:
    def __init__(self, interval_ms: int = 50) -> None:
        self.interval_ms = interval_ms
        self.hist = WindowedLatency("event_loop_lag")
        self.last_lag_ns = 0
        self.max_recent_ns = 0

    async def run(self) -> None:
        interval_ns = self.interval_ms * NS_PER_MS
        interval_s = self.interval_ms / 1000
        while True:
            t0 = mono_ns()
            await asyncio.sleep(interval_s)
            lag = mono_ns() - t0 - interval_ns
            if lag < 0:
                lag = 0
            self.last_lag_ns = lag
            if lag > self.max_recent_ns:
                self.max_recent_ns = lag
            self.hist.record(lag)
