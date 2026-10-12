from __future__ import annotations

import asyncio

import httpx
import orjson
import pytest
import uvicorn
from websockets.asyncio.client import connect

from marketintel.api.app import create_app

from ..conftest import make_engine
from .test_feeds import all_live
from .test_system import system_settings


@pytest.fixture
async def system(sims):
    s = system_settings()
    s.api.control_token = "s3cret"
    engine = await make_engine(sims, s, components=True)
    await engine.start()
    assert await engine.wait_until(lambda: all_live(engine), 10)
    assert await engine.wait_until(lambda: engine.health_cache != {}, 3)
    app = create_app(engine)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c, engine, sims, app
    await engine.stop()


async def test_read_endpoints(system):
    c, engine, sims, _ = system
    h = (await c.get("/api/health")).json()
    assert h["data_source"] == "SIMULATED" and h["execution_mode"] == "PAPER" and "PAPER TRADING ONLY" in h["banner"]
    assert h["status"] in ("OK", "DEGRADED") and set(h["venues"]) == {"BINANCE", "COINBASE"}
    ov = (await c.get("/api/overview")).json()
    assert ov["reference"]["BINANCE:BTCUSDT"]["bid"] < ov["reference"]["BINANCE:BTCUSDT"]["ask"]
    assert "cross_exchange" in ov and "triangular" in ov and "latency_us" in ov

    m = (await c.get("/api/markets", params={"venue": "coinbase", "sort": "spread_bps", "desc": "true", "limit": 5})).json()
    assert m["count"] >= 20 and len(m["markets"]) == 5 and all(r["venue"] == "COINBASE" for r in m["markets"])
    spreads = [r["spread_bps"] for r in m["markets"]]
    assert spreads == sorted(spreads, reverse=True)
    one = (await c.get("/api/markets/COINBASE:BTC-USD")).json()
    assert one["market"]["key"] == "COINBASE:BTC-USD" and one["order_book"]["sync"] == "SYNCED"
    assert one["instrument"]["mapping"] == "VERIFIED"
    assert (await c.get("/api/markets/NOPE:XYZ")).status_code == 404
    assert (await c.get("/api/markets", params={"sort": "evil"})).status_code == 422

    o = (await c.get("/api/opportunities", params={"strategy": "cross_exchange"})).json()
    assert o["pairs"] >= 20 and "scanner" in o and "open" in o
    t = (await c.get("/api/opportunities", params={"strategy": "triangular"})).json()
    assert t["routes"] >= 1
    assert (await c.get("/api/signals", params={"kind": "anomaly"})).status_code == 200
    ev = (await c.get("/api/signals/evaluation")).json()
    assert ev["min_sample"] == 30
    p = (await c.get("/api/paper")).json()
    assert p["mode"] == "PAPER" and p["portfolio"]["label"] == "SIMULATED"
    reg = (await c.get("/api/registry")).json()
    assert any(x["alias_of"] for x in reg["instruments"]) is False  # aliases are never subscribed
    assert len(reg["cross_venue_pairs"]) >= 20
    hist = (await c.get("/api/history/audit_log")).json()
    assert "memory" in hist["source"] and hist["rows"]
    lat = (await c.get("/api/latency")).json()
    assert any(k.startswith("ingest.recv_to_state") for k in lat)
    diag = (await c.get("/api/diagnostics")).json()
    assert len(diag["connections"]) == len(engine.connections)
    text = (await c.get("/metrics")).text
    assert 'mode="PAPER"' in text and "mie_venue_usable" in text


async def test_simulation_controls_require_token(system):
    c, engine, sims, _ = system
    assert (await c.post("/api/paper/emergency-stop")).status_code == 401
    assert (await c.post("/api/paper/emergency-stop", headers={"X-Control-Token": "wrong"})).status_code == 401
    r = await c.post("/api/paper/emergency-stop", params={"reason": "test"}, headers={"X-Control-Token": "s3cret"})
    assert r.status_code == 200 and r.json()["halted"]
    assert engine.component("paper").risk.halted
    r = await c.post("/api/paper/resume", headers={"X-Control-Token": "s3cret"})
    assert r.status_code == 200 and not engine.component("paper").risk.halted
    assert [x["event"] for x in engine.sink.recent["config_changes"]][-2:] == ["emergency_stop", "resume"]


async def test_controls_disabled_without_token(sims):
    engine = await make_engine(sims, system_settings(), components=True)
    app = create_app(engine)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        assert (await c.post("/api/paper/emergency-stop", headers={"X-Control-Token": "x"})).status_code == 403
    await engine.adapters["BINANCE"].close()
    await engine.adapters["COINBASE"].close()


async def test_websocket_stream_pushes_overview(system):
    c, engine, sims, app = system
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error", lifespan="off"))
    task = asyncio.create_task(server.serve())
    try:
        assert await engine.wait_until(lambda: server.started, 5)
        port = server.servers[0].sockets[0].getsockname()[1]
        async with connect(f"ws://127.0.0.1:{port}/api/stream", proxy=None) as ws:
            first = orjson.loads(await asyncio.wait_for(ws.recv(), 5))
            pushed = orjson.loads(await asyncio.wait_for(ws.recv(), 5))  # next summary tick
        for msg in (first, pushed):
            assert msg["type"] == "overview" and msg["execution_mode"] == "PAPER"
            assert msg["health"]["data_source"] == "SIMULATED"
    finally:
        server.should_exit = True
        await task
