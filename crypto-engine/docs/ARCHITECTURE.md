# Architecture

## 1. Requirements and assumptions (Phase 1)

**Goal of Phases 1–3:** a correct, measurable market-data foundation. Later
phases add strategies, profitability, replay and paper trading on top. They
can only be as good as the data they receive, so this phase puts correctness
and observability ahead of features.

Assumptions:

* **Venue:** Binance spot, public market data only. No credentials are
  needed, and none are handled.
* **Universe:** 50–60 symbols by default (configurable). BTCUSDT is the
  reference market. Cross-pair legs (ETHBTC, BNBBTC, BTCUSDC, USDCUSDT, …)
  are always included because Phase 4's cross-rate and triangular checks
  need them.
* **Streams per symbol:** `@bookTicker` (best bid/ask, real time) and
  `@trade` (every trade). `@depth@100ms` only for configured symbols
  (default BTCUSDT and ETHUSDT), because each local book costs a REST
  snapshot (request weight) and CPU.
* **Single host, single process.** The measured headroom (BENCHMARKS.md)
  covers expected load for 60 symbols. Scale-out is by sharding symbols
  across processes; no message broker is needed yet.
* **Time:** Binance sends `E`/`T` in milliseconds. Local timing uses
  nanosecond clocks.

Non-goals for this phase: signals, order placement, persistence beyond
optional raw-frame recording, dashboard UI.

## 2. Pipeline

```
                 ┌──────────────── one asyncio event loop (one process) ─────────────────┐
 Binance WSS ──► │ Shard 0 reader ─┐                                                     │
 (combined       │ Shard 1 reader ─┼─► on_frame (sync, hot path):                        │
  streams)       │   ...           │    orjson → Normalizer → MarketState / LocalOrderBook │
                 │                 │    → EventBus.publish (O(1), never awaits)          │
                 │                 │                 │                    │              │
                 │                 │      ConflatingQueue (quotes)  DropOldestQueue      │
                 │                 │                 │               (trades, bounded)   │
                 │                 │                 ▼                    ▼              │
                 │                 │      quote consumers           trade consumers      │
                 │                 │      (Phase 4 strategies)      (flow features)      │
                 │                                                                       │
                 │ side tasks: watchdogs · depth snapshots (REST) · clock-offset sampler │
                 │             loop-lag monitor · reporter · read-only HTTP API          │
                 └───────────────────────────────────────────────────────────────────────┘
```

### Hot path

Each shard's reader awaits `ws.recv()`, timestamps the frame immediately
(`monotonic_ns` and `time_ns`), and calls `Engine.on_frame` synchronously:

1. `orjson.loads` on the raw bytes. Frames are not decoded to `str`.
2. Normalize to a slotted dataclass. Prices and quantities are parsed into
   exact e8 integers, with a fast path for Binance's canonical
   `"123.45678900"` format.
3. Apply to the in-memory state in place: ordering checks, crossed-book
   detection, trade-gap counting.
4. Publish to the bus: O(1) per subscriber, never awaits.
5. Record per-stage latency into fixed-memory histograms.

No network I/O, disk I/O or locks happen on this path. Anything slower
belongs in a consumer.

### Why consumers use two different queue types

| Queue | Used for | When the consumer falls behind |
|---|---|---|
| `ConflatingQueue` | quote-driven logic (scanners, cross-rate checks) | Holds one entry per dirty symbol. The consumer reads the *current* state, so stale intermediate quotes are never processed. Memory is bounded by the symbol count. |
| `DropOldestQueue` | trade-sequence logic (volume, aggressor flow) | Fixed capacity. The oldest events are dropped and **counted**; drops degrade health. |

Ingestion never waits for a consumer. Each mode loses something different
(intermediate quotes vs. old trades), and both losses are measured, not
hidden.

### Concurrency model

* **One event loop** for I/O and the hot path. Hot-path work per frame is
  about 10–20 µs (measured), far below the inter-arrival time at our load.
* **CPU-heavy work** (Phase 4+ feature windows, model scoring) goes to
  consumer tasks that drain queues in batches. If profiling shows they hold
  the loop for too long, they move to a separate process fed with state
  snapshots. Event-loop lag is monitored continuously so this shows up as a
  measurement, not a guess.
