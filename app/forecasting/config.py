"""Configuration for the forecasting platform.

Follows the layered-config convention of the other subsystems: Pydantic
defaults, overridable via YAML (``config/<env>.yaml`` -> ``forecasting:``
block) and environment variables. The DI layer validates the raw YAML block
into a `ForecastConfig`.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ForecastConfig(BaseSettings):
    """Runtime settings for the forecasting platform."""

    enabled: bool = True

    # The model used when a request does not name one. `ensemble` combines all
    # available member models (inverse-variance weighted). Any registered model
    # name may be used instead.
    default_model: str = "ensemble"

    # Guardrails.
    max_horizon: int = 36        # max look-ahead periods a request may ask for
    max_batch_size: int = 50     # max items per batch-forecast call

    # Feature toggles. Statistical models are always available. ML models are
    # only registered when `enable_ml` is true AND sklearn is installed
    # (`pip install '.[forecasting]'`); LLM reasoning is always available and
    # produces a deterministic narrative unless a real provider is wired.
    enable_ml: bool = True
    enable_llm: bool = True

    # The member models used by the ensemble (subset of registered names).
    ensemble_members: list[str] = Field(
        default_factory=lambda: [
            "moving_average",
            "exponential_smoothing",
            "linear_trend",
            "seasonal_average",
            "persistence",
            "llm_reasoning",
        ]
    )

    # LLM reasoning provider: "reasoning" (deterministic baseline + narrative,
    # no external call). Future: "openai" / "anthropic" plug in here.
    llm_provider: str = "reasoning"

    model_config = SettingsConfigDict(extra="ignore")
