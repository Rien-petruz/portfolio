from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from marketintel.config import DataSource, Settings
from marketintel.market_data.events import BookSnapshot, Trade
from marketintel.numeric import ONE, parse_e8
from marketintel.paper_trading.orders import OrderStatus, OrderType, Side, SimOrder, TimeInForce, client_order_id
from marketintel.paper_trading.portfolio import Portfolio

from ..helpers import advance, offline_engine, quote, spec


def cfg(**over):
    s = Settings(data_source=DataSource.REPLAY, persistence={"jsonl_dir": None})
    s.strategies.cross_exchange.min_net_edge_bps = 1.0
    s.strategies.cross_exchange.max_notional_usd = 3000.0
    s.paper.latency_jitter_ms = 0.0
    s.paper.order_latency_ms = {"BINANCE": 50.0, "COINBASE": 80.0}
    s.paper.starting_balances = {"BINANCE": {"USDT": 50_000.0, "BTC": 0.5},
                                 "COINBASE": {"USD": 50_000.0, "USDT": 10_000.0, "BTC": 0.5}}
    for k, v in over.items():
        section, _, field = k.partition("__")
        setattr(getattr(s, section), field, v)
    return s


def make(depth=False, **over):
    specs = [
        spec("BINANCE", "BTCUSDT", "BTC", "USDT", taker=10.0, step="0.00001", depth=depth),
        spec("COINBASE", "BTC-USDT", "BTC", "USDT", taker=20.0, step="0.00000001", depth=depth),
        spec("COINBASE", "USDT-USD", "USDT", "USD", taker=0.0, tick="0.0001", step="0.01"),
    ]
    eng = offline_engine(specs, cfg(**over))
    quote(eng, "COINBASE:USDT-USD", "0.9999", "1.0001", "1000000", "1000000")
    return eng


def paper(eng):
    return eng.component("paper")


def open_arb(eng, ask_qty="0.04", bid_qty="0.04"):
    quote(eng, "BINANCE:BTCUSDT", "59990", "60000", ask_qty=ask_qty)
    quote(eng, "COINBASE:BTC-USDT", "60300", "60310", bid_qty=bid_qty)
    eng.drain()


def test_valid_opportunity_fills_both_legs_after_latency():
    eng = make()
    p = paper(eng)
    open_arb(eng)
    ep = eng.component("cross_exchange").tracker.open["BINANCE:BTCUSDT>COINBASE:BTC-USDT"]
    orders = list(p.orders.values())
    assert len(orders) == 2 and all(o.status is OrderStatus.PENDING for o in orders)
    assert {o.client_id for o in orders} == {client_order_id(ep.episode_id, "buy"), client_order_id(ep.episode_id, "sell")}
    advance(eng, 49)
    assert all(o.status is OrderStatus.PENDING for o in orders)  # still travelling
    advance(eng, 40)
    assert all(o.status is OrderStatus.FILLED for o in orders)
    buy, sell = sorted(orders, key=lambda o: o.side.value)
    assert buy.avg_px == 60000 and sell.avg_px == 60300 and buy.filled_qty_e8 == sell.filled_qty_e8 == parse_e8("0.04")
    assert buy.estimate and sell.estimate  # touch model only (no local books here)
    res = ep.execution
    assert res["status"] == "FILLED" and res["label"] == "SIMULATED" and res["unhedged"] == []
    expected = 60300 * 0.04 * (1 - 0.002) - 60000 * 0.04 * 1.001
    assert res["pnl_usd"] == pytest.approx(expected * 1.0, rel=1e-3)
    assert res["quote_cashflow_usd"] == pytest.approx(res["pnl_usd"], rel=1e-9)  # hedged: no base flow
    assert "BTC" not in res["asset_flows"]
    pf = p.portfolio
    assert pf.balance("BINANCE", "BTC") == Decimal("0.54") and pf.balance("COINBASE", "BTC") == Decimal("0.46")
    assert pf.balance("BINANCE", "USDT") == Decimal("50000") - Decimal("2400") * Decimal("1.001")
    v = pf.valuation()
    assert v["pnl_usd"] == pytest.approx(v["realized_usd"] + v["unrealized_usd"], abs=1e-6)
    assert len(eng.sink.recent["sim_fills"]) == 2
    assert all(r["label"] == "SIMULATED" for r in eng.sink.recent["sim_fills"])


