"""Internal normalized event schema.

All prices and quantities are exact integers in e8 units (see numeric.py).
Every event carries two local receive timestamps captured immediately after
the frame was handed to us by the WebSocket client:

* ``recv_mono_ns`` - monotonic clock, for local latency measurement.
* ``recv_wall_ns`` - wall clock, for comparison with exchange event times.

``shard_id`` identifies the logical connection group (see exchange/binance/ws.py)
that delivered the event.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class BookTicker:
    symbol: str
    update_id: int
    bid_px: int
    bid_qty: int
    ask_px: int
    ask_qty: int
    recv_mono_ns: int
    recv_wall_ns: int
    shard_id: int
    # Binance spot bookTicker carries no event time; kept for schema symmetry.
    event_time_ms: int = 0


@dataclass(slots=True)
class Trade:
    symbol: str
    trade_id: int
    px: int
    qty: int
    trade_time_ms: int
    event_time_ms: int
    buyer_is_maker: bool
    recv_mono_ns: int
    recv_wall_ns: int
    shard_id: int

    @property
    def aggressor_is_buy(self) -> bool:
        # If the buyer is the maker, the seller crossed the spread.
        return not self.buyer_is_maker


@dataclass(slots=True)
class DepthDiff:
    symbol: str
    first_update_id: int
    final_update_id: int
    event_time_ms: int
    bids: list[tuple[int, int]]
    asks: list[tuple[int, int]]
    recv_mono_ns: int
    recv_wall_ns: int
    shard_id: int


@dataclass(slots=True)
class ServerShutdown:
    event_time_ms: int
    recv_mono_ns: int
    recv_wall_ns: int
    shard_id: int


MarketEvent = BookTicker | Trade | DepthDiff | ServerShutdown
