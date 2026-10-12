from __future__ import annotations

import asyncio
import gzip
import os

import pytest
import pytest_asyncio

from marketintel.backtest.candles import evaluate_file, load_klines
from marketintel.backtest.metrics import max_drawdown, report, sharpe
from marketintel.backtest.replay import ChronologyError, load, replay
from marketintel.backtest.walkforward import walk_forward
from marketintel.config import DataSource, Settings
from marketintel.persistence.recorder import read_frames
from marketintel.persistence.sink import AuditSink
from marketintel.sim.binance_sim import FakeBinance
from marketintel.sim.coinbase_sim import FakeCoinbase
from marketintel.sim.world import MarketWorld

from ..conftest import Sims, fast_settings, make_engine


def bt_settings() -> Settings:
    s = Settings(data_source=DataSource.REPLAY, persistence={"jsonl_dir": None})
    s.coinbase.fees.taker_bps = s.coinbase.fees.maker_bps = 5.0
    s.strategies.cross_exchange.max_quote_age_ms = 2000
    s.strategies.cross_exchange.max_recv_skew_ms = 1000
    s.risk.max_quote_age_ms = 2000
    s.risk.max_skew_ms = 1000
    s.engine.feature_history_s = 20
    s.strategies.anomalies.baseline_s = 8
    s.binance.quiet_after_ms = s.coinbase.quiet_after_ms = 2000
    return s


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def recording(tmp_path_factory):
    d = tmp_path_factory.mktemp("rec")
    world = MarketWorld(21, lag_ms={"BINANCE": 0.0, "COINBASE": 0.0})
    b = FakeBinance(world=world, updates_per_s=1200, seed=21)
    c = FakeCoinbase(world, updates_per_s=400, seed=22)
    await b.start()
    await c.start()
    s = fast_settings(recording={"enabled": True, "directory": str(d)})
    s.coinbase.fees.taker_bps = s.coinbase.fees.maker_bps = 5.0
    engine = await make_engine(Sims(world, b, c), s, components=False)
    await engine.start()
    try:
        await asyncio.sleep(6)
        for asset, bps in (("BTC", 40), ("ETH", -45), ("SOL", 50)):
            world.dislocate(asset, "COINBASE", bps, 1.5)
            await asyncio.sleep(2.0)
        await asyncio.sleep(2)
    finally:
        await engine.stop()
        await b.stop()
        await c.stop()
    return engine.recorder.path


def test_replay_is_deterministic_and_trades_injected_dislocations(recording):
    r1 = replay(recording, bt_settings(), warmup_s=5)
    r2 = replay(recording, bt_settings(), warmup_s=5)
    p1, p2 = r1.engine.component("paper"), r2.engine.component("paper")
    sig = lambda p: [(e.strategy, e.route_id, e.status, round(e.result["pnl_usd"], 9))  # noqa: E731
                     for e in p.recent_executions]
    assert sig(p1) == sig(p2) and len(sig(p1)) >= 1
    assert any(e.strategy == "cross_exchange" for e in p1.recent_executions)
    ev1, ev2 = r1.engine.component("evaluation"), r2.engine.component("evaluation")
    assert ev1.registered == ev2.registered
    assert r1.engine.data_source.value == "REPLAY" and r1.frames > 1000


def test_replay_never_sees_the_future(recording):
    meta, frames = load(recording)
    violations = []

    class Guard:
        name = "guard"

        def __init__(self, eng):
            self.eng = eng

        def on_quotes(self, batch, now):
            assert now == self.eng.clock.mono()
            for st in self.eng.state.instruments.values():
                if st.book_recv_mono_ns > now:
                    violations.append(st.key)

    from marketintel.backtest import replay as rp
    orig = rp.build_replay_engine

    def patched(*a, **kw):
        eng = orig(*a, **kw)
        eng.add_component(Guard(eng), quotes=True)
        return eng

    rp.build_replay_engine = patched
    try:
        rp.replay(meta=meta, frames=frames[:3000], settings=bt_settings(), warmup_s=1)
    finally:
        rp.build_replay_engine = orig
    assert violations == []


def test_out_of_order_recording_is_refused(recording, tmp_path):
    lines = gzip.open(recording, "rb").read().splitlines(keepends=True)
    bad = tmp_path / "bad.tsv.gz"
    body = lines[1:]
    body[100], body[101] = body[101], body[100]
    if body[100].split(b"\t")[1] == body[101].split(b"\t")[1]:
        body[100], body[200] = body[200], body[100]
    with gzip.open(bad, "wb") as fh:
        fh.writelines([lines[0]] + body)
    with pytest.raises(ChronologyError):
        load(str(bad))


