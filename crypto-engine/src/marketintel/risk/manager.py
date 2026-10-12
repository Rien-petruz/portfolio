"""Pre-trade risk controls for simulated execution.

Every decision - accepted or rejected - is recorded (``risk_events``) with
explicit reasons.

Opportunity-level checks: emergency stop, health gating, minimum net edge,
maximum quote age, maximum cross-venue skew, maximum expected slippage,
minimum available liquidity, signal frequency per strategy+route, duplicate
suppression within a window.

Order-level checks: exchange filters (tick/step/min notional), maximum order
notional, available (unreserved) balance, maximum position per asset,
maximum exposure per venue and in total.

Emergency stop is *latched*: automatic triggers (daily loss limit, feed
health DOWN if configured, repeated abnormal simulated rejects) and manual
triggers stop all new simulated orders and cancel resting ones until
``resume()`` is called explicitly.
"""

from __future__ import annotations

import datetime as dt
from collections import deque
from decimal import Decimal
from typing import Any

from ..clock import NS_PER_MS, NS_PER_S
from ..config import RiskConfig


class RiskManager:
    def __init__(self, engine: Any, cfg: RiskConfig) -> None:
        self.engine = engine
        self.cfg = cfg
        self.halted = False
        self.halt_reason = ""
        self.halted_at_wall_ns = 0
        self.health_blocked = False
        self._freq: dict[str, deque[int]] = {}
        self._recent_routes: dict[str, int] = {}
        self.decisions = {"accepted": 0, "rejected": 0}
        self.reject_reasons: dict[str, int] = {}
        self.day = ""
        self.day_start_pnl = 0.0

    # -------------------------------------------------------------- record
    def _record(self, kind: str, ok: bool, reasons: list[str], ctx: dict[str, Any]) -> None:
        self.decisions["accepted" if ok else "rejected"] += 1
        for r in reasons:
            k = r.split(":")[0]
            self.reject_reasons[k] = self.reject_reasons.get(k, 0) + 1
        # Every decision is part of the audit trail (one per opportunity/order, never per tick).
        self.engine.audit("risk_events", {"event": kind, "status": "ACCEPTED" if ok else "REJECTED",
                                          "reasons": reasons, **ctx})

    # ---------------------------------------------------- opportunity level
    def check_opportunity(self, ev: dict[str, Any], now: int) -> tuple[bool, list[str]]:
        cfg = self.cfg
        r: list[str] = []
        if self.halted:
            r.append(f"emergency_stop:{self.halt_reason}")
        if self.health_blocked:
            r.append("feed_health_blocked")
        if ev.get("net_bps", -1e9) < cfg.min_net_edge_bps:
            r.append(f"min_net_edge:{ev.get('net_bps'):.2f}<{cfg.min_net_edge_bps}")
        if (ev.get("quote_age_ms") or 0) > cfg.max_quote_age_ms:
            r.append(f"max_quote_age:{ev['quote_age_ms']:.0f}ms")
        skew = max(ev.get("recv_skew_ms") or 0, ev.get("event_skew_ms") or 0)
        if skew > cfg.max_skew_ms:
            r.append(f"max_skew:{skew:.0f}ms")
        if (ev.get("slippage_bps") or 0) > cfg.max_slippage_bps:
            r.append(f"max_slippage:{ev['slippage_bps']:.2f}bps")
        if (ev.get("liquidity_usd") or 0) < cfg.min_liquidity_usd:
            r.append(f"min_liquidity:{ev.get('liquidity_usd')}")
        key = f"{ev.get('strategy')}|{ev.get('route_id')}"
        q = self._freq.setdefault(key, deque())
        while q and now - q[0] > 60 * NS_PER_S:
            q.popleft()
        if len(q) >= cfg.max_signals_per_minute:
            r.append(f"max_signal_frequency:{len(q)}/min")
        last = self._recent_routes.get(key)
        if last is not None and now - last < cfg.duplicate_window_ms * NS_PER_MS:
            r.append("duplicate_within_window")
        ok = not r
        if ok:
            q.append(now)
            self._recent_routes[key] = now
        self._record("opportunity_check", ok, r, {"correlation_id": ev.get("episode_id"),
                                                  "strategy": ev.get("strategy"), "instrument": ev.get("route_id"),
                                                  "net_bps": ev.get("net_bps")})
        return ok, r

    # ---------------------------------------------------------- order level
    def check_order(self, *, spec: Any, side: str, px_e8: int, qty_e8: int, notional_usd: float,
                    available_quote: float | None, available_base: float | None, fee_rate: float,
                    portfolio: Any, base_mark: float | None, ctx: dict[str, Any]) -> tuple[bool, list[str]]:
        cfg = self.cfg
        r: list[str] = []
        if self.halted:
            r.append(f"emergency_stop:{self.halt_reason}")
        r += [f"exchange_filter:{e}" for e in spec.validate_order(px_e8, qty_e8)]
        if notional_usd > cfg.max_order_notional_usd:
            r.append(f"max_order_notional:{notional_usd:.2f}")
        qty = qty_e8 / 1e8
        if side == "BUY":
            need = px_e8 / 1e8 * qty * (1 + fee_rate)
            if available_quote is None or available_quote + 1e-12 < need:
                r.append(f"insufficient_balance:{spec.quote}")
        elif available_base is None or available_base + 1e-12 < qty:
            r.append(f"insufficient_balance:{spec.base}")
        if base_mark is None:
            r.append(f"no_valuation:{spec.base}")
        elif portfolio is not None:
            delta = Decimal(qty_e8) / Decimal(100_000_000) * (1 if side == "BUY" else -1)
            a_exp, v_exp, t_exp = portfolio.exposure_after(spec.venue.value, spec.base, delta, Decimal(str(base_mark)))
            if a_exp > Decimal(str(cfg.max_position_usd_per_asset)):
                r.append(f"max_position_per_asset:{float(a_exp):.0f}")
            if v_exp > Decimal(str(cfg.max_exposure_usd_per_venue)):
                r.append(f"max_exposure_per_venue:{float(v_exp):.0f}")
            if t_exp > Decimal(str(cfg.max_total_exposure_usd)):
                r.append(f"max_total_exposure:{float(t_exp):.0f}")
        ok = not r
        self._record("order_check", ok, r, ctx)
        return ok, r

    # ------------------------------------------------------------ halting
    def emergency_stop(self, reason: str, *, manual: bool = False) -> None:
        if self.halted:
            return
        self.halted = True
        self.halt_reason = reason
        self.halted_at_wall_ns = self.engine.clock.wall()
        self._record("emergency", True, [reason], {"status": "HALTED", "manual": manual})

    def resume(self, *, by: str = "manual") -> None:
        if not self.halted:
            return
        self.halted = False
        self._record("emergency", True, [f"resumed_by:{by}"], {"status": "RESUMED", "previous": self.halt_reason})
        self.halt_reason = ""

    def on_summary(self, now: int, health: dict[str, Any], pnl_usd: float | None) -> None:
        self.health_blocked = health.get("status") in self.cfg.halt_on_health
        if pnl_usd is None:
            return
        day = dt.datetime.fromtimestamp(self.engine.clock.wall() / 1e9, dt.UTC).strftime("%Y-%m-%d")
        if day != self.day:
            self.day, self.day_start_pnl = day, pnl_usd
        daily = pnl_usd - self.day_start_pnl
        if daily < -self.cfg.max_daily_loss_usd:
            self.emergency_stop(f"max_daily_loss:{daily:.2f}")

    def daily_pnl(self, pnl_usd: float | None) -> float | None:
        return None if pnl_usd is None else pnl_usd - self.day_start_pnl

    def status(self) -> dict[str, Any]:
        return {"halted": self.halted, "halt_reason": self.halt_reason, "halted_at_wall_ns": self.halted_at_wall_ns,
                "health_blocked": self.health_blocked, "decisions": self.decisions,
                "reject_reasons": self.reject_reasons, "limits": self.cfg.model_dump()}
