"""PostgreSQL audit sink (requires MIE_TEST_DATABASE_URL; CI provides a service container)."""

from __future__ import annotations

import os

import pytest

from marketintel.persistence.sink import TABLES, PostgresSink

from ..conftest import make_engine
from .test_feeds import all_live
from .test_system import system_settings

DSN = os.environ.get("MIE_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="set MIE_TEST_DATABASE_URL to run PostgreSQL tests")


async def test_schema_batches_and_query_roundtrip():
    sink = PostgresSink(DSN, capacity=10_000)
    await sink.start()
    try:
        import asyncpg
        con = await asyncpg.connect(DSN)
        for t in TABLES:
            await con.execute(f"TRUNCATE {t}")
        for i in range(1200):
            sink.write("sim_orders", {"ts_ns": 1_700_000_000_000_000_000 + i, "correlation_id": f"c{i % 7}",
                                      "strategy": "cross_exchange", "venue": "BINANCE", "instrument": "BINANCE:BTCUSDT",
                                      "status": "PENDING", "i": i, "label": "SIMULATED", "nan": float("nan")})
        await sink.flush()
        assert sink.written == 1200 and sink.dropped == 0
        n = await con.fetchval("SELECT count(*) FROM sim_orders")
        assert n == 1200
        row = await con.fetchrow("SELECT correlation_id, venue, payload->>'label' AS label FROM sim_orders WHERE payload->>'i' = '5'")
        assert row["correlation_id"] == "c5" and row["venue"] == "BINANCE" and row["label"] == "SIMULATED"
        latest = await sink.query("sim_orders", 3)
        assert [r["i"] for r in latest] == [1199, 1198, 1197]
        await con.close()
    finally:
        await sink.close()


async def test_full_system_persists_audit_trail(sims):
    import asyncpg
    con = await asyncpg.connect(DSN)
    for t in TABLES:
        await con.execute(f"CREATE TABLE IF NOT EXISTS {t} (id BIGSERIAL PRIMARY KEY, ts TIMESTAMPTZ NOT NULL, "
                          "correlation_id TEXT, strategy TEXT, venue TEXT, instrument TEXT, status TEXT, payload JSONB NOT NULL)")
        await con.execute(f"TRUNCATE {t}")
    await con.close()
    s = system_settings()
    s.persistence.database_url = DSN
    engine = await make_engine(sims, s, components=True, sink=PostgresSink(DSN))
    await engine.start()
    try:
        assert await engine.wait_until(lambda: all_live(engine), 10)
        sims.world.dislocate("BTC", "COINBASE", 40.0, 2.0)
        assert await engine.wait_until(lambda: engine.component("paper").recent_executions, 6)
    finally:
        await engine.stop()  # flushes the sink
    import asyncpg
    con = await asyncpg.connect(DSN)
    try:
        cfg = await con.fetchval("SELECT payload::text FROM config_changes ORDER BY id DESC LIMIT 1")
        assert "database_url" not in cfg  # the DSN (a secret) is never persisted
        for t in ("opportunity_candidates", "opportunity_validations", "sim_orders", "risk_events", "audit_log"):
            assert await con.fetchval(f"SELECT count(*) FROM {t}") > 0, t
        modes = await con.fetch("SELECT DISTINCT payload->>'execution_mode' AS m FROM sim_orders")
        assert {r["m"] for r in modes} == {"PAPER"}
    finally:
        await con.close()
