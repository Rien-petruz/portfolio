"""Command-line entry points.

    marketintel run [--simulate] [--duration S] [--config FILE] [--no-api] [--record]
    marketintel sim-server [--port 9443]
    marketintel probe [--duration 30]     # live Binance connectivity + latency check
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
from .engine import Engine, resolve_universe
from .exchange.binance.rest import BinanceRest
from .logging_setup import setup_logging

log = logging.getLogger("marketintel")


async def _serve_api(engine: Engine, settings: Settings) -> Any:
    import uvicorn

    from .api.app import create_app

    config = uvicorn.Config(create_app(engine), host=settings.api.host, port=settings.api.port,
                            log_level="warning", access_log=False, lifespan="off")
    server = uvicorn.Server(config)
    server.install_signal_handlers = lambda: None  # type: ignore[method-assign]
    return server


async def run_engine(settings: Settings, *, duration: float | None, simulate: bool,
                     sim_updates_per_s: float = 2000.0, summary_path: str | None = None) -> dict[str, Any]:
    sim = None
    if simulate:
        from .sim.process import SimProcess

        sim = SimProcess(updates_per_s=sim_updates_per_s)
        await asyncio.to_thread(sim.start)
        settings = settings.model_copy(update={"data_source": DataSource.SIMULATED})
        settings.binance.ws_base_url = sim.ws_url
        settings.binance.rest_base_url = sim.rest_url
        log.warning("SIMULATED DATA: connected to local synthetic exchange (child process), not Binance",
                    extra={"ws": sim.ws_url})

    rest = BinanceRest(settings.binance.rest_base_url, timeout_s=settings.binance.rest_timeout_s,
                       weight_budget_per_min=settings.binance.rest_weight_budget_per_min)
    universe = await resolve_universe(settings, rest)
    engine = Engine(settings, universe, rest=rest)
    await engine.start()

    server_task = None
    if settings.api.enabled:
        server = await _serve_api(engine, settings)
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
        summary = {"health": engine.health(), "latency": engine.latency_report(),
                   "diagnostics": engine.diagnostics()}
        if server_task is not None:
            server.should_exit = True
            with contextlib.suppress(Exception):
                await asyncio.wait_for(server_task, 5)
        await engine.stop()
        await rest.close()
        if sim is not None:
            sim.stop()
    if summary_path:
        with open(summary_path, "wb") as fh:
            fh.write(orjson.dumps(summary, option=orjson.OPT_INDENT_2, default=str))
    return summary


async def run_sim_server(host: str, port: int, updates_per_s: float) -> None:
    from .sim.fake_exchange import FakeBinance

    sim = FakeBinance(host=host, port=port, updates_per_s=updates_per_s)
    await sim.start()
    log.warning("SIMULATED exchange listening", extra={"ws": sim.ws_url, "rest": sim.rest_url,
                                                        "symbols": len(sim.syms)})
    try:
        await asyncio.Event().wait()
    finally:
        await sim.stop()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="marketintel")
    p.add_argument("--config", help="TOML config file (or MIE_CONFIG_FILE)")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="run the engine")
    r.add_argument("--simulate", action="store_true", help="use the local synthetic exchange")
    r.add_argument("--sim-rate", type=float, default=2000.0, help="simulated symbol updates per second")
    r.add_argument("--duration", type=float, default=None, help="stop after N seconds")
    r.add_argument("--no-api", action="store_true")
    r.add_argument("--port", type=int, default=None)
    r.add_argument("--record", action="store_true", help="record raw frames for replay")
    r.add_argument("--summary", help="write a JSON summary on exit")

    pr = sub.add_parser("probe", help="connect to live Binance and report coverage and latency")
    pr.add_argument("--duration", type=float, default=30.0)
    pr.add_argument("--summary", default="probe-summary.json")

    s = sub.add_parser("sim-server", help="run the synthetic Binance-protocol exchange")
    s.add_argument("--host", default="127.0.0.1", help="bind address (0.0.0.0 inside containers)")
    s.add_argument("--port", type=int, default=9443)
    s.add_argument("--rate", type=float, default=2000.0)

    args = p.parse_args(argv)
    settings = load_settings(args.config)
    setup_logging(settings.log_level)

    if args.cmd == "sim-server":
        with contextlib.suppress(KeyboardInterrupt):
            asyncio.run(run_sim_server(args.host, args.port, args.rate))
        return 0

    if args.cmd == "run":
        if args.no_api:
            settings.api.enabled = False
        if args.port is not None:
            settings.api.port = args.port
        if args.record:
            settings.recording.enabled = True
        summary = asyncio.run(run_engine(settings, duration=args.duration, simulate=args.simulate,
                                         sim_updates_per_s=args.sim_rate, summary_path=args.summary))
        print(orjson.dumps(summary["health"], option=orjson.OPT_INDENT_2).decode())
        return 0

    if args.cmd == "probe":
        settings.api.enabled = False
        settings.engine.report_interval_s = min(settings.engine.report_interval_s, 5.0)
        summary = asyncio.run(run_engine(settings, duration=args.duration, simulate=False,
                                         summary_path=args.summary))
        h = summary["health"]
        print(orjson.dumps({"health": h, "latency": summary["latency"]}, option=orjson.OPT_INDENT_2).decode())
        ok = h["shards_connected"] == h["shards_total"] and h["symbols_usable"] >= min(
            settings.universe.min_symbols, h["symbols_total"]) and h["reference_status"] in ("LIVE", "QUIET")
        print("PROBE", "PASSED" if ok else "FAILED", file=sys.stderr)
        return 0 if ok else 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
