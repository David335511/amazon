"""Configuration for the financial optimization engine.

Everything the engine recommends — how many units to buy, when to buy/reorder,
which opportunity wins capital, and how capital is allocated — is governed here.
Follows the layered-config convention: Pydantic defaults overridable via YAML
(``config/<env>.yaml`` -> ``finance:`` block) and environment variables. The DI
layer validates the raw YAML block into a `FinanceConfig`.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class FinanceConfig(BaseSettings):
    """Runtime settings for the financial optimization engine."""

    enabled: bool = True
    currency: str = "USD"
    starting_cash: float = 0.0

    # ── Credit cards ──────────────────────────────────────────────────────
    credit_card_limit: float = 0.0      # total credit available across cards
    billing_cycle_days: int = 30        # length of one credit card statement cycle
    grace_period_days: int = 21         # interest-free days after the statement closes

    # ── Rewards ───────────────────────────────────────────────────────────
    cashback_rate: float = 0.02         # % of purchase value returned as cashback
    reward_points_value: float = 0.01   # $ value of one reward point
    points_per_dollar: float = 1.0      # points earned per $1 of spend

    # ── Costs ─────────────────────────────────────────────────────────────
    holding_cost_rate: float = 0.25     # annual % of inventory value (storage etc.)
    order_cost: float = 5.0             # fixed cost per purchase order (unitless)

    # ── Inventory / demand ────────────────────────────────────────────────
    service_level_z: float = 1.65       # 95% service level for safety stock
    max_units_per_order: int = 1000     # hard cap on a single order quantity

    # ── Capital allocation ────────────────────────────────────────────────
    allocation_policy: str = "efficiency"  # efficiency | equal | conservative
    investable_fraction: float = 0.8    # fraction of usable capital to deploy
    min_cash_reserve: float = 0.0       # cash held back before allocating

    # ── Guardrails ────────────────────────────────────────────────────────
    max_batch_size: int = 50            # max opportunities per allocate call

    model_config = SettingsConfigDict(extra="ignore")
