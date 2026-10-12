"""Engine: adapters -> decoders -> market state -> consumers.

Hot path (synchronous, inside each connection's read loop)::

    frame bytes -> venue decoder -> normalized event(s)
                -> MarketState / LocalOrderBook (in place; Coinbase BBO derived from its book)
                -> bus.publish (O(1), never awaits)

Everything else - strategies, paper trading, persistence, the API, depth
snapshots, clock-offset sampling - consumes bounded queues or runs from the
deterministic :class:`Scheduler`. In replay mode the same components are
driven by a :class:`ManualClock` and :meth:`Engine.replay_frame`.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

from .clock import NS_PER_MS, NS_PER_S, Clock, LiveClock, mono_ns
from .config import DataSource, Settings
from .exchanges.base import ConnectionPlan, ExchangeAdapter, FrameDecoder, InstrumentSpec, Venue
from .exchanges.connection import ManagedConnection, ShardHealth, ws_connect
from .exchanges.errors import DecodeError
from .exchanges.registry import InstrumentRegistry
from .market_data.bus import ConflatingQueue, DropOldestQueue, EventBus
from .market_data.events import BookDelta, BookSnapshot, ConnectionNotice, DepthDiff, Quote, Trade
from .market_data.order_book import DiffResult, OrderBookManager
from .market_data.quality import LAG_SAMPLE_TTL_NS, QuoteStatus
from .market_data.state import MarketState
from .metrics.loop_lag import LoopLagMonitor
from .metrics.registry import LatencyRegistry
from .persistence.recorder import FrameRecorder
from .persistence.sink import AuditSink
from .ratelimit import SlidingWindowLimiter
from .safety import EXECUTION_MODE, PAPER_BANNER
from .scheduler import Scheduler

log = logging.getLogger(__name__)

REFERENCE_KEY = "BINANCE:BTCUSDT"


class Health(StrEnum):
    OK = "OK"
    DEGRADED = "DEGRADED"
    DOWN = "DOWN"
    STARTING = "STARTING"


@dataclass
class Universe:
    specs: dict[str, list[InstrumentSpec]] = field(default_factory=dict)
    metadata_ok: dict[str, bool] = field(default_factory=dict)
    notes: dict[str, str] = field(default_factory=dict)

    def all(self) -> list[InstrumentSpec]:
        return [s for v in self.specs.values() for s in v]


def make_adapters(settings: Settings, registry: InstrumentRegistry) -> dict[str, ExchangeAdapter]:
    from .exchanges.binance.adapter import BinanceAdapter
    from .exchanges.coinbase.adapter import CoinbaseAdapter

    out: dict[str, ExchangeAdapter] = {}
    if settings.binance.enabled:
        out["BINANCE"] = BinanceAdapter(settings.binance, registry.asset_mapper("BINANCE"))
    if settings.coinbase.enabled:
        out["COINBASE"] = CoinbaseAdapter(settings.coinbase, registry.asset_mapper("COINBASE"))
    return out


async def resolve_universe(settings: Settings, adapters: dict[str, ExchangeAdapter],
                           registry: InstrumentRegistry) -> Universe:
    """Discover and select instruments per venue (primary venue first, so the
    secondary venue can be restricted to overlapping assets). Falls back to
    configured lists when metadata is unreachable - with filters unknown,
    which makes those instruments ineligible for paper execution."""
    u = Universe()
    for venue in [v for v in ("BINANCE", "COINBASE") if v in adapters]:
        ad = adapters[venue]
        if venue == "COINBASE" and "BINANCE" in u.specs:
            ad.wanted_bases = {s.base for s in u.specs["BINANCE"]}  # type: ignore[attr-defined]
        try:
            found = await ad.discover()
            chosen = ad.select(found)
            u.metadata_ok[venue] = True
            u.notes[venue] = f"metadata: {len(found)} instruments, selected {len(chosen)}"
        except Exception as exc:
            log.error("venue metadata unavailable; using fallback list",
                      extra={"venue": venue, "error": f"{type(exc).__name__}: {exc}"})
            chosen = ad.select(ad.fallback_instruments())
            u.metadata_ok[venue] = False
            u.notes[venue] = f"metadata unavailable ({type(exc).__name__}: {exc}); fallback list, filters unknown"
        u.specs[venue] = registry.add(chosen)
    return u


def spec_to_json(s: InstrumentSpec) -> dict[str, Any]:
    d = asdict(s)
    d["venue"] = s.venue.value
    d["market_type"] = s.market_type.value
    d["mapping"] = s.mapping.value
    return d


class Engine:
    def __init__(
        self,
        settings: Settings,
        universe: Universe,
        registry: InstrumentRegistry,
        adapters: dict[str, ExchangeAdapter],
        *,
        clock: Clock | None = None,
        connect: Callable[..., Any] = ws_connect,
        rng: random.Random | None = None,
        sink: AuditSink | None = None,
        plans: list[ConnectionPlan] | None = None,
    ) -> None:
        self.cfg = settings
        self.universe = universe
        self.registry = registry
        self.adapters = adapters
        self.data_source: DataSource = settings.data_source
        self.clock = clock or LiveClock()
        self.replay = not self.clock.live
        self.scheduler = Scheduler(self.clock)
        self.metrics = LatencyRegistry()
        if self.clock.live:
            self.scheduler.metrics = self.metrics
        self.sink = sink or AuditSink()
        self.state = MarketState(settings.feed.max_delivery_lag_ms)
        self.books = OrderBookManager(None if self.replay else self._fetch_snapshot,
                                      limit=settings.binance.depth_snapshot_limit, on_payload=self._record_snapshot)
        for venue, specs in universe.specs.items():
            vcfg = settings.venue(venue)
            ad = adapters.get(venue)
            contiguous = bool(ad is not None and ad.capabilities.trade_ids_contiguous)
            for s in specs:
                self.state.add(s.key, s, quiet_ms=vcfg.quiet_after_ms, stale_ms=vcfg.stale_after_ms,
                               stall_ms=vcfg.connection_stall_ms, trade_ids_contiguous=contiguous)
                if s.depth_available:
                    self.books.add(s.key)
        self.bus = EventBus()
        self.loop_lag = LoopLagMonitor(settings.engine.loop_lag_interval_ms)

        # connections --------------------------------------------------------
        self.plans: list[ConnectionPlan] = []
        self.connections: list[ManagedConnection] = []
        self.conn_by_id: dict[int, ManagedConnection] = {}
        self.conn_keys: dict[int, list[str]] = {}
        self.limiters: dict[str, SlidingWindowLimiter] = {}
        next_id = 0
        for venue, specs in universe.specs.items():
            ad = adapters.get(venue)
            if ad is None or not specs:
                continue
            vcfg = settings.venue(venue)
            limiter = self.limiters[venue] = SlidingWindowLimiter(vcfg.connect_attempts_per_window,
                                                                  vcfg.connect_window_s)
            venue_plans = ([p for p in plans if p.venue.value == venue] if plans is not None
                           else ad.plan_connections(specs, next_id))
            for plan in venue_plans:
                self.plans.append(plan)
                conn = ManagedConnection(
                    plan, vcfg, settings.backoff, watchdog_interval_ms=settings.feed.watchdog_interval_ms,
                    decoder_factory=self._decoder_factory(ad, plan), on_frame=self.on_frame,
                    on_up=self._on_up, on_down=self._on_down, attempt_limiter=limiter, rng=rng, connect=connect)
                keys = [f"{venue}:{sym}" for sym in plan.symbols]
                self.connections.append(conn)
                self.conn_by_id[plan.conn_id] = conn
                self.conn_keys[plan.conn_id] = keys
                self.state.bind_shard(keys, conn.health)
                next_id = plan.conn_id + 1

        # instrumentation ------------------------------------------------------
        self.frames = 0
        self.frames_by_venue: Counter[str] = Counter()
        self.events: Counter[str] = Counter()
        self.invalid: Counter[str] = Counter()
        self.negative_exchange_lag = 0
        self.clock_offsets: dict[str, dict[str, float]] = {}
        self._offset_ns: dict[str, int] = {}
        self.recycles_requested = 0
        self.started_mono_ns = self.clock.mono()
        self.started_wall_ns = self.clock.wall()
        self.recorder: FrameRecorder | None = None
        if settings.recording.enabled and not self.replay:
            self.recorder = FrameRecorder(settings.recording.directory, self.recording_meta(),
                                          settings.recording.queue_capacity)

        # consumers ------------------------------------------------------------
        self.components: list[Any] = []
        self._quote_consumers: list[tuple[Any, ConflatingQueue]] = []
        self._trade_consumers: list[tuple[Any, DropOldestQueue[Trade]]] = []
        self._tasks: list[asyncio.Task[Any]] = []
        self._frames_at_summary = (0, self.clock.mono())
        self.frames_per_s = 0.0
        self.health_cache: dict[str, Any] = {}
        self._prev_dropped = 0
        self._drops_in_window = 0
        self.summary_listeners: list[Callable[[dict[str, Any]], None]] = []

    # ================================================================ wiring
    def _decoder_factory(self, ad: ExchangeAdapter, plan: ConnectionPlan) -> Callable[[int], FrameDecoder]:
        def make(uid: int) -> FrameDecoder:
            d = ad.make_decoder(plan, uid)
            d.sock_uid = uid  # type: ignore[attr-defined]
            return d
        return make

    def add_component(self, comp: Any, *, quotes: bool = False, trades: bool = False) -> None:
        self.components.append(comp)
        if quotes:
            self._quote_consumers.append((comp, self.bus.subscribe_quotes(comp.name)))
        if trades:
            self._trade_consumers.append(
                (comp, self.bus.subscribe_trades(comp.name, self.cfg.engine.trade_queue_capacity)))

    def component(self, name: str) -> Any:
        return next((c for c in self.components if c.name == name), None)

    async def _fetch_snapshot(self, key: str, limit: int) -> dict[str, Any] | None:
        venue, _, sym = key.partition(":")
        ad = self.adapters.get(venue)
        return None if ad is None else await ad.depth_snapshot(sym, limit)

    SNAPSHOT_CONN_ID = -1

    def _record_snapshot(self, key: str, payload: dict[str, Any]) -> None:
        if self.recorder is not None:
            import orjson
            raw = orjson.dumps({"snapshot_for": key, "payload": payload})
            self.recorder.write(raw, self.clock.wall(), self.clock.mono(), self.SNAPSHOT_CONN_ID, 0)

    def recording_meta(self) -> dict[str, Any]:
        return {
            "version": 2,
            "data_source": self.data_source.value,
            "started_wall_ns": self.started_wall_ns,
            "plans": [{"conn_id": p.conn_id, "venue": p.venue.value, "symbols": p.symbols} for p in self.plans],
            "instruments": [spec_to_json(s) for s in self.universe.all()],
            "metadata_ok": self.universe.metadata_ok,
            "notes": self.universe.notes,
        }

    # ============================================================== hot path
    def on_frame(self, raw: bytes, t_mono: int, t_wall: int, conn: ManagedConnection, decoder: FrameDecoder) -> None:
        t0 = mono_ns() if self.replay else t_mono
        venue = conn.venue
        self.frames += 1
        self.frames_by_venue[venue] += 1
        if self.recorder is not None:
            self.recorder.write(raw, t_wall, t_mono, conn.shard_id, getattr(decoder, "sock_uid", 0))
        try:
            res = decoder.decode(raw, t_mono, t_wall)
        except DecodeError as exc:
            self.invalid[f"{venue}:{exc.reason}"] += 1
            return
        if res is None:
            return
        self.metrics.record(f"ingest.recv_to_decoded.{venue}", mono_ns() - t0)
        if res.__class__ is list:
            for ev in res:
                self._dispatch(ev, conn, t_mono, t_wall)
        else:
            self._dispatch(res, conn, t_mono, t_wall)
        self.metrics.record(f"ingest.recv_to_state.{venue}", mono_ns() - t0)

    def _dispatch(self, ev: Any, conn: ManagedConnection, t_mono: int, t_wall: int) -> None:
        cls = ev.__class__
        if cls is Quote:
            if self.state.apply_quote(ev) is not None:
                self.bus.publish_quote(ev.key, t_mono)
        elif cls is Trade:
            if self.state.apply_trade(ev) is not None:
                self.bus.publish_trade(ev)
            self._note_lag(conn, ev.event_time_ns, t_wall, t_mono, "trade")
        elif cls is DepthDiff:
            self.books.on_diff(ev)
            self._note_lag(conn, ev.event_time_ns, t_wall, t_mono, "depth")
        elif cls is BookDelta or cls is BookSnapshot:
            res = self.books.on_snapshot(ev) if cls is BookSnapshot else self.books.on_delta(ev)
            if res is DiffResult.APPLIED:
                self._derive_quote(ev)
            elif res is DiffResult.GAP:
                self.state.invalidate(ev.key)
                self.recycles_requested += 1
                if not self.replay:
                    conn.recycle(f"crossed book {ev.key}")
            self._note_lag(conn, ev.event_time_ns, t_wall, t_mono, "book")
        elif cls is ConnectionNotice:
            if ev.kind == "server_shutdown":
                log.warning("server shutdown notice; rotating", extra={"conn": conn.shard_id})
                if not self.replay:
                    conn.request_rotation("server_shutdown")
            elif ev.kind == "resync_required":
                for k in self.conn_keys.get(conn.shard_id, ()):
                    self.state.invalidate(k)
                self.recycles_requested += 1
                if not self.replay:
                    conn.recycle(ev.detail)
        self.events[cls.__name__] += 1

    def _derive_quote(self, ev: BookSnapshot | BookDelta) -> None:
        book = self.books.books[ev.key]
        b, a = book.bids, book.asks
        bb = b.peekitem(-1) if b else (0, 0)
        ba = a.peekitem(0) if a else (0, 0)
        st = self.state.instruments.get(ev.key)
        if st is None:
            return
        if (st.book_fresh and bb[0] == st.bid_px and bb[1] == st.bid_qty
                and ba[0] == st.ask_px and ba[1] == st.ask_qty):
            return
        q = Quote(ev.key, book.version, bb[0], bb[1], ba[0], ba[1], ev.recv_mono_ns, ev.recv_wall_ns,
                  ev.conn_id, ev.event_time_ns)
        if self.state.apply_quote(q) is not None:
            self.bus.publish_quote(ev.key, ev.recv_mono_ns)

    def _note_lag(self, conn: ManagedConnection, event_time_ns: int, t_wall: int, t_mono: int, kind: str) -> None:
        if not event_time_ns:
            return
        lag = t_wall + self._offset_ns.get(conn.venue, 0) - event_time_ns
        h = conn.health
        if lag < 0:
            self.negative_exchange_lag += 1
            lag = 0
        else:
            self.metrics.record(f"exchange.event_to_recv.{conn.venue}.{kind}", lag)
        h.delivery_lag_ns += (lag - h.delivery_lag_ns) >> 3  # EWMA, alpha = 1/8
        h.delivery_lag_at_ns = t_mono

    # ================================================== connection callbacks
    def _on_up(self, conn: ManagedConnection) -> None:
        self.state.on_shard_up(self.conn_keys[conn.shard_id])
        self.audit("audit_log", {"event": "connection_up", "venue": conn.venue, "conn_id": conn.shard_id,
                                 "reconnect_ms": conn.health.last_reconnect_ms})

    def _on_down(self, conn: ManagedConnection) -> None:
        keys = self.conn_keys[conn.shard_id]
        self.state.on_shard_down(keys)
        self.books.reset_keys(keys)
        self.audit("audit_log", {"event": "connection_down", "venue": conn.venue, "conn_id": conn.shard_id,
                                 "error": conn.health.last_error})

    def audit(self, table: str, rec: dict[str, Any]) -> None:
        rec.setdefault("ts_ns", self.clock.wall())
        rec.setdefault("execution_mode", EXECUTION_MODE)
        self.sink.write(table, rec)

    # ============================================================== consumers
    def drain(self, now: int | None = None) -> None:
        """Synchronously deliver queued trades/quotes to consumers (replay)."""
        now = self.clock.mono() if now is None else now
        for comp, q in self._trade_consumers:
            items = q.take_nowait()
            if items:
                comp.on_trades(items, now)
        for comp, q in self._quote_consumers:
            batch = q.take_nowait()
            if batch:
                comp.on_quotes(batch, now)

    async def _quote_consumer(self, comp: Any, q: ConflatingQueue) -> None:
        while True:
            batch = await q.get_batch()
            try:
                comp.on_quotes(batch, self.clock.mono())
            except Exception:
                log.exception("quote consumer failed", extra={"component": comp.name})

    async def _trade_consumer(self, comp: Any, q: DropOldestQueue[Trade]) -> None:
        while True:
            items = await q.get_many(4096)
            try:
                comp.on_trades(items, self.clock.mono())
            except Exception:
                log.exception("trade consumer failed", extra={"component": comp.name})

    # ========================================================== periodic jobs
    def _schedule_periodic(self) -> None:
        e = self.cfg.engine
        self.scheduler.every(e.summary_interval_ms * NS_PER_MS, self._summary)
        self.scheduler.every(int(e.report_interval_s * NS_PER_S), self._report)
        for comp in self.components:
            fn = getattr(comp, "periodic", None)
            for interval_ms, job in (fn() if fn else []):
                self.scheduler.every(int(interval_ms * NS_PER_MS), job)

    def _summary(self, now: int) -> None:
        f0, t0 = self._frames_at_summary
        if now > t0:
            self.frames_per_s = (self.frames - f0) / ((now - t0) / NS_PER_S)
        self._frames_at_summary = (self.frames, now)
        dropped = self.bus.total_dropped
        self._drops_in_window = dropped - self._prev_dropped
        self._prev_dropped = dropped
        self.health_cache = self.health(now)
        for comp in self.components:
            fn = getattr(comp, "on_summary", None)
            if fn is not None:
                try:
                    fn(now, self.health_cache)
                except Exception:
                    log.exception("summary hook failed", extra={"component": comp.name})
        for listener in self.summary_listeners:
            try:
                listener(self.health_cache)
            except Exception:
                log.exception("summary listener failed")

    def _report(self, now: int) -> None:
        self.metrics.roll(now)
        self.loop_lag.hist.roll(now)
        h = self.health_cache or self.health(now)
        log.info("engine report", extra={
            "data_source": self.data_source.value, "health": h["status"], "reasons": h["reasons"],
            "frames_per_s": round(self.frames_per_s, 1),
            "venues": {v: {"connected": d["connections_up"], "usable": d["usable"]} for v, d in h["venues"].items()},
            "invalid": dict(self.invalid), "queue_drops": self.bus.total_dropped,
        })

    async def _clock_offset_sampler(self, venue: str, ad: ExchangeAdapter) -> None:
        samples: list[tuple[float, float]] = []
        while True:
            try:
                res = await ad.server_time_offset_ms()
                if res is not None:
                    off, rtt = res
                    samples = sorted(samples + [(rtt, off)])[:5]
                    rtt0, off0 = samples[0]
                    self.clock_offsets[venue] = {"offset_ms": round(off0, 3), "uncertainty_ms": round(rtt0 / 2, 3)}
                    self._offset_ns[venue] = int(off0 * NS_PER_MS)
            except Exception as exc:
                log.warning("clock offset sample failed", extra={"venue": venue, "error": str(exc)})
            await asyncio.sleep(60)

    # ============================================================== lifecycle
    def _start_components(self) -> None:
        for comp in self.components:
            fn = getattr(comp, "start", None)
            if fn is not None:
                fn(self)
        self._schedule_periodic()

    async def start(self) -> None:
        log.info("starting engine", extra={
            "data_source": self.data_source.value, "mode": EXECUTION_MODE,
            "instruments": {v: len(s) for v, s in self.universe.specs.items()},
            "connections": len(self.connections), "notes": self.universe.notes})
        await self.sink.start()
        self.audit("config_changes", {"event": "startup", "config": self.cfg.model_dump(
            mode="json", exclude={"persistence": {"database_url"}})})
        self._start_components()
        loop = asyncio.get_running_loop()
        coros: list[Any] = [self.loop_lag.run(), self.scheduler.run_forever(),
                            self.sink.run(self.cfg.persistence.batch_size, self.cfg.persistence.flush_interval_ms / 1000)]
        coros += [self._quote_consumer(c, q) for c, q in self._quote_consumers]
        coros += [self._trade_consumer(c, q) for c, q in self._trade_consumers]
        for venue, ad in self.adapters.items():
            if venue in self.universe.specs:
                coros.append(self._clock_offset_sampler(venue, ad))
        coros += [c.run() for c in self.connections]
        self._tasks = [loop.create_task(c) for c in coros]

    def start_replay(self) -> None:
        self._start_components()

    def replay_frame(self, raw: bytes, t_mono: int, t_wall: int, conn_id: int, decoder: FrameDecoder | None) -> None:
        """Process one recorded frame at its recorded receive time."""
        self.clock.set(t_mono, t_wall)  # type: ignore[attr-defined]
        self.scheduler.run_due(t_mono)
        if conn_id == self.SNAPSHOT_CONN_ID:
            import orjson
            msg = orjson.loads(raw)
            self.books.apply_payload(msg["snapshot_for"], msg["payload"])
            return
        conn = self.conn_by_id[conn_id]
        h = conn.health
        if not h.connected:
            h.connected = True
            self._on_up(conn)
        h.last_msg_mono_ns = t_mono
        self.on_frame(raw, t_mono, t_wall, conn, decoder)
        self.drain(t_mono)

    async def stop(self) -> None:
        for c in self.connections:
            await c.stop()
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        self._tasks.clear()
        for comp in self.components:
            fn = getattr(comp, "stop", None)
            if fn is not None:
                try:
                    fn()
                except Exception:
                    log.exception("component stop failed")
        await self.books.close()
        await self.sink.close()
        if self.recorder is not None:
            self.recorder.close()
        for ad in self.adapters.values():
            await ad.close()

    async def wait_until(self, predicate: Callable[[], bool], timeout: float, poll: float = 0.02) -> bool:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            if predicate():
                return True
            await asyncio.sleep(poll)
        return predicate()

    # ================================================================= views
    def venue_health(self, venue: str, now: int) -> dict[str, Any]:
        conns = [c for c in self.connections if c.venue == venue]
        counts = self.state.status_counts(now, venue)
        up = sum(1 for c in conns if c.health.connected)
        late = [c.shard_id for c in conns if c.health.connected
                and c.health.delivery_lag_ns > self.cfg.feed.max_delivery_lag_ms * NS_PER_MS
                and now - c.health.delivery_lag_at_ns < LAG_SAMPLE_TTL_NS]
        last = max((c.health.last_msg_mono_ns for c in conns), default=0)
        return {
            "connections_up": up,
            "connections_total": len(conns),
            "instruments": sum(counts.values()),
            "usable": counts[QuoteStatus.LIVE.value] + counts[QuoteStatus.QUIET.value],
            "status_counts": {k: v for k, v in counts.items() if v},
            "late_connections": late,
            "last_frame_age_ms": round((now - last) / NS_PER_MS, 1) if last else None,
            "frames": self.frames_by_venue.get(venue, 0),
            "reconnects": sum(max(0, c.health.connects - 1) for c in conns),
            "metadata_ok": self.universe.metadata_ok.get(venue, False),
            "note": self.universe.notes.get(venue, ""),
            "clock_offset": self.clock_offsets.get(venue),
        }

    def health(self, now: int | None = None) -> dict[str, Any]:
        now = self.clock.mono() if now is None else now
        reasons: list[str] = []
        venues = {v: self.venue_health(v, now) for v in self.universe.specs}
        up = sum(1 for c in self.connections if c.health.connected)
        failures = sum(c.health.connect_failures for c in self.connections)
        ref = self.state.instruments.get(REFERENCE_KEY)
        ref_status = self.state.status(ref, now).value if ref else "NOT_MONITORED"
        if self.frames == 0 and failures == 0 and now - self.started_mono_ns < 15 * NS_PER_S:
            status = Health.STARTING
        elif up == 0:
            status = Health.DOWN
            reasons.append("no connected feeds")
            if failures:
                reasons.append(f"{failures} failed connection attempts; last: "
                               + next((c.health.last_error for c in self.connections if c.health.last_error), ""))
        else:
            status = Health.OK
            for v, d in venues.items():
                if d["connections_up"] < d["connections_total"]:
                    reasons.append(f"{v}: {d['connections_total'] - d['connections_up']} of "
                                   f"{d['connections_total']} connections down")
                if d["late_connections"]:
                    reasons.append(f"{v}: connections {d['late_connections']} delivering data later than "
                                   f"{self.cfg.feed.max_delivery_lag_ms} ms")
            if ref_status not in (QuoteStatus.LIVE.value, QuoteStatus.QUIET.value):
                reasons.append(f"{REFERENCE_KEY} is {ref_status}")
            b = venues.get("BINANCE")
            if b is not None and b["usable"] < min(self.cfg.binance.min_symbols, b["instruments"]):
                reasons.append(f"BINANCE: only {b['usable']} usable instruments")
            lag = self.loop_lag.hist.last
            thr = self.cfg.engine.loop_lag_degraded_ms * NS_PER_MS
            if (lag.count and lag.percentile(0.99) > thr) or self.loop_lag.last_lag_ns > thr:
                reasons.append("event-loop lag above threshold")
            if self._drops_in_window:
                reasons.append(f"{self._drops_in_window} queued trade events dropped")
            if self.sink.dropped:
                reasons.append(f"audit sink dropped {self.sink.dropped} records")
            if self.recorder is not None and self.recorder.dropped:
                reasons.append(f"recorder dropped {self.recorder.dropped} frames")
            if reasons:
                status = Health.DEGRADED
        return {
            "status": status.value,
            "reasons": reasons,
            "data_source": self.data_source.value,
            "execution_mode": EXECUTION_MODE,
            "paper_banner": PAPER_BANNER,
            "uptime_s": round((now - self.started_mono_ns) / NS_PER_S, 1),
            "connections_up": up,
            "connections_total": len(self.connections),
            "instruments_total": len(self.state.instruments),
            "instruments_usable": sum(d["usable"] for d in venues.values()),
            "venues": venues,
            "reference": REFERENCE_KEY,
            "reference_status": ref_status,
            "frames": self.frames,
            "frames_per_s": round(self.frames_per_s, 1),
        }

    def latency_report(self) -> dict[str, Any]:
        rep: dict[str, Any] = self.metrics.report()
        rep["event_loop_lag"] = self.loop_lag.hist.summary()
        rep["_notes"] = {
            "units": "microseconds",
            "ingest.*": "local monotonic clock from frame receipt (processing time only, in replay)",
            "exchange.event_to_recv.*": "wall clock vs exchange event time: network + exchange batching + clock "
                                        "offset error (see clock_offsets); uncorrected where no offset sample exists",
            "clock_offsets": self.clock_offsets,
            "negative_exchange_lag_samples": self.negative_exchange_lag,
        }
        return rep

    def diagnostics(self) -> dict[str, Any]:
        now = self.clock.mono()
        decoders: dict[str, Any] = {}
        for c in self.connections:
            cur = c._current
            if cur is not None:
                d = cur.decoder
                decoders[f"{c.venue}#{c.shard_id}"] = {
                    k: getattr(d, k) for k in ("gaps", "out_of_order", "heartbeats", "history_trades_skipped",
                                               "control_messages") if hasattr(d, k)}
        return {
            "connections": [c.health.snapshot(now) for c in self.connections],
            "connect_limiters": {v: {"attempts_in_window": lim.in_window, "limit": lim.limit, "waits": lim.waits}
                                 for v, lim in self.limiters.items()},
            "decoders": decoders,
            "queues": self.bus.stats(),
            "frames": self.frames,
            "frames_by_venue": dict(self.frames_by_venue),
            "events": dict(self.events),
            "invalid": dict(self.invalid),
            "unknown_instrument_events": self.state.unknown_events,
            "recycles_requested": self.recycles_requested,
            "order_books": {k: {"sync": b.sync.value, "version": b.version, "gaps": b.gaps, "resyncs": b.resyncs,
                                "crossed_resets": b.crossed_resets, "foreign_deltas": b.foreign_deltas,
                                "levels": [len(b.bids), len(b.asks)]}
                            for k, b in self.books.books.items()},
            "snapshot_requests": self.books.snapshot_requests,
            "snapshot_failures": self.books.snapshot_failures,
            "stream_snapshots": self.books.stream_snapshots,
            "rest": {v: ad.http.stats() for v, ad in self.adapters.items() if hasattr(ad, "http")},
            "scheduler": {"executed": self.scheduler.executed, "errors": self.scheduler.errors,
                          "max_late_ms": round(self.scheduler.max_late_ns / NS_PER_MS, 2)},
            "audit_sink": self.sink.stats(),
            "recorder": {"path": self.recorder.path, "written": self.recorder.written,
                         "dropped": self.recorder.dropped} if self.recorder else None,
            "errors": [f"{c.venue}#{c.shard_id}: {e}" for c in self.connections for e in c.health.errors[-5:]],
        }

    def market_rows(self, venue: str | None = None) -> list[dict[str, Any]]:
        now = self.clock.mono()
        rows = []
        for st in self.state.instruments.values():
            if venue and st.venue != venue:
                continue
            row = self.state.row(st, now)
            book = self.books.books.get(st.key)
            if book is not None and book.is_synced:
                row["depth_imbalance_10"] = book.depth_imbalance(10)
                row["book_levels"] = [len(book.bids), len(book.asks)]
            for comp in self.components:
                fn = getattr(comp, "decorate_row", None)
                if fn is not None:
                    fn(st.key, row)
            rows.append(row)
        return rows


__all__ = ["Engine", "Health", "Universe", "make_adapters", "resolve_universe", "ShardHealth", "Venue"]
