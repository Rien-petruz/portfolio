"""PAPER TRADING ONLY: prove that no code path can place a real order."""

import ast
import json
import pathlib
import re

import pytest
from pydantic import ValidationError

from marketintel.config import BinanceConfig, CoinbaseConfig, Settings, SubscribeMode
from marketintel.exchanges.base import FeeSchedule, InstrumentSpec, Venue
from marketintel.exchanges.binance.adapter import BinanceAdapter
from marketintel.exchanges.coinbase.adapter import CoinbaseAdapter
from marketintel.exchanges.http import ReadOnlyHttp
from marketintel.safety import EXECUTION_MODE, PaperOnlyViolation

SRC = pathlib.Path(__file__).resolve().parents[2] / "src" / "marketintel"

# Exchange order / account / withdrawal endpoints and signing primitives.
FORBIDDEN = [
    r"/api/v3/order", r"/api/v3/account", r"/sapi/", r"/wapi/", r"brokerage/orders", r"brokerage/accounts",
    r"/withdraw", r"withdraw\(", r"capital/withdraw", r"newOrder", r"placeOrder", r"create_order", r"cancelReplace", r"listenKey", r"userDataStream",
    r"\bhmac\b", r"signature=", r"build_ws_jwt", r"advanced-trade-ws-user",
]
# safety.py documents the boundary in prose (it necessarily names what is forbidden).
ALLOWED_FILES = {"safety.py"}


def test_execution_mode_is_paper():
    assert EXECUTION_MODE == "PAPER"


def test_source_tree_has_no_order_endpoints_or_signing():
    hits = []
    for path in SRC.rglob("*.py"):
        if path.name in ALLOWED_FILES:
            continue
        text = path.read_text()
        for pat in FORBIDDEN:
            for m in re.finditer(pat, text):
                hits.append(f"{path.relative_to(SRC)}: {m.group(0)}")
    assert hits == [], hits


def test_no_http_write_methods_anywhere():
    """No module calls .post/.put/.patch/.delete/.request on an HTTP client."""
    offenders = []
    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in {"post", "put", "patch", "delete", "request", "stream"}:
                    receiver = ast.unparse(node.func.value).lower()
                    if any(h in receiver for h in ("http", "client", "session", "requests", "httpx")):
                        offenders.append(f"{path.relative_to(SRC)}:{node.lineno} {receiver}.{node.func.attr}()")
    # Also: httpx/requests/aiohttp are only imported by the read-only client.
    importers = sorted(str(p.relative_to(SRC)) for p in SRC.rglob("*.py")
                       if re.search(r"^\s*(import|from)\s+(httpx|requests|aiohttp)\b", p.read_text(), re.M))
    assert importers == ["exchanges/http.py"], importers
    assert offenders == [], offenders


async def test_read_only_http_refuses_writes_before_sending():
    http = ReadOnlyHttp("http://127.0.0.1:9")  # nothing listens: a request would fail differently
    try:
        for method in ("POST", "PUT", "DELETE", "PATCH"):
            with pytest.raises(PaperOnlyViolation):
                await http._client.request(method, "/api/v3/order", json={"side": "BUY"})
        with pytest.raises(PaperOnlyViolation):
            await http._client.get("/api/v3/account", headers={"X-MBX-APIKEY": "k"})
        with pytest.raises(PaperOnlyViolation):
            await http._client.get("/x", headers={"Authorization": "Bearer t"})
    finally:
        await http.close()


def test_websocket_messages_are_subscriptions_only():
    b = BinanceAdapter(BinanceConfig(subscribe_mode=SubscribeMode.MESSAGE))
    specs = [InstrumentSpec(Venue.BINANCE, "BTCUSDT", "BTC", "USDT", "BTC", "USDT", fees=FeeSchedule(10, 10))]
    for plan in b.plan_connections(specs, 0):
        for m in plan.subscribe_messages:
            assert json.loads(m)["method"] == "SUBSCRIBE"
    c = CoinbaseAdapter(CoinbaseConfig())
    cspecs = [InstrumentSpec(Venue.COINBASE, "BTC-USD", "BTC", "USD", "BTC", "USD", fees=FeeSchedule(60, 120))]
    for plan in c.plan_connections(cspecs, 0):
        for m in plan.subscribe_messages:
            msg = json.loads(m)
            assert msg["type"] == "subscribe" and msg["channel"] in {"heartbeats", "level2", "market_trades"}
            assert "jwt" not in msg and "user" not in msg["channel"]


def test_no_live_execution_setting_exists():
    with pytest.raises(ValidationError):
        Settings(paper={"mode": "live"})
    fields = json.dumps(Settings.model_json_schema())
    assert "live_trading" not in fields and "api_secret" not in fields.lower()


def test_websocket_send_only_used_for_subscriptions():
    """The only WebSocket .send() in the engine sends planned subscription messages."""
    sends = []
    for path in (SRC / "exchanges").rglob("*.py"):
        for i, line in enumerate(path.read_text().splitlines(), 1):
            if ".send(" in line:
                sends.append((path.name, line.strip()))
    assert sends == [("connection.py", "await sock.ws.send(msg)")]