def test_opportunity_gone_during_latency_is_missed():
    eng = make()
    open_arb(eng)
    quote(eng, "COINBASE:BTC-USDT", "59900", "59910")  # bid collapses before the sell order arrives
    quote(eng, "BINANCE:BTCUSDT", "60100", "60200")     # ask moves above the buy limit
    advance(eng, 200)
    ex = paper(eng).recent_executions[-1]
    assert ex.status == "MISSED" and all(o.filled_qty_e8 == 0 for o in ex.orders)
    assert all(o.status is OrderStatus.CANCELED for o in ex.orders)
    assert "no_liquidity_within_limit_at_arrival" in ex.orders[0].reject_reason


def test_partial_fill_leaves_unhedged_inventory():
    eng = make()
    open_arb(eng)
    quote(eng, "COINBASE:BTC-USDT", "60300", "60310", bid_qty="0.01")  # only 0.01 left on the bid at arrival
    advance(eng, 200)
    ex = paper(eng).recent_executions[-1]
    assert ex.status == "PARTIAL"
    assert ex.result["unhedged"] == [{"asset": "BTC", "qty": pytest.approx(0.03), "where": "long on buy venue"}]
    # P&L marks the unhedged BTC: cash flow alone (-1800 USDT) would be misleading.
    btc_mark = paper(eng).valuation.usd("BTC")[0]
    assert ex.result["asset_flows"]["BTC"] == pytest.approx(0.03)
    assert ex.result["pnl_usd"] == pytest.approx(ex.result["quote_cashflow_usd"] + 0.03 * btc_mark, rel=1e-9)
    assert abs(ex.result["pnl_usd"]) < 20 < abs(ex.result["quote_cashflow_usd"])


def test_depth_model_walks_levels_and_ledger_prevents_double_consumption():
    eng = make(depth=True)
    p = paper(eng)
    book_key = "BINANCE:BTCUSDT"
    snap = BookSnapshot(book_key, 1, 0, [(parse_e8("59990"), parse_e8("1"))],
                        [(parse_e8("60000"), parse_e8("0.01")), (parse_e8("60010"), parse_e8("0.01")),
                         (parse_e8("60050"), parse_e8("5"))], eng.clock.mono(), eng.clock.wall(), 0, 1)
    eng.books.on_snapshot(snap)
    quote(eng, book_key, "59990", "60000", ask_qty="0.01")
    assert p.portfolio.initialize()
    spec_ = eng.registry.get(book_key)
    o1 = SimOrder("c1", "p", "manual", "BINANCE", book_key, Side.BUY, OrderType.LIMIT, TimeInForce.IOC,
                  parse_e8("0.015"), parse_e8("60020"), eng.clock.mono(), eng.clock.wall(),
                  reference_px_e8=parse_e8("60000"))
    o2 = SimOrder("c2", "p", "manual", "BINANCE", book_key, Side.BUY, OrderType.LIMIT, TimeInForce.IOC,
                  parse_e8("0.015"), parse_e8("60020"), eng.clock.mono(), eng.clock.wall())
    p.submit(o1)
    p.submit(o2)
    advance(eng, 100)
    assert [(f.px_e8 / ONE, f.qty_e8 / ONE) for f in o1.fills] == [(60000, 0.01), (60010, 0.005)]
    assert not o1.estimate and o1.status is OrderStatus.FILLED
    # o2 sees only what o1 left within its limit (0.005 @ 60010); the rest is cancelled (IOC).
    assert [(f.px_e8 / ONE, f.qty_e8 / ONE) for f in o2.fills] == [(60010, 0.005)]
    assert o2.status is OrderStatus.CANCELED
    assert o1.slippage_bps() > 0 and spec_.fees.taker_bps == 10.0


def test_market_order_not_assumed_to_fill_at_best_price():
    eng = make()
    p = paper(eng)
    quote(eng, "BINANCE:BTCUSDT", "59990", "60000", ask_qty="0.01")
    assert p.portfolio.initialize()
    o = SimOrder("m1", "p", "manual", "BINANCE", "BINANCE:BTCUSDT", Side.BUY, OrderType.MARKET, TimeInForce.IOC,
                 parse_e8("0.03"), 0, eng.clock.mono(), eng.clock.wall())
    p.submit(o)
    advance(eng, 100)
    assert o.filled_qty_e8 == parse_e8("0.01") and o.status is OrderStatus.CANCELED and o.estimate


