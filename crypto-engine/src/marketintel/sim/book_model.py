"""Synthetic L2 book model shared by the venue simulators (SYNTHETIC DATA)."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from ..numeric import ONE
from .world import STABLES


def pow10_e8(exp: int) -> int:
    """10**exp in e8 units, clamped to [1e-8, 1]."""
    exp = max(-8, min(0, exp))
    return 10 ** (8 + exp)


def default_tick_step(px: float, base: str, quote: str) -> tuple[int, int]:
    tick = pow10_e8(math.floor(math.log10(px)) - 4)
    step = pow10_e8(math.floor(-math.log10(px)) - 1) if px < 1e7 else 1
    if base in STABLES and quote in STABLES:
        tick, step = pow10_e8(-4), pow10_e8(0)
    return tick, step


@dataclass
class SimBook:
    tick: int
    step: int
    spread_ticks: int
    update_id: int = 1000
    trade_id: int = 5000
    bids: dict[int, int] = field(default_factory=dict)
    asks: dict[int, int] = field(default_factory=dict)
    changed_bids: dict[int, int] = field(default_factory=dict)
    changed_asks: dict[int, int] = field(default_factory=dict)
    volume_quote: float = 0.0

    def rebuild(self, mid: float, quote_usd: float, rng: random.Random, levels: int, initial: bool = False) -> None:
        """Regenerate the top ``levels`` per side around ``mid``, recording
        level changes (qty 0 = removed) for the next diff/update."""
        tick = self.tick
        mid_e8 = int(mid * ONE)
        half = self.spread_ticks * tick / 2
        best_bid = max(tick, int((mid_e8 - half) // tick) * tick)
        best_ask = best_bid + self.spread_ticks * tick
        new_bids: dict[int, int] = {}
        new_asks: dict[int, int] = {}
        notional_target = 20000.0 * rng.uniform(0.3, 1.7) / quote_usd
        for i in range(levels):
            for side, old_side, px in ((new_bids, self.bids, best_bid - i * tick),
                                       (new_asks, self.asks, best_ask + i * tick)):
                if px <= 0:
                    continue
                old = old_side.get(px)
                if old is not None and rng.random() < 0.8:
                    side[px] = old
                    continue
                qty_units = notional_target * rng.lognormvariate(0, 0.6) / (px / ONE)
                side[px] = max(self.step, int(qty_units * ONE) // self.step * self.step)
        if not initial:
            for old_book, new_book, changed in ((self.bids, new_bids, self.changed_bids),
                                                (self.asks, new_asks, self.changed_asks)):
                for p in old_book:
                    if p not in new_book:
                        changed[p] = 0
                for p, q in new_book.items():
                    if old_book.get(p) != q:
                        changed[p] = q
        self.bids, self.asks = new_bids, new_asks
        self.update_id += 1

    def take(self, buy: bool, rng: random.Random) -> tuple[int, int]:
        """A synthetic aggressive trade at the touch; returns (price, qty)."""
        book = self.asks if buy else self.bids
        px = min(book) if buy else max(book)
        top = book[px]
        q = max(self.step, int(top * rng.uniform(0.01, 0.5)) // self.step * self.step)
        if top - q >= self.step:
            book[px] = top - q
            (self.changed_asks if buy else self.changed_bids)[px] = top - q
            self.update_id += 1
        self.trade_id += 1
        self.volume_quote += q * px / 1e16
        return px, q

    def take_changes(self) -> tuple[dict[int, int], dict[int, int]]:
        b, a = self.changed_bids, self.changed_asks
        self.changed_bids, self.changed_asks = {}, {}
        return b, a

    def best(self) -> tuple[int, int, int, int]:
        bp = max(self.bids)
        ap = min(self.asks)
        return bp, self.bids[bp], ap, self.asks[ap]
