"""Event bus configuration.

Follows the same layered-config convention as every other subsystem: Pydantic
defaults, overridable via YAML (``config/<env>.yaml``) and environment vars.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class EventBusConfig(BaseSettings):
    """Runtime settings for the internal event bus."""

    enabled: bool = True

    # Retry policy defaults (used when a subscription does not override them).
    default_max_retries: int = 3
    backoff_base_ms: int = 200
    backoff_max_ms: int = 5000
    jitter: bool = True

    # Dead letter queue capacity (in-memory retained records).
    dlq_capacity: int = 1000

    # Future distributed broker transport. "memory" is the built-in in-process
    # broker; "redis" selects the Redis Streams broker (off by default).
    broker_type: str = "memory"

    model_config = SettingsConfigDict(extra="ignore")
