"""Durable, append-only audit records - never on the hot path.

Producers call :meth:`AuditSink.write` (synchronous, O(1), never blocks):
records go into a bounded queue drained by a background task that inserts in
batches. If the queue is full the record is *dropped and counted* (exposed
in diagnostics and degrading health) rather than slowing market-data
processing.

Every table has the same shape so the schema stays stable while payloads
evolve::

    id BIGSERIAL, ts TIMESTAMPTZ, correlation_id TEXT, strategy TEXT,
    venue TEXT, instrument TEXT, status TEXT, payload JSONB

Market ticks are *not* stored here (see the raw-frame recorder).
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import os
from collections import deque
from typing import Any

import orjson

log = logging.getLogger(__name__)

TABLES = (
    "opportunity_candidates",   # a candidate opportunity episode opened
    "opportunity_validations",  # validation decisions (accepted/rejected + reasons)
    "opportunity_outcomes",     # episode closed: lifetime, peak edge, execution outcome
    "strategy_signals",         # anomaly / pattern signals
    "signal_evaluations",       # forward-return evaluation of signals
    "sim_orders",               # simulated order lifecycle events
    "sim_fills",                # simulated fills
    "balance_snapshots",        # virtual balances / P&L snapshots
    "risk_events",              # risk-limit decisions, emergency stops
    "config_changes",           # effective configuration at start and runtime changes
    "audit_log",                # anything else worth an immutable record
)

SCHEMA_SQL = "\n".join(
    f"""CREATE TABLE IF NOT EXISTS {t} (
    id BIGSERIAL PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL,
    correlation_id TEXT,
    strategy TEXT,
    venue TEXT,
    instrument TEXT,
    status TEXT,
    payload JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS {t}_ts_idx ON {t} (ts);
CREATE INDEX IF NOT EXISTS {t}_corr_idx ON {t} (correlation_id);"""
    for t in TABLES
)

_COLUMNS = ("correlation_id", "strategy", "venue", "instrument", "status")


def _row(table: str, rec: dict[str, Any]) -> tuple[Any, ...]:
    ts_ns = rec.get("ts_ns") or 0
    ts = dt.datetime.fromtimestamp(ts_ns / 1e9, tz=dt.UTC) if ts_ns else dt.datetime.now(dt.UTC)
    return (ts, *(None if rec.get(c) is None else str(rec.get(c)) for c in _COLUMNS),
            orjson.dumps(rec, default=str, option=orjson.OPT_NON_STR_KEYS).decode())


class AuditSink:
    """Base: bounded in-memory queue + optional recent-records buffer for the API."""

    kind = "memory"

    def __init__(self, capacity: int = 50_000, recent: int = 2_000) -> None:
        self.capacity = capacity
        self._q: deque[tuple[str, dict[str, Any]]] = deque()
        self.recent: dict[str, deque[dict[str, Any]]] = {t: deque(maxlen=recent) for t in TABLES}
        self.written = 0
        self.dropped = 0
        self.failed_batches = 0
        self.last_error = ""
        self._event: asyncio.Event | None = None

    def write(self, table: str, rec: dict[str, Any]) -> None:
        if table not in self.recent:
            raise ValueError(f"unknown audit table {table!r}")
        self.recent[table].append(rec)
        if len(self._q) >= self.capacity:
            self.dropped += 1
            return
        self._q.append((table, rec))
        if self._event is not None:
            self._event.set()

    @property
    def depth(self) -> int:
        return len(self._q)

    async def start(self) -> None:
        self._event = asyncio.Event()

    async def flush(self) -> None:
        """Write everything queued (used at shutdown and in tests)."""
        while self._q:
            await self._write_batch(self._take(10_000))

    def _take(self, n: int) -> list[tuple[str, dict[str, Any]]]:
        out = []
        q = self._q
        while q and len(out) < n:
            out.append(q.popleft())
        return out

    async def _write_batch(self, batch: list[tuple[str, dict[str, Any]]]) -> None:
        self.written += len(batch)  # memory sink: recent buffers are the store

    async def run(self, batch_size: int = 500, flush_interval_s: float = 0.25) -> None:
        assert self._event is not None
        while True:
            if not self._q:
                self._event.clear()
                try:
                    await asyncio.wait_for(self._event.wait(), flush_interval_s)
                except TimeoutError:
                    continue
            batch = self._take(batch_size)
            try:
                await self._write_batch(batch)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.failed_batches += 1
                self.last_error = f"{type(exc).__name__}: {exc}"
                if self.failed_batches <= 10:
                    log.error("audit batch write failed; records requeued", extra={"error": self.last_error})
                # Requeue at the front (bounded) and back off.
                for item in reversed(batch):
                    if len(self._q) < self.capacity:
                        self._q.appendleft(item)
                    else:
                        self.dropped += 1
                await asyncio.sleep(min(5.0, 0.2 * self.failed_batches))

    async def close(self) -> None:
        try:
            await asyncio.wait_for(self.flush(), 10)
        except Exception as exc:
            log.error("audit flush at shutdown failed", extra={"error": str(exc)})

    def stats(self) -> dict[str, Any]:
        return {"kind": self.kind, "queued": self.depth, "written": self.written, "dropped": self.dropped,
                "failed_batches": self.failed_batches, "last_error": self.last_error}


class JsonlSink(AuditSink):
    """Append-only JSON-lines files per table (used when no database is configured)."""

    kind = "jsonl"

    def __init__(self, directory: str, **kw: Any) -> None:
        super().__init__(**kw)
        self.directory = directory
        os.makedirs(directory, exist_ok=True)

    async def _write_batch(self, batch: list[tuple[str, dict[str, Any]]]) -> None:
        by: dict[str, list[bytes]] = {}
        for t, rec in batch:
            by.setdefault(t, []).append(orjson.dumps(rec, default=str, option=orjson.OPT_NON_STR_KEYS) + b"\n")
        day = dt.datetime.now(dt.UTC).strftime("%Y%m%d")

        def write() -> None:
            for t, lines in by.items():
                with open(os.path.join(self.directory, f"{t}-{day}.jsonl"), "ab") as fh:
                    fh.writelines(lines)

        await asyncio.to_thread(write)
        self.written += len(batch)


class PostgresSink(AuditSink):
    """Batched inserts into PostgreSQL via asyncpg (off the event-loop hot path)."""

    kind = "postgres"

    def __init__(self, dsn: str, **kw: Any) -> None:
        super().__init__(**kw)
        self._dsn = dsn
        self._pool: Any = None

    async def start(self) -> None:
        import asyncpg

        await super().start()
        self._pool = await asyncpg.create_pool(self._dsn, min_size=1, max_size=2, command_timeout=10)
        async with self._pool.acquire() as con:
            await con.execute(SCHEMA_SQL)

    async def _write_batch(self, batch: list[tuple[str, dict[str, Any]]]) -> None:
        by: dict[str, list[tuple[Any, ...]]] = {}
        for t, rec in batch:
            by.setdefault(t, []).append(_row(t, rec))
        async with self._pool.acquire() as con:
            async with con.transaction():
                for t, rows in by.items():
                    await con.executemany(
                        f"INSERT INTO {t} (ts, correlation_id, strategy, venue, instrument, status, payload) "  # noqa: S608 - t in TABLES
                        "VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)", rows)
        self.written += len(batch)

    async def query(self, table: str, limit: int = 100) -> list[dict[str, Any]]:
        if table not in TABLES:
            raise ValueError(table)
        async with self._pool.acquire() as con:
            rows = await con.fetch(f"SELECT payload FROM {table} ORDER BY id DESC LIMIT $1", limit)  # noqa: S608 - whitelisted
        return [orjson.loads(r["payload"]) for r in rows]

    async def close(self) -> None:
        await super().close()
        if self._pool is not None:
            await self._pool.close()


def make_sink(cfg: Any) -> AuditSink:
    """PostgreSQL when a URL is configured, else JSONL files, else memory only."""
    if not cfg.enabled:
        return AuditSink(capacity=cfg.queue_capacity)
    if cfg.database_url is not None:
        return PostgresSink(cfg.database_url.get_secret_value(), capacity=cfg.queue_capacity)
    if cfg.jsonl_dir:
        return JsonlSink(cfg.jsonl_dir, capacity=cfg.queue_capacity)
    return AuditSink(capacity=cfg.queue_capacity)
