# Status, limitations and production readiness

## Phase status

| Phase | Scope | Status |
|---|---|---|
| 1 | Requirements, assumptions, architecture, repository plan | **Done** (ARCHITECTURE.md) |
| 2 | Binance WebSocket ingestion, ≥ 50 symbols, BTCUSDT reference | **Done**, verified against a protocol-compatible simulator. **Live verification pending** (Binance blocked from the build environment; run `marketintel probe`). |
| 3 | Market-state cache, normalization, feed health, latency instrumentation | **Done** |
| 4 | Anomaly detection, cross-market calculations | Not started (design in STRATEGIES.md) |
| 5 | Fee-aware profitability engine, ranking | Not started |
| 6 | Historical replay, backtesting, paper trading | Raw-frame recorder and reader done (replay reproduces live state exactly); backtester and paper trading not started |
| 7 | Dashboard, API, diagnostics | Read-only API, diagnostics and Prometheus metrics done; React dashboard not started |
| 8 | Load tests, failure simulation, security review, optimisation | Failure simulation and load benchmarks done for ingestion; security review and transport optimisation pending |
| 9 | Deployment, production-readiness assessment | Dockerfile + compose done (image built and smoke-tested); assessment below |

## Definition-of-done items covered so far

* [x] Maintains connections and processes updates for ≥ 50 symbols. 60 by
  default; tested over real WebSockets against the simulator.
* [ ] Real BTCUSDT ingestion demonstrated. **Blocked here** by network
  policy. Run `marketintel probe --duration 30`; exit code 0 means every
  shard connected, ≥ 50 usable symbols and BTCUSDT live.
* [x] Recovers from network interruptions without silently using stale
  state (tests: TCP abort, stall, `serverShutdown`, 429, late data).
* [x] Rejects stale and invalid data (status model; invalid frames counted
  by reason).
* [x] Reports measured processing latency (API, logs, benchmarks).
* [x] Passes automated tests (94).
* [x] Runs with documented setup (README, Docker).
* [ ] Synthetic anomaly detection, cross-rate and triangular calculations,
  profitability, paper trading, dashboard (Phases 4–7).

## Known limitations

1. **Live Binance not verified from this environment.** Every Binance host
   was blocked by the sandbox's egress policy. All connectivity code follows
   the official docs and is exercised against a byte-compatible simulator,
   but real-world behaviour (actual message rates, real `serverShutdown`
   timing, proxy and geo restrictions, URL-length limits for large combined
   streams) still needs `marketintel probe` on a host with access.
2. **bookTicker has no event time** on Binance spot, so per-quote
   exchange→local delay cannot be measured. The shard-level delivery-lag
   estimate comes from trades and depth on the same connection.
3. **After a reconnect, illiquid symbols stay `UNINITIALIZED`** until their
   book changes. This is deliberately conservative: the REST `bookTicker`
   endpoint has no update id that could seed state safely.
4. **Local books only for configured depth symbols** (default 2). Others
   have top-of-book only, so size-aware slippage (Phase 5) will be limited to
   the touch for them.
5. **Clock-offset uncertainty** is ± RTT/2 of the best recent `/time`
   sample. It is reported, and negative lags are counted.
6. **Single process.** Measured ceiling is about 14–16k frames/s on the
   test host (BENCHMARKS.md). Beyond that, shard across processes or switch
   to the faster transport.
7. **The API has no authentication.** It binds to localhost by default.
8. Recording writes gzip TSV locally with no rotation or retention policy
   yet.

## Production-readiness checklist

| Item | State |
|---|---|
| Typed, validated configuration; secrets only via env | ✅ |
| Live trading impossible by configuration | ✅ |
| Structured JSON logs; secret redaction | ✅ |
| Health endpoint with reasons; Prometheus metrics | ✅ |
| Container image runs as non-root, has a healthcheck, binds localhost by default | ✅ (built and run here; CA workaround needed only inside this sandbox) |
| CI running tests on 3.12 / 3.13 | ✅ (`.github/workflows/crypto-engine.yml`) |
| Reconnect/backoff/limiter/rotation per exchange limits | ✅ tested against simulator |
| Live connectivity probe on target host | ⏳ run `marketintel probe` |
| Alerting on `DEGRADED`/`DOWN` (Prometheus rules / pager) | ⏳ not configured |
| Recording rotation and retention | ⏳ |
| API authentication or reverse proxy | ⏳ |
| Load test against real peak message rates | ⏳ needs live data |
| Security review (dependencies, container, API surface) | ⏳ Phase 8 |
| Execution controls (RISK_MANAGEMENT.md) | ⏳ Phases 6–9; required before any order |
