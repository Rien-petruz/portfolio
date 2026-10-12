# Market Intelligence Engine (crypto)

A real-time market-data engine for Binance spot. It ingests 50+ symbols over
multiplexed WebSocket streams, keeps a validated in-memory market state plus
local L2 order books, and measures its own latency at every stage.

**Status: Phases 1–3 of 9 implemented** (architecture, ingestion, market
state, feed health, latency instrumentation). Strategy detection,
profitability, backtesting, paper trading and the dashboard are **not built
yet**; see [docs/STATUS.md](docs/STATUS.md). The engine is
**observation-only**: it contains no order-placement code, and the config
rejects `live_trading_enabled = true`.

> Nothing here promises profit. Most apparent price discrepancies come from
> asynchronous feeds, spreads, fees or thin liquidity. Later phases are built
> to tell those apart from executable edge.

## What works today

| Capability | Where |
|---|---|
| Symbol discovery from `exchangeInfo`, liquidity ranking via `ticker/24hr`, required cross-pair legs, offline fallback list | `exchange/binance/symbols.py`, `engine.resolve_universe` |
| Combined-stream WebSockets sharded by symbol (default 40 symbols / ≤200 streams per socket; Binance limit 1024) | `exchange/binance/streams.py` |
| Reconnect with exponential backoff and jitter, a per-IP connection-attempt limiter (Binance: 300 / 5 min), longer back-off on 429/418 | `exchange/binance/ws.py`, `ratelimit.py` |
| Make-before-break rotation before the 24 h limit and on `serverShutdown`, with zero lost trades across a rotation (tested) | `ws.py` |
| Stall watchdog (silent socket → recycled) | `ws.py` |
| Exact fixed-point parsing (e8 integers), exchange filter validation (tick, step, min notional) | `numeric.py`, `symbols.py` |
| Normalized event schema with monotonic and wall receive timestamps | `ingestion/` |
| Latest-state cache with explicit quote status: `LIVE`, `QUIET`, `STALE`, `CROSSED`, `ONE_SIDED`, `UNINITIALIZED`, `DISCONNECTED` | `state/market_state.py` |
| Out-of-order and duplicate rejection, trade-gap counting, crossed-book detection | `state/market_state.py` |
| Local order books following Binance's documented snapshot + diff procedure, with gap-triggered resync | `state/order_book.py` |
| Non-blocking fan-out: conflating queue for quotes, bounded drop-oldest queue for trades | `ingestion/bus.py` |
| HDR-style latency histograms (p50/p95/p99/max) per stage, event-loop lag, health aggregation | `metrics/`, `engine.py` |
| Read-only HTTP API (`/health`, `/markets`, `/latency`, `/diagnostics`, `/metrics`) | `api/app.py` |
| Raw-frame recorder and reader; replay reproduces the exact live state (tested) | `persistence/recorder.py` |
| Local Binance-protocol simulator with fault injection (synthetic data, always labeled `SIMULATED`) | `sim/` |

## Quick start

Requires Python ≥ 3.12.

```bash
cd crypto-engine
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"

# 1) Verify live Binance connectivity, coverage and latency (30 s; needs internet access to Binance)
marketintel probe --duration 30          # exit code 0 = all shards up, >=50 usable symbols, BTCUSDT live

# 2) Run against live Binance with the API on http://127.0.0.1:8080
marketintel run

# 3) No Binance access? Run against the local synthetic exchange (child process)
marketintel run --simulate --duration 60
```

Then:

```bash
curl -s localhost:8080/health | jq
curl -s 'localhost:8080/markets?status=LIVE&sort=spread_bps&desc=true&limit=10' | jq
curl -s localhost:8080/markets/BTCUSDT | jq
curl -s localhost:8080/latency | jq
```

If `api.binance.com` / `stream.binance.com` are blocked in your region or
network, try the market-data-only hosts:

```bash
MIE_BINANCE__WS_BASE_URL=wss://data-stream.binance.vision \
MIE_BINANCE__REST_BASE_URL=https://data-api.binance.vision marketintel probe
```

### Configuration

All settings live in `config.py` (typed, validated with Pydantic). Configuration
is layered: defaults, then a TOML file (`--config` or `MIE_CONFIG_FILE`), then
environment variables (`MIE_<SECTION>__<KEY>`). See
[`config/engine.example.toml`](config/engine.example.toml) and
[`.env.example`](.env.example). Public market data needs no credentials. The
engine refuses to label data `LIVE` unless it comes from a `*.binance.com` or
`*.binance.vision` host.

### Docker

```bash
docker compose up --build engine                 # live data, API on 127.0.0.1:8080
docker compose --profile sim up --build          # synthetic exchange + engine, API on 127.0.0.1:8081
```

### Tests

```bash
python -m pytest -q          # 94 tests, ~20 s; no network needed
MIE_LIVE_TESTS=1 python -m pytest -q -m live   # optional: real Binance connectivity
```

The tests cover parsing, decimal precision and exchange filters, event
ordering, staleness, crossed books, order-book synchronisation (including a
property-based test against a reference model), latency-histogram accuracy,
rate limiting and backoff, configuration, the API, overload behaviour, and
end-to-end WebSocket failure scenarios against the simulator: network drop,
`serverShutdown`, max-age rotation, stalled feed, HTTP 429 on handshake,
invalid frames, trade and depth gaps, and message-based subscription. A
record → replay test checks that replay reproduces live state exactly.

### Benchmarks

```bash
python benchmarks/bench_hotpath.py            # parse + state + publish, no network
python benchmarks/bench_e2e.py --rates 1000 3000 8000 20000
python benchmarks/bench_ws_clients.py websockets
```

Methodology, results and caveats are in [docs/BENCHMARKS.md](docs/BENCHMARKS.md).

## Documentation

* [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): pipeline, concurrency model, data-quality model, key decisions
* [docs/STRATEGIES.md](docs/STRATEGIES.md): planned detection strategies and their validation rules (Phase 4+)
* [docs/RISK_MANAGEMENT.md](docs/RISK_MANAGEMENT.md): safety model and the controls required before any execution
* [docs/API.md](docs/API.md): HTTP endpoints
* [docs/BENCHMARKS.md](docs/BENCHMARKS.md): measured performance and methodology
* [docs/STATUS.md](docs/STATUS.md): phase status, known limitations, production-readiness checklist

## Layout

```
crypto-engine/
├── src/marketintel/
│   ├── config.py               typed configuration + safety validation
│   ├── clock.py, numeric.py    clocks; exact e8 fixed-point
│   ├── ratelimit.py            connection-attempt limiter, backoff
│   ├── exchange/binance/       REST metadata, symbols/filters, stream sharding, WebSocket shards
│   ├── ingestion/              event schema, normalizer, non-blocking bus
│   ├── state/                  market-state cache, local order books
│   ├── metrics/                latency histograms, event-loop lag
│   ├── persistence/            raw-frame recorder/reader
│   ├── api/                    FastAPI monitoring endpoints
│   ├── sim/                    synthetic Binance-protocol exchange (tests, demos, benchmarks)
│   ├── engine.py               wiring, consumers, health
│   └── cli.py                  run / probe / sim-server
├── tests/                      unit, property-based, integration, overload
├── benchmarks/                 hot-path, end-to-end, WebSocket-client benchmarks
├── config/                     example configuration
├── deploy/Dockerfile
└── docker-compose.yml
```
