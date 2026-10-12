"""Monitoring API (read-only).

Endpoints only read in-memory state; none performs network I/O or writes, so
serving them on the ingestion event loop costs microseconds per request. All
responses carry ``data_source`` so simulated data can never be mistaken for
live market data.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import PlainTextResponse

from .. import __version__
from ..clock import mono_ns

if TYPE_CHECKING:
    from ..engine import Engine

SortKey = Literal["symbol", "spread_bps", "book_age_ms", "book_updates", "trades", "touch_imbalance",
                  "tapped_quote_volume", "status"]


def create_app(engine: "Engine") -> FastAPI:
    app = FastAPI(title="Market Intelligence Engine", version=__version__)

    def envelope(payload: dict[str, Any]) -> dict[str, Any]:
        return {"data_source": engine.data_source.value, **payload}

    @app.get("/health")
    def health() -> dict[str, Any]:
        return engine.health()

    @app.get("/markets")
    def markets(
        status: str | None = Query(None, description="filter by quote status, e.g. LIVE"),
        sort: SortKey = "symbol",
        desc: bool = False,
        limit: int = Query(500, ge=1, le=5000),
    ) -> dict[str, Any]:
        rows = engine.market_rows()
        if status:
            wanted = {s.strip().upper() for s in status.split(",")}
            rows = [r for r in rows if r["status"] in wanted]

        def key(r: dict[str, Any]) -> tuple[int, Any]:
            v = r.get(sort)
            return (1, 0) if v is None else (0, v)

        rows.sort(key=key, reverse=desc)
        if desc:  # keep missing values last either way
            rows.sort(key=lambda r: r.get(sort) is None)
        return envelope({"count": len(rows), "markets": rows[:limit]})

    @app.get("/markets/{symbol}")
    def market(symbol: str) -> dict[str, Any]:
        st = engine.state.symbols.get(symbol.upper())
        if st is None:
            raise HTTPException(404, f"{symbol.upper()} is not monitored")
        row = engine.state.row(st, mono_ns())
        book = engine.books.books.get(st.symbol)
        return envelope({"market": row, "order_book": book.snapshot_view(10) if book else None})

    @app.get("/latency")
    def latency() -> dict[str, Any]:
        return envelope(engine.latency_report())

    @app.get("/diagnostics")
    def diagnostics() -> dict[str, Any]:
        return envelope(engine.diagnostics())

    @app.get("/metrics", response_class=PlainTextResponse)
    def metrics() -> str:
        return prometheus_text(engine)

    return app


def prometheus_text(engine: "Engine") -> str:
    h = engine.health()
    lines = [
        f'mie_info{{data_source="{engine.data_source.value}",version="{__version__}"}} 1',
        f"mie_frames_total {engine.frames}",
        f"mie_shards_connected {h['shards_connected']}",
        f"mie_shards_total {h['shards_total']}",
        f"mie_symbols_usable {h['symbols_usable']}",
    ]
    for status, n in h["status_counts"].items():
        lines.append(f'mie_symbols_by_status{{status="{status}"}} {n}')
    for reason, n in engine.invalid.items():
        lines.append(f'mie_invalid_frames_total{{reason="{reason}"}} {n}')
    for q in engine.bus.stats():
        lines.append(f'mie_queue_depth{{queue="{q["name"]}"}} {q["depth"]}')
        lines.append(f'mie_queue_dropped_total{{queue="{q["name"]}"}} {q["dropped"]}')
    for sh in engine.shards:
        s = sh.health
        lines.append(f'mie_shard_connected{{shard="{s.shard_id}"}} {int(s.connected)}')
        lines.append(f'mie_shard_reconnects_total{{shard="{s.shard_id}"}} {max(0, s.connects - 1)}')
    for name, rep in engine.latency_report().items():
        if name.startswith("_"):
            continue
        w = rep["window"]
        for q in ("p50", "p95", "p99", "max"):
            if w[q] is not None:
                lines.append(f'mie_latency_us{{stage="{name}",quantile="{q}"}} {w[q]}')
    return "\n".join(lines) + "\n"
