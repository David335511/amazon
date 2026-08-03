"""Configuration for the feature engineering platform.

Follows the layered-config convention of the other subsystems: Pydantic
defaults, overridable via YAML (``config/<env>.yaml`` -> ``feature_store:``
block) and environment variables. The DI layer validates the raw YAML block
into a `FeatureConfig`.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class FeatureConfig(BaseSettings):
    """Runtime settings for the feature engineering platform."""

    enabled: bool = True

    # Default freshness TTL (seconds) applied when a feature computer does not
    # declare its own `ttl_seconds`. A stored value is served from the store
    # until `computed_at + ttl`; after that it is recomputed on access.
    default_ttl_seconds: int = 3600  # 1 hour

    # Signal acquisition: "local" (default, uses provided/neutral signals).
    # Future providers (database, HTTP, feature-server) plug in here.
    signal_provider: str = "local"

    # Batch-calculate guardrail.
    max_batch_size: int = 100

    model_config = SettingsConfigDict(extra="ignore")
