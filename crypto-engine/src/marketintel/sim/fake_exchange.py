"""Local Binance-protocol simulator (SYNTHETIC DATA ONLY).

Serves, on one localhost port, the subset of Binance's public spot API that
the engine uses, byte-compatible with the official formats:

* WebSocket ``/stream?streams=...`` combined streams and ``/ws/<stream>`` raw
  streams, plus ``SUBSCRIBE``/``UNSUBSCRIBE``/``LIST_SUBSCRIPTIONS`` control
  messages (and the 5-messages/second inbound limit);
* ``<sym>@bookTicker``, ``<sym>@trade``, ``<sym>@depth@100ms``, ``serverShutdown``;
* REST ``/api/v3/ping``, ``/time``, ``/exchangeInfo``, ``/ticker/24hr``, ``/depth``.

Prices come from a seeded random walk of synthetic asset values, so cross
rates are internally consistent (ETHBTC ~= ETHUSDT / BTCUSDT) and runs are
reproducible. Nothing here is real market data; the engine labels any session
connected to it ``SIMULATED``.

Fault injection hooks exist for every failure mode the engine must survive:
abrupt disconnects, server shutdown notices, stalls, handshake rate limiting,
crossed books, out-of-order and duplicate updates, trade-id and depth gaps,
and malformed frames.
"""

from __future__ import annotations

import asyncio
import math
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

# Synthetic reference values (USDT). Only used to make the simulation
# numerically realistic; they are not quotes.
_SEED_VALUES: dict[str, float] = {
    "BTC": 60000.0, "ETH": 3000.0, "BNB": 550.0, "SOL": 150.0, "XRP": 0.55, "USDC": 1.0,
    "FDUSD": 1.0, "ADA": 0.45, "DOGE": 0.12, "TRX": 0.12, "LINK": 14.0, "AVAX": 30.0,
    "DOT": 6.5, "LTC": 75.0, "BCH": 380.0, "UNI": 8.0, "XLM": 0.1, "ATOM": 7.0, "ETC": 22.0,
    "FIL": 4.5, "APT": 7.5, "ARB": 0.8, "OP": 1.7, "NEAR": 5.0, "INJ": 22.0, "SUI": 1.0,
    "AAVE": 95.0, "TON": 6.0, "SHIB": 0.00002, "PEPE": 0.00001, "WIF": 2.0, "SEI": 0.4,
    "TIA": 6.0, "RNDR": 7.0, "FET": 1.3, "HBAR": 0.07, "ICP": 9.0, "ALGO": 0.15, "VET": 0.025,
    "SAND": 0.35, "MANA": 0.35, "GALA": 0.025, "EGLD": 30.0, "THETA": 1.5, "AXS": 6.0,
    "RUNE": 4.5, "LDO": 1.8, "CRV": 0.35, "MKR": 2200.0, "ENS": 18.0, "JUP": 0.9,
    "PENDLE": 4.5, "ORDI": 35.0, "STX": 1.7, "IMX": 1.5, "KAS": 0.15, "GRT": 0.2, "QNT": 70.0,
    "FLOW": 0.6, "CHZ": 0.07, "KAVA": 0.4,
}
_STABLES = {"USDT", "USDC", "FDUSD"}
_CROSSES = ["ETHBTC", "BNBBTC", "BNBETH", "SOLBTC", "XRPBTC", "BTCUSDC", "ETHUSDC",
            "USDCUSDT", "FDUSDUSDT", "BTCFDUSD"]
_QUOTES = ("USDT", "USDC", "FDUSD", "BTC", "ETH", "BNB")


def split_symbol(sym: str) -> tuple[str, str]:
    for q in _QUOTES:
        if sym.endswith(q) and len(sym) > len(q):
            return sym[: -len(q)], q
    raise ValueError(f"cannot split {sym}")


def default_symbols(n_usdt: int = 60) -> list[str]:
    bases = [a for a in _SEED_VALUES if a not in _STABLES][:n_usdt]
    return [f"{b}USDT" for b in bases] + _CROSSES


def _pow10_e8(exp: int) -> int:
    """10**exp expressed in e8 units, clamped to [1e-8, 1]."""
    exp = max(-8, min(0, exp))
    return 10 ** (8 + exp)


@dataclass
class SimSymbol:
    symbol: str
    base: str
    quote: str
    tick: int
    step: int
    min_notional: int
    spread_ticks: int
    weight: float
    update_id: int = 1000
    trade_id: int = 5000
    bids: dict[int, int] = field(default_factory=dict)
    asks: dict[int, int] = field(default_factory=dict)
    changed_bids: dict[int, int] = field(default_factory=dict)
    changed_asks: dict[int, int] = field(default_factory=dict)
    depth_next_first: int = 1001
    last_bt: dict[str, Any] | None = None
    volume_quote: float = 0.0


