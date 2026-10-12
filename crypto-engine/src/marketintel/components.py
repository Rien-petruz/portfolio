"""Install strategy, signal, paper-trading and risk components on an engine."""

from __future__ import annotations

from typing import Any


def install(engine: Any) -> None:
    from .strategies.cross_exchange import CrossExchangeScanner

    paper = None
    try:
        from .paper_trading.engine import install_paper
        paper = install_paper(engine)
    except ImportError:
        pass
    inventory = paper.portfolio.available if paper is not None else None
    xex = CrossExchangeScanner(engine, inventory=inventory,
                               on_valid=paper.on_opportunity if paper is not None else None)
    engine.add_component(xex, quotes=True)
    try:
        from .strategies.triangular import TriangularScanner
        tri = TriangularScanner(engine, inventory=inventory,
                                on_valid=paper.on_opportunity if paper is not None else None)
        engine.add_component(tri, quotes=True)
    except ImportError:
        pass
    try:
        from .features.grid import install_features
        install_features(engine)
    except ImportError:
        pass
