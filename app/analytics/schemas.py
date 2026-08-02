"""Data models for the historical analytics module.

Design decisions:
- Snapshot models capture the full state at a point in time.
- TimeSeriesPoint is the universal container for chart data.
- Summary statistics include percentiles for distribution analysis.
- All monetary values use Decimal for precision.
- Timestamps are timezone-aware.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field


# ═══════════════════════════════════════════════════════════════
# Enums
# ═══════════════════════════════════════════════════════════════


class TrendDirection(str, Enum):
    """Direction of a trend over a time window."""

    UP = "up"
    DOWN = "down"
    FLAT = "flat"
    VOLATILE = "volatile"
    INSUFFICIENT_DATA = "insufficient_data"


class CollectionStatus(str, Enum):
    """Status of a data collection operation."""

    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    SKIPPED = "skipped"


# ═══════════════════════════════════════════════════════════════
# Time-Series Primitives
# ═══════════════════════════════════════════════════════════════


class TimeSeriesPoint(BaseModel):
    """A single data point in a time series.

    Used for chart data, CSV export, and trend analysis.
    """

    timestamp: datetime = Field(..., description="Observation timestamp")
    value: Decimal = Field(..., description="Numeric value at this point")
    label: str | None = Field(None, description="Optional label for this point")
    metadata: dict[str, str | float | int | None] = Field(
        default_factory=dict,
        description="Additional context (e.g., condition, seller count)",
    )


# ═══════════════════════════════════════════════════════════════
# Snapshot Models (one per data type)
# ═══════════════════════════════════════════════════════════════


class PriceSnapshot(BaseModel):
    """Snapshot of Amazon and supplier prices at a point in time."""

    product_id: UUID = Field(..., description="Product UUID")
    asin: str = Field(..., description="Amazon ASIN")
    timestamp: datetime = Field(..., description="When this snapshot was taken")

    # Amazon prices
    amazon_price: Decimal | None = Field(None, description="Current Amazon listing price")
    buy_box_price: Decimal | None = Field(None, description="Current Buy Box price")
    amazon_currency: str = Field(default="USD", description="Amazon price currency")
    is_fba: bool = Field(default=False, description="Fulfilled by Amazon")
    is_buy_box_winner: bool = Field(default=False, description="Amazon holds the Buy Box")

    # Supplier prices
    lowest_supplier_price: Decimal | None = Field(
        None, description="Lowest price across all suppliers",
    )
    average_supplier_price: Decimal | None = Field(
        None, description="Average price across all suppliers",
    )
    supplier_count: int = Field(default=0, description="Number of suppliers with pricing")
    supplier_currency: str = Field(default="USD", description="Supplier price currency")

    # Spread
    price_spread: Decimal | None = Field(
        None, description="amazon_price - lowest_supplier_price",
    )
    price_spread_percentage: Decimal | None = Field(
        None, description="(price_spread / amazon_price) * 100",
    )


class SellerSnapshot(BaseModel):
    """Snapshot of seller competition at a point in time."""

    product_id: UUID = Field(..., description="Product UUID")
    asin: str = Field(..., description="Amazon ASIN")
    timestamp: datetime = Field(..., description="When this snapshot was taken")

    new_seller_count: int = Field(default=0, description="New-condition sellers")
    used_seller_count: int = Field(default=0, description="Used-condition sellers")
    fba_seller_count: int = Field(default=0, description="FBA sellers")
    total_offer_count: int = Field(default=0, description="Total offers across all conditions")


class InventorySnapshot(BaseModel):
    """Snapshot of inventory levels at a point in time."""

    product_id: UUID = Field(..., description="Product UUID")
    asin: str = Field(..., description="Amazon ASIN")
    timestamp: datetime = Field(..., description="When this snapshot was taken")

    quantity_on_hand: int = Field(default=0, description="Physical stock")
    quantity_reserved: int = Field(default=0, description="Reserved for orders")
    quantity_inbound: int = Field(default=0, description="Inbound from suppliers")
    quantity_available: int = Field(default=0, description="Available (on_hand - reserved)")
    warehouse_location: str | None = Field(None, description="Warehouse location")
    days_of_stock: Decimal | None = Field(
        None, description="Estimated days until stockout based on avg daily sales",
    )


class FeeSnapshot(BaseModel):
    """Snapshot of Amazon fees at a point in time."""

    product_id: UUID = Field(..., description="Product UUID")
    asin: str = Field(..., description="Amazon ASIN")
    timestamp: datetime = Field(..., description="When this snapshot was taken")

    referral_fee: Decimal = Field(default=0, description="Referral fee amount")
    fulfillment_fee: Decimal = Field(default=0, description="FBA fulfillment fee")
    storage_fee: Decimal = Field(default=0, description="Monthly storage fee")
    closing_fee: Decimal = Field(default=0, description="Closing fee (media)")
    other_fees: Decimal = Field(default=0, description="Other Amazon fees")
    total_fees: Decimal = Field(default=0, description="Sum of all fees")
    fee_percentage: Decimal | None = Field(
        None, description="Total fees as percentage of amazon_price",
    )


class ProfitSnapshot(BaseModel):
    """Snapshot of profit calculations at a point in time."""

    product_id: UUID = Field(..., description="Product UUID")
    asin: str = Field(..., description="Amazon ASIN")
    timestamp: datetime = Field(..., description="When this snapshot was taken")

    unit_cost: Decimal = Field(default=0, description="Cost per unit from supplier")
    amazon_price: Decimal = Field(default=0, description="Selling price on Amazon")
    total_cost: Decimal = Field(default=0, description="All costs including fees")
    gross_profit: Decimal = Field(default=0, description="amazon_price - unit_cost")
    net_profit: Decimal = Field(default=0, description="amazon_price - total_cost")
    margin_percentage: Decimal = Field(default=0, description="(net_profit / amazon_price) * 100")
    roi_percentage: Decimal = Field(default=0, description="(net_profit / total_cost) * 100")
    is_profitable: bool = Field(default=False, description="net_profit > 0")


class AnalyticsSnapshot(BaseModel):
    """Complete snapshot of all analytics data for a product at a point in time.

    This is the composite model returned by the collection service.
    """

    product_id: UUID = Field(..., description="Product UUID")
    asin: str = Field(..., description="Amazon ASIN")
    timestamp: datetime = Field(..., description="When this snapshot was taken")

    prices: PriceSnapshot | None = Field(None, description="Price data")
    sellers: SellerSnapshot | None = Field(None, description="Seller data")
    inventory: InventorySnapshot | None = Field(None, description="Inventory data")
    fees: FeeSnapshot | None = Field(None, description="Fee data")
    profit: ProfitSnapshot | None = Field(None, description="Profit data")

    status: CollectionStatus = Field(
        default=CollectionStatus.SUCCESS,
        description="Overall collection status",
    )
    errors: list[str] = Field(default_factory=list, description="Per-component errors")


# ═══════════════════════════════════════════════════════════════
# Summary Statistics
# ═══════════════════════════════════════════════════════════════


class HistoricalSummary(BaseModel):
    """Summary statistics for a single metric over a time window."""

    product_id: UUID = Field(..., description="Product UUID")
    asin: str = Field(..., description="Amazon ASIN")
    metric: str = Field(..., description="Metric name (e.g., 'amazon_price', 'net_profit')")
    unit: str = Field(default="", description="Unit of measurement")

    # Time window
    window_start: datetime = Field(..., description="Start of analysis window")
    window_end: datetime = Field(..., description="End of analysis window")
    data_point_count: int = Field(default=0, description="Number of observations")

    # Central tendency
    current_value: Decimal | None = Field(None, description="Most recent value")
    mean: Decimal | None = Field(None, description="Arithmetic mean")
    median: Decimal | None = Field(None, description="50th percentile")
    mode: Decimal | None = Field(None, description="Most frequent value")

    # Dispersion
    min: Decimal | None = Field(None, description="Minimum value")
    max: Decimal | None = Field(None, description="Maximum value")
    range: Decimal | None = Field(None, description="max - min")
    std_dev: Decimal | None = Field(None, description="Population standard deviation")
    variance: Decimal | None = Field(None, description="Population variance")

    # Percentiles
    p10: Decimal | None = Field(None, description="10th percentile")
    p25: Decimal | None = Field(None, description="25th percentile (Q1)")
    p75: Decimal | None = Field(None, description="75th percentile (Q3)")
    p90: Decimal | None = Field(None, description="90th percentile")
    p95: Decimal | None = Field(None, description="95th percentile")
    p99: Decimal | None = Field(None, description="99th percentile")

    # Trend
    trend: TrendDirection = Field(
        default=TrendDirection.INSUFFICIENT_DATA,
        description="Trend direction over the window",
    )
    trend_change: Decimal | None = Field(
        None, description="Absolute change: current - first",
    )
    trend_percentage: Decimal | None = Field(
        None, description="Percentage change over the window",
    )
    slope: Decimal | None = Field(
        None, description="Linear regression slope (change per day)",
    )

    # Volatility
    coefficient_of_variation: Decimal | None = Field(
        None, description="std_dev / mean — relative volatility",
    )
    min_to_max_ratio: Decimal | None = Field(
        None, description="min / max — stability indicator",
    )


class MultiMetricSummary(BaseModel):
    """Summary statistics for multiple metrics across a time window."""

    product_id: UUID = Field(..., description="Product UUID")
    asin: str = Field(..., description="Amazon ASIN")
    window_start: datetime = Field(..., description="Start of analysis window")
    window_end: datetime = Field(..., description="End of analysis window")
    metrics: dict[str, HistoricalSummary] = Field(
        default_factory=dict,
        description="Map of metric name to summary statistics",
    )


# ═══════════════════════════════════════════════════════════════
# API Response Models
# ═══════════════════════════════════════════════════════════════


class TimeSeriesResponse(BaseModel):
    """Paginated time-series data for a single metric."""

    product_id: UUID = Field(..., description="Product UUID")
    asin: str = Field(..., description="Amazon ASIN")
    metric: str = Field(..., description="Metric name")
    unit: str = Field(default="", description="Unit of measurement")
    data_points: list[TimeSeriesPoint] = Field(
        default_factory=list, description="Time-series data points",
    )
    total_points: int = Field(default=0, description="Total matching points")
    summary: HistoricalSummary | None = Field(None, description="Summary statistics")


class CollectionResponse(BaseModel):
    """Response from a data collection operation."""

    product_id: UUID = Field(..., description="Product UUID")
    asin: str = Field(..., description="Amazon ASIN")
    status: CollectionStatus = Field(..., description="Collection status")
    components: dict[str, CollectionStatus] = Field(
        default_factory=dict,
        description="Per-component status",
    )
    errors: list[str] = Field(default_factory=list, description="Error messages")
    snapshot_id: UUID | None = Field(None, description="HistoricalInventory row ID if collected")


class BatchCollectionResponse(BaseModel):
    """Response from a batch collection operation."""

    total_products: int = Field(..., description="Products requested")
    succeeded: int = Field(default=0, description="Fully successful")
    partial: int = Field(default=0, description="Partial success")
    failed: int = Field(default=0, description="Fully failed")
    results: list[CollectionResponse] = Field(
        default_factory=list, description="Per-product results",
    )
    total_duration_ms: float = Field(default=0, description="Total processing time")
