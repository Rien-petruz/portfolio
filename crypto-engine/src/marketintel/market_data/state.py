"""In-memory latest-market-state cache for every monitored instrument on every venue.

One mutable :class:`InstrumentState` per instrument key (``VENUE:SYMBOL``),
updated in place. Validity is computed *on read* from timestamps, thresholds
and connection health (``market_data/quality.py``), so a quote can never
remain "valid" just because nobody re-evaluated it.

Ordering rules
--------------
* Quote ``update_id`` must strictly increase per instrument (Binance book
  update id; for venues with per-connection sequencing the engine supplies a
  per-instrument book version). Duplicates/out-of-order quotes are dropped.
* Trade ids: duplicates are dropped when ids are numeric; gaps count as
  missed trades only on venues whose ids are contiguous.
* After a reconnect, quote ordering restarts and the instrument is
  UNINITIALIZED until a fresh quote arrives.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from ..clock import NS_PER_MS
from ..numeric import ONE
from .events import Quote, Trade
from .quality import QuoteStatus, quote_status

if TYPE_CHECKING:
    from ..exchanges.base import InstrumentSpec
    from ..exchanges.connection import ShardHealth


class InstrumentState:
    __slots__ = (
        "key", "venue", "symbol", "spec", "shard",
        "quiet_ns", "stale_ns", "stall_ns", "trade_ids_contiguous",
        "bid_px", "bid_qty", "ask_px", "ask_qty", "book_update_id",
        "book_recv_mono_ns", "book_recv_wall_ns", "book_event_time_ns", "book_fresh",
        "last_trade_px", "last_trade_qty", "last_trade_id", "last_trade_time_ns", "last_trade_aggressor",
        "trade_recv_mono_ns",
        "n_book", "n_trades", "n_book_out_of_order", "n_trade_dups", "n_trade_gaps",
        "missed_trades", "n_crossed", "n_reconnects", "ever_up", "last_valid_mono_ns",
    )

    def __init__(self, key: str, spec: InstrumentSpec | None = None, *, quiet_ms: int = 2000,
                 stale_ms: int = 30000, stall_ms: int = 10000, trade_ids_contiguous: bool = True) -> None:
        self.key = key
        venue, _, symbol = key.partition(":")
        self.venue = venue
        self.symbol = symbol
        self.spec = spec
        self.shard: ShardHealth | None = None
        self.quiet_ns = quiet_ms * NS_PER_MS
        self.stale_ns = stale_ms * NS_PER_MS
        self.stall_ns = stall_ms * NS_PER_MS
        self.trade_ids_contiguous = trade_ids_contiguous
        self.bid_px = self.bid_qty = self.ask_px = self.ask_qty = 0
        self.book_update_id = 0
        self.book_recv_mono_ns = 0
        self.book_recv_wall_ns = 0
        self.book_event_time_ns = 0
        self.book_fresh = False
        self.last_trade_px = self.last_trade_qty = 0
        self.last_trade_id = 0
        self.last_trade_time_ns = 0
        self.last_trade_aggressor = 0
        self.trade_recv_mono_ns = 0
        self.n_book = self.n_trades = 0
        self.n_book_out_of_order = self.n_trade_dups = self.n_trade_gaps = 0
        self.missed_trades = self.n_crossed = self.n_reconnects = 0
        self.ever_up = False
        self.last_valid_mono_ns = 0

    @property
    def mid_e8(self) -> int:
        return (self.bid_px + self.ask_px) // 2

    def mid(self) -> float | None:
        if self.bid_px <= 0 or self.ask_px <= 0:
            return None
        return (self.bid_px + self.ask_px) / (2 * ONE)

    def spread_bps(self) -> float | None:
        if self.bid_px <= 0 or self.ask_px <= 0:
            return None
        return (self.ask_px - self.bid_px) * 20_000 / (self.ask_px + self.bid_px)

    def touch_imbalance(self) -> float | None:
        t = self.bid_qty + self.ask_qty
        return (self.bid_qty - self.ask_qty) / t if t > 0 else None


class MarketState:
    def __init__(self, max_delivery_lag_ms: int = 2_000) -> None:
        self.instruments: dict[str, InstrumentState] = {}
        self.max_delivery_lag_ns = max_delivery_lag_ms * NS_PER_MS
        self.unknown_events = 0

    # Backwards-compatible name used by earlier code/tests.
    @property
    def symbols(self) -> dict[str, InstrumentState]:
        return self.instruments

    def add(self, key: str, spec: InstrumentSpec | None = None, **kw: Any) -> InstrumentState:
        st = self.instruments.get(key)
        if st is None:
            st = self.instruments[key] = InstrumentState(key, spec, **kw)
        elif spec is not None:
            st.spec = spec
        return st

    def bind_shard(self, keys: Iterable[str], shard: ShardHealth) -> None:
        for k in keys:
            self.instruments[k].shard = shard

    # ---------------------------------------------------------------- events
    def apply_quote(self, ev: Quote) -> InstrumentState | None:
        st = self.instruments.get(ev.key)
        if st is None:
            self.unknown_events += 1
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
        st.book_event_time_ns = ev.event_time_ns
        st.book_fresh = True
        st.n_book += 1
        if ev.bid_px > 0 and ev.ask_px > 0 and ev.bid_px >= ev.ask_px:
            st.n_crossed += 1
        return st

    def apply_trade(self, ev: Trade) -> InstrumentState | None:
        st = self.instruments.get(ev.key)
        if st is None:
            self.unknown_events += 1
            return None
        tid = ev.trade_id
        if tid >= 0:
            last = st.last_trade_id
            if tid <= last and st.trade_recv_mono_ns:
                st.n_trade_dups += 1
                return None
            if st.trade_ids_contiguous and last and tid > last + 1:
                st.n_trade_gaps += 1
                st.missed_trades += tid - last - 1
            st.last_trade_id = tid
        st.last_trade_px = ev.px
        st.last_trade_qty = ev.qty
        st.last_trade_time_ns = ev.trade_time_ns
        st.last_trade_aggressor = ev.aggressor
        st.trade_recv_mono_ns = ev.recv_mono_ns
        st.n_trades += 1
        return st

    # ------------------------------------------------------- connection life
    def on_shard_up(self, keys: Iterable[str]) -> None:
        for k in keys:
            st = self.instruments.get(k)
            if st is not None:
                st.book_fresh = False
                st.book_update_id = 0
                if st.ever_up:
                    st.n_reconnects += 1
                st.ever_up = True

    def on_shard_down(self, keys: Iterable[str]) -> None:
        for k in keys:
            st = self.instruments.get(k)
            if st is not None:
                st.book_fresh = False

    def invalidate(self, key: str) -> None:
        """Book rebuild in progress (e.g. resync): quote not usable until refreshed."""
        st = self.instruments.get(key)
        if st is not None:
            st.book_fresh = False

    # ---------------------------------------------------------------- status
    def status(self, st: InstrumentState, now_mono_ns: int) -> QuoteStatus:
        return quote_status(st, now_mono_ns, self.max_delivery_lag_ns)

    def is_usable(self, key: str, now_mono_ns: int, *, allow_quiet: bool = False,
                  max_age_ms: int | None = None) -> bool:
        st = self.instruments.get(key)
        if st is None:
            return False
        s = self.status(st, now_mono_ns)
        if s is not QuoteStatus.LIVE and not (allow_quiet and s is QuoteStatus.QUIET):
            return False
        if max_age_ms is not None and now_mono_ns - st.book_recv_mono_ns > max_age_ms * NS_PER_MS:
            return False
        return True

    def status_counts(self, now_mono_ns: int, venue: str | None = None) -> dict[str, int]:
        out = {s.value: 0 for s in QuoteStatus}
        for st in self.instruments.values():
            if venue is None or st.venue == venue:
                out[self.status(st, now_mono_ns).value] += 1
        return out

    def row(self, st: InstrumentState, now_mono_ns: int) -> dict[str, Any]:
        age_ms = (now_mono_ns - st.book_recv_mono_ns) / NS_PER_MS if st.book_recv_mono_ns else None
        spec = st.spec
        return {
            "key": st.key,
            "venue": st.venue,
            "symbol": st.symbol,
            "canonical": spec.canonical if spec else None,
            "status": self.status(st, now_mono_ns).value,
            "bid": st.bid_px / ONE if st.bid_px else None,
            "bid_qty": st.bid_qty / ONE,
            "ask": st.ask_px / ONE if st.ask_px else None,
            "ask_qty": st.ask_qty / ONE,
            "mid": st.mid(),
            "spread_bps": st.spread_bps(),
            "touch_imbalance": st.touch_imbalance(),
            "book_age_ms": age_ms,
            "exchange_time_ms": st.book_event_time_ns // NS_PER_MS if st.book_event_time_ns else None,
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
            "filters_known": bool(spec and spec.filters_known),
            "mapping": spec.mapping.value if spec else None,
        }
