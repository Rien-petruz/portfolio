import asyncio

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from marketintel.market_data.events import BookDelta, BookSnapshot, DepthDiff
from marketintel.market_data.order_book import BookSync, DiffResult, LocalOrderBook, OrderBookManager, SnapshotResult


def diff(U, u, bids=(), asks=(), sym="BINANCE:BTCUSDT"):
    return DepthDiff(sym, U, u, 0, list(bids), list(asks), 0, 0, 0)


def test_documented_sync_procedure():
    b = LocalOrderBook("BTCUSDT")
    assert b.on_diff(diff(101, 105, bids=[(100, 1)])) is DiffResult.NEED_SNAPSHOT
    assert b.on_diff(diff(106, 110, asks=[(103, 4)])) is DiffResult.BUFFERED
    # Snapshot strictly older than the first buffered U: retry.
    assert b.apply_snapshot(99, [(99, 1)], [(102, 1)]) is SnapshotResult.RETRY
    assert b.sync is BookSync.BUFFERING
    # Snapshot at 107: event (101..105) is discarded, (106..110) bridges it.
    assert b.apply_snapshot(107, [(99, 5), (98, 1)], [(102, 2)]) is SnapshotResult.SYNCED
    assert b.last_update_id == 110
    assert b.best_bid() == (99, 5) and b.best_ask() == (102, 2)
    assert dict(b.asks) == {102: 2, 103: 4}
    # Old event ignored, contiguous applied, zero qty removes level.
    assert b.on_diff(diff(108, 110, bids=[(1, 1)])) is DiffResult.IGNORED
    assert b.on_diff(diff(111, 111, bids=[(99, 0)])) is DiffResult.APPLIED
    assert b.best_bid() == (98, 1)
    # Gap: U > last + 1 -> book discarded.
    assert b.on_diff(diff(113, 115)) is DiffResult.GAP
    assert b.sync is BookSync.INIT and not b.bids and b.gaps == 1


def test_snapshot_that_cannot_bridge_is_a_gap():
    b = LocalOrderBook("X")
    b.on_diff(diff(101, 105))
    b.on_diff(diff(110, 112))  # 106..109 missing from our buffer
    assert b.apply_snapshot(106, [], []) is SnapshotResult.GAP
    assert b.sync is BookSync.INIT


def test_retry_when_nothing_buffered():
    b = LocalOrderBook("X")
    assert b.apply_snapshot(10, [(1, 1)], [(2, 1)]) is SnapshotResult.RETRY


def test_crossed_book_is_treated_as_corrupt():
    b = LocalOrderBook("X")
    b.on_diff(diff(1, 1))
    b.apply_snapshot(1, [(100, 1)], [(101, 1)])
    assert b.on_diff(diff(2, 2, bids=[(102, 1)])) is DiffResult.GAP
    assert b.crossed_resets == 1 and not b.is_synced


def test_sweep_and_top_levels():
    b = LocalOrderBook("X")
    b.on_diff(diff(1, 1))
    b.apply_snapshot(1, [(100, 5), (99, 5)], [(101, 3), (102, 3), (105, 10)])
    filled, notional, worst = b.sweep("buy", 4)
    assert (filled, notional, worst) == (4, 101 * 3 + 102 * 1, 102)
    filled, notional, worst = b.sweep("sell", 100)  # insufficient liquidity
    assert filled == 10 and notional == 100 * 5 + 99 * 5 and worst == 99
    bids, asks = b.top(2)
    assert bids == [(100, 5), (99, 5)] and asks == [(101, 3), (102, 3)]
    assert b.depth_imbalance(2) == pytest.approx((10 - 6) / 16)
    unsynced = LocalOrderBook("Y")
    assert unsynced.sweep("buy", 1) is None


@settings(max_examples=60, deadline=None)
@given(st.lists(st.tuples(st.booleans(), st.integers(1, 30), st.integers(0, 5)), min_size=1, max_size=200))
def test_incremental_updates_match_reference_model(ops):
    """Applying diffs one at a time must equal a plain dict model."""
    b = LocalOrderBook("X")
    b.on_diff(diff(1, 1))
    b.apply_snapshot(1, [], [])
    ref_b: dict[int, int] = {}
    ref_a: dict[int, int] = {}
    uid = 1
    for is_bid, px, qty in ops:
        uid += 1
        # keep sides apart so the model never crosses: bids < 100 <= asks
        p = px if is_bid else 100 + px
        side = ref_b if is_bid else ref_a
        if qty:
            side[p] = qty
        else:
            side.pop(p, None)
        ev = diff(uid, uid, bids=[(p, qty)] if is_bid else [], asks=[] if is_bid else [(p, qty)])
        assert b.on_diff(ev) is DiffResult.APPLIED
    assert dict(b.bids) == ref_b and dict(b.asks) == ref_a


