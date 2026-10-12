# HTTP API

Read-only monitoring API (FastAPI) served by `marketintel run` on
`api.host:api.port` (default `127.0.0.1:8080`). OpenAPI docs are at `/docs`.
Every market-data response includes `data_source`: `LIVE`, `SIMULATED` or
`REPLAY`. Handlers only read memory; nothing in the API can change engine
state or place orders.

Bind to `127.0.0.1` (the default) or put an authenticating reverse proxy in
front. The API has no authentication of its own.

| Method & path | Description |
|---|---|
| `GET /health` | Overall status (`STARTING`/`OK`/`DEGRADED`/`DOWN`), reasons, shards connected, symbol status counts, BTCUSDT status, last-frame age, frames/s, `observation_only: true`. |
| `GET /markets` | Market scanner rows. Query: `status=LIVE,QUIET` (filter), `sort=` one of `symbol, spread_bps, book_age_ms, book_updates, trades, touch_imbalance, tapped_quote_volume, status`, `desc=true`, `limit=1..5000`. |
| `GET /markets/{symbol}` | One market row plus the local order book (top 10 levels, sync state) if depth is enabled for the symbol. 404 if not monitored. |
| `GET /latency` | Per-stage latency (p50/p95/p99/max/mean, µs) for the last completed report window and lifetime, plus notes on clocks and clock-offset correction. |
| `GET /diagnostics` | Shard states (reconnects, stalls, rotations, delivery lag, last errors), connection-attempt limiter, queue depths and drops, invalid-frame counts by reason, order-book sync/gap/resync counts, REST weight usage, recorder stats. |
| `GET /metrics` | Prometheus text exposition (frames, shard status, symbols by status, invalid frames, queue depth and drops, latency quantiles). |

## Market row fields

| Field | Meaning |
|---|---|
| `status` | `LIVE`, `QUIET`, `STALE`, `CROSSED`, `ONE_SIDED`, `UNINITIALIZED`, `DISCONNECTED` (see ARCHITECTURE.md §4). Only `LIVE` (and `QUIET` if opted in) is usable. |
| `bid`, `bid_qty`, `ask`, `ask_qty`, `mid` | Best bid/offer from `@bookTicker`. Floats for display only; internally exact e8 integers. |
| `spread_bps` | (ask − bid) / mid × 10⁴ |
| `touch_imbalance` | (bidQty − askQty) / (bidQty + askQty) at the touch, in [−1, 1] |
| `depth_imbalance_10` | Same over the top 10 levels of the local book (depth symbols only, when `SYNCED`) |
| `book_age_ms`, `last_trade_age_ms` | Time since the last update was received (monotonic clock) |
| `out_of_order`, `trade_dups`, `trade_gaps`, `missed_trades`, `crossed_events`, `reconnects` | Data-quality counters |
| `filters_known` | Whether exchange filters (tick/step/min notional) were loaded from `exchangeInfo` |

## Example

```bash
$ curl -s localhost:8080/health
{"status":"OK","reasons":[],"data_source":"SIMULATED","observation_only":true,
 "shards_connected":2,"shards_total":2,"symbols_total":60,"symbols_usable":60,
 "reference_symbol":"BTCUSDT","reference_status":"LIVE","last_frame_age_ms":4.4, ...}
```

A live dashboard push channel (WebSocket or SSE) arrives with the dashboard
in Phase 7.
