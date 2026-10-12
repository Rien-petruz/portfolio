"""End-to-end over real WebSocket connections to the local simulators.

Exercises the connection manager, decoders, state and books against
venue-format frames, including every failure mode we must survive. Data is
synthetic; the point is protocol and failure handling.
"""

from __future__ import annotations

import asyncio

from marketintel.clock import mono_ns
from marketintel.config import SubscribeMode
from marketintel.market_data.quality import QuoteStatus
from marketintel.persistence.recorder import read_frames, read_meta

from ..conftest import fast_settings, make_engine


def all_live(engine, venue: str | None = None) -> bool:
    now = mono_ns()
    return all(engine.state.status(st, now) is QuoteStatus.LIVE
               for st in engine.state.instruments.values() if venue is None or st.venue == venue)


def statuses(engine, venue: str | None = None) -> set[QuoteStatus]:
    now = mono_ns()
    return {engine.state.status(st, now) for st in engine.state.instruments.values()
            if venue is None or st.venue == venue}


def conns(engine, venue: str):
    return [c for c in engine.connections if c.venue == venue]


async def test_connects_50_plus_symbols_and_secondary_venue(running):
    engine, sims = running
    b = [k for k in engine.state.instruments if k.startswith("BINANCE:")]
    c = [k for k in engine.state.instruments if k.startswith("COINBASE:")]
    assert len(b) >= 50 and "BINANCE:BTCUSDT" in b and len(c) >= 20
    assert len(conns(engine, "BINANCE")) >= 2  # multiplexed, not one socket per symbol
    assert await engine.wait_until(lambda: all_live(engine), 10), statuses(engine)
    assert await engine.wait_until(lambda: all(b.is_synced for b in engine.books.books.values()), 10)
    h = engine.health()
    assert h["status"] == "OK", h["reasons"]
    assert h["data_source"] == "SIMULATED" and h["reference_status"] == "LIVE" and h["execution_mode"] == "PAPER"
    btc = engine.state.instruments["BINANCE:BTCUSDT"]
    assert 0 < btc.bid_px < btc.ask_px and btc.n_trades > 0 and btc.book_event_time_ns == 0
    cbtc = engine.state.instruments["COINBASE:BTC-USD"]
    assert 0 < cbtc.bid_px < cbtc.ask_px and cbtc.book_event_time_ns > 0  # Coinbase quotes carry exchange time
    # Coinbase BBO is derived from its local level2 book.
    book = engine.books.books["COINBASE:BTC-USD"]
    assert book.best_bid()[0] == cbtc.bid_px and book.best_ask()[0] == cbtc.ask_px
    assert all(st.spec is not None and st.spec.filters_known for st in engine.state.instruments.values())
    assert engine.invalid == {} and engine.metrics.hist("ingest.recv_to_state.COINBASE").current.count > 0
    assert len(engine.registry.cross_venue_pairs()) >= 20


async def test_network_drop_invalidates_state_then_recovers(running):
    engine, sims = running
    assert await engine.wait_until(lambda: all_live(engine), 10)
    at_down: list[set[QuoteStatus]] = []
    for c in engine.connections:
        orig = c._on_down

        def hooked(conn, orig=orig):
            orig(conn)
            now = mono_ns()
            at_down.append({engine.state.status(engine.state.instruments[k], now)
                            for k in engine.conn_keys[conn.shard_id]})

        c._on_down = hooked
    sims.binance.reject_next_handshakes(2 * len(conns(engine, "BINANCE")))
    sims.coinbase.reject_next_handshakes(2 * len(conns(engine, "COINBASE")))
    sims.binance.drop_all_connections()
    sims.coinbase.drop_all_connections()
    assert await engine.wait_until(lambda: len(at_down) == len(engine.connections), 3)
    assert all(st == {QuoteStatus.DISCONNECTED} for st in at_down), at_down
    assert not engine.state.is_usable("BINANCE:BTCUSDT", mono_ns(), allow_quiet=True)
    assert engine.health()["status"] in ("DOWN", "DEGRADED")
    assert all(not b.is_synced for b in engine.books.books.values())
    assert await engine.wait_until(lambda: all_live(engine), 15)
    assert all(c.health.disconnects >= 1 and c.health.last_reconnect_ms is not None for c in engine.connections)
    assert await engine.wait_until(lambda: all(b.is_synced for b in engine.books.books.values()), 10)
    assert any(r["event"] == "connection_down" for r in engine.sink.recent["audit_log"])


