"""Forward-return evaluation of signals against simple baselines.

For every directional signal the mid price at detection is recorded and, at
each horizon (default 1 s, 5 s, 30 s), the direction-adjusted forward return
in bps is computed - using only data available at that later time (no
look-ahead). A cost-adjusted figure subtracts a round trip at taker fees
plus the spread at entry.

Baselines, sampled on the same instruments and horizons:

* ``baseline.random``   - random direction at random times (expected ~0
  before costs);
* ``baseline.momentum`` - direction = sign of the prior 5 s return.

Per strategy and horizon the evaluator reports sample size, mean, standard
error, hit rate, cost-adjusted mean and Welch's t versus the random baseline,
and a verdict that refuses to claim anything below 30 samples. A positive
gross mean that does not survive costs is reported as such.

Non-directional signals (volatility, liquidity) are evaluated on the
absolute forward move versus the random baseline's absolute move.
"""

from __future__ import annotations

import math
import random
from collections import deque
from typing import Any

import numpy as np

from ..clock import NS_PER_S
from ..market_data.quality import QuoteStatus
from .base import Signal

MIN_SAMPLE = 30


class _Stat:
    __slots__ = ("n", "mean", "m2", "hits", "net_sum", "abs_sum")

    def __init__(self) -> None:
        self.n = 0
        self.mean = 0.0
        self.m2 = 0.0
        self.hits = 0
        self.net_sum = 0.0
        self.abs_sum = 0.0

    def add(self, x: float, net: float) -> None:
        self.n += 1
        d = x - self.mean
        self.mean += d / self.n
        self.m2 += d * (x - self.mean)
        self.hits += x > 0
        self.net_sum += net
        self.abs_sum += abs(x)

    @property
    def var(self) -> float:
        return self.m2 / (self.n - 1) if self.n > 1 else float("nan")

    def view(self) -> dict[str, Any]:
        se = math.sqrt(self.var / self.n) if self.n > 1 else None
        return {"n": self.n, "mean_bps": round(self.mean, 4) if self.n else None,
                "se_bps": round(se, 4) if se is not None and not math.isnan(se) else None,
                "hit_rate": round(self.hits / self.n, 4) if self.n else None,
                "mean_net_bps": round(self.net_sum / self.n, 4) if self.n else None,
                "mean_abs_bps": round(self.abs_sum / self.n, 4) if self.n else None}


def welch_t(a: _Stat, b: _Stat) -> float | None:
    if a.n < 2 or b.n < 2:
        return None
    va, vb = a.var / a.n, b.var / b.n
    if not (va + vb) > 0:
        return None
    return (a.mean - b.mean) / math.sqrt(va + vb)


