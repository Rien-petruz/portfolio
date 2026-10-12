"""Anomaly engine: unusual behaviour, not arbitrage and not predictions.

All features are computed vectorised over every instrument from the feature
grid. Robust statistics only:

* returns over 1 s / 5 s / 30 s / 60 s windows scored against the median and
  MAD of same-horizon returns over the baseline period (default 60 s)::

      z = (r_now - median) / max(1.4826 * MAD, floor * sqrt(horizon))

  The floor (``min_sigma_bps``) prevents division by ~zero when a market has
  not moved (zero volatility) - such markets produce *no* score rather than
  an infinite one;
* spread blow-out and touch-liquidity withdrawal versus their baseline
  medians;
* abnormal trade volume / trade-arrival rate (1 s sums versus the median of
  1 s sums);
* cross-venue divergence: z of the log basis between venues quoting the same
  verified asset (through the conversion instrument where quotes differ);
* BTC-relative residual: an asset's 5 s return net of beta x BTC's 5 s return.

Baselines are recomputed every ``baseline_refresh_ms``; scores every sample.
A score is computed only with at least ``min_coverage`` of valid samples in
both the window and the baseline (warm-up, missing data).

Classification separates data problems from market behaviour:

* ``DATA_QUALITY_SUSPECT`` - the instrument had missing/invalid samples in
  the window or is not LIVE now;
* ``CORROBORATED_MOVE`` - price move accompanied by trades in the window or
  a same-direction move of the same asset on another venue;
* ``UNCORROBORATED`` - nothing else confirms it (possible quote glitch);
* ``CROSS_VENUE_DIVERGENCE`` / ``LIQUIDITY`` / ``ACTIVITY`` for the
  non-price anomaly families.

Scores are never described as probabilities of profit.
"""

from __future__ import annotations

import math
import warnings
from collections import deque
from typing import Any

import numpy as np

from ..clock import NS_PER_S
from ..market_data.quality import QuoteStatus
from .base import Signal


class _quiet:
    """Scoped suppression of NumPy's all-NaN / divide warnings (expected with missing data)."""

    def __enter__(self) -> None:
        self._w = warnings.catch_warnings()
        self._w.__enter__()
        warnings.simplefilter("ignore", RuntimeWarning)
        self._e = np.errstate(all="ignore")
        self._e.__enter__()

    def __exit__(self, *exc: Any) -> None:
        self._e.__exit__(*exc)
        self._w.__exit__(*exc)

MAD_K = 1.4826
REFERENCE_KEY = "BINANCE:BTCUSDT"


