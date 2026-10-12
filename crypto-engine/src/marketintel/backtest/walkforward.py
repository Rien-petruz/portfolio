"""Walk-forward / out-of-sample evaluation over a recording.

The recording's timeline is split into ``k`` consecutive folds. For each fold
``i >= 1`` the edge threshold (``min_net_edge_bps`` of the arbitrage
strategies and risk) is chosen on fold ``i - 1`` (in-sample) from a grid, by
highest simulated net P&L (ties -> the more conservative, higher threshold),
and then applied unchanged to fold ``i`` (out-of-sample). Only out-of-sample
results are aggregated. Each run replays its fold with a warm-up period taken
from the data *before* the fold (no look-ahead).
"""

from __future__ import annotations

from typing import Any

from ..config import Settings
from .metrics import report
from .replay import load, replay


def _with_threshold(settings: Settings, bps: float) -> Settings:
    s = settings.model_copy(deep=True)
    s.strategies.cross_exchange.min_net_edge_bps = bps
    s.strategies.triangular.min_net_edge_bps = bps
    s.risk.min_net_edge_bps = bps
    return s


def walk_forward(path: str, settings: Settings, *, folds: int = 4, grid: list[float] | None = None,
                 warmup_s: float = 30.0) -> dict[str, Any]:
    grid = sorted(grid or [1.0, 2.0, 5.0, 10.0])
    meta, frames = load(path)
    t0, t1 = frames[0].recv_wall_ns, frames[-1].recv_wall_ns + 1
    edges = [t0 + (t1 - t0) * i // folds for i in range(folds + 1)]
    results = []
    for i in range(1, folds):
        ins = (edges[i - 1], edges[i])
        oos = (edges[i], edges[i + 1])
        scores = []
        for bps in grid:
            r = replay(meta=meta, frames=frames, settings=_with_threshold(settings, bps),
                       start_ns=ins[0], end_ns=ins[1], warmup_s=warmup_s)
            pnl = (report(r).get("paper") or {}).get("net_pnl_usd") or 0.0
            scores.append((pnl, bps))
        best_pnl, best = max(scores, key=lambda x: (x[0], x[1]))
        r = replay(meta=meta, frames=frames, settings=_with_threshold(settings, best),
                   start_ns=oos[0], end_ns=oos[1], warmup_s=warmup_s)
        rep = report(r)
        results.append({
            "fold": i, "in_sample_window_ns": ins, "out_of_sample_window_ns": oos,
            "in_sample_scores": [{"min_net_edge_bps": b, "net_pnl_usd": p} for p, b in scores],
            "chosen_min_net_edge_bps": best,
            "out_of_sample": {k: (rep.get("paper") or {}).get(k) for k in
                              ("net_pnl_usd", "executions", "win_rate", "max_drawdown_usd", "fees_usd")},
            "out_of_sample_opportunities": rep.get("opportunities"),
        })
    oos_pnl = [f["out_of_sample"]["net_pnl_usd"] or 0.0 for f in results]
    return {
        "label": "SIMULATED WALK-FORWARD",
        "folds": folds, "grid": grid, "results": results,
        "oos_total_pnl_usd": sum(oos_pnl),
        "oos_positive_folds": sum(1 for p in oos_pnl if p > 0),
        "note": "parameters are selected in-sample and evaluated on the following unseen fold only",
    }
