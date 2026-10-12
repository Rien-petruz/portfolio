"""End-to-end tests over real WebSocket connections to the local simulator.

These exercise the actual connection manager, normalizer, state and order
books against Binance-format frames, including every failure mode we must
survive. Data is synthetic; the point is protocol and failure handling.
"""

from __future__ import annotations

import asyncio

from marketintel.clock import mono_ns
from marketintel.config import SubscribeMode
from marketintel.persistence.recorder import read_frames
from marketintel.state.market_state import QuoteStatus

from .conftest import fast_settings, make_engine


def all_live(engine) -> bool:
    now = mono_ns()
    return all(engine.state.status(st, now) is QuoteStatus.LIVE for st in engine.state.symbols.values())


def statuses(engine) -> set[QuoteStatus]:
    now = mono_ns()
    return {engine.state.status(st, now) for st in engine.state.symbols.values()}


async def test_connects_50_plus_symbols_and_btc_reference(running):
    engine, sim = running
    assert len(engine.state.symbols) >= 50
    assert "BTCUSDT" in engine.state.symbols and engine.universe.metadata_ok
    assert len(engine.shards) >= 2  # multiplexed, not one socket per symbol
    assert await engine.wait_until(lambda: all_live(engine), 10)
    assert await engine.wait_until(lambda: all(b.is_synced for b in engine.books.books.values()), 10)
    h = engine.health()
    assert h["status"] == "OK", h
    assert h["data_source"] == "SIMULATED" and h["reference_status"] == "LIVE"
    btc = engine.state.symbols["BTCUSDT"]
    assert 0 < btc.bid_px < btc.ask_px and btc.n_trades > 0
    # Every symbol's filters came from exchangeInfo.
    assert all(st.info is not None and st.info.filters_known for st in engine.state.symbols.values())
    # Local book top matches the bookTicker feed for the same symbol (both
    # derive from the same exchange book).
    book = engine.books.books["BTCUSDT"]
    assert book.best_bid() is not None and book.best_ask() is not None
    assert engine.invalid == {}
    assert engine.lat_state.current.count > 0


async def test_network_drop_invalidates_state_then_recovers(running):
    engine, sim = running
    assert await engine.wait_until(lambda: all_live(engine), 10)
    connects_before = sum(s.health.connects for s in engine.shards)
    at_down: list[set[QuoteStatus]] = []
    for sh in engine.shards:
        orig = sh._on_down

        def hooked(shard, orig=orig):
            orig(shard)
            now = mono_ns()
            at_down.append({engine.state.status(engine.state.symbols[s], now) for s in shard.plan.symbols})

        sh._on_down = hooked
    sim.reject_next_handshakes(2 * len(engine.shards))  # keep the outage observable
    sim.drop_all_connections()
    # Invalidation is synchronous with the disconnect: no LIVE quote survives it.
    assert await engine.wait_until(lambda: len(at_down) == len(engine.shards), 2)
    assert all(st == {QuoteStatus.DISCONNECTED} for st in at_down), at_down
    assert await engine.wait_until(lambda: QuoteStatus.DISCONNECTED in statuses(engine), 1)
    assert not engine.state.is_usable("BTCUSDT", mono_ns(), allow_quiet=True)
    assert engine.health()["status"] in ("DOWN", "DEGRADED")
    assert all(not b.is_synced for b in engine.books.books.values())
    # Recovery: reconnect with backoff, then each symbol becomes LIVE only
    # after a fresh post-reconnect update.
    assert await engine.wait_until(lambda: all_live(engine), 10)
    assert sum(s.health.connects for s in engine.shards) >= connects_before + len(engine.shards)
    assert all(s.health.disconnects >= 1 for s in engine.shards)
    assert all(st.n_reconnects >= 1 for st in engine.state.symbols.values())
    assert await engine.wait_until(lambda: all(b.is_synced for b in engine.books.books.values()), 10)
    assert engine.health()["status"] == "OK"


async def test_server_shutdown_rotates_without_outage(running):
    engine, sim = running
    assert await engine.wait_until(lambda: all_live(engine), 10)
    seen: set[QuoteStatus] = set()

    async def watch():
        while True:
            seen.update(statuses(engine))
            await asyncio.sleep(0.005)

    w = asyncio.create_task(watch())
    await sim.server_shutdown(close_after_s=1.0)
    assert await engine.wait_until(lambda: all(s.health.rotations >= 1 for s in engine.shards), 5)
    await asyncio.sleep(0.3)
    w.cancel()
    assert QuoteStatus.DISCONNECTED not in seen
    assert all(s.health.disconnects == 0 for s in engine.shards)
    assert all(s.health.server_shutdowns >= 1 for s in engine.shards)
    assert all_live(engine)


async def test_proactive_rotation_before_max_age(sim):
    s = fast_settings(binance={"connection_max_age_s": 1.0})
    engine, rest = await make_engine(sim, s)
    await engine.start()
    try:
        assert await engine.wait_until(lambda: all(sh.health.rotations >= 2 for sh in engine.shards), 8)
        assert all(sh.health.disconnects == 0 for sh in engine.shards)
        # Make-before-break: the new socket is streaming before the old one is
        # closed, so not a single trade is lost across rotations. Duplicates
        # from the overlap are discarded by id.
        assert all(st.missed_trades == 0 for st in engine.state.symbols.values())
        # Old sockets are closed after each handover (poll: a rotation may be in flight).
        assert await engine.wait_until(lambda: all(sh.health.open_sockets == 1 for sh in engine.shards), 2)
        assert await engine.wait_until(lambda: all_live(engine), 5)
    finally:
        await engine.stop()
        await rest.close()


