"""Data models for the profit engine.

Design decisions:
- Input and output are separate Pydantic models.
- Every fee component is itemized in the output for transparency.
- All monetary values use Decimal for precision.
- All percentages are stored as Decimal (e.g., 15.00 = 15%).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field


class FeeComponent(BaseModel):
    """A single fee or cost component in the profit calculation."""

    name: str = Field(..., description="Fee name (e.g., 'Referral Fee', 'FBA Fee')")
    category: str = Field(..., description="Category: fixed, percentage, or variable")
    amount: Decimal = Field(..., ge=0, description="Fee amount in currency")
    description: str | None = Field(None, description="How this fee was calculated")


class FeeCategory:
    """Constants for fee categories."""

    FIXED = "fixed"
    PERCENTAGE = "percentage"
    VARIABLE = "variable"


class ProfitInput(BaseModel):
    """Input parameters for profit calculation.

    All monetary values in the same currency (default USD).
    """

    # ── Revenue ─────────────────────────────────────────────
    amazon_price: Decimal = Field(..., gt=0, description="Amazon selling price per unit")
    quantity: int = Field(default=1, ge=1, description="Number of units")

    # ── Costs ───────────────────────────────────────────────
    supplier_price: Decimal = Field(..., gt=0, description="Cost per unit from supplier")
    shipping_cost: Decimal = Field(default=Decimal("0"), ge=0, description="Shipping cost per unit")
    prep_cost: Decimal = Field(default=Decimal("0"), ge=0, description="Labeling/packaging cost per unit")
    other_costs: Decimal = Field(default=Decimal("0"), ge=0, description="Miscellaneous costs per unit")

    # ── Amazon Fees ────────────────────────────────────────
    referral_fee_percent: Decimal | None = Field(
        None, description="Referral fee percentage (e.g., 15.00 = 15%). Overrides config.",
    )
    referral_fee_min: Decimal | None = Field(
        None, description="Minimum referral fee. Overrides config.",
    )
    fba_fulfillment_fee: Decimal | None = Field(
        None, description="FBA fulfillment fee per unit. Overrides config.",
    )
    fba_storage_fee: Decimal | None = Field(
        None, description="Monthly storage fee per unit. Overrides config.",
    )
    closing_fee: Decimal = Field(default=Decimal("0"), ge=0, description="Closing fee (media products)")

    # ── Taxes ──────────────────────────────────────────────
    sales_tax_percent: Decimal = Field(
        default=Decimal("0"), ge=0, le=100,
        description="Sales tax percentage (e.g., 8.875 = 8.875%)",
    )

    # ── Discounts & Incentives ─────────────────────────────
    coupon_discount: Decimal = Field(
        default=Decimal("0"), ge=0,
        description="Coupon discount amount per unit",
    )
    cashback_percent: Decimal = Field(
        default=Decimal("0"), ge=0, le=100,
        description="Cashback percentage (e.g., 2.0 = 2%)",
    )
    credit_card_rewards_percent: Decimal = Field(
        default=Decimal("0"), ge=0, le=100,
        description="Credit card rewards percentage (e.g., 1.5 = 1.5%)",
    )
    supplier_discount_percent: Decimal = Field(
        default=Decimal("0"), ge=0, le=100,
        description="Supplier volume discount percentage",
    )

    # ── Capital ────────────────────────────────────────────
    capital_invested: Decimal | None = Field(
        None, description="Total capital invested (for ROI calculation). "
        "If None, calculated as (supplier_price + shipping) * quantity.",
    )

    # ── Metadata ───────────────────────────────────────────
    currency: str = Field(default="USD", description="Currency code")
    notes: str | None = Field(None, description="Optional notes about this calculation")


class ProfitOutput(BaseModel):
    """Complete profit calculation output."""

    # ── Revenue ─────────────────────────────────────────────
    total_revenue: Decimal = Field(..., description="Total revenue (amazon_price * quantity)")
    revenue_per_unit: Decimal = Field(..., description="Revenue per unit")

    # ── Costs ───────────────────────────────────────────────
    total_cost: Decimal = Field(..., description="Total cost (all fees + expenses)")
    cost_per_unit: Decimal = Field(..., description="Total cost per unit")
    cost_breakdown: list[FeeComponent] = Field(
        default_factory=list, description="Itemized cost breakdown",
    )

    # ── Profit Metrics ──────────────────────────────────────
    gross_profit: Decimal = Field(..., description="Revenue - supplier_price")
    net_profit: Decimal = Field(..., description="Revenue - total_cost")
    net_profit_per_unit: Decimal = Field(..., description="Net profit divided by quantity")

    # ── Percentage Metrics ─────────────────────────────────
    margin_percentage: Decimal = Field(
        ..., description="Net profit / Revenue * 100",
    )
    roi_percentage: Decimal = Field(
        ..., description="Net profit / Capital invested * 100",
    )
    markup_percentage: Decimal = Field(
        ..., description="(Revenue - Cost) / Cost * 100",
    )

    # ── Break-even ──────────────────────────────────────────
    break_even_price: Decimal = Field(
        ..., description="Minimum Amazon price to break even",
    )
    break_even_quantity: int = Field(
        ..., description="Minimum units to sell to break even (at current price)",
    )

    # ── Return on Capital ──────────────────────────────────
    return_on_capital: Decimal = Field(
        ..., description="Net profit / Capital invested (as decimal, e.g., 0.25 = 25%)",
    )
    capital_invested: Decimal = Field(
        ..., description="Total capital invested",
    )

    # ── Per-Unit Summary ──────────────────────────────────
    amazon_fees_per_unit: Decimal = Field(
        ..., description="Total Amazon fees per unit",
    )
    taxes_per_unit: Decimal = Field(
        ..., description="Sales tax per unit",
    )
    discounts_per_unit: Decimal = Field(
        ..., description="Total discounts per unit",
    )

    # ── Metadata ───────────────────────────────────────────
    currency: str = Field(default="USD", description="Currency code")
    is_profitable: bool = Field(..., description="Is net_profit > 0?")
