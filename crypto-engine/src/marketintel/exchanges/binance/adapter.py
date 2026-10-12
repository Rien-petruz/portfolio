"""Binance spot market-data adapter (public endpoints only, no credentials)."""

from __future__ import annotations

import logging
from typing import Any

import orjson

from ...clock import NS_PER_MS, mono_ns, wall_ns
from ...config import BinanceConfig, SubscribeMode
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
from .decoder import BinanceDecoder
from .streams import combined_url, plan_shards
from .symbols import parse_exchange_info, select_universe

log = logging.getLogger(__name__)

WEIGHT_EXCHANGE_INFO = 20
WEIGHT_TICKER_24H_ALL = 80


def depth_weight(limit: int) -> int:
    if limit <= 100:
        return 5
    if limit <= 500:
        return 25
    if limit <= 1000:
        return 50
    return 250


class BinanceAdapter(ExchangeAdapter):
    venue = Venue.BINANCE
    capabilities = Capabilities(
        bbo_stream=True, trade_stream=True, depth="diff+rest_snapshot", trade_ids_contiguous=True,
        quote_event_time=False, sequence_scope="per_symbol", max_streams_per_connection=1024,
        inbound_msgs_per_second=5.0, connection_max_age_s=24 * 3600,
    )

    def __init__(self, cfg: BinanceConfig, asset_mapper: Any = str.upper) -> None:
        self.cfg = cfg
        self.asset = asset_mapper
        self.http = ReadOnlyHttp(cfg.rest_base_url, timeout_s=cfg.rest_timeout_s,
                                 weight_budget_per_min=cfg.rest_weight_budget_per_min,
                                 used_weight_header="x-mbx-used-weight-1m")
        self.volumes: dict[str, float] = {}

    def _fees(self, symbol: str) -> FeeSchedule:
        f = self.cfg.fee_overrides.get(symbol, self.cfg.fees)
        return FeeSchedule(f.maker_bps, f.taker_bps, "config")

    async def discover(self) -> list[InstrumentSpec]:
        info = await self.http.get("/api/v3/exchangeInfo", weight=WEIGHT_EXCHANGE_INFO)
        specs = parse_exchange_info(info, fees=FeeSchedule(self.cfg.fees.maker_bps, self.cfg.fees.taker_bps),
                                    asset=self.asset, depth_symbols=self.cfg.depth_symbols)
        specs = [s if s.symbol not in self.cfg.fee_overrides else _with_fees(s, self._fees(s.symbol))
                 for s in specs]
        if not self.cfg.explicit_symbols:
            for t in await self.http.get("/api/v3/ticker/24hr", weight=WEIGHT_TICKER_24H_ALL):
                try:
                    self.volumes[t["symbol"]] = float(t["quoteVolume"])
                except (KeyError, ValueError):
                    continue
        return [_with_volume(s, self.volumes.get(s.symbol, 0.0)) for s in specs]

    def fallback_instruments(self) -> list[InstrumentSpec]:
        out = []
        seen: set[str] = set()
        base = self.cfg.explicit_symbols or self.cfg.fallback_symbols
        quotes = ("USDT", "USDC", "FDUSD", "BTC", "ETH", "BNB")
        for s in base:
            if s in seen or s in self.cfg.exclude_symbols:
                continue
            seen.add(s)
            q = next((q for q in quotes if s.endswith(q) and len(s) > len(q)), None)
            if q is None:
                continue
            b = s[: -len(q)]
            out.append(InstrumentSpec(Venue.BINANCE, s, self.asset(b), self.asset(q), b, q,
                                      MarketType.SPOT, "UNKNOWN", True, fees=self._fees(s),
                                      depth_available=s in self.cfg.depth_symbols,
                                      restrictions=("metadata_unavailable",)))
        return out[: max(self.cfg.max_symbols, len(self.cfg.explicit_symbols))]

    def select(self, instruments: list[InstrumentSpec]) -> list[InstrumentSpec]:
        by = {s.symbol: s for s in instruments}
        if any("metadata_unavailable" in s.restrictions for s in instruments):
            return instruments
        if self.cfg.explicit_symbols:
            missing = [s for s in self.cfg.explicit_symbols if s not in by]
            if missing:
                log.warning("explicit symbols unknown to exchange", extra={"symbols": missing})
            return [by[s] for s in self.cfg.explicit_symbols if s in by]
        chosen = select_universe(by, self.volumes, quote_assets=self.cfg.quote_assets,
                                 required=self.cfg.required_symbols, exclude=self.cfg.exclude_symbols,
                                 min_symbols=self.cfg.min_symbols, max_symbols=self.cfg.max_symbols)
        return [by[s] for s in chosen]

    def plan_connections(self, instruments: list[InstrumentSpec], first_conn_id: int) -> list[ConnectionPlan]:
        cfg = self.cfg
        shards = plan_shards([i.symbol for i in instruments],
                             depth_symbols={i.symbol for i in instruments if i.depth_available},
                             trades=cfg.subscribe_trades,
                             max_streams_per_connection=cfg.max_streams_per_connection,
                             max_symbols_per_connection=cfg.max_symbols_per_connection)
        plans = []
        for sh in shards:
            cid = first_conn_id + sh.shard_id
            if cfg.subscribe_mode is SubscribeMode.URL:
                plans.append(ConnectionPlan(cid, Venue.BINANCE, combined_url(cfg.ws_base_url, sh.streams),
                                            sh.symbols, [], f"{len(sh.streams)} streams in URL"))
            else:
                msgs = [orjson.dumps({"method": "SUBSCRIBE", "params": sh.streams[i:i + cfg.subscribe_batch_size],
                                      "id": i + 1}).decode()
                        for i in range(0, len(sh.streams), cfg.subscribe_batch_size)]
                plans.append(ConnectionPlan(cid, Venue.BINANCE, combined_url(cfg.ws_base_url, []),
                                            sh.symbols, msgs, f"{len(sh.streams)} streams via SUBSCRIBE"))
        return plans

    def make_decoder(self, plan: ConnectionPlan, sock_uid: int = 0) -> FrameDecoder:
        return BinanceDecoder(plan.conn_id, plan.symbols)

    async def depth_snapshot(self, symbol: str, limit: int) -> dict[str, Any] | None:
        return await self.http.get("/api/v3/depth", {"symbol": symbol, "limit": limit}, weight=depth_weight(limit))

    async def server_time_offset_ms(self) -> tuple[float, float] | None:
        t0w, t0m = wall_ns(), mono_ns()
        body = await self.http.get("/api/v3/time")
        rtt = mono_ns() - t0m
        return float(body["serverTime"]) - (t0w + rtt / 2) / NS_PER_MS, rtt / NS_PER_MS

    async def close(self) -> None:
        await self.http.close()


def _with_fees(s: InstrumentSpec, fees: FeeSchedule) -> InstrumentSpec:
    from dataclasses import replace
    return replace(s, fees=fees)


def _with_volume(s: InstrumentSpec, v: float) -> InstrumentSpec:
    from dataclasses import replace
    return replace(s, volume_24h_quote=v)
