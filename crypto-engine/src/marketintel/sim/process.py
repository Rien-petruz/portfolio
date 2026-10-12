"""Run the simulated venues in separate OS processes (SYNTHETIC DATA).

Generating and serialising synthetic events is CPU work; hosting it on the
engine's event loop would inflate the engine's own latency measurements.

By default both simulators share one :class:`MarketWorld` inside a single
child process. With ``split_venues=True`` each venue gets its own process
(for high symbol counts, where one core cannot generate both feeds); the two
worlds use the same seed and a shared fixed-step epoch, so their price paths
are identical and cross-venue prices stay consistent.
"""

from __future__ import annotations

import asyncio
import multiprocessing as mp
import os
import time
from typing import Any


def _child(q: Any, opts: dict[str, Any], venues: tuple[str, ...]) -> None:
    import logging

    from .binance_sim import FakeBinance, default_symbols
    from .coinbase_sim import FakeCoinbase
    from .world import MarketWorld

    logging.getLogger("asyncio").setLevel(logging.ERROR)
    logging.getLogger("websockets").setLevel(logging.ERROR)

    async def main() -> None:
        world = MarketWorld(opts["seed"], synthetic_assets=opts["synthetic_assets"],
                            lag_ms={"BINANCE": 0.0, "COINBASE": opts["coinbase_lag_ms"]},
                            grid_epoch=opts.get("grid_epoch"))
        world.dislocation_rate_per_min = opts["dislocations_per_min"]
        ports = {}
        if "binance" in venues:
            bsyms = default_symbols(opts["binance_usdt_symbols"], world=world)
            b = FakeBinance(bsyms, world=world, seed=opts["seed"], updates_per_s=opts["binance_rate"],
                            host=opts["host"], port=opts["binance_port"])
            await b.start()
            ports["binance"] = b.port
        if "coinbase" in venues:
            c = FakeCoinbase(world, opts["coinbase_products"], seed=opts["seed"] + 1,
                             updates_per_s=opts["coinbase_rate"], host=opts["host"], port=opts["coinbase_port"])
            await c.start()
            ports["coinbase"] = c.port
        q.put(ports)
        await asyncio.Event().wait()

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass


class SimProcess:
    def __init__(self, updates_per_s: float = 2000.0, seed: int = 7, *, coinbase: bool = True,
                 coinbase_rate: float = 600.0, binance_usdt_symbols: int = 60, synthetic_assets: int = 0,
                 coinbase_lag_ms: float = 120.0, dislocations_per_min: float = 2.0,
                 coinbase_products: list[str] | None = None, split_venues: bool = False,
                 host: str = "127.0.0.1", binance_port: int = 0, coinbase_port: int = 0) -> None:
        self.opts = dict(binance_rate=updates_per_s, seed=seed, coinbase=coinbase, coinbase_rate=coinbase_rate,
                         binance_usdt_symbols=binance_usdt_symbols, synthetic_assets=synthetic_assets,
                         coinbase_lag_ms=coinbase_lag_ms, dislocations_per_min=dislocations_per_min,
                         coinbase_products=coinbase_products,
                         host=host, binance_port=binance_port, coinbase_port=coinbase_port)
        self.split_venues = split_venues and coinbase
        self.ports: dict[str, int] = {}
        self._procs: list[Any] = []

    def start(self, timeout: float = 60.0) -> None:
        ctx = mp.get_context("spawn")
        q = ctx.Queue()
        venues = ("binance", "coinbase") if self.opts["coinbase"] else ("binance",)
        groups = [(v,) for v in venues] if self.split_venues else [venues]
        opts = dict(self.opts)
        if self.split_venues:
            # CLOCK_MONOTONIC is system-wide on Linux, so children share the epoch.
            opts["grid_epoch"] = time.monotonic()
        for g in groups:
            p = ctx.Process(target=_child, args=(q, opts, g), name=f"sim-{'+'.join(g)}", daemon=True)
            p.start()
            self._procs.append(p)
        for _ in groups:
            self.ports.update(q.get(timeout=timeout))

    def url(self, venue: str, scheme: str = "ws") -> str:
        return f"{scheme}://{self.opts['host']}:{self.ports[venue]}"

    @property
    def ws_url(self) -> str:
        return self.url("binance")

    @property
    def rest_url(self) -> str:
        return self.url("binance", "http")

    @property
    def pid(self) -> int | None:
        return self._procs[0].pid if self._procs else None

    def cpu_seconds(self) -> float | None:
        """Total CPU seconds used by the simulator process(es)."""
        total = 0.0
        try:
            for p in self._procs:
                with open(f"/proc/{p.pid}/stat") as fh:
                    fields = fh.read().rsplit(")", 1)[1].split()
                total += (int(fields[11]) + int(fields[12])) / os.sysconf("SC_CLK_TCK")
        except (OSError, IndexError, ValueError):
            return None
        return total

    def stop(self) -> None:
        for p in self._procs:
            if p.is_alive():
                p.terminate()
                p.join(5)
        self._procs.clear()
