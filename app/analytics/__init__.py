"""Historical analytics module — append-only time-series collection and analysis.

Provides:
- Append-only snapshots for every data type (prices, BSR, sellers, inventory, fees, profit)
- Scheduled collection via AnalyticsScheduler
- Optimized time-series queries for millions of rows
- Summary statistics (min, max, avg, percentiles, trends)
- API endpoints for historical analysis
"""

from app.analytics.schemas import (
    AnalyticsSnapshot,
    CollectionStatus,
    FeeSnapshot,
    HistoricalSummary,
    InventorySnapshot,
    PriceSnapshot,
    ProfitSnapshot,
    SellerSnapshot,
    TimeSeriesPoint,
    TrendDirection,
)
from app.analytics.service import AnalyticsService
from app.analytics.scheduler import AnalyticsScheduler

__all__ = [
    "AnalyticsService",
    "AnalyticsScheduler",
    "AnalyticsSnapshot",
    "CollectionStatus",
    "FeeSnapshot",
    "HistoricalSummary",
    "InventorySnapshot",
    "PriceSnapshot",
    "ProfitSnapshot",
    "SellerSnapshot",
    "TimeSeriesPoint",
    "TrendDirection",
]
