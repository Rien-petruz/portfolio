# Strategies (design; implementation starts in Phase 4)

**No strategy is implemented yet.** This document fixes the rules
strategies must follow so that Phase 4 builds on the guarantees of Phases
1–3 instead of working around them.

## Rules every strategy must follow

1. **Inputs must be valid.** Use only symbols whose status is `LIVE` (or
   `QUIET` where the strategy explicitly accepts unchanged books), with data
   age under the strategy's own `max_data_age_ms`, and only while engine
   health is `OK`. Multi-leg logic requires *all* legs to pass, and the legs'
   receive times must lie within a configurable synchronisation window.
2. **Use executable prices.** Buys execute at the ask, sells at the bid,
   walking the local book for size when depth is available. Last-traded
   prices are never used as executable prices.
3. **Warm-up and minimum samples.** No score is produced until the window
   holds enough samples. A zero or near-zero dispersion estimate yields "no
   score", not infinity.
4. **Explain every signal.** A signal carries its reason, contributing
   features, all relevant timestamps (exchange `E`, receive, detection),
   input statuses, and a confidence. Confidence is called a *probability*
   only after calibration on held-out data.
5. **Deduplicate.** One alert per (strategy, instrument/route, regime
   episode), with a cool-down.
6. **Labels are explicit.** Every result is labelled `theoretical` →
   `simulated` → `execution-verified`, and never presented as realised
   profit.

## Planned strategies

### A. Price anomaly

Robust deviation of the mid (or microprice) from rolling baselines over
100 ms (where the event rate allows), 1 s, 5 s, 30 s and 60 s. Features:

* log returns;
* rolling volatility;
* median and MAD z-scores, with a MAD floor;
* abnormal trade size and arrival rate;
* spread expansion;
* residual move relative to BTC (beta-adjusted).

Before scoring, stale, crossed or late data is excluded at the input.

### B. Cross-market discrepancy

* Implied rates from synchronised bid/ask quotes, for example BTCUSDT vs
  BTCUSDC × USDCUSDT.
* Triangular routes such as USDT → BTC → ETH → USDT using ETHBTC.

Evaluation covers:

* exact conversion with per-leg fees;
* tick, step and min-notional constraints (exchange filters are already
  parsed as exact integers);
* depth-walked slippage at the intended size;
* inventory and capital requirements;
* sequential-execution risk, where later legs see different prices.

The universe already forces these legs into the subscription.

### C. Order-book imbalance

Touch imbalance and depth imbalance (top N levels), changes in liquidity near
the touch, aggressor flow from trades, and "flicker" (liquidity that appears
and disappears). Treated as a probabilistic feature, never as a directional
guarantee.

### D. Short-term patterns

Momentum acceleration, mean-reversion candidates, volatility expansion,
breakouts, abnormal price/volume relationships, and BTC-led moves with
delayed reactions in related assets (lead/lag on synchronised receive
timestamps). The first versions are transparent statistical rules. ML comes
only after the recorded-data replay pipeline (Phase 6) provides a
reproducible dataset with walk-forward, out-of-sample evaluation and no
look-ahead.

## Telling real errors apart from noise

| Observation | Classification | Data that decides it |
|---|---|---|
| Quote far from baseline, connection healthy, delivery lag normal, other legs consistent | possible dislocation → strategy scoring | status `LIVE`, delivery lag, cross-checks |
| Quote unchanged for long, connection healthy | `QUIET` (illiquid), not an anomaly | `book_age_ms`, status |
| Shard silent or delivering late | stale or delayed feed, never a signal | `STALE`, `delivery_lag_ms` |
| bid ≥ ask | data error | `CROSSED` |
| Implied cross-rate deviation smaller than the summed spreads + fees | normal spread difference | executable quotes + fee model |
| Deviation only with legs received far apart | asynchronous-feed artefact | per-leg receive timestamps |
| Deviation exists, but depth at size removes it | theoretical, not executable | local book sweep |
