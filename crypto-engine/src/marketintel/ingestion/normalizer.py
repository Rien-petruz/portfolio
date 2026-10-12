"""Binance wire format -> internal events.

Handles both raw (``/ws/<stream>``) and combined (``/stream?streams=``)
payloads, subscription acknowledgements and error responses. Anything that is
not a well-formed, recognised market event raises :class:`NormalizeError` (or
returns ``None`` for benign control messages) so that callers can count it -
malformed data is never passed downstream.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

import orjson

from ..numeric import parse_e8
from .events import BookTicker, DepthDiff, MarketEvent, ServerShutdown, Trade


class NormalizeError(ValueError):
    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason


def _sym(data: dict) -> str:
    s = data["s"]
    if type(s) is not str or not s:
        raise NormalizeError("bad_symbol", repr(s))
    return s


def _levels(raw: Any) -> list[tuple[int, int]]:
    if not isinstance(raw, list):
        raise NormalizeError("bad_levels", "levels is not a list")
    out = []
    for lvl in raw:
        px = parse_e8(lvl[0])
        qty = parse_e8(lvl[1])
        if px <= 0 or qty < 0:
            raise NormalizeError("bad_levels", f"invalid level {lvl!r}")
        out.append((px, qty))
    return out


class Normalizer:
    __slots__ = ("control_messages", "control_errors", "unknown")

    def __init__(self) -> None:
        self.control_messages = 0
        self.control_errors: list[Any] = []
        self.unknown: Counter[str] = Counter()

    def normalize(
        self, raw: bytes | str, recv_mono_ns: int, recv_wall_ns: int, shard_id: int
    ) -> MarketEvent | None:
        try:
            msg = orjson.loads(raw)
        except orjson.JSONDecodeError as exc:
            raise NormalizeError("invalid_json", str(exc)) from None
        if not isinstance(msg, dict):
            raise NormalizeError("not_an_object")

        data = msg.get("data")
        if data is not None and "stream" in msg:
            if not isinstance(data, dict):
                raise NormalizeError("not_an_object", "combined payload data")
        elif "id" in msg and ("result" in msg or "error" in msg):
            self.control_messages += 1
            if "error" in msg:
                if len(self.control_errors) < 100:
                    self.control_errors.append(msg["error"])
                raise NormalizeError("control_error", str(msg["error"]))
            return None
        else:
            data = msg

        try:
            e = data.get("e")
            if e is None:
                # bookTicker payloads have no "e" field.
                if "b" in data and "a" in data and "u" in data:
                    bid_px = parse_e8(data["b"])
                    bid_qty = parse_e8(data["B"])
                    ask_px = parse_e8(data["a"])
                    ask_qty = parse_e8(data["A"])
                    if bid_px < 0 or ask_px < 0 or bid_qty < 0 or ask_qty < 0:
                        raise NormalizeError("negative_value")
                    return BookTicker(
                        _sym(data), int(data["u"]), bid_px, bid_qty, ask_px, ask_qty,
                        recv_mono_ns, recv_wall_ns, shard_id,
                    )
            elif e == "trade":
                px = parse_e8(data["p"])
                qty = parse_e8(data["q"])
                if px <= 0 or qty <= 0:
                    raise NormalizeError("non_positive_trade")
                return Trade(
                    _sym(data), int(data["t"]), px, qty, int(data["T"]), int(data["E"]),
                    bool(data["m"]), recv_mono_ns, recv_wall_ns, shard_id,
                )
            elif e == "depthUpdate":
                first = int(data["U"])
                final = int(data["u"])
                if final < first:
                    raise NormalizeError("bad_update_range", f"U={first} u={final}")
                return DepthDiff(
                    _sym(data), first, final, int(data["E"]), _levels(data["b"]),
                    _levels(data["a"]), recv_mono_ns, recv_wall_ns, shard_id,
                )
            elif e == "serverShutdown":
                return ServerShutdown(int(data.get("E", 0)), recv_mono_ns, recv_wall_ns, shard_id)
        except NormalizeError:
            raise
        except KeyError as exc:
            raise NormalizeError("missing_field", str(exc)) from None
        except (ValueError, TypeError, IndexError) as exc:
            raise NormalizeError("bad_value", str(exc)) from None

        self.unknown[str(e)] += 1
        raise NormalizeError("unknown_event", str(e))
