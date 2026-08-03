"""Application configuration management.

Design decisions:
- Layered configuration: YAML files provide environment-specific defaults,
  environment variables override for secrets/deployment-specific values,
  and Pydantic validates everything at startup.
- The YAML config is loaded first, then env vars override specific keys.
- Pydantic Settings handles env var parsing with type coercion.
- All config is frozen (immutable) after loading to prevent runtime mutation.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, ClassVar

import yaml
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.security import SecurityConfig
from app.events.config import EventBusConfig

# ──────────────────────────────────────────────────────────────
# YAML Configuration Loader
# ──────────────────────────────────────────────────────────────


def load_yaml_config(env: str | None = None) -> dict[str, Any]:
    """Load YAML configuration for the given environment.

    Falls back to APP_ENV env var, then 'development'.
    """
    if env is None:
        env = os.getenv("APP_ENV", "development")

    config_dir = Path(__file__).resolve().parent.parent.parent / "config"
    config_path = config_dir / f"{env}.yaml"

    if not config_path.exists():
        msg = f"Configuration file not found: {config_path}"
        raise FileNotFoundError(msg)

    with open(config_path) as f:
        return yaml.safe_load(f) or {}


def _apply_env_overrides(
    model_cls: type[BaseSettings],
    yaml_section: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build constructor kwargs from YAML, honoring env-var precedence.

    YAML stores values under field names, but pydantic-settings only accepts
    init kwargs for *aliased* fields under the alias name (e.g. ``DATABASE_URL``,
    ``OTEL_EXPORTER_OTLP_ENDPOINT``). We emit alias keys where aliases exist, and
    skip a value entirely when the matching environment variable is present so
    that env vars win over YAML.
    """
    yaml_data = dict(yaml_section or {})
    out: dict[str, Any] = {}
    for field_name, field_info in model_cls.model_fields.items():
        alias = field_info.validation_alias
        alias_name = alias if isinstance(alias, str) else None
        # A live env var overrides this field — skip the YAML value so env wins.
        if alias_name is not None and os.getenv(alias_name) is not None:
            continue
        if field_name in yaml_data:
            out[alias_name or field_name] = yaml_data[field_name]
    return out


# ──────────────────────────────────────────────────────────────
# Pydantic Models for Configuration Sections
# ──────────────────────────────────────────────────────────────


class AppConfig(BaseSettings):
    """Application metadata and behaviour settings."""

    name: str = "Amazon"
    debug: bool = False
    log_level: str = "INFO"
    secret_key: str = Field(default="", validation_alias="APP_SECRET_KEY")
    cors: dict[str, Any] = Field(default_factory=lambda: {"allowed_origins": ["*"]})

    model_config = SettingsConfigDict(extra="ignore")


class DatabaseConfig(BaseSettings):
    """PostgreSQL connection and pool settings."""

    url: str = Field(
        default="postgresql+asyncpg://amazon:amazon@localhost:5432/amazon",
        validation_alias="DATABASE_URL",
    )
    pool_size: int = 10
    max_overflow: int = 20
    echo: bool = False
    pool_pre_ping: bool = True
    pool_recycle: int = 3600

    model_config = SettingsConfigDict(extra="ignore")


class RedisConfig(BaseSettings):
    """Redis connection settings."""

    url: str = Field(
        default="redis://localhost:6379/0",
        validation_alias="REDIS_URL",
    )
    socket_connect_timeout: int = 5
    # Must be LARGER than the max BLPOP block timeout used by the agent workers
    # (default 5s). If socket_timeout <= blpop timeout, an empty-queue BLPOP holds
    # the connection for the full block and the client's read timeout fires first,
    # raising "Timeout reading from ..." on every empty dequeue (Upstash proxy).
    socket_timeout: int = 20
    retry_on_timeout: bool = True
    # Keep connections alive through serverless proxies (Upstash closes idle
    # connections aggressively).
    socket_keepalive: bool = True
    health_check_interval: int = 30

    model_config = SettingsConfigDict(extra="ignore")


class ServerConfig(BaseSettings):
    """Uvicorn server settings."""

    host: str = "0.0.0.0"
    port: int = 8000
    reload: bool = False
    workers: int = 1
    max_request_size: int = 10_485_760  # 10 MB

    model_config = SettingsConfigDict(extra="ignore")


class LoggingConfig(BaseSettings):
    """Structured logging configuration."""

    format: str = "json"
    level: str = "INFO"
    handlers: list[str] = Field(default_factory=lambda: ["console"])
    file_path: str | None = None
    rotation: str | None = "1 day"
    retention: str | None = "30 days"

    model_config = SettingsConfigDict(extra="ignore")


