"""Shared synthetic market model for the venue simulators (SYNTHETIC DATA).

Holds one USD value per asset, evolved as a seeded random walk with a common
BTC factor. Each simulated venue sees the world through its own lens:

* ``lag_ms[venue]`` - the venue reflects values from that long ago (lets the
  engine's lead-lag detection be exercised);
* ``dislocations`` - temporary venue-specific price displacements (bps) used
  to create genuine cross-venue discrepancies in tests and demos;
* stablecoins mean-revert around 1.0 with tiny noise.

Nothing here resembles real market microstructure; it exists to drive the
engine's protocol, quality, strategy and paper-trading code reproducibly.
"""

from __future__ import annotations

import math
import random
import time
from collections import deque
from dataclasses import dataclass

SEED_VALUES: dict[str, float] = {
    "BTC": 60000.0, "ETH": 3000.0, "BNB": 550.0, "SOL": 150.0, "XRP": 0.55, "USDC": 1.0,
    "FDUSD": 1.0, "ADA": 0.45, "DOGE": 0.12, "TRX": 0.12, "LINK": 14.0, "AVAX": 30.0,
    "DOT": 6.5, "LTC": 75.0, "BCH": 380.0, "UNI": 8.0, "XLM": 0.1, "ATOM": 7.0, "ETC": 22.0,
    "FIL": 4.5, "APT": 7.5, "ARB": 0.8, "OP": 1.7, "NEAR": 5.0, "INJ": 22.0, "SUI": 1.0,
    "AAVE": 95.0, "TON": 6.0, "SHIB": 0.00002, "PEPE": 0.00001, "WIF": 2.0, "SEI": 0.4,
    "TIA": 6.0, "RENDER": 7.0, "FET": 1.3, "HBAR": 0.07, "ICP": 9.0, "ALGO": 0.15, "VET": 0.025,
    "SAND": 0.35, "MANA": 0.35, "GALA": 0.025, "EGLD": 30.0, "THETA": 1.5, "AXS": 6.0,
    "RUNE": 4.5, "LDO": 1.8, "CRV": 0.35, "MKR": 2200.0, "ENS": 18.0, "JUP": 0.9,
    "PENDLE": 4.5, "ORDI": 35.0, "STX": 1.7, "IMX": 1.5, "KAS": 0.15, "GRT": 0.2, "QNT": 70.0,
    "FLOW": 0.6, "CHZ": 0.07, "KAVA": 0.4,
}
STABLES = {"USD", "USDT", "USDC", "FDUSD"}


@dataclass
class Dislocation:
    asset: str
    venue: str
    bps: float
    until: float


class MarketWorld:
    def __init__(self, seed: int = 7, *, vol_per_sqrt_s: float = 0.0004, synthetic_assets: int = 0,
                 lag_ms: dict[str, float] | None = None, step_s: float = 0.01,
                 grid_epoch: float | None = None) -> None:
        self.rng = random.Random(seed)
        self.vol = vol_per_sqrt_s
        self.values: dict[str, float] = {"USD": 1.0, "USDT": 1.0, **SEED_VALUES}
        for i in range(synthetic_assets):
            self.values[f"SYN{i:03d}"] = 10 ** self.rng.uniform(-3, 3)
        self.lag_ms = dict(lag_ms or {"BINANCE": 0.0, "COINBASE": 120.0})
        self.step_s = step_s
        maxlag = max(self.lag_ms.values(), default=0.0)
        self._history: deque[tuple[float, dict[str, float]]] = deque(maxlen=max(2, int(maxlag / 1000 / step_s) + 5))
        self.dislocations: list[Dislocation] = []
        self.dislocation_rate_per_min = 0.0
        self.dislocation_bps = (15.0, 60.0)
        self.dislocation_duration_s = (0.3, 2.0)
        self.t = 0.0
        self._last_wall: float | None = None
        # With a shared epoch the world advances on a fixed step grid, so separate
        # processes built with the same seed and epoch evolve identically.
        self.grid_epoch = grid_epoch
        self._grid_steps = 0
        self._history.append((self.t, dict(self.values)))

    # ------------------------------------------------------------ evolution
    def step(self, dt_s: float) -> None:
        sd = self.vol * math.sqrt(max(dt_s, 1e-6))
        btc_shock = self.rng.gauss(0, sd)
        for a, v in self.values.items():
            if a == "USD":
                continue
            if a in STABLES:
                self.values[a] = v + (1.0 - v) * 0.05 + self.rng.gauss(0, 2e-6)
                continue
            beta = 1.0 if a == "BTC" else 0.8
            idio = 0.0 if a == "BTC" else self.rng.gauss(0, sd * 0.6)
            self.values[a] = v * math.exp(beta * btc_shock + idio)
        self.t += dt_s
        self._history.append((self.t, dict(self.values)))
        if self.dislocation_rate_per_min > 0:
            p = self.dislocation_rate_per_min / 60 * dt_s
            if self.rng.random() < p:
                assets = [a for a in self.values if a not in STABLES]
                venue = self.rng.choice(sorted(self.lag_ms))
                self.dislocate(self.rng.choice(assets), venue,
                               self.rng.choice((-1, 1)) * self.rng.uniform(*self.dislocation_bps),
                               self.rng.uniform(*self.dislocation_duration_s))
        self.dislocations = [d for d in self.dislocations if d.until > self.t]

    def advance_to_wall(self, now: float | None = None) -> float:
        """Advance by wall-clock elapsed time (shared by several simulators)."""
        now = time.monotonic() if now is None else now
        if self.grid_epoch is not None:
            target = int((now - self.grid_epoch) / self.step_s)
            n = target - self._grid_steps
            for _ in range(n):
                self.step(self.step_s)
            self._grid_steps = max(target, self._grid_steps)
            return max(n, 0) * self.step_s
        if self._last_wall is None:
            self._last_wall = now
            return 0.0
        dt = now - self._last_wall
        if dt <= 0:
            return 0.0
        self._last_wall = now
        self.step(dt)
        return dt

    def dislocate(self, asset: str, venue: str, bps: float, duration_s: float) -> None:
        self.dislocations.append(Dislocation(asset, venue, bps, self.t + duration_s))

    # -------------------------------------------------------------- reading
    def _values_at(self, lag_s: float) -> dict[str, float]:
        if lag_s <= 0 or len(self._history) < 2:
            return self.values
        target = self.t - lag_s
        for t, vals in reversed(self._history):
            if t <= target:
                return vals
        return self._history[0][1]

    def value(self, asset: str, venue: str) -> float:
        vals = self._values_at(self.lag_ms.get(venue, 0.0) / 1000)
        v = vals[asset]
        for d in self.dislocations:
            if d.asset == asset and d.venue == venue:
                v *= 1 + d.bps / 10_000
        return v

    def price(self, base: str, quote: str, venue: str) -> float:
        return self.value(base, venue) / self.value(quote, venue)
