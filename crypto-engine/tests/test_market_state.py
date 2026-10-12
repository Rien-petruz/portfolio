import pytest

from marketintel.clock import NS_PER_MS
from marketintel.exchange.binance.ws import ShardHealth
from marketintel.ingestion.events import BookTicker, Trade
from marketintel.numeric import parse_e8
from marketintel.state.market_state import MarketState, QuoteStatus

T0 = 1_000_000 * NS_PER_MS


def bt(u, bid="100", ask="100.1", t=T0, sym="BTCUSDT"):
    return BookTicker(sym, u, parse_e8(bid), parse_e8("1"), parse_e8(ask), parse_e8("2"), t, t, 0)


def trade(tid, t=T0, sym="BTCUSDT"):
    return Trade(sym, tid, parse_e8("100"), parse_e8("0.5"), 1, 1, False, t, t, 0)


@pytest.fixture
def ms():
    m = MarketState(quiet_after_ms=2000, stale_after_ms=10000, conn_stall_ms=5000)
    m.add_symbol("BTCUSDT")
    sh = ShardHealth(0, ["BTCUSDT"], 2)
    sh.connected = True
    sh.last_msg_mono_ns = T0
    m.bind_shard(["BTCUSDT"], sh)
    return m, sh


def test_lifecycle_statuses(ms):
    m, sh = ms
    st = m.symbols["BTCUSDT"]
    assert m.status(st, T0) is QuoteStatus.UNINITIALIZED
    assert m.apply_book_ticker(bt(10)) is st
    assert m.status(st, T0) is QuoteStatus.LIVE
    assert st.spread_bps() == pytest.approx(9.995, rel=1e-3)
    assert st.touch_imbalance() == pytest.approx((1 - 2) / 3)
    # Book unchanged but connection healthy -> QUIET, then STALE.
    sh.last_msg_mono_ns = T0 + 3000 * NS_PER_MS
    assert m.status(st, T0 + 3000 * NS_PER_MS) is QuoteStatus.QUIET
    sh.last_msg_mono_ns = T0 + 11000 * NS_PER_MS
    assert m.status(st, T0 + 11000 * NS_PER_MS) is QuoteStatus.STALE
    # Connection silent for longer than the stall threshold -> STALE even if
    # the quote itself is recent.
    m.apply_book_ticker(bt(11, t=T0 + 11000 * NS_PER_MS))
    assert m.status(st, T0 + 11000 * NS_PER_MS) is QuoteStatus.LIVE
    assert m.status(st, T0 + 16001 * NS_PER_MS) is QuoteStatus.STALE


def test_disconnect_invalidates_immediately(ms):
    m, sh = ms
    st = m.symbols["BTCUSDT"]
    m.on_shard_up(["BTCUSDT"])  # initial connect is not a reconnect
    assert st.n_reconnects == 0
    m.apply_book_ticker(bt(10))
    sh.connected = False
    m.on_shard_down(["BTCUSDT"])
    assert m.status(st, T0) is QuoteStatus.DISCONNECTED
    assert not m.is_usable("BTCUSDT", T0, allow_quiet=True)
    # Reconnected but no fresh data yet: old quote is not usable.
    sh.connected = True
    m.on_shard_up(["BTCUSDT"])
    assert m.status(st, T0) is QuoteStatus.UNINITIALIZED
    # Update ids restart after an outage: any fresh update is accepted.
    assert m.apply_book_ticker(bt(5)) is st
    assert m.status(st, T0) is QuoteStatus.LIVE
    assert st.n_reconnects == 1


def test_out_of_order_and_duplicate_book_updates_dropped(ms):
    m, _ = ms
    st = m.symbols["BTCUSDT"]
    m.apply_book_ticker(bt(10, bid="100"))
    assert m.apply_book_ticker(bt(10, bid="99")) is None
    assert m.apply_book_ticker(bt(9, bid="98")) is None
    assert st.bid_px == parse_e8("100") and st.n_book_out_of_order == 2


def test_crossed_and_one_sided(ms):
    m, _ = ms
    st = m.symbols["BTCUSDT"]
    m.apply_book_ticker(bt(10, bid="101", ask="100"))
    assert m.status(st, T0) is QuoteStatus.CROSSED and st.n_crossed == 1
    m.apply_book_ticker(bt(11, bid="100", ask="100"))  # locked is also invalid
    assert m.status(st, T0) is QuoteStatus.CROSSED
    m.apply_book_ticker(bt(12, bid="0", ask="100"))
    assert m.status(st, T0) is QuoteStatus.ONE_SIDED
    assert not m.is_usable("BTCUSDT", T0)


def test_trade_dups_and_gaps(ms):
    m, _ = ms
    st = m.symbols["BTCUSDT"]
    assert m.apply_trade(trade(100)) is st
    assert m.apply_trade(trade(100)) is None
    assert m.apply_trade(trade(99)) is None
    assert m.apply_trade(trade(101)) is st
    assert m.apply_trade(trade(105)) is st
    assert (st.n_trade_dups, st.n_trade_gaps, st.missed_trades) == (2, 1, 3)


def test_unknown_symbol_counted(ms):
    m, _ = ms
    assert m.apply_book_ticker(bt(1, sym="NOPE")) is None
    assert m.apply_trade(trade(1, sym="NOPE")) is None
    assert m.unknown_symbol_events == 2


def test_max_age_and_unsubscribed(ms):
    m, _ = ms
    m.apply_book_ticker(bt(10))
    assert m.is_usable("BTCUSDT", T0 + 500 * NS_PER_MS)
    assert not m.is_usable("BTCUSDT", T0 + 500 * NS_PER_MS, max_age_ms=100)
    m.add_symbol("ETHUSDT")
    assert m.status(m.symbols["ETHUSDT"], T0) is QuoteStatus.UNSUBSCRIBED
    assert not m.is_usable("XRPUSDT", T0)


def test_late_delivery_marks_stale(ms):
    m, sh = ms
    st = m.symbols["BTCUSDT"]
    m.apply_book_ticker(bt(10))
    sh.delivery_lag_ns = 3000 * NS_PER_MS  # above the 2000 ms default
    sh.delivery_lag_at_ns = T0
    assert m.status(st, T0) is QuoteStatus.STALE
    # An old lag sample (no recent trades/depth) no longer applies.
    sh.last_msg_mono_ns = T0 + 6000 * NS_PER_MS
    m.apply_book_ticker(bt(11, t=T0 + 6000 * NS_PER_MS))
    assert m.status(st, T0 + 6000 * NS_PER_MS) is QuoteStatus.LIVE
