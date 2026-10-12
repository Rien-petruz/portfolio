"""Live Binance check (opt-in): MIE_LIVE_TESTS=1 pytest -m live

Connects to the real public market-data endpoints and asserts the Phase 2
definition of done: >= 50 symbols streaming, every shard connected, BTCUSDT
live with a sane book.
"""

import os

import pytest

from marketintel.clock import mono_ns
from marketintel.config import Settings
from marketintel.engine import Engine, resolve_universe
from marketintel.exchange.binance.rest import BinanceRest
from marketintel.state.market_state import QuoteStatus

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.environ.get("MIE_LIVE_TESTS") != "1", reason="set MIE_LIVE_TESTS=1 to run"),
]


async def test_live_binance_ingestion():
    s = Settings(api={"enabled": False})
    rest = BinanceRest(s.binance.rest_base_url)
    universe = await resolve_universe(s, rest)
    engine = Engine(s, universe, rest=rest)
    await engine.start()
    try:
        def ready():
            now = mono_ns()
            usable = sum(engine.state.status(st, now) in (QuoteStatus.LIVE, QuoteStatus.QUIET)
                         for st in engine.state.symbols.values())
            return all(sh.health.connected for sh in engine.shards) and usable >= 50
        assert await engine.wait_until(ready, 60), engine.health()
        btc = engine.state.symbols["BTCUSDT"]
        assert await engine.wait_until(lambda: engine.state.status(btc, mono_ns()) is QuoteStatus.LIVE, 30)
        assert 0 < btc.bid_px < btc.ask_px
        assert universe.metadata_ok and btc.info is not None and btc.info.filters_known
        assert engine.health()["data_source"] == "LIVE"
    finally:
        await engine.stop()
        await rest.close()
