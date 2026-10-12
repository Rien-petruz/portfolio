import pytest
from pydantic import ValidationError

from marketintel.config import Settings, load_settings
from marketintel.exchange.binance.streams import combined_url, plan_shards, streams_for_symbol
from marketintel.ingestion.bus import ConflatingQueue, DropOldestQueue


def test_streams_and_url():
    assert streams_for_symbol("BTCUSDT", trades=True, depth=True) == [
        "btcusdt@bookTicker", "btcusdt@trade", "btcusdt@depth@100ms"]
    assert combined_url("wss://x:9443/", ["a@b", "c@d"]) == "wss://x:9443/stream?streams=a@b/c@d"
    assert combined_url("wss://x", []) == "wss://x/stream"


def test_sharding_respects_limits_and_keeps_symbol_streams_together():
    syms = [f"S{i}USDT" for i in range(120)]
    shards = plan_shards(syms, depth_symbols={"S0USDT", "S5USDT"}, trades=True,
                         max_streams_per_connection=50, max_symbols_per_connection=40)
    assert sum(len(s.symbols) for s in shards) == 120
    for sh in shards:
        assert len(sh.streams) <= 50 and len(sh.symbols) <= 40
        for sym in sh.symbols:
            assert f"{sym.lower()}@bookTicker" in sh.streams
            assert f"{sym.lower()}@trade" in sh.streams
    assert [s.shard_id for s in shards] == list(range(len(shards)))
    with pytest.raises(ValueError):
        plan_shards(syms, depth_symbols=set(), trades=True, max_streams_per_connection=1025,
                    max_symbols_per_connection=10)
    with pytest.raises(ValueError):
        plan_shards(syms, depth_symbols=set(), trades=True, max_streams_per_connection=1,
                    max_symbols_per_connection=10)


async def test_conflating_queue_keeps_one_entry_per_symbol():
    q = ConflatingQueue("q")
    q.put("A", 1)
    q.put("A", 2)
    q.put("B", 3)
    batch = await q.get_batch()
    assert batch == {"A": 1, "B": 3}  # first-dirty time kept for latency
    assert q.conflated == 1 and q.depth == 0


async def test_drop_oldest_queue_bounds_memory_and_counts_drops():
    q = DropOldestQueue("t", capacity=3)
    for i in range(5):
        q.put(i)
    assert q.dropped == 2
    assert await q.get_many() == [2, 3, 4]


def test_config_validation_and_env(monkeypatch, tmp_path):
    with pytest.raises(ValidationError):
        Settings(execution={"live_trading_enabled": True})
    with pytest.raises(ValidationError):
        Settings(binance={"max_streams_per_connection": 2000})
    with pytest.raises(ValidationError):
        Settings(feed={"quiet_after_ms": 5000, "stale_after_ms": 1000})
    with pytest.raises(ValidationError):
        Settings(universe={"min_symbols": 60, "max_symbols": 50})
    with pytest.raises(ValidationError, match="official Binance endpoint"):
        Settings(binance={"ws_base_url": "ws://127.0.0.1:9443"})
    assert Settings(data_source="SIMULATED", binance={"ws_base_url": "ws://127.0.0.1:9443"})
    assert Settings(binance={"ws_base_url": "wss://data-stream.binance.vision"})
    monkeypatch.setenv("MIE_FEED__STALE_AFTER_MS", "7777")
    cfg = tmp_path / "c.toml"
    cfg.write_text('[feed]\nstale_after_ms = 9999\nquiet_after_ms = 1500\n[universe]\nexplicit_symbols = ["btcusdt"]\n')
    s = load_settings(str(cfg))
    assert s.feed.stale_after_ms == 7777  # env beats file
    assert s.feed.quiet_after_ms == 1500  # file beats default
    assert s.universe.explicit_symbols == ["BTCUSDT"]
    with pytest.raises(FileNotFoundError):
        load_settings(str(tmp_path / "missing.toml"))


def test_example_config_loads():
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "config", "engine.example.toml")
    s = load_settings(path)
    assert s.universe.min_symbols >= 50
    assert s.execution.live_trading_enabled is False
