"""Opportunity episode lifecycle: candidate -> validation(s) -> outcome.

An *episode* starts the first time a route's gross edge (executable prices,
before costs) is positive, and ends when that is no longer true or when a
leg's data stops being usable. Within an episode every change of validation
status/reasons is recorded, so both the initial candidate and every later
validation decision are auditable. Episode ids are deterministic
(strategy, route, start time) which makes downstream simulated orders
idempotent per episode.

Persisted (append-only): ``opportunity_candidates`` on open,
``opportunity_validations`` on each status change, ``opportunity_outcomes``
on close (lifetime, peak edge, execution outcome).
"""

from __future__ import annotations

import hashlib
import statistics
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..clock import NS_PER_MS


@dataclass
class Episode:
    episode_id: str
    strategy: str
    route_id: str
    opened_mono_ns: int
    opened_wall_ns: int
    first: dict[str, Any]
    last: dict[str, Any]
    peak_net_bps: float
    peak: dict[str, Any]
    updates: int = 1
    status: str = "CANDIDATE"
    reasons: tuple[str, ...] = ()
    ever_valid: bool = False
    first_valid_mono_ns: int = 0
    transitions: list[dict[str, Any]] = field(default_factory=list)
    closed_mono_ns: int = 0
    close_reason: str = ""
    execution: dict[str, Any] | None = None

    @property
    def lifetime_ms(self) -> float:
        end = self.closed_mono_ns or self.last.get("detected_mono_ns", self.opened_mono_ns)
        return (end - self.opened_mono_ns) / NS_PER_MS

    def view(self) -> dict[str, Any]:
        return {
            "episode_id": self.episode_id, "strategy": self.strategy, "route_id": self.route_id,
            "status": self.status, "reasons": list(self.reasons), "ever_valid": self.ever_valid,
            "opened_wall_ns": self.opened_wall_ns, "lifetime_ms": round(self.lifetime_ms, 1),
            "updates": self.updates, "peak_net_bps": round(self.peak_net_bps, 3),
            "closed": bool(self.closed_mono_ns), "close_reason": self.close_reason,
            "current": self.last, "first": self.first, "execution": self.execution,
        }


