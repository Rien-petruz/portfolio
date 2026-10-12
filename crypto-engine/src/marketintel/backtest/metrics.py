"""Backtest metrics from a replay (paper-trading results, opportunities, signals).

Everything reported is SIMULATED and limited by the data it was run on. The
report always includes sample sizes, the data source and explicit
limitations; Sharpe ratios and confidence intervals are omitted when there
are too few observations to mean anything.
"""

from __future__ import annotations

import math
import random
import statistics
from typing import Any

import numpy as np

from .replay import ReplayResult

MIN_SHARPE_PERIODS = 30
MIN_CI_SAMPLE = 10


def max_drawdown(values: list[float]) -> tuple[float, float]:
    """(max drawdown in USD, as fraction of the running peak)."""
    peak = -math.inf
    mdd = 0.0
    mdd_frac = 0.0
    for v in values:
        peak = max(peak, v)
        dd = peak - v
        if dd > mdd:
            mdd = dd
            mdd_frac = dd / peak if peak > 0 else 0.0
    return mdd, mdd_frac


def sharpe(equity: list[tuple[int, float]], period_s: int = 60) -> dict[str, Any]:
    """Annualised Sharpe of per-period equity returns (risk-free 0)."""
    if len(equity) < 2:
        return {"value": None, "periods": 0, "note": "insufficient data"}
    t0 = equity[0][0]
    buckets: dict[int, float] = {}
    for t, v in equity:
        buckets[(t - t0) // (period_s * 1_000_000_000)] = v
    vals = [buckets[k] for k in sorted(buckets)]
    rets = [(b - a) / a for a, b in zip(vals, vals[1:]) if a]
    if len(rets) < MIN_SHARPE_PERIODS:
        return {"value": None, "periods": len(rets),
                "note": f"not computed: fewer than {MIN_SHARPE_PERIODS} {period_s}s periods"}
    sd = statistics.pstdev(rets)
    if sd == 0:
        return {"value": None, "periods": len(rets), "note": "zero variance"}
    ann = math.sqrt(365 * 24 * 3600 / period_s)
    return {"value": statistics.fmean(rets) / sd * ann, "periods": len(rets), "period_s": period_s,
            "note": "annualised from short-horizon simulated returns; not a forecast"}


def bootstrap_ci(xs: list[float], n: int = 2000, seed: int = 7) -> tuple[float, float] | None:
    if len(xs) < MIN_CI_SAMPLE:
        return None
    rng = random.Random(seed)
    means = sorted(statistics.fmean(rng.choices(xs, k=len(xs))) for _ in range(n))
    return means[int(0.025 * n)], means[int(0.975 * n) - 1]


def _group(execs: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for e in execs:
        g = out.setdefault(e[key], {"executions": 0, "pnl_usd": 0.0, "filled": 0})
        g["executions"] += 1
        g["pnl_usd"] += e["pnl"]
        g["filled"] += e["status"] in ("FILLED", "PARTIAL")
    return out


def regimes(series: list[tuple[int, float | None, float | None, float | None]],
            execs: list[dict[str, Any]], window_s: int = 60) -> dict[str, Any]:
    """Label each window by BTC realised volatility and spread terciles."""
    pts = [(t, m, s) for t, _, m, s in series if m]
    if len(pts) < 3 * 5:
        return {"note": "insufficient data for regime split"}
    t0 = pts[0][0]
    wins: dict[int, list[tuple[float, float | None]]] = {}
    for t, m, s in pts:
        wins.setdefault((t - t0) // (window_s * 1_000_000_000), []).append((m, s))
    rows = []
    for w, vals in sorted(wins.items()):
        mids = np.array([v[0] for v in vals])
        r = np.diff(np.log(mids)) if len(mids) > 2 else np.array([0.0])
        sp = [v[1] for v in vals if v[1] is not None]
        rows.append((w, float(np.std(r)) * 1e4, statistics.fmean(sp) if sp else float("nan")))
    vols = sorted(r[1] for r in rows)
    lo, hi = vols[len(vols) // 3], vols[2 * len(vols) // 3]
    label = {w: ("low_vol" if v <= lo else "high_vol" if v > hi else "mid_vol") for w, v, _ in rows}
    out: dict[str, Any] = {k: {"windows": 0, "executions": 0, "pnl_usd": 0.0} for k in ("low_vol", "mid_vol", "high_vol")}
    for w, _, _ in rows:
        out[label[w]]["windows"] += 1
    for e in execs:
        w = (e["wall_ns"] - t0) // (window_s * 1_000_000_000)
        if w in label:
            out[label[w]]["executions"] += 1
            out[label[w]]["pnl_usd"] += e["pnl"]
    out["window_s"] = window_s
    out["volatility_metric"] = "std of 1s BTCUSDT log returns (bps), terciles across windows"
    return out


def report(res: ReplayResult) -> dict[str, Any]:
    eng = res.engine
    paper = eng.component("paper")
    xex = eng.component("cross_exchange")
    tri = eng.component("triangular")
    evaluator = eng.component("evaluation")
    duration_s = (res.last_mono_ns - res.first_mono_ns) / 1e9
    hours = max(duration_s / 3600, 1e-9)
    out: dict[str, Any] = {
        "label": "SIMULATED BACKTEST",
        "data_source": f"REPLAY of {eng.universe.notes}",
        "frames": res.frames,
        "duration_s": round(duration_s, 3),
        "replay_wall_seconds": round(res.wall_seconds, 3),
        "replay_speed_x": round(duration_s / res.wall_seconds, 2) if res.wall_seconds else None,
        "params": res.params,
    }
    execs: list[dict[str, Any]] = []
    if paper is not None:
        for e in paper.recent_executions:
            r = e.result
            execs.append({"strategy": e.strategy, "route": e.route_id, "status": r["status"],
                          "pnl": r.get("pnl_usd") or 0.0,
                          "expected": r.get("expected_profit_usd"), "est_slip": r.get("expected_slippage_bps"),
                          "sim_slip": r.get("simulated_slippage_bps"), "estimate": r.get("estimate"),
                          "venues": "|".join(sorted({leg["venue"] for leg in r.get("legs", [])})),
                          "wall_ns": r["legs"][0]["created_wall_ns"] if r.get("legs") else 0})
        v = paper.portfolio.valuation() if paper.portfolio.initialized else None
        curve = [(t, eq) for t, eq, _, _ in res.probe.series if eq is not None] if res.probe else []
        values = [eq for _, eq in curve]
        mdd, mdd_frac = max_drawdown(values) if values else (0.0, 0.0)
        filled = [e for e in execs if e["status"] in ("FILLED", "PARTIAL")]
        wins = [e["pnl"] for e in filled if e["pnl"] > 0]
        losses = [e["pnl"] for e in filled if e["pnl"] <= 0]
        pnl_list = [e["pnl"] for e in filled]
        ci = bootstrap_ci(pnl_list)
        slip_pairs = [(e["est_slip"], e["sim_slip"]) for e in filled
                      if e["est_slip"] is not None and e["sim_slip"] is not None]
        out["paper"] = {
            "net_pnl_usd": v["pnl_usd"] if v else None,
            "initial_equity_usd": v["initial_equity_usd"] if v else None,
            "return_on_capital": (v["pnl_usd"] / v["initial_equity_usd"]) if v and v["initial_equity_usd"] else None,
            "realized_usd": v["realized_usd"] if v else None,
            "unrealized_usd": v["unrealized_usd"] if v else None,
            "fees_usd": v["fees_usd"] if v else None,
            "turnover_usd": v["turnover_usd"] if v else None,
            "turnover_x_capital": (v["turnover_usd"] / v["initial_equity_usd"]) if v and v["initial_equity_usd"] else None,
            "max_drawdown_usd": round(mdd, 6), "max_drawdown_frac": round(mdd_frac, 8),
            "sharpe": sharpe(curve),
            "executions": len(execs),
            "executions_by_status": {s: sum(1 for e in execs if e["status"] == s)
                                     for s in ("FILLED", "PARTIAL", "MISSED", "REJECTED")},
            "win_rate": round(len(wins) / len(filled), 4) if filled else None,
            "avg_profit_usd": statistics.fmean(wins) if wins else None,
            "avg_loss_usd": statistics.fmean(losses) if losses else None,
            "mean_pnl_per_execution_usd": statistics.fmean(pnl_list) if pnl_list else None,
            "mean_pnl_95ci_bootstrap": ci,
            "estimated_vs_simulated_slippage_bps": {
                "n": len(slip_pairs),
                "mean_estimated": statistics.fmean(a for a, _ in slip_pairs) if slip_pairs else None,
                "mean_simulated": statistics.fmean(b for _, b in slip_pairs) if slip_pairs else None},
            "fills_flagged_estimate": sum(1 for e in filled if e["estimate"]),
            "by_strategy": _group(execs, "strategy"),
            "by_venues": _group(execs, "venues"),
            "regimes": regimes(res.probe.series if res.probe else [], execs),
            "risk": paper.risk.status()["reject_reasons"],
        }
    opp: dict[str, Any] = {}
    for comp in (xex, tri):
        if comp is None:
            continue
        tr = comp.tracker
        closed = list(tr.closed) + list(tr.open.values())
        valid = [e for e in closed if e.ever_valid]
        executed = [e for e in valid if e.execution and e.execution.get("status") in ("FILLED", "PARTIAL")]
        losing = [e for e in executed if (e.execution.get("pnl_usd") or 0) <= 0]
        missed = [e for e in valid if e.execution and e.execution.get("status") == "MISSED"]
        never = [e for e in closed if not e.ever_valid]
        naive = sum((e.first.get("expected_profit_usd") or 0.0) for e in never)
        lifetimes = [e.lifetime_ms for e in closed if e.closed_mono_ns]
        opp[comp.name] = {
            "candidates": len(closed), "candidates_per_hour": round(len(closed) / hours, 2),
            "valid": len(valid), "executed_with_fills": len(executed), "missed_at_arrival": len(missed),
            "signal_to_fill_conversion": round(len(executed) / len(valid), 4) if valid else None,
            "false_positive_rate": round((len(losing) + len(missed)) / len(valid), 4) if valid else None,
            "false_positive_definition": "valid candidates that were missed at arrival or realised <= 0",
            "median_lifetime_ms": round(statistics.median(lifetimes), 1) if lifetimes else None,
            "naive_baseline": {
                "description": "counterfactual: trading every gross-positive candidate that never passed validation, "
                               "at its first evaluated size and expected net (estimate, not simulated)",
                "candidates": len(never), "expected_pnl_usd": round(naive, 6)},
        }
    out["opportunities"] = opp
    if evaluator is not None:
        out["signals"] = evaluator.report()
    out["data_quality"] = {"invalid_frames": dict(eng.invalid), "events": dict(eng.events)}
    out["limitations"] = [
        "results are simulated on the replayed data source; simulated data proves nothing about real markets",
        "fills against top-of-book are estimates (hidden liquidity, queue position and market impact unknown)",
        "fees are charged in the quote currency (venue fee-asset rules not modelled)",
        "inter-venue transfers/rebalancing are not simulated; inventory is pre-funded",
        "sample sizes are small; see per-metric n and confidence intervals",
    ]
    return out
