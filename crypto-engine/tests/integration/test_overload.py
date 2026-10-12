"""Overload: slow consumers and a blocked loop never corrupt state or block
ingestion, and are visible in health."""

import asyncio
import time

import orjson

from marketintel.config import DataSource, Settings

from ..helpers import offline_engine, spec


def make(**engine_cfg):
    s = Settings(data_source=DataSource.REPLAY, persistence={"jsonl_dir": None})
    for k, v in engine_cfg.items():
        setattr(s.engine, k, v)
    eng = offline_engine([spec("BINANCE", "BTCUSDT", "BTC", "USDT"), spec("BINANCE", "ETHUSDT", "ETH", "USDT")], s,
                         components=False)
    eng.replay = False  # exercise the live hot path
    conn = eng.connections[0]
    dec = eng.adapters["BINANCE"].make_decoder(conn.plan, 1)
    return eng, conn, dec


def trade_frame(i):
    return orjson.dumps({"stream": "btcusdt@trade", "data": {
        "e": "trade", "E": 1, "s": "BTCUSDT", "t": i, "p": "100.0", "q": "1.0", "T": 1, "m": False}})


async def test_slow_consumer_drops_are_bounded_and_reported():
    eng, conn, dec = make(trade_queue_capacity=100)

    class Slow:
        name = "slow"
        def on_trades(self, items, now): ...

    eng.add_component(Slow(), trades=True)
    for i in range(1, 1001):  # consumer never runs: infinitely slow
        eng.on_frame(trade_frame(i), time.monotonic_ns(), time.time_ns(), conn, dec)
    q = eng._trade_consumers[0][1]
    assert q.depth == 100 and q.dropped == 900
    st = eng.state.instruments["BINANCE:BTCUSDT"]
    assert st.n_trades == 1000 and st.last_trade_id == 1000  # ingestion exact despite drops
    eng.frames = 1
    eng._summary(eng.clock.mono())
    h = eng.health()
    assert h["status"] == "DEGRADED" and any("dropped" in r for r in h["reasons"])


async def test_quote_conflation_under_burst():
    eng, conn, dec = make()

    class C:
        name = "c"
        def on_quotes(self, b, now): ...

    eng.add_component(C(), quotes=True)
    for u in range(1, 5001):
        raw = orjson.dumps({"stream": "btcusdt@bookTicker", "data": {
            "u": u, "s": "BTCUSDT", "b": f"{100 + u % 7}.0", "B": "1", "a": "200.0", "A": "1"}})
        eng.on_frame(raw, time.monotonic_ns(), time.time_ns(), conn, dec)
    q = eng._quote_consumers[0][1]
    assert q.depth == 1 and q.conflated == 4999
    assert eng.state.instruments["BINANCE:BTCUSDT"].book_update_id == 5000


async def test_blocked_event_loop_is_detected():
    eng, _, _ = make(loop_lag_interval_ms=10, loop_lag_degraded_ms=20.0)
    task = asyncio.create_task(eng.loop_lag.run())
    await asyncio.sleep(0.05)
    time.sleep(0.15)  # a CPU hog on the loop
    await asyncio.sleep(0.03)
    eng.loop_lag.hist.roll()
    task.cancel()
    assert eng.loop_lag.hist.last.max >= 100_000_000
    eng.frames = 1
    h = eng.health()
    assert any("lag" in r for r in h["reasons"]) and h["status"] == "DEGRADED"


async def test_audit_sink_overflow_drops_and_degrades_not_blocks():
    from marketintel.persistence.sink import AuditSink
    sink = AuditSink(capacity=10)
    for i in range(50):
        sink.write("audit_log", {"i": i})
    assert sink.depth == 10 and sink.dropped == 40
    assert len(sink.recent["audit_log"]) == 50  # API buffer still sees everything
