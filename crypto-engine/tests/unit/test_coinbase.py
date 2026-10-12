import json
import os

import orjson
import pytest

from marketintel.config import CoinbaseConfig, RegistryConfig
from marketintel.exchanges.base import FeeSchedule, MappingConfidence, MarketType
from marketintel.exchanges.coinbase.adapter import CoinbaseAdapter
from marketintel.exchanges.coinbase.decoder import CoinbaseDecoder
from marketintel.exchanges.coinbase.products import parse_products
from marketintel.exchanges.errors import DecodeError
from marketintel.exchanges.registry import InstrumentRegistry
from marketintel.market_data.events import BUY, SELL, UNKNOWN_SIDE, BookDelta, BookSnapshot, ConnectionNotice, Trade
from marketintel.numeric import parse_e8
from marketintel.timeparse import rfc3339_to_ns

from ..conftest import FIXTURES


def frames():
    with open(os.path.join(FIXTURES, "coinbase_frames.jsonl"), "rb") as fh:
        return [line.strip() for line in fh if line.strip()]


def test_decoder_fixture_frames():
    d = CoinbaseDecoder(4, sock_uid=9, trade_side="taker")
    out = [d.decode(f, 100, 200) for f in frames()]
    sub, snap, upd, hist, trades, hb = out
    assert sub is None and hb is None and d.heartbeats == 1
    (s,) = snap
    assert isinstance(s, BookSnapshot) and s.key == "COINBASE:BTC-USD" and s.src == 9 and s.conn_id == 4
    assert s.bids == [(parse_e8("21921.73"), parse_e8("0.06317902")), (parse_e8("21921.3"), parse_e8("0.02"))]
    assert s.asks == [(parse_e8("21922.06"), parse_e8("0.5"))]
    assert s.event_time_ns == rfc3339_to_ns("2023-02-09T20:32:50.714964855Z")
    (u,) = upd
    assert isinstance(u, BookDelta) and u.bids == [(parse_e8("21921.73"), 0)] and u.seq == 2
    assert hist == [] and d.history_trades_skipped == 1  # snapshot trades are history, not new flow
    t1, t2 = trades
    assert isinstance(t1, Trade) and t1.trade_id == 12345 and t1.aggressor == SELL
    assert t2.trade_id == -1 and t2.aggressor == BUY  # non-numeric id kept, not dedupable
    assert t1.trade_time_ns == rfc3339_to_ns("2023-02-09T20:19:35.9Z")


def test_trade_side_semantics_configurable():
    raw = frames()[4]
    d = CoinbaseDecoder(0, 0)  # default: unknown -> aggressor not used
    d.last_seq = 3
    assert all(t.aggressor == UNKNOWN_SIDE for t in d.decode(raw, 1, 2))
    d = CoinbaseDecoder(0, 0, trade_side="maker")
    d.last_seq = 3
    assert [t.aggressor for t in d.decode(raw, 1, 2)] == [BUY, SELL]


def test_sequence_gap_requires_resync_and_out_of_order_rejected():
    d = CoinbaseDecoder(1, 1)
    fs = frames()
    d.decode(fs[0], 1, 1)
    d.decode(fs[1], 1, 1)
    notice = d.decode(fs[4], 1, 1)  # seq 4 after 1: messages 2,3 lost
    assert isinstance(notice, ConnectionNotice) and notice.kind == "resync_required" and d.gaps == 1
    with pytest.raises(DecodeError) as ei:
        d.decode(fs[2], 1, 1)  # seq 2 after 4
    assert ei.value.reason == "out_of_order"
    d.reset()
    assert d.decode(fs[2], 1, 1)  # a new socket starts a new sequence


