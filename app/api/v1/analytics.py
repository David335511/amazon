"""Historical analytics API routes — time-series data, summary statistics, and collection.

Design decisions:
- Thin route handlers that delegate to the AnalyticsService.
- Keyset pagination for stable ordering at scale (no OFFSET).
- Consistent error responses with structured JSON.
- All monetary values returned as strings for precision.
- Timestamps in ISO 8601 format with timezone.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.repository import AnalyticsRepository
from app.analytics.schemas import (
    BatchCollectionResponse,
    CollectionResponse,
    HistoricalSummary,
    MultiMetricSummary,
    TimeSeriesResponse,
    TimeSeriesPoint,
)
from app.analytics.service import AnalyticsService
from app.core.database import get_db
from app.core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/analytics", tags=["analytics"])


# ── Dependency ──────────────────────────────────────────────


async def get_analytics_service(
    db: AsyncSession = Depends(get_db),
) -> AnalyticsService:
    """Create an AnalyticsService with all dependencies."""
    repository = AnalyticsRepository(db)
    return AnalyticsService(repository=repository)


# ═══════════════════════════════════════════════════════════════
# Time-Series Endpoints
# ═══════════════════════════════════════════════════════════════


@router.get(
    "/products/{product_id}/time-series/{metric}",
    response_model=TimeSeriesResponse,
    summary="Get time-series data for a metric",
    description=(
        "Returns historical time-series data for a specific metric. "
        "Supports keyset pagination via the `cursor` parameter. "
        "Available metrics: amazon_price, buy_box_price, supplier_price, "
        "bsr, new_seller_count, fba_seller_count, quantity_on_hand, "
        "quantity_available, total_fees, referral_fee, fulfillment_fee, "
        "net_profit, gross_profit, margin_percentage, roi_percentage, "
        "estimated_monthly_sales"
    ),
)
async def get_time_series(
    product_id: UUID,
    metric: str,
    days: int = Query(
        default=90, ge=1, le=1825,
        description="Days of history to return (max 5 years)",
    ),
    limit: int = Query(
        default=1000, ge=1, le=10000,
        description="Maximum data points to return",
    ),
    cursor: str | None = Query(
        default=None,
        description="Keyset cursor (ISO 8601 timestamp) for pagination",
    ),
    include_summary: bool = Query(
        default=True,
        description="Include summary statistics with the response",
    ),
    service: AnalyticsService = Depends(get_analytics_service),
) -> TimeSeriesResponse:
    """Get time-series data for a product metric."""
    # Validate metric
    valid_metrics = {
        "amazon_price", "buy_box_price", "supplier_price",
        "bsr", "new_seller_count", "fba_seller_count",
        "quantity_on_hand", "quantity_available",
        "total_fees", "referral_fee", "fulfillment_fee",
        "net_profit", "gross_profit", "margin_percentage", "roi_percentage",
        "estimated_monthly_sales",
    }
    if metric not in valid_metrics:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Invalid metric '{metric}'. Valid: {', '.join(sorted(valid_metrics))}",
        )

    # Parse cursor
    cursor_dt: datetime | None = None
    if cursor:
        try:
            cursor_dt = datetime.fromisoformat(cursor)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Invalid cursor format. Use ISO 8601: {exc}",
            ) from exc

    # Get product for ASIN
    product = await service._repo.get(product_id)
    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product with ID '{product_id}' not found",
        )

    # Compute time window
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    since = (now - timedelta(days=days)).replace(
        hour=0, minute=0, second=0, microsecond=0,
    )

    # Get data
    points, total = await service.get_time_series(
        product_id, metric,
        since=since,
        limit=limit,
        cursor=cursor_dt,
    )

    # Get summary
    summary = None
    if include_summary:
        summary = await service.compute_summary(product_id, metric, days=days)

    return TimeSeriesResponse(
        product_id=product_id,
        asin=product.asin,
        metric=metric,
        data_points=points,
        total_points=total,
        summary=summary,
    )


@router.get(
    "/products/{product_id}/summary",
    response_model=MultiMetricSummary,
    summary="Get summary statistics for multiple metrics",
    description=(
        "Returns summary statistics (min, max, mean, median, percentiles, "
        "trend) for multiple metrics in a single request."
    ),
)
async def get_multi_metric_summary(
    product_id: UUID,
    metrics: str = Query(
        default="amazon_price,net_profit,margin_percentage,bsr",
        description="Comma-separated list of metrics",
    ),
    days: int = Query(
        default=90, ge=1, le=1825,
        description="Analysis window in days",
    ),
    service: AnalyticsService = Depends(get_analytics_service),
) -> MultiMetricSummary:
    """Get summary statistics for multiple metrics."""
    metric_list = [m.strip() for m in metrics.split(",") if m.strip()]
    if not metric_list:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="At least one metric is required",
        )

    return await service.compute_multi_metric_summary(
        product_id, metric_list, days=days,
    )


@router.get(
    "/products/{product_id}/summary/{metric}",
    response_model=HistoricalSummary,
    summary="Get summary statistics for a single metric",
    description=(
        "Returns detailed summary statistics for a single metric including "
        "central tendency, dispersion, percentiles, and trend analysis."
    ),
)
async def get_single_metric_summary(
    product_id: UUID,
    metric: str,
    days: int = Query(
        default=90, ge=1, le=1825,
        description="Analysis window in days",
    ),
    service: AnalyticsService = Depends(get_analytics_service),
) -> HistoricalSummary:
    """Get summary statistics for a single metric."""
    summary = await service.compute_summary(product_id, metric, days=days)
    if summary is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product with ID '{product_id}' not found or no data for metric '{metric}'",
        )
    return summary


# ═══════════════════════════════════════════════════════════════
# Collection Endpoints
# ═══════════════════════════════════════════════════════════════


@router.post(
    "/products/{product_id}/collect",
    response_model=CollectionResponse,
    summary="Collect analytics snapshot",
    description=(
        "Trigger an immediate analytics snapshot collection for a product. "
        "Collects prices, sellers, inventory, fees, and profit data."
    ),
)
async def collect_snapshot(
    product_id: UUID,
    service: AnalyticsService = Depends(get_analytics_service),
) -> CollectionResponse:
    """Collect an analytics snapshot for a product."""
    product = await service._repo.get(product_id)
    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product with ID '{product_id}' not found",
        )

    snapshot = await service.collect_snapshot(product_id)

    return CollectionResponse(
        product_id=product_id,
        asin=product.asin,
        status=snapshot.status,
        components={
            k: v.value for k, v in snapshot.components.items()
        } if hasattr(snapshot, 'components') else {},
        errors=snapshot.errors,
    )


@router.post(
    "/collect/batch",
    response_model=BatchCollectionResponse,
    summary="Batch collect analytics snapshots",
    description=(
        "Collect analytics snapshots for multiple products. "
        "Accepts a list of product IDs or collects for all active products."
    ),
)
async def collect_batch(
    product_ids: list[UUID] | None = Query(
        default=None,
        description="Specific product IDs to collect. If empty, collects for all active products.",
    ),
    limit: int = Query(
        default=50, ge=1, le=500,
        description="Max products to process (only used when product_ids is empty)",
    ),
    offset: int = Query(
        default=0, ge=0,
        description="Pagination offset (only used when product_ids is empty)",
    ),
    service: AnalyticsService = Depends(get_analytics_service),
) -> BatchCollectionResponse:
    """Collect analytics snapshots for multiple products."""
    return await service.collect_batch(
        product_ids=product_ids,
        limit=limit,
        offset=offset,
    )


# ═══════════════════════════════════════════════════════════════
# Data Discovery Endpoints
# ═══════════════════════════════════════════════════════════════


@router.get(
    "/products/{product_id}/coverage",
    summary="Get data coverage information",
    description=(
        "Returns the date range and data point count for each "
        "analytics table for a product."
    ),
)
async def get_data_coverage(
    product_id: UUID,
    service: AnalyticsService = Depends(get_analytics_service),
) -> dict[str, Any]:
    """Get data coverage information for a product."""
    product = await service._repo.get(product_id)
    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product with ID '{product_id}' not found",
        )

    tables = [
        "amazon_prices",
        "product_prices",
        "historical_inventory",
        "seller_counts",
        "historical_fees",
        "profit_calculations",
        "sales_estimates",
        "reviews",
    ]

    coverage: dict[str, Any] = {}
    for table in tables:
        count = await service._repo.count_data_points(product_id, table)
        oldest = await service._repo.get_oldest_data_point(product_id, table)
        newest = await service._repo.get_newest_data_point(product_id, table)
        coverage[table] = {
            "count": count,
            "oldest": oldest.isoformat() if oldest else None,
            "newest": newest.isoformat() if newest else None,
        }

    return {
        "product_id": str(product_id),
        "asin": product.asin,
        "tables": coverage,
    }


@router.get(
    "/metrics",
    summary="List available metrics",
    description="Returns the list of all available metrics for time-series analysis.",
)
async def list_metrics() -> dict[str, list[dict[str, str]]]:
    """List all available metrics with descriptions."""
    metrics = [
        {"name": "amazon_price", "description": "Amazon listing price", "table": "amazon_prices"},
        {"name": "buy_box_price", "description": "Buy Box price", "table": "amazon_prices"},
        {"name": "supplier_price", "description": "Supplier cost price", "table": "product_prices"},
        {"name": "bsr", "description": "Best Sellers Rank", "table": "sales_estimates"},
        {"name": "new_seller_count", "description": "New-condition sellers", "table": "seller_counts"},
        {"name": "fba_seller_count", "description": "FBA sellers", "table": "seller_counts"},
        {"name": "quantity_on_hand", "description": "Physical inventory on hand", "table": "historical_inventory"},
        {"name": "quantity_available", "description": "Available inventory (on_hand - reserved)", "table": "historical_inventory"},
        {"name": "total_fees", "description": "Total Amazon fees", "table": "historical_fees"},
        {"name": "referral_fee", "description": "Amazon referral fee", "table": "historical_fees"},
        {"name": "fulfillment_fee", "description": "FBA fulfillment fee", "table": "historical_fees"},
        {"name": "net_profit", "description": "Net profit per unit", "table": "profit_calculations"},
        {"name": "gross_profit", "description": "Gross profit per unit", "table": "profit_calculations"},
        {"name": "margin_percentage", "description": "Net profit margin percentage", "table": "profit_calculations"},
        {"name": "roi_percentage", "description": "Return on investment percentage", "table": "profit_calculations"},
        {"name": "estimated_monthly_sales", "description": "Estimated monthly sales volume", "table": "sales_estimates"},
    ]
    return {"metrics": metrics}
