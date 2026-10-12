"""Paper-trading engine - SIMULATED execution only.

Hard boundary: nothing in this module (or anywhere in the code base) can
send an order to an exchange. Orders are Python objects matched against the
engine's own market state; see ``safety.py`` and the paper-only tests.

Flow for an opportunity that passes validation:

1. risk check of the opportunity (edge, freshness, skew, slippage, liquidity,
   frequency, duplicates, emergency stop);
2. one simulated order per leg with a deterministic client id
   (idempotent: re-submitting the same intent is rejected as a duplicate);
3. order-level risk check (filters, notional, balances, positions, exposure)
   and balance reservation;
4. the order *arrives* after a simulated latency (per venue + jitter) and is
   matched against the market state **at arrival time** - so opportunities
   that vanished during the latency are missed, as they would be;
5. fills update virtual balances; IOC remainders are cancelled; GTC orders
   rest until a trade prints through their price or they expire;
6. the execution outcome (filled / partial / missed / rejected, realized vs.
   expected edge, simulated slippage, unhedged inventory) is attached to the
   opportunity episode and persisted.

Triangular routes execute their legs sequentially; each leg's size comes from
the previous leg's actual (rounded, fee-reduced) output.
"""

from __future__ import annotations

import logging
import random
from collections import deque
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from ..clock import NS_PER_MS, NS_PER_S
from ..numeric import ONE
from ..opportunities.valuation import Valuation
from ..risk.manager import RiskManager
from ..safety import EXECUTION_MODE, PAPER_BANNER
from .fills import FillModel
from .orders import OrderStatus, OrderType, Side, SimFill, SimOrder, TimeInForce, client_order_id
from .portfolio import Portfolio, dec

log = logging.getLogger(__name__)


@dataclass
class Execution:
    parent_id: str
    strategy: str
    route_id: str
    created_mono_ns: int
    expected: dict[str, Any]
    leg_plans: list[dict[str, Any]]
    sequential: bool
    orders: list[SimOrder] = field(default_factory=list)
    status: str = "IN_PROGRESS"
    result: dict[str, Any] = field(default_factory=dict)
    episode: Any = None


