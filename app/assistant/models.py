"""Data models for the AI assistant — requests, responses, and tool definitions.

Design decisions:
- Each question type has a dedicated request/response model.
- Retrieved context is included in the response for transparency.
- Tool calls are logged for audit and debugging.
- All responses include the data sources used.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

# ═══════════════════════════════════════════════════════════════
# Enums
# ═══════════════════════════════════════════════════════════════


class AssistantCapability(StrEnum):
    """Capabilities the assistant can perform."""

    WHY_PROFITABLE = "why_profitable"
    FIND_SIMILAR = "find_similar"
    PREDICT_NEXT_SALE = "predict_next_sale"
    ESTIMATE_FUTURE_ROI = "estimate_future_roi"
    SUMMARIZE_OPPORTUNITIES = "summarize_opportunities"
    FIND_REPLACEMENT_SUPPLIERS = "find_replacement_suppliers"
    BUY_MORE_INVENTORY = "buy_more_inventory"
    GENERATE_PURCHASE_ORDER = "generate_purchase_order"
    EXPLAIN_CALCULATION = "explain_calculation"
    GENERAL_QUERY = "general_query"


class DataSource(StrEnum):
    """Data sources used in the response."""

    AMAZON_PRICES = "amazon_prices"
    SUPPLIER_PRICES = "supplier_prices"
    SELLER_COUNTS = "seller_counts"
    SALES_ESTIMATES = "sales_estimates"
    HISTORICAL_FEES = "historical_fees"
    HISTORICAL_INVENTORY = "historical_inventory"
    PROFIT_CALCULATIONS = "profit_calculations"
    PRODUCT_DATABASE = "product_database"
    SUPPLIER_DATABASE = "supplier_database"
    AI_REASONING = "ai_reasoning"


# ═══════════════════════════════════════════════════════════════
# Request Models
# ═══════════════════════════════════════════════════════════════


class AssistantQuery(BaseModel):
    """A user query to the AI assistant."""

    question: str = Field(..., min_length=1, max_length=2000, description="The user's question")
    capability: AssistantCapability | None = Field(
        None, description="Auto-detected if not specified",
    )
    product_id: UUID | None = Field(None, description="Product UUID (if applicable)")
    asin: str | None = Field(None, description="Amazon ASIN (if applicable)")
    supplier_code: str | None = Field(None, description="Supplier code (if applicable)")
    supplier_sku: str | None = Field(None, description="Supplier SKU (if applicable)")
    quantity: int | None = Field(None, ge=1, description="Quantity (for purchase orders)")
    days: int = Field(default=90, ge=1, le=365, description="Analysis window in days")
    include_sources: bool = Field(
        default=True, description="Include retrieved data sources in response",
    )
    language: str | None = Field(
        default=None, description="Response language (e.g. 'en', 'zh-CN'). Defaults to the request's resolved language.",
    )


# ═══════════════════════════════════════════════════════════════
# Response Models
# ═══════════════════════════════════════════════════════════════


class RetrievedContext(BaseModel):
    """Data retrieved from the database for the response."""

    source: DataSource = Field(..., description="Data source")
    summary: str = Field(..., description="Human-readable summary of the data")
    data: dict[str, Any] = Field(
        default_factory=dict, description="Key data points",
    )
    record_count: int = Field(default=0, description="Number of records retrieved")


class AssistantResponse(BaseModel):
    """Response from the AI assistant."""

    answer: str = Field(..., description="The assistant's answer in natural language")
    capability: AssistantCapability = Field(
        ..., description="Capability used for this response",
    )
    confidence: str = Field(
        default="medium", description="Confidence: very_high, high, medium, low, very_low",
    )

    # Retrieved context (transparency)
    contexts: list[RetrievedContext] = Field(
        default_factory=list, description="Data sources used",
    )

    # LLM metadata
    model_used: str = Field(default="", description="LLM model used")
    provider_used: str = Field(default="", description="LLM provider used")
    prompt_version: str = Field(
        default="assistant_v1", description="Prompt template version",
    )
    latency_ms: float = Field(default=0, description="Total response time")

    # Structured data (for programmatic use)
    structured_data: dict[str, Any] | None = Field(
        default=None, description="Structured data extracted from the answer",
    )

    # Multilingual output (display labels are localized; enum values stay English)
    language: str = Field(default="en", description="Language the answer is written in")
    capability_label: str | None = Field(
        default=None, description="Localized display label for the capability",
    )
    confidence_label: str | None = Field(
        default=None, description="Localized display label for the confidence level",
    )


# ═══════════════════════════════════════════════════════════════
# Tool-Specific Models
# ═══════════════════════════════════════════════════════════════


class ProfitExplanation(BaseModel):
    """Explanation of why a product is profitable."""

    amazon_price: Decimal = Field(..., description="Current Amazon price")
    supplier_price: Decimal = Field(..., description="Supplier cost")
    total_fees: Decimal = Field(..., description="Total Amazon fees")
    net_profit: Decimal = Field(..., description="Net profit per unit")
    roi_percentage: Decimal = Field(..., description="ROI percentage")
    margin_percentage: Decimal = Field(..., description="Profit margin percentage")
    break_even_price: Decimal = Field(..., description="Break-even price")
    monthly_profit_estimate: Decimal = Field(
        ..., description="Estimated monthly profit at current sales rate",
    )
    key_factors: list[str] = Field(
        ..., description="Key factors driving profitability",
    )
    risks: list[str] = Field(
        default_factory=list, description="Risks to profitability",
    )


class SimilarProduct(BaseModel):
    """A similar product found by the assistant."""

    asin: str = Field(..., description="Amazon ASIN")
    title: str = Field(..., description="Product title")
    price: Decimal | None = Field(None, description="Current price")
    similarity_score: float = Field(..., ge=0, le=1, description="Similarity 0.0-1.0")
    match_reason: str = Field(..., description="Why this product is similar")


class SalesPrediction(BaseModel):
    """Prediction of future sales."""

    asin: str = Field(..., description="Amazon ASIN")
    current_monthly_sales: int = Field(..., description="Current monthly sales")
    predicted_next_month_sales: int = Field(..., description="Predicted next month sales")
    predicted_range_low: int = Field(..., description="Lower bound of prediction")
    predicted_range_high: int = Field(..., description="Upper bound of prediction")
    trend_direction: str = Field(..., description="up, down, flat, seasonal")
    confidence: str = Field(..., description="very_high, high, medium, low, very_low")
    reasoning: str = Field(..., description="Why this prediction was made")


class FutureROIEstimate(BaseModel):
    """Estimate of future ROI."""

    current_roi: Decimal = Field(..., description="Current ROI percentage")
    estimated_future_roi: Decimal = Field(..., description="Estimated future ROI")
    roi_range_low: Decimal = Field(..., description="Lower bound")
    roi_range_high: Decimal = Field(..., description="Upper bound")
    time_horizon_days: int = Field(..., description="Days into the future")
    key_assumptions: list[str] = Field(..., description="Assumptions made")
    risk_factors: list[str] = Field(..., description="Factors that could change ROI")


class OpportunitySummary(BaseModel):
    """Summary of today's opportunities."""

    total_products_evaluated: int = Field(..., description="Products evaluated")
    buy_recommendations: int = Field(..., description="BUY recommendations")
    watch_recommendations: int = Field(..., description="WATCH recommendations")
    top_opportunities: list[dict[str, Any]] = Field(
        ..., description="Top 5 opportunities",
    )
    total_potential_monthly_profit: Decimal | None = Field(
        None, description="Sum of potential monthly profit",
    )
    market_conditions: str = Field(..., description="Overall market assessment")


