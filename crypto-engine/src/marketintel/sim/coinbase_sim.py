"""Local Coinbase Advanced Trade protocol simulator (SYNTHETIC DATA ONLY).

Speaks the public market-data subset the engine uses, following the message
schema of Coinbase's official SDK (``coinbase-advanced-py``):

* WebSocket at ``/``: ``{"type": "subscribe", "product_ids": [...],
  "channel": "level2" | "market_trades" | "heartbeats"}``; acknowledgements on
  the ``subscriptions`` channel; envelopes ``{"channel", "client_id",
  "timestamp", "sequence_num", "events"}`` with a per-connection sequence;
  level2 delivered as ``l2_data`` snapshot + update events (sides
  ``bid``/``offer``); ``market_trades`` snapshot + updates; 1 Hz heartbeats.
* Connections that do not subscribe within ``subscribe_deadline_s`` are
  closed; inbound messages beyond ``max_inbound_per_s`` cause an error and
  disconnect.
* REST: ``/api/v3/brokerage/market/products``, ``/api/v3/brokerage/time``,
  ``/api/v3/brokerage/market/product_book``.

Prices come from the shared :class:`MarketWorld`, so they are consistent with
the Binance simulator (plus configurable venue lag and dislocations). The
simulated trade ``side`` is the taker side.
"""

from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass, field
from http import HTTPStatus
from typing import Any
from urllib.parse import parse_qs, urlsplit

import orjson
from websockets.asyncio.server import ServerConnection, broadcast, serve
from websockets.exceptions import ConnectionClosed
from websockets.http11 import Request, Response

from ..numeric import ONE, e8_to_str
from .book_model import SimBook, default_tick_step
from .world import STABLES, MarketWorld

DEFAULT_USD_BASES = [
    "BTC", "ETH", "SOL", "XRP", "ADA", "DOGE", "LTC", "LINK", "AVAX", "DOT", "BCH", "UNI", "XLM",
    "ATOM", "ETC", "FIL", "APT", "ARB", "OP", "NEAR", "INJ", "SUI", "AAVE", "SHIB", "PEPE", "SEI",
    "TIA", "RENDER", "FET", "HBAR", "ICP", "ALGO",
]
DEFAULT_USDT_BASES = ["BTC", "ETH", "SOL", "XRP", "DOGE", "ADA", "LINK", "LTC"]


def fmt(v: int) -> str:
    """Coinbase-style decimal string (no padding zeros)."""
    s = e8_to_str(v).rstrip("0")
    return s[:-1] if s.endswith(".") else s


def rfc3339(t_ns: int) -> str:
    sec, frac = divmod(t_ns, 1_000_000_000)
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(sec)) + f".{frac:09d}Z"


def default_products(world: MarketWorld | None = None) -> list[str]:
    out = [f"{b}-USD" for b in DEFAULT_USD_BASES] + [f"{b}-USDT" for b in DEFAULT_USDT_BASES] + ["USDT-USD"]
    if world is not None:
        out += [f"{a}-USD" for a in world.values if a.startswith("SYN")]
    return out


@dataclass
class CbProduct(SimBook):
    product_id: str = ""
    base: str = ""
    quote: str = ""
    weight: float = 1.0
    alias: str | None = None
    recent_trades: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class _Conn:
    ws: ServerConnection
    subs: dict[str, set[str]] = field(default_factory=dict)
    seq: int = 0
    hb: int = 0
    stamps: list[float] = field(default_factory=list)
    subscribed: asyncio.Event = field(default_factory=asyncio.Event)


