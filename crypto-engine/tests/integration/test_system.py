"""Full system (all components) against both simulated venues."""

from __future__ import annotations

from marketintel.persistence.sink import AuditSink

from ..conftest import fast_settings, make_engine
from .test_feeds import all_live


def system_settings():
    s = fast_settings()
    # Low synthetic fees so injected dislocations become VALID (simulation only).
    s.coinbase.fees.taker_bps = s.coinbase.fees.maker_bps = 5.0
    s.strategies.cross_exchange.min_net_edge_bps = 2.0
    s.strategies.cross_exchange.max_quote_age_ms = 2000
    s.strategies.cross_exchange.max_recv_skew_ms = 1000
    s.risk.max_quote_age_ms = 2000
    s.risk.max_skew_ms = 1000
    s.engine.feature_history_s = 30
    s.strategies.anomalies.baseline_s = 10
    return s


async def test_full_system_detects_and_paper_trades_injected_dislocation(sims):
    sink = AuditSink()
    engine = await make_engine(sims, system_settings(), components=True, sink=sink)
    await engine.start()
    try:
        assert await engine.wait_until(lambda: all_live(engine), 10)
        xex = engine.component("cross_exchange")
        paper = engine.component("paper")
        assert xex is not None and paper is not None and len(xex.pairs) >= 20
        assert await engine.wait_until(lambda: paper.portfolio.initialized, 5)
        # Coinbase BTC trades 40 bps rich for 3 s: buy Binance ask, sell Coinbase bid.
        sims.world.dislocate("BTC", "COINBASE", 40.0, 3.0)
        assert await engine.wait_until(lambda: any(e.ever_valid for e in list(xex.tracker.open.values())
                                                   + list(xex.tracker.closed)), 5)
        xex_execs = lambda: [e for e in paper.recent_executions if e.strategy == "cross_exchange"]  # noqa: E731
        assert await engine.wait_until(lambda: len(xex_execs()) >= 1, 5)
        ex = xex_execs()[0]
        assert ex.result["label"] == "SIMULATED" and ex.route_id.startswith("BINANCE:BTC")
        assert ex.status in ("FILLED", "PARTIAL", "MISSED")
        assert {o.venue for o in ex.orders} == {"BINANCE", "COINBASE"}
        assert all(o.client_id.startswith("sim-") for o in ex.orders)
        snap = paper.snapshot()
        assert snap["mode"] == "PAPER" and "PAPER TRADING ONLY" in snap["banner"]
        assert sink.recent["opportunity_candidates"] and sink.recent["sim_orders"]
        # Engine stays healthy while strategies run; latency stages are measured.
        h = engine.health()
        assert h["status"] in ("OK", "DEGRADED") and h["execution_mode"] == "PAPER"
        names = engine.metrics.report().keys()
        assert any(n.startswith("xex.recv_to_signal") for n in names)
        assert any(n.startswith("paper.order_latency") for n in names)
        assert any(n.startswith("features.sample") for n in names)
        assert await engine.wait_until(lambda: engine.component("features").samples > 10, 3)
    finally:
        await engine.stop()
    assert sink.written > 0 and sink.dropped == 0
