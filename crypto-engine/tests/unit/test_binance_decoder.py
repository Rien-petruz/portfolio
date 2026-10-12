import os

import orjson
import pytest

from marketintel.exchanges.binance.decoder import BinanceDecoder
from marketintel.exchanges.errors import DecodeError
from marketintel.market_data.events import BUY, SELL, ConnectionNotice, DepthDiff, Quote, Trade
from marketintel.numeric import parse_e8

from ..conftest import FIXTURES


def dec(raw):
    return BinanceDecoder(3).decode(raw if isinstance(raw, bytes) else orjson.dumps(raw), 111, 222)


def test_recorded_fixture_frames():
    d = BinanceDecoder(0)
    with open(os.path.join(FIXTURES, "binance_frames.jsonl"), "rb") as fh:
        out = [d.decode(line.strip(), 1, 2) for line in fh if line.strip()]
    bt, bt_raw, tr, dd, sd, ctl = out
    assert isinstance(bt, Quote) and bt.key == "BINANCE:BNBUSDT" and bt.update_id == 400900217
    assert bt.bid_px == parse_e8("25.3519") and bt.ask_qty == parse_e8("40.66")
    assert bt.event_time_ns == 0  # bookTicker has no exchange time; never fabricated
    assert isinstance(bt_raw, Quote) and bt_raw.update_id == 400900218
    assert isinstance(tr, Trade) and tr.trade_id == 12345 and tr.px == parse_e8("0.001")
    assert tr.aggressor == SELL  # buyer is maker -> seller aggressed
    assert tr.event_time_ns == 1672515782136 * 1_000_000
    assert isinstance(dd, DepthDiff) and (dd.first_update_id, dd.final_update_id) == (157, 160)
    assert dd.bids == [(parse_e8("0.0024"), parse_e8("10"))]
    assert isinstance(sd, ConnectionNotice) and sd.kind == "server_shutdown"
    assert ctl is None and d.control_messages == 1


def test_timestamps_conn_and_buy_aggressor():
    ev = dec({"u": 1, "s": "BTCUSDT", "b": "1", "B": "1", "a": "2", "A": "1"})
    assert (ev.recv_mono_ns, ev.recv_wall_ns, ev.conn_id) == (111, 222, 3)
    t = dec({"e": "trade", "E": 5, "s": "X", "t": 1, "p": "1", "q": "1", "T": 4, "m": False})
    assert t.aggressor == BUY and t.trade_time_ns == 4_000_000


@pytest.mark.parametrize("raw,reason", [
    (b"not json", "invalid_json"),
    (b"[1,2]", "not_an_object"),
    ({"stream": "x", "data": [1]}, "not_an_object"),
    ({"stream": "btcusdt@trade", "data": {"e": "trade", "s": "BTCUSDT"}}, "missing_field"),
    ({"u": 1, "s": "BTCUSDT", "b": "abc", "B": "1", "a": "2", "A": "1"}, "bad_value"),
    ({"u": 1, "s": "BTCUSDT", "b": "-1", "B": "1", "a": "2", "A": "1"}, "negative_value"),
    ({"u": 1, "s": 5, "b": "1", "B": "1", "a": "2", "A": "1"}, "bad_symbol"),
    ({"e": "trade", "E": 1, "s": "X", "t": 1, "p": "0", "q": "1", "T": 1, "m": True}, "non_positive_trade"),
    ({"e": "depthUpdate", "E": 1, "s": "X", "U": 10, "u": 5, "b": [], "a": []}, "bad_update_range"),
    ({"e": "depthUpdate", "E": 1, "s": "X", "U": 1, "u": 5, "b": [["0", "1"]], "a": []}, "bad_levels"),
    ({"e": "depthUpdate", "E": 1, "s": "X", "U": 1, "u": 5, "b": "x", "a": []}, "bad_levels"),
    ({"e": "kline", "E": 1, "s": "X"}, "unknown_event"),
    ({"result": None, "error": {"code": 2, "msg": "Invalid request"}, "id": 7}, "control_error"),
    ({"u": 1, "s": "BTCUSDT", "b": "0.0000000001", "B": "1", "a": "2", "A": "1"}, "bad_value"),
])
def test_invalid_messages_rejected(raw, reason):
    with pytest.raises(DecodeError) as ei:
        dec(raw)
    assert ei.value.reason == reason


def test_zero_qty_depth_level_and_empty_side():
    ev = dec({"e": "depthUpdate", "E": 1, "s": "X", "U": 1, "u": 1, "b": [["1.0", "0"]], "a": []})
    assert ev.bids == [(parse_e8("1"), 0)]
    q = dec({"u": 3, "s": "X", "b": "0.00000000", "B": "0.00000000", "a": "2", "A": "1"})
    assert q.bid_px == 0
