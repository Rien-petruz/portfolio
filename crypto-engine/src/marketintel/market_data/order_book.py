"""Local L2 order books.

Two synchronisation models, chosen by the venue's capabilities:

* **diff + REST snapshot** (Binance ``@depth@100ms``): Binance's documented
  procedure - buffer diffs, fetch a snapshot, discard ``u <= lastUpdateId``,
  require the first event to bridge the snapshot, then require contiguous
  ``U``/``u``. Any gap discards the book and resyncs off the hot path.
* **stream snapshot + deltas** (Coinbase level2): the snapshot arrives on the
  WebSocket; deltas set absolute level quantities. Continuity is guaranteed by
  the connection's sequence numbers (checked in the decoder). A book is
  *owned* by the socket that delivered its snapshot, so during a
  make-before-break rotation deltas from the other socket are ignored instead
  of being interleaved.

A book is readable only when ``SYNCED``. A crossed book is treated as
corruption and rebuilt. ``version`` increases with every applied change and
is used as the derived quote's update id.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import Any

from sortedcontainers import SortedDict

from ..numeric import ONE, parse_e8
from .events import BookDelta, BookSnapshot, DepthDiff

log = logging.getLogger(__name__)


class BookSync(StrEnum):
    INIT = "INIT"              # nothing buffered yet
    BUFFERING = "BUFFERING"    # diffs buffered, waiting for a usable snapshot
    SYNCED = "SYNCED"


class DiffResult(StrEnum):
    BUFFERED = "BUFFERED"
    NEED_SNAPSHOT = "NEED_SNAPSHOT"  # first buffered event: fetch a snapshot
    APPLIED = "APPLIED"
    IGNORED = "IGNORED"              # u <= local update id
    GAP = "GAP"                      # missed events: book discarded


class SnapshotResult(StrEnum):
    SYNCED = "SYNCED"
    RETRY = "RETRY"  # snapshot older than buffered stream, or nothing buffered
    GAP = "GAP"      # buffer cannot bridge to the snapshot


class LocalOrderBook:
    def __init__(self, symbol: str, max_buffer: int = 2000) -> None:
        self.symbol = symbol
        self.bids: SortedDict = SortedDict()  # price_e8 -> qty_e8, best = last key
        self.asks: SortedDict = SortedDict()  # best = first key
        self.last_update_id = 0
        self.sync = BookSync.INIT
        self.buffer: deque[DepthDiff] = deque(maxlen=max_buffer)
        self.buffer_overflow = 0
        self.gaps = 0
        self.resyncs = 0
        self.crossed_resets = 0
        self.applied = 0
        self.last_event_time_ns = 0
        self.last_recv_mono_ns = 0
        self.version = 0
        self.owner_src: int | None = None
        self.foreign_deltas = 0

    # ------------------------------------------------------------ lifecycle
    def reset(self) -> None:
        self.bids.clear()
        self.asks.clear()
        self.last_update_id = 0
        self.sync = BookSync.INIT
        self.buffer.clear()
        self.owner_src = None

    # ---------------------------------------------- stream snapshot model
    def load_snapshot(self, bids: list[tuple[int, int]], asks: list[tuple[int, int]], src: int,
                      event_time_ns: int = 0, recv_mono_ns: int = 0) -> DiffResult:
        self.reset()
        self.bids = SortedDict({p: q for p, q in bids if q > 0})
        self.asks = SortedDict({p: q for p, q in asks if q > 0})
        self.owner_src = src
        self.sync = BookSync.SYNCED
        self.version += 1
        self.last_event_time_ns = event_time_ns
        self.last_recv_mono_ns = recv_mono_ns
        if self.bids and self.asks and self.bids.peekitem(-1)[0] >= self.asks.peekitem(0)[0]:
            self.crossed_resets += 1
            self.reset()
            return DiffResult.GAP
        return DiffResult.APPLIED

    def apply_levels(self, bids: list[tuple[int, int]], asks: list[tuple[int, int]], src: int,
                     event_time_ns: int = 0, recv_mono_ns: int = 0) -> DiffResult:
        if self.sync is not BookSync.SYNCED:
            return DiffResult.IGNORED
        if src != self.owner_src:
            self.foreign_deltas += 1
            return DiffResult.IGNORED
        b, a = self.bids, self.asks
        for p, q in bids:
            if q:
                b[p] = q
            else:
                b.pop(p, None)
        for p, q in asks:
            if q:
                a[p] = q
            else:
                a.pop(p, None)
        self.version += 1
        self.applied += 1
        self.last_event_time_ns = event_time_ns
        self.last_recv_mono_ns = recv_mono_ns
        if b and a and b.peekitem(-1)[0] >= a.peekitem(0)[0]:
            self.crossed_resets += 1
            self.reset()
            return DiffResult.GAP
        return DiffResult.APPLIED

    def on_diff(self, ev: DepthDiff) -> DiffResult:
        if self.sync is not BookSync.SYNCED:
            first = self.sync is BookSync.INIT
            if len(self.buffer) == self.buffer.maxlen:
                self.buffer_overflow += 1
            self.buffer.append(ev)
            self.sync = BookSync.BUFFERING
            return DiffResult.NEED_SNAPSHOT if first else DiffResult.BUFFERED
        return self._apply(ev)

    def apply_snapshot(self, last_update_id: int, bids: list[tuple[int, int]],
                       asks: list[tuple[int, int]]) -> SnapshotResult:
        if self.sync is BookSync.SYNCED:
            return SnapshotResult.SYNCED
        if not self.buffer or last_update_id < self.buffer[0].first_update_id:
            # Step 4: snapshot strictly older than the first buffered event.
            return SnapshotResult.RETRY
        while self.buffer and self.buffer[0].final_update_id <= last_update_id:
            self.buffer.popleft()
        if self.buffer and self.buffer[0].first_update_id > last_update_id + 1:
            self.gaps += 1
            self.reset()
            return SnapshotResult.GAP
        self.bids = SortedDict({p: q for p, q in bids if q > 0})
        self.asks = SortedDict({p: q for p, q in asks if q > 0})
        self.last_update_id = last_update_id
        self.sync = BookSync.SYNCED
        self.version += 1
        pending = list(self.buffer)
        self.buffer.clear()
        for ev in pending:
            if self._apply(ev) is DiffResult.GAP:
                return SnapshotResult.GAP
        return SnapshotResult.SYNCED

    # --------------------------------------------------------------- update
    def _apply(self, ev: DepthDiff) -> DiffResult:
        if ev.final_update_id <= self.last_update_id:
            return DiffResult.IGNORED
        if ev.first_update_id > self.last_update_id + 1:
            self.gaps += 1
            self.reset()
            return DiffResult.GAP
        bids, asks = self.bids, self.asks
        for p, q in ev.bids:
            if q:
                bids[p] = q
            else:
                bids.pop(p, None)
        for p, q in ev.asks:
            if q:
                asks[p] = q
            else:
                asks.pop(p, None)
        self.last_update_id = ev.final_update_id
        self.last_event_time_ns = ev.event_time_ns
        self.last_recv_mono_ns = ev.recv_mono_ns
        self.applied += 1
        self.version += 1
        if bids and asks and bids.peekitem(-1)[0] >= asks.peekitem(0)[0]:
            # A correctly maintained book cannot be crossed: treat as corrupt.
            self.crossed_resets += 1
            self.reset()
            return DiffResult.GAP
        return DiffResult.APPLIED

    # ---------------------------------------------------------------- reads
    @property
    def is_synced(self) -> bool:
        return self.sync is BookSync.SYNCED

    def best_bid(self) -> tuple[int, int] | None:
        return self.bids.peekitem(-1) if self.bids else None

    def best_ask(self) -> tuple[int, int] | None:
        return self.asks.peekitem(0) if self.asks else None

    def top(self, n: int) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
        b = self.bids
        bids = [(p, b[p]) for p in b.islice(max(0, len(b) - n), reverse=True)]
        a = self.asks
        asks = [(p, a[p]) for p in a.islice(0, n)]
        return bids, asks

    def depth_imbalance(self, levels: int = 10) -> float | None:
        """(sum bid qty - sum ask qty) / total over the top ``levels``."""
        bids, asks = self.top(levels)
        bq = sum(q for _, q in bids)
        aq = sum(q for _, q in asks)
        return (bq - aq) / (bq + aq) if bq + aq else None

    def sweep(self, side: str, qty: int) -> tuple[int, int, int] | None:
        """Walk the book to fill ``qty`` (e8) taking liquidity.

        ``side="buy"`` consumes asks, ``"sell"`` consumes bids. Returns
        (filled_qty_e8, notional_e16, worst_price_e8); notional is exact
        (price_e8 * qty_e8). Returns None if the book is not synced.
        """
        if not self.is_synced:
            return None
        if side == "buy":
            it = self.asks.items()
        elif side == "sell":
            it = reversed(self.bids.items())
        else:
            raise ValueError(side)
        remaining = qty
        notional = 0
        worst = 0
        for p, q in it:
            if remaining <= 0:
                break
            take = q if q < remaining else remaining
            notional += p * take
            remaining -= take
            worst = p
        return qty - remaining, notional, worst

    def snapshot_view(self, n: int = 10) -> dict[str, Any]:
        bids, asks = self.top(n)
        return {
            "key": self.symbol,
            "sync": self.sync.value,
            "version": self.version,
            "foreign_deltas": self.foreign_deltas,
            "last_update_id": self.last_update_id,
            "bids": [[p / ONE, q / ONE] for p, q in bids],
            "asks": [[p / ONE, q / ONE] for p, q in asks],
            "levels": [len(self.bids), len(self.asks)],
            "gaps": self.gaps,
            "resyncs": self.resyncs,
            "crossed_resets": self.crossed_resets,
            "buffer_overflow": self.buffer_overflow,
        }


SnapshotFetcher = Callable[[str, int], Awaitable[dict[str, Any] | None]]


def parse_snapshot(payload: dict[str, Any]) -> tuple[int, list[tuple[int, int]], list[tuple[int, int]]]:
    return (
        int(payload["lastUpdateId"]),
        [(parse_e8(p), parse_e8(q)) for p, q in payload["bids"]],
        [(parse_e8(p), parse_e8(q)) for p, q in payload["asks"]],
    )


class OrderBookManager:
    """Owns all local books (keyed by instrument key) and schedules REST
    snapshots off the hot path for diff-based venues."""

    def __init__(self, fetch: SnapshotFetcher | None = None, *, limit: int = 1000,
                 retry_delay_s: float = 1.0, max_retries: int = 10,
                 on_payload: Any = None) -> None:
        self.books: dict[str, LocalOrderBook] = {}
        # Called with (key, payload) for every REST snapshot received, so it can be
        # recorded and replayed at the same point in the stream.
        self.on_payload = on_payload
        self._fetch = fetch
        self.limit = limit
        self.retry_delay_s = retry_delay_s
        self.max_retries = max_retries
        self._pending: dict[str, asyncio.Task[None]] = {}
        self.snapshot_requests = 0
        self.snapshot_failures = 0
        self.stream_snapshots = 0

    def add(self, key: str) -> LocalOrderBook:
        b = self.books.get(key)
        if b is None:
            b = self.books[key] = LocalOrderBook(key)
        return b

    # -------------------------------------------- diff + REST (Binance)
    def on_diff(self, ev: DepthDiff) -> DiffResult | None:
        book = self.books.get(ev.key)
        if book is None:
            return None
        res = book.on_diff(ev)
        if res is DiffResult.GAP:
            book.resyncs += 1
            log.warning("order book gap; resynchronising", extra={"key": ev.key})
            book.on_diff(ev)
            self._schedule(ev.key)
        elif res is DiffResult.NEED_SNAPSHOT:
            self._schedule(ev.key)
        return res

    # ------------------------------------- stream snapshot (Coinbase)
    def on_snapshot(self, ev: BookSnapshot) -> DiffResult | None:
        book = self.books.get(ev.key)
        if book is None:
            return None
        self.stream_snapshots += 1
        return book.load_snapshot(ev.bids, ev.asks, ev.src, ev.event_time_ns, ev.recv_mono_ns)

    def on_delta(self, ev: BookDelta) -> DiffResult | None:
        book = self.books.get(ev.key)
        if book is None:
            return None
        return book.apply_levels(ev.bids, ev.asks, ev.src, ev.event_time_ns, ev.recv_mono_ns)

    def reset_keys(self, keys: list[str]) -> None:
        """A connection dropped: its diff stream is broken."""
        for k in keys:
            book = self.books.get(k)
            if book is not None:
                book.reset()
                t = self._pending.pop(k, None)
                if t is not None:
                    t.cancel()

    reset_symbols = reset_keys

    def _schedule(self, key: str) -> None:
        if self._fetch is None:
            return
        t = self._pending.get(key)
        if t is not None and not t.done():
            return
        self._pending[key] = asyncio.get_running_loop().create_task(self._sync(key), name=f"book-sync-{key}")

    async def _sync(self, key: str) -> None:
        assert self._fetch is not None
        book = self.books[key]
        for attempt in range(self.max_retries):
            if book.is_synced:
                return
            try:
                self.snapshot_requests += 1
                payload = await self._fetch(key, self.limit)
                if payload is None:
                    return
                if self.on_payload is not None:
                    self.on_payload(key, payload)
                uid, bids, asks = parse_snapshot(payload)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.snapshot_failures += 1
                log.warning("depth snapshot failed", extra={"key": key, "error": str(exc)})
                await asyncio.sleep(self.retry_delay_s * (attempt + 1))
                continue
            res = book.apply_snapshot(uid, bids, asks)
            if res is SnapshotResult.SYNCED:
                log.info("order book synced", extra={"key": key, "last_update_id": book.last_update_id})
                return
            if res is SnapshotResult.GAP:
                book.resyncs += 1
            await asyncio.sleep(self.retry_delay_s)
        log.error("order book could not be synchronised", extra={"key": key})

    def apply_payload(self, key: str, payload: dict[str, Any]) -> SnapshotResult | None:
        """Apply a recorded REST snapshot (replay)."""
        book = self.books.get(key)
        if book is None:
            return None
        self.snapshot_requests += 1
        uid, bids, asks = parse_snapshot(payload)
        res = book.apply_snapshot(uid, bids, asks)
        if res is SnapshotResult.GAP:
            book.resyncs += 1
        return res

    async def close(self) -> None:
        for t in self._pending.values():
            t.cancel()
        for t in self._pending.values():
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        self._pending.clear()