def nanmedian_rows(x: np.ndarray) -> np.ndarray:
    """Exact per-row median ignoring NaN, vectorised (np.nanmedian takes a slow
    per-row path on 2-D input). NaN rows -> NaN."""
    s = np.sort(x, axis=1)  # NaN sorts last
    cnt = np.sum(~np.isnan(x), axis=1)
    lo = np.clip((cnt - 1) // 2, 0, x.shape[1] - 1)
    hi = np.clip(cnt // 2, 0, x.shape[1] - 1)
    rows = np.arange(x.shape[0])
    med = (s[rows, lo] + s[rows, hi]) / 2
    med[cnt == 0] = np.nan
    return med


def rolling_sums(x: np.ndarray, n: int) -> np.ndarray:
    """Sums over every length-n window along axis 1 (NaN treated as 0)."""
    c = np.cumsum(np.nan_to_num(x), axis=1)
    c = np.concatenate([np.zeros((x.shape[0], 1)), c], axis=1)
    return c[:, n:] - c[:, :-n]


class Baselines:
    """Robust baseline statistics, refreshed on a slower cadence."""

    def __init__(self) -> None:
        self.ret: dict[int, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
        self.spread_med: np.ndarray | None = None
        self.touch_med: np.ndarray | None = None
        self.vol1_med: np.ndarray | None = None
        self.n1_med: np.ndarray | None = None
        self.beta: np.ndarray | None = None
        self.resid: tuple[np.ndarray, np.ndarray, np.ndarray] | None = None
        self.basis: tuple[np.ndarray, np.ndarray, np.ndarray] | None = None
        self.refreshed_mono_ns = 0
        self.ready = False


class AnomalyDetector:
    name = "anomalies"

    def __init__(self, engine: Any, grid: Any, evaluator: Any) -> None:
        self.engine = engine
        self.grid = grid
        self.evaluator = evaluator
        self.cfg = engine.cfg.strategies.anomalies
        self.windows = [grid.samples_for(w) for w in self.cfg.windows_s]
        self.L = min(grid.C, grid.samples_for(self.cfg.baseline_s))
        self.k1 = grid.samples_for(1.0)
        self.k5 = grid.samples_for(5.0)
        self.base = Baselines()
        self._pool: Any = None
        self._pending: Any = None
        self.last_emit: dict[tuple[str, str], int] = {}
        self.recent: deque[Signal] = deque(maxlen=500)
        self.last_by_key: dict[str, Signal] = {}
        self.counts: dict[str, int] = {}
        self.latest: dict[str, Any] = {}
        self.ref = grid.idx.get(REFERENCE_KEY)
        # Cross-venue pairs as index arrays (with optional conversion instrument).
        pairs = engine.registry.cross_venue_pairs()
        self.pairs = [p for p in pairs if p.a.key in grid.idx and p.b.key in grid.idx
                      and (p.conv is None or p.conv.spec.key in grid.idx)]
        self.pa = np.array([grid.idx[p.a.key] for p in self.pairs], dtype=int)
        self.pb = np.array([grid.idx[p.b.key] for p in self.pairs], dtype=int)
        self.pc = np.array([grid.idx[p.conv.spec.key] if p.conv else -1 for p in self.pairs], dtype=int)
        self.pinv = np.array([bool(p.conv and not p.conv.sell_base) for p in self.pairs], dtype=bool)
        # Same-base peers on other venues, for corroboration.
        self.peers: dict[int, list[int]] = {}
        for p in self.pairs:
            ia, ib = grid.idx[p.a.key], grid.idx[p.b.key]
            self.peers.setdefault(ia, []).append(ib)
            self.peers.setdefault(ib, []).append(ia)
        grid.listeners.append(self.on_sample)

    def periodic(self) -> list[tuple[float, Any]]:
        return [(self.engine.cfg.engine.baseline_refresh_ms, self.refresh)]

    # ------------------------------------------------------------ series
    def basis_series(self, n: int) -> np.ndarray:
        """log(mid_b converted into a's quote / mid_a) for the last n samples, (P, n)."""
        if not len(self.pairs):
            return np.zeros((0, n))
        m = self.grid.view("mid")[:, -n:]
        a, b = m[self.pa], m[self.pb]
        conv = np.ones_like(a)
        has = self.pc >= 0
        if has.any():
            c = m[self.pc[has]]
            conv[has] = np.where(self.pinv[has][:, None], 1.0 / c, c)
        return np.log(b * conv) - np.log(a)

    # ---------------------------------------------------------- baselines
    def refresh(self, now: int) -> None:
        """Recompute baselines. Live: on a worker thread from a copied snapshot
        (NumPy sorts release the GIL), results swapped in on the event loop.
        Replay: synchronous, so results are deterministic."""
        g = self.grid
        if g.filled < max(self.windows) + 10:
            return
        L = min(self.L, g.filled)
        snap = {name: g.view(name)[:, -L:].copy() for name in ("mid", "spread_bps", "touch_usd", "vol_usd", "n_trades")}
        snap["basis"] = self.basis_series(L).copy() if len(self.pairs) else None
        if not self.engine.clock.live:
            with _quiet():
                self._apply(self._compute(snap, L), now)
            return
        if self._pending is not None and not self._pending.done():
            return  # previous computation still running: skip, never queue up
        import asyncio
        from concurrent.futures import ThreadPoolExecutor

        if self._pool is None:
            self._pool = ThreadPoolExecutor(1, thread_name_prefix="anomaly-baseline")
        loop = asyncio.get_running_loop()
        t0 = self.engine.clock.mono()

        def job() -> Baselines:
            with _quiet():
                return self._compute(snap, L)

        def done(fut: Any) -> None:
            if fut.cancelled() or fut.exception() is not None:
                return
            self._apply(fut.result(), now)
            self.engine.metrics.record("anomaly.baseline_refresh_offloop", self.engine.clock.mono() - t0)

        self._pending = self._pool.submit(job)
        self._pending.add_done_callback(lambda f: loop.call_soon_threadsafe(done, f))

    def stop(self) -> None:
        if self._pool is not None:
            self._pool.shutdown(wait=False, cancel_futures=True)

    def _apply(self, b: Baselines, now: int) -> None:
        b.ready = True
        b.refreshed_mono_ns = now
        self.base = b

    def _compute(self, snap: dict[str, Any], L: int) -> Baselines:
        b = Baselines()
        logm = np.log(snap["mid"])
        N = logm.shape[0]
        for k in self.windows:
            if L <= k + 5:
                continue
            r = logm[:, k:] - logm[:, :-k]
            med = nanmedian_rows(r)
            mad = nanmedian_rows(np.abs(r - med[:, None]))
            cnt = np.sum(~np.isnan(r), axis=1)
            b.ret[k] = (med, mad, cnt / (L - k))
        b.spread_med = nanmedian_rows(snap["spread_bps"])
        b.touch_med = nanmedian_rows(snap["touch_usd"])
        b.vol1_med = nanmedian_rows(rolling_sums(snap["vol_usd"], self.k1))
        b.n1_med = nanmedian_rows(rolling_sums(snap["n_trades"], self.k1))
        if self.ref is not None and L > self.k5 + 10:
            r5 = logm[:, self.k5:] - logm[:, :-self.k5]
            x = r5[self.ref]
            ok = ~np.isnan(x)
            beta = np.full(N, np.nan)
            if ok.sum() > 20 and np.nanvar(x[ok]) > 0:
                xc = x - np.nanmean(x)
                yc = r5 - np.nanmean(r5, axis=1)[:, None]
                cov = np.nanmean(yc * xc[None, :], axis=1)
                beta = cov / np.nanvar(x)
                resid = r5 - beta[:, None] * x[None, :]
                med = nanmedian_rows(resid)
                mad = nanmedian_rows(np.abs(resid - med[:, None]))
                b.resid = (med, mad, np.mean(~np.isnan(resid), axis=1))
            b.beta = beta
        if snap["basis"] is not None:
            bs = snap["basis"]
            med = nanmedian_rows(bs)
            mad = nanmedian_rows(np.abs(bs - med[:, None]))
            b.basis = (med, mad, np.mean(~np.isnan(bs), axis=1))
        return b

    # ------------------------------------------------------------- scoring
    def on_sample(self, now: int) -> None:
        if not self.base.ready:
            return
        with _quiet():
            self._score(now)

    def _score(self, now: int) -> None:
        t0 = self.engine.clock.mono()
        g, cfg, b = self.grid, self.cfg, self.base
        mids = g.view("mid")
        logm_last = np.log(mids[:, -1])
        feats: dict[str, Any] = {"z": {}}
        floor_bps = cfg.min_sigma_bps
        for k in self.windows:
            if k not in b.ret or g.filled <= k:
                continue
            med, mad, cov = b.ret[k]
            r = logm_last - np.log(mids[:, -1 - k])
            sigma = np.maximum(MAD_K * mad, floor_bps * 1e-4 * math.sqrt(k))
            z = (r - med) / sigma
            z[(cov < cfg.min_coverage) | (g.coverage(k + 1) < cfg.min_coverage)] = np.nan
            feats["z"][k] = (z, r)
        feats["spread_ratio"] = g.latest("spread_bps") / b.spread_med
        feats["touch_ratio"] = g.latest("touch_usd") / b.touch_med
        vol1 = np.nansum(g.view("vol_usd")[:, -self.k1:], axis=1)
        n1 = np.nansum(g.view("n_trades")[:, -self.k1:], axis=1)
        feats["vol1"], feats["n1"] = vol1, n1
        feats["vol_ratio"] = np.where(b.vol1_med > 0, vol1 / b.vol1_med, np.nan)
        feats["rate_ratio"] = np.where(b.n1_med > 0, n1 / b.n1_med, np.nan)
        if b.resid is not None and self.ref is not None and b.beta is not None and g.filled > self.k5:
            r5 = logm_last - np.log(mids[:, -1 - self.k5])
            resid = r5 - b.beta * r5[self.ref]
            med, mad, cov = b.resid
            zr = (resid - med) / np.maximum(MAD_K * mad, floor_bps * 1e-4 * math.sqrt(self.k5))
            zr[cov < cfg.min_coverage] = np.nan
            feats["btc_resid_z"], feats["r5"], feats["btc_r5"] = zr, r5, r5[self.ref]
        if b.basis is not None and len(self.pairs):
            basis = self.basis_series(1)[:, -1]
            med, mad, cov = b.basis
            zb = (basis - med) / np.maximum(MAD_K * mad, 1e-4)
            zb[cov < cfg.min_coverage] = np.nan
            feats["basis"], feats["basis_z"] = basis, zb
        self.latest = feats
        self._emit(now, feats)
        if self.engine.clock.live:
            self.engine.metrics.record("anomaly.score", self.engine.clock.mono() - t0)

    # ------------------------------------------------------------ emission
    def _cooldown_ok(self, kind: str, key: str, now: int) -> bool:
        last = self.last_emit.get((kind, key))
        if last is not None and now - last < self.cfg.cooldown_s * NS_PER_S:
            return False
        self.last_emit[(kind, key)] = now
        return True

    def _quality(self, i: int, k: int, now: int) -> str:
        st = self.engine.state.instruments[self.grid.keys[i]]
        status = self.engine.state.status(st, now)
        if status is not QuoteStatus.LIVE or self.grid.coverage(k + 1)[i] < 1.0:
            return "DATA_QUALITY_SUSPECT"
        return status.value

    def _signal(self, kind: str, i: int, now: int, direction: int, strength: float, score_kind: str,
                features: dict[str, Any], classification: str, explanation: str, life: float | None) -> None:
        key = self.grid.keys[i]
        if not self._cooldown_ok(kind, key, now):
            return
        quality = "DATA_QUALITY_SUSPECT" if classification == "DATA_QUALITY_SUSPECT" else self._quality(i, self.k1, now)
        sig = Signal(f"anomaly.{kind}", "anomaly", key, key.split(":")[0], now, self.engine.clock.wall(), direction,
                     round(float(strength), 3), score_kind, features, quality, classification, explanation, life)
        self.recent.append(sig)
        self.last_by_key[key] = sig
        self.counts[kind] = self.counts.get(kind, 0) + 1
        self.evaluator.register(sig)

    def _emit(self, now: int, f: dict[str, Any]) -> None:
        cfg = self.cfg
        thr = cfg.z_threshold
        vol1 = f["vol1"]
        for k, (z, r) in f["z"].items():
            hits = np.where(np.abs(z) >= thr)[0]
            secs = k * self.grid.interval_ms / 1000
            for i in hits:
                d = 1 if r[i] > 0 else -1
                quality = self._quality(i, k, now)
                corroborated = bool(np.nansum(self.grid.view("n_trades")[i, -k:]) > 0)
                peer_moves = []
                for j in self.peers.get(i, ()):
                    zj = z[j]
                    if not np.isnan(zj) and np.sign(zj) == d and abs(zj) >= 2:
                        peer_moves.append(self.grid.keys[j])
                        corroborated = True
                cls = ("DATA_QUALITY_SUSPECT" if quality == "DATA_QUALITY_SUSPECT"
                       else "CORROBORATED_MOVE" if corroborated else "UNCORROBORATED")
                self._signal(f"price_jump_{secs:g}s", i, now, d, abs(z[i]), "robust_z",
                             {"window_s": secs, "return_bps": round(float(r[i]) * 1e4, 3), "z": round(float(z[i]), 3),
                              "trades_in_window": int(np.nansum(self.grid.view("n_trades")[i, -k:])),
                              "peer_confirmation": peer_moves},
                             cls, f"{secs:g}s return {r[i] * 1e4:+.1f} bps is {abs(z[i]):.1f} robust SDs from its "
                                  f"{cfg.baseline_s:g}s baseline ({cls.lower().replace('_', ' ')})", secs)
        for i in np.where(f["spread_ratio"] >= cfg.spread_ratio_threshold)[0]:
            self._signal("spread_blowout", i, now, 0, f["spread_ratio"][i], "ratio",
                         {"spread_bps": round(float(self.grid.latest("spread_bps")[i]), 3),
                          "baseline_spread_bps": round(float(self.base.spread_med[i]), 3)},
                         "LIQUIDITY", f"spread is {f['spread_ratio'][i]:.1f}x its baseline median", 5.0)
        for i in np.where(f["touch_ratio"] <= cfg.liquidity_drop_ratio)[0]:
            self._signal("liquidity_withdrawal", i, now, 0, 1 / max(f["touch_ratio"][i], 1e-9), "ratio",
                         {"touch_usd": round(float(self.grid.latest("touch_usd")[i]), 2),
                          "baseline_touch_usd": round(float(self.base.touch_med[i]), 2)},
                         "LIQUIDITY", f"touch liquidity fell to {f['touch_ratio'][i]:.0%} of its baseline median", 5.0)
        for name, arr, what in (("volume_spike", f["vol_ratio"], "1s traded notional"),
                                ("trade_rate_spike", f["rate_ratio"], "1s trade count")):
            for i in np.where(arr >= cfg.volume_ratio_threshold)[0]:
                if vol1[i] <= 0:
                    continue
                self._signal(name, i, now, 0, arr[i], "ratio", {"ratio": round(float(arr[i]), 3),
                                                                 "vol_1s_usd": round(float(vol1[i]), 2)},
                             "ACTIVITY", f"{what} is {arr[i]:.1f}x its baseline median", 5.0)
        if "btc_resid_z" in f:
            zr = f["btc_resid_z"]
            for i in np.where(np.abs(zr) >= thr)[0]:
                if i == self.ref:
                    continue
                self._signal("btc_relative", i, now, 1 if zr[i] > 0 else -1, abs(zr[i]), "robust_z",
                             {"resid_z": round(float(zr[i]), 3), "beta": round(float(self.base.beta[i]), 3),
                              "r5_bps": round(float(f["r5"][i]) * 1e4, 3), "btc_r5_bps": round(float(f["btc_r5"]) * 1e4, 3)},
                             "CORROBORATED_MOVE" if self._quality(i, self.k5, now) != "DATA_QUALITY_SUSPECT"
                             else "DATA_QUALITY_SUSPECT",
                             f"5s move net of BTC beta is {zr[i]:+.1f} robust SDs", 5.0)
        if "basis_z" in f:
            zb = f["basis_z"]
            for pi in np.where(np.abs(zb) >= cfg.divergence_z_threshold)[0]:
                p = self.pairs[pi]
                i = self.grid.idx[p.b.key]
                self._signal("cross_venue_divergence", i, now, 0, abs(zb[pi]), "robust_z",
                             {"pair": p.pair_id, "basis_bps": round(float(f["basis"][pi]) * 1e4, 3),
                              "z": round(float(zb[pi]), 3), "conversion": p.conv.spec.key if p.conv else None},
                             "CROSS_VENUE_DIVERGENCE",
                             f"{p.b.key} vs {p.a.key} basis {f['basis'][pi] * 1e4:+.1f} bps is {abs(zb[pi]):.1f} robust "
                             "SDs from normal (check the cross-exchange scanner for executable edge)", 2.0)

    def decorate_row(self, key: str, row: dict[str, Any]) -> None:
        """Scanner columns: short-horizon return, volatility and anomaly score."""
        f = self.latest
        i = self.grid.idx.get(key)
        if not f or i is None:
            return
        zs = [abs(z[i]) for z, _ in f["z"].values() if not np.isnan(z[i])]
        row["anomaly_score"] = round(float(max(zs)), 2) if zs else None
        k5 = self.k5
        if k5 in f["z"]:
            r = f["z"][k5][1][i]
            row["return_5s_bps"] = None if np.isnan(r) else round(float(r) * 1e4, 3)
        med_mad = self.base.ret.get(self.k1)
        if med_mad is not None:
            v = med_mad[1][i] * MAD_K * 1e4
            row["vol_1s_bps"] = None if np.isnan(v) else round(float(v), 3)
        lst = self.last_by_key.get(key)
        if lst is not None and self.engine.clock.mono() - lst.detected_mono_ns < 10 * NS_PER_S:
            row["signal"] = lst.strategy

    def snapshot(self, limit: int = 200) -> dict[str, Any]:
        return {"counts": self.counts, "baseline_ready": self.base.ready,
                "recent": [s.view() for s in list(self.recent)[-limit:]][::-1],
                "note": "scores are robust z-scores or ratios, not probabilities of profit"}


__all__ = ["AnomalyDetector", "Baselines", "rolling_sums"]