class TelemetryConfig(BaseSettings):
    """OpenTelemetry configuration for observability."""

    enabled: bool = True
    service_name: str = Field(default="amazon", validation_alias="OTEL_SERVICE_NAME")
    exporter_otlp_endpoint: str | None = Field(
        default="http://localhost:4317",
        validation_alias="OTEL_EXPORTER_OTLP_ENDPOINT",
    )
    exporter_otlp_headers: str = Field(
        default="",
        validation_alias="OTEL_EXPORTER_OTLP_HEADERS",
    )
    traces_sampler: str = "parentbased_always_on"
    metrics_exporter: str = "none"
    logs_exporter: str = "none"
    instrument_fastapi: bool = True
    instrument_sqlalchemy: bool = True
    instrument_redis: bool = True

    model_config = SettingsConfigDict(extra="ignore")


class FeaturesConfig(BaseSettings):
    """Feature flags to toggle platform capabilities."""

    enable_swagger: bool = True
    enable_metrics: bool = True
    rate_limiting: bool = False

    model_config = SettingsConfigDict(extra="ignore")


# ──────────────────────────────────────────────────────────────
# Root Settings — Composed from YAML + Env Vars
# ──────────────────────────────────────────────────────────────


class Settings(BaseSettings):
    """Root configuration object.

    Loads YAML first, then overlays environment variables.
    All sub-configs are frozen after construction.
    """

    app: AppConfig
    database: DatabaseConfig
    redis: RedisConfig
    server: ServerConfig
    logging: LoggingConfig
    telemetry: TelemetryConfig
    features: FeaturesConfig
    # Raw YAML block for the browser automation framework. Validated lazily
    # into `app.browser.config.BrowserAutomationConfig` by the DI layer.
    browser: dict[str, Any] = Field(default_factory=dict)
    event_bus: EventBusConfig
    # Raw YAML block for the AI memory system. Validated lazily into
    # `app.memory.config.MemoryConfig` by the DI layer.
    memory: dict[str, Any] = Field(default_factory=dict)
    # Raw YAML block for the computer-vision subsystem. Validated lazily into
    # `app.vision.config.VisionConfig` by the DI layer.
    vision: dict[str, Any] = Field(default_factory=dict)
    # Raw YAML block for the document intelligence system. Validated lazily into
    # `app.documents.config.DocumentConfig` by the DI layer.
    documents: dict[str, Any] = Field(default_factory=dict)
    # Raw YAML block for the feature engineering platform. Validated lazily into
    # `app.features.config.FeatureConfig` by the DI layer.
    feature_store: dict[str, Any] = Field(default_factory=dict)
    # Raw YAML block for the forecasting platform. Validated lazily into
    # `app.forecasting.config.ForecastConfig` by the DI layer.
    forecasting: dict[str, Any] = Field(default_factory=dict)
    # Raw YAML block for the financial optimization engine. Validated lazily
    # into `app.finance.config.FinanceConfig` by the DI layer.
    finance: dict[str, Any] = Field(default_factory=dict)
    # Raw YAML block for supplier intelligence. Validated lazily into
    # `app.supplier_intel.config.SupplierIntelConfig` by the DI layer.
    supplier_intel: dict[str, Any] = Field(default_factory=dict)
    # Raw YAML block for the reverse sourcing engine. Validated lazily into
    # `app.reverse_sourcing.config.ReverseSourcingConfig` by the DI layer.
    reverse_sourcing: dict[str, Any] = Field(default_factory=dict)
    # Raw YAML block for the multi-agent orchestration framework. Validated
    # lazily into `app.multiagent.config.MultiAgentConfig` by the DI layer.
    multiagent: dict[str, Any] = Field(default_factory=dict)
    # Raw YAML block for the experimentation platform. Validated lazily into
    # `app.experiments.config.ExperimentConfig` by the DI layer.
    experiments: dict[str, Any] = Field(default_factory=dict)
    # Raw YAML block for the commerce knowledge graph. Validated lazily into
    # `app.knowledge_graph.config.KnowledgeGraphConfig` by the DI layer.
    knowledge_graph: dict[str, Any] = Field(default_factory=dict)
    # Raw YAML block for the continuous-learning platform. Validated lazily into
    # `app.learning.config.LearningConfig` by the DI layer.
    learning: dict[str, Any] = Field(default_factory=dict)
    # Raw YAML block for the internationalization system. Validated lazily into
    # `app.i18n.config.I18nConfig` by the DI layer.
    i18n: dict[str, Any] = Field(default_factory=dict)
    # Raw YAML block for multilingual AI support. Validated lazily into
    # `app.multilingual.config.MultilingualConfig` by the DI layer.
    multilingual: dict[str, Any] = Field(default_factory=dict)
    # API security (Phase 0). Disabled by default so local dev is unaffected;
    # set `enabled: true` and provide API keys to protect the API.
    security: SecurityConfig = Field(default_factory=SecurityConfig)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        frozen=True,
        extra="ignore",
        case_sensitive=False,
    )

    # Cache the loaded instance
    _instance: ClassVar[Settings | None] = None

    @classmethod
    def load(cls, env: str | None = None) -> Settings:
        """Load or return cached settings singleton."""
        if cls._instance is not None:
            return cls._instance

        yaml_data = load_yaml_config(env)

        # Merge YAML data with env-var-backed Pydantic models.
        # Env vars win over YAML (see _apply_env_overrides).
        app_cfg = AppConfig(**_apply_env_overrides(AppConfig, yaml_data.get("app", {})))
        db_cfg = DatabaseConfig(
            **_apply_env_overrides(DatabaseConfig, yaml_data.get("database", {}))
        )
        redis_cfg = RedisConfig(**_apply_env_overrides(RedisConfig, yaml_data.get("redis", {})))
        server_cfg = ServerConfig(**_apply_env_overrides(ServerConfig, yaml_data.get("server", {})))
        logging_cfg = LoggingConfig(
            **_apply_env_overrides(LoggingConfig, yaml_data.get("logging", {}))
        )
        telemetry_cfg = TelemetryConfig(
            **_apply_env_overrides(TelemetryConfig, yaml_data.get("telemetry", {}))
        )
        features_cfg = FeaturesConfig(
            **_apply_env_overrides(FeaturesConfig, yaml_data.get("features", {}))
        )
        event_bus_cfg = EventBusConfig(
            **_apply_env_overrides(EventBusConfig, yaml_data.get("event_bus", {}))
        )
        # Security block: apply YAML defaults, then let explicit env vars win.
        # The fields have no pydantic aliases, so handle them here directly.
        security_kwargs = _apply_env_overrides(SecurityConfig, yaml_data.get("security", {}))
        if os.getenv("SECURITY_ENABLED") is not None:
            security_kwargs["enabled"] = os.getenv("SECURITY_ENABLED", "").lower() in (
                "1", "true", "yes",
            )
        if os.getenv("API_KEYS") is not None:
            security_kwargs["api_keys"] = [
                k.strip() for k in os.getenv("API_KEYS", "").split(",") if k.strip()
            ]
        security_cfg = SecurityConfig(**security_kwargs)

        instance = cls(
            app=app_cfg,
            database=db_cfg,
            redis=redis_cfg,
            server=server_cfg,
            logging=logging_cfg,
            telemetry=telemetry_cfg,
            features=features_cfg,
            browser=dict(yaml_data.get("browser", {})),
            memory=dict(yaml_data.get("memory", {})),
            vision=dict(yaml_data.get("vision", {})),
            documents=dict(yaml_data.get("documents", {})),
            feature_store=dict(yaml_data.get("feature_store", {})),
            forecasting=dict(yaml_data.get("forecasting", {})),
            finance=dict(yaml_data.get("finance", {})),
            supplier_intel=dict(yaml_data.get("supplier_intel", {})),
            reverse_sourcing=dict(yaml_data.get("reverse_sourcing", {})),
            multiagent=dict(yaml_data.get("multiagent", {})),
            experiments=dict(yaml_data.get("experiments", {})),
            knowledge_graph=dict(yaml_data.get("knowledge_graph", {})),
            learning=dict(yaml_data.get("learning", {})),
            i18n=dict(yaml_data.get("i18n", {})),
            multilingual=dict(yaml_data.get("multilingual", {})),
            event_bus=event_bus_cfg,
            security=security_cfg,
        )
        cls._instance = instance
        return instance

    @classmethod
    def reset(cls) -> None:
        """Clear cached settings (useful for testing)."""
        cls._instance = None

    @field_validator("app", mode="before")
    @classmethod
    def _validate_app(cls, v: Any) -> Any:
        if isinstance(v, dict):
            return AppConfig(**v)
        return v

    @field_validator("database", mode="before")
    @classmethod
    def _validate_database(cls, v: Any) -> Any:
        if isinstance(v, dict):
            return DatabaseConfig(**v)
        return v

    @field_validator("redis", mode="before")
    @classmethod
    def _validate_redis(cls, v: Any) -> Any:
        if isinstance(v, dict):
            return RedisConfig(**v)
        return v

    @field_validator("server", mode="before")
    @classmethod
    def _validate_server(cls, v: Any) -> Any:
        if isinstance(v, dict):
            return ServerConfig(**v)
        return v

    @field_validator("logging", mode="before")
    @classmethod
    def _validate_logging(cls, v: Any) -> Any:
        if isinstance(v, dict):
            return LoggingConfig(**v)
        return v

    @field_validator("telemetry", mode="before")
    @classmethod
    def _validate_telemetry(cls, v: Any) -> Any:
        if isinstance(v, dict):
            return TelemetryConfig(**v)
        return v

    @field_validator("features", mode="before")
    @classmethod
    def _validate_features(cls, v: Any) -> Any:
        if isinstance(v, dict):
            return FeaturesConfig(**v)
        return v

    @field_validator("event_bus", mode="before")
    @classmethod
    def _validate_event_bus(cls, v: Any) -> Any:
        if isinstance(v, dict):
            return EventBusConfig(**v)
        return v

    @field_validator("security", mode="before")
    @classmethod
    def _validate_security(cls, v: Any) -> Any:
        if isinstance(v, dict):
            return SecurityConfig(**v)
        return v

# Module-level convenience
settings = Settings.load()
