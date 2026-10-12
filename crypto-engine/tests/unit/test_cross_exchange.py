import math

import pytest

from marketintel.config import DataSource, Settings
from marketintel.exchanges.base import MappingConfidence

from ..helpers import advance, offline_engine, quote, spec


def settings(**xex):
    s = Settings(data_source=DataSource.REPLAY, persistence={"jsonl_dir": None}, paper={"enabled": False})
    for k, v in xex.items():
        setattr(s.strategies.cross_exchange, k, v)
    return s


def make(**kw):
    specs = [
        spec("BINANCE", "BTCUSDT", "BTC", "USDT", taker=10.0, step="0.00001"),
        spec("COINBASE", "BTC-USDT", "BTC", "USDT", taker=20.0, step="0.00000001"),
        spec("BINANCE", "ETHUSDT", "ETH", "USDT", taker=10.0),
        spec("COINBASE", "ETH-USD", "ETH", "USD", taker=20.0),
        spec("COINBASE", "USDT-USD", "USDT", "USD", taker=0.0, tick="0.0001", step="0.01"),
    ]
    return offline_engine(specs, settings(**kw))


def scanner(eng):
    return eng.component("cross_exchange")


def test_identical_quote_net_edge_from_cash_flows():
    eng = make(min_net_edge_bps=1.0, max_notional_usd=1_000_000.0)
    quote(eng, "BINANCE:BTCUSDT", "59990", "60000", ask_qty="0.5")
    quote(eng, "COINBASE:BTC-USDT", "60300", "60310", bid_qty="0.2")
    quote(eng, "COINBASE:USDT-USD", "0.9999", "1.0001", "1000000", "1000000")
    eng.drain()
    ev = scanner(eng).last["BINANCE:BTCUSDT>COINBASE:BTC-USDT"]
    # Buy at Binance ASK, sell at Coinbase BID: gross = (60300 - 60000) / 60000 = 50 bps
    assert ev["gross_bps"] == pytest.approx(50.0)
    # Size: min(touch 0.5, touch 0.2) on a common step (lcm of steps) -> 0.2
    assert ev["qty"] == pytest.approx(0.2) and ev["size_limited_by"] == "sell_touch"
    cost = 60000 * 0.2 * 1.001
    proceeds = 60300 * 0.2 * (1 - 0.002)
    assert ev["net_bps"] == pytest.approx((proceeds - cost) / cost * 1e4, abs=1e-3)
    # Decomposition is consistent with compounding (fees not double-counted).
    assert ev["net_bps"] == pytest.approx(ev["gross_bps"] - ev["fee_bps"], abs=0.5)
    assert ev["status"] == "VALID" and ev["reasons"] == []
    assert ev["expected_profit_usd"] == pytest.approx((proceeds - cost) * 0.99999998, rel=1e-3)
    # Reverse direction: buy Coinbase ask 60310, sell Binance bid 59990 -> negative gross, not a candidate.
    rev = scanner(eng).last["COINBASE:BTC-USDT>BINANCE:BTCUSDT"]
    assert rev["gross_bps"] < 0 and "COINBASE:BTC-USDT>BINANCE:BTCUSDT" not in scanner(eng).tracker.open
    ep = scanner(eng).tracker.open["BINANCE:BTCUSDT>COINBASE:BTC-USDT"]
    assert ep.status == "VALID" and ep.ever_valid
    assert len(eng.sink.recent["opportunity_candidates"]) == 1


def test_mid_price_is_never_used_as_executable():
    eng = make()
    # Mids cross (Binance mid 60150 < Coinbase mid 60155) but executable prices do not.
    quote(eng, "BINANCE:BTCUSDT", "60000", "60300")
    quote(eng, "COINBASE:BTC-USDT", "60150", "60160")
    eng.drain()
    ev = scanner(eng).last["BINANCE:BTCUSDT>COINBASE:BTC-USDT"]
    assert ev["gross_bps"] < 0 and not scanner(eng).tracker.open


def test_conversion_through_usdt_usd_market_applies_spread_and_fee():
    eng = make(min_net_edge_bps=-1e9, max_notional_usd=1e9)
    quote(eng, "BINANCE:ETHUSDT", "2999", "3000", ask_qty="1")
    quote(eng, "COINBASE:ETH-USD", "3030", "3031", bid_qty="1")
    quote(eng, "COINBASE:USDT-USD", "0.9990", "1.0010", "1000000", "1000000")
    eng.drain()
    ev = scanner(eng).last["BINANCE:ETHUSDT>COINBASE:ETH-USD"]
    assert ev["conversion"] == "COINBASE:USDT-USD"
    # Proceeds in USD are converted back to USDT by BUYING USDT at its ask (1.0010).
    qty = ev["qty"]
    cost = 3000 * qty * 1.001
    proceeds = 3030 * qty * 0.998 / 1.0010
    assert ev["net_bps"] == pytest.approx((proceeds - cost) / cost * 1e4, abs=1e-3)
    assert ev["conversion_bps"] > 0
    # Gross uses the conversion mid (1.0): (3030 - 3000)/3000 = 100 bps
    assert ev["gross_bps"] == pytest.approx(100.0, abs=1e-6)


