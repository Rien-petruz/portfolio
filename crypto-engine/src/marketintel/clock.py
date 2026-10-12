"""Clocks.

Two time bases are used deliberately and never mixed:

* **monotonic ns** for local durations (receive -> processed, quote age,
  staleness, simulated latency). It never jumps with NTP adjustments.
* **wall ns** only for comparison with exchange event times. Such comparisons
  include network delay and clock skew; they are corrected with an estimated
  offset where available and always reported separately.

Components never call ``time`` directly for decisions: they take a
:class:`Clock`. Live runs use :class:`LiveClock`; replay/backtests use
:class:`ManualClock`, advanced by the replay driver to each recorded frame's
receive time, so the very same strategy and paper-trading code is
deterministic under replay.
"""

from __future__ import annotations

import time

mono_ns = time.monotonic_ns
wall_ns = time.time_ns

NS_PER_MS = 1_000_000
NS_PER_US = 1_000
NS_PER_S = 1_000_000_000


def wall_ms() -> int:
    return time.time_ns() // NS_PER_MS


class Clock:
    """Interface: monotonic and wall time in integer nanoseconds."""

    live = True

    def mono(self) -> int:
        raise NotImplementedError

    def wall(self) -> int:
        raise NotImplementedError


class LiveClock(Clock):
    live = True

    def __init__(self) -> None:
        self.mono = time.monotonic_ns  # type: ignore[method-assign]
        self.wall = time.time_ns  # type: ignore[method-assign]


class ManualClock(Clock):
    """Replay clock. Time only moves forward when the driver says so."""

    live = False

    def __init__(self, mono_ns_: int = 0, wall_ns_: int = 0) -> None:
        self._mono = mono_ns_
        self._wall = wall_ns_

    def mono(self) -> int:
        return self._mono

    def wall(self) -> int:
        return self._wall

    def set(self, mono_ns_: int, wall_ns_: int | None = None) -> None:
        if mono_ns_ < self._mono:
            raise ValueError("replay clock cannot move backwards")
        if wall_ns_ is None:
            wall_ns_ = self._wall + (mono_ns_ - self._mono)
        self._mono = mono_ns_
        self._wall = wall_ns_

    def advance(self, ns: int) -> None:
        self.set(self._mono + ns)
