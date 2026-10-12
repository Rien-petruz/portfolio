"""Run the synthetic exchange in a separate OS process.

Generating and serialising thousands of synthetic events per second is CPU
work; running it on the engine's event loop would inflate the engine's own
latency measurements. Benchmarks and ``marketintel run --simulate`` therefore
host the simulator in a child process and talk to it over localhost TCP,
exactly as they would talk to Binance.
"""

from __future__ import annotations

import asyncio
import multiprocessing as mp
from typing import Any


def _child(q: Any, port: int, updates_per_s: float, seed: int) -> None:
    import logging

    from .fake_exchange import FakeBinance

    # Broadcasting to sockets the engine has just closed is expected at shutdown.
    logging.getLogger("asyncio").setLevel(logging.ERROR)
    logging.getLogger("websockets").setLevel(logging.ERROR)

    async def main() -> None:
        sim = FakeBinance(port=port, updates_per_s=updates_per_s, seed=seed)
        await sim.start()
        q.put(sim.port)
        await asyncio.Event().wait()

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass


class SimProcess:
    def __init__(self, updates_per_s: float = 2000.0, seed: int = 7, port: int = 0) -> None:
        self.updates_per_s = updates_per_s
        self.seed = seed
        self.port = port
        self._proc: Any = None

    def start(self, timeout: float = 30.0) -> None:
        ctx = mp.get_context("spawn")
        q = ctx.Queue()
        self._proc = ctx.Process(target=_child, args=(q, self.port, self.updates_per_s, self.seed),
                                 name="fake-binance", daemon=True)
        self._proc.start()
        self.port = q.get(timeout=timeout)

    @property
    def ws_url(self) -> str:
        return f"ws://127.0.0.1:{self.port}"

    @property
    def rest_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def pid(self) -> int | None:
        return self._proc.pid if self._proc is not None else None

    def cpu_seconds(self) -> float | None:
        """User+system CPU time of the simulator process (Linux /proc)."""
        try:
            with open(f"/proc/{self.pid}/stat") as fh:
                fields = fh.read().rsplit(")", 1)[1].split()
            import os
            return (int(fields[11]) + int(fields[12])) / os.sysconf("SC_CLK_TCK")
        except (OSError, IndexError, ValueError):
            return None

    def stop(self) -> None:
        if self._proc is not None and self._proc.is_alive():
            self._proc.terminate()
            self._proc.join(5)