* **Horizontal scale:** shards are independent. Running N processes with
  disjoint symbol sets multiplies capacity without shared state, because no
  strategy needs cross-process quotes within one tick.
* The **HTTP API** runs on the same loop. Its handlers only read memory
  (microseconds); none perform I/O.

## 3. Connectivity (exchange/binance/ws.py)

* **Sharding by symbol.** All streams of a symbol live on one connection,
  so a disconnect invalidates the whole symbol at once. Defaults: 40 symbols
  or 200 streams per connection (Binance allows 1024). For 60 symbols this
  gives 2 sockets instead of 120.
* **Subscription:** streams listed in the combined-stream URL (no control
  messages, so no exposure to the 5-messages/second inbound limit). Optional
  `message` mode sends paced `SUBSCRIBE` batches at ≤ 4 msg/s.
* **Reconnect:** exponential backoff with "equal jitter" (delay ∈ [d/2, d],
  d = min(cap, base·2ⁿ)). Attempts reset only after a connection has stayed
  up for `stable_after_s`, so a flapping endpoint keeps backing off. A
  process-wide sliding-window limiter enforces Binance's connection-attempt
  limit (default budget 200 per 5 min, against an exchange limit of 300). An
  HTTP 429/418 handshake response triggers `max(backoff, Retry-After,
  rate_limited_min_s)`.
* **Liveness:** the library answers server pings. A watchdog recycles any
  socket silent for `connection_stall_ms`.
* **Rotation (make-before-break):** at `connection_max_age_s` (default 23 h;
  Binance cuts at 24 h) or on a `serverShutdown` event, the shard opens a
  second socket. It closes the old one only after the new one delivers data.
  Both sockets carry identical streams during the overlap, and duplicates are
  dropped downstream by update/trade id. The integration test checks that
  zero trades are lost across repeated rotations.
* **Down = invalid, immediately.** When the last live socket of a shard
  closes, `on_down` runs synchronously. Every symbol on the shard becomes
  `DISCONNECTED` and its local order books are discarded. After a reconnect,
  each symbol stays `UNINITIALIZED` until a fresh update arrives.

## 4. Data-quality model (state/market_state.py, state/order_book.py)

Quote status is **computed on read** from timestamps and connection state,
so validity cannot go stale because nobody re-evaluated it:

| Status | Meaning | Usable? |
|---|---|---|
| `LIVE` | updated within `quiet_after_ms` on a healthy shard | yes |
| `QUIET` | healthy shard, book unchanged for > `quiet_after_ms`. bookTicker only publishes on change, so this is normal for illiquid pairs. | only if a consumer opts in (`allow_quiet`) |
| `STALE` | no update for `stale_after_ms`, or the shard has been silent > `connection_stall_ms`, or the shard's delivery lag > `max_delivery_lag_ms` | no |
| `CROSSED` | bid ≥ ask | no |
| `ONE_SIDED` | a side is empty | no |
| `UNINITIALIZED` | no update since (re)connect | no |
| `DISCONNECTED` | shard down | no |

Sequencing rules (from the Binance docs):

* **bookTicker `u`** is the book update id: increasing but not contiguous.
  `u ≤ last` means a duplicate or out-of-order frame, which is dropped and
  counted.
* **Trade ids** are contiguous per symbol. A jump counts as a gap, and the
  missed-trade count is exposed. A repeat is dropped as a duplicate.
* **Depth diffs** follow the documented local-book procedure: buffer, fetch a
  REST snapshot, discard `u ≤ lastUpdateId`, require the first event to
  bridge the snapshot, then require `U = previous u + 1`. Any gap discards
  the book and resyncs from a new snapshot, off the hot path. A crossed local
  book is treated as corruption and resynced. A book is readable only when
  `SYNCED`.
* **Delivery lag:** for every trade and depth event,
  `local_wall + clock_offset − E` feeds a per-shard EWMA. `clock_offset`
  comes from `/api/v3/time` midpoint sampling (lowest of the recent RTTs).
  Data that arrives seconds late describes a market that no longer exists,
  so it is `STALE`.

