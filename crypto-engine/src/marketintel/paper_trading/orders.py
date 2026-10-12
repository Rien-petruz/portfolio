"""Simulated order and fill records. Every record is labelled SIMULATED."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from ..numeric import ONE


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class TimeInForce(StrEnum):
    IOC = "IOC"
    GTC = "GTC"


class OrderStatus(StrEnum):
    PENDING = "PENDING"            # created, travelling to the (simulated) venue
    OPEN = "OPEN"                  # resting (GTC)
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"          # IOC remainder / user cancel / emergency stop
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"


FINAL = frozenset({OrderStatus.FILLED, OrderStatus.CANCELED, OrderStatus.EXPIRED, OrderStatus.REJECTED})


def client_order_id(parent_id: str, leg: str) -> str:
    """Deterministic, idempotent id: the same intent always maps to the same id."""
    return "sim-" + hashlib.sha1(f"{parent_id}|{leg}".encode(), usedforsecurity=False).hexdigest()[:20]


@dataclass
class SimFill:
    fill_id: str
    client_id: str
    venue: str
    key: str
    side: Side
    px_e8: int
    qty_e8: int
    fee_quote: float
    liquidity: str          # "depth" (local L2 book) | "touch" (top of book only) | "trade_through"
    estimate: bool          # True when the data cannot support a credible fill model
    mono_ns: int
    wall_ns: int

    def view(self) -> dict[str, Any]:
        return {"fill_id": self.fill_id, "client_id": self.client_id, "venue": self.venue, "key": self.key,
                "side": self.side.value, "price": self.px_e8 / ONE, "qty": self.qty_e8 / ONE,
                "fee_quote": self.fee_quote, "liquidity": self.liquidity, "estimate": self.estimate,
                "wall_ns": self.wall_ns, "label": "SIMULATED"}


@dataclass
class SimOrder:
    client_id: str
    parent_id: str
    strategy: str
    venue: str
    key: str
    side: Side
    type: OrderType
    tif: TimeInForce
    qty_e8: int
    limit_px_e8: int            # 0 for market orders
    created_mono_ns: int
    created_wall_ns: int
    arrival_mono_ns: int = 0
    expire_mono_ns: int = 0
    reference_px_e8: int = 0    # touch price at decision time (for slippage measurement)
    status: OrderStatus = OrderStatus.PENDING
    filled_qty_e8: int = 0
    notional_e16: int = 0
    fee_quote: float = 0.0
    fills: list[SimFill] = field(default_factory=list)
    reject_reason: str = ""
    leg: str = ""
    estimate: bool = False
    final_mono_ns: int = 0
    reserved: Any = None        # Decimal amount reserved in the portfolio while in flight

    @property
    def remaining_e8(self) -> int:
        return self.qty_e8 - self.filled_qty_e8

    @property
    def avg_px(self) -> float:
        return self.notional_e16 / self.filled_qty_e8 / ONE if self.filled_qty_e8 else 0.0

    @property
    def is_final(self) -> bool:
        return self.status in FINAL

    def slippage_bps(self) -> float | None:
        if not self.filled_qty_e8 or not self.reference_px_e8:
            return None
        ref = self.reference_px_e8 / ONE
        d = (self.avg_px - ref) / ref * 10_000
        return d if self.side is Side.BUY else -d

    def view(self) -> dict[str, Any]:
        return {
            "client_id": self.client_id, "parent_id": self.parent_id, "strategy": self.strategy, "leg": self.leg,
            "venue": self.venue, "key": self.key, "side": self.side.value, "type": self.type.value,
            "tif": self.tif.value, "qty": self.qty_e8 / ONE, "limit_price": self.limit_px_e8 / ONE or None,
            "reference_price": self.reference_px_e8 / ONE or None, "status": self.status.value,
            "filled_qty": self.filled_qty_e8 / ONE, "avg_price": self.avg_px or None, "fee_quote": self.fee_quote,
            "slippage_bps": self.slippage_bps(), "reject_reason": self.reject_reason, "estimate": self.estimate,
            "created_wall_ns": self.created_wall_ns,
            "latency_ms": (self.arrival_mono_ns - self.created_mono_ns) / 1e6 if self.arrival_mono_ns else None,
            "label": "SIMULATED",
        }
