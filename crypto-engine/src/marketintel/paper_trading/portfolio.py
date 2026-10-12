"""Virtual balances, cost basis and P&L (exact ``Decimal`` accounting).

Model
-----
* Independent balances per (venue, asset); nothing moves between venues
  (transfers/rebalancing are a separate operational process, not simulated).
* Every fill exchanges one asset for another. Fees are charged in the quote
  currency of the instrument (a simplification: some venues deduct from the
  received asset or a fee token; documented in RISK_MANAGEMENT.md).
* Cost basis is tracked per (venue, asset) in USD (average cost). When an
  asset leaves the portfolio, realized P&L = USD value received - average
  cost of what left. USD is the numeraire (cost basis 1).
* Unrealized P&L = Σ qty * (mark - avg_cost). The identity
  ``equity - (initial_equity + funding) == realized + unrealized`` holds by
  construction (tested).
* Funds reserved by in-flight simulated orders are unavailable to new orders.
* "Virtual funding": optional base-asset inventory granted on first use
  (configurable); recorded as funding, never as P&L.
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from typing import Any

D0 = Decimal(0)
E8 = Decimal(100_000_000)


def dec(x: float | int | str | Decimal) -> Decimal:
    return x if isinstance(x, Decimal) else Decimal(str(x))


def e8(v: int) -> Decimal:
    return Decimal(v) / E8


class Portfolio:
    def __init__(self, starting: dict[str, dict[str, float]], usd: Callable[[str], float | None]) -> None:
        self.usd = usd
        self.balances: dict[str, dict[str, Decimal]] = {}
        self.reserved: dict[str, dict[str, Decimal]] = {}
        self.cost: dict[tuple[str, str], Decimal] = {}     # avg USD cost per unit
        self.initial_qty: dict[tuple[str, str], Decimal] = {}
        self.realized_usd = D0
        self.fees_usd = D0
        self.funding_usd = D0
        self.initial_equity_usd = D0
        self.unpriced: set[str] = set()
        self.fills = 0
        self.turnover_usd = D0
        self._initialized = False
        self._starting = starting

    # ------------------------------------------------------------ set-up
    def initialize(self) -> bool:
        """Value starting balances once marks exist. Returns True when done."""
        if self._initialized:
            return True
        marks = {}
        for assets in self._starting.values():
            for a in assets:
                m = self.usd(a)
                if m is None:
                    return False
                marks[a] = dec(m)
        for venue, assets in self._starting.items():
            for a, q in assets.items():
                qd = dec(q)
                self.balances.setdefault(venue, {})[a] = qd
                self.cost[(venue, a)] = marks[a]
                self.initial_qty[(venue, a)] = qd
                self.initial_equity_usd += qd * marks[a]
        self._initialized = True
        return True

    @property
    def initialized(self) -> bool:
        return self._initialized

    def fund(self, venue: str, asset: str, qty: Decimal, mark: Decimal) -> None:
        """Virtual funding (deposit), excluded from P&L."""
        bal = self.balances.setdefault(venue, {})
        old = bal.get(asset, D0)
        oc = self.cost.get((venue, asset), mark)
        bal[asset] = old + qty
        self.cost[(venue, asset)] = (old * oc + qty * mark) / (old + qty) if old + qty else mark
        self.initial_qty[(venue, asset)] = self.initial_qty.get((venue, asset), D0) + qty
        self.funding_usd += qty * mark

    # ------------------------------------------------------------ queries
    def balance(self, venue: str, asset: str) -> Decimal:
        return self.balances.get(venue, {}).get(asset, D0)

    def available(self, venue: str, asset: str) -> float | None:
        if not self._initialized and not self.initialize():
            return 0.0
        return float(self.balance(venue, asset) - self.reserved.get(venue, {}).get(asset, D0))

    def reserve(self, venue: str, asset: str, amount: Decimal) -> None:
        r = self.reserved.setdefault(venue, {})
        r[asset] = r.get(asset, D0) + amount

    def release(self, venue: str, asset: str, amount: Decimal) -> None:
        r = self.reserved.setdefault(venue, {})
        r[asset] = max(D0, r.get(asset, D0) - amount)

    # ------------------------------------------------------------ fills
    def _remove(self, venue: str, asset: str, qty: Decimal, value_usd: Decimal) -> None:
        bal = self.balances.setdefault(venue, {})
        bal[asset] = bal.get(asset, D0) - qty
        basis = Decimal(1) if asset == "USD" else self.cost.get((venue, asset), value_usd / qty if qty else D0)
        self.realized_usd += value_usd - basis * qty

    def _add(self, venue: str, asset: str, qty: Decimal, cost_usd: Decimal) -> None:
        bal = self.balances.setdefault(venue, {})
        old = bal.get(asset, D0)
        if asset == "USD":
            bal[asset] = old + qty
            self.realized_usd += cost_usd - qty  # value received in USD vs. its face value
            return
        oc = self.cost.get((venue, asset), D0)
        new = old + qty
        if old <= 0:
            self.cost[(venue, asset)] = cost_usd / qty if qty else oc
        elif new > 0:
            self.cost[(venue, asset)] = (old * oc + cost_usd) / new
        bal[asset] = new

    def apply_fill(self, venue: str, base: str, quote: str, side: str, px_e8: int, qty_e8: int,
                   fee_rate: float) -> dict[str, Any]:
        """Apply one fill; returns accounting details (USD values at trade time)."""
        qty = e8(qty_e8)
        notional = e8(px_e8) * qty
        fee = notional * dec(fee_rate)
        q_usd = dec(self.usd(quote) or 0)
        if self.usd(quote) is None:
            self.unpriced.add(quote)
        if side == "BUY":
            out_amt = notional + fee                     # quote leaves
            value = out_amt * q_usd
            self._remove(venue, quote, out_amt, value)
            self._add(venue, base, qty, value)
        else:
            in_amt = notional - fee                      # quote arrives
            value = in_amt * q_usd
            self._remove(venue, base, qty, value)
            self._add(venue, quote, in_amt, value)
        self.fees_usd += fee * q_usd
        self.turnover_usd += notional * q_usd
        self.fills += 1
        return {"notional_quote": float(notional), "fee_quote": float(fee), "value_usd": float(value),
                "fee_usd": float(fee * q_usd)}

    # ------------------------------------------------------------ valuation
    def marks(self) -> dict[str, Decimal | None]:
        assets = {a for bal in self.balances.values() for a in bal}
        out: dict[str, Decimal | None] = {}
        for a in assets:
            m = self.usd(a)
            out[a] = dec(m) if m is not None else None
        return out

    def valuation(self) -> dict[str, Any]:
        marks = self.marks()
        equity = D0
        unreal = D0
        unpriced = []
        positions = []
        by_asset: dict[str, Decimal] = {}
        by_venue: dict[str, Decimal] = {}
        for venue, bal in self.balances.items():
            for a, q in bal.items():
                m = marks.get(a)
                init = self.initial_qty.get((venue, a), D0)
                if m is None:
                    # Fall back to cost basis so equity stays defined; flagged.
                    m = self.cost.get((venue, a), D0)
                    unpriced.append(a)
                equity += q * m
                c = Decimal(1) if a == "USD" else self.cost.get((venue, a), m)
                unreal += q * (m - c)
                dev = (q - init) * m
                if a not in ("USD",):
                    by_asset[a] = by_asset.get(a, D0) + dev
                by_venue[venue] = by_venue.get(venue, D0) + abs(dev)
                positions.append({"venue": venue, "asset": a, "qty": float(q), "initial_qty": float(init),
                                  "position": float(q - init), "mark_usd": float(m), "value_usd": float(q * m),
                                  "avg_cost_usd": float(c), "unrealized_usd": float(q * (m - c)),
                                  "reserved": float(self.reserved.get(venue, {}).get(a, D0))})
        pnl = equity - self.initial_equity_usd - self.funding_usd
        return {
            "equity_usd": float(equity),
            "initial_equity_usd": float(self.initial_equity_usd),
            "funding_usd": float(self.funding_usd),
            "pnl_usd": float(pnl),
            "realized_usd": float(self.realized_usd),
            "unrealized_usd": float(unreal),
            "fees_usd": float(self.fees_usd),
            "turnover_usd": float(self.turnover_usd),
            "exposure_by_asset_usd": {a: float(abs(v)) for a, v in by_asset.items()},
            "exposure_by_venue_usd": {v: float(x) for v, x in by_venue.items()},
            "total_exposure_usd": float(sum(abs(v) for v in by_asset.values())),
            "positions": positions,
            "unpriced_assets": sorted(set(unpriced) | self.unpriced),
            "fills": self.fills,
            "label": "SIMULATED",
        }

    def exposure_after(self, venue: str, asset: str, delta_qty: Decimal, mark: Decimal) -> tuple[Decimal, Decimal, Decimal]:
        """(asset exposure, venue exposure, total exposure) in USD if ``delta_qty`` is applied."""
        marks = self.marks()
        asset_net: dict[str, Decimal] = {}
        venue_gross: dict[str, Decimal] = {}
        for v, bal in self.balances.items():
            for a, q in bal.items():
                if a == "USD":
                    continue
                m = mark if a == asset else (marks.get(a) or self.cost.get((v, a), D0))
                dq = (q - self.initial_qty.get((v, a), D0)) + (delta_qty if (v, a) == (venue, asset) else D0)
                asset_net[a] = asset_net.get(a, D0) + dq * m
                venue_gross[v] = venue_gross.get(v, D0) + abs(dq * m)
        if (venue, asset) not in {(v, a) for v, bal in self.balances.items() for a in bal} and asset != "USD":
            asset_net[asset] = asset_net.get(asset, D0) + delta_qty * mark
            venue_gross[venue] = venue_gross.get(venue, D0) + abs(delta_qty * mark)
        total = sum((abs(x) for x in asset_net.values()), D0)
        return abs(asset_net.get(asset, D0)), venue_gross.get(venue, D0), total
