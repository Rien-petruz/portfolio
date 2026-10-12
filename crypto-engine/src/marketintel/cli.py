"""Command-line entry points (PAPER TRADING ONLY).

    marketintel run [--simulate] [--duration S] [--config FILE] [--record] [--port P]
    marketintel probe [--duration 45]                 # live venue connectivity + latency check
    marketintel sim-server [--host H] [--binance-port P] [--coinbase-port P]
    marketintel replay FILE [--report out.json]       # deterministic replay + backtest report
    marketintel backtest FILE --folds 4 --grid 1,2,5  # walk-forward, out-of-sample only
    marketintel candles KLINES.csv                     # candle-level rule evaluation (no order book)
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import signal
import sys
from typing import Any

import orjson

from .config import DataSource, Settings, load_settings
from .logging_setup import setup_logging
from .runtime import build_system
from .safety import PAPER_BANNER

log = logging.getLogger("marketintel")


def _dump(obj: Any, path: str | None) -> None:
    data = orjson.dumps(obj, option=orjson.OPT_INDENT_2 | orjson.OPT_NON_STR_KEYS | orjson.OPT_SERIALIZE_NUMPY,
                        default=str)
    if path:
        with open(path, "wb") as fh:
            fh.write(data)
    else:
        sys.stdout.write(data.decode() + "\n")


async def _api(engine: Any, settings: Settings) -> Any:
    import uvicorn

    from .api.app import create_app

    server = uvicorn.Server(uvicorn.Config(create_app(engine), host=settings.api.host, port=settings.api.port,
                                           log_level="warning", access_log=False, lifespan="off"))
    server.install_signal_handlers = lambda: None  # type: ignore[method-assign]
    return server


async def run_engine(settings: Settings, *, duration: float | None, simulate: bool, sim_rate: float = 2000.0,
                     summary_path: str | None = None, sim_dislocations: float = 2.0) -> dict[str, Any]:
    sim = None
    if simulate:
        from .sim.process import SimProcess

        sim = SimProcess(updates_per_s=sim_rate, dislocations_per_min=sim_dislocations)
        await asyncio.to_thread(sim.start)
        settings = settings.model_copy(update={"data_source": DataSource.SIMULATED})
        settings.binance.ws_base_url = sim.url("binance")
        settings.binance.rest_base_url = sim.url("binance", "http")
        settings.coinbase.ws_base_url = sim.url("coinbase")
        settings.coinbase.rest_base_url = sim.url("coinbase", "http")
        log.warning("SIMULATED DATA: local synthetic Binance + Coinbase (child process), not real markets",
                    extra={"binance": sim.url("binance"), "coinbase": sim.url("coinbase")})
    log.warning(PAPER_BANNER)
    engine = await build_system(settings)
    await engine.start()
    server = server_task = None
    if settings.api.enabled:
        server = await _api(engine, settings)
        server_task = asyncio.create_task(server.serve(), name="api")
        log.info("API listening", extra={"url": f"http://{settings.api.host}:{settings.api.port}"})
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop.set)
    try:
        if duration:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), duration)
        else:
            await stop.wait()
    finally:
        summary = {"health": engine.health(), "latency": engine.latency_report(), "diagnostics": engine.diagnostics()}
        paper = engine.component("paper")
        if paper is not None:
            summary["paper"] = paper.snapshot()
        if server is not None:
            server.should_exit = True
            with contextlib.suppress(Exception):
                await asyncio.wait_for(server_task, 5)  # type: ignore[arg-type]
        await engine.stop()
        if sim is not None:
            sim.stop()
    if summary_path:
        _dump(summary, summary_path)
    return summary


async def run_sim_server(host: str, binance_port: int, coinbase_port: int, rate: float, dislocations: float) -> None:
    from .sim.binance_sim import FakeBinance, default_symbols
    from .sim.coinbase_sim import FakeCoinbase
    from .sim.world import MarketWorld

    world = MarketWorld(7)
    world.dislocation_rate_per_min = dislocations
    b = FakeBinance(default_symbols(world=world), world=world, host=host, port=binance_port, updates_per_s=rate)
    c = FakeCoinbase(world, host=host, port=coinbase_port, updates_per_s=rate / 3)
    await b.start()
    await c.start()
    log.warning("SIMULATED exchanges listening", extra={"binance": b.ws_url, "coinbase": c.ws_url})
    try:
        await asyncio.Event().wait()
    finally:
        await b.stop()
        await c.stop()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="marketintel", description=PAPER_BANNER)
    p.add_argument("--config", help="TOML config file (or MIE_CONFIG_FILE)")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="run the engine (live public data by default)")
    r.add_argument("--simulate", action="store_true", help="use the local synthetic exchanges")
    r.add_argument("--sim-rate", type=float, default=2000.0)
    r.add_argument("--sim-dislocations", type=float, default=2.0, help="synthetic dislocations per minute")
    r.add_argument("--duration", type=float, default=None)
    r.add_argument("--no-api", action="store_true")
    r.add_argument("--port", type=int, default=None)
    r.add_argument("--dashboard", default=None, help="serve a built dashboard directory at /")
    r.add_argument("--record", action="store_true", help="record raw frames for replay")
    r.add_argument("--summary", help="write a JSON summary on exit")

    pr = sub.add_parser("probe", help="connect to live venues and report coverage and latency")
    pr.add_argument("--duration", type=float, default=45.0)
    pr.add_argument("--summary", default="probe-summary.json")

    s = sub.add_parser("sim-server", help="run the synthetic Binance + Coinbase exchanges")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--binance-port", type=int, default=9443)
    s.add_argument("--coinbase-port", type=int, default=9444)
    s.add_argument("--rate", type=float, default=2000.0)
    s.add_argument("--dislocations", type=float, default=2.0)

    rp = sub.add_parser("replay", help="replay a recording through the full system and report")
    rp.add_argument("file")
    rp.add_argument("--warmup", type=float, default=60.0)
    rp.add_argument("--report", default=None)

    bt = sub.add_parser("backtest", help="walk-forward evaluation of a recording")
    bt.add_argument("file")
    bt.add_argument("--folds", type=int, default=4)
    bt.add_argument("--grid", default="1,2,5,10", help="min_net_edge_bps candidates")
    bt.add_argument("--warmup", type=float, default=30.0)
    bt.add_argument("--report", default=None)

    cd = sub.add_parser("candles", help="candle-level rule evaluation (Binance kline CSV)")
    cd.add_argument("file")
    cd.add_argument("--cost-bps", type=float, default=20.0)
    cd.add_argument("--horizon", type=int, default=5)

    args = p.parse_args(argv)
    settings = load_settings(args.config)
    setup_logging(settings.log_level)

    if args.cmd == "sim-server":
        with contextlib.suppress(KeyboardInterrupt):
            asyncio.run(run_sim_server(args.host, args.binance_port, args.coinbase_port, args.rate, args.dislocations))
        return 0
    if args.cmd == "run":
        if args.no_api:
            settings.api.enabled = False
        if args.port is not None:
            settings.api.port = args.port
        if args.dashboard:
            settings.api.dashboard_dir = args.dashboard
        if args.record:
            settings.recording.enabled = True
        summary = asyncio.run(run_engine(settings, duration=args.duration, simulate=args.simulate,
                                         sim_rate=args.sim_rate, summary_path=args.summary,
                                         sim_dislocations=args.sim_dislocations))
        _dump(summary["health"], None)
        return 0
    if args.cmd == "probe":
        settings.api.enabled = False
        summary = asyncio.run(run_engine(settings, duration=args.duration, simulate=False, summary_path=args.summary))
        h = summary["health"]
        b = h["venues"].get("BINANCE", {})
        c = h["venues"].get("COINBASE", {})
        ok = (h["connections_up"] == h["connections_total"] and b.get("usable", 0) >= min(50, b.get("instruments", 0))
              and h["reference_status"] in ("LIVE", "QUIET") and (not c or c.get("usable", 0) > 0))
        _dump({"health": h, "latency_us": {k: v["window"] for k, v in summary["latency"].items()
                                           if isinstance(v, dict) and "window" in v}}, None)
        print("PROBE", "PASSED" if ok else "FAILED", file=sys.stderr)
        return 0 if ok else 1
    if args.cmd == "replay":
        from .backtest.metrics import report
        from .backtest.replay import replay
        res = replay(args.file, settings, warmup_s=args.warmup)
        _dump(report(res), args.report)
        return 0
    if args.cmd == "backtest":
        from .backtest.walkforward import walk_forward
        grid = [float(x) for x in args.grid.split(",") if x]
        _dump(walk_forward(args.file, settings, folds=args.folds, grid=grid, warmup_s=args.warmup), args.report)
        return 0
    if args.cmd == "candles":
        from .backtest.candles import evaluate_file
        _dump(evaluate_file(args.file, cost_bps=args.cost_bps, horizon=args.horizon), None)
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
