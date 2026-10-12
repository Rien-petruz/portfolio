"""Paper-trading-only safety boundary.

This build cannot place, amend or cancel real orders, and cannot withdraw:

* There is no authenticated exchange client and no order endpoint anywhere
  in the code base (enforced by tests/unit/test_paper_only.py, which scans the
  source tree).
* All exchange HTTP traffic goes through :class:`ReadOnlyHttp`, which rejects
  every method other than GET before the request leaves the process and never
  sends credentials.
* WebSocket connections only send public market-data subscription messages
  (also enforced by the scanning test).
* Configuration has no live-execution setting; ``execution.mode`` accepts only
  ``"paper"``.
"""

from __future__ import annotations

EXECUTION_MODE = "PAPER"
PAPER_BANNER = "PAPER TRADING ONLY - simulated orders and fills; no real orders can be placed"


class PaperOnlyViolation(RuntimeError):
    """Raised if any code path attempts a non-read-only exchange request."""
