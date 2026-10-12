"""End-to-end benchmark over real localhost WebSockets.

The synthetic exchange runs in a separate process (so its CPU use does not
pollute the engine's measurements) and streams Binance-format frames for 69
symbols. For each target update rate the engine runs for ``--seconds`` after
a warm-up, then we report achieved frames/s, per-stage latency percentiles,
event-loop lag, queue drops and health.

Exchange->receive latency here is localhost + simulator batching (it emits in
10 ms steps), NOT internet latency to Binance.

    python benchmarks/bench_e2e.py --rates 2000 10000 20000 --seconds 15
"""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import time

from marketintel.clock import NS_PER_S, mono_ns
from marketintel.config import DataSource, Settings
from marketintel.engine import Engine, resolve_universe
from marketintel.exchange.binance.rest import BinanceRest
from marketintel.sim.process import SimProcess


async def run_one(rate: float, seconds: float, warmup: float) -> dict:
    sim = SimProcess(updates_per_s=rate, seed=5)
    await asyncio.to_thread(sim.start)
    s = Settings(data_source=DataSource.SIMULATED, api={"enabled": False},
                 universe={"max_symbols": 69, "depth_symbols": ["BTCUSDT", "ETHUSDT"]},
                 engine={"report_interval_s": 3600})
    s.binance.ws_base_url = sim.ws_url
    s.binance.rest_base_url = sim.rest_url
    rest = BinanceRest(sim.rest_url)
    eng = Engine(s, await resolve_universe(s, rest), rest=rest)
    await eng.start()
    try:
        await asyncio.sleep(warmup)
        lats = eng._latencies() + [eng.loop_lag.hist]
        for h in lats:
            h.roll()
        f0, t0 = eng.frames, mono_ns()
        c0, sc0 = time.process_time(), sim.cpu_seconds()
        await asyncio.sleep(seconds)
        f1, t1 = eng.frames, mono_ns()
        c1, sc1 = time.process_time(), sim.cpu_seconds()
        wall_s = (t1 - t0) / NS_PER_S
        for h in lats:
            h.roll()
        health = eng.health()
        out = {
            "target_updates_per_s": rate,
            "symbols": len(eng.state.symbols),
            "shards": len(eng.shards),
            "frames_per_s": round((f1 - f0) / wall_s),
            # Share of one core used by each process during the measurement.
            "engine_cpu_pct": round(100 * (c1 - c0) / wall_s, 1),
            "simulator_cpu_pct": round(100 * (sc1 - sc0) / wall_s, 1) if sc0 is not None and sc1 is not None else None,
            "engine_cpu_us_per_frame": round(1e6 * (c1 - c0) / max(1, f1 - f0), 1),
            "latency_us": {h.name: h.summary()["window"] for h in lats},
            "quote_conflated_pct": round(100 * eng.quote_queue.conflated / max(1, eng.quote_queue.published), 1),
            "trade_queue_dropped": eng.trade_queue.dropped,
            "invalid": dict(eng.invalid),
            "health": health["status"],
            "health_reasons": health["reasons"],
            "status_counts": {k: v for k, v in health["status_counts"].items() if v},
        }
    finally:
        await eng.stop()
        await rest.close()
        sim.stop()
    return out


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rates", type=float, nargs="+", default=[2000, 10000, 20000])
    ap.add_argument("--seconds", type=float, default=15)
    ap.add_argument("--warmup", type=float, default=3)
    ap.add_argument("--json", help="write results to this file")
    args = ap.parse_args()
    results = []
    for r in args.rates:
        res = await run_one(r, args.seconds, args.warmup)
        results.append(res)
        lat = res["latency_us"]
        print(f"\n=== target {r:,.0f} updates/s -> {res['frames_per_s']:,} frames/s "
              f"({res['symbols']} symbols, {res['shards']} shards), health={res['health']} {res['health_reasons']}")
        print(f"  CPU (% of one core): engine {res['engine_cpu_pct']}% "
              f"({res['engine_cpu_us_per_frame']} us/frame), simulator {res['simulator_cpu_pct']}%")
        for k in ("recv_to_normalized", "recv_to_state_applied", "recv_to_quote_consumer",
                  "recv_to_trade_consumer", "exchange_event_to_recv_trade", "event_loop_lag"):
            v = lat[k]
            print(f"  {k:32s} p50={v['p50']!s:>8} p95={v['p95']!s:>8} p99={v['p99']!s:>8} max={v['max']!s:>9}  n={v['count']}")
        print(f"  quote conflation {res['quote_conflated_pct']}%  trade drops {res['trade_queue_dropped']}  invalid {res['invalid']}")
    meta = {"python": platform.python_version(), "machine": platform.machine(), "cpus": __import__("os").cpu_count()}
    if args.json:
        with open(args.json, "w") as fh:
            json.dump({"meta": meta, "results": results}, fh, indent=2)


if __name__ == "__main__":
    asyncio.run(main())
