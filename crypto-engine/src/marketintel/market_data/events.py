"""Normalized, exchange-independent market events.

* Prices and quantities are exact integers in e8 units (numeric.py).
* ``key`` is the engine-wide instrument key ``"<VENUE>:<native symbol>"``.
* ``recv_mono_ns`` / ``recv_wall_ns`` are captured immediately after the
  WebSocket client hands over the frame.
* ``event_time_ns`` is the exchange's own timestamp for the event, converted to
  ns since the epoch; ``0`` means the venue does not provide one (e.g. the
  Binance spot bookTicker stream). It is never fabricated from local time.
* ``conn_id`` identifies the logical connection (shard) that delivered it.
"""

from __future__ import annotations

from dataclasses import dataclass

BUY = 1
SELL = -1
UNKNOWN_SIDE = 0


@dataclass(slots=True)
class Quote:
    key: str
    update_id: int
    bid_px: int
    bid_qty: int
    ask_px: int
    ask_qty: int
    recv_mono_ns: int
    recv_wall_ns: int
    conn_id: int
    event_time_ns: int = 0


@dataclass(slots=True)
class Trade:
    key: str
    trade_id: int          # -1 when the venue id is not an integer
    px: int
    qty: int
    aggressor: int         # BUY / SELL / UNKNOWN_SIDE (taker side)
    trade_time_ns: int
    event_time_ns: int
    recv_mono_ns: int
    recv_wall_ns: int
    conn_id: int


@dataclass(slots=True)
class DepthDiff:
    """Binance-style diff with an update-id range [first, final]."""

    key: str
    first_update_id: int
    final_update_id: int
    event_time_ns: int
    bids: list[tuple[int, int]]
    asks: list[tuple[int, int]]
    recv_mono_ns: int
    recv_wall_ns: int
    conn_id: int


@dataclass(slots=True)
class BookSnapshot:
    """Full book image delivered on the stream (e.g. Coinbase level2 snapshot)."""

    key: str
    seq: int
    event_time_ns: int
    bids: list[tuple[int, int]]
    asks: list[tuple[int, int]]
    recv_mono_ns: int
    recv_wall_ns: int
    conn_id: int
    src: int = 0           # socket uid: books are owned by the socket that sent the snapshot


@dataclass(slots=True)
class BookDelta:
    """Absolute level replacements (qty 0 = remove), sequenced per connection."""

    key: str
    seq: int
    event_time_ns: int
    bids: list[tuple[int, int]]
    asks: list[tuple[int, int]]
    recv_mono_ns: int
    recv_wall_ns: int
    conn_id: int
    src: int = 0


@dataclass(slots=True)
class ConnectionNotice:
    """Feed-level condition the connection manager must act on."""

    kind: str              # "server_shutdown" | "resync_required" | "heartbeat"
    detail: str
    conn_id: int
    recv_mono_ns: int
    event_time_ns: int = 0


MarketEvent = Quote | Trade | DepthDiff | BookSnapshot | BookDelta | ConnectionNotice
