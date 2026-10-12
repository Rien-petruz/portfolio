"""Live venue check (opt-in): MIE_LIVE_TESTS=1 pytest -m live

Connects to the real public market-data endpoints of Binance and Coinbase
and asserts the definition of done for ingestion: >= 50 Binance symbols
streaming, BTCUSDT live, the secondary venue connected.
"""

import os

import pytest

from marketintel.clock import mono_ns
from marketintel.config import Settings
from marketintel.market_data.quality import QuoteStatus
from marketintel.runtime import build_system

pytestmark = [pytest.mark.live,
              pytest.mark.skipif(os.environ.get("MIE_LIVE_TESTS") != "1", reason="set MIE_LIVE_TESTS=1 to run")]


async def test_live_ingestion_both_venues():
    s = Settings(api={"enabled": False}, persistence={"jsonl_dir": None})
    engine = await build_system(s)
    await engine.start()
    try:
        def ready():
            h = engine.health()
            return h["venues"]["BINANCE"]["usable"] >= 50 and h["venues"].get("COINBASE", {}).get("usable", 0) >= 5
        assert await engine.wait_until(ready, 90), engine.health()
        btc = engine.state.instruments["BINANCE:BTCUSDT"]
        assert await engine.wait_until(lambda: engine.state.status(btc, mono_ns()) is QuoteStatus.LIVE, 30)
        assert 0 < btc.bid_px < btc.ask_px and engine.health()["data_source"] == "LIVE"
    finally:
        await engine.stop()
