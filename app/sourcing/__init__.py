"""Sourcing engine — evaluates products against configurable rules and ranks by opportunity.

Provides:
- Configurable rules: ROI, profit, sales, competition, Buy Box stability, price stability, inventory
- Weighted scoring with full transparency
- Opportunity Score (0-100), Confidence, Risk Level, and Reasoning
- Ranked product lists with sort/filter
- Documented scoring methodology
"""

from app.sourcing.engine import SourcingEngine, SourcingResult
from app.sourcing.models import (
    ConfidenceLevel,
    OpportunityScore,
    ProductEvaluation,
    RiskLevel,
    RuleResult,
    SourcingConfig,
    SourcingWeights,
)
from app.sourcing.rules import (
    BuyBoxStabilityRule,
    CompetitionRule,
    InventoryAvailabilityRule,
    MinimumProfitRule,
    MinimumRoiRule,
    MinimumSalesRule,
    PriceStabilityRule,
)

__all__ = [
    "SourcingEngine",
    "SourcingResult",
    "SourcingConfig",
    "SourcingRule",
    "SourcingWeights",
    "ProductEvaluation",
    "OpportunityScore",
    "ConfidenceLevel",
    "RiskLevel",
    "RuleResult",
    "MinimumRoiRule",
    "MinimumProfitRule",
    "MinimumSalesRule",
    "CompetitionRule",
    "BuyBoxStabilityRule",
    "PriceStabilityRule",
    "InventoryAvailabilityRule",
]