def test_duplicate_client_ids_are_idempotent():
    eng = make()
    p = paper(eng)
    quote(eng, "BINANCE:BTCUSDT", "59990", "60000")
    assert p.portfolio.initialize()
    mk = lambda: SimOrder("same-id", "p", "manual", "BINANCE", "BINANCE:BTCUSDT", Side.BUY, OrderType.LIMIT,  # noqa: E731
                          TimeInForce.IOC, parse_e8("0.01"), parse_e8("60000"), eng.clock.mono(), eng.clock.wall())
    first = p.submit(mk())
    again = p.submit(mk())
    assert again is first and p.counters["duplicates"] == 1 and len(p.orders) == 1
    advance(eng, 100)
    assert p.portfolio.balance("BINANCE", "BTC") == Decimal("0.51")  # executed once


def test_order_level_risk_and_filter_rejections():
    eng = make(risk__max_order_notional_usd=500.0)
    p = paper(eng)
    quote(eng, "BINANCE:BTCUSDT", "59990", "60000")
    assert p.portfolio.initialize()
    base = dict(parent_id="p", strategy="manual", venue="BINANCE", key="BINANCE:BTCUSDT", type=OrderType.LIMIT,
                tif=TimeInForce.IOC, created_mono_ns=eng.clock.mono(), created_wall_ns=eng.clock.wall())
    big = p.submit(SimOrder("r1", side=Side.BUY, qty_e8=parse_e8("0.01"), limit_px_e8=parse_e8("60000"), **base))
    assert big.status is OrderStatus.REJECTED and "max_order_notional" in big.reject_reason
    off_step = p.submit(SimOrder("r2", side=Side.BUY, qty_e8=parse_e8("0.000005"), limit_px_e8=parse_e8("60000"), **base))
    assert "qty_not_on_step" in off_step.reject_reason
    too_much = p.submit(SimOrder("r3", side=Side.SELL, qty_e8=parse_e8("0.008"), limit_px_e8=parse_e8("59990"), **base))
    assert too_much.status is OrderStatus.PENDING  # 480 USD ok, BTC available
    eng.cfg.risk.max_order_notional_usd = 1e9
    no_bal = p.submit(SimOrder("r4", side=Side.SELL, qty_e8=parse_e8("5"), limit_px_e8=parse_e8("59990"), **base))
    assert "insufficient_balance:BTC" in no_bal.reject_reason
    assert any(r["event"] == "order_check" for r in eng.sink.recent["risk_events"])


def test_reservations_prevent_overspending_in_flight():
    eng = make()
    p = paper(eng)
    quote(eng, "BINANCE:BTCUSDT", "59990", "60000")
    assert p.portfolio.initialize()
    eng.cfg.risk.max_order_notional_usd = 1e9
    eng.cfg.risk.max_position_usd_per_asset = 1e9
    eng.cfg.risk.max_exposure_usd_per_venue = 1e9
    eng.cfg.risk.max_total_exposure_usd = 1e9
    base = dict(parent_id="p", strategy="manual", venue="BINANCE", key="BINANCE:BTCUSDT", type=OrderType.LIMIT,
                tif=TimeInForce.IOC, created_mono_ns=eng.clock.mono(), created_wall_ns=eng.clock.wall(),
                side=Side.SELL, limit_px_e8=parse_e8("59990"))
    a = p.submit(SimOrder("a", qty_e8=parse_e8("0.3"), **base))
    b = p.submit(SimOrder("b", qty_e8=parse_e8("0.3"), **base))  # only 0.2 BTC left unreserved
    assert a.status is OrderStatus.PENDING and b.status is OrderStatus.REJECTED


def test_emergency_stop_blocks_and_cancels_and_daily_loss_trips_it():
    eng = make()
    p = paper(eng)
    open_arb(eng)
    pending = [o for o in p.orders.values() if not o.is_final]
    assert pending
    p.risk.emergency_stop("manual test", manual=True)
    p.cancel_all("emergency_stop")
    assert all(o.status is OrderStatus.CANCELED for o in pending)
    advance(eng, 300)
    quote(eng, "COINBASE:BTC-USDT", "60400", "60410")
    eng.drain()
    ok, reasons = p.risk.check_opportunity({"net_bps": 100, "strategy": "x", "route_id": "y", "liquidity_usd": 1e6}, eng.clock.mono())
    assert not ok and reasons[0].startswith("emergency_stop")
    p.risk.resume()
    assert not p.risk.halted
    # Daily loss: P&L below the limit within the same UTC day trips the latched stop.
    p.risk.on_summary(eng.clock.mono(), {"status": "OK"}, 0.0)
    p.risk.on_summary(eng.clock.mono(), {"status": "OK"}, -eng.cfg.risk.max_daily_loss_usd - 1)
    assert p.risk.halted and p.risk.halt_reason.startswith("max_daily_loss")
    events = [r for r in eng.sink.recent["risk_events"] if r["event"] == "emergency"]
    assert [e["status"] for e in events] == ["HALTED", "RESUMED", "HALTED"]


