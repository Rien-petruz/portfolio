"""Coinbase Advanced Trade market-data adapter (public channels, no credentials).

Connection plan per group of products (``max_symbols_per_connection``):
subscribe to ``heartbeats`` (keeps the connection alive and gives a 1 Hz
liveness signal), ``level2`` (book snapshot + updates; BBO is derived from
it) and ``market_trades``. Subscriptions are sent immediately after connect
(Coinbase closes connections that do not subscribe within a few seconds) and
paced below the unauthenticated inbound message limit.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any

import orjson

from ...clock import NS_PER_MS, mono_ns, wall_ns
from ...config import CoinbaseConfig
from ..base import (
    Capabilities,
    ConnectionPlan,
    ExchangeAdapter,
    FeeSchedule,
    FrameDecoder,
    InstrumentSpec,
    MarketType,
    Venue,
)
from ..http import ReadOnlyHttp
from .decoder import CoinbaseDecoder
from .products import parse_products

log = logging.getLogger(__name__)


class CoinbaseAdapter(ExchangeAdapter):
    venue = Venue.COINBASE
    capabilities = Capabilities(
        bbo_stream=False, trade_stream=True, depth="stream_snapshot", trade_ids_contiguous=False,
        quote_event_time=True, sequence_scope="per_connection", max_streams_per_connection=0,
        inbound_msgs_per_second=8.0, connection_max_age_s=None,
    )

    def __init__(self, cfg: CoinbaseConfig, asset_mapper: Any = str.upper, trade_side: str = "unknown") -> None:
        self.cfg = cfg
        self.asset = asset_mapper
        self.trade_side = trade_side
        self.http = ReadOnlyHttp(cfg.rest_base_url, timeout_s=cfg.rest_timeout_s,
                                 weight_budget_per_min=cfg.rest_weight_budget_per_min)
        # Canonical base assets of interest (set by the engine from the primary venue).
        self.wanted_bases: set[str] = set()

    def _fees(self, symbol: str) -> FeeSchedule:
        f = self.cfg.fee_overrides.get(symbol, self.cfg.fees)
        return FeeSchedule(f.maker_bps, f.taker_bps, "config")

    async def discover(self) -> list[InstrumentSpec]:
        payload = await self.http.get("/api/v3/brokerage/market/products", {"product_type": "SPOT"})
        specs = parse_products(payload, fees=FeeSchedule(self.cfg.fees.maker_bps, self.cfg.fees.taker_bps),
                               asset=self.asset, depth=self.cfg.use_level2)
        return [replace(s, fees=self._fees(s.symbol)) if s.symbol in self.cfg.fee_overrides else s for s in specs]

    def fallback_instruments(self) -> list[InstrumentSpec]:
        prods = self.cfg.explicit_products or self.cfg.required_products
        out = []
        for p in dict.fromkeys(prods):
            if "-" not in p:
                continue
            b, q = p.split("-", 1)
            out.append(InstrumentSpec(Venue.COINBASE, p, self.asset(b), self.asset(q), b, q, MarketType.SPOT,
                                      "UNKNOWN", True, fees=self._fees(p), depth_available=self.cfg.use_level2,
                                      restrictions=("metadata_unavailable",)))
        return out

    def select(self, instruments: list[InstrumentSpec]) -> list[InstrumentSpec]:
        by = {s.symbol: s for s in instruments}
        if any("metadata_unavailable" in s.restrictions for s in instruments):
            return instruments
        if self.cfg.explicit_products:
            return [by[p] for p in self.cfg.explicit_products if p in by and by[p].alias_of is None]
        chosen: list[InstrumentSpec] = []
        seen: set[str] = set()

        def add(s: InstrumentSpec) -> None:
            if s.symbol not in seen and len(chosen) < self.cfg.max_products:
                chosen.append(s)
                seen.add(s.symbol)

        for p in self.cfg.required_products:
            s = by.get(p)
            if s is not None and s.alias_of is None and s.status == "ONLINE":
                add(s)
            elif s is None:
                log.warning("required Coinbase product not listed", extra={"product": p})
        quotes = self.cfg.quote_currencies
        cands = [s for s in instruments
                 if s.market_type is MarketType.SPOT and s.alias_of is None and s.status == "ONLINE"
                 and s.native_quote in quotes and (not self.wanted_bases or s.base in self.wanted_bases)]
        # Prefer liquid products; among equal bases prefer configured quote order.
        cands.sort(key=lambda s: (-s.volume_24h_quote, quotes.index(s.native_quote)))
        for s in cands:
            add(s)
        return chosen

    def plan_connections(self, instruments: list[InstrumentSpec], first_conn_id: int) -> list[ConnectionPlan]:
        n = self.cfg.max_symbols_per_connection
        prods = [i.symbol for i in instruments if i.alias_of is None]
        plans = []
        channels = ["heartbeats"] + (["level2"] if self.cfg.use_level2 else []) + ["market_trades"]
        for gi, i in enumerate(range(0, len(prods), n)):
            group = prods[i:i + n]
            msgs = [orjson.dumps({"type": "subscribe", "product_ids": group, "channel": ch}).decode()
                    for ch in channels]
            plans.append(ConnectionPlan(first_conn_id + gi, Venue.COINBASE, self.cfg.ws_base_url, group, msgs,
                                        f"{len(group)} products x {', '.join(channels)}"))
        return plans

    def make_decoder(self, plan: ConnectionPlan, sock_uid: int = 0) -> FrameDecoder:
        return CoinbaseDecoder(plan.conn_id, sock_uid, plan.symbols, self.trade_side)

    async def server_time_offset_ms(self) -> tuple[float, float] | None:
        t0w, t0m = wall_ns(), mono_ns()
        body = await self.http.get("/api/v3/brokerage/time")
        rtt = mono_ns() - t0m
        return float(body["epochMillis"]) - (t0w + rtt / 2) / NS_PER_MS, rtt / NS_PER_MS

    async def close(self) -> None:
        await self.http.close()
