"""Exchange metadata: symbol filters and universe selection.

Parses ``GET /api/v3/exchangeInfo`` into exact e8 filter values and chooses
the monitored universe. Filter semantics follow Binance's filter docs:

* PRICE_FILTER: price % tickSize == 0 and minPrice <= price <= maxPrice
* LOT_SIZE:     qty % stepSize == 0 and minQty <= qty <= maxQty
* NOTIONAL / MIN_NOTIONAL: price * qty >= minNotional
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Iterable

from ...numeric import ONE, ceil_to_step, floor_to_step, parse_e8

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SymbolInfo:
    symbol: str
    base: str
    quote: str
    status: str
    tick_size: int = 0      # e8; 0 = unknown/unconstrained
    min_price: int = 0
    max_price: int = 0
    step_size: int = 0
    min_qty: int = 0
    max_qty: int = 0
    min_notional: int = 0   # e8 quote units
    spot_allowed: bool = True

    @property
    def filters_known(self) -> bool:
        return self.tick_size > 0 and self.step_size > 0

    def round_price(self, px: int, *, up: bool = False) -> int:
        return ceil_to_step(px, self.tick_size) if up else floor_to_step(px, self.tick_size)

    def round_qty(self, qty: int) -> int:
        """Quantities are always rounded *down*: never trade more than intended."""
        return floor_to_step(qty, self.step_size)

    def validate_order(self, px: int, qty: int) -> list[str]:
        """Return a list of filter violations (empty means the order passes)."""
        errs: list[str] = []
        if not self.filters_known:
            errs.append("filters_unknown")
            return errs
        if px <= 0:
            errs.append("price_non_positive")
        else:
            if px % self.tick_size:
                errs.append("price_not_on_tick")
            if self.min_price and px < self.min_price:
                errs.append("price_below_min")
            if self.max_price and px > self.max_price:
                errs.append("price_above_max")
        if qty <= 0:
            errs.append("qty_non_positive")
        else:
            if qty % self.step_size:
                errs.append("qty_not_on_step")
            if qty < self.min_qty:
                errs.append("qty_below_min")
            if self.max_qty and qty > self.max_qty:
                errs.append("qty_above_max")
        if px > 0 and qty > 0 and self.min_notional:
            # px*qty is in e16 units; compare exactly against minNotional (e8).
            if px * qty < self.min_notional * ONE:
                errs.append("notional_below_min")
        return errs


def parse_symbol(raw: dict[str, Any]) -> SymbolInfo:
    kw: dict[str, Any] = {}
    for f in raw.get("filters", []):
        ft = f.get("filterType")
        if ft == "PRICE_FILTER":
            kw["tick_size"] = parse_e8(f["tickSize"])
            kw["min_price"] = parse_e8(f["minPrice"])
            kw["max_price"] = parse_e8(f["maxPrice"])
        elif ft == "LOT_SIZE":
            kw["step_size"] = parse_e8(f["stepSize"])
            kw["min_qty"] = parse_e8(f["minQty"])
            kw["max_qty"] = parse_e8(f["maxQty"])
        elif ft in ("NOTIONAL", "MIN_NOTIONAL"):
            kw["min_notional"] = parse_e8(f["minNotional"])
    return SymbolInfo(
        symbol=raw["symbol"],
        base=raw["baseAsset"],
        quote=raw["quoteAsset"],
        status=raw["status"],
        spot_allowed=bool(raw.get("isSpotTradingAllowed", True)),
        **kw,
    )


def parse_exchange_info(payload: dict[str, Any]) -> dict[str, SymbolInfo]:
    out: dict[str, SymbolInfo] = {}
    for raw in payload.get("symbols", []):
        try:
            info = parse_symbol(raw)
        except (KeyError, ValueError) as exc:
            log.warning("skipping symbol with unparseable metadata", extra={"symbol": raw.get("symbol"), "error": str(exc)})
            continue
        out[info.symbol] = info
    return out


def select_universe(
    infos: dict[str, SymbolInfo],
    quote_volume: dict[str, float],
    *,
    quote_assets: Iterable[str],
    required: Iterable[str],
    exclude: Iterable[str],
    min_symbols: int,
    max_symbols: int,
) -> list[str]:
    """Required symbols first, then the most liquid tradable pairs in the
    configured quote assets, ranked by 24h quote volume."""
    exclude_set = set(exclude)
    quotes = set(quote_assets)

    def tradable(s: str) -> bool:
        i = infos.get(s)
        return i is not None and i.status == "TRADING" and i.spot_allowed and s not in exclude_set

    chosen: list[str] = []
    seen: set[str] = set()
    for s in required:
        if s in seen:
            continue
        if tradable(s):
            chosen.append(s)
            seen.add(s)
        else:
            log.warning("required symbol not tradable on exchange; skipped", extra={"symbol": s})

    ranked = sorted(
        (s for s, i in infos.items() if i.quote in quotes and tradable(s) and s not in seen),
        key=lambda s: quote_volume.get(s, 0.0),
        reverse=True,
    )
    for s in ranked:
        if len(chosen) >= max_symbols:
            break
        chosen.append(s)
        seen.add(s)

    if len(chosen) < min_symbols:
        raise ValueError(f"only {len(chosen)} tradable symbols selected; need >= {min_symbols}")
    return chosen
