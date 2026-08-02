"""Configurable fee rates and thresholds for the profit engine.

All rates are loaded from configuration and can be overridden per-calculation.
Default values reflect typical Amazon US marketplace rates as of 2025.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field


class AmazonFeeSchedule(BaseModel):
    """Amazon fee schedule for a specific category.

    Referral fees vary by product category. This model captures
    the percentage and any minimum fee for a given category.
    """

    category: str = Field(..., description="Amazon product category")
    referral_fee_percent: Decimal = Field(..., ge=0, le=50, description="Referral fee percentage")
    referral_fee_min: Decimal = Field(default=0, ge=0, description="Minimum referral fee")
    closing_fee: Decimal = Field(default=0, ge=0, description="Closing fee (media only)")


class FeeConfig(BaseModel):
    """Fee configuration for the profit engine.

    Contains default fee rates and thresholds. Individual values
    can be overridden per-calculation via ProfitInput.
    """

    # ── Referral Fees by Category ───────────────────────────
    default_referral_fee_percent: Decimal = Field(
        default=15.00, ge=0, le=50,
        description="Default referral fee percentage",
    )
    default_referral_fee_min: Decimal = Field(
        default=0, ge=0,
        description="Default minimum referral fee",
    )

    # ── FBA Fees ───────────────────────────────────────────
    # Standard-size fulfillment fees (as of 2025)
    small_standard_fulfillment: Decimal = Field(
        default=3.50, ge=0,
        description="Small standard-size FBA fulfillment fee",
    )
    large_standard_fulfillment: Decimal = Field(
        default=5.50, ge=0,
        description="Large standard-size FBA fulfillment fee",
    )
    small_oversize_fulfillment: Decimal = Field(
        default=8.50, ge=0,
        description="Small oversize FBA fulfillment fee",
    )
    large_oversize_fulfillment: Decimal = Field(
        default=12.50, ge=0,
        description="Large oversize FBA fulfillment fee",
    )

    # Monthly storage fees (per cubic foot)
    standard_monthly_storage: Decimal = Field(
        default=0.87, ge=0,
        description="Standard-size monthly storage per cubic foot",
    )
    oversize_monthly_storage: Decimal = Field(
        default=0.56, ge=0,
        description="Oversize monthly storage per cubic foot",
    )

    # ── Sales Tax ──────────────────────────────────────────
    default_sales_tax_percent: Decimal = Field(
        default=0, ge=0, le=100,
        description="Default sales tax percentage",
    )

    # ── Discounts ──────────────────────────────────────────
    default_coupon_discount: Decimal = Field(
        default=0, ge=0,
        description="Default coupon discount per unit",
    )
    default_cashback_percent: Decimal = Field(
        default=0, ge=0, le=100,
        description="Default cashback percentage",
    )
    default_credit_card_rewards_percent: Decimal = Field(
        default=0, ge=0, le=100,
        description="Default credit card rewards percentage",
    )


class ProfitConfig(BaseModel):
    """Root configuration for the profit engine."""

    fees: FeeConfig = Field(default_factory=FeeConfig, description="Fee configuration")
    category_schedules: list[AmazonFeeSchedule] = Field(
        default_factory=list,
        description="Category-specific fee schedules",
    )

    def get_referral_fee(self, category: str | None = None) -> tuple[Decimal, Decimal]:
        """Get referral fee percentage and minimum for a category.

        Args:
            category: Amazon product category name.

        Returns:
            Tuple of (referral_fee_percent, referral_fee_min).
        """
        if category:
            for schedule in self.category_schedules:
                if schedule.category.lower() == category.lower():
                    return schedule.referral_fee_percent, schedule.referral_fee_min

        return self.fees.default_referral_fee_percent, self.fees.default_referral_fee_min


# ── Default Configuration ────────────────────────────────────

DEFAULT_PROFIT_CONFIG = ProfitConfig(
    fees=FeeConfig(
        default_referral_fee_percent=Decimal("15.00"),
        default_referral_fee_min=Decimal("0"),
        small_standard_fulfillment=Decimal("3.50"),
        large_standard_fulfillment=Decimal("5.50"),
        small_oversize_fulfillment=Decimal("8.50"),
        large_oversize_fulfillment=Decimal("12.50"),
        standard_monthly_storage=Decimal("0.87"),
        oversize_monthly_storage=Decimal("0.56"),
        default_sales_tax_percent=Decimal("0"),
        default_coupon_discount=Decimal("0"),
        default_cashback_percent=Decimal("0"),
        default_credit_card_rewards_percent=Decimal("0"),
    ),
    category_schedules=[
        AmazonFeeSchedule(
            category="Electronics",
            referral_fee_percent=Decimal("8.00"),
            referral_fee_min=Decimal("0.30"),
        ),
        AmazonFeeSchedule(
            category="Cell Phone Accessories",
            referral_fee_percent=Decimal("15.00"),
            referral_fee_min=Decimal("0.30"),
        ),
        AmazonFeeSchedule(
            category="Home & Kitchen",
            referral_fee_percent=Decimal("15.00"),
            referral_fee_min=Decimal("0.30"),
        ),
        AmazonFeeSchedule(
            category="Sports & Outdoors",
            referral_fee_percent=Decimal("15.00"),
            referral_fee_min=Decimal("0.30"),
        ),
        AmazonFeeSchedule(
            category="Toys & Games",
            referral_fee_percent=Decimal("15.00"),
            referral_fee_min=Decimal("0.30"),
        ),
        AmazonFeeSchedule(
            category="Books",
            referral_fee_percent=Decimal("15.00"),
            referral_fee_min=Decimal("0"),
            closing_fee=Decimal("1.80"),
        ),
        AmazonFeeSchedule(
            category="Clothing & Accessories",
            referral_fee_percent=Decimal("17.00"),
            referral_fee_min=Decimal("0.30"),
        ),
        AmazonFeeSchedule(
            category="Health & Personal Care",
            referral_fee_percent=Decimal("15.00"),
            referral_fee_min=Decimal("0.30"),
        ),
        AmazonFeeSchedule(
            category="Beauty",
            referral_fee_percent=Decimal("15.00"),
            referral_fee_min=Decimal("0.30"),
        ),
        AmazonFeeSchedule(
            category="Automotive",
            referral_fee_percent=Decimal("15.00"),
            referral_fee_min=Decimal("0.30"),
        ),
        AmazonFeeSchedule(
            category="Pet Supplies",
            referral_fee_percent=Decimal("15.00"),
            referral_fee_min=Decimal("0.30"),
        ),
        AmazonFeeSchedule(
            category="Musical Instruments",
            referral_fee_percent=Decimal("15.00"),
            referral_fee_min=Decimal("0.30"),
        ),
        AmazonFeeSchedule(
            category="Office Products",
            referral_fee_percent=Decimal("15.00"),
            referral_fee_min=Decimal("0.30"),
        ),
        AmazonFeeSchedule(
            category="Video Games",
            referral_fee_percent=Decimal("15.00"),
            referral_fee_min=Decimal("0"),
        ),
        AmazonFeeSchedule(
            category="Grocery & Gourmet Food",
            referral_fee_percent=Decimal("15.00"),
            referral_fee_min=Decimal("0.30"),
        ),
    ],
)