The engine never concludes that the exchange "mispriced" anything. This
phase only establishes whether a quote is trustworthy as a *description of
the current market*. Separating dislocations from noise and from executable
edge is Phase 4–5 work (see STRATEGIES.md).

## 5. Time and latency measurement

| Measurement | Clock | What it includes |
|---|---|---|
| `recv_to_normalized` | monotonic | JSON parse + normalization |
| `recv_to_state_applied` | monotonic | above + state/book update + publish |
| `recv_to_quote_consumer` / `recv_to_trade_consumer` | monotonic | above + queueing + scheduling until a consumer handles it (end-to-end inside the process) |
| `exchange_event_to_recv_*` | wall vs exchange `E` | exchange batching + network + kernel + library buffering + clock-offset error (± RTT/2, reported) |
| `event_loop_lag` | monotonic | how late a 50 ms timer fires: the overload signal |

"recv" is when the WebSocket library hands us the frame. Time spent in
kernel buffers or the library's queue *before* that is invisible to the
monotonic measurements. It does appear in `exchange_event_to_recv_*`, which
is why both are reported. Order-execution latency does not exist yet (no
execution). Percentiles come from HDR-style log-linear histograms with
≤ 3.2 % relative error (tested against NumPy).

## 6. Health

`Engine.health()` aggregates the following:

* `DOWN`: no shard connected.
* `DEGRADED`, with explicit reasons: any of
  * a shard is disconnected;
  * BTCUSDT is not `LIVE` or `QUIET`;
  * fewer than `min_symbols` usable symbols;
  * event-loop lag p99 or current lag above threshold;
  * trade-queue drops;
  * recorder drops;
  * late delivery.
* `STARTING` / `OK` otherwise.

Phase 4+ strategies must not emit actionable signals unless health is `OK`
and their inputs are `LIVE`.

## 7. Key decisions

| Decision | Alternatives considered | Reason |
|---|---|---|
| Python 3.12+, asyncio, single process | Rust/C++ core; multi-process from day one | The measured hot path (~10–20 µs/frame) leaves large headroom at expected load. Profiling showed receive overhead dominates (§8), so rewriting the core first would optimise the wrong thing. |
| `websockets` client | `aiohttp` (−17 % CPU/frame), `picows` (−42 %) | Mature, supports HTTP proxies and correct close/ping semantics. Measured savings from alternatives are real but not decisive. The transport sits behind one class (`Shard`) and can be swapped in Phase 8 if load requires it. |
| Exact e8 integers | `Decimal`, floats | Exact, hashable and fast. Exchange filters are checked with integer arithmetic. Floats appear only in display and statistics. |
| Conflation for quotes, bounded drop-oldest for trades | unbounded queues; backpressure on ingestion | Unbounded queues hide overload until memory runs out. Backpressure on ingestion makes the exchange see a slow client and eventually disconnect it. |
| Status computed on read | periodic sweeper marking stale | No window in which a sweeper has not run yet. Cheap (a few comparisons). |
| No database, Redis or broker in this phase | PostgreSQL / Redis / Kafka | Nothing here needs durable or shared state. Raw-frame recording to gzip TSV covers replay. PostgreSQL arrives with paper trading and audit logs (Phase 6). |
| Raw frames recorded, not normalized events | store normalized events | Replay then exercises exactly the live normalizer and state code (test: replay ⇒ identical state). |
| Local Binance-protocol simulator | mocking the client library | Tests run real sockets, real framing and real failure modes (TCP abort, 429 handshakes, `serverShutdown`, stalls) without internet access. |

## 8. Where the time goes (summary of BENCHMARKS.md)

At about 10.8k frames/s from the out-of-process simulator, the engine uses
about 62–66 % of one core:

* about 50 µs CPU per frame in the WebSocket client, asyncio and syscalls
  (measured with a no-op frame handler);
* about 9–12 µs CPU per frame for everything we do (parse, state, books,
  metrics, consumers).

Practical ceiling: ~14–16k frames/s per process on this 2.8 GHz Xeon
container. Beyond that, shard across processes or switch transport (§7).
