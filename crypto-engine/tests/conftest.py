from __future__ import annotations

import os
import random

import pytest

from marketintel.config import DataSource, Settings
from marketintel.engine import Engine
from marketintel.persistence.sink import AuditSink
from marketintel.runtime import build_system
from marketintel.sim.binance_sim import FakeBinance
from marketintel.sim.coinbase_sim import FakeCoinbase
from marketintel.sim.world import MarketWorld

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")

_FAST_VENUE = {"quiet_after_ms": 2000, "stale_after_ms": 5000, "connection_stall_ms": 800,
               "open_timeout_s": 3.0, "ping_interval_s": None, "ping_timeout_s": None}


def fast_settings(**over) -> Settings:
    """Short timeouts so failure scenarios run in seconds. The in-process
    simulators share the event loop with the engine in tests, so their CPU
    bursts show up as loop lag; lag detection has its own dedicated test."""
    s = Settings(
        data_source=DataSource.SIMULATED,
        binance=dict(_FAST_VENUE),
        coinbase={**_FAST_VENUE, "subscribe_messages_per_second": 8.0},
        feed={"watchdog_interval_ms": 50},
        backoff={"base_s": 0.05, "cap_s": 0.2, "rate_limited_min_s": 0.3, "stable_after_s": 1.0},
        engine={"summary_interval_ms": 200, "report_interval_s": 0.5, "loop_lag_degraded_ms": 1000.0},
        api={"enabled": False},
        persistence={"jsonl_dir": None},
    )
    for k, v in over.items():
        section = getattr(s, k)
        if isinstance(v, dict):
            for kk, vv in v.items():
                sub = getattr(section, kk)
                if isinstance(vv, dict) and hasattr(sub, "model_fields"):
                    for k3, v3 in vv.items():
                        setattr(sub, k3, v3)
                else:
                    setattr(section, kk, vv)
        else:
            setattr(s, k, v)
    return s


class Sims:
    def __init__(self, world: MarketWorld, binance: FakeBinance, coinbase: FakeCoinbase) -> None:
        self.world, self.binance, self.coinbase = world, binance, coinbase

    def point(self, s: Settings) -> Settings:
        s.binance.ws_base_url, s.binance.rest_base_url = self.binance.ws_url, self.binance.rest_url
        s.coinbase.ws_base_url, s.coinbase.rest_base_url = self.coinbase.ws_url, self.coinbase.rest_url
        return s


@pytest.fixture
async def sims():
    world = MarketWorld(11, lag_ms={"BINANCE": 0.0, "COINBASE": 0.0})
    b = FakeBinance(world=world, updates_per_s=1500, seed=11)
    c = FakeCoinbase(world, updates_per_s=500, seed=12)
    await b.start()
    await c.start()
    try:
        yield Sims(world, b, c)
    finally:
        await b.stop()
        await c.stop()


@pytest.fixture
async def sim(sims):
    """Binance simulator only (Coinbase disabled in settings made by make_engine)."""
    yield sims.binance


async def make_engine(sims: Sims, settings: Settings | None = None, *, components: bool = False,
                      sink: AuditSink | None = None) -> Engine:
    s = sims.point(settings or fast_settings())
    return await build_system(s, rng=random.Random(1), components=components, sink=sink or AuditSink())


@pytest.fixture
async def running(sims):
    engine = await make_engine(sims)
    await engine.start()
    try:
        yield engine, sims
    finally:
        await engine.stop()
