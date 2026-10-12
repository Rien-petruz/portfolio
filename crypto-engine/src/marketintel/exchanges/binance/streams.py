"""Binance stream naming and connection sharding.

All streams of one symbol stay on the same connection so a disconnect
invalidates a symbol atomically.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ...config import BINANCE_MAX_STREAMS_PER_CONNECTION


def streams_for_symbol(symbol: str, *, trades: bool, depth: bool) -> list[str]:
    s = symbol.lower()
    out = [f"{s}@bookTicker"]
    if trades:
        out.append(f"{s}@trade")
    if depth:
        out.append(f"{s}@depth@100ms")
    return out


@dataclass(slots=True)
class ShardPlan:
    shard_id: int
    symbols: list[str] = field(default_factory=list)
    streams: list[str] = field(default_factory=list)


def plan_shards(symbols: list[str], *, depth_symbols: set[str], trades: bool,
                max_streams_per_connection: int, max_symbols_per_connection: int) -> list[ShardPlan]:
    if max_streams_per_connection > BINANCE_MAX_STREAMS_PER_CONNECTION:
        raise ValueError("exceeds Binance's 1024 streams per connection")
    shards: list[ShardPlan] = []
    cur = ShardPlan(0)
    for sym in symbols:
        st = streams_for_symbol(sym, trades=trades, depth=sym in depth_symbols)
        if len(st) > max_streams_per_connection:
            raise ValueError("max_streams_per_connection too small for one symbol")
        if cur.symbols and (len(cur.streams) + len(st) > max_streams_per_connection
                            or len(cur.symbols) >= max_symbols_per_connection):
            shards.append(cur)
            cur = ShardPlan(len(shards))
        cur.symbols.append(sym)
        cur.streams.extend(st)
    if cur.symbols:
        shards.append(cur)
    return shards


def combined_url(base: str, streams: list[str]) -> str:
    base = base.rstrip("/")
    if not streams:
        return f"{base}/stream"
    return f"{base}/stream?streams={'/'.join(streams)}"