async def test_server_shutdown_rotates_without_outage(running):
    engine, sims = running
    assert await engine.wait_until(lambda: all_live(engine, "BINANCE"), 10)
    seen: set[QuoteStatus] = set()

    async def watch():
        while True:
            seen.update(statuses(engine, "BINANCE"))
            await asyncio.sleep(0.005)

    w = asyncio.create_task(watch())
    await sims.binance.server_shutdown(close_after_s=1.0)
    assert await engine.wait_until(lambda: all(c.health.rotations >= 1 for c in conns(engine, "BINANCE")), 5)
    await asyncio.sleep(0.3)
    w.cancel()
    assert QuoteStatus.DISCONNECTED not in seen
    assert all(c.health.disconnects == 0 for c in conns(engine, "BINANCE"))


async def test_proactive_rotation_before_max_age(sims):
    s = fast_settings(binance={"connection_max_age_s": 1.0}, coinbase={"connection_max_age_s": 1.5})
    engine = await make_engine(sims, s)
    await engine.start()
    try:
        assert await engine.wait_until(lambda: all(c.health.rotations >= 2 for c in engine.connections), 10)
        assert all(c.health.disconnects == 0 for c in engine.connections)
        # Make-before-break: no Binance trade lost across rotations.
        assert all(st.missed_trades == 0 for st in engine.state.instruments.values())
        # Coinbase books are owned by one socket at a time; deltas from the other are ignored.
        assert await engine.wait_until(lambda: all(c.health.open_sockets == 1 for c in engine.connections), 3)
        assert await engine.wait_until(lambda: all_live(engine), 5)
        assert engine.invalid == {}
    finally:
        await engine.stop()


async def test_stalled_feed_goes_stale_and_is_recycled(running):
    engine, sims = running
    assert await engine.wait_until(lambda: all_live(engine), 10)
    sims.binance.paused = True
    sims.coinbase.paused = True  # heartbeats stop too
    assert await engine.wait_until(lambda: QuoteStatus.LIVE not in statuses(engine), 3)
    assert await engine.wait_until(lambda: all(c.health.stalls >= 1 for c in engine.connections), 3)
    sims.binance.paused = False
    sims.coinbase.paused = False
    assert await engine.wait_until(lambda: all_live(engine), 10)


async def test_handshake_rate_limit_backs_off(sims):
    sims.binance.reject_next_handshakes(3, status=429)
    engine = await make_engine(sims, fast_settings(coinbase={"enabled": False}))
    t0 = asyncio.get_running_loop().time()
    await engine.start()
    try:
        assert await engine.wait_until(lambda: all_live(engine), 15)
        assert sum(c.health.connect_failures for c in engine.connections) == 3
        assert asyncio.get_running_loop().time() - t0 >= 0.3
        assert "429" in " ".join(e for c in engine.connections for e in c.health.errors)
    finally:
        await engine.stop()


async def test_binance_data_quality_faults(running):
    engine, sims = running
    assert await engine.wait_until(lambda: all_live(engine), 10)
    sims.binance.inject_invalid_frames()
    assert await engine.wait_until(lambda: sum(engine.invalid.values()) >= 3, 2)
    assert set(engine.invalid) == {"BINANCE:invalid_json", "BINANCE:missing_field", "BINANCE:bad_value"}
    st = engine.state.instruments["BINANCE:SOLUSDT"]
    sims.binance.inject_crossed("SOLUSDT")
    sims.binance.paused = True
    assert await engine.wait_until(lambda: engine.state.status(st, mono_ns()) is QuoteStatus.CROSSED, 2)
    sims.binance.paused = False
    sims.binance.inject_out_of_order("SOLUSDT")
    assert await engine.wait_until(lambda: st.n_book_out_of_order >= 1, 2)
    btc = engine.state.instruments["BINANCE:BTCUSDT"]
    gaps = btc.n_trade_gaps
    sims.binance.inject_trade_gap("BTCUSDT", 7)
    assert await engine.wait_until(lambda: btc.n_trade_gaps > gaps, 3) and btc.missed_trades >= 7
    book = engine.books.books["BINANCE:BTCUSDT"]
    assert await engine.wait_until(lambda: book.is_synced, 5)
    sims.binance.inject_depth_gap("BTCUSDT")
    assert await engine.wait_until(lambda: book.gaps >= 1, 3)
    assert await engine.wait_until(lambda: book.is_synced, 5)
    assert all(c.health.callback_errors == 0 for c in engine.connections)


