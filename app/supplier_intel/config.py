"""Configuration for supplier intelligence.

Layered-config convention shared by the other subsystems: Pydantic defaults,
overridable via YAML (``config/<env>.yaml`` -> ``supplier_intel:`` block) and
environment variables. The DI layer validates the raw YAML block into a
`SupplierIntelConfig`.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class SupplierIntelConfig(BaseSettings):
    """Runtime settings for supplier intelligence."""

    enabled: bool = True

    # Scoring thresholds (pure heuristics, all configurable).
    # A shipping time at/above max_shipping_days scores zero on the
    # shipping-reliability component.
    max_shipping_days: float = 14.0
    # Coefficient-of-variation (of price / inventory) considered "high"
    # volatility. Used to normalize volatility components into 0..1.
    volatility_scale: float = 0.5
    # Frequencies (per period) at which coupon / sale activity earns full credit.
    max_coupon_rate: float = 5.0
    max_sale_rate: float = 5.0
    # Stockouts per period at which the supplier earns no credit.
    max_stockout_rate: float = 3.0
    # Number of observations needed for a score to reach full confidence.
    min_samples: int = 8

    # Guardrails.
    max_batch_size: int = 50

    # AI explanation provider: "reasoning" (deterministic narrative over the
    # historical scores and metrics, zero external calls). Future: "openai" /
    # "anthropic" plug in here.
    explanation_provider: str = "reasoning"

    # Weights for each composite score. Values are normalized internally, so
    # they only need to be proportional to each other.
    weights: dict[str, list[float]] = Field(
        default_factory=lambda: {
            # shipping, inventory, stockout, cancellation, service, returns
            "reliability": [0.20, 0.20, 0.20, 0.15, 0.15, 0.10],
            # price_vol, inventory_vol, shipping_vol, stockout_swing
            "volatility": [0.30, 0.30, 0.20, 0.20],
            # depth, coupon, sale
            "discount": [0.50, 0.25, 0.25],
            # volatility, stockout, cancellation, slow-ship, weak-service, weak-returns
            "risk": [0.25, 0.20, 0.20, 0.10, 0.15, 0.10],
        }
    )

    model_config = SettingsConfigDict(extra="ignore")
