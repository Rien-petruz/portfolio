import httpx
import pytest

from marketintel.api.app import create_app

from .test_integration_feed import all_live


@pytest.fixture
async def client(running):
    engine, sim = running
    assert await engine.wait_until(lambda: all_live(engine), 10)
    transport = httpx.ASGITransport(app=create_app(engine))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, engine, sim


async def test_health_and_markets(client):
    c, engine, sim = client
    r = await c.get("/health")
    assert r.status_code == 200
    h = r.json()
    assert h["status"] == "OK", h["reasons"]
    assert h["data_source"] == "SIMULATED" and h["observation_only"] is True
    assert h["symbols_total"] >= 50 and h["shards_connected"] == h["shards_total"]

    r = await c.get("/markets", params={"sort": "spread_bps", "desc": "true", "limit": 5})
    body = r.json()
    assert body["data_source"] == "SIMULATED" and len(body["markets"]) == 5
    spreads = [m["spread_bps"] for m in body["markets"]]
    assert spreads == sorted(spreads, reverse=True)

    r = await c.get("/markets", params={"status": "LIVE"})
    assert r.json()["count"] == len(engine.state.symbols)

    r = await c.get("/markets/btcusdt")
    m = r.json()
    assert m["market"]["symbol"] == "BTCUSDT" and m["market"]["bid"] < m["market"]["ask"]
    assert m["order_book"]["symbol"] == "BTCUSDT"
    assert (await c.get("/markets/NOPE")).status_code == 404
    assert (await c.get("/markets", params={"sort": "evil"})).status_code == 422


async def test_latency_diagnostics_metrics(client):
    c, engine, sim = client
    engine.lat_state.roll()
    lat = (await c.get("/latency")).json()
    w = lat["recv_to_state_applied"]["window"]
    assert w["count"] > 0 and w["p50"] <= w["p95"] <= w["p99"] <= w["max"]
    assert "exchange_event_to_recv_trade" in lat and lat["_notes"]["units"] == "microseconds"
    d = (await c.get("/diagnostics")).json()
    assert len(d["shards"]) == len(engine.shards) and d["queues"][0]["name"] == "quote_scanner"
    assert d["order_books"]["BTCUSDT"]["sync"] in ("SYNCED", "BUFFERING", "INIT")
    text = (await c.get("/metrics")).text
    assert 'mie_info{data_source="SIMULATED"' in text and "mie_shard_connected" in text


async def test_health_reports_down_on_disconnect(client):
    c, engine, sim = client
    for sh in engine.shards:
        await sh.stop()
    h = (await c.get("/health")).json()
    assert h["status"] == "DOWN" and h["symbols_usable"] == 0
