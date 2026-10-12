"""Binance wire format -> normalized events.

Handles raw (``/ws/<stream>``) and combined (``/stream?streams=``) payloads,
subscription acknowledgements and error responses. Anything not a
well-formed, recognised market event raises :class:`DecodeError` (benign
control messages return ``None``) so callers can count it.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

import orjson

from ...clock import NS_PER_MS
from ...market_data.events import BUY, SELL, ConnectionNotice, DepthDiff, Quote, Trade
from ...numeric import parse_e8
from ..base import FrameDecoder
from ..errors import DecodeError

# Kept for compatibility with earlier imports.
NormalizeError = DecodeError


def _levels(raw: Any) -> list[tuple[int, int]]:
    if not isinstance(raw, list):
        raise DecodeError("bad_levels", "levels is not a list")
    out = []
    for lvl in raw:
        px = parse_e8(lvl[0])
        qty = parse_e8(lvl[1])
        if px <= 0 or qty < 0:
            raise DecodeError("bad_levels", f"invalid level {lvl!r}")
        out.append((px, qty))
    return out


class BinanceDecoder(FrameDecoder):
    __slots__ = ("conn_id", "keys", "control_messages", "control_errors", "unknown")

    def __init__(self, conn_id: int, symbols: list[str] | None = None) -> None:
        self.conn_id = conn_id
        # native symbol -> engine key; unknown symbols still decode (key built on the fly)
        self.keys: dict[str, str] = {s: f"BINANCE:{s}" for s in symbols or ()}
        self.control_messages = 0
        self.control_errors: list[Any] = []
        self.unknown: Counter[str] = Counter()

    def _key(self, data: dict) -> str:
        s = data["s"]
        k = self.keys.get(s)
        if k is None:
            if type(s) is not str or not s:
                raise DecodeError("bad_symbol", repr(s))
            k = self.keys[s] = f"BINANCE:{s}"
        return k

    def decode(self, raw: bytes, recv_mono_ns: int, recv_wall_ns: int) -> Any:
        try:
            msg = orjson.loads(raw)
        except orjson.JSONDecodeError as exc:
            raise DecodeError("invalid_json", str(exc)) from None
        if not isinstance(msg, dict):
            raise DecodeError("not_an_object")
        data = msg.get("data")
        if data is not None and "stream" in msg:
            if not isinstance(data, dict):
                raise DecodeError("not_an_object", "combined payload data")
        elif "id" in msg and ("result" in msg or "error" in msg):
            self.control_messages += 1
            if "error" in msg:
                if len(self.control_errors) < 100:
                    self.control_errors.append(msg["error"])
                raise DecodeError("control_error", str(msg["error"]))
            return None
        else:
            data = msg
        conn = self.conn_id
        try:
            e = data.get("e")
            if e is None:
                if "b" in data and "a" in data and "u" in data:
                    bid_px = parse_e8(data["b"])
                    bid_qty = parse_e8(data["B"])
                    ask_px = parse_e8(data["a"])
                    ask_qty = parse_e8(data["A"])
                    if bid_px < 0 or ask_px < 0 or bid_qty < 0 or ask_qty < 0:
                        raise DecodeError("negative_value")
                    return Quote(self._key(data), int(data["u"]), bid_px, bid_qty, ask_px, ask_qty,
                                 recv_mono_ns, recv_wall_ns, conn, 0)
            elif e == "trade":
                px = parse_e8(data["p"])
                qty = parse_e8(data["q"])
                if px <= 0 or qty <= 0:
                    raise DecodeError("non_positive_trade")
                # "m": buyer is the maker -> the seller was the aggressor.
                return Trade(self._key(data), int(data["t"]), px, qty, SELL if data["m"] else BUY,
                             int(data["T"]) * NS_PER_MS, int(data["E"]) * NS_PER_MS,
                             recv_mono_ns, recv_wall_ns, conn)
            elif e == "depthUpdate":
                first = int(data["U"])
                final = int(data["u"])
                if final < first:
                    raise DecodeError("bad_update_range", f"U={first} u={final}")
                return DepthDiff(self._key(data), first, final, int(data["E"]) * NS_PER_MS,
                                 _levels(data["b"]), _levels(data["a"]), recv_mono_ns, recv_wall_ns, conn)
            elif e == "serverShutdown":
                return ConnectionNotice("server_shutdown", "serverShutdown event", conn, recv_mono_ns,
                                        int(data.get("E", 0)) * NS_PER_MS)
        except DecodeError:
            raise
        except KeyError as exc:
            raise DecodeError("missing_field", str(exc)) from None
        except (ValueError, TypeError, IndexError) as exc:
            raise DecodeError("bad_value", str(exc)) from None
        self.unknown[str(e)] += 1
        raise DecodeError("unknown_event", str(e))