class PaperEngine:
    name = "paper"

    def __init__(self, engine: Any) -> None:
        self.engine = engine
        self.cfg = engine.cfg.paper
        self.valuation = Valuation(engine)
        self.portfolio = Portfolio(self.cfg.starting_balances, lambda a: self.valuation.usd(a)[0])
        self.risk = RiskManager(engine, engine.cfg.risk)
        self.fill_model = FillModel(engine)
        self.rng = random.Random(self.cfg.seed)
        self.orders: dict[str, SimOrder] = {}
        self.recent_orders: deque[SimOrder] = deque(maxlen=500)
        self.recent_fills: deque[SimFill] = deque(maxlen=1000)
        self.executions: dict[str, Execution] = {}
        self.recent_executions: deque[Execution] = deque(maxlen=300)
        self.resting: dict[str, SimOrder] = {}
        self.funded: set[tuple[str, str]] = set()
        self.equity_curve: deque[tuple[int, float]] = deque(maxlen=100_000)
        self.counters = {"opportunities": 0, "risk_rejected": 0, "orders": 0, "duplicates": 0, "rejected": 0,
                         "filled": 0, "partial": 0, "missed": 0, "fills": 0}
        self._fill_seq = 0
        self._last_snapshot_ns = 0

    # --------------------------------------------------------------- hooks
    def start(self, engine: Any) -> None:
        engine.audit("audit_log", {"event": "paper_engine_started", "mode": EXECUTION_MODE, "banner": PAPER_BANNER,
                                   "starting_balances": self.cfg.starting_balances})

    def periodic(self) -> list[tuple[float, Any]]:
        return [(250.0, self._expire)]

    def on_trades(self, trades: list[Any], now: int) -> None:
        if not self.resting:
            return
        by_key: dict[str, list[SimOrder]] = {}
        for o in self.resting.values():
            by_key.setdefault(o.key, []).append(o)
        for t in trades:
            for o in by_key.get(t.key, ()):
                if o.is_final:
                    continue
                q = FillModel.trade_through(o, t.px, t.qty)
                if q > 0:
                    self._apply_fill(o, o.limit_px_e8, q, "trade_through", True, now)
                    if o.remaining_e8 <= 0:
                        self._finalize(o, OrderStatus.FILLED, now)
                    else:
                        o.status = OrderStatus.PARTIALLY_FILLED

    def on_summary(self, now: int, health: dict[str, Any]) -> None:
        if not self.portfolio.initialized and self.portfolio.initialize():
            v = self.portfolio.valuation()
            self.engine.audit("balance_snapshots", {"event": "initial", "status": "SIMULATED", **v})
        pnl = None
        if self.portfolio.initialized:
            v = self.portfolio.valuation()
            pnl = v["pnl_usd"]
            self.equity_curve.append((self.engine.clock.wall(), v["equity_usd"] - v["funding_usd"]))
            interval = int(self.engine.cfg.persistence.balance_snapshot_interval_s * NS_PER_S)
            if now - self._last_snapshot_ns >= interval:
                self._last_snapshot_ns = now
                self.engine.audit("balance_snapshots", {"event": "periodic", "status": "SIMULATED", **{
                    k: v[k] for k in ("equity_usd", "pnl_usd", "realized_usd", "unrealized_usd", "fees_usd",
                                      "funding_usd", "total_exposure_usd", "exposure_by_venue_usd")}})
        was = self.risk.halted
        self.risk.on_summary(now, health, pnl)
        if self.risk.halted and not was:
            self.cancel_all("emergency_stop")

    # -------------------------------------------------------- opportunities
    def on_opportunity(self, episode: Any, ev: dict[str, Any]) -> None:
        strategy = ev.get("strategy", "")
        if not self.cfg.enabled or strategy not in self.cfg.trade_strategies:
            return
        now = self.engine.clock.mono()
        self.counters["opportunities"] += 1
        if not self.portfolio.initialize():
            self._mark_episode(episode, {"status": "SKIPPED", "reasons": ["portfolio_not_initialized"]})
            return
        ok, reasons = self.risk.check_opportunity(ev, now)
        if not ok:
            self.counters["risk_rejected"] += 1
            self._mark_episode(episode, {"status": "RISK_REJECTED", "reasons": reasons})
            return
        legs = ev.get("legs") or self._cross_legs(ev)
        ex = Execution(episode.episode_id if episode else ev["route_id"], strategy, ev["route_id"], now, {
            k: ev.get(k) for k in ("net_bps", "gross_bps", "expected_profit_usd", "qty", "slippage_bps",
                                   "trigger_recv_mono_ns")}, legs, sequential=bool(ev.get("legs")), episode=episode)
        if ex.parent_id in self.executions:
            self.counters["duplicates"] += 1
            return
        self.executions[ex.parent_id] = ex
        trig = ev.get("trigger_recv_mono_ns")
        if trig and self.engine.clock.live:
            self.engine.metrics.record(f"paper.recv_to_submit.{strategy}", self.engine.clock.mono() - trig)
        if ex.sequential:
            self._submit_leg(ex, 0, None)
        else:
            for i in range(len(legs)):
                self._submit_leg(ex, i, None)

    def _cross_legs(self, ev: dict[str, Any]) -> list[dict[str, Any]]:
        tol = self.cfg.limit_slippage_bps / 10_000
        return [
            {"leg": "buy", "key": ev["buy_key"], "side": "BUY", "qty_e8": ev["qty_e8"],
             "ref_px_e8": int(round(ev["buy_ask"] * ONE)), "limit_px_e8": int(ev["buy_ask"] * (1 + tol) * ONE)},
            {"leg": "sell", "key": ev["sell_key"], "side": "SELL", "qty_e8": ev["qty_e8"],
             "ref_px_e8": int(round(ev["sell_bid"] * ONE)), "limit_px_e8": int(ev["sell_bid"] * (1 - tol) * ONE)},
        ]

    def _ensure_inventory(self, venue: str, asset: str) -> None:
        if self.cfg.auto_base_inventory_usd <= 0 or (venue, asset) in self.funded:
            return
        self.funded.add((venue, asset))
        if asset in self.cfg.starting_balances.get(venue, {}) or asset in ("USD", "USDT", "USDC", "FDUSD"):
            return
        mark = self.valuation.usd(asset)[0]
        if not mark:
            return
        qty = dec(self.cfg.auto_base_inventory_usd) / dec(mark)
        self.portfolio.fund(venue, asset, qty, dec(mark))
        self.engine.audit("audit_log", {"event": "virtual_funding", "venue": venue, "asset": asset,
                                        "qty": float(qty), "usd": self.cfg.auto_base_inventory_usd,
                                        "note": "simulated inventory, excluded from P&L"})

    def _submit_leg(self, ex: Execution, i: int, prev: SimOrder | None) -> None:
        plan = ex.leg_plans[i]
        spec = self.engine.registry.get(plan["key"])
        if spec is None:
            ex.status = "REJECTED"
            return
        qty = plan["qty_e8"]
        if ex.sequential and prev is not None:
            qty = self._next_qty(prev, plan, spec)
        self._ensure_inventory(spec.venue.value, spec.base)
        o = SimOrder(
            client_order_id(ex.parent_id, plan["leg"]), ex.parent_id, ex.strategy, spec.venue.value, spec.key,
            Side(plan["side"]), OrderType.LIMIT, TimeInForce.IOC, qty, plan["limit_px_e8"],
            self.engine.clock.mono(), self.engine.clock.wall(), reference_px_e8=plan.get("ref_px_e8", 0),
            leg=plan["leg"])
        ex.orders.append(o)
        self.submit(o)

    def _next_qty(self, prev: SimOrder, plan: dict[str, Any], spec: Any) -> int:
        """Size of the next sequential leg from what the previous leg produced."""
        pspec = self.engine.registry.get(prev.key)
        fee = pspec.fees.taker_bps / 10_000
        if prev.side is Side.BUY:   # received base of prev
            got = Decimal(prev.filled_qty_e8)
            got_asset = pspec.base
        else:                       # received quote of prev (net of fee)
            got = Decimal(prev.notional_e16) / Decimal(ONE) * (1 - dec(fee))
            got_asset = pspec.quote
        if plan["side"] == "SELL":  # selling got_asset as base
            q = int(got) if spec.base == got_asset else 0
        else:                       # buying base with got_asset as quote
            px = Decimal(plan["limit_px_e8"])
            q = int(got * Decimal(ONE) / (px * (1 + dec(spec.fees.taker_bps / 10_000)))) if spec.quote == got_asset else 0
        return spec.round_qty(max(0, q))

    # -------------------------------------------------------------- orders
    def submit(self, o: SimOrder) -> SimOrder:
        eng = self.engine
        if o.client_id in self.orders:
            self.counters["duplicates"] += 1
            eng.audit("sim_orders", {"correlation_id": o.parent_id, "client_id": o.client_id, "status": "DUPLICATE_REJECTED",
                                     "venue": o.venue, "instrument": o.key, "strategy": o.strategy})
            return self.orders[o.client_id]
        self.orders[o.client_id] = o
        self.recent_orders.append(o)
        self.counters["orders"] += 1
        spec = eng.registry.get(o.key)
        now = eng.clock.mono()
        fee = spec.fees.taker_bps / 10_000
        px = o.limit_px_e8 or (eng.state.instruments[o.key].ask_px if o.side is Side.BUY else eng.state.instruments[o.key].bid_px)
        q_usd = self.valuation.usd(spec.quote)[0] or 0.0
        notional_usd = px / ONE * o.qty_e8 / ONE * q_usd
        if o.limit_px_e8:
            # Round to the tick in the conservative direction (never a worse price than intended).
            o.limit_px_e8 = spec.round_price(o.limit_px_e8, up=o.side is Side.SELL)
            px = o.limit_px_e8
        ok, reasons = self.risk.check_order(
            spec=spec, side=o.side.value, px_e8=px, qty_e8=o.qty_e8, notional_usd=notional_usd,
            available_quote=self.portfolio.available(o.venue, spec.quote),
            available_base=self.portfolio.available(o.venue, spec.base), fee_rate=fee, portfolio=self.portfolio,
            base_mark=self.valuation.usd(spec.base)[0],
            ctx={"correlation_id": o.parent_id, "client_id": o.client_id, "venue": o.venue, "instrument": o.key,
                 "strategy": o.strategy})
        if not ok:
            o.reject_reason = ";".join(reasons)
            self._finalize(o, OrderStatus.REJECTED, now)
            return o
        if o.side is Side.BUY:
            o.reserved = Decimal(px) / Decimal(ONE) * Decimal(o.qty_e8) / Decimal(ONE) * (1 + dec(fee))
            self.portfolio.reserve(o.venue, spec.quote, o.reserved)
        else:
            o.reserved = Decimal(o.qty_e8) / Decimal(ONE)
            self.portfolio.reserve(o.venue, spec.base, o.reserved)
        lat = (self.cfg.processing_delay_ms + self.cfg.order_latency_ms.get(o.venue, 100.0)
               + self.rng.uniform(0, self.cfg.latency_jitter_ms))
        o.arrival_mono_ns = now + int(lat * NS_PER_MS)
        if o.tif is TimeInForce.GTC:
            o.expire_mono_ns = o.arrival_mono_ns + self.cfg.gtc_ttl_ms * NS_PER_MS
        eng.audit("sim_orders", {"correlation_id": o.parent_id, "status": "PENDING", "venue": o.venue,
                                 "instrument": o.key, "strategy": o.strategy, **o.view()})
        eng.scheduler.call_at(o.arrival_mono_ns, lambda t, o=o: self._arrive(o, t))
        return o

    def _release(self, o: SimOrder) -> None:
        r = o.reserved
        if r is None:
            return
        spec = self.engine.registry.get(o.key)
        self.portfolio.release(o.venue, spec.quote if o.side is Side.BUY else spec.base, r)
        o.reserved = None

    def _arrive(self, o: SimOrder, now: int) -> None:
        if o.is_final:
            return
        if self.risk.halted:
            o.reject_reason = f"emergency_stop:{self.risk.halt_reason}"
            self._finalize(o, OrderStatus.CANCELED, now)
            return
        self.engine.metrics.record(f"paper.order_latency.{o.venue}", now - o.created_mono_ns)
        # Release the reservation first: fills are booked against real balances.
        self._release(o)
        fills, reason = self.fill_model.match(o, now)
        if reason:
            o.reject_reason = reason
            self._finalize(o, OrderStatus.REJECTED, now)
            return
        for px, q, src, est in fills:
            self._apply_fill(o, px, q, src, est, now)
        if o.remaining_e8 <= 0:
            self._finalize(o, OrderStatus.FILLED, now)
        elif o.tif is TimeInForce.IOC:
            if not o.filled_qty_e8:
                o.reject_reason = "no_liquidity_within_limit_at_arrival"
            self._finalize(o, OrderStatus.CANCELED, now)
        else:
            o.status = OrderStatus.PARTIALLY_FILLED if o.filled_qty_e8 else OrderStatus.OPEN
            self.resting[o.client_id] = o

    def _apply_fill(self, o: SimOrder, px: int, q: int, src: str, est: bool, now: int) -> None:
        spec = self.engine.registry.get(o.key)
        fee_rate = spec.fees.taker_bps / 10_000 if src != "trade_through" else spec.fees.maker_bps / 10_000
        acct = self.portfolio.apply_fill(o.venue, spec.base, spec.quote, o.side.value, px, q, fee_rate)
        self._fill_seq += 1
        f = SimFill(f"{o.client_id}-f{len(o.fills) + 1}", o.client_id, o.venue, o.key, o.side, px, q,
                    acct["fee_quote"], src, est, now, self.engine.clock.wall())
        o.fills.append(f)
        o.filled_qty_e8 += q
        o.notional_e16 += px * q
        o.fee_quote += acct["fee_quote"]
        o.estimate = o.estimate or est
        self.recent_fills.append(f)
        self.counters["fills"] += 1
        self.engine.audit("sim_fills", {"correlation_id": o.parent_id, "status": "SIMULATED_FILL", "venue": o.venue,
                                        "instrument": o.key, "strategy": o.strategy, **f.view(),
                                        "value_usd": acct["value_usd"], "fee_usd": acct["fee_usd"]})

    def _finalize(self, o: SimOrder, status: OrderStatus, now: int) -> None:
        if o.status in (OrderStatus.FILLED, OrderStatus.CANCELED, OrderStatus.EXPIRED, OrderStatus.REJECTED):
            return
        self._release(o)
        o.status = status
        o.final_mono_ns = now
        self.resting.pop(o.client_id, None)
        if status is OrderStatus.REJECTED:
            self.counters["rejected"] += 1
        self.engine.audit("sim_orders", {"correlation_id": o.parent_id, "status": status.value, "venue": o.venue,
                                         "instrument": o.key, "strategy": o.strategy, **o.view()})
        ex = self.executions.get(o.parent_id)
        if ex is not None:
            self._leg_done(ex, o, now)

    def _expire(self, now: int) -> None:
        for o in list(self.resting.values()):
            if o.expire_mono_ns and now >= o.expire_mono_ns:
                self._finalize(o, OrderStatus.EXPIRED, now)

    def cancel_all(self, reason: str) -> None:
        now = self.engine.clock.mono()
        for o in list(self.orders.values()):
            if not o.is_final:
                o.reject_reason = reason
                self._finalize(o, OrderStatus.CANCELED, now)

    # ---------------------------------------------------------- executions
    def _leg_done(self, ex: Execution, o: SimOrder, now: int) -> None:
        if ex.sequential:
            idx = len(ex.orders) - 1
            if o.filled_qty_e8 > 0 and idx + 1 < len(ex.leg_plans):
                delay = int(self.cfg.leg_latency_ms * NS_PER_MS)
                self.engine.scheduler.call_at(now + delay, lambda t: self._submit_leg(ex, idx + 1, o))
                return
            # last leg done, or a leg produced nothing: remaining legs are not attempted
        elif len(ex.orders) < len(ex.leg_plans) or not all(x.is_final for x in ex.orders):
            return
        self._complete(ex, now)

    def _complete(self, ex: Execution, now: int) -> None:
        legs = ex.orders
        filled = [x for x in legs if x.filled_qty_e8 > 0]
        if not filled:
            risk_like = any(x.reject_reason.startswith(("exchange_filter", "insufficient_balance", "max_",
                                                        "emergency", "no_valuation")) for x in legs)
            status = "REJECTED" if risk_like else "MISSED"
        elif len(legs) == len(ex.leg_plans) and all(x.status is OrderStatus.FILLED for x in legs):
            status = "FILLED"
        else:
            status = "PARTIAL"
        self.counters[{"FILLED": "filled", "PARTIAL": "partial", "MISSED": "missed",
                       "REJECTED": "executions_rejected"}[status]] = self.counters.get(
            {"FILLED": "filled", "PARTIAL": "partial", "MISSED": "missed", "REJECTED": "executions_rejected"}[status], 0) + 1
        cash_usd = 0.0
        flows: dict[str, float] = {}
        for x in legs:
            spec = self.engine.registry.get(x.key)
            notional = x.notional_e16 / ONE / ONE
            qty = x.filled_qty_e8 / ONE
            q_flow = (notional - x.fee_quote) if x.side is Side.SELL else -(notional + x.fee_quote)
            b_flow = -qty if x.side is Side.SELL else qty
            flows[spec.quote] = flows.get(spec.quote, 0.0) + q_flow
            flows[spec.base] = flows.get(spec.base, 0.0) + b_flow
            cash_usd += q_flow * (self.valuation.usd(spec.quote)[0] or 0.0)
        # Mark-to-market P&L of the execution: every asset flow (quote and base,
        # all legs, including unhedged remainders) valued at current marks.
        marked = 0.0
        unpriced = []
        for asset, amt in flows.items():
            if abs(amt) < 1e-15:
                continue
            m = self.valuation.usd(asset)[0]
            if m is None:
                unpriced.append(asset)
                continue
            marked += amt * m
        slips = [s for s in (x.slippage_bps() for x in legs) if s is not None]
        result = {
            "status": status,
            "label": "SIMULATED",
            "pnl_usd": round(marked, 6),
            "pnl_basis": "mark-to-market of all asset flows at completion (SIMULATED)",
            "quote_cashflow_usd": round(cash_usd, 6),
            "asset_flows": {a: round(v, 12) for a, v in flows.items() if abs(v) >= 1e-15},
            "unpriced_assets": unpriced,
            "expected_profit_usd": ex.expected.get("expected_profit_usd"),
            "expected_net_bps": ex.expected.get("net_bps"),
            "expected_slippage_bps": ex.expected.get("slippage_bps"),
            "simulated_slippage_bps": round(sum(slips), 4) if slips else None,
            "legs": [x.view() for x in legs],
            "estimate": any(x.estimate for x in legs),
            "duration_ms": round((now - ex.created_mono_ns) / NS_PER_MS, 3),
            "unhedged": self._unhedged(ex),
        }
        if ex.strategy == "triangular":
            result["note"] = "cash flow covers start-asset legs; intermediate residuals appear as unhedged inventory"
        ex.status = status
        ex.result = result
        self.executions.pop(ex.parent_id, None)
        self.recent_executions.append(ex)
        trig = ex.expected.get("trigger_recv_mono_ns")
        if trig and self.engine.clock.live:
            self.engine.metrics.record(f"paper.recv_to_fill_complete.{ex.strategy}", self.engine.clock.mono() - trig)
        self._mark_episode(ex.episode, result)
        self.engine.audit("audit_log", {"event": "execution_outcome", "correlation_id": ex.parent_id,
                                        "strategy": ex.strategy, "instrument": ex.route_id, "status": status, **result})

    def _unhedged(self, ex: Execution) -> list[dict[str, Any]]:
        out = []
        if ex.strategy == "cross_exchange" and len(ex.orders) == 2:
            b, s = ex.orders
            diff = b.filled_qty_e8 - s.filled_qty_e8
            if diff:
                spec = self.engine.registry.get(b.key)
                out.append({"asset": spec.base, "qty": diff / ONE,
                            "where": "long on buy venue" if diff > 0 else "short vs. plan on sell venue"})
        return out

    @staticmethod
    def _mark_episode(ep: Any, result: dict[str, Any]) -> None:
        if ep is not None:
            ep.execution = result

    # ---------------------------------------------------------------- views
    def snapshot(self) -> dict[str, Any]:
        v = self.portfolio.valuation() if self.portfolio.initialized else None
        return {
            "mode": EXECUTION_MODE,
            "banner": PAPER_BANNER,
            "initialized": self.portfolio.initialized,
            "portfolio": v,
            "daily_pnl_usd": self.risk.daily_pnl(v["pnl_usd"]) if v else None,
            "risk": self.risk.status(),
            "counters": self.counters,
            "open_orders": [o.view() for o in self.orders.values() if not o.is_final][:200],
            "recent_orders": [o.view() for o in list(self.recent_orders)[-200:]][::-1],
            "recent_fills": [f.view() for f in list(self.recent_fills)[-200:]][::-1],
            "recent_executions": [{"parent_id": e.parent_id, "strategy": e.strategy, "route_id": e.route_id,
                                   **{k: v for k, v in e.result.items() if k != "legs"}}
                                  for e in list(self.recent_executions)[-100:]][::-1],
        }


def install_paper(engine: Any) -> PaperEngine | None:
    if not engine.cfg.paper.enabled:
        return None
    p = PaperEngine(engine)
    engine.add_component(p, trades=True)
    return p
