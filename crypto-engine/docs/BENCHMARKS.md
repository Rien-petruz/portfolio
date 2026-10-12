# Benchmarks

All numbers below were **measured** on the development container: 4 vCPU
Intel Xeon @ 2.80 GHz, Python 3.13.16, Linux, shared and virtualised (expect
noisy tails). They describe this engine on this machine. They are **not**
internet latency to Binance, which could not be measured here (see
"Limitations").

## Methodology

Three benchmarks isolate different costs:

1. **Hot path** (`benchmarks/bench_hotpath.py`): pre-serialised
   Binance-format frames are fed straight into `Engine.on_frame`. No sockets
   are involved. The frames come from the simulator's book model and include
   a heavy depth mix (34 % depth diffs of ~40 levels each), so this is a
   pessimistic load. The latencies are the engine's own histograms.
2. **End to end** (`benchmarks/bench_e2e.py`): the synthetic exchange runs
   in a **separate process** and streams to the engine over localhost
   WebSockets (69 symbols, 2 shards, bookTicker + trade for all, depth for
   BTCUSDT/ETHUSDT). After 3 s of warm-up we measure 12 s at each target
   rate. CPU per process comes from `process_time()` (engine) and
   `/proc/<pid>/stat` (simulator).
3. **Transport only** (`benchmarks/bench_ws_clients.py`): the same stream
   with a frame handler that only counts. This isolates WebSocket client,
   asyncio and syscall cost.

Percentiles come from HDR-style histograms (≤ 3.2 % relative error, verified
against NumPy in `tests/test_metrics.py`). Units are microseconds.

## 1. Hot path

| Run | Throughput (1 core) | recv→normalized p50 / p95 / p99 | recv→state+publish p50 / p95 / p99 |
|---|---|---|---|
| before decimal fast path | 32.2k frames/s | 8.7 / 79.9 / 159.7 | 12.8 / 86.0 / 167.9 |
| after decimal fast path | 41–50k frames/s | 6.4–8.4 / 45–54 / 98–111 | 11–14 / 51–63 / 110–125 |

cProfile showed `parse_e8` (regex validation) taking about 55 % of hot-path
time on depth-heavy input. An exact fast path for the canonical
`digits.8digits` format halved its cost. The range reflects run-to-run noise
on the shared host.

GC tuning was tested (`gc.freeze()` plus a higher gen-0 threshold). Only
about 50 young collections happen per 200k frames, and tuning changed
nothing measurable, so it was **not** adopted. The rare 5–90 ms maxima appear
with and without GC tuning and are attributed to host scheduling noise.

## 2. End to end (localhost, simulator in a separate process)

| Target updates/s | Achieved frames/s | Engine CPU (one core) | Engine CPU/frame | Simulator CPU | Health |
|---|---|---|---|---|---|
| 1,000 | 1,372 | 12.9 % | 94 µs | 19 % | OK |
| 3,000 | 4,068 | 30.7 % | 75 µs | 40 % | OK |
| 8,000 | 10,788 | 66.4 % | 62 µs | 77 % | OK |
| 20,000 | 13,857 | 89.3 % | 64 µs | 98.5 % (saturated) | **DEGRADED**: all quotes STALE, delivery lag > 2 s |

Per-stage latency (µs):

| Target | recv→state p50 / p99 | recv→quote consumer p50 / p99 | recv→trade consumer p50 / p99 | exchange E→recv (trade) p50 / p99 | loop lag p50 / p99 |
|---|---|---|---|---|---|
| 1,000 | 18 / 180 | 88 / 467 | 115 / 508 | 3,932 / 6,947 | 770 / 2,687 |
| 3,000 | 17 / 109 | 70 / 688 | 96 / 754 | 4,719 / 15,204 | 688 / 13,107 |
| 8,000 | 15 / 78 | 59 / 803 | 80 / 999 | 17,302 / 69,206 | 279 / 2,163 |
| 20,000 | 16 / 74 | 60 / 786 | 84 / 967 | 2,013,266 / 6,024,052 | 225 / 3,539 |

Raw results: `benchmarks/results-e2e.json`.

How to read this:

* **The engine's own processing latency stays flat** as load grows
  (recv→state p99 ≈ 75–180 µs). There were no trade-queue drops at any rate.
  Quote conflation stayed around 2 %.
* **exchange E→recv** in this setup is mostly the simulator: it stamps `E`
  per 10 ms generation step and then serialises and sends from a single
  Python process. At 20k/s the simulator saturates (98.5 % CPU) and its send
  backlog reaches seconds. The engine **correctly** flags this: delivery lag
  above `max_delivery_lag_ms` turns every quote `STALE` and health
  `DEGRADED`. Before this check was added, the same run reported `OK`. The
  benchmark found the gap, and the integration test
  `test_late_data_is_stale_and_degrades_health` now guards it.
* **Loop lag** p50 of 0.2–0.8 ms is mostly timer granularity; it shrinks as
  load rises because the loop wakes more often. Occasional p99 spikes match
  host noise.
* CPU per frame *falls* as load rises because each loop wake-up and recv
  syscall carries more frames.

## 3. Where the CPU goes

Same stream (~10.8k frames/s), with the engine's frame handler replaced by a
counter versus the full pipeline:

| Configuration | Engine CPU | CPU per frame |
|---|---|---|
| `websockets` + no-op handler | 52–56 % | 49–52 µs |
| `websockets` + full engine | 62–66 % | 58–61 µs |

So **~85 % of per-frame CPU is the receive path** (WebSocket client, asyncio,
syscalls), and only ~9–12 µs is ours. Transport alternatives, receive-only:

| Client | CPU per frame |
|---|---|
| `websockets` 17.2 | 46–48 µs |
| `aiohttp` 3.14 | 40 µs |
| `picows` 2.3 (Cython) | 26–28 µs |

Even the fastest client spends ~27 µs per frame, so much of the cost is
per-wake-up syscall and scheduling overhead in this virtualised container,
not Python framing. Switching to `picows` would raise single-process capacity
by roughly 1.5×. It is the documented Phase 8 option if live load requires it
(the transport is isolated in `Shard`). Multi-process sharding scales roughly
linearly and needs no new dependency.

## 4. Capacity and operating point

* **Measured ceiling:** about 14–16k frames/s per engine process on this
  host (~90 % of one core).
* **Recommended operating point:** ≤ 60 % of one core, about 10k frames/s per
  process, which leaves headroom for Phase 4 strategy work. Beyond that, run
  additional processes with disjoint symbol sets.
* **Expected live load for 60 symbols** (bookTicker + trade): not measured
  here (Binance unreachable). `marketintel probe` reports `frames_per_s` and
  all latency stages on a host with access. Run it during volatile periods
  before committing to a process layout.

## 5. Limitations

* **No live measurements.** This environment's network policy blocks every
  Binance host (`api.binance.com`, `stream.binance.com`,
  `data-api.binance.vision`, `data-stream.binance.vision`). Live
  exchange→local latency, real message rates and real gap/duplicate
  frequencies are still to be measured with `marketintel probe`.
* The simulator's message mix and burstiness are synthetic and reflect no
  real market microstructure.
* Results come from a shared virtualised host. Tails (max) are noisy and
  should not be compared across runs.

## Reproduce

```bash
pip install -e ".[dev]"
python benchmarks/bench_hotpath.py [--profile]
python benchmarks/bench_e2e.py --rates 1000 3000 8000 20000 --seconds 12 --json out.json
pip install aiohttp picows && python benchmarks/bench_ws_clients.py picows
```
