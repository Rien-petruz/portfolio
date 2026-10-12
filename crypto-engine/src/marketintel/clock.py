"""Clock helpers.

Two clocks are used deliberately and never mixed:

* ``mono_ns`` (CLOCK_MONOTONIC) for *local* durations: receive -> processed,
  queue delay, event-loop lag, staleness. It never jumps with NTP adjustments.
* ``wall_ns`` (CLOCK_REALTIME) only to compare against exchange event times
  (``E``/``T`` fields, milliseconds since the Unix epoch). Such comparisons
  include network latency *and* clock skew between our host and Binance, so
  they are reported separately and corrected with an estimated offset when one
  is available.
"""

from __future__ import annotations

import time

mono_ns = time.monotonic_ns
wall_ns = time.time_ns

NS_PER_MS = 1_000_000
NS_PER_US = 1_000
NS_PER_S = 1_000_000_000


def wall_ms() -> int:
    return time.time_ns() // NS_PER_MS