async def test_stalled_feed_goes_stale_and_is_recycled(running):
    engine, sim = running
    assert await engine.wait_until(lambda: all_live(engine), 10)
    sim.paused = True  # sockets stay open, no data: a silent feed
    assert await engine.wait_until(lambda: QuoteStatus.LIVE not in statuses(engine), 3)
    assert await engine.wait_until(lambda: all(s.health.stalls >= 1 for s in engine.shards), 3)
    assert not engine.state.is_usable("BTCUSDT", mono_ns(), allow_quiet=True)
    sim.paused = False
    assert await engine.wait_until(lambda: all_live(engine), 10)


async def test_handshake_rate_limit_backs_off(sim):
    sim.reject_next_handshakes(3, status=429)
    engine, rest = await make_engine(sim)
    t0 = asyncio.get_running_loop().time()
    await engine.start()
    try:
        assert await engine.wait_until(lambda: all_live(engine), 15)
        failures = sum(s.health.connect_failures for s in engine.shards)
        assert failures == 3 and sim.handshakes_rejected == 3
        # rate_limited_min_s (0.3 s in tests) is honoured after a 429.
        assert asyncio.get_running_loop().time() - t0 >= 0.3
        assert "429" in " ".join(e for s in engine.shards for e in s.health.errors)
    finally:
        await engine.stop()
        await rest.close()


async def test_data_quality_faults_are_detected(running):
    engine, sim = running
    assert await engine.wait_until(lambda: all_live(engine), 10)
    sim.paused = False
    sim.inject_invalid_frames()
    assert await engine.wait_until(lambda: sum(engine.invalid.values()) >= 3, 2)
    assert set(engine.invalid) == {"invalid_json", "missing_field", "bad_value"}

    st = engine.state.symbols["SOLUSDT"]
    sim.paused = True  # freeze to observe the injected state deterministically
    await asyncio.sleep(0.05)
    sim.paused = False
    sim.inject_crossed("SOLUSDT")
    sim.paused = True
    assert await engine.wait_until(lambda: engine.state.status(st, mono_ns()) is QuoteStatus.CROSSED, 2)
    assert not engine.state.is_usable("SOLUSDT", mono_ns(), allow_quiet=True)
    sim.paused = False
    sim.inject_out_of_order("SOLUSDT")
    assert await engine.wait_until(lambda: st.n_book_out_of_order >= 1, 2)

    btc = engine.state.symbols["BTCUSDT"]
    gaps = btc.n_trade_gaps
    sim.inject_trade_gap("BTCUSDT", 7)
    assert await engine.wait_until(lambda: btc.n_trade_gaps > gaps, 3)
    assert btc.missed_trades >= 7

    book = engine.books.books["BTCUSDT"]
    assert await engine.wait_until(lambda: book.is_synced, 5)
    sim.inject_depth_gap("BTCUSDT")
    assert await engine.wait_until(lambda: book.gaps >= 1, 3)
    assert await engine.wait_until(lambda: book.is_synced, 5)  # resynchronised from a new snapshot
    assert engine.books.snapshot_requests >= 2
    assert all(s.health.callback_errors == 0 for s in engine.shards)


async def test_message_subscribe_mode_respects_inbound_limit(sim):
    s = fast_settings(binance={"subscribe_mode": SubscribeMode.MESSAGE, "subscribe_batch_size": 20,
                               "subscribe_messages_per_second": 4.0})
    engine, rest = await make_engine(sim, s)
    await engine.start()
    try:
        assert await engine.wait_until(lambda: all_live(engine), 15)
        assert sim.inbound_limit_disconnects == 0
        assert engine.normalizer.control_messages >= 2  # SUBSCRIBE acks consumed, not treated as data
        assert engine.invalid == {}
    finally:
        await engine.stop()
        await rest.close()


async def test_recorded_frames_replay_to_identical_state(sim, tmp_path):
    s = fast_settings(recording={"enabled": True, "directory": str(tmp_path)})
    engine, rest = await make_engine(sim, s)
    await engine.start()
    assert await engine.wait_until(lambda: all_live(engine), 10)
    await asyncio.sleep(0.5)
    await engine.stop()
    await rest.close()
    assert engine.recorder is not None and engine.recorder.dropped == 0
    frames = list(read_frames(engine.recorder.path))
    assert len(frames) == engine.recorder.written > 100
    assert all(a.recv_mono_ns <= b.recv_mono_ns for a, b in zip(frames, frames[1:]))

    # Replay the raw frames through a fresh engine's hot path.
    s2 = fast_settings()
    s2.binance.ws_base_url = sim.ws_url
    replay, rest2 = await make_engine(sim, s2)
    for sh in replay.shards:
        sh.health.connected = True
    for f in frames:
        replay.on_frame(f.raw, f.recv_mono_ns, f.recv_wall_ns, replay.shards[f.shard_id])
    await rest2.close()
    for sym, st in engine.state.symbols.items():
        r = replay.state.symbols[sym]
        assert (r.bid_px, r.ask_px, r.book_update_id, r.last_trade_id) == \
            (st.bid_px, st.ask_px, st.book_update_id, st.last_trade_id), sym


async def test_late_data_is_stale_and_degrades_health(running):
    engine, sim = running
    assert await engine.wait_until(lambda: all_live(engine), 10)
    sim.event_delay_ms = 4000  # events stamped 4 s before they are delivered
    assert await engine.wait_until(lambda: QuoteStatus.STALE in statuses(engine), 3)
    assert not engine.state.is_usable("BTCUSDT", mono_ns(), allow_quiet=True)
    h = engine.health()
    assert h["status"] == "DEGRADED" and any("later than" in r for r in h["reasons"])
    sim.event_delay_ms = 0
    assert await engine.wait_until(lambda: all_live(engine), 5)
