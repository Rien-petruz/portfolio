"""Typed, validated configuration.

Precedence (highest first): keyword overrides, environment variables
(``MIE_`` prefix, ``__`` nesting, e.g. ``MIE_BINANCE__STALE_AFTER_MS=5000``),
the TOML file given by ``--config`` / ``MIE_CONFIG_FILE``, then defaults.

There is deliberately **no** setting that enables live order placement:
``paper.mode`` only accepts ``"paper"``. Secrets (the PostgreSQL URL) come
from the environment and are never logged.
"""

from __future__ import annotations

import os
from enum import StrEnum
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

BINANCE_MAX_STREAMS_PER_CONNECTION = 1024
BINANCE_CONNECTION_ATTEMPTS_PER_5MIN = 300
BINANCE_CONNECTION_MAX_AGE_S = 24 * 3600

DEFAULT_REQUIRED_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "ETHBTC", "BNBUSDT", "BNBBTC", "BNBETH", "SOLUSDT", "SOLBTC",
    "SOLETH", "XRPUSDT", "XRPBTC", "BTCUSDC", "ETHUSDC", "USDCUSDT", "FDUSDUSDT", "BTCFDUSD",
    "LTCBTC", "LINKBTC", "ADABTC", "DOGEBTC",
]

DEFAULT_FALLBACK_SYMBOLS = DEFAULT_REQUIRED_SYMBOLS + [
    "ADAUSDT", "DOGEUSDT", "TRXUSDT", "LINKUSDT", "AVAXUSDT", "DOTUSDT", "LTCUSDT",
    "BCHUSDT", "UNIUSDT", "XLMUSDT", "ATOMUSDT", "ETCUSDT", "FILUSDT", "APTUSDT",
    "ARBUSDT", "OPUSDT", "NEARUSDT", "INJUSDT", "SUIUSDT", "AAVEUSDT", "TONUSDT",
    "SHIBUSDT", "PEPEUSDT", "WIFUSDT", "SEIUSDT", "TIAUSDT", "RENDERUSDT", "FETUSDT",
    "HBARUSDT", "ICPUSDT", "ALGOUSDT", "VETUSDT", "SANDUSDT", "MANAUSDT", "GALAUSDT",
    "EGLDUSDT", "THETAUSDT", "AXSUSDT", "RUNEUSDT", "LDOUSDT", "CRVUSDT",
    "ENSUSDT", "JUPUSDT", "PENDLEUSDT", "STXUSDT", "IMXUSDT", "GRTUSDT",
]

# Assets whose identity is the same on every supported venue. Cross-venue
# comparison only happens for VERIFIED assets unless explicitly relaxed.
DEFAULT_VERIFIED_ASSETS = [
    "BTC", "ETH", "SOL", "XRP", "ADA", "DOGE", "LTC", "LINK", "AVAX", "DOT", "BCH", "UNI",
    "XLM", "ATOM", "ETC", "FIL", "APT", "ARB", "OP", "NEAR", "INJ", "SUI", "AAVE", "SHIB",
    "PEPE", "WIF", "SEI", "TIA", "RENDER", "FET", "HBAR", "ICP", "ALGO", "VET", "SAND", "MANA",
    "GALA", "EGLD", "AXS", "LDO", "CRV", "ENS", "JUP", "STX", "IMX", "GRT", "USDT", "USDC", "USD",
]


class _Model(BaseModel):
    """All config sections validate on assignment too (runtime/test overrides)."""

    model_config = ConfigDict(validate_assignment=True)


class SubscribeMode(StrEnum):
    URL = "url"
    MESSAGE = "message"


class DataSource(StrEnum):
    LIVE = "LIVE"
    SIMULATED = "SIMULATED"
    REPLAY = "REPLAY"


class FeeConfig(_Model):
    maker_bps: float = Field(ge=0)
    taker_bps: float = Field(ge=0)


