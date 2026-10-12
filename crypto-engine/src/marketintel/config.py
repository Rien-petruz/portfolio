"""Typed, validated configuration.

Precedence (highest first): explicit keyword overrides, environment variables
(``MIE_`` prefix, ``__`` as the nesting delimiter, e.g.
``MIE_FEED__STALE_AFTER_MS=5000``), the TOML file named by ``MIE_CONFIG_FILE``
or passed to :func:`load_settings`, then the defaults below.

No credentials are needed for public market data. When live execution is
added later, API keys must come from the environment only and are never
logged (see docs/RISK_MANAGEMENT.md).
"""

from __future__ import annotations

import os
from enum import StrEnum
from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

# Binance hard limits, from the official web-socket-streams.md.
BINANCE_MAX_STREAMS_PER_CONNECTION = 1024
BINANCE_CONNECTION_ATTEMPTS_PER_5MIN = 300
BINANCE_CONNECTION_MAX_AGE_S = 24 * 3600

DEFAULT_REQUIRED_SYMBOLS = [
    # Reference market.
    "BTCUSDT",
    # Legs needed for cross-rate / triangular checks (Phase 4).
    "ETHUSDT", "ETHBTC", "BNBUSDT", "BNBBTC", "BNBETH", "SOLUSDT", "SOLBTC",
    "XRPUSDT", "XRPBTC", "BTCUSDC", "ETHUSDC", "USDCUSDT", "FDUSDUSDT", "BTCFDUSD",
]

# Used only when exchange metadata cannot be fetched (e.g. REST blocked).
# Symbols that turn out not to exist are simply never populated and stay
# UNINITIALIZED; they are reported, never fabricated.
DEFAULT_FALLBACK_SYMBOLS = DEFAULT_REQUIRED_SYMBOLS + [
    "ADAUSDT", "DOGEUSDT", "TRXUSDT", "LINKUSDT", "AVAXUSDT", "DOTUSDT", "LTCUSDT",
    "BCHUSDT", "UNIUSDT", "XLMUSDT", "ATOMUSDT", "ETCUSDT", "FILUSDT", "APTUSDT",
    "ARBUSDT", "OPUSDT", "NEARUSDT", "INJUSDT", "SUIUSDT", "AAVEUSDT", "TONUSDT",
    "SHIBUSDT", "PEPEUSDT", "WIFUSDT", "SEIUSDT", "TIAUSDT", "RNDRUSDT", "FETUSDT",
    "HBARUSDT", "ICPUSDT", "ALGOUSDT", "VETUSDT", "SANDUSDT", "MANAUSDT", "GALAUSDT",
    "EGLDUSDT", "THETAUSDT", "AXSUSDT", "RUNEUSDT", "LDOUSDT", "CRVUSDT", "MKRUSDT",
    "ENSUSDT", "JUPUSDT", "PENDLEUSDT", "ORDIUSDT", "STXUSDT", "IMXUSDT", "KASUSDT",
]


class SubscribeMode(StrEnum):
    URL = "url"          # streams listed in the combined-stream URL
    MESSAGE = "message"  # connect to /stream then send paced SUBSCRIBE requests


class DataSource(StrEnum):
    LIVE = "LIVE"            # real Binance production market data
    SIMULATED = "SIMULATED"  # local synthetic exchange; never real prices
    REPLAY = "REPLAY"        # recorded frames


class BinanceConfig(BaseModel):
    ws_base_url: str = "wss://stream.binance.com:9443"
    rest_base_url: str = "https://api.binance.com"
    max_streams_per_connection: int = Field(200, ge=1, le=BINANCE_MAX_STREAMS_PER_CONNECTION)
    max_symbols_per_connection: int = Field(40, ge=1)
    subscribe_mode: SubscribeMode = SubscribeMode.URL
    # Binance allows 5 incoming control messages/s per connection (pings and
    # pongs included). Stay well below it.
    subscribe_messages_per_second: float = Field(3.0, gt=0, le=4.0)
    subscribe_batch_size: int = Field(100, ge=1, le=BINANCE_MAX_STREAMS_PER_CONNECTION)
    # Rotate before the exchange's 24h hard disconnect (make-before-break).
    connection_max_age_s: float = Field(23 * 3600, gt=0, le=BINANCE_CONNECTION_MAX_AGE_S)
    connect_attempts_per_window: int = Field(200, ge=1, le=BINANCE_CONNECTION_ATTEMPTS_PER_5MIN)
    connect_window_s: float = Field(300.0, gt=0)
    open_timeout_s: float = Field(10.0, gt=0)
    # Client-side keepalive pings; the library answers server pings itself.
    ping_interval_s: float | None = 20.0
    ping_timeout_s: float | None = 20.0
    rest_timeout_s: float = Field(10.0, gt=0)
    rest_weight_budget_per_min: int = Field(3000, ge=1)  # exchange limit is 6000
    compression: bool = False  # deflate costs CPU per frame; off by default


