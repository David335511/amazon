"""Configuration for the reverse sourcing engine.

Layered-config convention shared by the other subsystems: Pydantic defaults,
overridable via YAML (``config/<env>.yaml`` -> ``reverse_sourcing:`` block) and
environment variables. The DI layer validates the raw YAML block into a
`ReverseSourcingConfig`.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ReverseSourcingConfig(BaseSettings):
    """Runtime settings for reverse sourcing."""

    enabled: bool = True

    # Defaults applied when a request does not specify them.
    default_currency: str = "USD"
    default_quantity: int = 1

    # Guardrails.
    max_suppliers: int = 50        # cap on offers evaluated in one run
    max_batch_size: int = 50

    # Horizon for predicted-future-discount.
    forecast_horizon: int = 1

    # Weights for the supplier ranking score (normalized internally).
    # price, speed, availability, discount, reliability, risk_inverse
    rank_weights: list[float] = Field(default_factory=lambda: [0.30, 0.20, 0.15, 0.10, 0.15, 0.10])

    model_config = SettingsConfigDict(extra="ignore")
