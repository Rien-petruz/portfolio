import json
import os

import pytest

from marketintel.exchanges.base import FeeSchedule
from marketintel.exchanges.binance.symbols import parse_exchange_info, select_universe
from marketintel.numeric import parse_e8

from ..conftest import FIXTURES


@pytest.fixture
def infos():
    with open(os.path.join(FIXTURES, "exchange_info.json")) as fh:
        specs = parse_exchange_info(json.load(fh), fees=FeeSchedule(10, 10), asset=lambda a: {"RNDR": "RENDER"}.get(a, a))
        return {sp.symbol: sp for sp in specs}


def test_parse_filters(infos):
    btc = infos["BTCUSDT"]
    assert btc.tick_size == parse_e8("0.01")
    assert btc.step_size == parse_e8("0.00001")
    assert btc.min_qty == parse_e8("0.00001")
    assert btc.key == "BINANCE:BTCUSDT" and btc.canonical == "BTC/USDT:SPOT"
    assert btc.tradable and btc.fees.taker_bps == 10
    assert btc.min_notional == parse_e8("5")
    assert btc.filters_known
    # Legacy MIN_NOTIONAL filter is understood too.
    assert infos["ETHBTC"].min_notional == parse_e8("0.0001")
    # Unparseable metadata is skipped, not guessed.
    assert "BADUSDT" not in infos


def test_validate_order(infos):
    btc = infos["BTCUSDT"]
    ok_px, ok_qty = parse_e8("60000.01"), parse_e8("0.001")
    assert btc.validate_order(ok_px, ok_qty) == []
    assert "price_not_on_tick" in btc.validate_order(parse_e8("60000.015"), ok_qty)
    assert "qty_not_on_step" in btc.validate_order(ok_px, parse_e8("0.000015"))
    assert "qty_below_min" in btc.validate_order(ok_px, parse_e8("0.000001"))
    # 0.00008 BTC * 60000 = 4.8 USDT < 5 minNotional
    assert btc.validate_order(ok_px, parse_e8("0.00008")) == ["notional_below_min"]
    # exactly at the minimum notional passes (exact integer comparison)
    assert btc.validate_order(parse_e8("50000"), parse_e8("0.0001")) == []
    assert "price_non_positive" in btc.validate_order(0, ok_qty)
    assert "qty_above_max" in btc.validate_order(ok_px, parse_e8("9001"))
    # Restricted / non-trading symbols are parsed but not tradable.
    assert not infos["OLDUSDT"].tradable and "status_break" in infos["OLDUSDT"].restrictions
    assert not infos["MARGUSDT"].tradable and "spot_trading_not_allowed" in infos["MARGUSDT"].restrictions


def test_rounding(infos):
    btc = infos["BTCUSDT"]
    assert btc.round_qty(parse_e8("0.123456789"[:10])) == parse_e8("0.12345")
    assert btc.round_price(parse_e8("100.019")) == parse_e8("100.01")
    assert btc.round_price(parse_e8("100.011"), up=True) == parse_e8("100.02")


def test_unknown_filters_refuse_validation(infos):
    assert infos["OLDUSDT"].validate_order(1, 1) == ["filters_unknown"]


def test_select_universe(infos):
    vol = {"DOGEUSDT": 1e9, "ETHUSDT": 5e8, "BTCUSDT": 1.0}
    out = select_universe(infos, vol, quote_assets=["USDT"], required=["BTCUSDT", "ETHBTC", "NOPEUSDT"],
                          exclude=[], min_symbols=3, max_symbols=10)
    # required first (in order, unknown skipped), then by volume; non-trading and
    # non-spot symbols never selected.
    assert out == ["BTCUSDT", "ETHBTC", "DOGEUSDT", "ETHUSDT"]
    out = select_universe(infos, vol, quote_assets=["USDT"], required=["BTCUSDT"], exclude=["DOGEUSDT"],
                          min_symbols=1, max_symbols=2)
    assert out == ["BTCUSDT", "ETHUSDT"]
    with pytest.raises(ValueError):
        select_universe(infos, vol, quote_assets=["USDT"], required=[], exclude=[], min_symbols=50, max_symbols=60)
