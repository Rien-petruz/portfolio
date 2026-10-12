"""USD valuation of assets from live, usable market data.

Used for sizing limits, P&L and exposure. Rates come from markets in the
monitored universe (``ASSET/USD``, ``ASSET/USDT`` x ``USDT/USD``, ...). If no
usable market exists for a stablecoin, a 1.0 peg is used and *labelled*
``assumed_peg`` so downstream reports can show the assumption.
"""

from __future__ import annotations

from typing import Any

from ..market_data.quality import QuoteStatus
from ..numeric import ONE

_STABLE = {"USDT", "USDC", "FDUSD"}
_PREF_QUOTES = ("USD", "USDT", "USDC", "FDUSD")


class Valuation:
    def __init__(self, engine: Any, cache_ns: int = 100_000_000) -> None:
        self.engine = engine
        self.cache_ns = cache_ns
        self._cache: dict[str, tuple[float | None, str]] = {}
        self._cache_at = -1
        self._by_base: dict[str, list[Any]] = {}
        for s in engine.registry.by_key.values():
            if s.alias_of is None and s.quote in _PREF_QUOTES:
                self._by_base.setdefault(s.base, []).append(s)
        for lst in self._by_base.values():
            lst.sort(key=lambda s: (_PREF_QUOTES.index(s.quote), s.venue.value))

    def _mid(self, key: str, now: int) -> float | None:
        st = self.engine.state.instruments.get(key)
        if st is None:
            return None
        if self.engine.state.status(st, now) not in (QuoteStatus.LIVE, QuoteStatus.QUIET):
            return None
        return (st.bid_px + st.ask_px) / (2 * ONE)

    def usd(self, asset: str, now: int | None = None, _depth: int = 0) -> tuple[float | None, str]:
        """(USD per unit of ``asset``, source description)."""
        if asset == "USD":
            return 1.0, "numeraire"
        now = self.engine.clock.mono() if now is None else now
        if now - self._cache_at > self.cache_ns:
            self._cache.clear()
            self._cache_at = now
        hit = self._cache.get(asset)
        if hit is not None:
            return hit
        res: tuple[float | None, str] = (None, "unavailable")
        if _depth < 3:
            for s in self._by_base.get(asset, ()):
                m = self._mid(s.key, now)
                if m is None:
                    continue
                q, src = self.usd(s.quote, now, _depth + 1)
                if q is not None:
                    res = (m * q, f"{s.key}" + ("" if s.quote == "USD" else f" x {src}"))
                    break
        if res[0] is None and asset in _STABLE:
            res = (1.0, "assumed_peg")
        self._cache[asset] = res
        return res

    def usd_value(self, asset: str, amount: float, now: int | None = None) -> float | None:
        r, _ = self.usd(asset, now)
        return None if r is None else amount * r
