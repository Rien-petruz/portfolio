"""Engine: wires connections -> normalizer -> market state -> consumers.

Hot path (synchronous, runs inside each shard's read loop)::

    frame bytes --orjson--> event --> MarketState / OrderBook (in place)
                                  --> bus.publish (O(1), never blocks)

Everything else - consumers, reporting, the HTTP API, depth snapshots, clock
offset sampling - runs as separate asyncio tasks that read state or drain
bounded queues. Latency is measured per stage with monotonic timestamps; the
exchange-to-local delay is measured separately against exchange event times
(wall clock, corrected for the estimated clock offset when available).
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections import Counter
from enum import StrEnum
from typing import Any, Callable

from .clock import NS_PER_MS, NS_PER_S, mono_ns, wall_ns
from .config import DataSource, Settings
from .exchange.binance.rest import BinanceRest
from .exchange.binance.streams import plan_shards
from .exchange.binance.symbols import SymbolInfo, parse_exchange_info, select_universe
from .exchange.binance.ws import Shard, ShardHealth, ws_connect
from .ingestion.bus import EventBus
from .ingestion.events import BookTicker, DepthDiff, ServerShutdown, Trade
from .ingestion.normalizer import NormalizeError, Normalizer
from .metrics.latency import WindowedLatency
from .metrics.loop_lag import LoopLagMonitor
from .persistence.recorder import FrameRecorder
from .ratelimit import SlidingWindowLimiter
from .state.market_state import MarketState, QuoteStatus
from .state.order_book import OrderBookManager

log = logging.getLogger(__name__)

REFERENCE_SYMBOL = "BTCUSDT"


class Health(StrEnum):
    OK = "OK"
    DEGRADED = "DEGRADED"
    DOWN = "DOWN"
    STARTING = "STARTING"


class UniverseResult:
    def __init__(self, symbols: list[str], infos: dict[str, SymbolInfo], metadata_ok: bool, note: str) -> None:
        self.symbols = symbols
        self.infos = infos
        self.metadata_ok = metadata_ok
        self.note = note


async def resolve_universe(settings: Settings, rest: BinanceRest | None) -> UniverseResult:
    """Discover tradable symbols from exchange metadata, ranked by liquidity.

    Falls back to the configured symbol list if metadata is unavailable; in
    that case exchange filters are unknown and are reported as such (Phase 5
    profitability checks refuse symbols without filters).
    """
    u = settings.universe
    if rest is not None:
        try:
            infos = parse_exchange_info(await rest.exchange_info())
            volumes: dict[str, float] = {}
            if not u.explicit_symbols:
                for t in await rest.ticker_24h():
                    try:
                        volumes[t["symbol"]] = float(t["quoteVolume"])
                    except (KeyError, ValueError):
                        continue
            if u.explicit_symbols:
                missing = [s for s in u.explicit_symbols if s not in infos]
                if missing:
                    log.warning("explicit symbols unknown to exchange", extra={"symbols": missing})
                symbols = [s for s in u.explicit_symbols if s in infos]
            else:
                symbols = select_universe(
                    infos, volumes, quote_assets=u.quote_assets, required=u.required_symbols,
                    exclude=u.exclude_symbols, min_symbols=u.min_symbols, max_symbols=u.max_symbols,
                )
            return UniverseResult(symbols, infos, True, f"exchangeInfo: {len(infos)} symbols, selected {len(symbols)}")
        except Exception as exc:
            log.error("exchange metadata unavailable; using fallback symbol list", extra={"error": str(exc)})
            note = f"metadata unavailable ({type(exc).__name__}: {exc}); fallback list, filters unknown"
    else:
        note = "no REST client; fallback list, filters unknown"
    base = u.explicit_symbols or u.fallback_symbols
    seen: set[str] = set()
    symbols = [s for s in base if not (s in seen or seen.add(s)) and s not in u.exclude_symbols]
    return UniverseResult(symbols[: max(u.max_symbols, len(u.explicit_symbols))], {}, False, note)


class Engine:
    def __init__(
        self,
        settings: Settings,
        universe: UniverseResult,
        *,
        rest: BinanceRest | None = None,
        connect: Callable[..., Any] = ws_connect,
        rng: random.Random | None = None,
    ) -> None:
        self.cfg = settings
        self.universe = universe
        self.data_source: DataSource = settings.data_source
        self.rest = rest
        f = settings.feed
        self.state = MarketState(f.quiet_after_ms, f.stale_after_ms, f.connection_stall_ms,
                                 f.max_delivery_lag_ms)
        for s in universe.symbols:
            self.state.add_symbol(s, universe.infos.get(s))
        depth_syms = [s for s in settings.universe.depth_symbols if s in self.state.symbols]
        self.books = OrderBookManager(
            depth_syms, rest.depth if rest is not None else None, limit=settings.universe.depth_snapshot_limit)
        self.plans = plan_shards(
            universe.symbols,
            depth_symbols=set(depth_syms),
            trades=settings.universe.subscribe_trades,
            max_streams_per_connection=settings.binance.max_streams_per_connection,
            max_symbols_per_connection=settings.binance.max_symbols_per_connection,
        )
        self.normalizer = Normalizer()
        self.bus = EventBus()
        self.lat_parse = WindowedLatency("recv_to_normalized")
        self.lat_state = WindowedLatency("recv_to_state_applied")
        self.lat_quote_e2e = WindowedLatency("recv_to_quote_consumer")
        self.lat_trade_e2e = WindowedLatency("recv_to_trade_consumer")
        self.lat_exch_trade = WindowedLatency("exchange_event_to_recv_trade")
        self.lat_exch_depth = WindowedLatency("exchange_event_to_recv_depth")
        self.loop_lag = LoopLagMonitor(settings.engine.loop_lag_interval_ms)
        self.frames = 0
        self.events: Counter[str] = Counter()
        self.invalid: Counter[str] = Counter()
        self.negative_exchange_lag = 0
        self.clock_offset_ms: float | None = None
        self.clock_offset_rtt_ms: float | None = None
        self._offset_ns = 0
        self.attempt_limiter = SlidingWindowLimiter(
            settings.binance.connect_attempts_per_window, settings.binance.connect_window_s)
        self.shards = [
            Shard(p, settings, on_frame=self.on_frame, on_up=self._on_up, on_down=self._on_down,
                  attempt_limiter=self.attempt_limiter, rng=rng, connect=connect)
            for p in self.plans
        ]
        for sh in self.shards:
            self.state.bind_shard(sh.plan.symbols, sh.health)
        self.recorder: FrameRecorder | None = None
        if settings.recording.enabled:
            self.recorder = FrameRecorder(settings.recording.directory, settings.recording.queue_capacity)
        self.quote_queue = self.bus.subscribe_quotes("quote_scanner")
        self.trade_queue = self.bus.subscribe_trades("trade_tap", settings.engine.trade_queue_capacity)
        self.scanner_rows_processed = 0
        self.trade_tap: dict[str, list[float]] = {}  # symbol -> [count, base_qty, quote_notional]
        self.started_wall_ns = wall_ns()
        self.started_mono_ns = mono_ns()
        self._tasks: list[asyncio.Task[Any]] = []
        self._stopped = asyncio.Event()
        self._last_report: dict[str, Any] = {}
        self._prev_dropped = 0
        self._drops_in_window = 0

    # ============================================================ hot path
    def on_frame(self, raw: bytes, t_mono: int, t_wall: int, shard: Shard) -> None:
        self.frames += 1
        try:
            ev = self.normalizer.normalize(raw, t_mono, t_wall, shard.shard_id)
        except NormalizeError as exc:
            self.invalid[exc.reason] += 1
            return
        if self.recorder is not None:
            self.recorder.write(raw, t_wall, t_mono, shard.shard_id)
        if ev is None:
            return
        self.lat_parse.record(mono_ns() - t_mono)
        cls = ev.__class__
        if cls is BookTicker:
            if self.state.apply_book_ticker(ev) is not None:  # type: ignore[arg-type]
                self.bus.publish_quote(ev.symbol, t_mono)  # type: ignore[union-attr]
        elif cls is Trade:
            if self.state.apply_trade(ev) is not None:  # type: ignore[arg-type]
                self.bus.publish_trade(ev)  # type: ignore[arg-type]
                lag = t_wall + self._offset_ns - ev.event_time_ms * NS_PER_MS  # type: ignore[union-attr]
                self._note_delivery_lag(shard, lag, t_mono)
                if lag >= 0:
                    self.lat_exch_trade.record(lag)
                else:
                    self.negative_exchange_lag += 1
        elif cls is DepthDiff:
            self.books.on_diff(ev)  # type: ignore[arg-type]
            lag = t_wall + self._offset_ns - ev.event_time_ms * NS_PER_MS  # type: ignore[union-attr]
            self._note_delivery_lag(shard, lag, t_mono)
            if lag >= 0:
                self.lat_exch_depth.record(lag)
            else:
                self.negative_exchange_lag += 1
        elif cls is ServerShutdown:
            log.warning("serverShutdown received; rotating", extra={"shard": shard.shard_id})
            shard.request_rotation("server_shutdown")
        self.events[cls.__name__] += 1
        self.lat_state.record(mono_ns() - t_mono)

    @staticmethod
    def _note_delivery_lag(shard: Shard, lag_ns: int, t_mono: int) -> None:
        h = shard.health
        if lag_ns < 0:
            lag_ns = 0  # clock skew within the offset uncertainty
        h.delivery_lag_ns += (lag_ns - h.delivery_lag_ns) >> 3  # EWMA, alpha = 1/8
        h.delivery_lag_at_ns = t_mono

    # ================================================= connection callbacks
    def _on_up(self, shard: Shard) -> None:
        self.state.on_shard_up(shard.plan.symbols)

    def _on_down(self, shard: Shard) -> None:
        self.state.on_shard_down(shard.plan.symbols)
        self.books.reset_symbols(shard.plan.symbols)

    # ============================================================ consumers
    async def _quote_scanner(self) -> None:
        """Reference latest-state consumer: measures receipt -> consumer
        latency. Phase 4 strategies plug in at exactly this point."""
        q = self.quote_queue
        rec = self.lat_quote_e2e.record
        while True:
            batch = await q.get_batch()
            for _sym, dirty_ns in batch.items():
                self.scanner_rows_processed += 1
                rec(mono_ns() - dirty_ns)

    async def _trade_tap(self) -> None:
        q = self.trade_queue
        rec = self.lat_trade_e2e.record
        tap = self.trade_tap
        while True:
            items = await q.get_many()
            now = mono_ns()
            for ev in items:
                rec(now - ev.recv_mono_ns)
                row = tap.get(ev.symbol)
                if row is None:
                    row = tap[ev.symbol] = [0, 0.0, 0.0]
                row[0] += 1
                row[1] += ev.qty / 1e8
                row[2] += ev.qty * ev.px / 1e16

    # ======================================================= periodic tasks
    async def _clock_offset_sampler(self) -> None:
        assert self.rest is not None
        best: list[tuple[float, float]] = []
        while True:
            try:
                off, rtt = await self.rest.clock_offset_ms()
                best.append((rtt, off))
                best = sorted(best)[:5]
                rtt0, off0 = best[0]
                self.clock_offset_ms, self.clock_offset_rtt_ms = off0, rtt0
                self._offset_ns = int(off0 * NS_PER_MS)
            except Exception as exc:
                log.warning("clock offset sample failed", extra={"error": str(exc)})
            await asyncio.sleep(60)

    async def _reporter(self) -> None:
        interval = self.cfg.engine.report_interval_s
        prev_frames = self.frames
        prev_t = mono_ns()
        while True:
            await asyncio.sleep(interval)
            now = mono_ns()
            for h in self._latencies():
                h.roll(now)
            self.loop_lag.hist.roll(now)
            dropped = self.bus.total_dropped
            self._drops_in_window = dropped - self._prev_dropped
            self._prev_dropped = dropped
            rate = (self.frames - prev_frames) / ((now - prev_t) / NS_PER_S)
            prev_frames, prev_t = self.frames, now
            counts = self.state.status_counts(now)
            self._last_report = {"frames_per_s": round(rate, 1)}
            lp = self.lat_state.summary()["window"]
            ll = self.loop_lag.hist.summary()["window"]
            log.info(
                "engine report",
                extra={
                    "data_source": self.data_source.value,
                    "health": self.health()["status"],
                    "shards_up": sum(1 for s in self.shards if s.health.connected),
                    "shards": len(self.shards),
                    "frames_per_s": round(rate, 1),
                    "status_counts": {k: v for k, v in counts.items() if v},
                    "recv_to_state_us": lp,
                    "loop_lag_us": ll,
                    "invalid": dict(self.invalid),
                    "trade_queue_dropped": dropped,
                },
            )
            self.loop_lag.max_recent_ns = 0

    def _latencies(self) -> list[WindowedLatency]:
        return [self.lat_parse, self.lat_state, self.lat_quote_e2e, self.lat_trade_e2e,
                self.lat_exch_trade, self.lat_exch_depth]

    # ============================================================ lifecycle
    async def start(self) -> None:
        log.info("starting engine", extra={
            "data_source": self.data_source.value, "symbols": len(self.state.symbols),
            "shards": len(self.shards), "universe": self.universe.note})
        loop = asyncio.get_running_loop()
        self._tasks.append(loop.create_task(self.loop_lag.run(), name="loop-lag"))
        self._tasks.append(loop.create_task(self._quote_scanner(), name="quote-scanner"))
        self._tasks.append(loop.create_task(self._trade_tap(), name="trade-tap"))
        self._tasks.append(loop.create_task(self._reporter(), name="reporter"))
        if self.rest is not None:
            self._tasks.append(loop.create_task(self._clock_offset_sampler(), name="clock-offset"))
        for sh in self.shards:
            self._tasks.append(loop.create_task(sh.run(), name=f"shard-{sh.shard_id}"))

    async def stop(self) -> None:
        for sh in self.shards:
            await sh.stop()
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        self._tasks.clear()
        await self.books.close()
        if self.recorder is not None:
            self.recorder.close()
        self._stopped.set()

    async def wait_until(self, predicate: Callable[[], bool], timeout: float, poll: float = 0.02) -> bool:
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            if predicate():
                return True
            await asyncio.sleep(poll)
        return predicate()

    # =============================================================== views
    def health(self) -> dict[str, Any]:
        now = mono_ns()
        reasons: list[str] = []
        up = sum(1 for s in self.shards if s.health.connected)
        counts = self.state.status_counts(now)
        usable = counts[QuoteStatus.LIVE.value] + counts[QuoteStatus.QUIET.value]
        ref = self.state.symbols.get(REFERENCE_SYMBOL)
        ref_status = self.state.status(ref, now).value if ref else "NOT_MONITORED"
        failures = sum(s.health.connect_failures for s in self.shards)
        if self.frames == 0 and failures == 0 and now - self.started_mono_ns < 15 * NS_PER_S:
            status = Health.STARTING
        elif up == 0:
            status = Health.DOWN
            reasons.append("no connected shards")
            if failures:
                reasons.append(f"{failures} failed connection attempts; last: "
                               + next((s.health.last_error for s in self.shards if s.health.last_error), ""))
        else:
            status = Health.OK
            if up < len(self.shards):
                reasons.append(f"{len(self.shards) - up} of {len(self.shards)} shards disconnected")
            if ref_status not in (QuoteStatus.LIVE.value, QuoteStatus.QUIET.value):
                reasons.append(f"{REFERENCE_SYMBOL} is {ref_status}")
            if usable < min(self.cfg.universe.min_symbols, len(self.state.symbols)):
                reasons.append(f"only {usable} usable symbols")
            lag = self.loop_lag.hist.last
            if lag.count and lag.percentile(0.99) > self.cfg.engine.loop_lag_degraded_ms * NS_PER_MS:
                reasons.append("event-loop lag p99 above threshold")
            if self.loop_lag.last_lag_ns > self.cfg.engine.loop_lag_degraded_ms * NS_PER_MS:
                reasons.append("event loop currently lagging")
            max_lag = self.cfg.feed.max_delivery_lag_ms * NS_PER_MS
            late = [s.shard_id for s in self.shards if s.health.connected and s.health.delivery_lag_ns > max_lag
                    and now - s.health.delivery_lag_at_ns < MarketState.LAG_SAMPLE_TTL_NS]
            if late:
                reasons.append(f"shards {late} delivering data later than {self.cfg.feed.max_delivery_lag_ms} ms")
            if self._drops_in_window:
                reasons.append(f"{self._drops_in_window} trade events dropped in last window")
            if self.recorder is not None and self.recorder.dropped:
                reasons.append(f"recorder dropped {self.recorder.dropped} frames")
            if reasons:
                status = Health.DEGRADED
        last_msg = max((s.health.last_msg_mono_ns for s in self.shards), default=0)
        return {
            "status": status.value,
            "reasons": reasons,
            "data_source": self.data_source.value,
            "observation_only": True,
            "execution_mode": self.cfg.execution.mode,
            "uptime_s": round((now - self.started_mono_ns) / NS_PER_S, 1),
            "shards_connected": up,
            "shards_total": len(self.shards),
            "symbols_total": len(self.state.symbols),
            "symbols_usable": usable,
            "status_counts": counts,
            "reference_symbol": REFERENCE_SYMBOL,
            "reference_status": ref_status,
            "last_frame_age_ms": round((now - last_msg) / NS_PER_MS, 1) if last_msg else None,
            "frames": self.frames,
            "frames_per_s": self._last_report.get("frames_per_s"),
            "metadata_ok": self.universe.metadata_ok,
            "universe_note": self.universe.note,
        }

    def latency_report(self) -> dict[str, Any]:
        rep = {h.name: h.summary() for h in self._latencies()}
        rep["event_loop_lag"] = self.loop_lag.hist.summary()
        rep["_notes"] = {
            "units": "microseconds",
            "window": f"last completed report interval ({self.lat_state.last_window_s:.1f} s)",
            "recv_to_*": "local monotonic clock, from frame handed over by the WebSocket client",
            "exchange_event_to_recv_*": (
                "wall clock vs exchange event time E; includes network latency and clock skew"
                + (f"; corrected by estimated offset {self.clock_offset_ms:.2f} ms (+/- {self.clock_offset_rtt_ms / 2:.2f} ms)"
                   if self.clock_offset_ms is not None and self.clock_offset_rtt_ms is not None else "; NOT offset-corrected")
            ),
            "negative_exchange_lag_samples": self.negative_exchange_lag,
        }
        return rep

    def diagnostics(self) -> dict[str, Any]:
        now = mono_ns()
        return {
            "shards": [s.health.snapshot(now) for s in self.shards],
            "connect_limiter": {"attempts_in_window": self.attempt_limiter.in_window,
                                "limit": self.attempt_limiter.limit, "waits": self.attempt_limiter.waits},
            "queues": self.bus.stats(),
            "frames": self.frames,
            "events": dict(self.events),
            "invalid": dict(self.invalid),
            "unknown_event_types": dict(self.normalizer.unknown),
            "control_messages": self.normalizer.control_messages,
            "control_errors": list(self.normalizer.control_errors[-10:]),
            "unknown_symbol_events": self.state.unknown_symbol_events,
            "order_books": {s: {"sync": b.sync.value, "last_update_id": b.last_update_id, "gaps": b.gaps,
                                "resyncs": b.resyncs, "crossed_resets": b.crossed_resets,
                                "levels": [len(b.bids), len(b.asks)]}
                            for s, b in self.books.books.items()},
            "snapshot_requests": self.books.snapshot_requests,
            "snapshot_failures": self.books.snapshot_failures,
            "rest": {"requests": self.rest.requests, "errors": self.rest.errors,
                     "used_weight": self.rest.used_weight} if self.rest else None,
            "recorder": {"path": self.recorder.path, "written": self.recorder.written,
                         "dropped": self.recorder.dropped} if self.recorder else None,
            "errors": [e for s in self.shards for e in s.health.errors[-5:]],
        }

    def market_rows(self) -> list[dict[str, Any]]:
        now = mono_ns()
        rows = []
        for st in self.state.symbols.values():
            row = self.state.row(st, now)
            tap = self.trade_tap.get(st.symbol)
            row["tapped_trades"] = int(tap[0]) if tap else 0
            row["tapped_quote_volume"] = tap[2] if tap else 0.0
            book = self.books.books.get(st.symbol)
            if book is not None and book.is_synced:
                row["depth_imbalance_10"] = book.depth_imbalance(10)
            rows.append(row)
        return rows


__all__ = ["Engine", "Health", "UniverseResult", "resolve_universe", "ShardHealth"]
