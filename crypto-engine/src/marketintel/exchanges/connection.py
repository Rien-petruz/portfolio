"""Exchange-independent WebSocket connection management.

One :class:`ManagedConnection` owns a fixed :class:`ConnectionPlan` (URL,
subscription messages, symbols) and keeps exactly one *primary* WebSocket
for it, with:

* reconnect with exponential backoff + jitter, and a process-wide connection
  attempt limiter (Binance: 300 attempts / 5 min / IP);
* longer back-off on HTTP 429/418 handshake rejections;
* a stall watchdog: no frames for ``connection_stall_ms`` -> recycle socket;
* paced subscription messages after connect (venues limit inbound
  messages per second);
* proactive make-before-break rotation before a venue's maximum connection
  age and on shutdown notices. During the overlap both sockets deliver
  frames; each socket has its *own* decoder (per-connection sequence numbers
  stay correct), and duplicates are discarded downstream by update/trade id
  or by book ownership;
* explicit recycling on decoder-detected gaps (``recycle``);
* immediate down notification when the last live socket closes, so market
  state is invalidated at once rather than silently going stale.

Frames are handed to ``on_frame(raw, t_mono, t_wall, conn, decoder)``
synchronously, straight from the read loop, with monotonic and wall receive
timestamps taken immediately after ``recv``.
``on_frame`` must be cheap and must not block; anything expensive belongs in
downstream consumers fed through bounded queues.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from websockets.asyncio.client import connect as ws_connect
from websockets.exceptions import ConnectionClosed, InvalidStatus, InvalidURI, WebSocketException

from ..clock import NS_PER_MS, NS_PER_S, mono_ns, wall_ns
from ..config import BackoffConfig, VenueConfig
from ..ratelimit import Backoff, SlidingWindowLimiter
from .base import ConnectionPlan, FrameDecoder

log = logging.getLogger(__name__)

FrameCallback = Callable[[bytes, int, int, "ManagedConnection", FrameDecoder], None]
ShardCallback = Callable[["ManagedConnection"], None]


class ShardState(StrEnum):
    CONNECTING = "CONNECTING"
    LIVE = "LIVE"
    BACKOFF = "BACKOFF"
    STOPPED = "STOPPED"


@dataclass(slots=True)
class ShardHealth:
    shard_id: int
    venue: str
    symbols: list[str]
    streams: int
    state: ShardState = ShardState.CONNECTING
    connected: bool = False
    last_msg_mono_ns: int = 0
    connected_since_mono_ns: int = 0
    msgs: int = 0
    bytes: int = 0
    connects: int = 0
    disconnects: int = 0
    connect_failures: int = 0
    rotations: int = 0
    rotation_failures: int = 0
    server_shutdowns: int = 0
    stalls: int = 0
    callback_errors: int = 0
    open_sockets: int = 0
    # EWMA of exchange-event -> receipt delay, ns, and when it was last sampled.
    delivery_lag_ns: int = 0
    delivery_lag_at_ns: int = 0
    recycles: int = 0
    down_since_mono_ns: int = 0
    last_reconnect_ms: float | None = None
    last_error: str = ""
    errors: list[str] = field(default_factory=list)

    def note_error(self, msg: str) -> None:
        self.last_error = msg
        self.errors.append(msg)
        if len(self.errors) > 50:
            del self.errors[:-50]

    def snapshot(self, now_mono_ns: int) -> dict[str, Any]:
        return {
            "shard_id": self.shard_id,
            "venue": self.venue,
            "state": self.state.value,
            "connected": self.connected,
            "symbols": len(self.symbols),
            "streams": self.streams,
            "last_msg_age_ms": (now_mono_ns - self.last_msg_mono_ns) / NS_PER_MS if self.last_msg_mono_ns else None,
            "uptime_s": (now_mono_ns - self.connected_since_mono_ns) / NS_PER_S if self.connected else 0.0,
            "msgs": self.msgs,
            "bytes": self.bytes,
            "connects": self.connects,
            "reconnects": max(0, self.connects - 1),
            "disconnects": self.disconnects,
            "connect_failures": self.connect_failures,
            "rotations": self.rotations,
            "rotation_failures": self.rotation_failures,
            "server_shutdowns": self.server_shutdowns,
            "stalls": self.stalls,
            "callback_errors": self.callback_errors,
            "open_sockets": self.open_sockets,
            "delivery_lag_ms": round(self.delivery_lag_ns / NS_PER_MS, 2),
            "recycles": self.recycles,
            "last_reconnect_ms": self.last_reconnect_ms,
            "last_error": self.last_error,
        }


class _Sock:
    __slots__ = ("ws", "task", "opened_mono_ns", "last_msg_mono_ns", "first_frame", "closed", "seq", "decoder")

    def __init__(self, ws: Any, seq: int, decoder: FrameDecoder) -> None:
        self.ws = ws
        self.decoder = decoder
        self.task: asyncio.Task[None] | None = None
        self.opened_mono_ns = mono_ns()
        self.last_msg_mono_ns = self.opened_mono_ns
        self.first_frame = asyncio.Event()
        self.closed = False
        self.seq = seq


class ManagedConnection:
    def __init__(
        self,
        plan: ConnectionPlan,
        venue_cfg: VenueConfig,
        backoff_cfg: BackoffConfig,
        *,
        watchdog_interval_ms: int,
        decoder_factory: Callable[[int], FrameDecoder],
        on_frame: FrameCallback,
        on_up: ShardCallback,
        on_down: ShardCallback,
        attempt_limiter: SlidingWindowLimiter,
        rng: random.Random | None = None,
        connect: Callable[..., Any] = ws_connect,
    ) -> None:
        self.plan = plan
        self.shard_id = plan.conn_id
        self.venue = plan.venue.value
        self.vcfg = venue_cfg
        self.bcfg = backoff_cfg
        self.watchdog_interval_ms = watchdog_interval_ms
        self.health = ShardHealth(plan.conn_id, plan.venue.value, list(plan.symbols),
                                  max(1, len(plan.subscribe_messages)))
        self._decoder_factory = decoder_factory
        self._on_frame = on_frame
        self._on_up = on_up
        self._on_down = on_down
        self._limiter = attempt_limiter
        self._backoff = Backoff(backoff_cfg.base_s, backoff_cfg.cap_s, rng)
        self._connect = connect
        self._sockets: set[_Sock] = set()
        self._current: _Sock | None = None
        self._stopping = False
        self._wake = asyncio.Event()
        self._rotate_reason: str | None = None
        self._next_rotation_try_ns = 0
        self._seq = 0

    # ------------------------------------------------------------------ API
    def request_rotation(self, reason: str) -> None:
        if reason == "server_shutdown":
            self.health.server_shutdowns += 1
        if self._rotate_reason is None:
            self._rotate_reason = reason
            self._next_rotation_try_ns = 0
        self._wake.set()

    async def stop(self) -> None:
        self._stopping = True
        self._wake.set()
        for s in list(self._sockets):
            await self._close_sock(s)

    def recycle(self, reason: str) -> None:
        """Close the primary socket (e.g. sequence gap): forces resubscription
        and fresh snapshots. Market state is invalidated by the down event."""
        cur = self._current
        if cur is None or cur.closed:
            return
        self.health.recycles += 1
        self.health.note_error(f"recycle: {reason}")
        log.warning("recycling connection", extra={"conn": self.shard_id, "venue": self.venue, "reason": reason})
        asyncio.get_running_loop().create_task(self._close_sock(cur))

    @property
    def url(self) -> str:
        return self.plan.url

    @property
    def is_primary_decoder(self) -> Callable[[FrameDecoder], bool]:
        return lambda d: self._current is not None and self._current.decoder is d

    # ------------------------------------------------------------ main loop
    async def run(self) -> None:
        try:
            while not self._stopping:
                sock = await self._open_socket(max_attempts=None)
                if sock is None:
                    break
                self._current = sock
                self._mark_up()
                await self._supervise()
        finally:
            for s in list(self._sockets):
                await self._close_sock(s)
            if self.health.connected:
                self._mark_down("stopped")
            self.health.state = ShardState.STOPPED

    async def _supervise(self) -> None:
        interval = self.watchdog_interval_ms / 1000
        stall_ns = self.vcfg.connection_stall_ms * NS_PER_MS
        max_age_ns = int(self.vcfg.connection_max_age_s * NS_PER_S)
        stable_ns = int(self.bcfg.stable_after_s * NS_PER_S)
        while not self._stopping:
            cur = self._current
            if cur is None or not self.health.connected:
                return
            self._wake.clear()
            wake_task = asyncio.ensure_future(self._wake.wait())
            assert cur.task is not None
            await asyncio.wait({cur.task, wake_task}, timeout=interval, return_when=asyncio.FIRST_COMPLETED)
            wake_task.cancel()
            if self._stopping:
                return
            if not self.health.connected:
                return  # last live socket closed; reconnect via run()
            cur = self._current
            if cur is None:
                return
            now = mono_ns()
            if now - cur.last_msg_mono_ns > stall_ns:
                self.health.stalls += 1
                self.health.note_error(f"stall: no frames for {(now - cur.last_msg_mono_ns) / NS_PER_MS:.0f} ms")
                log.warning("connection stalled; recycling", extra={"conn": self.shard_id, "venue": self.venue})
                await self._close_sock(cur)
                continue
            if self.health.connected_since_mono_ns and now - self.health.connected_since_mono_ns > stable_ns:
                self._backoff.reset()
            if self._rotate_reason is None and now - cur.opened_mono_ns >= max_age_ns:
                self._rotate_reason = "max_age"
            if self._rotate_reason is not None and now >= self._next_rotation_try_ns:
                await self._rotate()

    async def _rotate(self) -> None:
        reason = self._rotate_reason
        old = self._current
        log.info("rotating connection", extra={"conn": self.shard_id, "venue": self.venue, "reason": reason})
        new = await self._open_socket(max_attempts=3)
        if new is not None:
            try:
                await asyncio.wait_for(new.first_frame.wait(), self.vcfg.open_timeout_s)
            except TimeoutError:
                await self._close_sock(new)
                new = None
        if new is None:
            self.health.rotation_failures += 1
            self.health.note_error(f"rotation ({reason}) failed; keeping current socket")
            # Retry later. If the old socket has died meanwhile, the shard is
            # already marked down and run() reconnects from scratch.
            self._next_rotation_try_ns = mono_ns() + int(self._backoff.next_delay() * NS_PER_S)
            return
        self._current = new
        self._rotate_reason = None
        self.health.rotations += 1
        if not self.health.connected:
            # The old socket died while we were rotating; we are up again.
            self._mark_up()
        if old is not None:
            await self._close_sock(old)

    # -------------------------------------------------------------- sockets
    async def _open_socket(self, max_attempts: int | None) -> _Sock | None:
        v = self.vcfg
        attempts = 0
        while not self._stopping:
            await self._limiter.acquire()
            if self._stopping:
                return None
            if not self.health.connected:
                self.health.state = ShardState.CONNECTING
            try:
                ws = await self._connect(
                    self.url,
                    open_timeout=v.open_timeout_s,
                    ping_interval=v.ping_interval_s,
                    ping_timeout=v.ping_timeout_s,
                    close_timeout=2,
                    compression="deflate" if v.compression else None,
                    max_size=2**24,
                    max_queue=4096,
                )
            except InvalidURI:
                raise
            except (OSError, TimeoutError, WebSocketException) as exc:
                self.health.connect_failures += 1
                delay = self._backoff.next_delay()
                if isinstance(exc, InvalidStatus) and exc.response.status_code in (418, 429):
                    retry_after = exc.response.headers.get("Retry-After")
                    delay = max(delay, self.bcfg.rate_limited_min_s,
                                float(retry_after) if retry_after and retry_after.isdigit() else 0.0)
                self.health.note_error(f"connect failed: {type(exc).__name__}: {exc}")
                log.warning("connect failed", extra={"conn": self.shard_id, "venue": self.venue,
                                                     "error": str(exc), "retry_in_s": round(delay, 3)})
                attempts += 1
                if max_attempts is not None and attempts >= max_attempts:
                    return None
                if not self.health.connected:
                    self.health.state = ShardState.BACKOFF
                await self._sleep(delay)
                continue

            self._seq += 1
            sock = _Sock(ws, self._seq, self._decoder_factory(self._seq))
            self._sockets.add(sock)
            self.health.open_sockets = len(self._sockets)
            self.health.connects += 1
            sock.task = asyncio.create_task(self._reader(sock), name=f"{self.venue}{self.shard_id}-reader{sock.seq}")
            if self.plan.subscribe_messages:
                try:
                    await self._subscribe(sock)
                except (ConnectionClosed, OSError) as exc:
                    self.health.note_error(f"subscribe failed: {exc}")
                    await self._close_sock(sock)
                    attempts += 1
                    if max_attempts is not None and attempts >= max_attempts:
                        return None
                    await self._sleep(self._backoff.next_delay())
                    continue
            return sock
        return None

    async def _subscribe(self, sock: _Sock) -> None:
        gap = 1.0 / self.vcfg.subscribe_messages_per_second
        for i, msg in enumerate(self.plan.subscribe_messages):
            if i:
                await asyncio.sleep(gap)
            await sock.ws.send(msg)

    async def _reader(self, sock: _Sock) -> None:
        recv = sock.ws.recv
        on_frame = self._on_frame
        h = self.health
        first = sock.first_frame
        dec = sock.decoder
        try:
            while True:
                raw = await recv(decode=False)
                t_mono = mono_ns()
                t_wall = wall_ns()
                sock.last_msg_mono_ns = t_mono
                h.last_msg_mono_ns = t_mono
                h.msgs += 1
                h.bytes += len(raw)
                if not first.is_set():
                    first.set()
                try:
                    on_frame(raw, t_mono, t_wall, self, dec)
                except Exception:  # never let a consumer bug kill ingestion
                    h.callback_errors += 1
                    if h.callback_errors <= 10:
                        log.exception("frame callback failed", extra={"conn": self.shard_id})
        except ConnectionClosed as exc:
            if not sock.closed:
                h.note_error(f"connection closed: code={exc.rcvd.code if exc.rcvd else None} reason={exc.rcvd.reason if exc.rcvd else ''}")
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover - defensive
            h.note_error(f"reader error: {type(exc).__name__}: {exc}")
            log.exception("reader failed", extra={"conn": self.shard_id})
        finally:
            self._socket_finished(sock)

    def _socket_finished(self, sock: _Sock) -> None:
        sock.closed = True
        self._sockets.discard(sock)
        self.health.open_sockets = len(self._sockets)
        if not self.health.connected:
            return
        # Still covered if another socket on this shard is already streaming.
        alternatives = [s for s in self._sockets if not s.closed and s.first_frame.is_set()]
        if sock is self._current and alternatives:
            self._current = alternatives[-1]
            return
        if sock is self._current or not alternatives and not any(not s.closed for s in self._sockets):
            self._mark_down("socket closed")

    async def _close_sock(self, sock: _Sock) -> None:
        if sock.closed and (sock.task is None or sock.task.done()):
            return
        sock.closed = True
        try:
            await asyncio.wait_for(sock.ws.close(), 2)
        except Exception:
            pass
        if sock.task is not None and not sock.task.done():
            sock.task.cancel()
            try:
                await sock.task
            except (asyncio.CancelledError, Exception):
                pass
        self._socket_finished(sock)

    async def _sleep(self, delay: float) -> None:
        try:
            await asyncio.wait_for(self._wait_stop(), delay)
        except TimeoutError:
            pass

    async def _wait_stop(self) -> None:
        while not self._stopping:
            self._wake.clear()
            await self._wake.wait()

    # --------------------------------------------------------------- status
    def _mark_up(self) -> None:
        h = self.health
        h.delivery_lag_ns = h.delivery_lag_at_ns = 0
        h.connected = True
        h.state = ShardState.LIVE
        now = mono_ns()
        h.connected_since_mono_ns = now
        if h.down_since_mono_ns:
            h.last_reconnect_ms = (now - h.down_since_mono_ns) / NS_PER_MS
            h.down_since_mono_ns = 0
        log.info("connection up", extra={"conn": self.shard_id, "venue": self.venue, "symbols": len(h.symbols),
                                         "reconnect_ms": h.last_reconnect_ms})
        self._on_up(self)

    def _mark_down(self, reason: str) -> None:
        h = self.health
        if not h.connected:
            return
        h.connected = False
        h.disconnects += 1
        h.down_since_mono_ns = mono_ns()
        h.state = ShardState.CONNECTING if not self._stopping else ShardState.STOPPED
        log.warning("connection down", extra={"conn": self.shard_id, "venue": self.venue, "reason": reason})
        self._on_down(self)
