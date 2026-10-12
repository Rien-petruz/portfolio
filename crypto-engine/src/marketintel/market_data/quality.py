"""Quote quality rules (shared by all venues; thresholds are per venue).

=================  =====================================================  ========
Status             Meaning                                                Usable?
=================  =====================================================  ========
``LIVE``           updated within ``quiet_after_ms`` on a healthy feed    yes
``QUIET``          healthy feed, book unchanged > ``quiet_after_ms``      opt-in
``STALE``          no update for ``stale_after_ms``; or the connection    no
                   delivered no frame for ``connection_stall_ms``; or
                   the connection's exchange-event -> receipt delay is
                   above ``max_delivery_lag_ms``
``CROSSED``        bid >= ask                                             no
``ONE_SIDED``      one side empty                                         no
``UNINITIALIZED``  no update since (re)connect / book resync in progress  no
``DISCONNECTED``   connection down                                        no
``UNSUBSCRIBED``   instrument not bound to any connection                 no
=================  =====================================================  ========
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from ..clock import NS_PER_S


class QuoteStatus(StrEnum):
    LIVE = "LIVE"
    QUIET = "QUIET"
    STALE = "STALE"
    ONE_SIDED = "ONE_SIDED"
    CROSSED = "CROSSED"
    UNINITIALIZED = "UNINITIALIZED"
    DISCONNECTED = "DISCONNECTED"
    UNSUBSCRIBED = "UNSUBSCRIBED"


USABLE = frozenset({QuoteStatus.LIVE})
USABLE_INCL_QUIET = frozenset({QuoteStatus.LIVE, QuoteStatus.QUIET})

# A delivery-lag sample older than this no longer describes the feed.
LAG_SAMPLE_TTL_NS = 5 * NS_PER_S


def quote_status(st: Any, now: int, max_delivery_lag_ns: int) -> QuoteStatus:
    sh = st.shard
    if sh is None:
        return QuoteStatus.UNSUBSCRIBED
    if not sh.connected:
        return QuoteStatus.DISCONNECTED
    if not st.book_fresh:
        return QuoteStatus.UNINITIALIZED
    if now - sh.last_msg_mono_ns > st.stall_ns:
        return QuoteStatus.STALE
    if sh.delivery_lag_ns > max_delivery_lag_ns and now - sh.delivery_lag_at_ns < LAG_SAMPLE_TTL_NS:
        return QuoteStatus.STALE
    if st.bid_px <= 0 or st.ask_px <= 0:
        return QuoteStatus.ONE_SIDED
    if st.bid_px >= st.ask_px:
        return QuoteStatus.CROSSED
    age = now - st.book_recv_mono_ns
    if age > st.stale_ns:
        return QuoteStatus.STALE
    if age > st.quiet_ns:
        return QuoteStatus.QUIET
    return QuoteStatus.LIVE
