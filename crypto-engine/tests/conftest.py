from __future__ import annotations

import os
import random

import pytest

from marketintel.config import DataSource, Settings
from marketintel.engine import Engine, resolve_universe
from marketintel.exchange.binance.rest import BinanceRest
from marketintel.sim.fake_exchange import FakeBinance

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def fast_settings(**over) -> Settings:
    """Settings with short timeouts so failure scenarios run in seconds."""
    s = Settings(
        data_source=DataSource.SIMULATED,
        feed={"quiet_after_ms": 2000, "stale_after_ms": 5000, "connection_stall_ms": 800,
              "watchdog_interval_ms": 50},
        backoff={"base_s": 0.05, "cap_s": 0.2, "rate_limited_min_s": 0.3, "stable_after_s": 1.0},
        binance={"open_timeout_s": 3.0, "ping_interval_s": None, "ping_timeout_s": None},
        # The in-process simulator shares the event loop with the engine in
        # these tests, so its CPU bursts show up as loop lag. Lag detection is
        # covered by test_overload.py; don't let it make feed tests flaky.
        engine={"report_interval_s": 0.5, "loop_lag_degraded_ms": 1000.0},
        api={"enabled": False},
    )
    for k, v in over.items():
        section = getattr(s, k)
        for kk, vv in v.items():
            setattr(section, kk, vv)
    return s


@pytest.fixture
async def sim():
    fx = FakeBinance(updates_per_s=1500, seed=11)
    await fx.start()
    try:
        yield fx
    finally:
        await fx.stop()


async def make_engine(sim: FakeBinance, settings: Settings | None = None) -> tuple[Engine, BinanceRest]:
    s = settings or fast_settings()
    s.binance.ws_base_url = sim.ws_url
    s.binance.rest_base_url = sim.rest_url
    rest = BinanceRest(sim.rest_url)
    universe = await resolve_universe(s, rest)
    engine = Engine(s, universe, rest=rest, rng=random.Random(1))
    return engine, rest


@pytest.fixture
async def running(sim):
    engine, rest = await make_engine(sim)
    await engine.start()
    try:
        yield engine, sim
    finally:
        await engine.stop()
        await rest.close()
