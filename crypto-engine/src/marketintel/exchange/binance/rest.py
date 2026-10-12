"""Minimal async REST client for public Binance spot endpoints.

Only used off the hot path: startup metadata, depth snapshots for order-book
(re)synchronisation and server-time sampling. Request weight is tracked from
the ``X-MBX-USED-WEIGHT-1M`` response header and throttled locally well below
the exchange limit; HTTP 429/418 responses honour ``Retry-After``.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

from ...clock import NS_PER_MS, mono_ns, wall_ns

log = logging.getLogger(__name__)

# Request weights from Binance's REST documentation (spot, 2024+).
WEIGHT_EXCHANGE_INFO = 20
WEIGHT_TICKER_24H_ALL = 80
WEIGHT_TIME = 1


def depth_weight(limit: int) -> int:
    if limit <= 100:
        return 5
    if limit <= 500:
        return 25
    if limit <= 1000:
        return 50
    return 250


class RestError(RuntimeError):
    def __init__(self, status: int, body: str) -> None:
        super().__init__(f"HTTP {status}: {body[:200]}")
        self.status = status


class BinanceRest:
    def __init__(self, base_url: str, *, timeout_s: float = 10.0, weight_budget_per_min: int = 3000,
                 client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(base_url=base_url, timeout=timeout_s)
        self.weight_budget = weight_budget_per_min
        self.used_weight = 0
        self._window_start = time.monotonic()
        self._banned_until = 0.0
        self._lock = asyncio.Lock()
        self.requests = 0
        self.errors = 0

    async def close(self) -> None:
        await self._client.aclose()

    async def _reserve(self, weight: int) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                if now < self._banned_until:
                    await asyncio.sleep(self._banned_until - now)
                    continue
                if now - self._window_start >= 60:
                    self._window_start = now
                    self.used_weight = 0
                if self.used_weight + weight <= self.weight_budget:
                    self.used_weight += weight
                    return
                await asyncio.sleep(60 - (now - self._window_start))

    async def get(self, path: str, params: dict[str, Any] | None = None, *, weight: int = 1) -> Any:
        await self._reserve(weight)
        self.requests += 1
        resp = await self._client.get(path, params=params)
        used = resp.headers.get("x-mbx-used-weight-1m")
        if used is not None and used.isdigit():
            # Exchange view is authoritative (other processes may share the IP).
            self.used_weight = max(self.used_weight, int(used))
        if resp.status_code in (418, 429):
            self.errors += 1
            retry = float(resp.headers.get("retry-after", "60"))
            self._banned_until = time.monotonic() + retry
            log.error("REST rate limited", extra={"status": resp.status_code, "retry_after_s": retry})
            raise RestError(resp.status_code, resp.text)
        if resp.status_code != 200:
            self.errors += 1
            raise RestError(resp.status_code, resp.text)
        return resp.json()

    async def exchange_info(self) -> dict[str, Any]:
        return await self.get("/api/v3/exchangeInfo", weight=WEIGHT_EXCHANGE_INFO)

    async def ticker_24h(self) -> list[dict[str, Any]]:
        return await self.get("/api/v3/ticker/24hr", weight=WEIGHT_TICKER_24H_ALL)

    async def depth(self, symbol: str, limit: int = 1000) -> dict[str, Any]:
        return await self.get("/api/v3/depth", {"symbol": symbol, "limit": limit}, weight=depth_weight(limit))

    async def clock_offset_ms(self) -> tuple[float, float]:
        """Estimate (server - local) wall-clock offset and the round trip, in ms.

        Uses the midpoint of the request; the uncertainty is +/- RTT/2.
        """
        t0w, t0m = wall_ns(), mono_ns()
        body = await self.get("/api/v3/time", weight=WEIGHT_TIME)
        rtt_ns = mono_ns() - t0m
        local_mid_ms = (t0w + rtt_ns / 2) / NS_PER_MS
        return float(body["serverTime"]) - local_mid_ms, rtt_ns / NS_PER_MS
