import math
import random

import pytest

from marketintel.config import DataSource, Settings
from marketintel.market_data.events import BUY, Trade
from marketintel.numeric import parse_e8
from marketintel.paper_trading.orders import OrderStatus, Side
from marketintel.strategies.triangular import build_routes

from ..helpers import advance, offline_engine, quote, spec


def settings(**kw):
    s = Settings(data_source=DataSource.REPLAY, persistence={"jsonl_dir": None})
    s.engine.feature_history_s = 90
    s.strategies.anomalies.baseline_s = 60
    s.strategies.anomalies.cooldown_s = 5
    s.strategies.patterns.cooldown_s = 5
    for k, v in kw.items():
        section, _, field = k.partition("__")
        obj = s.strategies if section in ("anomalies", "patterns", "triangular", "cross_exchange") else s
        setattr(getattr(obj, section), field, v)
    return s


SPECS = [
    spec("BINANCE", "BTCUSDT", "BTC", "USDT", step="0.00001"),
    spec("BINANCE", "ETHUSDT", "ETH", "USDT"),
    spec("BINANCE", "SOLUSDT", "SOL", "USDT"),
    spec("COINBASE", "ETH-USDT", "ETH", "USDT", step="0.00000001"),
]
BASE = {"BINANCE:BTCUSDT": 60000.0, "BINANCE:ETHUSDT": 3000.0, "BINANCE:SOLUSDT": 150.0, "COINBASE:ETH-USDT": 3000.0}


class Driver:
    """Feeds 100 ms steps of quotes/trades into an offline engine."""

    def __init__(self, eng, seed=1, noise_bps=1.0):
        self.eng = eng
        self.rng = random.Random(seed)
        self.noise = noise_bps
        self.px = dict(BASE)
        self.tid = 0
        self.frozen: set[str] = set()
        self.silent: set[str] = set()
        self.basis = 0.0  # Coinbase ETH tracks Binance ETH plus a small mean-reverting basis

    def step(self, n=1, trades=("BINANCE:ETHUSDT",), shocks=None):
        for _ in range(n):
            for k in self.px:
                if k not in self.frozen and k != "COINBASE:ETH-USDT":
                    self.px[k] *= math.exp(self.rng.gauss(0, self.noise * 1e-4))
            self.basis = 0.5 * self.basis + self.rng.gauss(0, 0.5e-4)
            for k, bps in (shocks or {}).items():
                if k == "COINBASE:ETH-USDT":
                    self.basis += bps / 1e4
                else:
                    self.px[k] *= 1 + bps / 1e4
            self.px["COINBASE:ETH-USDT"] = self.px["BINANCE:ETHUSDT"] * (1 + self.basis)
            shocks = None
            now = self.eng.clock.mono()
            for k, p in self.px.items():
                if k in self.silent:
                    continue
                half = p * 0.5e-4
                quote(self.eng, k, f"{p - half:.2f}", f"{p + half:.2f}", "5", "5", t=now)
            for k in trades:
                self.tid += 1
                ev = Trade(k, self.tid, parse_e8(f"{self.px[k]:.2f}"), parse_e8("0.1"), BUY, now, now, now, now, 0)
                self.eng.state.apply_trade(ev)
                self.eng.bus.publish_trade(ev)
            self.eng.drain(now)
            advance(self.eng, 100)


def signals(eng, prefix):
    return [s for s in eng.component("evaluation").recent if s.strategy.startswith(prefix)]


