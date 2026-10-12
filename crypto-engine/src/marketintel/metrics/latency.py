"""Fixed-memory latency histograms (HDR-style log-linear buckets).

Values are recorded in integer nanoseconds. Values below 64 ns are exact;
larger values fall into one of 32 linear sub-buckets per power of two, so a
reported percentile is within ~3.2% (1/32) of the true sample value. Recording
is O(1) with no allocation; percentiles are an O(buckets) scan done only when
a report is requested.

``WindowedLatency`` keeps a lifetime histogram plus the most recently completed
reporting window (the reporter calls ``roll()`` once per interval), so
dashboards can show "now" without old samples diluting it.
"""

from __future__ import annotations

from bisect import bisect_left
from itertools import accumulate
from operator import add
from typing import Any

from ..clock import NS_PER_US, mono_ns

_SUB_BITS = 5
_SUB = 1 << _SUB_BITS            # 32 sub-buckets per octave
_EXACT = _SUB << 1               # values < 64 stored exactly
_N_BUCKETS = _EXACT + 64 * _SUB  # covers values up to 2**70 ns


def _index(v: int) -> int:
    if v < _EXACT:
        return v
    shift = v.bit_length() - (_SUB_BITS + 1)
    return _EXACT + (shift - 1) * _SUB + ((v >> shift) - _SUB)


def _upper(idx: int) -> int:
    """Highest value mapping to bucket ``idx`` (conservative for percentiles)."""
    if idx < _EXACT:
        return idx
    k = idx - _EXACT
    shift = k // _SUB + 1
    top = k % _SUB + _SUB
    return ((top + 1) << shift) - 1


class LatencyHistogram:
    __slots__ = ("counts", "count", "total", "min", "max")

    def __init__(self) -> None:
        self.counts = [0] * _N_BUCKETS
        self.count = 0
        self.total = 0
        self.min = 0
        self.max = 0

    def record(self, v: int) -> None:
        if v < 0:
            v = 0
        self.counts[_index(v)] += 1
        if self.count == 0 or v < self.min:
            self.min = v
        if v > self.max:
            self.max = v
        self.count += 1
        self.total += v

    def merge(self, other: LatencyHistogram) -> None:
        if other.count == 0:
            return
        self.counts = list(map(add, self.counts, other.counts))
        self.min = other.min if self.count == 0 else min(self.min, other.min)
        self.max = max(self.max, other.max)
        self.count += other.count
        self.total += other.total

    def reset(self) -> None:
        self.counts = [0] * _N_BUCKETS
        self.count = self.total = self.min = self.max = 0

    def percentile(self, q: float) -> int:
        """Value at quantile q in [0, 1] (bucket upper bound, clamped to max)."""
        return self.percentiles((q,))[0]

    def percentiles(self, qs: tuple[float, ...]) -> list[int]:
        if self.count == 0:
            return [0 for _ in qs]
        cum = list(accumulate(self.counts))  # C-level; one pass for all quantiles
        out = []
        for q in qs:
            if q <= 0:
                out.append(self.min)
            elif q >= 1:
                out.append(self.max)
            else:
                rank = max(1, int(q * self.count + 0.999999999))
                out.append(min(_upper(bisect_left(cum, rank)), self.max))
        return out

    def summary_us(self) -> dict[str, Any]:
        """Summary in microseconds (floats, 1 decimal)."""
        if self.count == 0:
            return {"count": 0, "p50": None, "p95": None, "p99": None, "max": None, "mean": None}
        f = lambda ns: round(ns / NS_PER_US, 1)  # noqa: E731
        p50, p95, p99 = self.percentiles((0.50, 0.95, 0.99))
        return {"count": self.count, "p50": f(p50), "p95": f(p95), "p99": f(p99), "max": f(self.max),
                "mean": f(self.total / self.count)}


class WindowedLatency:
    __slots__ = ("name", "lifetime", "current", "last", "_window_start", "last_window_s")

    def __init__(self, name: str) -> None:
        self.name = name
        self.lifetime = LatencyHistogram()
        self.current = LatencyHistogram()
        self.last = LatencyHistogram()
        self._window_start = mono_ns()
        self.last_window_s = 0.0

    def record(self, v: int) -> None:
        self.current.record(v)

    def roll(self, now_ns: int | None = None) -> None:
        """Close the current window. Called by the reporter, not the hot path."""
        now = mono_ns() if now_ns is None else now_ns
        self.lifetime.merge(self.current)
        self.last, self.current = self.current, self.last
        self.current.reset()
        self.last_window_s = (now - self._window_start) / 1e9
        self._window_start = now

    def summary(self, lifetime: bool = True) -> dict[str, Any]:
        if not lifetime:
            partial = self.last.count == 0
            w = (self.current if partial else self.last).summary_us()
            w["partial"] = partial
            return {"window": w}
        life = LatencyHistogram()
        life.merge(self.lifetime)
        life.merge(self.current)
        # Before the first window closes, show the partial current window.
        partial = self.last.count == 0
        window = (self.current if partial else self.last).summary_us()
        window["partial"] = partial
        return {"window": window, "lifetime": life.summary_us()}
