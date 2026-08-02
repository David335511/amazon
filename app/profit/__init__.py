"""Profit engine for Amazon product sourcing.

Calculates profit, ROI, margin, break-even price, and return on capital
from Amazon price, supplier price, shipping, fees, taxes, and discounts.

All fee rates are configurable via ProfitConfig. Every calculation is
fully transparent — each fee component is itemized in the output.
"""

from app.profit.config import ProfitConfig, FeeConfig, AmazonFeeSchedule
from app.profit.engine import ProfitEngine
from app.profit.models import (
    ProfitInput,
    ProfitOutput,
    FeeComponent,
    FeeCategory,
)

__all__ = [
    "ProfitEngine",
    "ProfitResult",
    "FeeBreakdown",
    "ProfitInput",
    "ProfitOutput",
    "FeeComponent",
    "FeeCategory",
    "ProfitConfig",
    "FeeConfig",
    "AmazonFeeSchedule",
]