class OpportunityTracker:
    def __init__(self, engine: Any, strategy: str, *, on_valid: Callable[[Episode, dict[str, Any]], None] | None = None,
                 keep_closed: int = 500) -> None:
        self.engine = engine
        self.strategy = strategy
        self.on_valid = on_valid
        self.open: dict[str, Episode] = {}
        self.closed: deque[Episode] = deque(maxlen=keep_closed)
        self.lifetimes_ms: dict[str, deque[float]] = {}
        self.opened = 0
        self.validated = 0
        self.rejected_validations = 0

    @staticmethod
    def make_id(strategy: str, route: str, t_ns: int) -> str:
        return hashlib.sha1(f"{strategy}|{route}|{t_ns}".encode(), usedforsecurity=False).hexdigest()[:16]

    def est_lifetime_ms(self, route_class: str) -> float | None:
        d = self.lifetimes_ms.get(route_class)
        return statistics.median(d) if d and len(d) >= 5 else None

    def update(self, ev: dict[str, Any], *, is_candidate: bool, now: int, route_class: str = "") -> Episode | None:
        route = ev["route_id"]
        ep = self.open.get(route)
        if not is_candidate:
            if ep is not None:
                self._close(ep, now, ev.get("close_reason") or "edge_gone", ev)
            return None
        status = ev["status"]
        reasons = tuple(ev.get("reasons", ()))
        if ep is None:
            ep = Episode(self.make_id(self.strategy, route, now), self.strategy, route, now, self.engine.clock.wall(),
                         ev, ev, ev["net_bps"], ev)
            self.open[route] = ep
            self.opened += 1
            ev["episode_id"] = ep.episode_id
            ev["est_lifetime_ms"] = self.est_lifetime_ms(route_class or route)
            self.engine.audit("opportunity_candidates", {"correlation_id": ep.episode_id, "strategy": self.strategy,
                                                         "instrument": route, "status": status, **ev})
            self._transition(ep, status, reasons, ev, now)
        else:
            ev["episode_id"] = ep.episode_id
            ev["est_lifetime_ms"] = ep.first.get("est_lifetime_ms")
            ep.last = ev
            ep.updates += 1
            if ev["net_bps"] > ep.peak_net_bps:
                ep.peak_net_bps, ep.peak = ev["net_bps"], ev
            if status != ep.status or reasons != ep.reasons:
                self._transition(ep, status, reasons, ev, now)
        return ep

    def _transition(self, ep: Episode, status: str, reasons: tuple[str, ...], ev: dict[str, Any], now: int) -> None:
        became_valid = status == "VALID" and ep.status != "VALID"
        ep.status, ep.reasons = status, reasons
        rec = {"t_ms": (now - ep.opened_mono_ns) / NS_PER_MS, "status": status, "reasons": list(reasons),
               "net_bps": ev["net_bps"]}
        if len(ep.transitions) < 50:
            ep.transitions.append(rec)
        if status == "VALID":
            self.validated += 1
        else:
            self.rejected_validations += 1
        self.engine.audit("opportunity_validations", {
            "correlation_id": ep.episode_id, "strategy": self.strategy, "instrument": ep.route_id, "status": status,
            "reasons": list(reasons), "net_bps": ev["net_bps"], "gross_bps": ev["gross_bps"],
            "expected_profit_usd": ev.get("expected_profit_usd"), "qty": ev.get("qty"),
            "quote_age_ms": ev.get("quote_age_ms"), "recv_skew_ms": ev.get("recv_skew_ms")})
        if became_valid:
            first_time = not ep.ever_valid
            ep.ever_valid = True
            if first_time:
                ep.first_valid_mono_ns = now
                if self.on_valid is not None:
                    self.on_valid(ep, ev)

    def _close(self, ep: Episode, now: int, reason: str, ev: dict[str, Any] | None) -> None:
        ep.closed_mono_ns = now
        ep.close_reason = reason
        self.open.pop(ep.route_id, None)
        self.closed.append(ep)
        cls = ep.first.get("route_class", ep.route_id)
        self.lifetimes_ms.setdefault(cls, deque(maxlen=200)).append(ep.lifetime_ms)
        self.engine.audit("opportunity_outcomes", {
            "correlation_id": ep.episode_id, "strategy": self.strategy, "instrument": ep.route_id,
            "status": "EXECUTED" if ep.execution else ("VALID_NOT_EXECUTED" if ep.ever_valid else "NEVER_VALID"),
            "lifetime_ms": ep.lifetime_ms, "peak_net_bps": ep.peak_net_bps, "updates": ep.updates,
            "close_reason": reason, "ever_valid": ep.ever_valid, "transitions": ep.transitions,
            "execution": ep.execution})

    def close_all(self, now: int, reason: str) -> None:
        for ep in list(self.open.values()):
            self._close(ep, now, reason, None)

    def ranked(self, limit: int = 100) -> list[dict[str, Any]]:
        eps = sorted(self.open.values(), key=lambda e: (e.status != "VALID",
                                                        -(e.last.get("expected_profit_usd") or 0.0),
                                                        -e.last["net_bps"]))
        return [e.view() for e in eps[:limit]]

    def recent_closed(self, limit: int = 100) -> list[dict[str, Any]]:
        return [e.view() for e in list(self.closed)[-limit:][::-1]]

    def stats(self) -> dict[str, Any]:
        closed = list(self.closed)
        lt = [e.lifetime_ms for e in closed]
        return {
            "open": len(self.open), "opened_total": self.opened, "closed_kept": len(closed),
            "valid_transitions": self.validated, "rejected_transitions": self.rejected_validations,
            "ever_valid_closed": sum(1 for e in closed if e.ever_valid),
            "executed_closed": sum(1 for e in closed if e.execution),
            "median_lifetime_ms": round(statistics.median(lt), 1) if lt else None,
        }
