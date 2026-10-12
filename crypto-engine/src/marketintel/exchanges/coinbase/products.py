"""Coinbase Advanced Trade public product metadata -> :class:`InstrumentSpec`.

Endpoint: ``GET /api/v3/brokerage/market/products`` (public). Field names as
in Coinbase's official SDK (``coinbase-advanced-py`` product types).

Notable venue specifics handled here:
* **Aliases**: some products are aliases of another book (e.g. ``BTC-USDC``
  is served by the ``BTC-USD`` book). Alias products are recorded with
  ``alias_of`` and never subscribed or compared as independent markets.
* Trading states ``cancel_only``, ``limit_only``, ``post_only``,
  ``auction_mode``, ``trading_disabled``, ``is_disabled``, ``view_only``
  become restrictions; only fully tradable spot products are eligible for
  paper execution.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from ...numeric import parse_e8
from ..base import FeeSchedule, InstrumentSpec, MarketType, Venue

log = logging.getLogger(__name__)

_TYPES = {"SPOT": MarketType.SPOT, "FUTURE": MarketType.FUTURE}


def parse_product(p: dict[str, Any], *, fees: FeeSchedule, asset: Callable[[str], str] = str.upper,
                  depth: bool = True) -> InstrumentSpec:
    pid = p["product_id"]
    nb = p.get("base_currency_id") or p.get("base_display_symbol") or pid.split("-")[0]
    nq = p.get("quote_currency_id") or p.get("quote_display_symbol") or pid.split("-")[1]
    restrictions: list[str] = []
    for flag in ("cancel_only", "limit_only", "post_only", "auction_mode", "trading_disabled",
                 "is_disabled", "view_only"):
        if p.get(flag):
            restrictions.append(flag)
    status = str(p.get("status", "")).lower()
    if status != "online":
        restrictions.append(f"status_{status or 'unknown'}")
    blocking = {"cancel_only", "trading_disabled", "is_disabled", "view_only", "auction_mode"}
    tradable = status == "online" and not (blocking & set(restrictions))
    tick = p.get("price_increment") or p.get("quote_increment")
    alias = p.get("alias") or None
    return InstrumentSpec(
        venue=Venue.COINBASE,
        symbol=pid,
        base=asset(nb),
        quote=asset(nq),
        native_base=nb,
        native_quote=nq,
        market_type=_TYPES.get(str(p.get("product_type", "SPOT")).upper(), MarketType.FUTURE),
        status=status.upper() or "UNKNOWN",
        tradable=tradable,
        tick_size=parse_e8(tick) if tick else 0,
        step_size=parse_e8(p["base_increment"]) if p.get("base_increment") else 0,
        min_qty=parse_e8(p["base_min_size"]) if p.get("base_min_size") else 0,
        max_qty=parse_e8(p["base_max_size"]) if p.get("base_max_size") else 0,
        min_notional=parse_e8(p["quote_min_size"]) if p.get("quote_min_size") else 0,
        fees=fees,
        order_types=("LIMIT",) if p.get("limit_only") else ("LIMIT", "MARKET"),
        depth_available=depth and alias is None,
        restrictions=tuple(restrictions),
        alias_of=alias,
        volume_24h_quote=_f(p.get("approximate_quote_24h_volume")) or _f(p.get("volume_24h")) * _f(p.get("price")),
    )


def _f(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def parse_products(payload: dict[str, Any], *, fees: FeeSchedule, asset: Callable[[str], str] = str.upper,
                   depth: bool = True) -> list[InstrumentSpec]:
    out = []
    for p in payload.get("products", []):
        try:
            out.append(parse_product(p, fees=fees, asset=asset, depth=depth))
        except (KeyError, ValueError, IndexError) as exc:
            log.warning("skipping product with unparseable metadata",
                        extra={"product": p.get("product_id"), "error": str(exc)})
    return out