class VenueConfig(_Model):
    enabled: bool = True
    ws_base_url: str
    rest_base_url: str
    max_symbols_per_connection: int = Field(40, ge=1)
    connect_attempts_per_window: int = Field(200, ge=1)
    connect_window_s: float = Field(300.0, gt=0)
    open_timeout_s: float = Field(10.0, gt=0)
    ping_interval_s: float | None = 20.0
    ping_timeout_s: float | None = 20.0
    connection_max_age_s: float = Field(23 * 3600, gt=0)
    subscribe_messages_per_second: float = Field(3.0, gt=0)
    rest_timeout_s: float = Field(10.0, gt=0)
    rest_weight_budget_per_min: int = Field(1000, ge=1)
    compression: bool = False
    # Quote freshness (per venue: update cadences differ).
    quiet_after_ms: int = Field(2_000, ge=1)
    stale_after_ms: int = Field(30_000, ge=1)
    connection_stall_ms: int = Field(10_000, ge=100)
    fees: FeeConfig
    fee_overrides: dict[str, FeeConfig] = Field(default_factory=dict)  # by native symbol
    depth_symbols: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _order(self) -> VenueConfig:
        if self.stale_after_ms <= self.quiet_after_ms:
            raise ValueError("stale_after_ms must exceed quiet_after_ms")
        return self


class BinanceConfig(VenueConfig):
    ws_base_url: str = "wss://stream.binance.com:9443"
    rest_base_url: str = "https://api.binance.com"
    max_streams_per_connection: int = Field(200, ge=1, le=BINANCE_MAX_STREAMS_PER_CONNECTION)
    subscribe_mode: SubscribeMode = SubscribeMode.URL
    subscribe_messages_per_second: float = Field(3.0, gt=0, le=4.0)
    subscribe_batch_size: int = Field(100, ge=1, le=BINANCE_MAX_STREAMS_PER_CONNECTION)
    connection_max_age_s: float = Field(23 * 3600, gt=0, le=BINANCE_CONNECTION_MAX_AGE_S)
    connect_attempts_per_window: int = Field(200, ge=1, le=BINANCE_CONNECTION_ATTEMPTS_PER_5MIN)
    rest_weight_budget_per_min: int = Field(3000, ge=1)
    # Binance spot regular tier; set your real tier / BNB discount here.
    fees: FeeConfig = FeeConfig(maker_bps=10.0, taker_bps=10.0)
    depth_symbols: list[str] = Field(default_factory=lambda: ["BTCUSDT", "ETHUSDT"])
    depth_snapshot_limit: int = Field(1000, ge=5, le=5000)
    min_symbols: int = Field(50, ge=1)
    max_symbols: int = Field(60, ge=1)
    quote_assets: list[str] = Field(default_factory=lambda: ["USDT"])
    explicit_symbols: list[str] = Field(default_factory=list)
    required_symbols: list[str] = Field(default_factory=lambda: list(DEFAULT_REQUIRED_SYMBOLS))
    exclude_symbols: list[str] = Field(default_factory=list)
    fallback_symbols: list[str] = Field(default_factory=lambda: list(DEFAULT_FALLBACK_SYMBOLS))
    subscribe_trades: bool = True

    @field_validator("explicit_symbols", "required_symbols", "exclude_symbols", "fallback_symbols",
                     "depth_symbols", "quote_assets")
    @classmethod
    def _upper(cls, v: list[str]) -> list[str]:
        return [s.strip().upper() for s in v if s.strip()]

    @model_validator(mode="after")
    def _bounds(self) -> BinanceConfig:
        if self.max_symbols < self.min_symbols:
            raise ValueError("max_symbols must be >= min_symbols")
        return self


