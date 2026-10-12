# Risk management

## Current state (Phases 1–3)

* **Observation-only.** The codebase contains no order-placement code and no
  authenticated API client. `ExecutionConfig.live_trading_enabled = true` is
  rejected by configuration validation, so the process refuses to start.
* No credentials are needed or read. The JSON log formatter also redacts any
  log field whose name contains `key`, `secret`, `token`, `password` or
  `signature`, as defence in depth.
* `.env` and recordings are git-ignored. `.env.example` contains no values.
* The engine already provides the **data-safety preconditions** that every
  later control depends on: explicit quote status, immediate invalidation on
  disconnect, stale and late-data detection, gap detection, health
  aggregation, and reasons for any degradation.

## Controls required before any execution (Phases 6–9)

Execution will be added behind an interface whose default implementation is
the paper simulator. A live adapter (Binance **Testnet** first) will exist
only when explicitly configured, and only after every control below is
implemented **and tested**:

| Control | Behaviour |
|---|---|
| Max position size / per-asset exposure / total exposure | Pre-trade check on intended *and* open positions. Reject on breach. |
| Max order notional; exchange filters | Exact integer checks (tick, step, min/max qty, min notional) before submission |
| Max daily loss | Measured on realised + marked-to-market P&L; breach → kill switch |
| Max order frequency | Token bucket per symbol and global, below exchange order-rate limits |
| Minimum net edge after costs | Fees, spread, depth-walked slippage, latency haircut |
| Max data age / feed health | No order unless every input leg is `LIVE`, younger than the strategy's max age, and health is `OK` |
| Slippage limit | Limit or IOC prices bounded by the modelled worst acceptable price; no unbounded market orders |
| Idempotent order intents | Deterministic client order id = hash(strategy, route, signal id, leg). Retries reuse it, and the exchange rejects duplicates. |
| Duplicate-order prevention | Intent registry; one live intent per (strategy, route) |
| Kill switch | Manual (API + file flag) and automatic: stale feed, shard down, health `DOWN`, reconciliation mismatch, abnormal reject/fill rate, daily-loss breach. It cancels open orders and blocks new ones until manually re-armed. |
| Reconciliation | Periodic comparison of intended vs exchange-reported positions and balances. A mismatch halts trading. |
| Audit log | Append-only record of every intent, check result, submission, ack, fill, cancel and kill-switch event (PostgreSQL), for paper and live alike |

## Credentials policy (for the future live adapter)

* Keys come only from environment variables or a secret manager. They are
  never stored in config files, never committed, and never logged.
* **Withdrawal permission disabled**, keys IP-restricted, trade-only scope,
  separate keys for Testnet and production.
* The live adapter refuses to start if the key has withdrawal permission
  (checked via the account API).
