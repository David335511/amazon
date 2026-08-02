"""Data models for the sourcing engine — rules, evaluations, scores, and configuration.

Design decisions:
- Every rule produces a RuleResult with score, passed/failed, and reasoning.
- The OpportunityScore aggregates all rule results with weights.
- Confidence and Risk are derived from rule outcomes, not independently set.
- All monetary values use Decimal for precision.
- Scores are always 0.0–1.0 internally, scaled to 0–100 for display.
"""

from __future__ import annotations

from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


# ═══════════════════════════════════════════════════════════════
# Enums
# ═══════════════════════════════════════════════════════════════


class ConfidenceLevel(str, Enum):
    """Confidence in the evaluation result."""

    VERY_HIGH = "very_high"       # 90%+ — abundant high-quality data
    HIGH = "high"                 # 75-90% — good data coverage
    MEDIUM = "medium"             # 50-75% — moderate data coverage
    LOW = "low"                   # 25-50% — sparse data
    VERY_LOW = "very_low"         # <25% — insufficient data


class RiskLevel(str, Enum):
    """Overall risk level of the opportunity."""

    VERY_LOW = "very_low"         # 0-15 — safe opportunity
    LOW = "low"                   # 15-30 — manageable risk
    MEDIUM = "medium"             # 30-50 — moderate risk, monitor
    HIGH = "high"                 # 50-70 — significant risk
    VERY_HIGH = "very_high"       # 70+ — high risk, avoid


class RuleSeverity(str, Enum):
    """How a rule failure affects the overall evaluation."""

    CRITICAL = "critical"         # Fails the entire evaluation
    MAJOR = "major"               # Significant score penalty
    MINOR = "minor"               # Small score penalty
    INFO = "info"                 # Informational only, no penalty


# ═══════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════


class SourcingWeights(BaseModel):
    """Weight configuration for each scoring dimension.

    Weights determine how much each rule contributes to the
    overall Opportunity Score. All weights are 0.0–1.0.
    """

    roi_weight: Decimal = Field(default=Decimal("0.25"), ge=0, le=1,
                                description="Weight for ROI rule")
    profit_weight: Decimal = Field(default=Decimal("0.20"), ge=0, le=1,
                                   description="Weight for minimum profit rule")
    sales_weight: Decimal = Field(default=Decimal("0.15"), ge=0, le=1,
                                  description="Weight for sales volume rule")
    competition_weight: Decimal = Field(default=Decimal("0.15"), ge=0, le=1,
                                       description="Weight for competition rule")
    buy_box_weight: Decimal = Field(default=Decimal("0.10"), ge=0, le=1,
                                    description="Weight for Buy Box stability rule")
    price_stability_weight: Decimal = Field(default=Decimal("0.08"), ge=0, le=1,
                                            description="Weight for price stability rule")
    inventory_weight: Decimal = Field(default=Decimal("0.07"), ge=0, le=1,
                                      description="Weight for inventory availability rule")

    @property
    def total(self) -> Decimal:
        """Sum of all weights — should equal 1.0."""
        return (
            self.roi_weight + self.profit_weight + self.sales_weight
            + self.competition_weight + self.buy_box_weight
            + self.price_stability_weight + self.inventory_weight
        )


class SourcingConfig(BaseModel):
    """Complete configuration for the sourcing engine.

    Defines the thresholds, weights, and severity for every rule.
    Can be customized per-user or per-category.
    """

    # ── Weights ────────────────────────────────────────────
    weights: SourcingWeights = Field(default_factory=SourcingWeights)

    # ── ROI Rule ───────────────────────────────────────────
    min_roi_percentage: Decimal = Field(
        default=Decimal("20.00"), ge=0,
        description="Minimum acceptable ROI percentage",
    )
    target_roi_percentage: Decimal = Field(
        default=Decimal("50.00"), ge=0,
        description="ROI at which this rule scores 1.0",
    )
    roi_severity: RuleSeverity = Field(
        default=RuleSeverity.CRITICAL,
        description="Severity if ROI is below minimum",
    )

    # ── Profit Rule ────────────────────────────────────────
    min_net_profit: Decimal = Field(
        default=Decimal("2.00"), ge=0,
        description="Minimum net profit per unit",
    )
    target_net_profit: Decimal = Field(
        default=Decimal("10.00"), ge=0,
        description="Profit at which this rule scores 1.0",
    )
    profit_severity: RuleSeverity = Field(
        default=RuleSeverity.CRITICAL,
        description="Severity if profit is below minimum",
    )

    # ── Sales Rule ────────────────────────────────────────
    min_monthly_sales: int = Field(
        default=300, ge=0,
        description="Minimum estimated monthly sales",
    )
    target_monthly_sales: int = Field(
        default=2000, ge=0,
        description="Sales at which this rule scores 1.0",
    )
    sales_severity: RuleSeverity = Field(
        default=RuleSeverity.MAJOR,
        description="Severity if sales are below minimum",
    )

    # ── Competition Rule ───────────────────────────────────
    max_new_sellers: int = Field(
        default=20, ge=0,
        description="Maximum acceptable new-condition sellers",
    )
    min_new_sellers: int = Field(
        default=1, ge=0,
        description="Minimum sellers (some competition validates demand)",
    )
    target_new_sellers: int = Field(
        default=5, ge=0,
        description="Seller count at which this rule scores 1.0",
    )
    max_fba_percentage: Decimal = Field(
        default=Decimal("70.00"), ge=0, le=100,
        description="Maximum FBA seller percentage before saturation",
    )
    competition_severity: RuleSeverity = Field(
        default=RuleSeverity.MAJOR,
        description="Severity if competition is too high",
    )

    # ── Buy Box Rule ──────────────────────────────────────
    min_buy_box_win_rate: Decimal = Field(
        default=Decimal("60.00"), ge=0, le=100,
        description="Minimum Buy Box win rate percentage",
    )
    buy_box_severity: RuleSeverity = Field(
        default=RuleSeverity.MINOR,
        description="Severity if Buy Box is unstable",
    )

    # ── Price Stability Rule ─────────────────────────────
    max_price_volatility: Decimal = Field(
        default=Decimal("15.00"), ge=0, le=100,
        description="Maximum coefficient of variation percentage",
    )
    price_stability_severity: RuleSeverity = Field(
        default=RuleSeverity.MINOR,
        description="Severity if prices are volatile",
    )

    # ── Inventory Rule ────────────────────────────────────
    min_days_of_stock: int = Field(
        default=30, ge=0,
        description="Minimum days of stock available",
    )
    inventory_severity: RuleSeverity = Field(
        default=RuleSeverity.MAJOR,
        description="Severity if inventory is insufficient",
    )

    # ── Overall Thresholds ────────────────────────────────
    minimum_opportunity_score: Decimal = Field(
        default=Decimal("40.00"), ge=0, le=100,
        description="Minimum overall score to be considered viable",
    )
    critical_rule_fail_threshold: int = Field(
        default=1, ge=0,
        description="Number of critical rule failures that auto-reject",
    )


