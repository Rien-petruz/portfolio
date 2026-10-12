"""Common exchange-adapter interface and instrument metadata.

Each venue implements :class:`ExchangeAdapter`. The engine only ever talks to
this interface, so adding a venue means adding an adapter (metadata
discovery, connection plans, frame decoding) - never changing the core.

Adapters declare :class:`Capabilities` explicitly instead of the engine
assuming every venue offers the same fields, sequencing or depth.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from ..market_data.events import MarketEvent


class Venue(StrEnum):
    BINANCE = "BINANCE"
    COINBASE = "COINBASE"


class MarketType(StrEnum):
    SPOT = "SPOT"
    MARGIN = "MARGIN"
    FUTURE = "FUTURE"
    PERPETUAL = "PERPETUAL"


class MappingConfidence(StrEnum):
    VERIFIED = "VERIFIED"   # asset identity confirmed by the curated asset table
    INFERRED = "INFERRED"   # only the ticker matched; never used cross-venue by default


@dataclass(frozen=True, slots=True)
class FeeSchedule:
    maker_bps: float
    taker_bps: float
    source: str = "config"   # where the numbers came from (config, tier table, ...)


@dataclass(frozen=True, slots=True)
class InstrumentSpec:
    venue: Venue
    symbol: str                      # native id: "BTCUSDT", "BTC-USD"
    base: str                        # canonical asset ids
    quote: str
    native_base: str
    native_quote: str
    market_type: MarketType = MarketType.SPOT
    status: str = "TRADING"
    tradable: bool = True
    tick_size: int = 0               # e8; 0 = unknown
    step_size: int = 0
    min_qty: int = 0
    max_qty: int = 0
    min_notional: int = 0            # e8, in quote units
    fees: FeeSchedule = FeeSchedule(10.0, 10.0)
    order_types: tuple[str, ...] = ("LIMIT", "MARKET")
    depth_available: bool = False    # a local L2 book will be maintained
    restrictions: tuple[str, ...] = ()
    mapping: MappingConfidence = MappingConfidence.VERIFIED
    alias_of: str | None = None      # venue says this product is the same book as another
    volume_24h_quote: float = 0.0
    key: str = field(default="", compare=False)  # "VENUE:SYMBOL", derived (cached)

    def __post_init__(self) -> None:
        object.__setattr__(self, "key", f"{self.venue.value}:{self.symbol}")

    @property
    def canonical(self) -> str:
        return f"{self.base}/{self.quote}:{self.market_type.value}"

    @property
    def filters_known(self) -> bool:
        return self.tick_size > 0 and self.step_size > 0

    def validate_order(self, px: int, qty: int) -> list[str]:
        """Exchange-filter violations for a (price, qty) pair; empty = valid."""
        from ..numeric import ONE

        errs: list[str] = []
        if not self.filters_known:
            return ["filters_unknown"]
        if not self.tradable:
            errs.append("not_tradable")
        if px <= 0:
            errs.append("price_non_positive")
        elif px % self.tick_size:
            errs.append("price_not_on_tick")
        if qty <= 0:
            errs.append("qty_non_positive")
        else:
            if qty % self.step_size:
                errs.append("qty_not_on_step")
            if qty < self.min_qty:
                errs.append("qty_below_min")
            if self.max_qty and qty > self.max_qty:
                errs.append("qty_above_max")
        if px > 0 and qty > 0 and self.min_notional and px * qty < self.min_notional * ONE:
            errs.append("notional_below_min")
        return errs

    def round_qty(self, qty: int) -> int:
        s = self.step_size
        return qty - qty % s if s > 0 else qty

    def round_price(self, px: int, *, up: bool = False) -> int:
        t = self.tick_size
        if t <= 0:
            return px
        r = px % t
        if not r:
            return px
        return px - r + t if up else px - r


@dataclass(frozen=True, slots=True)
class Capabilities:
    bbo_stream: bool              # dedicated best-bid/offer stream
    trade_stream: bool
    depth: str                    # "diff+rest_snapshot" | "stream_snapshot" | "none"
    trade_ids_contiguous: bool    # gap in trade ids == missed trades
    quote_event_time: bool        # quotes carry an exchange timestamp
    sequence_scope: str           # "per_symbol" | "per_connection" | "none"
    max_streams_per_connection: int
    inbound_msgs_per_second: float  # client -> server message limit
    connection_max_age_s: float | None


@dataclass(slots=True)
class ConnectionPlan:
    conn_id: int
    venue: Venue
    url: str
    symbols: list[str]
    subscribe_messages: list[str] = field(default_factory=list)
    description: str = ""


class FrameDecoder(ABC):
    """Per-connection, stateful decoder: raw frame -> normalized events.

    Decoders may raise :class:`marketintel.exchanges.errors.DecodeError`;
    they return ``None``, one event, or a list of events.
    """

    @abstractmethod
    def decode(self, raw: bytes, recv_mono_ns: int, recv_wall_ns: int) -> Any: ...

    def reset(self) -> None:
        """Called when the connection (re)opens."""


class ExchangeAdapter(ABC):
    venue: Venue
    capabilities: Capabilities

    @abstractmethod
    async def discover(self) -> list[InstrumentSpec]:
        """Instrument metadata from the venue's public REST API."""

    @abstractmethod
    def fallback_instruments(self) -> list[InstrumentSpec]:
        """Instruments to use when metadata is unreachable (filters unknown)."""

    @abstractmethod
    def select(self, instruments: list[InstrumentSpec]) -> list[InstrumentSpec]:
        """Choose the monitored universe according to configuration."""

    @abstractmethod
    def plan_connections(self, instruments: list[InstrumentSpec], first_conn_id: int) -> list[ConnectionPlan]: ...

    @abstractmethod
    def make_decoder(self, plan: ConnectionPlan, sock_uid: int = 0) -> FrameDecoder:
        """New decoder for one socket of ``plan`` (``sock_uid`` distinguishes
        overlapping sockets during rotation)."""

    async def depth_snapshot(self, symbol: str, limit: int) -> dict[str, Any] | None:
        """REST order-book snapshot, for venues that need one (Binance)."""
        return None

    async def server_time_offset_ms(self) -> tuple[float, float] | None:
        """(server - local wall clock offset, round trip) in ms, if supported."""
        return None

    async def close(self) -> None:
        return None


__all__ = [
    "Capabilities", "ConnectionPlan", "ExchangeAdapter", "FeeSchedule", "FrameDecoder",
    "InstrumentSpec", "MappingConfidence", "MarketEvent", "MarketType", "Venue",
]
