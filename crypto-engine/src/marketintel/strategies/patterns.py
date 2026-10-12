"""Short-term pattern strategies: transparent statistical rules.

Each rule reads the shared feature grid and the anomaly engine's robust
statistics, and emits a structured :class:`Signal` with the feature values
that triggered it. No machine learning: rules are evaluated against forward
returns and simple baselines first (``evaluation.py``) - models may only be
considered once that evidence exists.

Rules (``z`` = robust z-score of the window return):

* ``momentum_acceleration``  - |z5| >= z_entry, 1 s and 5 s returns agree in
  sign and the last second moved faster than twice the 5 s average pace.
* ``mean_reversion``         - |z30| >= z_entry + 1 and the last second moved
  against the 30 s move (turning).                       direction: reversal
* ``volatility_expansion``   - 5 s realised vol >= ratio x 60 s realised vol.
* ``breakout``               - mid beyond the prior 60 s high/low (excluding
  the last second) by 2 bps with 1 s volume >= 1.5x baseline.
* ``price_volume_divergence``- |z5| >= z_entry on <= 0.5x baseline volume.
* ``lead_lag``               - same asset on two venues: leader's 1 s move
  |z| >= z_entry while the follower moved < 30 % as much. Signal on follower.
* ``btc_relative``           - BTC |z5| >= z_entry; an asset with beta >= 0.5
  has delivered < 30 % of its beta-implied move. Signal: catch-up direction.
* ``book_imbalance``         - |depth/touch imbalance| >= threshold and 5 s
  aggressor flow imbalance of the same sign >= 0.3.
"""

from __future__ import annotations

import warnings
from collections import deque
from typing import Any

import numpy as np

from ..clock import NS_PER_S
from ..market_data.quality import QuoteStatus
from .base import Signal


