"""HTTP + WebSocket API for the dashboard and operators.

* Read endpoints only read in-memory state (microseconds); none performs
  exchange I/O. Every payload carries ``data_source`` and the paper-trading
  banner so simulated/replayed data and simulated results are never
  mistaken for live trading.
* ``/api/stream`` (WebSocket) pushes the overview at the engine's summary
  cadence (default 1 s). Slow clients get dropped updates (bounded queue),
  never back-pressure on the engine.
* The only write endpoints control the *simulation* (emergency stop /
  resume). They require ``X-Control-Token`` matching ``api.control_token``
  and are disabled when no token is configured. No endpoint can place an
  exchange order: no such capability exists.
"""

from __future__ import annotations

import asyncio
import math
import os
import secrets
from typing import TYPE_CHECKING, Any, Literal

import orjson
from fastapi import FastAPI, Header, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

from .. import __version__
from ..safety import EXECUTION_MODE, PAPER_BANNER

if TYPE_CHECKING:
    from ..engine import Engine

SortKey = Literal["key", "symbol", "venue", "spread_bps", "book_age_ms", "book_updates", "trades", "touch_imbalance",
                  "status", "anomaly_score", "return_5s_bps", "vol_1s_bps", "liquidity"]


def clean(x: Any) -> Any:
    """JSON-safe: non-finite floats -> None (recursively)."""
    if isinstance(x, float):
        return x if math.isfinite(x) else None
    if isinstance(x, dict):
        return {k: clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [clean(v) for v in x]
    return x


def overview(engine: Engine) -> dict[str, Any]:
    h = engine.health_cache or engine.health()
    now = engine.clock.mono()
    refs = {}
    for k in ("BINANCE:BTCUSDT", "COINBASE:BTC-USD", "COINBASE:BTC-USDT"):
        st = engine.state.instruments.get(k)
        if st is not None:
            r = engine.state.row(st, now)
            refs[k] = {f: r[f] for f in ("bid", "ask", "mid", "spread_bps", "status", "book_age_ms", "exchange_time_ms")}
    lat = engine.metrics.report(("ingest.recv_to_state", "xex.recv_to_signal", "paper.recv_to_submit",
                                 "features.sample", "exchange.event_to_recv"), lifetime=False)
    pick = {name: rep["window"] for name, rep in lat.items()}
    pick["event_loop_lag"] = engine.loop_lag.hist.summary()["window"]
    out: dict[str, Any] = {"health": h, "reference": refs, "latency_us": pick, "version": __version__}
    xex, tri, an, pat, paper = (engine.component(n) for n in ("cross_exchange", "triangular", "anomalies",
                                                                 "patterns", "paper"))
    if xex is not None:
        out["cross_exchange"] = {**xex.tracker.stats(), "pairs": len(xex.pairs)}
    if tri is not None:
        out["triangular"] = {**tri.tracker.stats(), "routes": len(tri.routes)}
    if an is not None:
        out["anomalies"] = {"counts": an.counts, "active": sum(
            1 for s in an.recent if now - s.detected_mono_ns < 30e9)}
    if pat is not None:
        out["patterns"] = {"counts": pat.counts}
    if paper is not None and paper.portfolio.initialized:
        v = paper.portfolio.valuation()
        out["paper"] = {k: v[k] for k in ("equity_usd", "pnl_usd", "realized_usd", "unrealized_usd", "fees_usd",
                                          "total_exposure_usd")}
        out["paper"]["halted"] = paper.risk.halted
        out["paper"]["counters"] = paper.counters
    return out


def create_app(engine: Engine) -> FastAPI:
    app = FastAPI(title="Market Intelligence Engine (paper trading only)", version=__version__)
    subscribers: set[asyncio.Queue[str]] = set()

    def envelope(payload: dict[str, Any]) -> Response:
        # orjson maps NaN/inf to null and is ~10x faster than the stdlib encoder.
        body = orjson.dumps({"data_source": engine.data_source.value, "execution_mode": EXECUTION_MODE,
                             "banner": PAPER_BANNER, **payload},
                            option=orjson.OPT_SERIALIZE_NUMPY | orjson.OPT_NON_STR_KEYS, default=str)
        return Response(body, media_type="application/json")

    def comp(name: str) -> Any:
        c = engine.component(name)
        if c is None:
            raise HTTPException(404, f"component {name!r} not enabled")
        return c

    def push(_: dict[str, Any]) -> None:
        if not subscribers:
            return
        msg = orjson.dumps({"type": "overview", "data_source": engine.data_source.value,
                            "execution_mode": EXECUTION_MODE, **overview(engine)},
                           option=orjson.OPT_SERIALIZE_NUMPY | orjson.OPT_NON_STR_KEYS, default=str).decode()
        for q in list(subscribers):
            if q.full():
                try:
                    q.get_nowait()  # drop the oldest update for slow clients
                except asyncio.QueueEmpty:
                    pass
            q.put_nowait(msg)

    engine.summary_listeners.append(push)

    @app.middleware("http")
    async def timing(request: Any, call_next: Any) -> Any:
        import time as _t
        t0 = _t.perf_counter_ns()
        resp = await call_next(request)
        route = request.scope.get("route")
        path = getattr(route, "path", request.url.path)
        engine.metrics.record(f"api{path}", _t.perf_counter_ns() - t0)
        return resp

    @app.get("/api/health")
    async def health() -> Response:
        return envelope(engine.health_cache or engine.health())

    @app.get("/health")
    async def health_compat() -> Response:
        return await health()

    @app.get("/api/overview")
    async def get_overview() -> Response:
        return envelope(overview(engine))

    @app.get("/api/markets")
    async def markets(venue: str | None = None, status: str | None = None, sort: SortKey = "key", desc: bool = False,
                limit: int = Query(500, ge=1, le=5000)) -> Response:
        rows = engine.market_rows(venue.upper() if venue else None)
        if status:
            wanted = {s.strip().upper() for s in status.split(",")}
            rows = [r for r in rows if r["status"] in wanted]
        for r in rows:
            r["liquidity"] = None if r["bid"] is None else (r["bid"] * r["bid_qty"] + (r["ask"] or 0) * r["ask_qty"]) / 2
        present = [r for r in rows if r.get(sort) is not None]
        missing = [r for r in rows if r.get(sort) is None]
        present.sort(key=lambda r: r[sort], reverse=desc)
        rows = present + missing
        return envelope({"count": len(rows), "markets": rows[:limit]})

    @app.get("/api/markets/{key}")
    async def market(key: str) -> Response:
        k = key.upper() if ":" in key else f"BINANCE:{key.upper()}"
        st = engine.state.instruments.get(k)
        if st is None:
            raise HTTPException(404, f"{k} is not monitored")
        book = engine.books.books.get(k)
        spec = engine.registry.get(k)
        return envelope({"market": engine.state.row(st, engine.clock.mono()),
                         "order_book": book.snapshot_view(10) if book else None,
                         "instrument": next((x for x in engine.registry.snapshot() if x["key"] == k), None)
                         if spec else None})

    @app.get("/api/opportunities")
    async def opportunities(strategy: Literal["cross_exchange", "triangular"] = "cross_exchange",
                      limit: int = Query(100, ge=1, le=1000)) -> Response:
        return envelope(comp(strategy).snapshot(limit))

    @app.get("/api/signals")
    async def signals(kind: Literal["anomaly", "pattern"] = "pattern", limit: int = Query(200, ge=1, le=2000)) -> Response:
        return envelope(comp("anomalies" if kind == "anomaly" else "patterns").snapshot(limit))

    @app.get("/api/signals/evaluation")
    async def evaluation() -> Response:
        return envelope(comp("evaluation").report())

    @app.get("/api/paper")
    async def paper() -> Response:
        return envelope(comp("paper").snapshot())

    def _authorize(token: str | None) -> None:
        cfg = engine.cfg.api.control_token
        if cfg is None:
            raise HTTPException(403, "simulation control disabled (no api.control_token configured)")
        if token is None or not secrets.compare_digest(token, cfg.get_secret_value()):
            raise HTTPException(401, "invalid control token")

    @app.post("/api/paper/emergency-stop")
    async def emergency_stop(reason: str = "manual", x_control_token: str | None = Header(None)) -> Response:
        _authorize(x_control_token)
        p = comp("paper")
        p.risk.emergency_stop(f"manual:{reason}", manual=True)
        p.cancel_all("emergency_stop")
        engine.audit("config_changes", {"event": "emergency_stop", "reason": reason, "source": "api"})
        return envelope({"halted": True, "reason": p.risk.halt_reason})

    @app.post("/api/paper/resume")
    async def resume(x_control_token: str | None = Header(None)) -> Response:
        _authorize(x_control_token)
        p = comp("paper")
        p.risk.resume(by="api")
        engine.audit("config_changes", {"event": "resume", "source": "api"})
        return envelope({"halted": False})

    @app.get("/api/latency")
    async def latency() -> Response:
        return envelope(engine.latency_report())

    @app.get("/api/diagnostics")
    async def diagnostics() -> Response:
        return envelope(engine.diagnostics())

    @app.get("/api/registry")
    async def registry() -> Response:
        pairs = engine.registry.cross_venue_pairs()
        return envelope({"instruments": engine.registry.snapshot(),
                         "cross_venue_pairs": [{"pair": p.pair_id, "base": p.base,
                                                "conversion": p.conv.spec.key if p.conv else None} for p in pairs]})

    @app.get("/api/history/{table}")
    async def history(table: str, limit: int = Query(100, ge=1, le=5000)) -> Response:
        sink = engine.sink
        if table not in sink.recent:
            raise HTTPException(404, f"unknown table {table}")
        if hasattr(sink, "query"):
            rows = await sink.query(table, limit)
            source = "postgres"
        else:
            rows = list(sink.recent[table])[-limit:][::-1]
            source = f"{sink.kind} (recent in-memory buffer)"
        return envelope({"table": table, "source": source, "rows": rows})

    @app.get("/metrics", response_class=PlainTextResponse)
    async def metrics() -> str:
        return prometheus_text(engine)

    @app.websocket("/api/stream")
    async def stream(ws: WebSocket) -> None:
        await ws.accept()
        q: asyncio.Queue[str] = asyncio.Queue(maxsize=5)
        subscribers.add(q)
        try:
            await ws.send_text(orjson.dumps({"type": "overview", "data_source": engine.data_source.value,
                                             "execution_mode": EXECUTION_MODE, **overview(engine)},
                                            option=orjson.OPT_SERIALIZE_NUMPY | orjson.OPT_NON_STR_KEYS,
                                            default=str).decode())
            while True:
                await ws.send_text(await q.get())
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            subscribers.discard(q)

    dash = engine.cfg.api.dashboard_dir
    if dash and os.path.isdir(dash):
        app.mount("/", StaticFiles(directory=dash, html=True), name="dashboard")
    return app


def prometheus_text(engine: Engine) -> str:
    h = engine.health_cache or engine.health()
    lines = [
        f'mie_info{{data_source="{engine.data_source.value}",mode="{EXECUTION_MODE}",version="{__version__}"}} 1',
        f"mie_frames_total {engine.frames}",
        f"mie_connections_up {h['connections_up']}",
        f"mie_connections_total {h['connections_total']}",
        f"mie_instruments_usable {h['instruments_usable']}",
        f'mie_health{{status="{h["status"]}"}} 1',
    ]
    for v, d in h["venues"].items():
        lines.append(f'mie_venue_usable{{venue="{v}"}} {d["usable"]}')
        lines.append(f'mie_venue_reconnects_total{{venue="{v}"}} {d["reconnects"]}')
    for reason, n in engine.invalid.items():
        lines.append(f'mie_invalid_frames_total{{reason="{reason}"}} {n}')
    for q in engine.bus.stats():
        lines.append(f'mie_queue_depth{{queue="{q["name"]}"}} {q["depth"]}')
        lines.append(f'mie_queue_dropped_total{{queue="{q["name"]}"}} {q["dropped"]}')
    lines.append(f"mie_audit_dropped_total {engine.sink.dropped}")
    for name, rep in engine.metrics.report().items():
        w = rep["window"]
        for q in ("p50", "p95", "p99", "max"):
            if w.get(q) is not None:
                lines.append(f'mie_latency_us{{stage="{name}",quantile="{q}"}} {w[q]}')
    return "\n".join(lines) + "\n"