def test_stale_or_missing_conversion_and_quotes_are_rejected():
    eng = make(min_net_edge_bps=1.0, max_quote_age_ms=500, max_recv_skew_ms=200, max_conversion_age_ms=1000)
    quote(eng, "BINANCE:BTCUSDT", "59990", "60000")
    advance(eng, 300)
    quote(eng, "COINBASE:BTC-USDT", "60300", "60310")
    eng.drain()
    ev = scanner(eng).last["BINANCE:BTCUSDT>COINBASE:BTC-USDT"]
    assert ev["status"] == "REJECTED" and any(r.startswith("recv_skew") for r in ev["reasons"])
    advance(eng, 400)
    quote(eng, "COINBASE:BTC-USDT", "60300", "60310")
    eng.drain()
    ev = scanner(eng).last["BINANCE:BTCUSDT>COINBASE:BTC-USDT"]
    assert any(r.startswith("quote_stale:BINANCE:BTCUSDT") for r in ev["reasons"])
    # ETH via conversion with no USDT-USD quote at all -> unusable conversion, closed/not candidate.
    quote(eng, "BINANCE:ETHUSDT", "2999", "3000")
    quote(eng, "COINBASE:ETH-USD", "3030", "3031")
    eng.drain()
    ev = scanner(eng).last["BINANCE:ETHUSDT>COINBASE:ETH-USD"]
    assert ev["status"] == "REJECTED" and ev.get("close_reason") == "conversion_unavailable"


def test_insufficient_liquidity_minimums_and_threshold():
    eng = make(min_net_edge_bps=1.0, min_liquidity_usd=50.0)
    quote(eng, "BINANCE:BTCUSDT", "59990", "60000", ask_qty="0.0005")   # $30 at the touch
    quote(eng, "COINBASE:BTC-USDT", "60300", "60310", bid_qty="1")
    eng.drain()
    ev = scanner(eng).last["BINANCE:BTCUSDT>COINBASE:BTC-USDT"]
    assert any(r.startswith("insufficient_liquidity") for r in ev["reasons"])
    quote(eng, "BINANCE:BTCUSDT", "59990", "60000", ask_qty="0.000001")  # below the 0.00001 step
    eng.drain()
    ev = scanner(eng).last["BINANCE:BTCUSDT>COINBASE:BTC-USDT"]
    assert any(r.startswith("no_executable_size") for r in ev["reasons"]) and ev["qty"] == 0
    # Positive gross but costs exceed it -> candidate recorded, rejected below threshold.
    quote(eng, "BINANCE:BTCUSDT", "59990", "60000", ask_qty="1")
    quote(eng, "COINBASE:BTC-USDT", "60010", "60020", bid_qty="1")
    eng.drain()
    ev = scanner(eng).last["BINANCE:BTCUSDT>COINBASE:BTC-USDT"]
    assert 0 < ev["gross_bps"] < ev["fee_bps"] and ev["net_bps"] < 0
    assert any(r.startswith("net_below_threshold") for r in ev["reasons"])


def test_inferred_mapping_never_compared():
    specs = [spec("BINANCE", "ABCUSDT", "ABC", "USDT"), spec("COINBASE", "ABC-USDT", "ABC", "USDT")]
    eng = offline_engine(specs, settings())
    assert eng.registry.by_key["BINANCE:ABCUSDT"].mapping is MappingConfidence.INFERRED
    assert scanner(eng).pairs == []


def test_episode_lifecycle_and_lifetime():
    eng = make(min_net_edge_bps=1.0)
    sc = scanner(eng)
    quote(eng, "BINANCE:BTCUSDT", "59990", "60000")
    quote(eng, "COINBASE:BTC-USDT", "60300", "60310")
    eng.drain()
    ep = sc.tracker.open["BINANCE:BTCUSDT>COINBASE:BTC-USDT"]
    advance(eng, 250)
    quote(eng, "COINBASE:BTC-USDT", "60030", "60040")  # still gross>0 but no longer net-profitable
    eng.drain()
    assert ep.status == "REJECTED" and len(ep.transitions) == 2
    advance(eng, 250)
    quote(eng, "COINBASE:BTC-USDT", "59900", "59910")  # edge gone -> episode closed
    eng.drain()
    assert "BINANCE:BTCUSDT>COINBASE:BTC-USDT" not in sc.tracker.open
    assert ep.closed_mono_ns and ep.close_reason == "edge_gone"
    # ...and the opposite direction is now a (separate) candidate: buy 59910 < sell 59990.
    assert "COINBASE:BTC-USDT>BINANCE:BTCUSDT" in sc.tracker.open
    assert ep.lifetime_ms == pytest.approx(500.0)
    out = eng.sink.recent["opportunity_outcomes"][-1]
    assert out["status"] == "VALID_NOT_EXECUTED" and out["correlation_id"] == ep.episode_id
    assert [v["status"] for v in eng.sink.recent["opportunity_validations"]
            if v["correlation_id"] == ep.episode_id] == ["VALID", "REJECTED"]
    assert not math.isnan(ep.peak_net_bps)