def test_warmup_zero_volatility_and_uncorroborated_jump():
    eng = offline_engine(SPECS, settings())
    d = Driver(eng)
    d.frozen.add("BINANCE:SOLUSDT")  # zero volatility instrument
    d.step(30, shocks=None)
    d.step(1, shocks={"BINANCE:ETHUSDT": 80})  # during warm-up: baselines not ready
    assert signals(eng, "anomaly.price_jump") == []
    d.step(700)
    assert not [s for s in signals(eng, "anomaly.price_jump") if s.key == "BINANCE:SOLUSDT"]
    sol = eng.component("anomalies").latest["z"][10][0][eng.component("features").idx["BINANCE:SOLUSDT"]]
    assert sol == 0 or math.isfinite(sol)  # zero-vol is guarded: finite (no inf/NaN blow-up)
    before = len(signals(eng, "anomaly.price_jump"))
    d.step(1, trades=(), shocks={"BINANCE:SOLUSDT": 60})  # no trades, no peer venue: uncorroborated
    jumps = [s for s in signals(eng, "anomaly.price_jump")[before:] if s.key == "BINANCE:SOLUSDT"]
    assert jumps and jumps[0].classification == "UNCORROBORATED" and jumps[0].direction == 1
    assert jumps[0].score_kind == "robust_z" and "not a probability" in jumps[0].view()["note"]


def test_corroborated_jump_and_cross_venue_divergence():
    eng = offline_engine(SPECS, settings())
    d = Driver(eng)
    d.step(700)
    n0 = len(signals(eng, "anomaly"))
    # ETH jumps on both venues with trades -> corroborated
    d.step(1, shocks={"BINANCE:ETHUSDT": 70})  # Coinbase follows: both venues move
    eth = [s for s in signals(eng, "anomaly.price_jump") if s.key == "BINANCE:ETHUSDT"]
    assert eth and all(s.classification == "CORROBORATED_MOVE" for s in eth)
    assert "COINBASE:ETH-USDT" in eth[0].features["peer_confirmation"] and eth[0].features["trades_in_window"] > 0
    d.step(100)
    # Coinbase alone dislocates by 60 bps -> divergence of the basis
    d.step(1, trades=(), shocks={"COINBASE:ETH-USDT": 60})
    div = signals(eng, "anomaly.cross_venue_divergence")
    assert div and div[-1].classification == "CROSS_VENUE_DIVERGENCE" and len(signals(eng, "anomaly")) > n0


def test_data_gap_is_flagged_not_treated_as_market_move():
    s = settings()
    s.binance.quiet_after_ms, s.binance.stale_after_ms = 300, 400
    eng = offline_engine(SPECS, s)
    d = Driver(eng)
    d.step(700)
    g = eng.component("features")
    i = g.idx["BINANCE:SOLUSDT"]
    d.silent.add("BINANCE:SOLUSDT")
    d.step(6)  # SOL goes STALE: those samples are recorded as missing, never as prices
    assert math.isnan(g.latest("mid")[i])
    d.silent.discard("BINANCE:SOLUSDT")
    d.px["BINANCE:SOLUSDT"] *= 1.01  # the first fresh quote after the gap is +100 bps
    d.step(1, trades=())
    sol = [x for x in signals(eng, "anomaly.price_jump") if x.key == "BINANCE:SOLUSDT"]
    # Either suppressed (insufficient coverage) or explicitly flagged - never a clean "market move".
    assert all(x.classification == "DATA_QUALITY_SUSPECT" for x in sol)
    assert any(x.classification == "DATA_QUALITY_SUSPECT" for x in sol) or g.coverage(11)[i] < 0.8


