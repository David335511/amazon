"""Analytics service — collection orchestration, summary statistics, and trend analysis.

Design decisions:
- Collection is component-based: each data type (prices, sellers, inventory, fees, profit)
  is collected independently. One component failure doesn't block others.
- Summary statistics use SQL aggregation for O(n) computation at the database level.
- Trend analysis uses linear regression (REGR_SLOPE) for direction detection.
- All timestamps are UTC. Timezone conversion happens at the presentation layer.
- The service is stateless — all state is in the database.
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.analytics.repository import AnalyticsRepository
from app.analytics.schemas import (
    AnalyticsSnapshot,
    BatchCollectionResponse,
    CollectionResponse,
    CollectionStatus,
    FeeSnapshot,
    HistoricalSummary,
    InventorySnapshot,
    MultiMetricSummary,
    PriceSnapshot,
    ProfitSnapshot,
    SellerSnapshot,
    TimeSeriesPoint,
    TrendDirection,
)
from app.core.logging import get_logger
from app.domain.models.product import Product
from app.domain.models.sourcing import (
    AmazonPrice,
    HistoricalFee,
    HistoricalInventory,
    ProductPrice,
    ProfitCalculation,
    SalesEstimate,
    SellerCount,
)
from app.profit.config import DEFAULT_PROFIT_CONFIG, ProfitConfig
from app.profit.engine import ProfitEngine
from app.profit.models import ProfitInput

logger = get_logger(__name__)

# Default time windows for summary statistics
DEFAULT_WINDOW_DAYS = 90
TREND_MIN_POINTS = 3


class AnalyticsService:
    """Orchestrates historical data collection and analysis.

    Usage:
        service = AnalyticsService(repository)
        snapshot = await service.collect_snapshot(product_id)
        summary = await service.compute_summary(product_id, "amazon_price")
    """

    def __init__(
        self,
        repository: AnalyticsRepository,
        profit_config: ProfitConfig | None = None,
    ) -> None:
        self._repo = repository
        self._profit_engine = ProfitEngine(config=profit_config or DEFAULT_PROFIT_CONFIG)

    # ═══════════════════════════════════════════════════════════
    # Snapshot Collection
    # ═══════════════════════════════════════════════════════════

    async def collect_snapshot(
        self,
        product_id: UUID,
    ) -> AnalyticsSnapshot:
        """Collect a complete analytics snapshot for a product.

        Gathers all data types (prices, sellers, inventory, fees, profit)
        and stores them as append-only rows. Each component is collected
        independently — failures are isolated.

        Args:
            product_id: Product UUID.

        Returns:
            Complete analytics snapshot with per-component status.
        """
        product = await self._repo.get(product_id)
        if product is None:
            return AnalyticsSnapshot(
                product_id=product_id,
                asin="unknown",
                timestamp=datetime.now(timezone.utc),
                status=CollectionStatus.FAILED,
                errors=[f"Product {product_id} not found"],
            )

        now = datetime.now(timezone.utc)
        components: dict[str, CollectionStatus] = {}
        errors: list[str] = []

        # Collect each component independently
        price_snapshot = await self._collect_prices(product, now, components, errors)
        seller_snapshot = await self._collect_sellers(product, now, components, errors)
        inventory_snapshot = await self._collect_inventory(product, now, components, errors)
        fee_snapshot = await self._collect_fees(product, now, components, errors)
        profit_snapshot = await self._collect_profit(
            product, now, price_snapshot, fee_snapshot, components, errors,
        )

        # Determine overall status
        status_counts = list(components.values())
        if all(s == CollectionStatus.SUCCESS for s in status_counts):
            overall = CollectionStatus.SUCCESS
        elif all(s == CollectionStatus.FAILED for s in status_counts):
            overall = CollectionStatus.FAILED
        else:
            overall = CollectionStatus.PARTIAL

        return AnalyticsSnapshot(
            product_id=product.id,
            asin=product.asin,
            timestamp=now,
            prices=price_snapshot,
            sellers=seller_snapshot,
            inventory=inventory_snapshot,
            fees=fee_snapshot,
            profit=profit_snapshot,
            status=overall,
            errors=errors,
        )

    async def _collect_prices(
        self,
        product: Product,
        now: datetime,
        components: dict[str, CollectionStatus],
        errors: list[str],
    ) -> PriceSnapshot | None:
        """Collect Amazon and supplier price snapshots."""
        try:
            # Latest Amazon price
            latest_amazon = await self._repo.get_latest_amazon_price(
                product.id, is_buy_box=False,
            )
            latest_buy_box = await self._repo.get_latest_amazon_price(
                product.id, is_buy_box=True,
            )

            # Latest supplier prices
            supplier_prices = await self._repo.get_latest_supplier_prices(product.id)

            # Compute supplier stats
            supplier_count = len(supplier_prices)
            if supplier_prices:
                prices_list = [sp.price for sp in supplier_prices]
                lowest = min(prices_list)
                avg = sum(prices_list) / len(prices_list)
            else:
                lowest = None
                avg = None

            # Price spread
            amazon_price = latest_amazon.price if latest_amazon else product.price
            spread = (amazon_price - lowest) if (amazon_price and lowest) else None
            spread_pct = (
                (spread / amazon_price * 100)
                if (spread and amazon_price and amazon_price > 0)
                else None
            )

            components["prices"] = CollectionStatus.SUCCESS
            return PriceSnapshot(
                product_id=product.id,
                asin=product.asin,
                timestamp=now,
                amazon_price=amazon_price,
                buy_box_price=latest_buy_box.price if latest_buy_box else None,
                is_fba=latest_amazon.is_amazon_fulfilled if latest_amazon else False,
                is_buy_box_winner=latest_buy_box.is_buy_box if latest_buy_box else False,
                lowest_supplier_price=lowest,
                average_supplier_price=round(avg, 2) if avg else None,
                supplier_count=supplier_count,
                price_spread=round(spread, 2) if spread else None,
                price_spread_percentage=round(spread_pct, 2) if spread_pct else None,
            )
        except Exception as exc:
            logger.warning("Price collection failed for %s: %s", product.asin, exc)
            components["prices"] = CollectionStatus.FAILED
            errors.append(f"prices: {exc}")
            return None

    async def _collect_sellers(
        self,
        product: Product,
        now: datetime,
        components: dict[str, CollectionStatus],
        errors: list[str],
    ) -> SellerSnapshot | None:
        """Collect seller competition snapshot."""
        try:
            latest = await self._repo.get_latest_seller_count(product.id)
            components["sellers"] = CollectionStatus.SUCCESS
            return SellerSnapshot(
                product_id=product.id,
                asin=product.asin,
                timestamp=now,
                new_seller_count=latest.new_seller_count if latest else 0,
                used_seller_count=latest.used_seller_count if latest else 0,
                fba_seller_count=latest.fba_seller_count if latest else 0,
                total_offer_count=(latest.new_seller_count + latest.used_seller_count)
                if latest else 0,
            )
        except Exception as exc:
            logger.warning("Seller collection failed for %s: %s", product.asin, exc)
            components["sellers"] = CollectionStatus.FAILED
            errors.append(f"sellers: {exc}")
            return None

    async def _collect_inventory(
        self,
        product: Product,
        now: datetime,
        components: dict[str, CollectionStatus],
        errors: list[str],
    ) -> InventorySnapshot | None:
        """Collect inventory snapshot and store as historical row."""
        try:
            # Get current inventory from the mutable table
            from app.domain.models.sourcing import Inventory as CurrentInventory
            stmt = (
                select(CurrentInventory)
                .where(CurrentInventory.product_id == product.id)
            )
            from sqlalchemy import select as sa_select
            result = await self._repo._session.execute(
                sa_select(CurrentInventory).where(
                    CurrentInventory.product_id == product.id,
                ),
            )
            current = result.scalar_one_or_none()

            if current is None:
                components["inventory"] = CollectionStatus.SKIPPED
                return InventorySnapshot(
                    product_id=product.id,
                    asin=product.asin,
                    timestamp=now,
                    quantity_on_hand=0,
                    quantity_reserved=0,
                    quantity_inbound=0,
                    quantity_available=0,
                )

            available = current.quantity_on_hand - current.quantity_reserved

            # Get daily sales rate for days-of-stock calculation
            latest_sales = await self._repo.get_latest_sales_estimate(product.id)
            daily_sales = (
                latest_sales.estimated_daily_sales
                if latest_sales and latest_sales.estimated_daily_sales > 0
                else None
            )
            days_of_stock = (
                round(Decimal(str(available)) / daily_sales, 1)
                if daily_sales and daily_sales > 0 and available > 0
                else None
            )

            # Store as historical row (append-only)
            inv_record = HistoricalInventory(
                id=uuid.uuid4(),
                product_id=product.id,
                supplier_id=current.supplier_id,
                quantity_on_hand=current.quantity_on_hand,
                quantity_reserved=current.quantity_reserved,
                quantity_inbound=current.quantity_inbound,
                quantity_available=max(0, available),
                warehouse_location=current.warehouse_location,
                lot_number=current.lot_number,
                effective_date=now,
            )
            self._repo._session.add(inv_record)
            await self._repo._session.flush()

            components["inventory"] = CollectionStatus.SUCCESS
            return InventorySnapshot(
                product_id=product.id,
                asin=product.asin,
                timestamp=now,
                quantity_on_hand=current.quantity_on_hand,
                quantity_reserved=current.quantity_reserved,
                quantity_inbound=current.quantity_inbound,
                quantity_available=max(0, available),
                warehouse_location=current.warehouse_location,
                days_of_stock=days_of_stock,
            )
        except Exception as exc:
            logger.warning("Inventory collection failed for %s: %s", product.asin, exc)
            components["inventory"] = CollectionStatus.FAILED
            errors.append(f"inventory: {exc}")
            return None

    async def _collect_fees(
        self,
        product: Product,
        now: datetime,
        components: dict[str, CollectionStatus],
        errors: list[str],
    ) -> FeeSnapshot | None:
        """Collect Amazon fee snapshot."""
        try:
            latest = await self._repo.get_latest_fees(product.id)
            if latest is None:
                components["fees"] = CollectionStatus.SKIPPED
                return FeeSnapshot(
                    product_id=product.id,
                    asin=product.asin,
                    timestamp=now,
                )

            # Fee as percentage of price
            latest_price = await self._repo.get_latest_amazon_price(product.id)
            price = latest_price.price if latest_price else product.price
            fee_pct = (
                round(latest.total_fees / price * 100, 2)
                if price and price > 0
                else None
            )

            components["fees"] = CollectionStatus.SUCCESS
            return FeeSnapshot(
                product_id=product.id,
                asin=product.asin,
                timestamp=now,
                referral_fee=latest.referral_fee,
                fulfillment_fee=latest.fulfillment_fee,
                storage_fee=latest.storage_fee,
                closing_fee=latest.closing_fee,
                other_fees=latest.other_fees,
                total_fees=latest.total_fees,
                fee_percentage=fee_pct,
            )
        except Exception as exc:
            logger.warning("Fee collection failed for %s: %s", product.asin, exc)
            components["fees"] = CollectionStatus.FAILED
            errors.append(f"fees: {exc}")
            return None

    async def _collect_profit(
        self,
        product: Product,
        now: datetime,
        price_snapshot: PriceSnapshot | None,
        fee_snapshot: FeeSnapshot | None,
        components: dict[str, CollectionStatus],
        errors: list[str],
    ) -> ProfitSnapshot | None:
        """Calculate and store profit snapshot."""
        try:
            amazon_price = (
                price_snapshot.amazon_price
                if price_snapshot and price_snapshot.amazon_price
                else product.price
            )
            unit_cost = (
                price_snapshot.lowest_supplier_price
                if price_snapshot and price_snapshot.lowest_supplier_price
                else Decimal("0")
            )
            referral_fee = fee_snapshot.referral_fee if fee_snapshot else Decimal("0")
            fulfillment_fee = fee_snapshot.fulfillment_fee if fee_snapshot else Decimal("0")
            storage_fee = fee_snapshot.storage_fee if fee_snapshot else Decimal("0")

            if amazon_price <= 0 or unit_cost <= 0:
                components["profit"] = CollectionStatus.SKIPPED
                return ProfitSnapshot(
                    product_id=product.id,
                    asin=product.asin,
                    timestamp=now,
                    is_profitable=False,
                )

            # Calculate profit
            total_cost = unit_cost + referral_fee + fulfillment_fee + storage_fee
            gross_profit = amazon_price - unit_cost
            net_profit = amazon_price - total_cost
            margin = (net_profit / amazon_price * 100) if amazon_price > 0 else Decimal("0")
            roi = (net_profit / total_cost * 100) if total_cost > 0 else Decimal("0")

            # Store as profit calculation row
            profit_record = ProfitCalculation(
                id=uuid.uuid4(),
                product_id=product.id,
                unit_cost=unit_cost,
                amazon_price=amazon_price,
                referral_fee=referral_fee,
                fulfillment_fee=fulfillment_fee,
                storage_fee=storage_fee,
                other_costs=Decimal("0"),
                total_cost=total_cost,
                gross_profit=gross_profit,
                net_profit=net_profit,
                margin_percentage=round(margin, 2),
                roi_percentage=round(roi, 2),
                currency="USD",
                effective_date=now,
            )
            self._repo._session.add(profit_record)
            await self._repo._session.flush()

            components["profit"] = CollectionStatus.SUCCESS
            return ProfitSnapshot(
                product_id=product.id,
                asin=product.asin,
                timestamp=now,
                unit_cost=unit_cost,
                amazon_price=amazon_price,
                total_cost=total_cost,
                gross_profit=gross_profit,
                net_profit=net_profit,
                margin_percentage=round(margin, 2),
                roi_percentage=round(roi, 2),
                is_profitable=net_profit > 0,
            )
        except Exception as exc:
            logger.warning("Profit collection failed for %s: %s", product.asin, exc)
            components["profit"] = CollectionStatus.FAILED
            errors.append(f"profit: {exc}")
            return None

    # ═══════════════════════════════════════════════════════════
    # Batch Collection
    # ═══════════════════════════════════════════════════════════

    async def collect_batch(
        self,
        product_ids: list[UUID] | None = None,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> BatchCollectionResponse:
        """Collect snapshots for multiple products.

        Args:
            product_ids: Specific products to collect. If None, collects
                        for all active products within limit/offset.
            limit: Max products to process.
            offset: Pagination offset.

        Returns:
            Batch collection response with per-product results.
        """
        start_time = datetime.now(timezone.utc)

        if product_ids is not None:
            products: Sequence[Product] = []
            for pid in product_ids:
                p = await self._repo.get(pid)
                if p:
                    products = list(products) + [p]
        else:
            products = await self._repo.get_active_products(limit=limit, offset=offset)

        results: list[CollectionResponse] = []
        succeeded = 0
        partial = 0
        failed = 0

        for product in products:
            snapshot = await self.collect_snapshot(product.id)
            comp_status = {
                k: v.value for k, v in snapshot.components.items()
            } if hasattr(snapshot, 'components') else {}

            # Determine per-product status
            if snapshot.status == CollectionStatus.SUCCESS:
                succeeded += 1
            elif snapshot.status == CollectionStatus.PARTIAL:
                partial += 1
            else:
                failed += 1

            results.append(CollectionResponse(
                product_id=product.id,
                asin=product.asin,
                status=snapshot.status,
                components=comp_status,
                errors=snapshot.errors,
            ))

        duration = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000

        return BatchCollectionResponse(
            total_products=len(products),
            succeeded=succeeded,
            partial=partial,
            failed=failed,
            results=results,
            total_duration_ms=round(duration, 2),
        )

    # ═══════════════════════════════════════════════════════════
    # Time-Series Data
    # ═══════════════════════════════════════════════════════════

    async def get_time_series(
        self,
        product_id: UUID,
        metric: str,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 1000,
        cursor: datetime | None = None,
    ) -> tuple[list[TimeSeriesPoint], int]:
        """Get time-series data for a specific metric.

        Args:
            product_id: Product UUID.
            metric: Metric name. One of:
                amazon_price, buy_box_price, supplier_price,
                bsr, new_seller_count, fba_seller_count,
                quantity_on_hand, quantity_available,
                total_fees, net_profit, margin_percentage.
            since: Window start.
            until: Window end.
            limit: Max data points.
            cursor: Keyset cursor for pagination.

        Returns:
            Tuple of (data_points, total_count).
        """
        # Map metric to table and column
        table_info = self._get_metric_table(metric)
        if table_info is None:
            return [], 0

        table_name, value_column, model_class = table_info

        # Get raw data
        if model_class == AmazonPrice:
            is_buy_box = "buy_box" in metric
            rows = await self._repo.get_amazon_price_series(
                product_id, since=since, until=until,
                limit=limit, cursor=cursor, is_buy_box=is_buy_box,
            )
        elif model_class == ProductPrice:
            rows = await self._repo.get_supplier_price_series(
                product_id, since=since, until=until,
                limit=limit, cursor=cursor,
            )
        elif model_class == HistoricalInventory:
            rows = await self._repo.get_inventory_series(
                product_id, since=since, until=until,
                limit=limit, cursor=cursor,
            )
        elif model_class == SellerCount:
            rows = await self._repo.get_seller_count_series(
                product_id, since=since, until=until,
                limit=limit, cursor=cursor,
            )
        elif model_class == HistoricalFee:
            rows = await self._repo.get_fee_series(
                product_id, since=since, until=until,
                limit=limit, cursor=cursor,
            )
        elif model_class == ProfitCalculation:
            rows = await self._repo.get_profit_series(
                product_id, since=since, until=until,
                limit=limit, cursor=cursor,
            )
        elif model_class == SalesEstimate:
            rows = await self._repo.get_bsr_series(
                product_id, since=since, until=until,
                limit=limit, cursor=cursor,
            )
        else:
            return [], 0

        # Convert to TimeSeriesPoints
        points = []
        for row in rows:
            value = self._extract_value(row, value_column)
            if value is not None:
                points.append(TimeSeriesPoint(
                    timestamp=row.effective_date,
                    value=value,
                    metadata=self._extract_metadata(row, metric),
                ))

        # Get total count
        total = await self._repo.count_data_points(product_id, table_name)

        return points, total

    def _get_metric_table(
        self,
        metric: str,
    ) -> tuple[str, str, type[Any]] | None:
        """Map a metric name to its table, column, and model class."""
        mapping: dict[str, tuple[str, str, type[Any]]] = {
            "amazon_price": ("amazon_prices", "price", AmazonPrice),
            "buy_box_price": ("amazon_prices", "price", AmazonPrice),
            "supplier_price": ("product_prices", "price", ProductPrice),
            "bsr": ("sales_estimates", "sales_rank", SalesEstimate),
            "new_seller_count": ("seller_counts", "new_seller_count", SellerCount),
            "fba_seller_count": ("seller_counts", "fba_seller_count", SellerCount),
            "quantity_on_hand": ("historical_inventory", "quantity_on_hand", HistoricalInventory),
            "quantity_available": ("historical_inventory", "quantity_available", HistoricalInventory),
            "total_fees": ("historical_fees", "total_fees", HistoricalFee),
            "referral_fee": ("historical_fees", "referral_fee", HistoricalFee),
            "fulfillment_fee": ("historical_fees", "fulfillment_fee", HistoricalFee),
            "net_profit": ("profit_calculations", "net_profit", ProfitCalculation),
            "gross_profit": ("profit_calculations", "gross_profit", ProfitCalculation),
            "margin_percentage": ("profit_calculations", "margin_percentage", ProfitCalculation),
            "roi_percentage": ("profit_calculations", "roi_percentage", ProfitCalculation),
            "estimated_monthly_sales": ("sales_estimates", "estimated_monthly_sales", SalesEstimate),
        }
        return mapping.get(metric)

    def _extract_value(
        self,
        row: Any,
        column: str,
    ) -> Decimal | None:
        """Extract a numeric value from a row by column name."""
        val = getattr(row, column, None)
        if val is None:
            return None
        if isinstance(val, Decimal):
            return val
        if isinstance(val, (int, float)):
            return Decimal(str(val))
        return None

    def _extract_metadata(
        self,
        row: Any,
        metric: str,
    ) -> dict[str, str | float | int | None]:
        """Extract metadata from a row for the time-series point."""
        meta: dict[str, str | float | int | None] = {}
        if hasattr(row, "is_buy_box"):
            meta["is_buy_box"] = str(getattr(row, "is_buy_box", False))
        if hasattr(row, "is_amazon_fulfilled"):
            meta["is_fba"] = str(getattr(row, "is_amazon_fulfilled", False))
        if hasattr(row, "condition"):
            meta["condition"] = getattr(row, "condition", None)
        if hasattr(row, "supplier_id"):
            meta["supplier_id"] = str(getattr(row, "supplier_id", "")) if getattr(row, "supplier_id", None) else None
        return meta

    # ═══════════════════════════════════════════════════════════
    # Summary Statistics
    # ═══════════════════════════════════════════════════════════

    async def compute_summary(
        self,
        product_id: UUID,
        metric: str,
        *,
        days: int = DEFAULT_WINDOW_DAYS,
    ) -> HistoricalSummary | None:
        """Compute summary statistics for a metric over a time window.

        Args:
            product_id: Product UUID.
            metric: Metric name (e.g., 'amazon_price', 'net_profit').
            days: Analysis window in days.

        Returns:
            HistoricalSummary with statistics, or None if no data.
        """
        product = await self._repo.get(product_id)
        if product is None:
            return None

        table_info = self._get_metric_table(metric)
        if table_info is None:
            return None

        table_name, value_column, _ = table_info

        now = datetime.now(timezone.utc)
        since = now - timedelta(days=days)

        # Get SQL aggregation
        agg = await self._repo.compute_summary(
            product_id, table_name, value_column,
            since=since,
        )

        if not agg or agg.get("count", 0) == 0:
            return HistoricalSummary(
                product_id=product_id,
                asin=product.asin,
                metric=metric,
                window_start=since,
                window_end=now,
                data_point_count=0,
                trend=TrendDirection.INSUFFICIENT_DATA,
            )

        # Get trend slope
        slope = await self._repo.compute_trend_slope(
            product_id, table_name, value_column,
            since=since,
        )

        # Determine trend direction
        trend = self._determine_trend(agg, slope)

        # Compute derived statistics
        count = agg.get("count", 0)
        min_val = self._to_decimal(agg.get("min"))
        max_val = self._to_decimal(agg.get("max"))
        mean_val = self._to_decimal(agg.get("mean"))
        stddev_val = self._to_decimal(agg.get("stddev"))
        first_val = self._to_decimal(agg.get("first_val"))
        last_val = self._to_decimal(agg.get("last_val"))

        # Coefficient of variation
        cv = (
            round(stddev_val / mean_val, 4)
            if stddev_val and mean_val and mean_val > 0
            else None
        )

        # Min-to-max ratio
        min_max_ratio = (
            round(min_val / max_val, 4)
            if min_val is not None and max_val is not None and max_val > 0
            else None
        )

        # Trend change
        trend_change = (
            round(last_val - first_val, 2)
            if last_val is not None and first_val is not None
            else None
        )
        trend_pct = (
            round((last_val - first_val) / first_val * 100, 2)
            if (last_val is not None and first_val is not None and first_val != 0)
            else None
        )

        return HistoricalSummary(
            product_id=product_id,
            asin=product.asin,
            metric=metric,
            window_start=since,
            window_end=now,
            data_point_count=count,
            current_value=last_val,
            mean=round(mean_val, 4) if mean_val else None,
            median=self._to_decimal(agg.get("median")),
            min=min_val,
            max=max_val,
            range=round(max_val - min_val, 2) if (min_val is not None and max_val is not None) else None,
            std_dev=round(stddev_val, 4) if stddev_val else None,
            variance=round(stddev_val ** 2, 4) if stddev_val else None,
            p10=self._to_decimal(agg.get("p10")),
            p25=self._to_decimal(agg.get("p25")),
            p75=self._to_decimal(agg.get("p75")),
            p90=self._to_decimal(agg.get("p90")),
            p95=self._to_decimal(agg.get("p95")),
            p99=self._to_decimal(agg.get("p99")),
            trend=trend,
            trend_change=trend_change,
            trend_percentage=trend_pct,
            slope=round(slope, 6) if slope else None,
            coefficient_of_variation=cv,
            min_to_max_ratio=min_max_ratio,
        )

    async def compute_multi_metric_summary(
        self,
        product_id: UUID,
        metrics: list[str],
        *,
        days: int = DEFAULT_WINDOW_DAYS,
    ) -> MultiMetricSummary:
        """Compute summary statistics for multiple metrics at once.

        Args:
            product_id: Product UUID.
            metrics: List of metric names.
            days: Analysis window in days.

        Returns:
            MultiMetricSummary with per-metric statistics.
        """
        product = await self._repo.get(product_id)
        if product is None:
            asin = "unknown"
        else:
            asin = product.asin

        now = datetime.now(timezone.utc)
        since = now - timedelta(days=days)

        result_map: dict[str, HistoricalSummary] = {}
        for metric in metrics:
            summary = await self.compute_summary(product_id, metric, days=days)
            if summary is not None:
                result_map[metric] = summary

        return MultiMetricSummary(
            product_id=product_id,
            asin=asin,
            window_start=since,
            window_end=now,
            metrics=result_map,
        )

    def _determine_trend(
        self,
        agg: dict[str, Any],
        slope: Decimal | None,
    ) -> TrendDirection:
        """Determine trend direction from aggregation data and slope."""
        count = agg.get("count", 0)
        if count < TREND_MIN_POINTS:
            return TrendDirection.INSUFFICIENT_DATA

        if slope is None:
            return TrendDirection.INSUFFICIENT_DATA

        # Normalize slope by mean to get relative change
        mean_val = self._to_decimal(agg.get("mean"))
        if mean_val and mean_val > 0:
            relative_slope = abs(slope / mean_val)
        else:
            relative_slope = abs(slope)

        # Classify based on relative slope magnitude
        if relative_slope < Decimal("0.001"):
            return TrendDirection.FLAT
        if slope > 0:
            return TrendDirection.UP
        return TrendDirection.DOWN

    @staticmethod
    def _to_decimal(value: Any) -> Decimal | None:
        """Safely convert a value to Decimal."""
        if value is None:
            return None
        try:
            return Decimal(str(value))
        except (ValueError, TypeError):
            return None