@pytest.mark.parametrize("raw,reason", [
    (b"{bad", "invalid_json"),
    ({"type": "error", "message": "failure to subscribe"}, "control_error"),
    ({"channel": "l2_data", "timestamp": "2023-01-01T00:00:00Z", "events": []}, "missing_field"),
    ({"channel": "nope", "sequence_num": 0, "events": []}, "unknown_event"),
    ({"channel": "l2_data", "sequence_num": 0, "timestamp": "2023-01-01T00:00:00Z", "events": [
        {"type": "update", "product_id": "X-USD", "updates": [
            {"side": "sideways", "price_level": "1", "new_quantity": "1", "event_time": "x"}]}]}, "bad_levels"),
    ({"channel": "l2_data", "sequence_num": 0, "timestamp": "2023-01-01T00:00:00Z", "events": [
        {"type": "update", "product_id": "X-USD", "updates": [
            {"side": "bid", "price_level": "-1", "new_quantity": "1", "event_time": "x"}]}]}, "bad_levels"),
    ({"channel": "market_trades", "sequence_num": 0, "timestamp": "2023-01-01T00:00:00Z", "events": [
        {"type": "update", "trades": [{"trade_id": "1", "product_id": "X-USD", "price": "0", "size": "1",
                                       "side": "BUY", "time": "2023-01-01T00:00:00Z"}]}]}, "non_positive_trade"),
    ({"channel": "l2_data", "sequence_num": 0, "timestamp": "not-a-time", "events": []}, "bad_value"),
])
def test_invalid_coinbase_messages(raw, reason):
    with pytest.raises(DecodeError) as ei:
        CoinbaseDecoder(0, 0).decode(raw if isinstance(raw, bytes) else orjson.dumps(raw), 1, 1)
    assert ei.value.reason == reason


def test_rfc3339():
    assert rfc3339_to_ns("1970-01-01T00:00:01Z") == 1_000_000_000
    assert rfc3339_to_ns("1970-01-01T00:00:01.5Z") == 1_500_000_000
    assert rfc3339_to_ns("1970-01-01T00:00:01.123456789Z") == 1_123_456_789
    assert rfc3339_to_ns("1970-01-01T01:00:00+01:00") == 0
    assert rfc3339_to_ns("2023-02-09T20:32:50.714964855Z") == 1675974770714964855
    with pytest.raises(ValueError):
        rfc3339_to_ns("yesterday")


PRODUCTS = {"products": [
    {"product_id": "BTC-USD", "base_currency_id": "BTC", "quote_currency_id": "USD", "base_increment": "0.00000001",
     "quote_increment": "0.01", "price_increment": "0.01", "base_min_size": "0.00000001", "base_max_size": "3400",
     "quote_min_size": "1", "status": "online", "trading_disabled": False, "is_disabled": False,
     "cancel_only": False, "limit_only": False, "post_only": False, "auction_mode": False, "view_only": False,
     "product_type": "SPOT", "alias": "", "approximate_quote_24h_volume": "500000000"},
    {"product_id": "BTC-USDC", "base_currency_id": "BTC", "quote_currency_id": "USDC", "base_increment": "0.00000001",
     "quote_increment": "0.01", "base_min_size": "0.00000001", "quote_min_size": "1", "status": "online",
     "product_type": "SPOT", "alias": "BTC-USD"},
    {"product_id": "RNDR-USD", "base_currency_id": "RNDR", "quote_currency_id": "USD", "base_increment": "0.01",
     "quote_increment": "0.001", "base_min_size": "0.01", "quote_min_size": "1", "status": "online",
     "limit_only": True, "product_type": "SPOT"},
    {"product_id": "OLD-USD", "base_currency_id": "OLD", "quote_currency_id": "USD", "base_increment": "1",
     "quote_increment": "0.0001", "status": "delisted", "trading_disabled": True, "product_type": "SPOT"},
    {"product_id": "BIT-28JUN24-CDE", "base_currency_id": "BTC", "quote_currency_id": "USD", "base_increment": "1",
     "quote_increment": "5", "status": "online", "product_type": "FUTURE"},
    {"product_id": "BAD-USD", "base_currency_id": "BAD", "quote_currency_id": "USD", "base_increment": "x",
     "quote_increment": "0.01", "status": "online", "product_type": "SPOT"},
]}


