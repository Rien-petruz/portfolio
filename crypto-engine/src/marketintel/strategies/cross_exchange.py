"""Cross-exchange discrepancy scanner (event-driven).

For every registry-approved pair (same canonical base asset, VERIFIED
mapping, same market type) both directions are evaluated whenever a quote of
either leg - or of the conversion instrument - changes:

    buy on X at X's ASK, sell on Y at Y's BID     (never mid prices)

Net edge is computed from cash flows, so each cost is applied exactly once::

    cost     = buy_vwap  * qty * (1 + taker_fee_buy)            [buy quote]
    proceeds = sell_vwap * qty * (1 - taker_fee_sell)           [sell quote]
    proceeds/costs in another quote currency are converted at the conversion
    instrument's executable bid/ask with its taker fee
    net_bps  = (proceeds - cost) / cost * 1e4                    [one currency]

``gross_bps`` uses touch prices with the conversion at its mid. The
decomposition (fees, conversion, slippage) is informational; ``net_bps`` is
never "gross minus a fee table".

Size is the minimum of: touch liquidity (or depth within the slippage limit
when a synced local book exists), the configured notional cap, the
conversion instrument's displayed liquidity, and paper inventories; then
rounded down to a multiple of both venues' step sizes.

A candidate is ``VALID`` only if every check passes; otherwise it is
``REJECTED`` with explicit reasons. Rebalancing / transfers between venues
are not assumed to happen within an opportunity's lifetime: they are an
operational process outside this calculation.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from ..clock import NS_PER_MS
from ..exchanges.base import InstrumentSpec, MappingConfidence
from ..exchanges.registry import Conversion, CrossVenuePair
from ..market_data.quality import QuoteStatus
from ..numeric import ONE
from ..opportunities.profitability import floor_to, lcm, qty_within, walk
from ..opportunities.tracker import OpportunityTracker
from ..opportunities.valuation import Valuation

log = logging.getLogger(__name__)

InventoryFn = Callable[[str, str], "float | None"]


class CrossExchangeScanner:
    name = "cross_exchange"

    def __init__(self, engine: Any, *, inventory: InventoryFn | None = None,
                 on_valid: Callable[[Any, dict[str, Any]], None] | None = None) -> None:
        self.engine = engine
        self.cfg = engine.cfg.strategies.cross_exchange
        self.valuation = Valuation(engine)
        self.inventory = inventory
        self.pairs: list[CrossVenuePair] = engine.registry.cross_venue_pairs(use_conversions=self.cfg.use_conversions)
        self.index: dict[str, list[CrossVenuePair]] = {}
        for p in self.pairs:
            for k in (p.a.key, p.b.key) + ((p.conv.spec.key,) if p.conv else ()):
                self.index.setdefault(k, []).append(p)
        self.tracker = OpportunityTracker(engine, self.name, on_valid=on_valid)
        self.evaluations = 0
        self.quick_rejects = 0
        self.last: dict[str, dict[str, Any]] = {}  # route -> latest evaluation (candidates and non-candidates)

    # ------------------------------------------------------------ hooks
    def on_quotes(self, batch: dict[str, int], now: int) -> None:
        if not self.cfg.enabled:
            return
        todo: dict[str, tuple[CrossVenuePair, int]] = {}
        for key, dirty_ns in batch.items():
            for p in self.index.get(key, ()):
                prev = todo.get(p.pair_id)
                if prev is None or dirty_ns < prev[1]:
                    todo[p.pair_id] = (p, dirty_ns)
        for p, dirty_ns in todo.values():
            self.evaluate_pair(p, now, dirty_ns)

    def periodic(self) -> list[tuple[float, Callable[[int], None]]]:
        # Close episodes whose legs stopped updating (no quote event would trigger them).
        return [(self.engine.cfg.engine.summary_interval_ms, self._sweep)]

    def _sweep(self, now: int) -> None:
        for route in list(self.tracker.open):
            ep = self.tracker.open[route]
            pair = next((p for p in self.index.get(ep.last["buy_key"], ()) if
                         {p.a.key, p.b.key} == {ep.last["buy_key"], ep.last["sell_key"]}), None)
            if pair is not None:
                self.evaluate_pair(pair, now, now)

    # ---------------------------------------------------------- evaluation
    def evaluate_pair(self, p: CrossVenuePair, now: int, trigger_ns: int) -> list[dict[str, Any]]:
        out = []
        t0 = self.engine.clock.mono() if self.engine.clock.live else now
        for buy, sell in ((p.a, p.b), (p.b, p.a)):
            route = f"{buy.key}>{sell.key}"
            if route not in self.tracker.open:
                quick = self._quick_gross_bps(p, buy, sell, now)
                if quick is not None and quick <= self.cfg.min_gross_edge_bps:
                    # Not a candidate: skip the full fee/size/depth evaluation (hot-path saver).
                    self.last[route] = {"route_id": route, "gross_bps": round(quick, 4), "net_bps": float("-inf"),
                                        "status": "NO_EDGE", "reasons": [], "buy_key": buy.key, "sell_key": sell.key}
                    self.quick_rejects += 1
                    continue
            ev = self.evaluate(p, buy, sell, now)
            if ev is None:
                continue
            ev["trigger_recv_mono_ns"] = trigger_ns
            self.evaluations += 1
            self.last[ev["route_id"]] = ev
            is_cand = ev["gross_bps"] > self.cfg.min_gross_edge_bps and not ev.get("close_reason")
            self.tracker.update(ev, is_candidate=is_cand, now=now, route_class=f"{p.base}:{buy.venue.value}>{sell.venue.value}")
            out.append(ev)
        if self.engine.clock.live:
            m = self.engine.metrics
            t1 = self.engine.clock.mono()
            m.record("xex.recv_to_signal", t1 - trigger_ns)
            m.record("xex.evaluation", t1 - t0)
        return out

    def _quick_gross_bps(self, p: CrossVenuePair, buy: InstrumentSpec, sell: InstrumentSpec, now: int) -> float | None:
        """Gross edge from touch prices (conversion at mid); None if not computable."""
        inst = self.engine.state.instruments
        bst, sst = inst.get(buy.key), inst.get(sell.key)
        if bst is None or sst is None or bst.ask_px <= 0 or sst.bid_px <= 0:
            return None
        ask, bid = bst.ask_px, sst.bid_px
        if p.conv is not None:
            cst = inst.get(p.conv.spec.key)
            if cst is None or cst.bid_px <= 0 or cst.ask_px <= 0:
                return None
            mid = (cst.bid_px + cst.ask_px) / 2 / ONE
            rate = mid if p.conv.sell_base else 1 / mid   # qa per qb
            if buy.key == p.b.key:
                ask = ask * rate
            else:
                bid = bid * rate
        return (bid - ask) / ask * 10_000

    def _leg(self, spec: InstrumentSpec, now: int) -> tuple[Any, QuoteStatus]:
        st = self.engine.state.instruments.get(spec.key)
        return st, self.engine.state.status(st, now) if st is not None else QuoteStatus.UNSUBSCRIBED

    def _conv_rates(self, conv: Conversion, now: int) -> tuple[dict[str, float] | None, list[str]]:
        st, status = self._leg(conv.spec, now)
        reasons = []
        if status not in (QuoteStatus.LIVE, QuoteStatus.QUIET):
            return None, [f"conversion_unusable:{conv.spec.key}:{status.value}"]
        age_ms = (now - st.book_recv_mono_ns) / NS_PER_MS
        if age_ms > self.cfg.max_conversion_age_ms:
            reasons.append(f"conversion_stale:{age_ms:.0f}ms")
        bid, ask = st.bid_px / ONE, st.ask_px / ONE
        fee = conv.spec.fees.taker_bps / 10_000
        if conv.sell_base:   # qb is the conversion base: qa per qb
            r = {"recv": bid, "pay": ask, "mid": (bid + ask) / 2,
                 "liq_recv": st.bid_qty / ONE, "liq_pay": st.ask_qty / ONE, "units": "qb"}
        else:                # qa is the conversion base: qa per qb = 1/price
            r = {"recv": 1 / ask, "pay": 1 / bid, "mid": 2 / (bid + ask),
                 "liq_recv": st.ask_qty / ONE, "liq_pay": st.bid_qty / ONE, "units": "qa"}
        r["fee"] = fee
        r["age_ms"] = age_ms
        return r, reasons

    def evaluate(self, p: CrossVenuePair, buy: InstrumentSpec, sell: InstrumentSpec, now: int) -> dict[str, Any] | None:
        cfg = self.cfg
        eng = self.engine
        bst, bstatus = self._leg(buy, now)
        sst, sstatus = self._leg(sell, now)
        if bst is None or sst is None or bst.ask_px <= 0 or sst.bid_px <= 0:
            return {"route_id": f"{buy.key}>{sell.key}", "gross_bps": float("-inf"), "net_bps": float("-inf"),
                    "status": "REJECTED", "reasons": ["no_quote"], "close_reason": "data_unavailable",
                    "buy_key": buy.key, "sell_key": sell.key}
        reasons: list[str] = []
        a_quote = p.a.quote  # all amounts are expressed in leg A's quote currency
        conv = p.conv
        rates = None
        if conv is not None:
            rates, r = self._conv_rates(conv, now)
            reasons += r
        # quote currency of each side relative to qa: True if side trades in qb
        buy_in_qb = conv is not None and buy.key == p.b.key
        sell_in_qb = conv is not None and sell.key == p.b.key
        ask = bst.ask_px / ONE
        bid = sst.bid_px / ONE
        if (buy_in_qb or sell_in_qb) and rates is None:
            mid_rate = recv_rate = pay_rate = None
        else:
            mid_rate = rates["mid"] if rates else 1.0
            recv_rate = rates["recv"] if rates else 1.0
            pay_rate = rates["pay"] if rates else 1.0
        if mid_rate is None:
            return {"route_id": f"{buy.key}>{sell.key}", "gross_bps": float("-inf"), "net_bps": float("-inf"),
                    "status": "REJECTED", "reasons": reasons, "close_reason": "conversion_unavailable",
                    "buy_key": buy.key, "sell_key": sell.key}
        ask_qa = ask * (mid_rate if buy_in_qb else 1.0)
        bid_qa = bid * (mid_rate if sell_in_qb else 1.0)
        gross_bps = (bid_qa - ask_qa) / ask_qa * 10_000

        # ---------------------------------------------------------- freshness
        for spec, st, status in ((buy, bst, bstatus), (sell, sst, sstatus)):
            age = (now - st.book_recv_mono_ns) / NS_PER_MS
            if status is not QuoteStatus.LIVE:
                reasons.append(f"quote_not_live:{spec.key}:{status.value}")
            elif age > cfg.max_quote_age_ms:
                reasons.append(f"quote_stale:{spec.key}:{age:.0f}ms")
        quote_age_ms = max(now - bst.book_recv_mono_ns, now - sst.book_recv_mono_ns) / NS_PER_MS
        recv_skew_ms = abs(bst.book_recv_mono_ns - sst.book_recv_mono_ns) / NS_PER_MS
        if recv_skew_ms > cfg.max_recv_skew_ms:
            reasons.append(f"recv_skew:{recv_skew_ms:.0f}ms")
        event_skew_ms = None
        if bst.book_event_time_ns and sst.book_event_time_ns:
            off = eng._offset_ns
            event_skew_ms = abs((bst.book_event_time_ns - off.get(buy.venue.value, 0))
                                - (sst.book_event_time_ns - off.get(sell.venue.value, 0))) / NS_PER_MS
            if event_skew_ms > cfg.max_event_skew_ms:
                reasons.append(f"event_skew:{event_skew_ms:.0f}ms")
        lag_unc = sum((st.shard.delivery_lag_ns if st.shard else 0) for st in (bst, sst)) / NS_PER_MS

        # --------------------------------------------------- mapping / filters
        for spec in (buy, sell):
            if spec.mapping is not MappingConfidence.VERIFIED:
                reasons.append(f"mapping_uncertain:{spec.key}")
            if not spec.filters_known:
                reasons.append(f"filters_unknown:{spec.key}")
            elif not spec.tradable:
                reasons.append(f"not_tradable:{spec.key}")

        # --------------------------------------------------------------- size
        usd_qa, usd_src = self.valuation.usd(a_quote, now)
        usd_per_qa = usd_qa or 0.0
        fee_b = buy.fees.taker_bps / 10_000
        fee_s = sell.fees.taker_bps / 10_000
        caps: dict[str, float] = {}
        max_slip = cfg.max_slippage_bps / 10_000
        buy_book = eng.books.books.get(buy.key)
        sell_book = eng.books.books.get(sell.key)
        depth_buy = buy_book is not None and buy_book.is_synced
        depth_sell = sell_book is not None and sell_book.is_synced
        if depth_buy:
            caps["buy_depth"] = qty_within(buy_book.asks.items(), int(bst.ask_px * (1 + max_slip)), True) / ONE
        else:
            caps["buy_touch"] = bst.ask_qty / ONE
        if depth_sell:
            caps["sell_depth"] = qty_within(reversed(sell_book.bids.items()), int(sst.bid_px * (1 - max_slip)), False) / ONE
        else:
            caps["sell_touch"] = sst.bid_qty / ONE
        if usd_per_qa > 0:
            caps["max_notional"] = cfg.max_notional_usd / (ask_qa * usd_per_qa)
        if rates is not None:
            # conversion amount in its base units; translate to base-asset qty
            if buy_in_qb:   # paying qb: need qb (or sell qa) at conversion "pay" side
                per_unit = ask if rates["units"] == "qb" else ask * pay_rate
                caps["conversion_liquidity"] = rates["liq_pay"] / per_unit
            else:           # receiving qb from the sale
                per_unit = bid if rates["units"] == "qb" else bid * recv_rate
                caps["conversion_liquidity"] = rates["liq_recv"] / per_unit
        if self.inventory is not None:
            quote_bal = self.inventory(buy.venue.value, buy.quote)
            base_bal = self.inventory(sell.venue.value, sell.base)
            if quote_bal is not None:
                caps["inventory_quote"] = max(0.0, quote_bal) / (ask * (1 + fee_b))
            if base_bal is not None:
                caps["inventory_base"] = max(0.0, base_bal)
        cap_name, cap = min(caps.items(), key=lambda kv: kv[1])
        step = lcm(buy.step_size, sell.step_size) if buy.step_size and sell.step_size else 1
        qty_e8 = floor_to(int(cap * ONE), step) if cap > 0 else 0
        if qty_e8 <= 0:
            reasons.append(f"no_executable_size:{cap_name}")
        else:
            if qty_e8 < max(buy.min_qty, sell.min_qty) or any(
                    "notional_below_min" in s.validate_order(px, qty_e8)
                    for s, px in ((buy, bst.ask_px), (sell, sst.bid_px)) if s.filters_known):
                reasons.append("below_exchange_minimum")

        # ---------------------------------------------- executable cash flows
        q = qty_e8 if qty_e8 > 0 else max(step, 1)
        if depth_buy:
            filled_b, notional_b, _ = walk(buy_book.asks.items(), q)
        else:
            filled_b, notional_b = min(q, bst.ask_qty), min(q, bst.ask_qty) * bst.ask_px
        if depth_sell:
            filled_s, notional_s, _ = walk(reversed(sell_book.bids.items()), q)
        else:
            filled_s, notional_s = min(q, sst.bid_qty), min(q, sst.bid_qty) * sst.bid_px
        vb = notional_b / filled_b / ONE if filled_b else ask
        vs = notional_s / filled_s / ONE if filled_s else bid
        qf = q / ONE
        cost = vb * qf * (1 + fee_b)
        proceeds = vs * qf * (1 - fee_s)
        conv_cost_bps = 0.0
        if buy_in_qb:
            cost = cost * pay_rate * (1 + rates["fee"])  # type: ignore[index,operator]
            conv_cost_bps = ((pay_rate / mid_rate) * (1 + rates["fee"]) - 1) * 10_000  # type: ignore[index,operator]
        if sell_in_qb:
            proceeds = proceeds * recv_rate * (1 - rates["fee"])  # type: ignore[index,operator]
            conv_cost_bps = (1 - (recv_rate / mid_rate) * (1 - rates["fee"])) * 10_000  # type: ignore[index,operator]
        net_bps = (proceeds - cost) / cost * 10_000 if cost > 0 else float("-inf")
        slippage_bps = ((vb - ask) / ask + (bid - vs) / bid) * 10_000
        fee_bps = (fee_b + fee_s) * 10_000
        if slippage_bps > cfg.max_slippage_bps + 1e-9:
            reasons.append(f"slippage_above_max:{slippage_bps:.2f}bps")
        touch_liq_usd = min(bst.ask_qty / ONE * ask_qa, sst.bid_qty / ONE * bid_qa) * usd_per_qa
        if usd_qa is None:
            reasons.append(f"valuation_unavailable:{a_quote}")
        elif touch_liq_usd < cfg.min_liquidity_usd:
            reasons.append(f"insufficient_liquidity:{touch_liq_usd:.0f}usd")
        if net_bps < cfg.min_net_edge_bps:
            reasons.append(f"net_below_threshold:{net_bps:.2f}<{cfg.min_net_edge_bps}bps")
        expected_profit_usd = (proceeds - cost) * usd_per_qa if qty_e8 > 0 else 0.0
        return {
            "strategy": self.name,
            "route_id": f"{buy.key}>{sell.key}",
            "route_class": f"{p.base}:{buy.venue.value}>{sell.venue.value}",
            "base": p.base,
            "buy_key": buy.key, "sell_key": sell.key,
            "buy_venue": buy.venue.value, "sell_venue": sell.venue.value,
            "buy_quote_ccy": buy.quote, "sell_quote_ccy": sell.quote, "valuation_ccy": a_quote,
            "conversion": conv.spec.key if conv else None,
            "conversion_rate_source": "market" if conv else "identical_quote",
            "buy_ask": ask, "sell_bid": bid, "buy_vwap": vb, "sell_vwap": vs,
            "gross_bps": round(gross_bps, 4), "fee_bps": round(fee_bps, 4),
            "conversion_bps": round(conv_cost_bps, 4), "slippage_bps": round(slippage_bps, 4),
            "net_bps": round(net_bps, 4),
            "qty": qty_e8 / ONE, "qty_e8": qty_e8, "size_limited_by": cap_name,
            "max_executable_qty": round(cap, 10),
            "notional_quote": round(vb * qty_e8 / ONE, 8),
            "notional_usd": round(vb * qty_e8 / ONE * (mid_rate if buy_in_qb else 1.0) * usd_per_qa, 4),
            "expected_profit_usd": round(expected_profit_usd, 6),
            "liquidity_usd": round(touch_liq_usd, 2),
            "usd_rate_source": usd_src,
            "depth_model": f"buy:{'depth' if depth_buy else 'touch'},sell:{'depth' if depth_sell else 'touch'}",
            "quote_age_ms": round(quote_age_ms, 2),
            "recv_skew_ms": round(recv_skew_ms, 2),
            "event_skew_ms": None if event_skew_ms is None else round(event_skew_ms, 2),
            "skew_uncertainty_ms": round(lag_unc, 2),
            "est_execution_latency_ms": cfg.est_execution_latency_ms,
            "status": "VALID" if not reasons else "REJECTED",
            "reasons": reasons,
            "validation": "theoretical",
            "detected_mono_ns": now,
            "detected_wall_ns": eng.clock.wall(),
        }

    # ---------------------------------------------------------------- views
    def snapshot(self, limit: int = 200) -> dict[str, Any]:
        rows = sorted(self.last.values(), key=lambda e: (-e["net_bps"] if e["net_bps"] != float("-inf") else 1e18,
                                                          -e.get("gross_bps", -1e18)))
        return {"pairs": len(self.pairs), "evaluations": self.evaluations, "quick_rejects": self.quick_rejects,
                "tracker": self.tracker.stats(),
                "open": self.tracker.ranked(limit), "recent_closed": self.tracker.recent_closed(50),
                "scanner": [r for r in rows if "buy_ask" in r][:limit]}
