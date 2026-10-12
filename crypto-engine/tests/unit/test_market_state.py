import pytest

from marketintel.clock import NS_PER_MS
from marketintel.exchanges.connection import ShardHealth
from marketintel.market_data.events import Quote, Trade
from marketintel.market_data.quality import QuoteStatus
from marketintel.market_data.state import MarketState
from marketintel.numeric import parse_e8

T0 = 1_000_000 * NS_PER_MS


K = "BINANCE:BTCUSDT"


def bt(u, bid="100", ask="100.1", t=T0, key=K):
    return Quote(key, u, parse_e8(bid), parse_e8("1"), parse_e8(ask), parse_e8("2"), t, t, 0)


def trade(tid, t=T0, key=K):
    return Trade(key, tid, parse_e8("100"), parse_e8("0.5"), 1, 1, 1, t, t, 0)


@pytest.fixture
def ms():
    m = MarketState(max_delivery_lag_ms=2000)
    m.add(K, quiet_ms=2000, stale_ms=10000, stall_ms=5000)
    sh = ShardHealth(0, "BINANCE", ["BTCUSDT"], 2)
    sh.connected = True
    sh.last_msg_mono_ns = T0
    m.bind_shard([K], sh)
    return m, sh


def test_lifecycle_statuses(ms):
    m, sh = ms
    st = m.instruments[K]
    assert m.status(st, T0) is QuoteStatus.UNINITIALIZED
    assert m.apply_quote(bt(10)) is st
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
    m.apply_quote(bt(11, t=T0 + 11000 * NS_PER_MS))
    assert m.status(st, T0 + 11000 * NS_PER_MS) is QuoteStatus.LIVE
    assert m.status(st, T0 + 16001 * NS_PER_MS) is QuoteStatus.STALE


def test_disconnect_invalidates_immediately(ms):
    m, sh = ms
    st = m.instruments[K]
    m.on_shard_up([K])  # initial connect is not a reconnect
    assert st.n_reconnects == 0
    m.apply_quote(bt(10))
    sh.connected = False
    m.on_shard_down([K])
    assert m.status(st, T0) is QuoteStatus.DISCONNECTED
    assert not m.is_usable(K, T0, allow_quiet=True)
    # Reconnected but no fresh data yet: old quote is not usable.
    sh.connected = True
    m.on_shard_up([K])
    assert m.status(st, T0) is QuoteStatus.UNINITIALIZED
    # Update ids restart after an outage: any fresh update is accepted.
    assert m.apply_quote(bt(5)) is st
    assert m.status(st, T0) is QuoteStatus.LIVE
    assert st.n_reconnects == 1


def test_out_of_order_and_duplicate_book_updates_dropped(ms):
    m, _ = ms
    st = m.instruments[K]
    m.apply_quote(bt(10, bid="100"))
    assert m.apply_quote(bt(10, bid="99")) is None
    assert m.apply_quote(bt(9, bid="98")) is None
    assert st.bid_px == parse_e8("100") and st.n_book_out_of_order == 2


def test_crossed_and_one_sided(ms):
    m, _ = ms
    st = m.instruments[K]
    m.apply_quote(bt(10, bid="101", ask="100"))
    assert m.status(st, T0) is QuoteStatus.CROSSED and st.n_crossed == 1
    m.apply_quote(bt(11, bid="100", ask="100"))  # locked is also invalid
    assert m.status(st, T0) is QuoteStatus.CROSSED
    m.apply_quote(bt(12, bid="0", ask="100"))
    assert m.status(st, T0) is QuoteStatus.ONE_SIDED
    assert not m.is_usable(K, T0)


def test_trade_dups_and_gaps(ms):
    m, _ = ms
    st = m.instruments[K]
    assert m.apply_trade(trade(100)) is st
    assert m.apply_trade(trade(100)) is None
    assert m.apply_trade(trade(99)) is None
    assert m.apply_trade(trade(101)) is st
    assert m.apply_trade(trade(105)) is st
    assert (st.n_trade_dups, st.n_trade_gaps, st.missed_trades) == (2, 1, 3)


def test_unknown_symbol_counted(ms):
    m, _ = ms
    assert m.apply_quote(bt(1, key="BINANCE:NOPE")) is None
    assert m.apply_trade(trade(1, key="BINANCE:NOPE")) is None
    assert m.unknown_events == 2


def test_max_age_and_unsubscribed(ms):
    m, _ = ms
    m.apply_quote(bt(10))
    assert m.is_usable(K, T0 + 500 * NS_PER_MS)
    assert not m.is_usable(K, T0 + 500 * NS_PER_MS, max_age_ms=100)
    m.add("BINANCE:ETHUSDT")
    assert m.status(m.instruments["BINANCE:ETHUSDT"], T0) is QuoteStatus.UNSUBSCRIBED
    assert not m.is_usable("BINANCE:XRPUSDT", T0)


def test_late_delivery_marks_stale(ms):
    m, sh = ms
    st = m.instruments[K]
    m.apply_quote(bt(10))
    sh.delivery_lag_ns = 3000 * NS_PER_MS  # above the 2000 ms default
    sh.delivery_lag_at_ns = T0
    assert m.status(st, T0) is QuoteStatus.STALE
    # An old lag sample (no recent trades/depth) no longer applies.
    sh.last_msg_mono_ns = T0 + 6000 * NS_PER_MS
    m.apply_quote(bt(11, t=T0 + 6000 * NS_PER_MS))
    assert m.status(st, T0 + 6000 * NS_PER_MS) is QuoteStatus.LIVE


def test_non_contiguous_trade_ids_do_not_count_gaps():
    m = MarketState()
    k = "COINBASE:BTC-USD"
    m.add(k, trade_ids_contiguous=False)
    st = m.instruments[k]
    assert m.apply_trade(trade(10, key=k)) is st
    assert m.apply_trade(trade(50, key=k)) is st
    assert st.n_trade_gaps == 0 and st.missed_trades == 0
    assert m.apply_trade(trade(50, key=k)) is None  # numeric ids still de-duplicated
    # Non-numeric ids (-1) are accepted without ordering checks.
    assert m.apply_trade(trade(-1, key=k)) is st