def test_products_parsing_aliases_and_restrictions():
    aliases = {"RNDR": "RENDER"}
    specs = {s.symbol: s for s in parse_products(PRODUCTS, fees=FeeSchedule(60, 120),
                                                  asset=lambda a: aliases.get(a, a))}
    assert "BAD-USD" not in specs  # malformed metadata skipped, never guessed
    btc = specs["BTC-USD"]
    assert btc.tradable and btc.tick_size == parse_e8("0.01") and btc.step_size == 1
    assert btc.min_notional == parse_e8("1") and btc.max_qty == parse_e8("3400")
    assert btc.key == "COINBASE:BTC-USD" and btc.depth_available
    assert specs["BTC-USDC"].alias_of == "BTC-USD" and not specs["BTC-USDC"].depth_available
    r = specs["RNDR-USD"]
    assert r.base == "RENDER" and r.native_base == "RNDR" and r.order_types == ("LIMIT",)
    assert "limit_only" in r.restrictions and r.tradable
    assert not specs["OLD-USD"].tradable and "trading_disabled" in specs["OLD-USD"].restrictions
    assert specs["BIT-28JUN24-CDE"].market_type is MarketType.FUTURE


def test_adapter_selection_and_subscription_plans():
    cfg = CoinbaseConfig(required_products=["BTC-USD"], max_symbols_per_connection=2, max_products=10)
    ad = CoinbaseAdapter(cfg)
    specs = parse_products(PRODUCTS, fees=FeeSchedule(60, 120))
    ad.wanted_bases = {"BTC"}
    chosen = ad.select(specs)
    assert [s.symbol for s in chosen] == ["BTC-USD"]  # aliases, futures, non-overlapping bases excluded
    plans = ad.plan_connections(chosen, first_conn_id=7)
    assert plans[0].conn_id == 7
    msgs = [json.loads(m) for m in plans[0].subscribe_messages]
    assert [m["channel"] for m in msgs] == ["heartbeats", "level2", "market_trades"]
    assert all(m["type"] == "subscribe" and m["product_ids"] == ["BTC-USD"] and "jwt" not in m for m in msgs)


def test_registry_mapping_and_conversions():
    from marketintel.exchanges.base import InstrumentSpec, Venue
    reg = InstrumentRegistry(RegistryConfig(verified_assets=["BTC", "ETH", "USD", "USDT", "USDC"]))
    mk = InstrumentSpec
    specs = reg.add([
        mk(Venue.BINANCE, "BTCUSDT", "BTC", "USDT", "BTC", "USDT"),
        mk(Venue.BINANCE, "ETHUSDT", "ETH", "USDT", "ETH", "USDT"),
        mk(Venue.BINANCE, "XYZUSDT", "XYZ", "USDT", "XYZ", "USDT"),
        mk(Venue.COINBASE, "BTC-USDT", "BTC", "USDT", "BTC", "USDT"),
        mk(Venue.COINBASE, "ETH-USD", "ETH", "USD", "ETH", "USD"),
        mk(Venue.COINBASE, "XYZ-USD", "XYZ", "USD", "XYZ", "USD"),
        mk(Venue.COINBASE, "USDT-USD", "USDT", "USD", "USDT", "USD"),
        mk(Venue.COINBASE, "BTC-USDC", "BTC", "USDC", "BTC", "USDC", alias_of="BTC-USD"),
    ])
    assert {s.symbol: s.mapping for s in specs}["XYZUSDT"] is MappingConfidence.INFERRED
    pairs = {(p.a.key, p.b.key): p for p in reg.cross_venue_pairs()}
    assert ("BINANCE:BTCUSDT", "COINBASE:BTC-USDT") in pairs and pairs[("BINANCE:BTCUSDT", "COINBASE:BTC-USDT")].conv is None
    eth = pairs[("BINANCE:ETHUSDT", "COINBASE:ETH-USD")]
    # Convert USD (Coinbase quote) into USDT (Binance quote): buy USDT with USD -> pay the ask.
    assert eth.conv is not None and eth.conv.spec.key == "COINBASE:USDT-USD" and not eth.conv.sell_base
    assert not any("XYZ" in k[0] for k in pairs)  # inferred ticker match is never compared
    assert not any("USDC" in k[1] for k in pairs)  # aliases excluded
    assert reg.conversion("USDT", "USD").sell_base and reg.conversion("BTC", "USD") is None
    reg.cfg.allow_inferred_mapping = True
    assert any("XYZ" in p.a.key for p in reg.cross_venue_pairs())
