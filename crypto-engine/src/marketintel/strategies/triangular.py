"""Triangular arbitrage on a single venue (event-driven).

Routes ``S -> X -> Y -> S`` are enumerated from the venue's monitored
instruments for each configured start asset ``S``. Each leg converts
``from_asset`` into ``to_asset`` through one instrument:

* the instrument's base is ``to_asset``  -> BUY at the ASK
* the instrument's base is ``from_asset`` -> SELL at the BID

Two figures are reported and never confused:

* ``theoretical_net_bps`` - product of executable touch rates with each
  leg's taker fee, ignoring quantity rounding and minimums;
* ``net_bps`` (simulated executable) - the route run at the maximum feasible
  starting capital with every leg rounded down to its step size and checked
  against minimum quantity/notional; leftovers ("dust") stay as inventory and
  are excluded from the edge.

The maximum feasible starting capital is the smallest of: each leg's
displayed touch liquidity translated back into the start asset, and the
configured notional cap. Execution in paper trading is sequential (each leg
sized from the previous leg's actual output); simultaneous fills at quoted
prices are never assumed.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..clock import NS_PER_MS
from ..exchanges.base import InstrumentSpec
from ..market_data.quality import QuoteStatus
from ..numeric import ONE
from ..opportunities.tracker import OpportunityTracker
from ..opportunities.valuation import Valuation


@dataclass(frozen=True)
class Leg:
    spec: InstrumentSpec
    side: str          # BUY | SELL
    src: str
    dst: str


@dataclass(frozen=True)
class Route:
    route_id: str
    venue: str
    start: str
    legs: tuple[Leg, Leg, Leg]


def build_routes(specs: list[InstrumentSpec], start_assets: list[str]) -> list[Route]:
    edges: dict[str, list[Leg]] = {}
    for s in specs:
        if s.alias_of is not None:
            continue
        edges.setdefault(s.quote, []).append(Leg(s, "BUY", s.quote, s.base))
        edges.setdefault(s.base, []).append(Leg(s, "SELL", s.base, s.quote))
    routes: list[Route] = []
    seen: set[str] = set()
    for start in start_assets:
        for l1 in edges.get(start, ()):
            x = l1.dst
            for l2 in edges.get(x, ()):
                y = l2.dst
                if y in (start, x) or l2.spec is l1.spec:
                    continue
                for l3 in edges.get(y, ()):
                    if l3.dst != start or l3.spec in (l1.spec, l2.spec):
                        continue
                    rid = f"{l1.spec.venue.value}:{start}>{x}>{y}>{start}"
                    if rid in seen:
                        continue
                    seen.add(rid)
                    routes.append(Route(rid, l1.spec.venue.value, start, (l1, l2, l3)))
    return routes


class TriangularScanner:
    name = "triangular"

    def __init__(self, engine: Any, *, inventory: Callable[[str, str], float | None] | None = None,
                 on_valid: Callable[[Any, dict[str, Any]], None] | None = None) -> None:
        self.engine = engine
        self.cfg = engine.cfg.strategies.triangular
        self.valuation = Valuation(engine)
        self.inventory = inventory
        venue_specs = [s for s in engine.registry.by_key.values() if s.venue.value == self.cfg.venue
                       and s.key in engine.state.instruments]
        self.routes = build_routes(venue_specs, self.cfg.start_assets) if self.cfg.enabled else []
        self.index: dict[str, list[Route]] = {}
        for r in self.routes:
            for leg in r.legs:
                self.index.setdefault(leg.spec.key, []).append(r)
        self.tracker = OpportunityTracker(engine, self.name, on_valid=on_valid)
        self.last: dict[str, dict[str, Any]] = {}
        self.evaluations = 0
        self.quick_rejects = 0

    def on_quotes(self, batch: dict[str, int], now: int) -> None:
        if not self.routes:
            return
        todo: dict[str, tuple[Route, int]] = {}
        for k, t in batch.items():
            for r in self.index.get(k, ()):
                if r.route_id not in todo or t < todo[r.route_id][1]:
                    todo[r.route_id] = (r, t)
        t0 = self.engine.clock.mono()
        inst = self.engine.state.instruments
        for r, trig in todo.values():
            if r.route_id not in self.tracker.open:
                g = 1.0
                for leg in r.legs:
                    st = inst[leg.spec.key]
                    if st.bid_px <= 0 or st.ask_px <= 0:
                        g = 0.0
                        break
                    g *= (ONE / st.ask_px) if leg.side == "BUY" else (st.bid_px / ONE)
                if g <= 1.0:
                    self.quick_rejects += 1
                    continue
            ev = self.evaluate(r, now)
            ev["trigger_recv_mono_ns"] = trig
            self.evaluations += 1
            self.last[r.route_id] = ev
            cand = ev["gross_bps"] > 0 and not ev.get("close_reason")
            self.tracker.update(ev, is_candidate=cand, now=now)
        if self.engine.clock.live and todo:
            self.engine.metrics.record("tri.evaluation_batch", self.engine.clock.mono() - t0)

    def periodic(self) -> list[tuple[float, Callable[[int], None]]]:
        def sweep(now: int) -> None:
            for rid in list(self.tracker.open):
                r = next((x for x in self.routes if x.route_id == rid), None)
                if r is not None:
                    ev = self.evaluate(r, now)
                    self.last[rid] = ev
                    self.tracker.update(ev, is_candidate=ev["gross_bps"] > 0 and not ev.get("close_reason"), now=now)
        return [(self.engine.cfg.engine.summary_interval_ms, sweep)]

    def evaluate(self, r: Route, now: int) -> dict[str, Any]:
        cfg = self.cfg
        state = self.engine.state
        reasons: list[str] = []
        quotes = []
        for leg in r.legs:
            st = state.instruments.get(leg.spec.key)
            status = state.status(st, now) if st is not None else QuoteStatus.UNSUBSCRIBED
            if st is None or st.bid_px <= 0 or st.ask_px <= 0:
                return {"route_id": r.route_id, "gross_bps": float("-inf"), "net_bps": float("-inf"),
                        "status": "REJECTED", "reasons": ["no_quote"], "close_reason": "data_unavailable"}
            if status is not QuoteStatus.LIVE:
                reasons.append(f"quote_not_live:{leg.spec.key}:{status.value}")
            elif (now - st.book_recv_mono_ns) / NS_PER_MS > cfg.max_quote_age_ms:
                reasons.append(f"quote_stale:{leg.spec.key}")
            if not leg.spec.filters_known:
                reasons.append(f"filters_unknown:{leg.spec.key}")
            elif not leg.spec.tradable:
                reasons.append(f"not_tradable:{leg.spec.key}")
            quotes.append(st)
        recv = [st.book_recv_mono_ns for st in quotes]
        skew_ms = (max(recv) - min(recv)) / NS_PER_MS
        if skew_ms > cfg.max_recv_skew_ms:
            reasons.append(f"recv_skew:{skew_ms:.0f}ms")

        # ---- theoretical rates (per unit of src) and touch capacity in src units
        gross = 1.0
        theo = 1.0
        rates: list[float] = []
        caps_src: list[float] = []
        for leg, st in zip(r.legs, quotes):
            fee = leg.spec.fees.taker_bps / 10_000
            if leg.side == "BUY":
                px = st.ask_px / ONE
                rate = 1 / px
                caps_src.append(st.ask_qty / ONE * px)        # quote units we can spend at the touch
                theo *= rate / (1 + fee)
            else:
                px = st.bid_px / ONE
                rate = px
                caps_src.append(st.bid_qty / ONE)              # base units we can sell at the touch
                theo *= rate * (1 - fee)
            gross *= rate
            rates.append(rate)
        gross_bps = (gross - 1) * 10_000
        theo_bps = (theo - 1) * 10_000
        # Translate each leg's capacity into start-asset units.
        cum = 1.0
        start_caps = []
        for i, cap in enumerate(caps_src):
            start_caps.append(cap / cum)
            cum *= rates[i]
        usd, _ = self.valuation.usd(r.start, now)
        cap_name = "touch_liquidity"
        start_cap = min(start_caps)
        if usd:
            notional_cap = cfg.max_start_notional_usd / usd
            if notional_cap < start_cap:
                start_cap, cap_name = notional_cap, "max_start_notional"
        if self.inventory is not None:
            inv = self.inventory(r.venue, r.start)
            if inv is not None and inv < start_cap:
                start_cap, cap_name = max(0.0, inv), "inventory"

        # ---- simulated executable run with rounding and minimums
        amount = start_cap * 0.999
        spent_start = 0.0
        plans = []
        tol = self.engine.cfg.paper.limit_slippage_bps / 10_000
        for i, (leg, st) in enumerate(zip(r.legs, quotes)):
            spec = leg.spec
            fee = spec.fees.taker_bps / 10_000
            if leg.side == "BUY":
                px = st.ask_px
                qty = spec.round_qty(int(amount / (px / ONE * (1 + fee)) * ONE))
                used = qty / ONE * px / ONE * (1 + fee)
                out = qty / ONE
            else:
                px = st.bid_px
                qty = spec.round_qty(int(amount * ONE))
                used = qty / ONE
                out = qty / ONE * px / ONE * (1 - fee)
            errs = spec.validate_order(px, qty) if spec.filters_known else []
            if qty <= 0:
                reasons.append(f"leg{i + 1}_zero_after_rounding")
            elif errs:
                reasons.append(f"leg{i + 1}_{errs[0]}")
            if i == 0:
                spent_start = used
            plans.append({"leg": f"l{i + 1}", "key": spec.key, "side": leg.side, "qty_e8": qty,
                          "ref_px_e8": px, "limit_px_e8": int(px * (1 + tol)) if leg.side == "BUY" else int(px * (1 - tol)),
                          "src": leg.src, "dst": leg.dst})
            amount = out
        final = amount
        net_bps = (final - spent_start) / spent_start * 10_000 if spent_start > 0 else float("-inf")
        if net_bps < cfg.min_net_edge_bps:
            reasons.append(f"net_below_threshold:{net_bps:.2f}<{cfg.min_net_edge_bps}bps")
        profit_usd = (final - spent_start) * usd if usd and spent_start > 0 else 0.0
        return {
            "strategy": self.name, "route_id": r.route_id, "route_class": r.route_id, "venue": r.venue,
            "start_asset": r.start, "path": [f"{lg.side} {lg.spec.symbol}" for lg in r.legs],
            "gross_bps": round(gross_bps, 4), "theoretical_net_bps": round(theo_bps, 4), "net_bps": round(net_bps, 4),
            "fee_bps": round(sum(lg.spec.fees.taker_bps for lg in r.legs), 4),
            "start_capital": round(spent_start, 10), "max_start_capital": round(start_cap, 10), "size_limited_by": cap_name,
            "final_amount": round(final, 10), "expected_profit_usd": round(profit_usd, 6),
            "notional_usd": round(spent_start * (usd or 0.0), 4),
            "liquidity_usd": round(min(start_caps) * (usd or 0.0), 2),
            "quote_age_ms": round(max(now - t for t in recv) / NS_PER_MS, 2), "recv_skew_ms": round(skew_ms, 2),
            "slippage_bps": 0.0, "depth_model": "touch",
            "legs": plans,
            "status": "VALID" if not reasons else "REJECTED", "reasons": reasons,
            "validation": "theoretical", "detected_mono_ns": now, "detected_wall_ns": self.engine.clock.wall(),
        }

    def snapshot(self, limit: int = 100) -> dict[str, Any]:
        rows = sorted((e for e in self.last.values() if "path" in e), key=lambda e: -e["gross_bps"])
        return {"routes": len(self.routes), "evaluations": self.evaluations, "tracker": self.tracker.stats(),
                "open": self.tracker.ranked(limit), "recent_closed": self.tracker.recent_closed(50),
                "scanner": rows[:limit]}