class FakeCoinbase:
    def __init__(self, world: MarketWorld | None = None, products: list[str] | None = None, *, seed: int = 9,
                 updates_per_s: float = 800.0, trade_prob: float = 0.35, depth_levels: int = 40,
                 host: str = "127.0.0.1", port: int = 0, step_ms: float = 10.0,
                 subscribe_deadline_s: float = 5.0, max_inbound_per_s: int = 8) -> None:
        self.rng = random.Random(seed)
        self.owns_world = world is None
        self.world = world or MarketWorld(seed)
        self.host, self.port = host, port
        self.updates_per_s = updates_per_s
        self.trade_prob = trade_prob
        self.depth_levels = depth_levels
        self.step_ms = step_ms
        self.subscribe_deadline_s = subscribe_deadline_s
        self.max_inbound_per_s = max_inbound_per_s
        self.products: dict[str, CbProduct] = {}
        for pid in products or default_products(self.world):
            b, q = pid.split("-", 1)
            if b in self.world.values and q in self.world.values:
                self.products[pid] = self._make(pid, b, q)
        # Venue alias (REST only): USDC book served by the USD book.
        if "BTC-USD" in self.products:
            self.alias_products = {"BTC-USDC": "BTC-USD", "ETH-USDC": "ETH-USD"}
        else:
            self.alias_products = {}
        self._names = list(self.products)
        self._weights = [self.products[p].weight for p in self._names]
        self._conns: dict[ServerConnection, _Conn] = {}
        self._server: Any = None
        self._tasks: list[asyncio.Task[None]] = []
        self.paused = False
        self.reject_remaining = 0
        self.reject_status = 429
        self.connections_accepted = 0
        self.deadline_disconnects = 0
        self.inbound_limit_disconnects = 0
        self.rest_requests: dict[str, int] = {}
        self.event_delay_ms = 0
        self.messages_sent = 0

    # ------------------------------------------------------------- set-up
    def _make(self, pid: str, b: str, q: str) -> CbProduct:
        px = self.world.values[b] / self.world.values[q]
        tick, step = default_tick_step(px, b, q)
        weight = 8.0 if pid == "BTC-USD" else 4.0 if pid == "ETH-USD" else 1.0 if q == "USD" else 0.5
        p = CbProduct(tick, step, 1 if weight >= 4 else self.rng.randint(1, 5), product_id=pid, base=b, quote=q,
                      weight=weight)
        p.rebuild(self.mid(p), self.world.values[q], self.rng, self.depth_levels, initial=True)
        return p

    def mid(self, p: CbProduct) -> float:
        return self.world.price(p.base, p.quote, "COINBASE")

    @property
    def ws_url(self) -> str:
        return f"ws://{self.host}:{self.port}"

    @property
    def rest_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    async def start(self) -> None:
        self._server = await serve(self._handler, self.host, self.port, process_request=self._process_request,
                                   ping_interval=20, ping_timeout=60, compression=None, max_queue=64)
        self.port = next(iter(self._server.sockets)).getsockname()[1]
        self._tasks = [asyncio.create_task(self._generate(), name="cb-gen"),
                       asyncio.create_task(self._heartbeats(), name="cb-hb")]

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            try:
                await t
            except asyncio.CancelledError:
                pass
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    async def __aenter__(self) -> FakeCoinbase:
        await self.start()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.stop()

    # ---------------------------------------------------------------- REST
    def _process_request(self, connection: ServerConnection, request: Request) -> Response | None:
        parts = urlsplit(request.path)
        if parts.path.startswith("/api/"):
            return self._rest(connection, parts.path, parse_qs(parts.query))
        if self.reject_remaining > 0:
            self.reject_remaining -= 1
            resp = connection.respond(HTTPStatus(self.reject_status), "rate limited (simulated)\n")
            resp.headers["Retry-After"] = "1"
            return resp
        return None

    def _json(self, connection: ServerConnection, body: Any, status: int = 200) -> Response:
        resp = connection.respond(HTTPStatus(status), orjson.dumps(body).decode())
        resp.headers["Content-Type"] = "application/json"
        return resp

    def _rest(self, connection: ServerConnection, path: str, q: dict[str, list[str]]) -> Response:
        self.rest_requests[path] = self.rest_requests.get(path, 0) + 1
        if path == "/api/v3/brokerage/time":
            now = time.time_ns()
            return self._json(connection, {"iso": rfc3339(now), "epochSeconds": str(now // 10**9),
                                           "epochMillis": str(now // 10**6)})
        if path == "/api/v3/brokerage/market/products":
            prods = [self._product_json(p) for p in self.products.values()]
            for alias, target in self.alias_products.items():
                d = self._product_json(self.products[target])
                d.update(product_id=alias, quote_currency_id="USDC", quote_display_symbol="USDC", alias=target)
                prods.append(d)
            return self._json(connection, {"products": prods, "num_products": len(prods)})
        if path == "/api/v3/brokerage/market/product_book":
            p = self.products.get((q.get("product_id") or [""])[0])
            if p is None:
                return self._json(connection, {"error": "NOT_FOUND", "message": "product not found"}, 404)
            lim = int((q.get("limit") or ["50"])[0])
            return self._json(connection, {"pricebook": {
                "product_id": p.product_id,
                "bids": [{"price": fmt(px), "size": fmt(qq)} for px, qq in sorted(p.bids.items(), reverse=True)[:lim]],
                "asks": [{"price": fmt(px), "size": fmt(qq)} for px, qq in sorted(p.asks.items())[:lim]],
                "time": rfc3339(time.time_ns())}})
        return self._json(connection, {"error": "NOT_FOUND", "message": "not simulated"}, 404)

    def _product_json(self, p: CbProduct) -> dict[str, Any]:
        mid = self.mid(p)
        return {
            "product_id": p.product_id, "price": f"{mid:.8f}", "volume_24h": f"{p.weight * 1e5 / max(mid, 1e-9):.8f}",
            "approximate_quote_24h_volume": f"{p.weight * 1e7:.2f}",
            "base_increment": fmt(p.step), "quote_increment": fmt(p.tick), "price_increment": fmt(p.tick),
            "quote_min_size": "1", "quote_max_size": "10000000", "base_min_size": fmt(p.step),
            "base_max_size": "100000000", "base_name": p.base, "quote_name": p.quote, "status": "online",
            "cancel_only": False, "limit_only": False, "post_only": False, "trading_disabled": False,
            "auction_mode": False, "is_disabled": False, "view_only": False, "product_type": "SPOT",
            "quote_currency_id": p.quote, "base_currency_id": p.base, "base_display_symbol": p.base,
            "quote_display_symbol": p.quote, "alias": "", "alias_to": [], "product_venue": "CBE",
        }

    # ----------------------------------------------------------- WebSocket
    def _send(self, c: _Conn, channel: str, events: list[dict[str, Any]], ts: str | None = None) -> None:
        if self.paused:
            return
        msg = {"channel": channel, "client_id": "", "timestamp": ts or rfc3339(time.time_ns() - self.event_delay_ms * 10**6),
               "sequence_num": c.seq, "events": events}
        c.seq += 1
        broadcast([c.ws], orjson.dumps(msg).decode())
        self.messages_sent += 1

    async def _handler(self, ws: ServerConnection) -> None:
        self.connections_accepted += 1
        c = _Conn(ws)
        self._conns[ws] = c
        deadline = asyncio.create_task(self._enforce_deadline(c))
        try:
            async for raw in ws:
                now = time.monotonic()
                c.stamps = [t for t in c.stamps if now - t < 1.0] + [now]
                if len(c.stamps) > self.max_inbound_per_s:
                    self.inbound_limit_disconnects += 1
                    await ws.send(orjson.dumps({"type": "error", "message": "rate limit exceeded"}).decode())
                    await ws.close(1008, "rate limit")
                    break
                self._control(c, raw)
        except ConnectionClosed:
            pass
        finally:
            deadline.cancel()
            self._conns.pop(ws, None)

    async def _enforce_deadline(self, c: _Conn) -> None:
        try:
            await asyncio.wait_for(c.subscribed.wait(), self.subscribe_deadline_s)
        except TimeoutError:
            self.deadline_disconnects += 1
            await c.ws.close(1008, "no subscription")

    def _control(self, c: _Conn, raw: str | bytes) -> None:
        try:
            req = orjson.loads(raw)
            typ, channel = req["type"], req["channel"]
            pids = list(req.get("product_ids") or [])
        except Exception:
            broadcast([c.ws], orjson.dumps({"type": "error", "message": "failure to parse message"}).decode())
            return
        unknown = [p for p in pids if p not in self.products]
        if channel not in ("level2", "market_trades", "heartbeats", "ticker") or unknown:
            broadcast([c.ws], orjson.dumps({"type": "error", "message": f"invalid subscription {channel} {unknown}"}).decode())
            return
        subs = c.subs.setdefault(channel, set())
        if typ == "subscribe":
            new = [p for p in pids if p not in subs]
            subs.update(pids)
            c.subscribed.set()
        elif typ == "unsubscribe":
            subs.difference_update(pids)
            new = []
        else:
            return
        self._send(c, "subscriptions", [{"subscriptions": {k: sorted(v) for k, v in c.subs.items()}}])
        if channel == "level2":
            for pid in new:
                p = self.products[pid]
                ts = rfc3339(time.time_ns())
                ups = [{"side": "bid", "event_time": ts, "price_level": fmt(px), "new_quantity": fmt(q)}
                       for px, q in sorted(p.bids.items(), reverse=True)]
                ups += [{"side": "offer", "event_time": ts, "price_level": fmt(px), "new_quantity": fmt(q)}
                        for px, q in sorted(p.asks.items())]
                self._send(c, "l2_data", [{"type": "snapshot", "product_id": pid, "updates": ups}])
        elif channel == "market_trades" and new:
            hist = [t for pid in new for t in self.products[pid].recent_trades[-5:]]
            self._send(c, "market_trades", [{"type": "snapshot", "trades": hist}])

    # ---------------------------------------------------------- generation
    def step(self, dt_s: float, n_updates: int) -> None:
        if self.owns_world:
            self.world.step(dt_s)
        else:
            self.world.advance_to_wall()
        if not self._names or n_updates <= 0:
            return
        now = time.time_ns() - self.event_delay_ms * 10**6
        ts = rfc3339(now)
        touched: dict[str, CbProduct] = {}
        trades: dict[str, list[dict[str, Any]]] = {}
        for pid in self.rng.choices(self._names, weights=self._weights, k=n_updates):
            p = self.products[pid]
            p.rebuild(self.mid(p), self.world.values[p.quote], self.rng, self.depth_levels)
            if self.rng.random() < self.trade_prob:
                buy = self.rng.random() < 0.5
                px, q = p.take(buy, self.rng)
                t = {"trade_id": str(p.trade_id), "product_id": pid, "price": fmt(px), "size": fmt(q),
                     "side": "BUY" if buy else "SELL", "time": ts}
                p.recent_trades = (p.recent_trades + [t])[-20:]
                trades.setdefault(pid, []).append(t)
            touched[pid] = p
        for pid, p in touched.items():
            cb, ca = p.take_changes()
            ups = [{"side": "bid", "event_time": ts, "price_level": fmt(px), "new_quantity": fmt(q)} for px, q in cb.items()]
            ups += [{"side": "offer", "event_time": ts, "price_level": fmt(px), "new_quantity": fmt(q)} for px, q in ca.items()]
            for c in list(self._conns.values()):
                if pid in c.subs.get("level2", ()) and ups:
                    self._send(c, "l2_data", [{"type": "update", "product_id": pid, "updates": ups}], ts)
                if pid in trades and pid in c.subs.get("market_trades", ()):
                    self._send(c, "market_trades", [{"type": "update", "trades": trades[pid]}], ts)

    async def _generate(self) -> None:
        dt = self.step_ms / 1000
        carry = 0.0
        last = time.monotonic()
        while True:
            await asyncio.sleep(dt)
            now = time.monotonic()
            elapsed, last = now - last, now
            carry += self.updates_per_s * elapsed
            n = int(carry)
            carry -= n
            self.step(elapsed, n)

    async def _heartbeats(self) -> None:
        while True:
            await asyncio.sleep(1.0)
            ts_ns = time.time_ns()
            for c in list(self._conns.values()):
                if c.subs.get("heartbeats"):
                    c.hb += 1
                    self._send(c, "heartbeats", [{"current_time": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(ts_ns // 10**9))
                                                  + f".{ts_ns % 10**9:09d} +0000 UTC", "heartbeat_counter": str(c.hb)}])

    # --------------------------------------------------------------- faults
    @property
    def open_connections(self) -> int:
        return len(self._conns)

    def drop_all_connections(self) -> int:
        n = 0
        for ws in list(self._conns):
            ws.transport.abort()
            n += 1
        return n

    def reject_next_handshakes(self, n: int, status: int = 429) -> None:
        self.reject_remaining, self.reject_status = n, status

    def inject_sequence_gap(self, skip: int = 3) -> None:
        for c in self._conns.values():
            c.seq += skip

    def inject_crossed(self, pid: str) -> None:
        p = self.products[pid]
        ap = min(p.asks)
        ts = rfc3339(time.time_ns())
        for c in list(self._conns.values()):
            if pid in c.subs.get("level2", ()):
                self._send(c, "l2_data", [{"type": "update", "product_id": pid, "updates": [
                    {"side": "bid", "event_time": ts, "price_level": fmt(ap + p.tick), "new_quantity": fmt(p.step)}]}], ts)

    def send_error(self, message: str = "simulated server error") -> None:
        broadcast(list(self._conns), orjson.dumps({"type": "error", "message": message}).decode())

    def send_invalid(self) -> None:
        broadcast(list(self._conns), "{not json")


__all__ = ["FakeCoinbase", "default_products", "rfc3339", "fmt", "ONE", "STABLES"]
