"""In-memory latest-market-state cache.

One mutable :class:`SymbolState` per symbol, updated in place from normalized
events (no per-tick allocation beyond the event itself). Validity is computed
on read from timestamps and connection status, so a quote can never be
considered valid merely because nobody re-evaluated it.

Quote status semantics
----------------------
* ``DISCONNECTED``  - the shard carrying this symbol is down. Never usable.
* ``UNINITIALIZED`` - no book update received since the (re)connect.
* ``CROSSED``       - bid >= ask: data error or race; never usable.
* ``ONE_SIDED``     - one side empty (price 0).
* ``STALE``         - no update for ``stale_after_ms``; or the shard has not
                      delivered *any* frame for ``connection_stall_ms``; or the
                      shard's recent exchange-event -> receipt delay exceeds
                      ``max_delivery_lag_ms`` (data arriving late is stale).
* ``QUIET``         - connection healthy, book unchanged for ``quiet_after_ms``.
                      bookTicker only publishes on change, so this is the
                      normal state of an illiquid pair, but consumers must
                      decide whether they accept it.
* ``LIVE``          - updated recently on a healthy connection.

Sequence handling
-----------------
* bookTicker ``u`` is the exchange order-book update id: strictly increasing
  per symbol but not contiguous. ``u <=`` last seen => duplicate/out-of-order,
  dropped (this also de-duplicates overlapping sockets during rotation).
* trade ids are contiguous per symbol: a jump counts as a gap and the number
  of missed trades is recorded; ``id <=`` last => duplicate, dropped.
* After a reconnect, ordering state is reset so the first fresh event is
  always accepted (missed trades across the outage are still counted).
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Any, Iterable

from ..clock import NS_PER_MS, NS_PER_S
from ..ingestion.events import BookTicker, Trade
from ..numeric import ONE

if TYPE_CHECKING:
    from ..exchange.binance.symbols import SymbolInfo
    from ..exchange.binance.ws import ShardHealth


class QuoteStatus(StrEnum):
    LIVE = "LIVE"
    QUIET = "QUIET"
    STALE = "STALE"
    ONE_SIDED = "ONE_SIDED"
    CROSSED = "CROSSED"
    UNINITIALIZED = "UNINITIALIZED"
    DISCONNECTED = "DISCONNECTED"
    UNSUBSCRIBED = "UNSUBSCRIBED"


USABLE = frozenset({QuoteStatus.LIVE})
USABLE_INCL_QUIET = frozenset({QuoteStatus.LIVE, QuoteStatus.QUIET})


class SymbolState:
    __slots__ = (
        "symbol", "info", "shard",
        "bid_px", "bid_qty", "ask_px", "ask_qty", "book_update_id",
        "book_recv_mono_ns", "book_recv_wall_ns", "book_fresh",
        "last_trade_px", "last_trade_qty", "last_trade_id", "last_trade_time_ms",
        "last_trade_event_ms", "last_trade_buyer_maker", "trade_recv_mono_ns", "trade_fresh",
        "n_book", "n_trades", "n_book_out_of_order", "n_trade_dups", "n_trade_gaps",
        "missed_trades", "n_crossed", "n_reconnects", "ever_up",
    )

    def __init__(self, symbol: str, info: "SymbolInfo | None" = None) -> None:
        self.symbol = symbol
        self.info = info
        self.shard: ShardHealth | None = None
        self.bid_px = self.bid_qty = self.ask_px = self.ask_qty = 0
        self.book_update_id = 0
        self.book_recv_mono_ns = 0
        self.book_recv_wall_ns = 0
        self.book_fresh = False  # updated since last (re)connect
        self.last_trade_px = self.last_trade_qty = 0
        self.last_trade_id = 0
        self.last_trade_time_ms = 0
        self.last_trade_event_ms = 0
        self.last_trade_buyer_maker = False
        self.trade_recv_mono_ns = 0
        self.trade_fresh = False
        self.n_book = self.n_trades = 0
        self.n_book_out_of_order = self.n_trade_dups = self.n_trade_gaps = 0
        self.missed_trades = self.n_crossed = self.n_reconnects = 0
        self.ever_up = False

    # Derived values (exact ints / floats for features) ----------------------
    @property
    def mid_e8(self) -> int:
        return (self.bid_px + self.ask_px) // 2

    @property
    def crossed(self) -> bool:
        return self.bid_px > 0 and self.ask_px > 0 and self.bid_px >= self.ask_px

    def spread_bps(self) -> float | None:
        if self.bid_px <= 0 or self.ask_px <= 0:
            return None
        return (self.ask_px - self.bid_px) * 20_000 / (self.ask_px + self.bid_px)

    def touch_imbalance(self) -> float | None:
        """(bidQty - askQty) / (bidQty + askQty) at the touch, in [-1, 1]."""
        t = self.bid_qty + self.ask_qty
        if t <= 0:
            return None
        return (self.bid_qty - self.ask_qty) / t


class MarketState:
    # A delivery-lag sample older than this no longer describes the feed.
    LAG_SAMPLE_TTL_NS = 5 * NS_PER_S

    def __init__(self, quiet_after_ms: int, stale_after_ms: int, conn_stall_ms: int,
                 max_delivery_lag_ms: int = 2_000) -> None:
        self.symbols: dict[str, SymbolState] = {}
        self.quiet_ns = quiet_after_ms * NS_PER_MS
        self.stale_ns = stale_after_ms * NS_PER_MS
        self.conn_stall_ns = conn_stall_ms * NS_PER_MS
        self.max_delivery_lag_ns = max_delivery_lag_ms * NS_PER_MS
        self.unknown_symbol_events = 0

    def add_symbol(self, symbol: str, info: "SymbolInfo | None" = None) -> SymbolState:
        st = self.symbols.get(symbol)
        if st is None:
            st = self.symbols[symbol] = SymbolState(symbol, info)
        elif info is not None:
            st.info = info
        return st

    def bind_shard(self, symbols: Iterable[str], shard: "ShardHealth") -> None:
        for s in symbols:
            self.add_symbol(s).shard = shard

    # ---------------------------------------------------------------- events
    def apply_book_ticker(self, ev: BookTicker) -> SymbolState | None:
        st = self.symbols.get(ev.symbol)
        if st is None:
            self.unknown_symbol_events += 1
            return None
        if ev.update_id <= st.book_update_id:
            st.n_book_out_of_order += 1
            return None
        st.bid_px = ev.bid_px
        st.bid_qty = ev.bid_qty
        st.ask_px = ev.ask_px
        st.ask_qty = ev.ask_qty
        st.book_update_id = ev.update_id
        st.book_recv_mono_ns = ev.recv_mono_ns
        st.book_recv_wall_ns = ev.recv_wall_ns
        st.book_fresh = True
        st.n_book += 1
        if ev.bid_px > 0 and ev.ask_px > 0 and ev.bid_px >= ev.ask_px:
            st.n_crossed += 1
        return st

    def apply_trade(self, ev: Trade) -> SymbolState | None:
        st = self.symbols.get(ev.symbol)
        if st is None:
            self.unknown_symbol_events += 1
            return None
        last = st.last_trade_id
        if ev.trade_id <= last:
            st.n_trade_dups += 1
            return None
        if last and ev.trade_id > last + 1:
            st.n_trade_gaps += 1
            st.missed_trades += ev.trade_id - last - 1
        st.last_trade_id = ev.trade_id
        st.last_trade_px = ev.px
        st.last_trade_qty = ev.qty
        st.last_trade_time_ms = ev.trade_time_ms
        st.last_trade_event_ms = ev.event_time_ms
        st.last_trade_buyer_maker = ev.buyer_is_maker
        st.trade_recv_mono_ns = ev.recv_mono_ns
        st.trade_fresh = True
        st.n_trades += 1
        return st

    # ------------------------------------------------------- connection life
    def on_shard_up(self, symbols: Iterable[str]) -> None:
        for s in symbols:
            st = self.symbols.get(s)
            if st is not None:
                st.book_fresh = False
                st.trade_fresh = False
                # The exchange's update ids are monotonic, but after an outage
                # we accept the first fresh event unconditionally.
                st.book_update_id = 0
                if st.ever_up:
                    st.n_reconnects += 1
                st.ever_up = True

    def on_shard_down(self, symbols: Iterable[str]) -> None:
        for s in symbols:
            st = self.symbols.get(s)
            if st is not None:
                st.book_fresh = False
                st.trade_fresh = False

    # ---------------------------------------------------------------- status
    def status(self, st: SymbolState, now_mono_ns: int) -> QuoteStatus:
        sh = st.shard
        if sh is None:
            return QuoteStatus.UNSUBSCRIBED
        if not sh.connected:
            return QuoteStatus.DISCONNECTED
        if not st.book_fresh:
            return QuoteStatus.UNINITIALIZED
        if now_mono_ns - sh.last_msg_mono_ns > self.conn_stall_ns:
            return QuoteStatus.STALE
        if (sh.delivery_lag_ns > self.max_delivery_lag_ns
                and now_mono_ns - sh.delivery_lag_at_ns < self.LAG_SAMPLE_TTL_NS):
            return QuoteStatus.STALE
        if st.bid_px <= 0 or st.ask_px <= 0:
            return QuoteStatus.ONE_SIDED
        if st.bid_px >= st.ask_px:
            return QuoteStatus.CROSSED
        age = now_mono_ns - st.book_recv_mono_ns
        if age > self.stale_ns:
            return QuoteStatus.STALE
        if age > self.quiet_ns:
            return QuoteStatus.QUIET
        return QuoteStatus.LIVE

    def is_usable(self, symbol: str, now_mono_ns: int, *, allow_quiet: bool = False,
                  max_age_ms: int | None = None) -> bool:
        st = self.symbols.get(symbol)
        if st is None:
            return False
        s = self.status(st, now_mono_ns)
        if s not in (USABLE_INCL_QUIET if allow_quiet else USABLE):
            return False
        if max_age_ms is not None and now_mono_ns - st.book_recv_mono_ns > max_age_ms * NS_PER_MS:
            return False
        return True

    def status_counts(self, now_mono_ns: int) -> dict[str, int]:
        out = {s.value: 0 for s in QuoteStatus}
        for st in self.symbols.values():
            out[self.status(st, now_mono_ns).value] += 1
        return out

    def row(self, st: SymbolState, now_mono_ns: int) -> dict[str, Any]:
        """JSON-friendly view for API/dashboard (floats for display only)."""
        age_ms = (now_mono_ns - st.book_recv_mono_ns) / NS_PER_MS if st.book_recv_mono_ns else None
        mid = st.mid_e8 / ONE if st.bid_px > 0 and st.ask_px > 0 else None
        return {
            "symbol": st.symbol,
            "status": self.status(st, now_mono_ns).value,
            "bid": st.bid_px / ONE if st.bid_px else None,
            "bid_qty": st.bid_qty / ONE,
            "ask": st.ask_px / ONE if st.ask_px else None,
            "ask_qty": st.ask_qty / ONE,
            "mid": mid,
            "spread_bps": st.spread_bps(),
            "touch_imbalance": st.touch_imbalance(),
            "book_age_ms": age_ms,
            "book_update_id": st.book_update_id,
            "last_trade": st.last_trade_px / ONE if st.last_trade_px else None,
            "last_trade_age_ms": (now_mono_ns - st.trade_recv_mono_ns) / NS_PER_MS if st.trade_recv_mono_ns else None,
            "book_updates": st.n_book,
            "trades": st.n_trades,
            "out_of_order": st.n_book_out_of_order,
            "trade_dups": st.n_trade_dups,
            "trade_gaps": st.n_trade_gaps,
            "missed_trades": st.missed_trades,
            "crossed_events": st.n_crossed,
            "reconnects": st.n_reconnects,
            "shard": st.shard.shard_id if st.shard else None,
            "filters_known": bool(st.info and st.info.filters_known),
        }

    @staticmethod
    def age_s(now_mono_ns: int, then_ns: int) -> float | None:
        return (now_mono_ns - then_ns) / NS_PER_S if then_ns else None
