"""Binance ``exchangeInfo`` -> :class:`InstrumentSpec`, and universe selection.

Filter semantics (Binance filter docs):
* PRICE_FILTER: price % tickSize == 0 and minPrice <= price <= maxPrice
* LOT_SIZE:     qty % stepSize == 0 and minQty <= qty <= maxQty
* NOTIONAL / MIN_NOTIONAL: price * qty >= minNotional
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from typing import Any

from ...numeric import parse_e8
from ..base import FeeSchedule, InstrumentSpec, MarketType, Venue

log = logging.getLogger(__name__)

AssetMapper = Callable[[str], str]


def parse_symbol(raw: dict[str, Any], *, fees: FeeSchedule, asset: AssetMapper = str.upper,
                 depth: bool = False) -> InstrumentSpec:
    kw: dict[str, Any] = {}
    for f in raw.get("filters", []):
        ft = f.get("filterType")
        if ft == "PRICE_FILTER":
            kw["tick_size"] = parse_e8(f["tickSize"])
            parse_e8(f["minPrice"])  # validated: malformed metadata excludes the symbol
            parse_e8(f["maxPrice"])
        elif ft == "LOT_SIZE":
            kw["step_size"] = parse_e8(f["stepSize"])
            kw["min_qty"] = parse_e8(f["minQty"])
            kw["max_qty"] = parse_e8(f["maxQty"])
        elif ft in ("NOTIONAL", "MIN_NOTIONAL"):
            kw["min_notional"] = parse_e8(f["minNotional"])
    status = raw["status"]
    spot = bool(raw.get("isSpotTradingAllowed", True))
    restrictions = []
    if not spot:
        restrictions.append("spot_trading_not_allowed")
    if status != "TRADING":
        restrictions.append(f"status_{status.lower()}")
    return InstrumentSpec(
        venue=Venue.BINANCE,
        symbol=raw["symbol"],
        base=asset(raw["baseAsset"]),
        quote=asset(raw["quoteAsset"]),
        native_base=raw["baseAsset"],
        native_quote=raw["quoteAsset"],
        market_type=MarketType.SPOT,
        status=status,
        tradable=status == "TRADING" and spot,
        fees=fees,
        order_types=tuple(raw.get("orderTypes", ("LIMIT", "MARKET"))),
        depth_available=depth,
        restrictions=tuple(restrictions),
        **kw,
    )


def parse_exchange_info(payload: dict[str, Any], *, fees: FeeSchedule, asset: AssetMapper = str.upper,
                        depth_symbols: Iterable[str] = ()) -> list[InstrumentSpec]:
    depth = set(depth_symbols)
    out: list[InstrumentSpec] = []
    for raw in payload.get("symbols", []):
        try:
            out.append(parse_symbol(raw, fees=fees, asset=asset, depth=raw.get("symbol") in depth))
        except (KeyError, ValueError) as exc:
            log.warning("skipping symbol with unparseable metadata",
                        extra={"symbol": raw.get("symbol"), "error": str(exc)})
    return out


def select_universe(
    specs: dict[str, InstrumentSpec],
    quote_volume: dict[str, float],
    *,
    quote_assets: Iterable[str],
    required: Iterable[str],
    exclude: Iterable[str],
    min_symbols: int,
    max_symbols: int,
) -> list[str]:
    """Required symbols first, then the most liquid tradable pairs in the
    configured quote assets ranked by 24h quote volume."""
    exclude_set = set(exclude)
    quotes = set(quote_assets)

    def ok(s: str) -> bool:
        i = specs.get(s)
        return i is not None and i.tradable and s not in exclude_set

    chosen: list[str] = []
    seen: set[str] = set()
    for s in required:
        if s in seen:
            continue
        if ok(s):
            chosen.append(s)
            seen.add(s)
        else:
            log.warning("required symbol not tradable on exchange; skipped", extra={"symbol": s})
    ranked = sorted((s for s, i in specs.items() if i.native_quote in quotes and ok(s) and s not in seen),
                    key=lambda s: quote_volume.get(s, 0.0), reverse=True)
    for s in ranked:
        if len(chosen) >= max_symbols:
            break
        chosen.append(s)
        seen.add(s)
    if len(chosen) < min_symbols:
        raise ValueError(f"only {len(chosen)} tradable symbols selected; need >= {min_symbols}")
    return chosen
