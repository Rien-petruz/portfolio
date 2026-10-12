"""Non-blocking fan-out from ingestion to consumers.

Publishing never awaits and never blocks the read loop. Two queue types
define exactly what happens when a consumer falls behind:

* :class:`ConflatingQueue` - for "latest state" consumers (scanners,
  quote-driven strategies). It holds at most one pending entry per symbol: if
  a symbol updates five times before the consumer runs, the consumer sees it
  once and reads the *current* state. Memory is bounded by the number of
  symbols and nothing stale is ever processed. The time the symbol first
  became dirty is kept so queueing delay can be measured.
* :class:`DropOldestQueue` - for event-sequence consumers (trade-flow
  features). Bounded ring buffer; on overflow the oldest event is discarded
  and counted. Consumers must treat drops as data loss (they are exposed in
  diagnostics and degrade system health).
"""

from __future__ import annotations

import asyncio
from collections import deque
from typing import Generic, TypeVar

from .events import Trade

T = TypeVar("T")


class ConflatingQueue:
    __slots__ = ("name", "_pending", "_event", "published", "conflated", "max_depth")

    def __init__(self, name: str) -> None:
        self.name = name
        self._pending: dict[str, int] = {}
        self._event = asyncio.Event()
        self.published = 0
        self.conflated = 0
        self.max_depth = 0

    def put(self, symbol: str, dirty_since_ns: int) -> None:
        self.published += 1
        p = self._pending
        if symbol in p:
            self.conflated += 1
            return
        p[symbol] = dirty_since_ns
        if len(p) > self.max_depth:
            self.max_depth = len(p)
        self._event.set()

    def take_nowait(self) -> dict[str, int]:
        batch = self._pending
        if batch:
            self._pending = {}
        return batch

    async def get_batch(self) -> dict[str, int]:
        """Wait for and return all dirty symbols -> first-dirty mono ns."""
        while not self._pending:
            self._event.clear()
            await self._event.wait()
        batch = self._pending
        self._pending = {}
        return batch

    @property
    def depth(self) -> int:
        return len(self._pending)

    def stats(self) -> dict[str, int | str]:
        return {"name": self.name, "kind": "conflating", "depth": self.depth,
                "max_depth": self.max_depth, "published": self.published,
                "conflated": self.conflated, "dropped": 0}


class DropOldestQueue(Generic[T]):
    __slots__ = ("name", "_buf", "_event", "capacity", "published", "dropped", "max_depth")

    def __init__(self, name: str, capacity: int) -> None:
        self.name = name
        self.capacity = capacity
        self._buf: deque[T] = deque(maxlen=capacity)
        self._event = asyncio.Event()
        self.published = 0
        self.dropped = 0
        self.max_depth = 0

    def put(self, item: T) -> None:
        self.published += 1
        b = self._buf
        if len(b) == self.capacity:
            self.dropped += 1
        b.append(item)
        n = len(b)
        if n > self.max_depth:
            self.max_depth = n
        self._event.set()

    def take_nowait(self, max_items: int = 1 << 30) -> list[T]:
        b = self._buf
        n = min(len(b), max_items)
        return [b.popleft() for _ in range(n)]

    async def get_many(self, max_items: int = 1024) -> list[T]:
        while not self._buf:
            self._event.clear()
            await self._event.wait()
        b = self._buf
        n = min(len(b), max_items)
        return [b.popleft() for _ in range(n)]

    @property
    def depth(self) -> int:
        return len(self._buf)

    def stats(self) -> dict[str, int | str]:
        return {"name": self.name, "kind": "drop_oldest", "depth": self.depth,
                "capacity": self.capacity, "max_depth": self.max_depth,
                "published": self.published, "conflated": 0, "dropped": self.dropped}


class EventBus:
    def __init__(self) -> None:
        self.quote_queues: list[ConflatingQueue] = []
        self.trade_queues: list[DropOldestQueue[Trade]] = []

    def subscribe_quotes(self, name: str) -> ConflatingQueue:
        q = ConflatingQueue(name)
        self.quote_queues.append(q)
        return q

    def subscribe_trades(self, name: str, capacity: int) -> DropOldestQueue[Trade]:
        q: DropOldestQueue[Trade] = DropOldestQueue(name, capacity)
        self.trade_queues.append(q)
        return q

    def publish_quote(self, symbol: str, recv_mono_ns: int) -> None:
        for q in self.quote_queues:
            q.put(symbol, recv_mono_ns)

    def publish_trade(self, ev: Trade) -> None:
        for q in self.trade_queues:
            q.put(ev)

    def stats(self) -> list[dict[str, int | str]]:
        return [q.stats() for q in self.quote_queues] + [q.stats() for q in self.trade_queues]

    @property
    def total_dropped(self) -> int:
        return sum(q.dropped for q in self.trade_queues)

