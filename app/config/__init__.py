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
    """Drop YAML keys that have a live environment variable override.

    pydantic-settings gives init kwargs higher priority than env vars, so a
    YAML value passed as a keyword argument would otherwise shadow the env var.
    Removing those keys lets the environment win, matching the documented design
    intent that "env vars override for secrets/deployment-specific values".
    """
    out = dict(yaml_section or {})
    for field_name, field_info in model_cls.model_fields.items():
        alias = field_info.validation_alias
        if isinstance(alias, str) and os.getenv(alias) is not None:
            out.pop(field_name, None)
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
    socket_timeout: int = 5
    retry_on_timeout: bool = True
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

        instance = cls(
            app=app_cfg,
            database=db_cfg,
            redis=redis_cfg,
            server=server_cfg,
            logging=logging_cfg,
            telemetry=telemetry_cfg,
            features=features_cfg,
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


# Module-level convenience
settings = Settings.load()
