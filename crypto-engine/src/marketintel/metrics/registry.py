"""Named latency histograms created on demand.

Stage names follow ``<area>.<from>_to_<to>`` (e.g. ``xex.recv_to_signal``),
optionally with a venue suffix (``ingest.recv_to_state.BINANCE``). Every
histogram reports the last completed summary window and the lifetime.
"""

from __future__ import annotations

from typing import Any

from .latency import WindowedLatency


class LatencyRegistry:
    def __init__(self) -> None:
        self._h: dict[str, WindowedLatency] = {}

    def hist(self, name: str) -> WindowedLatency:
        h = self._h.get(name)
        if h is None:
            h = self._h[name] = WindowedLatency(name)
        return h

    def record(self, name: str, ns: int) -> None:
        self.hist(name).record(ns)

    def roll(self, now_ns: int | None = None) -> None:
        for h in self._h.values():
            h.roll(now_ns)

    def all(self) -> list[WindowedLatency]:
        return list(self._h.values())

    def report(self, prefixes: tuple[str, ...] | None = None, lifetime: bool = True) -> dict[str, Any]:
        return {name: h.summary(lifetime) for name, h in sorted(self._h.items())
                if prefixes is None or name.startswith(prefixes)}