async def test_manager_fetches_snapshot_off_hot_path_and_resyncs():
    calls = []
    snapshots = [
        {"lastUpdateId": 5, "bids": [["1.0", "1"]], "asks": [["2.0", "1"]]},  # too old -> retry
        {"lastUpdateId": 12, "bids": [["1.0", "1"]], "asks": [["2.0", "1"]]},
        {"lastUpdateId": 30, "bids": [["1.0", "3"]], "asks": [["2.0", "3"]]},
    ]

    async def fetch(sym, limit):
        calls.append((sym, limit))
        return snapshots[len(calls) - 1]

    m = OrderBookManager(fetch, limit=100, retry_delay_s=0.01)
    m.add("BINANCE:BTCUSDT")
    assert m.on_diff(diff(10, 13)) is DiffResult.NEED_SNAPSHOT
    for _ in range(50):
        await asyncio.sleep(0.01)
        if m.books["BINANCE:BTCUSDT"].is_synced:
            break
    book = m.books["BINANCE:BTCUSDT"]
    assert book.is_synced and book.last_update_id == 13 and calls == [("BINANCE:BTCUSDT", 100)] * 2
    # A gap triggers an automatic resync from a new snapshot.
    assert m.on_diff(diff(20, 31)) is DiffResult.GAP
    for _ in range(50):
        await asyncio.sleep(0.01)
        if book.is_synced:
            break
    assert book.is_synced and book.last_update_id == 31 and book.resyncs == 1
    m.reset_keys(["BINANCE:BTCUSDT"])
    assert not book.is_synced
    assert m.on_diff(diff(1, 1, sym="OTHER")) is None
    await m.close()


def test_stream_snapshot_ownership_and_crossed():
    b = LocalOrderBook("COINBASE:BTC-USD")
    assert b.apply_levels([(1, 1)], [], src=1) is DiffResult.IGNORED  # no snapshot yet
    assert b.load_snapshot([(100, 1), (99, 2)], [(101, 1)], src=1) is DiffResult.APPLIED
    v = b.version
    assert b.apply_levels([(100, 0)], [(102, 5)], src=1) is DiffResult.APPLIED
    assert b.best_bid() == (99, 2) and dict(b.asks) == {101: 1, 102: 5} and b.version == v + 1
    # A delta from another socket (rotation overlap) is ignored, not interleaved.
    assert b.apply_levels([(100, 9)], [], src=2) is DiffResult.IGNORED and b.foreign_deltas == 1
    # The new socket's snapshot takes ownership.
    assert b.load_snapshot([(98, 1)], [(103, 1)], src=2) is DiffResult.APPLIED and b.owner_src == 2
    assert b.apply_levels([(97, 1)], [], src=1) is DiffResult.IGNORED
    # Crossed after an update -> corrupt -> reset.
    assert b.apply_levels([(104, 1)], [], src=2) is DiffResult.GAP and not b.is_synced
    assert b.load_snapshot([(105, 1)], [(104, 1)], src=3) is DiffResult.GAP


def test_manager_stream_books():
    m = OrderBookManager(None)
    m.add("COINBASE:ETH-USD")
    snap = BookSnapshot("COINBASE:ETH-USD", 1, 0, [(10, 1)], [(11, 1)], 0, 0, 0, 7)
    assert m.on_snapshot(snap) is DiffResult.APPLIED
    assert m.on_delta(BookDelta("COINBASE:ETH-USD", 2, 0, [(10, 3)], [], 0, 0, 0, 7)) is DiffResult.APPLIED
    assert m.books["COINBASE:ETH-USD"].best_bid() == (10, 3)
    assert m.on_delta(BookDelta("COINBASE:NOPE", 2, 0, [], [], 0, 0, 0, 7)) is None