def test_health_down_blocks_new_opportunities():
    eng = make()
    p = paper(eng)
    p.risk.on_summary(eng.clock.mono(), {"status": "DOWN"}, None)
    ok, reasons = p.risk.check_opportunity({"net_bps": 100, "strategy": "x", "route_id": "z", "liquidity_usd": 1e6},
                                           eng.clock.mono())
    assert not ok and "feed_health_blocked" in reasons


def test_risk_frequency_and_duplicate_window():
    eng = make(risk__max_signals_per_minute=2, risk__duplicate_window_ms=1000)
    r = paper(eng).risk
    ev = {"net_bps": 50, "strategy": "s", "route_id": "r", "liquidity_usd": 1e6}
    assert r.check_opportunity(ev, eng.clock.mono())[0]
    ok, reasons = r.check_opportunity(ev, eng.clock.mono())
    assert not ok and "duplicate_within_window" in reasons
    advance(eng, 1500)
    assert r.check_opportunity(ev, eng.clock.mono())[0]
    advance(eng, 1500)
    ok, reasons = r.check_opportunity(ev, eng.clock.mono())
    assert not ok and any(x.startswith("max_signal_frequency") for x in reasons)


def test_gtc_limit_fills_only_on_trade_through_and_expires():
    eng = make(paper__gtc_ttl_ms=2000)
    p = paper(eng)
    quote(eng, "BINANCE:BTCUSDT", "59990", "60000")
    assert p.portfolio.initialize()
    o = SimOrder("g1", "p", "manual", "BINANCE", "BINANCE:BTCUSDT", Side.BUY, OrderType.LIMIT, TimeInForce.GTC,
                 parse_e8("0.02"), parse_e8("59900"), eng.clock.mono(), eng.clock.wall())
    p.submit(o)
    advance(eng, 100)
    assert o.status is OrderStatus.OPEN
    t = eng.clock.mono()
    p.on_trades([Trade("BINANCE:BTCUSDT", 1, parse_e8("59900"), parse_e8("1"), -1, t, t, t, t, 0)], t)
    assert o.filled_qty_e8 == 0  # at the limit, not through it: queue position unknown
    p.on_trades([Trade("BINANCE:BTCUSDT", 2, parse_e8("59899"), parse_e8("0.005"), -1, t, t, t, t, 0)], t)
    assert o.filled_qty_e8 == parse_e8("0.005") and o.status is OrderStatus.PARTIALLY_FILLED and o.estimate
    assert o.fills[0].liquidity == "trade_through"
    advance(eng, 2500)
    assert o.status is OrderStatus.EXPIRED


@settings(max_examples=40, deadline=None)
@given(st.lists(st.tuples(st.sampled_from(["BUY", "SELL"]), st.integers(1, 2000), st.integers(55_000, 65_000),
                          st.sampled_from([0.0, 0.001, 0.002])), min_size=1, max_size=30),
       st.floats(50_000, 70_000), st.floats(0.98, 1.02))
def test_pnl_identity_holds_for_any_fill_sequence(fills, btc_mark, usdt_mark):
    marks = {"USD": 1.0, "USDT": 1.0, "BTC": 60_000.0}
    pf = Portfolio({"V": {"USDT": 1_000_000.0, "BTC": 10.0, "USD": 100.0}}, marks.get)
    assert pf.initialize()
    for side, qty_k, px, fee in fills:
        pf.apply_fill("V", "BTC", "USDT", side, px * ONE, qty_k * 100_000, fee)
    pf.fund("V", "ETH", Decimal("2"), Decimal("3000"))
    marks.update(BTC=btc_mark, USDT=usdt_mark, ETH=3100.0)
    v = pf.valuation()
    assert v["pnl_usd"] == pytest.approx(v["realized_usd"] + v["unrealized_usd"], abs=1e-6)
    assert v["funding_usd"] == pytest.approx(6000.0)