class CoinbaseConfig(VenueConfig):
    ws_base_url: str = "wss://advanced-trade-ws.coinbase.com"
    rest_base_url: str = "https://api.coinbase.com"
    # Coinbase recommends few products per subscription; level2 snapshots are large.
    max_symbols_per_connection: int = Field(10, ge=1)
    # Unauthenticated clients may send a small number of messages per second.
    subscribe_messages_per_second: float = Field(2.0, gt=0, le=8.0)
    rest_weight_budget_per_min: int = Field(300, ge=1)
    # Advanced Trade lowest volume tier at time of writing; configure yours.
    fees: FeeConfig = FeeConfig(maker_bps=60.0, taker_bps=120.0)
    # Products are chosen to overlap the Binance universe (same base asset).
    explicit_products: list[str] = Field(default_factory=list)
    quote_currencies: list[str] = Field(default_factory=lambda: ["USD", "USDT"])
    max_products: int = Field(40, ge=1)
    # Always subscribed: needed as conversion instruments.
    required_products: list[str] = Field(default_factory=lambda: ["BTC-USD", "ETH-USD", "USDT-USD", "BTC-USDT", "ETH-USDT"])
    use_level2: bool = True  # BBO derived from level2; without it only trades
    quiet_after_ms: int = Field(3_000, ge=1)
    connection_stall_ms: int = Field(8_000, ge=100)  # heartbeats arrive every second

    @field_validator("explicit_products", "required_products", "quote_currencies", "depth_symbols")
    @classmethod
    def _upper(cls, v: list[str]) -> list[str]:
        return [s.strip().upper() for s in v if s.strip()]


class RegistryConfig(_Model):
    verified_assets: list[str] = Field(default_factory=lambda: list(DEFAULT_VERIFIED_ASSETS))
    # native ticker -> canonical asset id, per venue (renames, wrapped assets)
    asset_aliases: dict[str, dict[str, str]] = Field(default_factory=lambda: {
        "BINANCE": {"RNDR": "RENDER"},
        "COINBASE": {"RNDR": "RENDER"},
    })
    allow_inferred_mapping: bool = False
    # Instruments usable to convert between quote currencies (bid/ask, fees, freshness
    # and liquidity all applied). Order matters only for preference.
    conversion_instruments: list[str] = Field(default_factory=lambda: [
        "COINBASE:USDT-USD", "BINANCE:USDCUSDT", "BINANCE:FDUSDUSDT"])


class FeedConfig(_Model):
    watchdog_interval_ms: int = Field(250, ge=10)
    max_delivery_lag_ms: int = Field(2_000, ge=1)


class BackoffConfig(_Model):
    base_s: float = Field(0.5, gt=0)
    cap_s: float = Field(30.0, gt=0)
    rate_limited_min_s: float = Field(60.0, gt=0)
    stable_after_s: float = Field(30.0, gt=0)


class EngineConfig(_Model):
    trade_queue_capacity: int = Field(16384, ge=16)
    loop_lag_interval_ms: int = Field(50, ge=5)
    loop_lag_degraded_ms: float = Field(50.0, gt=0)
    summary_interval_ms: int = Field(1000, ge=50)       # health/summary/dashboard cadence
    feature_interval_ms: int = Field(100, ge=10)        # feature-grid sampling period
    baseline_refresh_ms: int = Field(1000, ge=50)       # robust baseline recomputation
    feature_history_s: float = Field(120.0, gt=1)
    report_interval_s: float = Field(10.0, gt=0)


class CrossExchangeConfig(_Model):
    enabled: bool = True
    min_gross_edge_bps: float = 0.0       # record a candidate when buy-ask < sell-bid
    min_net_edge_bps: float = 2.0
    max_quote_age_ms: int = Field(1500, ge=1)
    max_recv_skew_ms: int = Field(500, ge=0)
    max_event_skew_ms: int = Field(750, ge=0)
    max_notional_usd: float = Field(2_000.0, gt=0)
    min_liquidity_usd: float = Field(50.0, ge=0)
    max_slippage_bps: float = Field(10.0, ge=0)
    use_conversions: bool = True
    max_conversion_age_ms: int = Field(5000, ge=1)
    est_execution_latency_ms: float = Field(150.0, ge=0)


