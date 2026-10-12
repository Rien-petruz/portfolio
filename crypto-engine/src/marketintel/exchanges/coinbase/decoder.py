"""Coinbase Advanced Trade WebSocket messages -> normalized events.

Envelope (all public channels)::

    {"channel": "l2_data" | "market_trades" | "heartbeats" | "subscriptions",
     "client_id": "", "timestamp": "<RFC3339 ns>", "sequence_num": <int>,
     "events": [...]}

* ``sequence_num`` is per *connection* across all channels. A gap means a
  message was lost and every book on this connection is suspect, so the
  decoder emits ``ConnectionNotice("resync_required")`` and the connection is
  recycled (fresh subscription => fresh snapshots).
* level2 (``l2_data``) events are ``snapshot`` (full book) or ``update``
  (absolute new quantity per level; 0 removes). Sides ``bid`` / ``offer``.
* ``market_trades`` ``snapshot`` events replay recent history on subscribe;
  they are counted but not treated as new trades (their receive time would
  be meaningless for flow features).
* Trade ``side``: whether Coinbase reports the maker or taker side is not
  stated unambiguously in the SDK; it is configurable (``trade_side`` =
  "taker" | "maker" | "unknown", default "unknown" => aggressor not used).
"""

from __future__ import annotations

from collections import Counter
from typing import Any

import orjson

from ...market_data.events import BUY, SELL, UNKNOWN_SIDE, BookDelta, BookSnapshot, ConnectionNotice, Trade
from ...numeric import parse_e8
from ...timeparse import rfc3339_to_ns
from ..base import FrameDecoder
from ..errors import DecodeError

_BID = frozenset(("bid", "BID", "buy", "BUY"))
_ASK = frozenset(("offer", "OFFER", "ask", "ASK", "sell", "SELL"))


class CoinbaseDecoder(FrameDecoder):
    def __init__(self, conn_id: int, sock_uid: int, products: list[str] | None = None,
                 trade_side: str = "unknown") -> None:
        self.conn_id = conn_id
        self.sock_uid = sock_uid
        self.keys = {p: f"COINBASE:{p}" for p in products or ()}
        self.trade_side = trade_side
        self.last_seq = -1
        self.gaps = 0
        self.out_of_order = 0
        self.heartbeats = 0
        self.history_trades_skipped = 0
        self.control_messages = 0
        self.control_errors: list[Any] = []
        self.unknown: Counter[str] = Counter()

    def reset(self) -> None:
        self.last_seq = -1

    def _key(self, pid: Any) -> str:
        k = self.keys.get(pid)
        if k is None:
            if type(pid) is not str or not pid:
                raise DecodeError("bad_symbol", repr(pid))
            k = self.keys[pid] = f"COINBASE:{pid}"
        return k

    def _side(self, s: str) -> int:
        if self.trade_side == "unknown":
            return UNKNOWN_SIDE
        is_buy = s.upper() == "BUY"
        if self.trade_side == "taker":
            return BUY if is_buy else SELL
        return SELL if is_buy else BUY  # maker side reported -> taker is opposite

    def decode(self, raw: bytes, recv_mono_ns: int, recv_wall_ns: int) -> Any:
        try:
            msg = orjson.loads(raw)
        except orjson.JSONDecodeError as exc:
            raise DecodeError("invalid_json", str(exc)) from None
        if not isinstance(msg, dict):
            raise DecodeError("not_an_object")
        if msg.get("type") == "error":
            self.control_messages += 1
            if len(self.control_errors) < 100:
                self.control_errors.append(msg.get("message"))
            raise DecodeError("control_error", str(msg.get("message")))
        try:
            channel = msg["channel"]
            seq = int(msg["sequence_num"])
        except KeyError as exc:
            raise DecodeError("missing_field", str(exc)) from None
        except (TypeError, ValueError) as exc:
            raise DecodeError("bad_value", str(exc)) from None

        notice = None
        last = self.last_seq
        if last >= 0:
            if seq <= last:
                self.out_of_order += 1
                raise DecodeError("out_of_order", f"sequence {seq} after {last}")
            if seq != last + 1:
                self.gaps += 1
                notice = ConnectionNotice("resync_required", f"sequence gap {last} -> {seq}",
                                          self.conn_id, recv_mono_ns)
        self.last_seq = seq
        if notice is not None:
            return notice  # nothing on this connection can be trusted until resync

        try:
            if channel == "l2_data":
                return self._l2(msg, recv_mono_ns, recv_wall_ns)
            if channel == "market_trades":
                return self._trades(msg, recv_mono_ns, recv_wall_ns)
            if channel == "heartbeats":
                self.heartbeats += 1
                return None
            if channel in ("subscriptions", "status", "ticker", "ticker_batch"):
                self.control_messages += 1
                return None
        except DecodeError:
            raise
        except KeyError as exc:
            raise DecodeError("missing_field", str(exc)) from None
        except (ValueError, TypeError, IndexError) as exc:
            raise DecodeError("bad_value", str(exc)) from None
        self.unknown[str(channel)] += 1
        raise DecodeError("unknown_event", str(channel))

    def _l2(self, msg: dict, t_mono: int, t_wall: int) -> list[Any]:
        ts = rfc3339_to_ns(msg["timestamp"])
        out: list[Any] = []
        seq = int(msg["sequence_num"])
        for ev in msg["events"]:
            typ = ev["type"]
            bids: list[tuple[int, int]] = []
            asks: list[tuple[int, int]] = []
            for u in ev["updates"]:
                px = parse_e8(u["price_level"])
                qty = parse_e8(u["new_quantity"])
                if px <= 0 or qty < 0:
                    raise DecodeError("bad_levels", f"{u!r}")
                side = u["side"]
                if side in _BID:
                    bids.append((px, qty))
                elif side in _ASK:
                    asks.append((px, qty))
                else:
                    raise DecodeError("bad_levels", f"unknown side {side!r}")
            key = self._key(ev["product_id"])
            if typ == "snapshot":
                out.append(BookSnapshot(key, seq, ts, bids, asks, t_mono, t_wall, self.conn_id, self.sock_uid))
            elif typ == "update":
                out.append(BookDelta(key, seq, ts, bids, asks, t_mono, t_wall, self.conn_id, self.sock_uid))
            else:
                raise DecodeError("unknown_event", f"l2 {typ}")
        return out

    def _trades(self, msg: dict, t_mono: int, t_wall: int) -> list[Any]:
        ts = rfc3339_to_ns(msg["timestamp"])
        out: list[Any] = []
        for ev in msg["events"]:
            trades = ev.get("trades") or []
            if ev.get("type") == "snapshot":
                self.history_trades_skipped += len(trades)
                continue
            for t in trades:
                px = parse_e8(t["price"])
                qty = parse_e8(t["size"])
                if px <= 0 or qty <= 0:
                    raise DecodeError("non_positive_trade")
                tid = t.get("trade_id")
                tid_i = int(tid) if isinstance(tid, str) and tid.isdigit() else -1
                out.append(Trade(self._key(t["product_id"]), tid_i, px, qty, self._side(str(t.get("side", ""))),
                                 rfc3339_to_ns(t["time"]) if t.get("time") else ts, ts, t_mono, t_wall,
                                 self.conn_id))
        return out