class SignalEvaluator:
    name = "evaluation"

    def __init__(self, engine: Any, grid: Any) -> None:
        self.engine = engine
        self.grid = grid
        self.horizons = list(engine.cfg.strategies.patterns.eval_horizons_s)
        self.stats: dict[tuple[str, float], _Stat] = {}
        self.rng = random.Random(engine.cfg.paper.seed + 1)
        self.recent: deque[Signal] = deque(maxlen=1000)
        self.registered = 0
        self.persisted = 0
        grid.listeners.append(self._baseline_tick)

    # ---------------------------------------------------------- registration
    def register(self, sig: Signal) -> None:
        eng = self.engine
        st = eng.state.instruments.get(sig.key)
        self.registered += 1
        self.recent.append(sig)
        if st is not None and eng.state.status(st, sig.detected_mono_ns) in (QuoteStatus.LIVE, QuoteStatus.QUIET):
            sig.entry_mid = (st.bid_px + st.ask_px) / 2e8
            cost = 2 * (st.spec.fees.taker_bps if st.spec else 10.0) + (st.spread_bps() or 0.0)
            sig.evaluation = {"entry_mid": sig.entry_mid, "round_trip_cost_bps": round(cost, 4), "horizons": {}}
            for h in self.horizons:
                eng.scheduler.call_later(int(h * NS_PER_S), lambda now, s=sig, h=h, c=cost: self._score(s, h, c, now))
        else:
            sig.validation_status = "NOT_EVALUABLE"
        eng.audit("strategy_signals", {"correlation_id": sig.signal_id, "strategy": sig.strategy, "venue": sig.venue,
                                       "instrument": sig.key, "status": sig.classification, **sig.view()})

    def _mid(self, key: str, now: int) -> float | None:
        st = self.engine.state.instruments.get(key)
        if st is None or self.engine.state.status(st, now) not in (QuoteStatus.LIVE, QuoteStatus.QUIET):
            return None
        return (st.bid_px + st.ask_px) / 2e8

    def _score(self, sig: Signal, h: float, cost: float, now: int) -> None:
        exit_mid = self._mid(sig.key, now)
        if exit_mid is None or not sig.entry_mid:
            sig.evaluation["horizons"][str(h)] = {"status": "exit_unavailable"}
            return
        move = (exit_mid / sig.entry_mid - 1) * 10_000
        if sig.direction:
            fwd = sig.direction * move
            self._stat(sig.strategy, h).add(fwd, fwd - cost)
        else:
            fwd = abs(move)
            self._stat(sig.strategy, h).add(fwd, fwd)
        sig.evaluation["horizons"][str(h)] = {"fwd_bps": round(fwd, 4), "net_bps": round(fwd - cost, 4) if sig.direction else None}
        if h == max(self.horizons):
            sig.validation_status = "EVALUATED"
            self.persisted += 1
            self.engine.audit("signal_evaluations", {"correlation_id": sig.signal_id, "strategy": sig.strategy,
                                                     "instrument": sig.key, "status": "EVALUATED",
                                                     "direction": sig.direction, **sig.evaluation})

    def _stat(self, strategy: str, h: float) -> _Stat:
        s = self.stats.get((strategy, h))
        if s is None:
            s = self.stats[(strategy, h)] = _Stat()
        return s

    # ------------------------------------------------------------ baselines
    def _baseline_tick(self, now: int) -> None:
        """Once per second, sample a random instrument for both baselines."""
        g = self.grid
        if g.samples % max(1, g.samples_for(1.0)) or g.filled <= g.samples_for(5.0):
            return
        i = self.rng.randrange(g.N)
        key = g.keys[i]
        entry = self._mid(key, now)
        if entry is None:
            return
        mids = g.view("mid")[i]
        k5 = g.samples_for(5.0)
        prev = mids[-1 - k5]
        mom_dir = 0 if np.isnan(prev) or prev == mids[-1] else (1 if mids[-1] > prev else -1)
        rnd_dir = self.rng.choice((-1, 1))
        for h in self.horizons:
            def score(t: int, key=key, entry=entry, h=h, rd=rnd_dir, md=mom_dir) -> None:
                ex = self._mid(key, t)
                if ex is None:
                    return
                move = (ex / entry - 1) * 10_000
                self._stat("baseline.random", h).add(rd * move, rd * move)
                self._stat("baseline.abs_move", h).add(abs(move), abs(move))
                if md:
                    self._stat("baseline.momentum", h).add(md * move, md * move)
            self.engine.scheduler.call_later(int(h * NS_PER_S), score)

    # ---------------------------------------------------------------- report
    def report(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        strategies = sorted({s for s, _ in self.stats})
        for s in strategies:
            out[s] = {}
            for h in self.horizons:
                st = self.stats.get((s, h))
                if st is None:
                    continue
                v = st.view()
                directional = not any(x in s for x in ("volatility_expansion", "spread_blowout", "liquidity",
                                                       "volume_spike", "trade_rate", "divergence", "abs_move",
                                                       "price_volume"))
                base = self.stats.get(("baseline.random" if directional else "baseline.abs_move", h))
                t = welch_t(st, base) if base is not None else None
                v["vs_baseline_t"] = round(t, 3) if t is not None else None
                v["metric"] = "direction-adjusted forward return" if directional else "absolute forward move"
                if s.startswith("baseline."):
                    v["verdict"] = "baseline"
                elif st.n < MIN_SAMPLE:
                    v["verdict"] = f"insufficient_sample (n<{MIN_SAMPLE})"
                elif t is None or abs(t) < 2:
                    v["verdict"] = "no_evidence_of_difference_from_baseline"
                elif directional and (v["mean_net_bps"] or 0) <= 0:
                    v["verdict"] = "beats_baseline_gross_but_not_after_costs" if t > 0 else "underperforms_baseline"
                else:
                    v["verdict"] = "differs_from_baseline" + (" (after costs positive)" if directional else "")
                out[s][str(h)] = v
        return {"horizons_s": self.horizons, "min_sample": MIN_SAMPLE, "registered": self.registered,
                "results": out,
                "caveats": ["evaluated on whatever data source is running (simulated data proves nothing about markets)",
                            "overlapping signals are not independent; t-statistics are optimistic",
                            "costs = 2x taker fee + spread at entry; market impact not modelled"]}
