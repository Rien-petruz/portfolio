"""Receive-only CPU cost of WebSocket client libraries on the same stream.

Connects each client to the out-of-process simulator with the engine's shard
layout and only counts frames (no parsing), isolating transport cost.
aiohttp and picows are optional: ``pip install aiohttp picows``.

    python benchmarks/bench_ws_clients.py websockets|aiohttp|picows [--rate 8000]
"""

from __future__ import annotations

import argparse
import asyncio
import time
from typing import Any

from marketintel.exchange.binance.streams import combined_url, plan_shards
from marketintel.sim.fake_exchange import default_symbols
from marketintel.sim.process import SimProcess


async def start_clients(lib: str, urls: list[str], count: list[int]) -> list[Any]:
    handles: list[Any] = []
    if lib == "websockets":
        from websockets.asyncio.client import connect

        async def run_ws(url: str) -> None:
            async with connect(url, compression=None, max_queue=4096, max_size=2**22) as ws:
                while True:
                    await ws.recv(decode=False)
                    time.monotonic_ns()
                    count[0] += 1

        handles = [asyncio.create_task(run_ws(u)) for u in urls]
    elif lib == "aiohttp":
        import aiohttp

        session = aiohttp.ClientSession()
        handles.append(session)

        async def run_aio(url: str) -> None:
            async with session.ws_connect(url, compress=0, max_msg_size=2**22) as ws:
                while True:
                    await ws.receive()
                    time.monotonic_ns()
                    count[0] += 1

        handles += [asyncio.create_task(run_aio(u)) for u in urls]
    elif lib == "picows":
        from picows import WSListener, WSMsgType, ws_connect

        class Listener(WSListener):  # type: ignore[misc]
            def on_ws_frame(self, transport: Any, frame: Any) -> None:
                if frame.msg_type == WSMsgType.TEXT:
                    frame.get_payload_as_bytes()
                    time.monotonic_ns()
                    count[0] += 1

        for u in urls:
            transport, _ = await ws_connect(Listener, u)
            handles.append(transport)
    else:
        raise SystemExit(f"unknown client {lib}")
    return handles


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("lib", choices=["websockets", "aiohttp", "picows"])
    ap.add_argument("--rate", type=float, default=8000)
    ap.add_argument("--seconds", type=float, default=10)
    args = ap.parse_args()

    sim = SimProcess(updates_per_s=args.rate, seed=5)
    await asyncio.to_thread(sim.start)
    plans = plan_shards(default_symbols()[:69], depth_symbols={"BTCUSDT", "ETHUSDT"}, trades=True,
                        max_streams_per_connection=200, max_symbols_per_connection=40)
    count = [0]
    handles = await start_clients(args.lib, [combined_url(sim.ws_url, p.streams) for p in plans], count)
    try:
        await asyncio.sleep(2)
        f0, c0, t0 = count[0], time.process_time(), time.monotonic()
        await asyncio.sleep(args.seconds)
        f1, c1, t1 = count[0], time.process_time(), time.monotonic()
        n, wall, cpu = f1 - f0, t1 - t0, c1 - c0
        print(f"{args.lib:10s}: {n / wall:,.0f} frames/s, CPU {100 * cpu / wall:.1f}% of a core, "
              f"{1e6 * cpu / max(1, n):.1f} us CPU/frame")
    finally:
        sim.stop()
        for h in handles:
            if isinstance(h, asyncio.Task):
                h.cancel()
            elif hasattr(h, "close"):
                res = h.close()
                if asyncio.iscoroutine(res):
                    await res


if __name__ == "__main__":
    asyncio.run(main())
