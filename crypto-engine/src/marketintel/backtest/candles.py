"""Candle-level evaluation of transparent pattern rules (no order book!).

Input: Binance kline CSV as published on data.binance.vision
(open_time, open, high, low, close, volume, close_time, quote_volume,
trades, taker_buy_base, taker_buy_quote, ignore). Only bar data exists here,
so this module **does not** simulate executions, spreads, depth or
arbitrage. It evaluates directional rules on close-to-close forward returns
and compares them with a random-direction baseline and a buy-and-hold drift,
subtracting a configurable round-trip cost. Results are labelled
``CANDLE-LEVEL`` and must not be compared with order-book-level backtests.
"""

from __future__ import annotations

import csv
import math
import random
import statistics
from collections.abc import Iterable
from typing import Any


def load_klines(path: str) -> list[dict[str, float]]:
    rows = []
    with open(path, newline="") as fh:
        for r in csv.reader(fh):
            if not r or not r[0].strip().isdigit():
                continue  # header or blank
            rows.append({"t": float(r[0]), "open": float(r[1]), "high": float(r[2]), "low": float(r[3]),
                         "close": float(r[4]), "volume": float(r[5]),
                         "taker_buy_base": float(r[9]) if len(r) > 9 and r[9] else math.nan})
    for a, b in zip(rows, rows[1:]):
        if b["t"] <= a["t"]:
            raise ValueError("duplicate or out-of-order candles")
    return rows


def _stats(xs: list[float]) -> dict[str, Any]:
    if not xs:
        return {"n": 0}
    m = statistics.fmean(xs)
    se = statistics.stdev(xs) / math.sqrt(len(xs)) if len(xs) > 1 else None
    return {"n": len(xs), "mean_bps": round(m, 3), "se_bps": None if se is None else round(se, 3),
            "hit_rate": round(sum(x > 0 for x in xs) / len(xs), 4)}


def evaluate(rows: list[dict[str, float]], *, lookback: int = 20, horizon: int = 5, z_entry: float = 2.0,
             cost_bps: float = 20.0, seed: int = 1) -> dict[str, Any]:
    """Momentum / mean-reversion / breakout rules on closes; decisions at bar i
    use bars <= i only, outcomes use bar i + horizon."""
    closes = [r["close"] for r in rows]
    rets = [math.log(b / a) for a, b in zip(closes, closes[1:])]
    rng = random.Random(seed)
    out: dict[str, list[float]] = {"momentum": [], "mean_reversion": [], "breakout": [], "baseline.random": []}
    for i in range(lookback + 1, len(closes) - horizon):
        window = rets[i - lookback:i]
        sd = statistics.pstdev(window)
        r1 = rets[i - 1]
        fwd = (closes[i + horizon] / closes[i] - 1) * 1e4
        out["baseline.random"].append(rng.choice((-1, 1)) * fwd - cost_bps)
        if sd > 0 and abs(r1 / sd) >= z_entry:
            d = 1 if r1 > 0 else -1
            out["momentum"].append(d * fwd - cost_bps)
            out["mean_reversion"].append(-d * fwd - cost_bps)
        prior = closes[i - lookback:i]
        if closes[i] > max(prior):
            out["breakout"].append(fwd - cost_bps)
        elif closes[i] < min(prior):
            out["breakout"].append(-fwd - cost_bps)
    drift = (closes[-1] / closes[0] - 1) * 1e4 if closes else 0.0
    return {
        "label": "CANDLE-LEVEL (no order book, no executable prices, no arbitrage)",
        "bars": len(rows), "lookback": lookback, "horizon_bars": horizon, "cost_bps_round_trip": cost_bps,
        "buy_and_hold_bps": round(drift, 2),
        "results": {k: _stats(v) for k, v in out.items()},
        "note": "net of cost_bps; overlapping horizons make samples dependent",
    }


def evaluate_file(path: str, **kw: Any) -> dict[str, Any]:
    return evaluate(load_klines(path), **kw)


__all__ = ["evaluate", "evaluate_file", "load_klines", "Iterable"]
