"""Offline engines with hand-set market state for deterministic strategy tests."""

from __future__ import annotations

from marketintel.clock import ManualClock
from marketintel.config import DataSource, Settings
from marketintel.engine import Engine, Universe, make_adapters
from marketintel.exchanges.base import FeeSchedule, InstrumentSpec, MarketType, Venue
from marketintel.exchanges.registry import InstrumentRegistry
from marketintel.market_data.events import Quote
from marketintel.numeric import ONE, parse_e8
from marketintel.persistence.sink import AuditSink

T0 = 10_000_000_000_000


def spec(venue: str, symbol: str, base: str, quote: str, *, tick="0.01", step="0.0001", min_notional="1",
         taker=10.0, depth=False, **kw) -> InstrumentSpec:
    return InstrumentSpec(Venue(venue), symbol, base, quote, base, quote, MarketType.SPOT, "TRADING", True,
                          tick_size=parse_e8(tick), step_size=parse_e8(step), min_qty=parse_e8(step),
                          min_notional=parse_e8(min_notional), fees=FeeSchedule(taker, taker),
                          depth_available=depth, **kw)


def offline_engine(specs: list[InstrumentSpec], settings: Settings | None = None, *, components: bool = True) -> Engine:
    s = settings or Settings(data_source=DataSource.REPLAY, persistence={"jsonl_dir": None})
    reg = InstrumentRegistry(s.registry)
    uni = Universe()
    for sp in specs:
        uni.specs.setdefault(sp.venue.value, []).append(sp)
    for v in uni.specs:
        uni.specs[v] = reg.add(uni.specs[v])
        uni.metadata_ok[v] = True
    eng = Engine(s, uni, reg, make_adapters(s, reg), clock=ManualClock(T0, 1_700_000_000_000_000_000), sink=AuditSink())
    for c in eng.connections:
        c.health.connected = True
        c.health.last_msg_mono_ns = T0
    for k in eng.state.instruments:
        eng.state.instruments[k].book_update_id = 0
    if components:
        from marketintel.runtime import add_components
        add_components(eng)
        eng.start_replay()
    return eng


_uid: dict[str, int] = {}


def quote(eng: Engine, key: str, bid: str, ask: str, bid_qty: str = "10", ask_qty: str = "10", *,
          t: int | None = None, event_time_ns: int = 0) -> None:
    t = eng.clock.mono() if t is None else t
    _uid[key] = _uid.get(key, 0) + 1
    st = eng.state.instruments[key]
    q = Quote(key, st.book_update_id + 1, parse_e8(bid), parse_e8(bid_qty), parse_e8(ask), parse_e8(ask_qty),
              t, eng.clock.wall(), 0, event_time_ns)
    eng.state.apply_quote(q)
    if st.shard is not None:
        st.shard.last_msg_mono_ns = max(st.shard.last_msg_mono_ns, t)
    eng.bus.publish_quote(key, t)


def advance(eng: Engine, ms: float) -> int:
    eng.clock.advance(int(ms * 1_000_000))
    now = eng.clock.mono()
    for c in eng.connections:
        c.health.last_msg_mono_ns = now
    eng.scheduler.run_due(now)
    return now


__all__ = ["ONE", "T0", "advance", "offline_engine", "quote", "spec"]
