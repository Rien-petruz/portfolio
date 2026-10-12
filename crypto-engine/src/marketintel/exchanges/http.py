"""Read-only HTTP client for public exchange endpoints.

Off the hot path only: metadata at start-up, order-book snapshots for
resynchronisation, server-time sampling. Enforces:

* GET only - any other method raises :class:`PaperOnlyViolation` from a
  request hook, i.e. even code holding the underlying ``httpx`` client cannot
  send a POST/DELETE to an exchange;
* no credential headers;
* a local request-weight budget per minute, plus honouring 429/418 +
  ``Retry-After``.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

from ..safety import PaperOnlyViolation

log = logging.getLogger(__name__)

_FORBIDDEN_HEADERS = ("x-mbx-apikey", "cb-access-key", "cb-access-sign", "authorization")


async def _guard(request: httpx.Request) -> None:
    if request.method != "GET":
        raise PaperOnlyViolation(f"refusing {request.method} {request.url}: read-only market-data client")
    for h in _FORBIDDEN_HEADERS:
        if h in request.headers:
            raise PaperOnlyViolation(f"refusing request carrying credential header {h!r}")


class HttpError(RuntimeError):
    def __init__(self, status: int, body: str) -> None:
        super().__init__(f"HTTP {status}: {body[:200]}")
        self.status = status


class ReadOnlyHttp:
    def __init__(self, base_url: str, *, timeout_s: float = 10.0, weight_budget_per_min: int = 1000,
                 used_weight_header: str | None = None) -> None:
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout_s,
                                         event_hooks={"request": [_guard]},
                                         headers={"User-Agent": "marketintel-paper/1.0"})
        self.weight_budget = weight_budget_per_min
        self.used_weight = 0
        self._used_header = used_weight_header
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
        if self._used_header:
            used = resp.headers.get(self._used_header)
            if used is not None and used.isdigit():
                self.used_weight = max(self.used_weight, int(used))
        if resp.status_code in (418, 429):
            self.errors += 1
            retry = resp.headers.get("retry-after", "60")
            self._banned_until = time.monotonic() + (float(retry) if retry.replace(".", "", 1).isdigit() else 60.0)
            log.error("REST rate limited", extra={"status": resp.status_code, "retry_after_s": retry})
            raise HttpError(resp.status_code, resp.text)
        if resp.status_code != 200:
            self.errors += 1
            raise HttpError(resp.status_code, resp.text)
        return resp.json()

    def stats(self) -> dict[str, Any]:
        return {"requests": self.requests, "errors": self.errors, "used_weight": self.used_weight,
                "weight_budget": self.weight_budget}