class TriangularConfig(_Model):
    enabled: bool = True
    venue: str = "BINANCE"
    start_assets: list[str] = Field(default_factory=lambda: ["USDT"])
    min_net_edge_bps: float = 1.0
    max_start_notional_usd: float = Field(1_000.0, gt=0)
    max_quote_age_ms: int = Field(1500, ge=1)
    max_recv_skew_ms: int = Field(500, ge=0)


class AnomalyConfig(_Model):
    enabled: bool = True
    windows_s: list[float] = Field(default_factory=lambda: [1.0, 5.0, 30.0, 60.0])
    baseline_s: float = Field(60.0, gt=1)
    z_threshold: float = Field(5.0, gt=0)
    min_coverage: float = Field(0.8, gt=0, le=1)       # fraction of non-missing samples required
    min_sigma_bps: float = Field(0.5, ge=0)            # floor on robust dispersion (zero-vol guard)
    spread_ratio_threshold: float = Field(4.0, gt=1)
    liquidity_drop_ratio: float = Field(0.15, gt=0, lt=1)
    volume_ratio_threshold: float = Field(6.0, gt=1)
    divergence_z_threshold: float = Field(6.0, gt=0)
    cooldown_s: float = Field(10.0, ge=0)


class PatternConfig(_Model):
    enabled: bool = True
    strategies: list[str] = Field(default_factory=lambda: [
        "momentum_acceleration", "mean_reversion", "volatility_expansion", "breakout",
        "price_volume_divergence", "lead_lag", "btc_relative", "book_imbalance"])
    z_entry: float = Field(3.0, gt=0)
    vol_expansion_ratio: float = Field(3.0, gt=1)
    imbalance_threshold: float = Field(0.6, gt=0, lt=1)
    cooldown_s: float = Field(15.0, ge=0)
    eval_horizons_s: list[float] = Field(default_factory=lambda: [1.0, 5.0, 30.0])


class StrategiesConfig(_Model):
    cross_exchange: CrossExchangeConfig = Field(default_factory=CrossExchangeConfig)
    triangular: TriangularConfig = Field(default_factory=TriangularConfig)
    anomalies: AnomalyConfig = Field(default_factory=AnomalyConfig)
    patterns: PatternConfig = Field(default_factory=PatternConfig)


class PaperConfig(_Model):
    """Simulated execution. There is no other execution mode."""

    mode: Literal["paper"] = "paper"
    enabled: bool = True
    # Starting virtual balances, per venue and canonical asset.
    starting_balances: dict[str, dict[str, float]] = Field(default_factory=lambda: {
        "BINANCE": {"USDT": 50_000.0, "BTC": 0.5, "ETH": 5.0},
        "COINBASE": {"USD": 50_000.0, "USDT": 10_000.0, "BTC": 0.5, "ETH": 5.0},
    })
    # Virtual base inventory (USD value) granted per traded asset on first valid mark.
    auto_base_inventory_usd: float = Field(5_000.0, ge=0)
    order_latency_ms: dict[str, float] = Field(default_factory=lambda: {"BINANCE": 60.0, "COINBASE": 90.0})
    latency_jitter_ms: float = Field(20.0, ge=0)
    # Extra decision/processing delay before an order is created (replay/backtest knob;
    # live runs measure their real processing time instead).
    processing_delay_ms: float = Field(0.0, ge=0)
    leg_latency_ms: float = Field(5.0, ge=0)          # between sequential triangular legs
    limit_slippage_bps: float = Field(5.0, ge=0)       # IOC limit price tolerance vs detection price
    gtc_ttl_ms: int = Field(30_000, ge=1)
    trade_strategies: list[str] = Field(default_factory=lambda: ["cross_exchange", "triangular"])
    seed: int = 42

    @field_validator("mode", mode="before")
    @classmethod
    def _paper_only(cls, v: Any) -> Any:
        if v != "paper":
            raise ValueError("only paper trading exists in this application")
        return v