def test_backtest_report_metrics_and_labels(recording):
    sink = AuditSink(capacity=1_000_000)
    res = replay(recording, bt_settings(), warmup_s=5, sink=sink)
    rep = report(res)
    assert rep["label"] == "SIMULATED BACKTEST" and rep["limitations"]
    p = rep["paper"]
    for k in ("net_pnl_usd", "return_on_capital", "max_drawdown_usd", "win_rate", "turnover_usd", "sharpe",
              "executions_by_status", "estimated_vs_simulated_slippage_bps", "by_strategy", "by_venues", "regimes"):
        assert k in p
    assert p["sharpe"]["value"] is None and "not computed" in p["sharpe"]["note"]  # too short: honest
    o = rep["opportunities"]["cross_exchange"]
    assert o["candidates"] >= 1 and "false_positive_rate" in o and "naive_baseline" in o
    assert rep["signals"]["min_sample"] == 30
    # Audit trail produced during replay.
    assert sink.recent["opportunity_candidates"] and sink.recent["sim_orders"]


def test_walk_forward_selects_in_sample_reports_out_of_sample(recording):
    wf = walk_forward(recording, bt_settings(), folds=3, grid=[1.0, 50.0], warmup_s=3)
    assert wf["label"] == "SIMULATED WALK-FORWARD" and len(wf["results"]) == 2
    for f in wf["results"]:
        assert f["chosen_min_net_edge_bps"] in (1.0, 50.0)
        assert f["in_sample_window_ns"][1] == f["out_of_sample_window_ns"][0]


def test_processing_and_execution_delay_change_outcomes(recording):
    fast = bt_settings()
    slow = bt_settings()
    slow.paper.processing_delay_ms = 3000.0  # decisions arrive after the dislocations ended
    rf, rs = report(replay(recording, fast, warmup_s=5)), report(replay(recording, slow, warmup_s=5))
    filled = lambda r: r["paper"]["executions_by_status"]["FILLED"] + r["paper"]["executions_by_status"]["PARTIAL"]  # noqa: E731
    assert filled(rs) <= filled(rf)
    assert rs["paper"]["executions_by_status"]["MISSED"] >= rf["paper"]["executions_by_status"]["MISSED"]


def test_metric_helpers():
    assert max_drawdown([100, 120, 90, 130, 80]) == (50, pytest.approx(50 / 130))
    assert sharpe([(0, 100.0), (10**9, 101.0)])["value"] is None


def test_candle_level_evaluation(tmp_path):
    import math
    path = tmp_path / "BTCUSDT-1m.csv"
    rows = []
    p = 100.0
    for i in range(400):
        p *= math.exp(0.001 * math.sin(i / 7) + 0.0005 * ((i * 7919) % 13 - 6) / 6)
        rows.append(f"{1700000000000 + i * 60000},{p:.4f},{p * 1.001:.4f},{p * 0.999:.4f},{p:.4f},10,"
                    f"{1700000059999 + i * 60000},1000,5,5,500,0\n")
    path.write_text("open_time,open,high,low,close,volume,close_time,quote_volume,trades,tbb,tbq,ignore\n" + "".join(rows))
    rep = evaluate_file(str(path), cost_bps=10.0)
    assert rep["label"].startswith("CANDLE-LEVEL") and rep["bars"] == 400
    assert set(rep["results"]) == {"momentum", "mean_reversion", "breakout", "baseline.random"}
    bad = tmp_path / "bad.csv"
    bad.write_text(rows[1] + rows[0])
    with pytest.raises(ValueError):
        load_klines(str(bad))


def test_recording_frames_are_multi_venue(recording):
    venues = set()
    meta, _ = load(recording)
    conn_venue = {p["conn_id"]: p["venue"] for p in meta["plans"]}
    for f in read_frames(recording):
        venues.add(conn_venue.get(f.conn_id, "REST_SNAPSHOT"))
    # Both venues' WebSocket frames plus the REST depth snapshots needed to rebuild Binance books.
    assert venues == {"BINANCE", "COINBASE", "REST_SNAPSHOT"} and os.path.getsize(recording) > 0