class UniverseConfig(BaseModel):
    min_symbols: int = Field(50, ge=1)
    max_symbols: int = Field(60, ge=1)
    quote_assets: list[str] = Field(default_factory=lambda: ["USDT"])
    explicit_symbols: list[str] = Field(default_factory=list)  # if set, used verbatim
    required_symbols: list[str] = Field(default_factory=lambda: list(DEFAULT_REQUIRED_SYMBOLS))
    exclude_symbols: list[str] = Field(default_factory=list)
    fallback_symbols: list[str] = Field(default_factory=lambda: list(DEFAULT_FALLBACK_SYMBOLS))
    depth_symbols: list[str] = Field(default_factory=lambda: ["BTCUSDT", "ETHUSDT"])
    depth_snapshot_limit: int = Field(1000, ge=5, le=5000)
    subscribe_trades: bool = True

    @field_validator("explicit_symbols", "required_symbols", "exclude_symbols",
                     "fallback_symbols", "depth_symbols", "quote_assets")
    @classmethod
    def _upper(cls, v: list[str]) -> list[str]:
        return [s.strip().upper() for s in v if s.strip()]

    @model_validator(mode="after")
    def _bounds(self) -> "UniverseConfig":
        if self.max_symbols < self.min_symbols:
            raise ValueError("max_symbols must be >= min_symbols")
        return self


class FeedConfig(BaseModel):
    # A quote with no update for quiet_after_ms on a healthy connection is
    # QUIET (book unchanged); after stale_after_ms it is STALE and unusable.
    quiet_after_ms: int = Field(2_000, ge=1)
    stale_after_ms: int = Field(30_000, ge=1)
    # A connection with no frames at all for this long is considered stalled
    # and is recycled. With 50+ symbols silence of several seconds is abnormal.
    connection_stall_ms: int = Field(10_000, ge=100)
    watchdog_interval_ms: int = Field(250, ge=10)
    # Exchange event time -> local receipt (clock-offset corrected), smoothed
    # per shard from trade/depth events. Above this, data is arriving too late
    # to describe the current market: quotes on that shard become STALE.
    max_delivery_lag_ms: int = Field(2_000, ge=1)

    @model_validator(mode="after")
    def _order(self) -> "FeedConfig":
        if self.stale_after_ms <= self.quiet_after_ms:
            raise ValueError("stale_after_ms must exceed quiet_after_ms")
        return self


class BackoffConfig(BaseModel):
    base_s: float = Field(0.5, gt=0)
    cap_s: float = Field(30.0, gt=0)
    rate_limited_min_s: float = Field(60.0, gt=0)  # after HTTP 429/418
    stable_after_s: float = Field(30.0, gt=0)      # reset attempts after this uptime


class EngineConfig(BaseModel):
    trade_queue_capacity: int = Field(8192, ge=16)
    loop_lag_interval_ms: int = Field(50, ge=5)
    loop_lag_degraded_ms: float = Field(50.0, gt=0)
    # Latency "window" percentiles cover exactly one report interval.
    report_interval_s: float = Field(10.0, gt=0)


class ApiConfig(BaseModel):
    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = Field(8080, ge=0, le=65535)


class RecordingConfig(BaseModel):
    enabled: bool = False
    directory: str = "recordings"
    queue_capacity: int = Field(100_000, ge=1)


class ExecutionConfig(BaseModel):
    """Execution is not implemented in this phase. Live trading is refused."""

    mode: str = Field("observe", pattern="^(observe|paper)$")
    live_trading_enabled: bool = False

    @field_validator("live_trading_enabled")
    @classmethod
    def _no_live(cls, v: bool) -> bool:
        if v:
            raise ValueError("live trading is not available in this build")
        return v


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MIE_", env_nested_delimiter="__", extra="ignore"
    )

    data_source: DataSource = DataSource.LIVE
    binance: BinanceConfig = Field(default_factory=BinanceConfig)
    universe: UniverseConfig = Field(default_factory=UniverseConfig)
    feed: FeedConfig = Field(default_factory=FeedConfig)
    backoff: BackoffConfig = Field(default_factory=BackoffConfig)
    engine: EngineConfig = Field(default_factory=EngineConfig)
    api: ApiConfig = Field(default_factory=ApiConfig)
    recording: RecordingConfig = Field(default_factory=RecordingConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    log_level: str = "INFO"

    @model_validator(mode="after")
    def _live_means_binance(self) -> "Settings":
        # Never label data LIVE unless it comes from an official Binance host.
        if self.data_source is DataSource.LIVE:
            host = urlsplit(self.binance.ws_base_url).hostname or ""
            if not (host.endswith(".binance.com") or host.endswith(".binance.vision")):
                raise ValueError(
                    f"data_source=LIVE requires an official Binance endpoint, got {host!r}; "
                    "set data_source=SIMULATED or REPLAY for other sources")
        return self

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        sources: list[PydanticBaseSettingsSource] = [init_settings, env_settings]
        if settings_cls.model_config.get("toml_file"):
            sources.append(TomlConfigSettingsSource(settings_cls))
        return tuple(sources)


def load_settings(path: str | None = None, **overrides: Any) -> Settings:
    path = path or os.environ.get("MIE_CONFIG_FILE")
    if not path:
        return Settings(**overrides)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"config file not found: {path}")

    class _FileSettings(Settings):
        model_config = SettingsConfigDict(**{**Settings.model_config, "toml_file": path})

    return _FileSettings(**overrides)
