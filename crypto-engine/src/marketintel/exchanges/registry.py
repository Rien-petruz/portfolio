"""Canonical instrument registry.

Maps every venue-native instrument to canonical asset ids and decides which
instruments may be compared across venues:

* Native tickers pass through a per-venue alias table (renames such as
  ``RNDR`` -> ``RENDER``) before becoming canonical asset ids.
* An instrument's mapping is ``VERIFIED`` only if *both* its canonical base
  and quote are in the curated ``verified_assets`` list. Matching tickers alone
  (``INFERRED``) are never compared across venues unless explicitly allowed:
  identical tickers can denote different assets on different venues.
* Only identical market types are compared (spot with spot). Spot, margin,
  futures and perpetuals are different instrument classes.
* Venue aliases (Coinbase ``BTC-USDC`` served by the ``BTC-USD`` book) are
  kept out of comparisons; the alias target is the real market.
* Different quote currencies are only compared through an explicit
  *conversion instrument* (e.g. ``COINBASE:USDT-USD``) whose own bid/ask,
  fees, freshness and liquidity are applied by the profitability model.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace

from ..config import RegistryConfig
from .base import InstrumentSpec, MappingConfidence, MarketType


@dataclass(frozen=True, slots=True)
class Conversion:
    """Convert amounts of ``src`` into ``dst`` by trading ``spec``.

    ``sell_base`` is True when converting means selling the instrument's base
    (src == base, dst == quote), so the executable price is the bid;
    otherwise we buy the base with the quote and pay the ask.
    """

    spec: InstrumentSpec
    src: str
    dst: str
    sell_base: bool


@dataclass(frozen=True, slots=True)
class CrossVenuePair:
    """Two venues quoting the same canonical base asset.

    ``conv`` converts ``b``'s quote currency into ``a``'s (None when the
    quotes are identical).
    """

    base: str
    a: InstrumentSpec
    b: InstrumentSpec
    conv: Conversion | None

    @property
    def pair_id(self) -> str:
        return f"{self.a.key}|{self.b.key}"


class InstrumentRegistry:
    def __init__(self, cfg: RegistryConfig) -> None:
        self.cfg = cfg
        self.verified = {a.upper() for a in cfg.verified_assets}
        self.by_key: dict[str, InstrumentSpec] = {}

    def asset_mapper(self, venue: str) -> Callable[[str], str]:
        aliases = {k.upper(): v.upper() for k, v in self.cfg.asset_aliases.get(venue, {}).items()}
        return lambda native: aliases.get(native.upper(), native.upper())

    def confidence(self, spec: InstrumentSpec) -> MappingConfidence:
        if spec.base in self.verified and spec.quote in self.verified:
            return MappingConfidence.VERIFIED
        return MappingConfidence.INFERRED

    def add(self, specs: Iterable[InstrumentSpec]) -> list[InstrumentSpec]:
        out = []
        for s in specs:
            s = replace(s, mapping=self.confidence(s))
            self.by_key[s.key] = s
            out.append(s)
        return out

    def get(self, key: str) -> InstrumentSpec | None:
        return self.by_key.get(key)

    def canonical_groups(self) -> dict[str, list[InstrumentSpec]]:
        groups: dict[str, list[InstrumentSpec]] = {}
        for s in self.by_key.values():
            if s.alias_of is None:
                groups.setdefault(s.canonical, []).append(s)
        return groups

    # ------------------------------------------------------------ conversions
    def conversion(self, src: str, dst: str) -> Conversion | None:
        """Executable conversion of ``src`` currency into ``dst`` currency."""
        if src == dst:
            return None
        for key in self.cfg.conversion_instruments:
            s = self.by_key.get(key)
            if s is None or s.alias_of is not None or s.market_type is not MarketType.SPOT:
                continue
            if self.confidence(s) is not MappingConfidence.VERIFIED:
                continue
            if s.base == src and s.quote == dst:
                return Conversion(s, src, dst, sell_base=True)
            if s.base == dst and s.quote == src:
                return Conversion(s, src, dst, sell_base=False)
        return None

    # ------------------------------------------------------- cross-venue pairs
    def cross_venue_pairs(self, *, use_conversions: bool = True) -> list[CrossVenuePair]:
        allow_inferred = self.cfg.allow_inferred_mapping
        conv_keys = set(self.cfg.conversion_instruments)
        by_base: dict[tuple[str, MarketType], list[InstrumentSpec]] = {}
        for s in self.by_key.values():
            if s.alias_of is not None or s.key in conv_keys:
                continue  # conversion instruments are cost inputs, not compared markets
            if s.mapping is not MappingConfidence.VERIFIED and not allow_inferred:
                continue
            by_base.setdefault((s.base, s.market_type), []).append(s)
        pairs: list[CrossVenuePair] = []
        for (base, _mt), specs in by_base.items():
            specs.sort(key=lambda s: s.key)
            for i, a in enumerate(specs):
                for b in specs[i + 1:]:
                    if a.venue == b.venue:
                        continue
                    if a.quote == b.quote:
                        pairs.append(CrossVenuePair(base, a, b, None))
                    elif use_conversions:
                        conv = self.conversion(b.quote, a.quote)
                        if conv is not None:
                            pairs.append(CrossVenuePair(base, a, b, conv))
        # Identical-quote pairs first (they need no conversion assumptions).
        pairs.sort(key=lambda p: (p.conv is not None, p.base, p.pair_id))
        return pairs

    def snapshot(self) -> list[dict[str, object]]:
        from ..numeric import ONE
        return [{
            "key": s.key, "venue": s.venue.value, "symbol": s.symbol, "canonical": s.canonical,
            "base": s.base, "quote": s.quote, "market_type": s.market_type.value, "status": s.status,
            "tradable": s.tradable, "tick_size": s.tick_size / ONE, "step_size": s.step_size / ONE,
            "min_qty": s.min_qty / ONE, "min_notional": s.min_notional / ONE,
            "maker_bps": s.fees.maker_bps, "taker_bps": s.fees.taker_bps, "order_types": list(s.order_types),
            "depth": s.depth_available, "restrictions": list(s.restrictions), "mapping": s.mapping.value,
            "alias_of": s.alias_of,
        } for s in self.by_key.values()]