class ReplacementSupplier(BaseModel):
    """A replacement supplier recommendation."""

    supplier_code: str = Field(..., description="Supplier code")
    supplier_name: str = Field(..., description="Supplier name")
    price: Decimal = Field(..., description="Price per unit")
    moq: int = Field(..., description="Minimum order quantity")
    lead_time_days: int | None = Field(None, description="Lead time")
    savings_percentage: Decimal | None = Field(None, description="Savings vs current")
    confidence: str = Field(..., description="Recommendation confidence")
    reason: str = Field(..., description="Why this supplier is recommended")


class InventoryDecision(BaseModel):
    """Decision about whether to buy more inventory."""

    asin: str = Field(..., description="Amazon ASIN")
    current_stock: int = Field(..., description="Current units on hand")
    daily_sales_rate: float = Field(..., description="Units sold per day")
    days_of_stock_remaining: int = Field(..., description="Days until stockout")
    restock_recommendation: str = Field(
        ..., description="buy_now, buy_soon, wait, emergency",
    )
    recommended_order_quantity: int = Field(..., description="Units to order")
    estimated_days_to_restock: int = Field(..., description="Days to receive new stock")
    reasoning: str = Field(..., description="Why this recommendation was made")


class PurchaseOrder(BaseModel):
    """A generated purchase order."""

    po_number: str = Field(..., description="Purchase order number")
    supplier_code: str = Field(..., description="Supplier code")
    supplier_name: str = Field(..., description="Supplier name")
    items: list[dict[str, Any]] = Field(
        ..., description="Line items: asin, title, quantity, unit_price, total",
    )
    total_amount: Decimal = Field(..., description="Total order amount")
    currency: str = Field(default="USD", description="Currency")
    estimated_total_profit: Decimal | None = Field(
        None, description="Estimated profit from this order",
    )
    estimated_roi: Decimal | None = Field(None, description="Estimated ROI")
    notes: list[str] = Field(default_factory=list, description="Notes and warnings")
