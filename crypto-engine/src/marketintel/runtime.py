"""Assemble the full system (engine + strategy, paper-trading and risk
components) from configuration. Used by the CLI, tests and the replay engine
so every entry point runs the same wiring."""

from __future__ import annotations

import random
from collections.abc import Callable
from typing import Any

from .clock import Clock
from .config import Settings
from .engine import Engine, Universe, make_adapters, resolve_universe
from .exchanges.connection import ws_connect
from .exchanges.registry import InstrumentRegistry
from .persistence.sink import AuditSink, make_sink


def add_components(engine: Engine) -> Engine:
    """Attach strategy / paper-trading components according to configuration."""
    try:
        from .components import install
    except ImportError:  # strategy layer not installed (early phases)
        return engine
    install(engine)
    return engine


async def build_system(settings: Settings, *, clock: Clock | None = None, sink: AuditSink | None = None,
                       connect: Callable[..., Any] = ws_connect, rng: random.Random | None = None,
                       universe: Universe | None = None, registry: InstrumentRegistry | None = None,
                       components: bool = True) -> Engine:
    registry = registry or InstrumentRegistry(settings.registry)
    adapters = make_adapters(settings, registry)
    if universe is None:
        universe = await resolve_universe(settings, adapters, registry)
    engine = Engine(settings, universe, registry, adapters, clock=clock, connect=connect, rng=rng,
                    sink=sink if sink is not None else make_sink(settings.persistence))
    return add_components(engine) if components else engine
