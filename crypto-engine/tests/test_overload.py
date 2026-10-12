"""Overload behaviour: slow consumers and a blocked event loop must never
corrupt state or block ingestion; they must be visible in health."""

import asyncio
import time

import orjson

from marketintel.config import DataSource
from marketintel.engine import Engine, UniverseResult

from .conftest import fast_settings


def make_offline_engine(**over) -> Engine:
    s = fast_settings(**over)
    s.data_source = DataSource.REPLAY
    eng = Engine(s, UniverseResult(["BTCUSDT", "ETHUSDT"], {}, False, "test"), rest=None)
    for sh in eng.shards:
        sh.health.connected = True
    return eng


def trade_frame(i: int) -> bytes:
    return orjson.dumps({"stream": "btcusdt@trade", "data": {
        "e": "trade", "E": 1, "s": "BTCUSDT", "t": i, "p": "100.0", "q": "1.0", "T": 1, "m": False}})


async def test_slow_consumer_drops_are_bounded_and_reported():
    eng = make_offline_engine(engine={"trade_queue_capacity": 100})
    sh = eng.shards[0]
    t0 = time.monotonic_ns()
    for i in range(1, 1001):  # consumer task not running: it is "infinitely slow"
        eng.on_frame(trade_frame(i), t0, time.time_ns(), sh)
    q = eng.trade_queue
    assert q.depth == 100 and q.dropped == 900
    # Ingestion state is complete and exact despite consumer drops.
    st = eng.state.symbols["BTCUSDT"]
    assert st.n_trades == 1000 and st.last_trade_id == 1000
    eng._drops_in_window = q.dropped
    h = eng.health()
    assert h["status"] == "DEGRADED" and any("dropped" in r for r in h["reasons"])


async def test_quote_conflation_under_burst():
    eng = make_offline_engine()
    sh = eng.shards[0]
    for u in range(1, 5001):
        raw = orjson.dumps({"stream": "btcusdt@bookTicker", "data": {
            "u": u, "s": "BTCUSDT", "b": f"{100 + u % 7}.0", "B": "1", "a": "200.0", "A": "1"}})
        eng.on_frame(raw, time.monotonic_ns(), time.time_ns(), sh)
    # 5000 updates for one symbol -> one pending work item reflecting the latest state.
    assert eng.quote_queue.depth == 1 and eng.quote_queue.conflated == 4999
    assert eng.state.symbols["BTCUSDT"].book_update_id == 5000


async def test_blocked_event_loop_is_detected():
    eng = make_offline_engine(engine={"loop_lag_interval_ms": 10, "loop_lag_degraded_ms": 20.0})
    task = asyncio.create_task(eng.loop_lag.run())
    await asyncio.sleep(0.05)
    time.sleep(0.15)  # simulate a CPU hog on the loop
    await asyncio.sleep(0.03)
    eng.loop_lag.hist.roll()
    task.cancel()
    assert eng.loop_lag.hist.last.max >= 100_000_000
    eng.frames = 1
    h = eng.health()
    assert any("lag" in r for r in h["reasons"]) and h["status"] == "DEGRADED"


async def test_consumer_exception_does_not_kill_ingestion():
    eng = make_offline_engine()
    sh = eng.shards[0]

    def boom(*a):
        raise RuntimeError("consumer bug")

    eng.bus.publish_trade = boom  # type: ignore[assignment]
    # The shard read loop wraps on_frame; emulate that contract here.
    try:
        eng.on_frame(trade_frame(1), time.monotonic_ns(), time.time_ns(), sh)
    except RuntimeError:
        sh.health.callback_errors += 1
    assert eng.state.symbols["BTCUSDT"].last_trade_id == 1