def test_patterns_emit_explained_signals_and_evaluator_scores_them():
    eng = offline_engine(SPECS, settings(patterns__z_entry=3.0))
    d = Driver(eng)
    d.step(700)
    # A sustained BTC rally with acceleration -> momentum/breakout/btc_relative candidates.
    for _ in range(12):
        d.step(1, trades=("BINANCE:BTCUSDT", "BINANCE:ETHUSDT"), shocks={"BINANCE:BTCUSDT": 8})
    pats = signals(eng, "pattern")
    names = {s.strategy for s in pats}
    assert names & {"pattern.momentum_acceleration", "pattern.breakout", "pattern.btc_relative"}
    s = pats[0]
    assert s.explanation and s.features and s.direction in (-1, 0, 1) and s.validation_status == "PENDING_EVALUATION"
    d.step(320)  # beyond the 30 s horizon
    ev = eng.component("evaluation")
    assert s.validation_status in ("EVALUATED", "NOT_EVALUABLE")
    rep = ev.report()
    assert "baseline.random" in rep["results"] and rep["min_sample"] == 30
    some = next(iter(rep["results"][s.strategy].values()))
    assert some["verdict"].startswith(("insufficient_sample", "no_evidence", "differs", "beats", "underperforms"))
    assert eng.sink.recent["strategy_signals"] and eng.sink.recent["signal_evaluations"]


def test_triangular_routes_math_and_sequential_paper_execution():
    specs = [
        spec("BINANCE", "BTCUSDT", "BTC", "USDT", step="0.00001", taker=10),
        spec("BINANCE", "ETHUSDT", "ETH", "USDT", step="0.0001", taker=10),
        spec("BINANCE", "ETHBTC", "ETH", "BTC", tick="0.00001", step="0.0001", min_notional="0.0001", taker=10),
    ]
    routes = build_routes(specs, ["USDT"])
    assert sorted(r.route_id for r in routes) == ["BINANCE:USDT>BTC>ETH>USDT", "BINANCE:USDT>ETH>BTC>USDT"]
    s = settings(triangular__min_net_edge_bps=5.0, triangular__max_start_notional_usd=600.0)
    s.paper.latency_jitter_ms = 0.0
    s.paper.starting_balances = {"BINANCE": {"USDT": 10_000.0}}
    s.paper.auto_base_inventory_usd = 0.0
    s.strategies.cross_exchange.enabled = False
    eng = offline_engine(specs, s)
    tri = eng.component("triangular")
    quote(eng, "BINANCE:BTCUSDT", "59990", "60000", "1", "1")
    quote(eng, "BINANCE:ETHBTC", "0.04899", "0.04900", "10", "10")
    quote(eng, "BINANCE:ETHUSDT", "3000", "3000.5", "10", "10")
    eng.drain()
    ev = tri.last["BINANCE:USDT>BTC>ETH>USDT"]
    # gross = (1/60000) * (1/0.049) * 3000 - 1 = +204.08 bps; three 10 bps taker fees
    assert ev["gross_bps"] == pytest.approx((3000 / (60000 * 0.049) - 1) * 1e4, abs=1e-3)
    assert ev["theoretical_net_bps"] == pytest.approx((3000 / (60000 * 0.049) / 1.001 ** 2 * 0.999 - 1) * 1e4, abs=1e-2)
    assert ev["net_bps"] <= ev["theoretical_net_bps"] + 1e-9  # rounding only ever costs
    assert ev["status"] == "VALID" and ev["size_limited_by"] == "max_start_notional"
    assert ev["start_capital"] <= 600.0
    p = eng.component("paper")
    for _ in range(10):
        advance(eng, 50)
    ex = p.recent_executions[-1]
    legs = ex.orders
    assert [o.key for o in legs] == ["BINANCE:BTCUSDT", "BINANCE:ETHBTC", "BINANCE:ETHUSDT"]
    assert [o.side for o in legs] == [Side.BUY, Side.BUY, Side.SELL]
    assert all(o.status is OrderStatus.FILLED for o in legs) and ex.status == "FILLED"
    assert legs[0].final_mono_ns < legs[1].created_mono_ns < legs[2].created_mono_ns  # sequential, not simultaneous
    # Leg 2 size derived from leg 1's actual BTC output; leg 3 sells exactly what leg 2 bought.
    assert legs[2].qty_e8 == legs[1].filled_qty_e8
    assert p.portfolio.balance("BINANCE", "USDT") > 10_000  # synthetic edge, simulated
    assert ex.result["label"] == "SIMULATED"
