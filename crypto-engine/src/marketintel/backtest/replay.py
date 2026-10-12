"""Deterministic replay of recorded raw frames through the full system.

The recorded file's ``#meta`` header supplies instrument metadata and the
connection layout, so a replay needs no network. Frames are processed in
receive-time order with a :class:`ManualClock` set to each frame's recorded
monotonic time *before* the frame is applied, and the deterministic
scheduler fires everything that was due in between (feature samples,
simulated order arrivals, signal evaluations). Nothing can observe a frame
before its recorded receive time: no look-ahead.

Paper trading is disabled during the warm-up period (features need history)
and only trades inside ``[start, end)``.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from ..clock import NS_PER_S, ManualClock
from ..config import DataSource, Settings
from ..engine import Engine, Universe, make_adapters
from ..exchanges.base import ConnectionPlan, FeeSchedule, InstrumentSpec, MappingConfidence, MarketType, Venue
from ..exchanges.registry import InstrumentRegistry
from ..persistence.recorder import RecordedFrame, read_frames, read_meta
from ..persistence.sink import AuditSink
from ..runtime import add_components

log = logging.getLogger(__name__)


def spec_from_json(d: dict[str, Any]) -> InstrumentSpec:
    d = dict(d)
    d["venue"] = Venue(d["venue"])
    d["market_type"] = MarketType(d["market_type"])
    d["mapping"] = MappingConfidence(d.get("mapping", "VERIFIED"))
    f = d["fees"]
    d["fees"] = FeeSchedule(f["maker_bps"], f["taker_bps"], f.get("source", "config"))
    d["order_types"] = tuple(d.get("order_types", ()))
    d["restrictions"] = tuple(d.get("restrictions", ()))
    return InstrumentSpec(**d)


class ChronologyError(ValueError):
    pass


class Probe:
    """Per-summary time series for backtest metrics (equity, BTC mid, spread)."""

    name = "probe"

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.series: list[tuple[int, float | None, float | None, float | None]] = []

    def on_summary(self, now: int, health: dict[str, Any]) -> None:
        eq = None
        paper = self.engine.component("paper")
        if paper is not None and paper.portfolio.initialized:
            v = paper.portfolio.valuation()
            eq = v["equity_usd"] - v["funding_usd"]
        st = self.engine.state.instruments.get("BINANCE:BTCUSDT")
        mid = spread = None
        if st is not None and st.bid_px > 0 and st.ask_px > 0:
            mid = st.mid()
            spread = st.spread_bps()
        self.series.append((self.engine.clock.wall(), eq, mid, spread))


@dataclass
class ReplayResult:
    engine: Engine
    probe: Probe
    frames: int
    first_mono_ns: int
    last_mono_ns: int
    window: tuple[int, int]
    wall_seconds: float
    params: dict[str, Any] = field(default_factory=dict)


def load(path: str) -> tuple[dict[str, Any], list[RecordedFrame]]:
    meta = read_meta(path)
    frames = list(read_frames(path))
    for a, b in zip(frames, frames[1:]):
        if b.recv_mono_ns < a.recv_mono_ns:
            raise ChronologyError(f"{path}: frames out of receive-time order ({b.recv_mono_ns} < {a.recv_mono_ns})")
    return meta, frames


def build_replay_engine(meta: dict[str, Any], settings: Settings, first: RecordedFrame,
                        sink: AuditSink | None = None) -> Engine:
    s = settings.model_copy(deep=True)
    s.data_source = DataSource.REPLAY
    s.recording.enabled = False
    s.api.enabled = False
    reg = InstrumentRegistry(s.registry)
    uni = Universe()
    for d in meta["instruments"]:
        sp = spec_from_json(d)
        uni.specs.setdefault(sp.venue.value, []).append(sp)
    for v in list(uni.specs):
        if not s.venue(v).enabled:
            del uni.specs[v]
            continue
        uni.specs[v] = reg.add(uni.specs[v])
        uni.metadata_ok[v] = bool(meta.get("metadata_ok", {}).get(v, True))
        uni.notes[v] = f"replay of {meta.get('data_source', '?')} recording"
    plans = [ConnectionPlan(p["conn_id"], Venue(p["venue"]), "", p["symbols"]) for p in meta["plans"]
             if p["venue"] in uni.specs]
    eng = Engine(s, uni, reg, make_adapters(s, reg), clock=ManualClock(first.recv_mono_ns, first.recv_wall_ns),
                 sink=sink or AuditSink(capacity=1_000_000), plans=plans)
    add_components(eng)
    eng.add_component(Probe(eng))
    return eng


def replay(path: str | None = None, settings: Settings | None = None, *, meta: dict[str, Any] | None = None,
           frames: list[RecordedFrame] | None = None, start_ns: int | None = None, end_ns: int | None = None,
           warmup_s: float = 60.0, sink: AuditSink | None = None, flush_s: float | None = None) -> ReplayResult:
    """Replay a recording. ``start_ns``/``end_ns`` are wall-clock bounds of the
    trading window; frames from ``warmup_s`` before the window are processed
    with paper trading disabled."""
    if frames is None or meta is None:
        assert path is not None
        meta, frames = load(path)
    if not frames:
        raise ValueError("recording has no frames")
    settings = settings or Settings(data_source=DataSource.REPLAY, persistence={"jsonl_dir": None})
    t_start = start_ns if start_ns is not None else frames[0].recv_wall_ns
    t_end = end_ns if end_ns is not None else frames[-1].recv_wall_ns + 1
    warm_from = t_start - int(warmup_s * NS_PER_S)
    sel = [f for f in frames if warm_from <= f.recv_wall_ns < t_end]
    if not sel:
        raise ValueError("no frames in the requested window")
    eng = build_replay_engine(meta, settings, sel[0], sink)
    paper = eng.component("paper")
    trading_enabled = paper.cfg.enabled if paper is not None else False
    if paper is not None:
        paper.cfg.enabled = False
    eng.start_replay()
    decoders: dict[tuple[int, int], Any] = {}
    t0 = time.perf_counter()
    in_window = False
    for f in sel:
        if not in_window and f.recv_wall_ns >= t_start:
            in_window = True
            if paper is not None:
                paper.cfg.enabled = trading_enabled
        if f.conn_id == Engine.SNAPSHOT_CONN_ID:
            eng.replay_frame(f.raw, f.recv_mono_ns, f.recv_wall_ns, f.conn_id, None)
            continue
        dec = decoders.get((f.conn_id, f.sock_uid))
        if dec is None:
            conn = eng.conn_by_id.get(f.conn_id)
            if conn is None:
                continue
            dec = eng._decoder_factory(eng.adapters[conn.venue], conn.plan)(f.sock_uid)
            decoders[(f.conn_id, f.sock_uid)] = dec
        eng.replay_frame(f.raw, f.recv_mono_ns, f.recv_wall_ns, f.conn_id, dec)
    # Let in-flight simulated orders and signal evaluations complete.
    horizon = flush_s if flush_s is not None else max(eng.cfg.strategies.patterns.eval_horizons_s + [1.0]) + 1
    last = sel[-1]
    for c in eng.connections:
        c.health.last_msg_mono_ns = last.recv_mono_ns  # end of data, not a stall
    end_mono = last.recv_mono_ns + int(horizon * NS_PER_S)
    step = NS_PER_S // 10
    t = last.recv_mono_ns
    while t < end_mono:
        t += step
        eng.clock.set(t)  # type: ignore[attr-defined]
        eng.scheduler.run_due(t)
    return ReplayResult(eng, eng.component("probe"), len(sel), sel[0].recv_mono_ns, last.recv_mono_ns,
                        (t_start, t_end), time.perf_counter() - t0)


def frames_window(frames: Iterable[RecordedFrame]) -> tuple[int, int]:
    fs = list(frames)
    return fs[0].recv_wall_ns, fs[-1].recv_wall_ns
