import pytest
from pydantic import ValidationError

from marketintel.config import Settings, load_settings
from marketintel.exchanges.binance.streams import combined_url, plan_shards, streams_for_symbol
from marketintel.market_data.bus import ConflatingQueue, DropOldestQueue


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
        Settings(paper={"mode": "live"})  # there is no live mode
    with pytest.raises(ValidationError):
        Settings(binance={"max_streams_per_connection": 2000})
    with pytest.raises(ValidationError):
        Settings(binance={"quiet_after_ms": 5000, "stale_after_ms": 1000})
    with pytest.raises(ValidationError):
        Settings(binance={"min_symbols": 60, "max_symbols": 50})
    with pytest.raises(ValidationError, match="official exchange endpoints"):
        Settings(binance={"ws_base_url": "ws://127.0.0.1:9443"})
    with pytest.raises(ValidationError, match="official exchange endpoints"):
        Settings(coinbase={"rest_base_url": "http://evil.example"})
    assert Settings(data_source="SIMULATED", binance={"ws_base_url": "ws://127.0.0.1:9443"})
    assert Settings(binance={"ws_base_url": "wss://data-stream.binance.vision"}, coinbase={"enabled": False,
                                                                                         "ws_base_url": "ws://x"})
    monkeypatch.setenv("MIE_BINANCE__STALE_AFTER_MS", "7777")
    monkeypatch.setenv("MIE_PERSISTENCE__DATABASE_URL", "postgresql://u:secret@h/db")
    cfg = tmp_path / "c.toml"
    cfg.write_text('[binance]\nstale_after_ms = 9999\nquiet_after_ms = 1500\nexplicit_symbols = ["btcusdt"]\n')
    s = load_settings(str(cfg))
    assert s.binance.stale_after_ms == 7777  # env beats file
    assert s.binance.quiet_after_ms == 1500  # file beats default
    assert s.binance.explicit_symbols == ["BTCUSDT"]
    # Secrets are never rendered in dumps/logs.
    assert "secret" not in repr(s.persistence) and "secret" not in s.model_dump_json()
    assert s.persistence.database_url.get_secret_value().endswith("/db")
    with pytest.raises(FileNotFoundError):
        load_settings(str(tmp_path / "missing.toml"))


def test_example_config_loads():
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "..", "config", "engine.example.toml")
    s = load_settings(path)
    assert s.binance.min_symbols >= 50 and s.coinbase.enabled
    assert s.paper.mode == "paper"
