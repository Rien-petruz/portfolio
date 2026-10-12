"""Fast RFC 3339 timestamp parsing (exchange timestamps with up to ns precision).

``"2023-02-09T20:30:37.167359596Z"`` -> integer ns since the epoch. The
seconds part changes once per second, so it is cached; only the fraction is
parsed per call.
"""

from __future__ import annotations

import calendar
import time

_cache_prefix = ""
_cache_base = 0


def rfc3339_to_ns(s: str) -> int:
    global _cache_prefix, _cache_base
    if len(s) < 20 or s[10] not in "Tt ":
        raise ValueError(f"not an RFC 3339 timestamp: {s!r}")
    prefix = s[:19]
    if prefix != _cache_prefix:
        _cache_base = calendar.timegm(time.strptime(prefix, "%Y-%m-%dT%H:%M:%S" if s[10] in "Tt" else "%Y-%m-%d %H:%M:%S")) * 1_000_000_000
        _cache_prefix = prefix
    base = _cache_base
    rest = s[19:]
    frac_ns = 0
    if rest.startswith("."):
        end = 1
        while end < len(rest) and rest[end].isdigit():
            end += 1
        digits = rest[1:end][:9]
        if digits:
            frac_ns = int(digits.ljust(9, "0"))
        rest = rest[end:]
    if rest in ("Z", "z", "", "+00:00"):
        return base + frac_ns
    sign = 1 if rest[0] == "+" else -1
    hh, mm = int(rest[1:3]), int(rest[4:6])
    return base + frac_ns - sign * (hh * 3600 + mm * 60) * 1_000_000_000