async def test_coinbase_sequence_gap_and_crossed_book_force_resync(running):
    engine, sims = running
    assert await engine.wait_until(lambda: all_live(engine, "COINBASE"), 10)
    recycles = sum(c.health.recycles for c in conns(engine, "COINBASE"))
    sims.coinbase.inject_sequence_gap()
    # Every Coinbase connection detects the gap, is recycled, resubscribes and rebuilds books.
    assert await engine.wait_until(
        lambda: sum(c.health.recycles for c in conns(engine, "COINBASE")) >= recycles + len(conns(engine, "COINBASE")), 3)
    assert await engine.wait_until(lambda: all_live(engine, "COINBASE"), 10)
    decs = [c._current.decoder for c in conns(engine, "COINBASE")]
    assert all(d.gaps == 0 for d in decs)  # fresh sockets, fresh sequences
    sims.coinbase.inject_crossed("ETH-USD")
    book = engine.books.books["COINBASE:ETH-USD"]
    assert await engine.wait_until(lambda: book.crossed_resets >= 1, 3)
    assert await engine.wait_until(lambda: all_live(engine, "COINBASE"), 10)
    sims.coinbase.send_error("simulated failure")
    sims.coinbase.send_invalid()
    assert await engine.wait_until(lambda: engine.invalid.get("COINBASE:control_error", 0) >= 1
                                   and engine.invalid.get("COINBASE:invalid_json", 0) >= 1, 3)


async def test_coinbase_subscription_respects_inbound_limit(sims):
    engine = await make_engine(sims, fast_settings(binance={"enabled": False},
                                                   coinbase={"subscribe_messages_per_second": 2.0}))
    await engine.start()
    try:
        assert await engine.wait_until(lambda: all_live(engine), 15)
        assert sims.coinbase.inbound_limit_disconnects == 0 and sims.coinbase.deadline_disconnects == 0
    finally:
        await engine.stop()


async def test_binance_message_subscribe_mode(sims):
    s = fast_settings(binance={"subscribe_mode": SubscribeMode.MESSAGE, "subscribe_batch_size": 20,
                               "subscribe_messages_per_second": 4.0}, coinbase={"enabled": False})
    engine = await make_engine(sims, s)
    await engine.start()
    try:
        assert await engine.wait_until(lambda: all_live(engine), 15)
        assert sims.binance.inbound_limit_disconnects == 0 and engine.invalid == {}
    finally:
        await engine.stop()


async def test_late_data_is_stale_and_degrades_health(running):
    engine, sims = running
    assert await engine.wait_until(lambda: all_live(engine), 10)
    sims.coinbase.event_delay_ms = 4000
    assert await engine.wait_until(lambda: QuoteStatus.STALE in statuses(engine, "COINBASE"), 4)
    assert await engine.wait_until(
        lambda: not engine.state.is_usable("COINBASE:BTC-USD", mono_ns(), allow_quiet=True), 4)
    h = engine.health()
    assert h["status"] == "DEGRADED" and any("later than" in r for r in h["reasons"])
    sims.coinbase.event_delay_ms = 0
    assert await engine.wait_until(lambda: all_live(engine), 8)


async def test_multi_venue_recording_has_metadata_and_replays(sims, tmp_path):
    s = fast_settings(recording={"enabled": True, "directory": str(tmp_path)})
    engine = await make_engine(sims, s)
    await engine.start()
    assert await engine.wait_until(lambda: all_live(engine), 10)
    await asyncio.sleep(0.5)
    await engine.stop()
    assert engine.recorder is not None and engine.recorder.dropped == 0
    meta = read_meta(engine.recorder.path)
    assert {p["venue"] for p in meta["plans"]} == {"BINANCE", "COINBASE"} and len(meta["instruments"]) >= 60
    frames = list(read_frames(engine.recorder.path))
    assert len(frames) == engine.recorder.written > 100
    # WebSocket frames from every planned connection, plus recorded REST depth snapshots (-1).
    assert {f.conn_id for f in frames} == {p.conn_id for p in engine.plans} | {engine.SNAPSHOT_CONN_ID}
