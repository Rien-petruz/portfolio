"""Time-sampled feature grid (fixed memory, vectorised with NumPy).

Every ``feature_interval_ms`` (default 100 ms) the grid samples, for every
instrument on every venue, the mid price, spread, touch liquidity (USD) and
the trade flow accumulated since the last sample. Only usable quotes
(``LIVE``/``QUIET``) are sampled; anything else is recorded as missing
(NaN), so stale or disconnected data never enters a feature.

Market events are still processed immediately; the grid is the *analysis*
cadence. Windows of 1 s / 5 s / 30 s / 60 s become 10 / 50 / 300 / 600
samples. Storage is a double-written ring buffer, so a chronological
``(N, C)`` view is a zero-copy slice.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from ..market_data.events import BUY, SELL
from ..market_data.quality import QuoteStatus
from ..numeric import ONE

FIELDS = ("mid", "spread_bps", "touch_usd", "vol_usd", "n_trades", "buy_usd", "sell_usd", "imbalance")


class FeatureGrid:
    name = "features"

    def __init__(self, engine: Any) -> None:
        self.engine = engine
        ec = engine.cfg.engine
        self.interval_ms = ec.feature_interval_ms
        self.C = max(20, int(ec.feature_history_s * 1000 / self.interval_ms))
        self.keys = list(engine.state.instruments)
        self.idx = {k: i for i, k in enumerate(self.keys)}
        self.N = len(self.keys)
        self.data = {f: np.full((self.N, 2 * self.C), np.nan) for f in FIELDS}
        self.head = 0
        self.filled = 0
        self.last_sample_mono_ns = 0
        self._acc = np.zeros((4, self.N))   # vol_usd, n_trades, buy_usd, sell_usd
        self._usd_quote = np.ones(self.N)
        self.listeners: list[Any] = []
        self.samples = 0
        self._valuation = None

    def samples_for(self, seconds: float) -> int:
        return max(1, int(round(seconds * 1000 / self.interval_ms)))

    # ------------------------------------------------------------ inputs
    def on_trades(self, trades: list[Any], now: int) -> None:
        idx, acc, uq = self.idx, self._acc, self._usd_quote
        for t in trades:
            i = idx.get(t.key)
            if i is None:
                continue
            v = t.px / ONE * t.qty / ONE * uq[i]
            acc[0, i] += v
            acc[1, i] += 1
            if t.aggressor == BUY:
                acc[2, i] += v
            elif t.aggressor == SELL:
                acc[3, i] += v

    def periodic(self) -> list[tuple[float, Any]]:
        return [(self.interval_ms, self.sample)]

    def sample(self, now: int) -> None:
        t0 = self.engine.clock.mono()
        eng = self.engine
        state = eng.state
        books = eng.books.books
        if self._valuation is None:
            from ..opportunities.valuation import Valuation
            self._valuation = Valuation(eng)
        h = self.head
        cols = (h, h + self.C)
        mid = np.full(self.N, np.nan)
        spread = np.full(self.N, np.nan)
        touch = np.full(self.N, np.nan)
        imb = np.full(self.N, np.nan)
        for i, k in enumerate(self.keys):
            st = state.instruments[k]
            if state.status(st, now) not in (QuoteStatus.LIVE, QuoteStatus.QUIET):
                continue
            b, a = st.bid_px / ONE, st.ask_px / ONE
            mid[i] = (a + b) / 2
            spread[i] = (a - b) / mid[i] * 10_000
            if st.spec is not None and self.samples % 10 == 0:
                self._usd_quote[i] = self._valuation.usd(st.spec.quote, now)[0] or np.nan
            touch[i] = (st.bid_qty / ONE * b + st.ask_qty / ONE * a) / 2 * self._usd_quote[i]
            book = books.get(k)
            if book is not None and book.is_synced:
                di = book.depth_imbalance(10)
                imb[i] = np.nan if di is None else di
            else:
                ti = st.touch_imbalance()
                imb[i] = np.nan if ti is None else ti
        acc = self._acc
        for name, arr in (("mid", mid), ("spread_bps", spread), ("touch_usd", touch), ("imbalance", imb),
                          ("vol_usd", acc[0]), ("n_trades", acc[1]), ("buy_usd", acc[2]), ("sell_usd", acc[3])):
            d = self.data[name]
            d[:, cols[0]] = arr
            d[:, cols[1]] = arr
        acc[:] = 0.0
        self.head = (h + 1) % self.C
        self.filled = min(self.filled + 1, self.C)
        self.samples += 1
        self.last_sample_mono_ns = now
        t1 = self.engine.clock.mono()
        if self.engine.clock.live:
            self.engine.metrics.record("features.sample", t1 - t0)
        for fn in self.listeners:
            fn(now)

    # ------------------------------------------------------------- views
    def view(self, name: str) -> np.ndarray:
        """Chronological (N, C) view, newest sample last (zero-copy)."""
        return self.data[name][:, self.head:self.head + self.C]

    def latest(self, name: str) -> np.ndarray:
        return self.data[name][:, (self.head - 1) % self.C]

    def coverage(self, n: int) -> np.ndarray:
        """Fraction of the last ``n`` samples with a valid mid, per instrument."""
        m = self.view("mid")[:, -n:]
        return np.mean(~np.isnan(m), axis=1)


def install_features(engine: Any) -> FeatureGrid:
    grid = FeatureGrid(engine)
    engine.add_component(grid, trades=True)
    a = None
    if engine.cfg.strategies.anomalies.enabled or engine.cfg.strategies.patterns.enabled:
        from ..strategies.evaluation import SignalEvaluator
        evaluator = SignalEvaluator(engine, grid)
        engine.add_component(evaluator)
        if engine.cfg.strategies.anomalies.enabled:
            from ..strategies.anomalies import AnomalyDetector
            a = AnomalyDetector(engine, grid, evaluator)
            engine.add_component(a)
        if engine.cfg.strategies.patterns.enabled:
            from ..strategies.patterns import PatternDetector
            p = PatternDetector(engine, grid, evaluator, a)
            engine.add_component(p)
    return grid
