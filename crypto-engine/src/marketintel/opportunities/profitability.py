"""Executable-price arithmetic shared by the opportunity strategies.

All inputs are exact e8 integers from the market state/books; outputs used
for ranking/display are floats. Sizing respects exchange step sizes using
integer arithmetic (the least common multiple of both venues' steps).
"""

from __future__ import annotations

from collections.abc import Iterable
from math import gcd

from ..numeric import ONE


def lcm(a: int, b: int) -> int:
    if a <= 0:
        return max(b, 1)
    if b <= 0:
        return a
    return a * b // gcd(a, b)


def floor_to(v: int, step: int) -> int:
    return v - v % step if step > 0 else v


def walk(levels: Iterable[tuple[int, int]], qty: int) -> tuple[int, int, int]:
    """Consume ``qty`` (e8) across price levels (best first).

    Returns (filled_qty_e8, notional_e16, worst_px_e8). ``notional`` is exact
    (sum of px_e8 * qty_e8)."""
    remaining = qty
    notional = 0
    worst = 0
    for px, q in levels:
        if remaining <= 0:
            break
        take = q if q < remaining else remaining
        notional += px * take
        remaining -= take
        worst = px
    return qty - remaining, notional, worst


def qty_within(levels: Iterable[tuple[int, int]], limit_px: int, buy: bool) -> int:
    """Total quantity available at prices no worse than ``limit_px``."""
    total = 0
    for px, q in levels:
        if (buy and px > limit_px) or (not buy and px < limit_px):
            break
        total += q
    return total


def vwap(notional_e16: int, qty_e8: int) -> float:
    return notional_e16 / qty_e8 / ONE if qty_e8 else 0.0


def bps(x: float) -> float:
    return x * 10_000.0
