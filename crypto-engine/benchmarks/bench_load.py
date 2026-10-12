"""Load benchmark: the full system at 50 / 100 / 250 Binance symbols (SIMULATED DATA).

For each size N the synthetic Binance + Coinbase venues run in a separate OS
process (so their CPU use does not pollute the engine's measurements) and
stream over localhost WebSockets. The engine runs with every component
enabled - market state, order books, cross-exchange + triangular scanners,
feature grid, anomaly/pattern detectors, signal evaluation, paper trading,
risk and the in-memory audit sink - exactly as ``marketintel run`` builds it.

Reported per size: achieved frames/s per venue, per-stage latency
p50/p95/p99/max (engine instrumentation, microseconds), event-loop lag,
scheduler job durations, queue drops, engine CPU utilisation and health.

Localhost latency is NOT internet latency to Binance or Coinbase; these
numbers measure this process's processing cost only.

    python benchmarks/bench_load.py --sizes 50 100 250 --seconds 30 --out benchmarks/results-load.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import platform
import random
import resource
import time
from typing import Any

from marketintel.config import DataSource, Settings
from marketintel.persistence.sink import AuditSink
from marketintel.runtime import build_system
from marketintel.sim.coinbase_sim import default_products
from marketintel.sim.process import SimProcess
from marketintel.sim.world import SEED_VALUES, STABLES


def _cpu_s() -> float:
    r = resource.getrusage(resource.RUSAGE_SELF)
    return r.ru_utime + r.ru_stime


def _reset(eng: Any) -> None:
    """Drop warm-up samples so the reported histograms cover the measured window only."""
    for h in [*eng.metrics.all(), eng.loop_lag.hist]:
        h.lifetime.reset()
        h.current.reset()
        h.last.reset()


async def run_one(n: int, seconds: float, warmup: float, per_symbol_rate: float, cb_products: int) -> dict[str, Any]:
    real_bases = sum(1 for a in SEED_VALUES if a not in STABLES)
    synthetic = max(0, n - real_bases)
    # List only the real Coinbase products in the simulator (no synthetic ones): it spreads
    # updates over every listed product. Each venue runs in its own process (shared price path).
    cb_list = default_products(None)
    cb_listed = len(cb_list)
    sim = SimProcess(updates_per_s=per_symbol_rate * n, coinbase_rate=per_symbol_rate / 2 * cb_listed,
                     coinbase_products=cb_list, split_venues=True,
                     binance_usdt_symbols=n, synthetic_assets=synthetic, seed=5)
    await asyncio.to_thread(sim.start)
    s = Settings(data_source=DataSource.SIMULATED, api={"enabled": False}, persistence={"jsonl_dir": None})
    s.binance.ws_base_url, s.binance.rest_base_url = sim.url("binance"), sim.url("binance", "http")
    s.coinbase.ws_base_url, s.coinbase.rest_base_url = sim.url("coinbase"), sim.url("coinbase", "http")
    s.binance.max_symbols = n
    s.binance.min_symbols = min(50, n)
    s.coinbase.max_products = cb_products
    eng = await build_system(s, rng=random.Random(1), sink=AuditSink())
    await eng.start()
    try:
        t_ready = time.perf_counter()
        ready = await eng.wait_until(lambda: all(v["usable"] >= v["instruments"] > 0
                                                 for v in eng.health()["venues"].values()), warmup + 60)
        startup_s = time.perf_counter() - t_ready
        await asyncio.sleep(warmup)
        _reset(eng)
        f0, fv0, c0, t0 = eng.frames, dict(eng.frames_by_venue), _cpu_s(), time.perf_counter()
        sc0 = sim.cpu_seconds()
        await asyncio.sleep(seconds)
        dt = time.perf_counter() - t0
        cpu = _cpu_s() - c0
        sc1 = sim.cpu_seconds()
        h = eng.health()
        rep = eng.latency_report()
        diag = eng.diagnostics()
        return {
            "binance_symbols": n, "coinbase_products": cb_products, "coinbase_sim_listed": cb_listed, "synthetic_assets": synthetic,
            "all_instruments_usable": ready, "startup_to_all_usable_s": round(startup_s, 2),
            "connections": {v: (d["connections_up"], d["connections_total"]) for v, d in h["venues"].items()},
            "usable": {v: (d["usable"], d["instruments"]) for v, d in h["venues"].items()},
            "frames_per_s": round((eng.frames - f0) / dt, 1),
            "frames_per_s_by_venue": {v: round((c - fv0.get(v, 0)) / dt, 1) for v, c in eng.frames_by_venue.items()},
            "engine_cpu_utilisation": round(cpu / dt, 3),
            "simulator_cpu_utilisation": round((sc1 - sc0) / dt, 3) if sc0 is not None and sc1 is not None else None,
            "health": h["status"], "health_reasons": h["reasons"],
            "latency_us": {k: rep[k]["lifetime"] for k in rep if k.startswith("ingest.") and "lifetime" in rep[k]},
            "event_loop_lag_us": rep["event_loop_lag"]["lifetime"],
            "jobs_us": {k: rep[k]["lifetime"] for k in rep if k.startswith("job.") and "lifetime" in rep[k]},
            "queues": diag["queues"],
            "audit_dropped": eng.sink.dropped,
            "cross_exchange_pairs": len(eng.component("cross_exchange").pairs),
            "triangular_routes": len(eng.component("triangular").routes),
            "measured_window_s": round(dt, 2),
        }
    finally:
        await eng.stop()
        sim.stop()


async def main() -> None:
    logging.getLogger("marketintel").setLevel(logging.ERROR)  # shutdown chatter
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", type=int, nargs="+", default=[50, 100, 250])
    ap.add_argument("--seconds", type=float, default=30.0)
    ap.add_argument("--warmup", type=float, default=10.0)
    ap.add_argument("--per-symbol-rate", type=float, default=40.0, help="Binance updates/s per symbol")
    ap.add_argument("--coinbase-products", type=int, default=40)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    results = {"label": "SIMULATED DATA - localhost, processing cost only",
               "machine": {"python": platform.python_version(), "platform": platform.platform(),
                           "cpus": os.cpu_count()},
               "params": vars(args), "runs": []}
    for n in args.sizes:
        r = await run_one(n, args.seconds, args.warmup, args.per_symbol_rate, min(args.coinbase_products, n))
        results["runs"].append(r)
        lat = r["latency_us"]
        print(f"N={n:>4} usable={r["usable"]} fps={r["frames_per_s_by_venue"]} cpu={r["engine_cpu_utilisation"]:.2f} sim_cpu={r["simulator_cpu_utilisation"]} "
              f"health={r['health']} loop_lag_p99={r['event_loop_lag_us'].get('p99')}us", flush=True)
        for k, v in sorted(lat.items()):
            print(f"        {k:<44} p50={v['p50']} p95={v['p95']} p99={v['p99']} max={v['max']} n={v['count']}")
    if args.out:
        with open(args.out, "w") as fh:
            json.dump(results, fh, indent=2, default=str)


if __name__ == "__main__":
    asyncio.run(main())