class RiskConfig(_Model):
    max_order_notional_usd: float = Field(2_500.0, gt=0)
    max_position_usd_per_asset: float = Field(10_000.0, gt=0)
    max_exposure_usd_per_venue: float = Field(25_000.0, gt=0)
    max_total_exposure_usd: float = Field(40_000.0, gt=0)
    max_daily_loss_usd: float = Field(1_000.0, gt=0)
    min_net_edge_bps: float = 2.0
    max_quote_age_ms: int = Field(1500, ge=1)
    max_skew_ms: int = Field(500, ge=0)
    max_slippage_bps: float = Field(10.0, ge=0)
    min_liquidity_usd: float = Field(50.0, ge=0)
    max_signals_per_minute: int = Field(20, ge=1)    # per strategy+instrument/route
    duplicate_window_ms: int = Field(5_000, ge=0)
    halt_on_health: list[str] = Field(default_factory=lambda: ["DOWN"])


class PersistenceConfig(_Model):
    enabled: bool = True
    database_url: SecretStr | None = None            # postgresql://... (env only, never logged)
    queue_capacity: int = Field(50_000, ge=10)
    batch_size: int = Field(500, ge=1)
    flush_interval_ms: int = Field(250, ge=10)
    jsonl_dir: str | None = "data/audit"             # used when no database is configured
    balance_snapshot_interval_s: float = Field(10.0, gt=0)


class ApiConfig(_Model):
    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = Field(8080, ge=0, le=65535)
    dashboard_dir: str | None = None                 # built dashboard (dist/) to serve at /
    # Required (header X-Control-Token) for the simulation control endpoints
    # (emergency stop / resume). Without it those endpoints are disabled.
    control_token: SecretStr | None = None


class RecordingConfig(_Model):
    enabled: bool = False
    directory: str = "recordings"
    queue_capacity: int = Field(200_000, ge=1)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MIE_", env_nested_delimiter="__", extra="ignore")

    data_source: DataSource = DataSource.LIVE
    binance: BinanceConfig = Field(default_factory=BinanceConfig)
    coinbase: CoinbaseConfig = Field(default_factory=CoinbaseConfig)
    registry: RegistryConfig = Field(default_factory=RegistryConfig)
    feed: FeedConfig = Field(default_factory=FeedConfig)
    backoff: BackoffConfig = Field(default_factory=BackoffConfig)
    engine: EngineConfig = Field(default_factory=EngineConfig)
    strategies: StrategiesConfig = Field(default_factory=StrategiesConfig)
    paper: PaperConfig = Field(default_factory=PaperConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    persistence: PersistenceConfig = Field(default_factory=PersistenceConfig)
    api: ApiConfig = Field(default_factory=ApiConfig)
    recording: RecordingConfig = Field(default_factory=RecordingConfig)
    log_level: str = "INFO"

    @model_validator(mode="after")
    def _live_means_official_hosts(self) -> Settings:
        if self.data_source is DataSource.LIVE:
            checks = [(self.binance, (".binance.com", ".binance.vision")),
                      (self.coinbase, (".coinbase.com",))]
            for venue, suffixes in checks:
                if not venue.enabled:
                    continue
                for url in (venue.ws_base_url, venue.rest_base_url):
                    host = urlsplit(url).hostname or ""
                    if not host.endswith(suffixes):
                        raise ValueError(
                            f"data_source=LIVE requires official exchange endpoints, got {host!r}; "
                            "use data_source=SIMULATED or REPLAY for other sources")
        return self

    def venue(self, name: str) -> VenueConfig:
        return {"BINANCE": self.binance, "COINBASE": self.coinbase}[name]

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
