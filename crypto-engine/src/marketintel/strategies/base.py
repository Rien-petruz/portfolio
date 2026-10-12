"""Structured signal model shared by anomaly and pattern strategies.

A signal is an *observation with an explanation*, never a promise: its
``strength`` is a robust z-score or ratio (``score_kind``), not a probability
of profit. Directional signals are later scored against forward returns and
simple baselines (``strategies/evaluation.py``).
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Signal:
    strategy: str                # e.g. "anomaly.price_jump", "pattern.breakout"
    kind: str                    # "anomaly" | "pattern"
    key: str                     # instrument key (or pair id for cross-venue signals)
    venue: str
    detected_mono_ns: int
    detected_wall_ns: int
    direction: int               # +1 / -1 / 0 (non-directional)
    strength: float
    score_kind: str              # "robust_z" | "ratio"
    features: dict[str, Any]
    data_quality: str            # quote status / "DATA_QUALITY_SUSPECT"
    classification: str          # e.g. CORROBORATED_MOVE, UNCORROBORATED, DATA_QUALITY_SUSPECT
    explanation: str
    est_lifetime_s: float | None = None
    validation_status: str = "PENDING_EVALUATION"
    signal_id: str = ""
    evaluation: dict[str, Any] = field(default_factory=dict)
    entry_mid: float | None = None

    def __post_init__(self) -> None:
        if not self.signal_id:
            self.signal_id = hashlib.sha1(
                f"{self.strategy}|{self.key}|{self.detected_mono_ns}".encode(), usedforsecurity=False).hexdigest()[:16]

    def view(self) -> dict[str, Any]:
        d = asdict(self)
        d["note"] = "strength is a score, not a probability of profit"
        return d
