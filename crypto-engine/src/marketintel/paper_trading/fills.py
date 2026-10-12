"""Fill model for simulated orders.

* **Depth model** - when a synced local L2 book exists, an order walks the
  book level by level up to its limit (market orders: up to a protection
  price). Liquidity already consumed by earlier simulated orders against the
  same book version is subtracted (a liquidity ledger), so two simulated
  orders cannot both take the same displayed quantity.
* **Touch model** - otherwise only the displayed top-of-book quantity is
  available; fills are flagged ``estimate=True`` because hidden liquidity,
  queue position and deeper levels are unknown.
* Market orders never fill entirely at the best price unless the displayed
  quantity covers them.
* Passive (GTC) limit orders fill only when a later trade prints *through*
  the limit price (conservative: queue position unknown) - also an estimate.

Orders arriving when the instrument's quote is not usable are rejected:
nothing credible can be simulated against stale data.
"""

from __future__ import annotations

from typing import Any

from ..market_data.quality import QuoteStatus
from .orders import OrderType, Side, SimOrder


class LiquidityLedger:
    def __init__(self) -> None:
        self._used: dict[str, tuple[int, dict[int, int]]] = {}

    def used(self, key: str, version: int) -> dict[int, int]:
        cur = self._used.get(key)
        if cur is None or cur[0] != version:
            cur = (version, {})
            self._used[key] = cur
        return cur[1]


class FillModel:
    def __init__(self, engine: Any, market_protection_bps: float = 50.0) -> None:
        self.engine = engine
        self.ledger = LiquidityLedger()
        self.protection = market_protection_bps / 10_000

    def match(self, order: SimOrder, now: int) -> tuple[list[tuple[int, int, str, bool]], str]:
        """Return ([(px, qty, liquidity, estimate)], reject_reason)."""
        eng = self.engine
        st = eng.state.instruments.get(order.key)
        if st is None:
            return [], "unknown_instrument"
        status = eng.state.status(st, now)
        if status not in (QuoteStatus.LIVE, QuoteStatus.QUIET):
            return [], f"market_data_{status.value.lower()}"
        buy = order.side is Side.BUY
        touch = st.ask_px if buy else st.bid_px
        if touch <= 0:
            return [], "no_liquidity"
        if order.type is OrderType.MARKET:
            limit = int(touch * (1 + self.protection)) if buy else int(touch * (1 - self.protection))
        else:
            limit = order.limit_px_e8
        book = eng.books.books.get(order.key)
        if book is not None and book.is_synced:
            levels = book.asks.items() if buy else reversed(book.bids.items())
            version = book.version
            source, estimate = "depth", False
        else:
            levels = [(touch, st.ask_qty if buy else st.bid_qty)]
            version = st.book_update_id
            source, estimate = "touch", True
        used = self.ledger.used(order.key, version)
        out: list[tuple[int, int, str, bool]] = []
        remaining = order.remaining_e8
        for px, q in levels:
            if remaining <= 0 or (buy and px > limit) or (not buy and px < limit):
                break
            avail = q - used.get(px, 0)
            if avail <= 0:
                continue
            take = avail if avail < remaining else remaining
            out.append((px, take, source, estimate))
            used[px] = used.get(px, 0) + take
            remaining -= take
        return out, ""

    @staticmethod
    def trade_through(order: SimOrder, trade_px: int, trade_qty: int) -> int:
        """Quantity a resting limit order may fill against a printed trade."""
        if order.side is Side.BUY and trade_px < order.limit_px_e8:
            return min(order.remaining_e8, trade_qty)
        if order.side is Side.SELL and trade_px > order.limit_px_e8:
            return min(order.remaining_e8, trade_qty)
        return 0