# ═══════════════════════════════════════════════════════════════
# Rule Results
# ═══════════════════════════════════════════════════════════════


class RuleResult(BaseModel):
    """Result of evaluating a single sourcing rule."""

    rule_name: str = Field(..., description="Name of the rule (e.g., 'minimum_roi')")
    display_name: str = Field(..., description="Human-readable name (e.g., 'Minimum ROI')")
    severity: RuleSeverity = Field(..., description="Severity if this rule fails")
    weight: Decimal = Field(..., ge=0, le=1, description="Weight in overall score")

    # Score
    score: Decimal = Field(..., ge=0, le=1, description="Normalized score 0.0-1.0")
    passed: bool = Field(..., description="Did this rule pass its minimum threshold?")
    is_critical_failure: bool = Field(
        default=False,
        description="True if severity=CRITICAL and passed=False",
    )

    # Values
    actual_value: str | None = Field(
        None, description="The actual value observed (formatted for display)",
    )
    threshold_value: str | None = Field(
        None, description="The minimum threshold (formatted for display)",
    )
    target_value: str | None = Field(
        None, description="The target for a perfect score (formatted for display)",
    )

    # Reasoning
    summary: str = Field(..., description="One-line summary of the evaluation")
    details: str | None = Field(None, description="Detailed explanation")
    data_quality: str | None = Field(
        None, description="Data quality note (e.g., 'estimated from 90 days of data')",
    )


# ═══════════════════════════════════════════════════════════════
# Evaluation Output
# ═══════════════════════════════════════════════════════════════


class OpportunityScore(BaseModel):
    """Overall opportunity score with breakdown."""

    total_score: Decimal = Field(
        ..., ge=0, le=100,
        description="Overall opportunity score 0-100",
    )
    weighted_score: Decimal = Field(
        ..., ge=0, le=1,
        description="Raw weighted average of all rule scores",
    )
    rule_results: list[RuleResult] = Field(
        ..., description="Individual rule results",
    )
    critical_failures: int = Field(
        default=0, description="Number of critical rule failures",
    )
    is_viable: bool = Field(
        ..., description="Does this product meet minimum criteria?",
    )


class ProductEvaluation(BaseModel):
    """Complete evaluation of a single product."""

    # Product identity
    product_id: UUID = Field(..., description="Database product UUID")
    asin: str = Field(..., description="Amazon ASIN")
    title: str = Field(..., description="Product title")

    # Scores
    opportunity_score: OpportunityScore = Field(
        ..., description="Opportunity score breakdown",
    )
    confidence: ConfidenceLevel = Field(
        ..., description="Confidence in the evaluation",
    )
    risk_level: RiskLevel = Field(
        ..., description="Overall risk level",
    )

    # Summary
    summary: str = Field(
        ..., description="One-paragraph summary of the evaluation",
    )
    strengths: list[str] = Field(
        default_factory=list, description="Key strengths",
    )
    weaknesses: list[str] = Field(
        default_factory=list, description="Key weaknesses",
    )
    recommendations: list[str] = Field(
        default_factory=list, description="Actionable recommendations",
    )

    # Data quality
    data_points_used: int = Field(
        default=0, description="Total data points used in evaluation",
    )
    data_quality_note: str | None = Field(
        None, description="Note about data quality or gaps",
    )

    # AI-powered recommendation (optional — requires LLM provider)
    ai_recommendation: Any = Field(
        default=None, description="AI-generated recommendation with natural language analysis",
    )


class SourcingResult(BaseModel):
    """Result of a sourcing evaluation — single or batch."""

    evaluations: list[ProductEvaluation] = Field(
        ..., description="Product evaluations sorted by score descending",
    )
    total_evaluated: int = Field(..., description="Total products evaluated")
    viable_count: int = Field(default=0, description="Products meeting minimum criteria")
    non_viable_count: int = Field(default=0, description="Products below minimum criteria")
    config: SourcingConfig = Field(..., description="Configuration used for evaluation")
    methodology_version: str = Field(
        default="1.0.0", description="Scoring methodology version",
    )