class PatternDetector:
    name = "patterns"

    def __init__(self, engine: Any, grid: Any, evaluator: Any, anomalies: Any | None) -> None:
        self.engine = engine
        self.grid = grid
        self.evaluator = evaluator
        self.anom = anomalies
        self.cfg = engine.cfg.strategies.patterns
        self.enabled = set(self.cfg.strategies)
        self.k1, self.k5 = grid.samples_for(1), grid.samples_for(5)
        self.k30, self.k60 = grid.samples_for(30), grid.samples_for(60)
        self.last_emit: dict[tuple[str, str], int] = {}
        self.recent: deque[Signal] = deque(maxlen=500)
        self.last_by_key: dict[str, Signal] = {}
        self.counts: dict[str, int] = {}
        grid.listeners.append(self.on_sample)

    def _ok(self, name: str, key: str, now: int) -> bool:
        last = self.last_emit.get((name, key))
        if last is not None and now - last < self.cfg.cooldown_s * NS_PER_S:
            return False
        self.last_emit[(name, key)] = now
        return True

    def _emit(self, name: str, i: int, now: int, direction: int, strength: float, features: dict[str, Any],
              explanation: str, life_s: float) -> None:
        key = self.grid.keys[i]
        if not self._ok(name, key, now):
            return
        st = self.engine.state.instruments[key]
        status = self.engine.state.status(st, now)
        quality = status.value if status is QuoteStatus.LIVE else "DATA_QUALITY_SUSPECT"
        sig = Signal(f"pattern.{name}", "pattern", key, key.split(":")[0], now, self.engine.clock.wall(),
                     direction, round(float(strength), 3), "robust_z" if "z" in explanation else "ratio",
                     {k: (round(float(v), 4) if isinstance(v, (float, np.floating)) else v) for k, v in features.items()},
                     quality, "RULE_TRIGGERED" if quality != "DATA_QUALITY_SUSPECT" else "DATA_QUALITY_SUSPECT",
                     explanation, life_s)
        self.recent.append(sig)
        self.last_by_key[key] = sig
        self.counts[name] = self.counts.get(name, 0) + 1
        self.evaluator.register(sig)

    def on_sample(self, now: int) -> None:
        a = self.anom
        if a is None or not a.base.ready or not a.latest:
            return
        with warnings.catch_warnings(), np.errstate(all="ignore"):
            warnings.simplefilter("ignore", RuntimeWarning)
            t0 = self.engine.clock.mono()
            self._run(now, a.latest)
            if self.engine.clock.live:
                self.engine.metrics.record("pattern.evaluate", self.engine.clock.mono() - t0)

    def _run(self, now: int, f: dict[str, Any]) -> None:
        g, cfg = self.grid, self.cfg
        zmap = f.get("z", {})
        if self.k5 not in zmap or self.k1 not in zmap:
            return
        z1, r1 = zmap[self.k1]
        z5, r5 = zmap[self.k5]
        ze = cfg.z_entry
        on = self.enabled
        if "momentum_acceleration" in on:
            pace = np.abs(r1) > 2 * np.abs(r5) / 5
            hit = (np.abs(z5) >= ze) & (np.sign(r1) == np.sign(r5)) & pace
            for i in np.where(hit)[0]:
                self._emit("momentum_acceleration", i, now, int(np.sign(r5[i])), abs(z5[i]),
                           {"z5": z5[i], "r1_bps": r1[i] * 1e4, "r5_bps": r5[i] * 1e4},
                           f"5s move {r5[i] * 1e4:+.1f} bps (z {z5[i]:+.1f}) accelerating in the last second", 5.0)
        if "mean_reversion" in on and self.k30 in zmap:
            z30, r30 = zmap[self.k30]
            hit = (np.abs(z30) >= ze + 1) & (np.sign(r1) == -np.sign(r30)) & (r1 != 0)
            for i in np.where(hit)[0]:
                self._emit("mean_reversion", i, now, int(-np.sign(r30[i])), abs(z30[i]),
                           {"z30": z30[i], "r30_bps": r30[i] * 1e4, "r1_bps": r1[i] * 1e4},
                           f"30s move {r30[i] * 1e4:+.1f} bps (z {z30[i]:+.1f}) with the last second turning", 30.0)
        mids = g.view("mid")
        logr = np.diff(np.log(mids[:, -(self.k60 + 1):]), axis=1)
        if "volatility_expansion" in on and g.filled > self.k60:
            rv5 = np.nanstd(logr[:, -self.k5:], axis=1)
            rv60 = np.nanstd(logr, axis=1)
            ratio = np.where(rv60 > 0, rv5 / rv60, np.nan)
            for i in np.where(ratio >= cfg.vol_expansion_ratio)[0]:
                self._emit("volatility_expansion", i, now, 0, ratio[i],
                           {"rv5_bps": rv5[i] * 1e4, "rv60_bps": rv60[i] * 1e4, "ratio": ratio[i]},
                           f"5s realised volatility is {ratio[i]:.1f}x the 60s level", 10.0)
        vol_ratio = f.get("vol_ratio")
        if "breakout" in on and g.filled > self.k60 and vol_ratio is not None:
            prior = mids[:, -self.k60:-self.k1]
            hi, lo = np.nanmax(prior, axis=1), np.nanmin(prior, axis=1)
            m = mids[:, -1]
            up = (m > hi * 1.0002) & (vol_ratio >= 1.5)
            dn = (m < lo * 0.9998) & (vol_ratio >= 1.5)
            for i in np.where(up | dn)[0]:
                d = 1 if up[i] else -1
                ref = hi[i] if d > 0 else lo[i]
                self._emit("breakout", i, now, d, abs(m[i] / ref - 1) * 1e4,
                           {"mid": m[i], "prior_high": hi[i], "prior_low": lo[i], "vol_ratio": vol_ratio[i]},
                           f"broke the prior 60s {'high' if d > 0 else 'low'} by {abs(m[i] / ref - 1) * 1e4:.1f} bps "
                           f"on {vol_ratio[i]:.1f}x volume", 10.0)
        if "price_volume_divergence" in on and vol_ratio is not None:
            hit = (np.abs(z5) >= ze) & (vol_ratio <= 0.5)
            for i in np.where(hit)[0]:
                self._emit("price_volume_divergence", i, now, 0, abs(z5[i]),
                           {"z5": z5[i], "vol_ratio": vol_ratio[i]},
                           f"5s move (z {z5[i]:+.1f}) on only {vol_ratio[i]:.1f}x baseline volume", 5.0)
        if "lead_lag" in on and self.anom is not None:
            for p in self.anom.pairs:
                ia, ib = g.idx[p.a.key], g.idx[p.b.key]
                for lead, lag in ((ia, ib), (ib, ia)):
                    if np.isnan(z1[lead]) or np.isnan(r1[lag]) or abs(z1[lead]) < ze:
                        continue
                    if abs(r1[lag]) < 0.3 * abs(r1[lead]):
                        self._emit("lead_lag", lag, now, int(np.sign(r1[lead])), abs(z1[lead]),
                                   {"leader": g.keys[lead], "leader_r1_bps": r1[lead] * 1e4,
                                    "follower_r1_bps": r1[lag] * 1e4, "leader_z1": z1[lead]},
                                   f"{g.keys[lead]} moved {r1[lead] * 1e4:+.1f} bps in 1s (z {z1[lead]:+.1f}); "
                                   f"this venue moved only {r1[lag] * 1e4:+.1f} bps", 2.0)
        ref = self.anom.ref if self.anom is not None else None
        beta = self.anom.base.beta if self.anom is not None else None
        if "btc_relative" in on and ref is not None and beta is not None and not np.isnan(z5[ref]) \
                and abs(z5[ref]) >= ze:
            implied = beta * r5[ref]
            hit = (beta >= 0.5) & (np.abs(r5) < 0.3 * np.abs(implied))
            hit[ref] = False
            for i in np.where(hit)[0]:
                self._emit("btc_relative", i, now, int(np.sign(r5[ref])), abs(z5[ref]),
                           {"btc_r5_bps": r5[ref] * 1e4, "beta": beta[i], "r5_bps": r5[i] * 1e4,
                            "implied_bps": implied[i] * 1e4},
                           f"BTC moved {r5[ref] * 1e4:+.1f} bps in 5s (z {z5[ref]:+.1f}); beta {beta[i]:.2f} implies "
                           f"{implied[i] * 1e4:+.1f} bps, delivered {r5[i] * 1e4:+.1f}", 5.0)
        if "book_imbalance" in on:
            imb = g.latest("imbalance")
            buy = np.nansum(g.view("buy_usd")[:, -self.k5:], axis=1)
            sell = np.nansum(g.view("sell_usd")[:, -self.k5:], axis=1)
            tot = buy + sell
            flow = np.where(tot > 0, (buy - sell) / tot, np.nan)
            hit = (np.abs(imb) >= cfg.imbalance_threshold) & (np.sign(flow) == np.sign(imb)) & (np.abs(flow) >= 0.3)
            for i in np.where(hit)[0]:
                self._emit("book_imbalance", i, now, int(np.sign(imb[i])), abs(imb[i]),
                           {"book_imbalance": imb[i], "flow_imbalance_5s": flow[i], "flow_usd_5s": tot[i]},
                           f"book imbalance {imb[i]:+.2f} with same-side aggressor flow {flow[i]:+.2f} "
                           "(probabilistic feature, not a directional guarantee)", 5.0)

    def decorate_row(self, key: str, row: dict[str, Any]) -> None:
        lst = self.last_by_key.get(key)
        if lst is not None and self.engine.clock.mono() - lst.detected_mono_ns < 10 * NS_PER_S:
            row["signal"] = f"{lst.strategy} ({'+' if lst.direction > 0 else '-' if lst.direction < 0 else '~'})"

    def snapshot(self, limit: int = 200) -> dict[str, Any]:
        return {"counts": self.counts, "recent": [s.view() for s in list(self.recent)[-limit:]][::-1]}