class FakeBinance:
    def __init__(
        self,
        symbols: list[str] | None = None,
        *,
        seed: int = 7,
        updates_per_s: float = 2000.0,
        trade_prob: float = 0.35,
        depth_levels: int = 20,
        vol_per_sqrt_s: float = 0.0004,
        host: str = "127.0.0.1",
        port: int = 0,
        step_ms: float = 10.0,
    ) -> None:
        self.rng = random.Random(seed)
        self.host = host
        self.port = port
        self.updates_per_s = updates_per_s
        self.trade_prob = trade_prob
        self.depth_levels = depth_levels
        self.vol = vol_per_sqrt_s
        self.step_ms = step_ms
        self.values = dict(_SEED_VALUES)
        self.values["USDT"] = 1.0
        self.syms: dict[str, SimSymbol] = {}
        for s in symbols or default_symbols():
            base, quote = split_symbol(s)
            if base not in self.values or quote not in self.values:
                continue
            self.syms[s] = self._make_symbol(s, base, quote)
        self._names = list(self.syms)
        self._weights = [self.syms[s].weight for s in self._names]
        self._subs: dict[str, set[ServerConnection]] = {}
        self._conn_subs: dict[ServerConnection, set[str]] = {}
        self._conn_msgs: dict[ServerConnection, list[float]] = {}
        self._server: Any = None
        self._gen_task: asyncio.Task[None] | None = None
        self._depth_task: asyncio.Task[None] | None = None
        self.paused = False
        self.reject_remaining = 0
        self.reject_status = 429
        self.connections_accepted = 0
        self.handshakes_rejected = 0
        self.frames_sent = 0
        self.rest_requests: dict[str, int] = {}
        self.inbound_limit_disconnects = 0
        self.snapshot_delay_s = 0.0
        # Make event times look this many ms old (simulates delayed delivery).
        self.event_delay_ms = 0

    # ------------------------------------------------------------- set-up
    def _make_symbol(self, s: str, base: str, quote: str) -> SimSymbol:
        px = self.values[base] / self.values[quote]
        tick = _pow10_e8(math.floor(math.log10(px)) - 4)
        step = _pow10_e8(math.floor(-math.log10(px)) - 1) if px < 1e7 else 1
        if base in _STABLES and quote in _STABLES:
            tick = _pow10_e8(-4)
            step = _pow10_e8(0)
        weight = 10.0 if s == "BTCUSDT" else 5.0 if s == "ETHUSDT" else 2.0 if quote == "USDT" else 1.0
        min_notional_quote = 5.0 / self.values[quote]
        sym = SimSymbol(s, base, quote, tick, step, max(1, int(min_notional_quote * ONE)),
                        spread_ticks=1 if weight >= 5 else self.rng.randint(1, 4), weight=weight)
        self._rebuild(sym, initial=True)
        sym.depth_next_first = sym.update_id + 1
        return sym

    def mid(self, sym: SimSymbol) -> float:
        return self.values[sym.base] / self.values[sym.quote]

    def _rebuild(self, sym: SimSymbol, initial: bool = False) -> None:
        """Regenerate the top ``depth_levels`` around the current fair mid,
        recording level changes for the next depth diff."""
        mid_e8 = int(self.mid(sym) * ONE)
        half = sym.spread_ticks * sym.tick / 2
        best_bid = int((mid_e8 - half) // sym.tick) * sym.tick
        best_bid = max(sym.tick, best_bid)
        best_ask = best_bid + sym.spread_ticks * sym.tick
        new_bids = {}
        new_asks = {}
        notional_target = 20000.0 * self.rng.uniform(0.3, 1.7) / self.values[sym.quote]
        for i in range(self.depth_levels):
            for side, px in ((new_bids, best_bid - i * sym.tick), (new_asks, best_ask + i * sym.tick)):
                if px <= 0:
                    continue
                old = (sym.bids if side is new_bids else sym.asks).get(px)
                if old is not None and self.rng.random() < 0.8:
                    side[px] = old
                    continue
                qty_units = notional_target * self.rng.lognormvariate(0, 0.6) / (px / ONE)
                q = max(sym.step, int(qty_units * ONE) // sym.step * sym.step)
                side[px] = q
        if not initial:
            for old_book, new_book, changed in ((sym.bids, new_bids, sym.changed_bids),
                                                (sym.asks, new_asks, sym.changed_asks)):
                for p in old_book:
                    if p not in new_book:
                        changed[p] = 0
                for p, q in new_book.items():
                    if old_book.get(p) != q:
                        changed[p] = q
        sym.bids, sym.asks = new_bids, new_asks
        sym.update_id += 1

    # ----------------------------------------------------------- servers
    @property
    def ws_url(self) -> str:
        return f"ws://{self.host}:{self.port}"

    @property
    def rest_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    async def start(self) -> None:
        self._server = await serve(
            self._handler, self.host, self.port, process_request=self._process_request,
            ping_interval=20, ping_timeout=60, compression=None, max_queue=64,
        )
        sock = next(iter(self._server.sockets))
        self.port = sock.getsockname()[1]
        self._gen_task = asyncio.create_task(self._generate(), name="sim-generator")
        self._depth_task = asyncio.create_task(self._depth_loop(), name="sim-depth")

    async def stop(self) -> None:
        for t in (self._gen_task, self._depth_task):
            if t is not None:
                t.cancel()
        for t in (self._gen_task, self._depth_task):
            if t is not None:
                try:
                    await t
                except asyncio.CancelledError:
                    pass
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    async def __aenter__(self) -> "FakeBinance":
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
            self.handshakes_rejected += 1
            resp = connection.respond(HTTPStatus(self.reject_status), "rate limited (simulated)\n")
            resp.headers["Retry-After"] = "1"
            return resp
        return None

    def _json(self, connection: ServerConnection, body: Any, weight: int, status: int = 200) -> Response:
        resp = connection.respond(HTTPStatus(status), orjson.dumps(body).decode())
        resp.headers["Content-Type"] = "application/json"
        resp.headers["X-MBX-USED-WEIGHT-1M"] = str(weight)
        return resp

    def _rest(self, connection: ServerConnection, path: str, q: dict[str, list[str]]) -> Response:
        self.rest_requests[path] = self.rest_requests.get(path, 0) + 1
        if path == "/api/v3/ping":
            return self._json(connection, {}, 1)
        if path == "/api/v3/time":
            return self._json(connection, {"serverTime": int(time.time() * 1000)}, 1)
        if path == "/api/v3/exchangeInfo":
            return self._json(connection, self.exchange_info(), 20)
        if path == "/api/v3/ticker/24hr":
            return self._json(connection, [
                {"symbol": s.symbol, "quoteVolume": f"{s.weight * 1e7 * self.values[s.quote]:.8f}"}
                for s in self.syms.values()], 80)
        if path == "/api/v3/depth":
            sym = self.syms.get((q.get("symbol") or [""])[0])
            if sym is None:
                return self._json(connection, {"code": -1121, "msg": "Invalid symbol."}, 1, 400)
            limit = int((q.get("limit") or ["100"])[0])
            return self._json(connection, self.depth_snapshot(sym, limit), 5)
        return self._json(connection, {"code": -1, "msg": "not simulated"}, 1, 404)

    def exchange_info(self) -> dict[str, Any]:
        out = []
        for s in self.syms.values():
            out.append({
                "symbol": s.symbol, "status": "TRADING", "baseAsset": s.base, "quoteAsset": s.quote,
                "baseAssetPrecision": 8, "quoteAssetPrecision": 8, "isSpotTradingAllowed": True,
                "filters": [
                    {"filterType": "PRICE_FILTER", "minPrice": e8_to_str(s.tick),
                     "maxPrice": "1000000.00000000", "tickSize": e8_to_str(s.tick)},
                    {"filterType": "LOT_SIZE", "minQty": e8_to_str(s.step),
                     "maxQty": "9000000000.00000000", "stepSize": e8_to_str(s.step)},
                    {"filterType": "NOTIONAL", "minNotional": e8_to_str(s.min_notional),
                     "applyMinToMarket": True, "maxNotional": "9000000.00000000",
                     "applyMaxToMarket": False, "avgPriceMins": 5},
                ],
            })
        return {"timezone": "UTC", "serverTime": int(time.time() * 1000), "rateLimits": [], "symbols": out}

    def depth_snapshot(self, sym: SimSymbol, limit: int) -> dict[str, Any]:
        bids = sorted(sym.bids.items(), reverse=True)[:limit]
        asks = sorted(sym.asks.items())[:limit]
        # Pending (unpublished) changes are already part of the book state.
        return {
            "lastUpdateId": sym.update_id,
            "bids": [[e8_to_str(p), e8_to_str(q)] for p, q in bids],
            "asks": [[e8_to_str(p), e8_to_str(q)] for p, q in asks],
        }

    # ----------------------------------------------------------- WebSocket
    async def _handler(self, conn: ServerConnection) -> None:
        self.connections_accepted += 1
        parts = urlsplit(conn.request.path if conn.request else "")
        streams: list[str] = []
        if parts.path == "/stream":
            for v in parse_qs(parts.query).get("streams", []):
                streams.extend(x for x in v.split("/") if x)
        elif parts.path.startswith("/ws/"):
            streams.extend(x for x in parts.path[4:].split("/") if x)
        self._conn_subs[conn] = set()
        self._conn_msgs[conn] = []
        self._subscribe(conn, streams)
        try:
            async for msg in conn:
                now = time.monotonic()
                stamps = [t for t in self._conn_msgs[conn] if now - t < 1.0]
                stamps.append(now)
                self._conn_msgs[conn] = stamps
                if len(stamps) > 5:
                    self.inbound_limit_disconnects += 1
                    await conn.close(1008, "Too many requests")
                    break
                await self._control(conn, msg)
        except ConnectionClosed:
            pass
        finally:
            for st in self._conn_subs.pop(conn, set()):
                self._subs.get(st, set()).discard(conn)
            self._conn_msgs.pop(conn, None)

    def _subscribe(self, conn: ServerConnection, streams: list[str]) -> None:
        for st in streams:
            self._subs.setdefault(st, set()).add(conn)
            self._conn_subs[conn].add(st)

    async def _control(self, conn: ServerConnection, msg: str | bytes) -> None:
        try:
            req = orjson.loads(msg)
            method = req["method"]
            rid = req.get("id")
        except Exception:
            await conn.send(orjson.dumps({"error": {"code": 3, "msg": "Invalid JSON"}, "id": None}).decode())
            return
        if method == "SUBSCRIBE":
            self._subscribe(conn, list(req.get("params", [])))
            await conn.send(orjson.dumps({"result": None, "id": rid}).decode())
        elif method == "UNSUBSCRIBE":
            for st in req.get("params", []):
                self._subs.get(st, set()).discard(conn)
                self._conn_subs[conn].discard(st)
            await conn.send(orjson.dumps({"result": None, "id": rid}).decode())
        elif method == "LIST_SUBSCRIPTIONS":
            await conn.send(orjson.dumps({"result": sorted(self._conn_subs[conn]), "id": rid}).decode())
        else:
            await conn.send(orjson.dumps({"error": {"code": 2, "msg": "Invalid request"}, "id": rid}).decode())

    def _send(self, stream: str, data: dict[str, Any]) -> bool:
        conns = self._subs.get(stream)
        if not conns or self.paused:
            return False
        frame = orjson.dumps({"stream": stream, "data": data}).decode()
        broadcast(conns, frame)
        self.frames_sent += len(conns)
        return True

    # ---------------------------------------------------------- generation
    def _evolve(self, dt_s: float) -> None:
        sd = self.vol * math.sqrt(dt_s)
        btc_shock = self.rng.gauss(0, sd)
        for a in self.values:
            if a == "USDT":
                continue
            if a in _STABLES:
                # Mean-reverting around 1 with tiny noise.
                self.values[a] += (1.0 - self.values[a]) * 0.05 + self.rng.gauss(0, 2e-6)
                continue
            beta = 1.0 if a == "BTC" else 0.8
            idio = self.rng.gauss(0, sd * 0.6) if a != "BTC" else 0.0
            self.values[a] *= math.exp(beta * btc_shock + idio)

    def step(self, dt_s: float, n_updates: int) -> None:
        """Advance the simulation and publish ``n_updates`` symbol updates."""
        self._evolve(dt_s)
        if not self._names or n_updates <= 0:
            return
        now_ms = int(time.time() * 1000) - self.event_delay_ms
        for name in self.rng.choices(self._names, weights=self._weights, k=n_updates):
            sym = self.syms[name]
            self._rebuild(sym)
            if self.rng.random() < self.trade_prob:
                self._trade(sym, now_ms)
            self._book_ticker(sym)

    def _trade(self, sym: SimSymbol, now_ms: int) -> None:
        buy = self.rng.random() < 0.5
        book = sym.asks if buy else sym.bids
        px = min(book) if buy else max(book)
        top = book[px]
        q = max(sym.step, int(top * self.rng.uniform(0.01, 0.5)) // sym.step * sym.step)
        if top - q >= sym.step:
            book[px] = top - q
            (sym.changed_asks if buy else sym.changed_bids)[px] = top - q
            sym.update_id += 1
        sym.trade_id += 1
        sym.volume_quote += q * px / 1e16
        self._send(f"{sym.symbol.lower()}@trade", {
            "e": "trade", "E": now_ms, "s": sym.symbol, "t": sym.trade_id,
            "p": e8_to_str(px), "q": e8_to_str(q), "T": now_ms, "m": not buy, "M": True,
        })

    def _book_ticker(self, sym: SimSymbol) -> None:
        bp = max(sym.bids)
        ap = min(sym.asks)
        data = {"u": sym.update_id, "s": sym.symbol, "b": e8_to_str(bp), "B": e8_to_str(sym.bids[bp]),
                "a": e8_to_str(ap), "A": e8_to_str(sym.asks[ap])}
        if self._send(f"{sym.symbol.lower()}@bookTicker", data):
            sym.last_bt = data  # last bookTicker actually delivered

    def emit_depth(self) -> None:
        now_ms = int(time.time() * 1000) - self.event_delay_ms
        for sym in self.syms.values():
            if sym.update_id < sym.depth_next_first:
                continue
            stream = f"{sym.symbol.lower()}@depth@100ms"
            data = {
                "e": "depthUpdate", "E": now_ms, "s": sym.symbol,
                "U": sym.depth_next_first, "u": sym.update_id,
                "b": [[e8_to_str(p), e8_to_str(q)] for p, q in sym.changed_bids.items()],
                "a": [[e8_to_str(p), e8_to_str(q)] for p, q in sym.changed_asks.items()],
            }
            sym.changed_bids = {}
            sym.changed_asks = {}
            sym.depth_next_first = sym.update_id + 1
            self._send(stream, data)

    async def _generate(self) -> None:
        dt = self.step_ms / 1000
        carry = 0.0
        last = time.monotonic()
        while True:
            await asyncio.sleep(dt)
            now = time.monotonic()
            elapsed = now - last
            last = now
            carry += self.updates_per_s * elapsed
            n = int(carry)
            carry -= n
            self.step(elapsed, n)

    async def _depth_loop(self) -> None:
        while True:
            await asyncio.sleep(0.1)
            self.emit_depth()

    # --------------------------------------------------------------- faults
    @property
    def open_connections(self) -> int:
        return len(self._conn_subs)

    def drop_all_connections(self) -> int:
        """Abort every TCP connection without a close frame (network failure)."""
        n = 0
        for conn in list(self._conn_subs):
            conn.transport.abort()
            n += 1
        return n

    async def server_shutdown(self, close_after_s: float = 0.5) -> None:
        msg = orjson.dumps({"stream": "!serverShutdown",
                            "data": {"e": "serverShutdown", "E": int(time.time() * 1000)}}).decode()
        old = list(self._conn_subs)
        broadcast(old, msg)
        await asyncio.sleep(close_after_s)
        for conn in old:
            await conn.close(1001, "server shutdown")

    def reject_next_handshakes(self, n: int, status: int = 429) -> None:
        self.reject_remaining = n
        self.reject_status = status

    def inject_crossed(self, symbol: str) -> None:
        sym = self.syms[symbol]
        sym.update_id += 1
        bp = max(sym.bids)
        data = {"u": sym.update_id, "s": symbol, "b": e8_to_str(bp + 2 * sym.tick), "B": "1.00000000",
                "a": e8_to_str(bp), "A": "1.00000000"}
        if self._send(f"{symbol.lower()}@bookTicker", data):
            sym.last_bt = data

    def inject_out_of_order(self, symbol: str) -> None:
        """Re-send the last delivered bookTicker with an older update id."""
        sym = self.syms[symbol]
        if sym.last_bt is not None:
            old = dict(sym.last_bt)
            old["u"] = old["u"] - 1
            self._send(f"{symbol.lower()}@bookTicker", old)

    def inject_trade_gap(self, symbol: str, missing: int = 5) -> None:
        self.syms[symbol].trade_id += missing

    def inject_depth_gap(self, symbol: str) -> None:
        sym = self.syms[symbol]
        self.emit_depth()           # flush, then silently lose some updates
        sym.update_id += 5
        sym.depth_next_first = sym.update_id + 1
        sym.changed_bids = {}
        sym.changed_asks = {}

    def inject_invalid_frames(self) -> None:
        conns = list(self._conn_subs)
        broadcast(conns, "this is not json")
        broadcast(conns, orjson.dumps({"stream": "btcusdt@trade", "data": {"e": "trade", "s": "BTCUSDT"}}).decode())
        broadcast(conns, orjson.dumps({"stream": "btcusdt@bookTicker", "data": {
            "u": 1, "s": "BTCUSDT", "b": "abc", "B": "1", "a": "2", "A": "1"}}).decode())
