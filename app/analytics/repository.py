"""Analytics repository — optimized time-series queries for millions of rows.

Design decisions:
- All time-series queries use composite indexes on (product_id, effective_date).
- Window functions (LAG, AVG over partition) for trend calculations.
- Batch inserts for efficient snapshot storage.
- Pagination via keyset pagination (WHERE effective_date < ?) for stable
  ordering at scale — no OFFSET on large tables.
- Summary statistics use SQL aggregation functions, not Python.
- Read replicas: all queries are read-only SELECT statements.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import Select, desc, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.product import Product
from app.domain.models.sourcing import (
    AmazonPrice,
    HistoricalFee,
    HistoricalInventory,
    ProductPrice,
    ProfitCalculation,
    Review,
    SalesEstimate,
    SellerCount,
)
from app.infrastructure.repositories.base import BaseRepository


class AnalyticsRepository(BaseRepository[Product]):
    """Repository for historical analytics queries.

    All methods are optimized for time-series access patterns on
    append-only tables with millions of rows.
    """

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Product)

    # ═══════════════════════════════════════════════════════════
    # Batch Insert (for efficient snapshot storage)
    # ═══════════════════════════════════════════════════════════

    async def bulk_insert_amazon_prices(
        self,
        records: list[dict[str, Any]],
    ) -> None:
        """Bulk insert Amazon price observations.

        Uses raw INSERT for maximum throughput. Skips conflict check
        since this is append-only — every observation is unique.
        """
        if not records:
            return
        stmt = text("""
            INSERT INTO amazon_prices
                (id, product_id, price, currency, condition,
                 is_amazon_fulfilled, is_buy_box, is_prime, effective_date,
                 created_at, updated_at)
            VALUES
                (:id, :product_id, :price, :currency, :condition,
                 :is_amazon_fulfilled, :is_buy_box, :is_prime, :effective_date,
                 NOW(), NOW())
        """)
        await self._session.execute(stmt, records)
        await self._session.flush()

    async def bulk_insert_product_prices(
        self,
        records: list[dict[str, Any]],
    ) -> None:
        """Bulk insert supplier price observations."""
        if not records:
            return
        stmt = text("""
            INSERT INTO product_prices
                (id, product_id, supplier_id, price, currency,
                 quantity_break, source, effective_date,
                 created_at, updated_at)
            VALUES
                (:id, :product_id, :supplier_id, :price, :currency,
                 :quantity_break, :source, :effective_date,
                 NOW(), NOW())
        """)
        await self._session.execute(stmt, records)
        await self._session.flush()

    async def bulk_insert_historical_inventory(
        self,
        records: list[dict[str, Any]],
    ) -> list[UUID]:
        """Bulk insert historical inventory snapshots.

        Returns the IDs of the inserted rows.
        """
        if not records:
            return []
        stmt = text("""
            INSERT INTO historical_inventory
                (id, product_id, supplier_id,
                 quantity_on_hand, quantity_reserved, quantity_inbound, quantity_available,
                 warehouse_location, lot_number,
                 effective_date, created_at, updated_at)
            VALUES
                (:id, :product_id, :supplier_id,
                 :quantity_on_hand, :quantity_reserved, :quantity_inbound, :quantity_available,
                 :warehouse_location, :lot_number,
                 :effective_date, NOW(), NOW())
            RETURNING id
        """)
        result = await self._session.execute(stmt, records)
        await self._session.flush()
        return [row[0] for row in result.fetchall()]

    async def bulk_insert_fees(
        self,
        records: list[dict[str, Any]],
    ) -> None:
        """Bulk insert historical fee observations."""
        if not records:
            return
        stmt = text("""
            INSERT INTO historical_fees
                (id, product_id, referral_fee, closing_fee, storage_fee,
                 fulfillment_fee, other_fees, total_fees, currency,
                 effective_date, created_at, updated_at)
            VALUES
                (:id, :product_id, :referral_fee, :closing_fee, :storage_fee,
                 :fulfillment_fee, :other_fees, :total_fees, :currency,
                 :effective_date, NOW(), NOW())
        """)
        await self._session.execute(stmt, records)
        await self._session.flush()

    async def bulk_insert_profit_calculations(
        self,
        records: list[dict[str, Any]],
    ) -> None:
        """Bulk insert profit calculation snapshots."""
        if not records:
            return
        stmt = text("""
            INSERT INTO profit_calculations
                (id, product_id, unit_cost, amazon_price,
                 referral_fee, fulfillment_fee, storage_fee, other_costs,
                 total_cost, gross_profit, net_profit,
                 margin_percentage, roi_percentage, currency,
                 effective_date, created_at, updated_at)
            VALUES
                (:id, :product_id, :unit_cost, :amazon_price,
                 :referral_fee, :fulfillment_fee, :storage_fee, :other_costs,
                 :total_cost, :gross_profit, :net_profit,
                 :margin_percentage, :roi_percentage, :currency,
                 :effective_date, NOW(), NOW())
        """)
        await self._session.execute(stmt, records)
        await self._session.flush()

    # ═══════════════════════════════════════════════════════════
    # Time-Series Queries (Keyset Pagination)
    # ═══════════════════════════════════════════════════════════

    async def get_amazon_price_series(
        self,
        product_id: UUID,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 1000,
        cursor: datetime | None = None,
        is_buy_box: bool | None = None,
    ) -> Sequence[AmazonPrice]:
        """Get Amazon price time-series with keyset pagination.

        Args:
            product_id: Product UUID.
            since: Only return prices after this date.
            until: Only return prices before this date.
            limit: Maximum rows (default 1000).
            cursor: Keyset cursor — return rows BEFORE this timestamp.
            is_buy_box: Filter by Buy Box status (None = all).

        Returns:
            Price records ordered by effective_date DESC.
        """
        stmt = self._build_time_series_query(
            AmazonPrice,
            product_id,
            since=since,
            until=until,
            limit=limit,
            cursor=cursor,
        )
        if is_buy_box is not None:
            stmt = stmt.where(AmazonPrice.is_buy_box == is_buy_box)
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def get_supplier_price_series(
        self,
        product_id: UUID,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 1000,
        cursor: datetime | None = None,
    ) -> Sequence[ProductPrice]:
        """Get supplier price time-series with keyset pagination."""
        stmt = self._build_time_series_query(
            ProductPrice,
            product_id,
            since=since,
            until=until,
            limit=limit,
            cursor=cursor,
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def get_inventory_series(
        self,
        product_id: UUID,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 1000,
        cursor: datetime | None = None,
    ) -> Sequence[HistoricalInventory]:
        """Get historical inventory time-series with keyset pagination."""
        stmt = self._build_time_series_query(
            HistoricalInventory,
            product_id,
            since=since,
            until=until,
            limit=limit,
            cursor=cursor,
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def get_seller_count_series(
        self,
        product_id: UUID,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 1000,
        cursor: datetime | None = None,
    ) -> Sequence[SellerCount]:
        """Get seller count time-series with keyset pagination."""
        stmt = self._build_time_series_query(
            SellerCount,
            product_id,
            since=since,
            until=until,
            limit=limit,
            cursor=cursor,
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def get_fee_series(
        self,
        product_id: UUID,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 1000,
        cursor: datetime | None = None,
    ) -> Sequence[HistoricalFee]:
        """Get historical fee time-series with keyset pagination."""
        stmt = self._build_time_series_query(
            HistoricalFee,
            product_id,
            since=since,
            until=until,
            limit=limit,
            cursor=cursor,
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def get_profit_series(
        self,
        product_id: UUID,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 1000,
        cursor: datetime | None = None,
    ) -> Sequence[ProfitCalculation]:
        """Get profit calculation time-series with keyset pagination."""
        stmt = self._build_time_series_query(
            ProfitCalculation,
            product_id,
            since=since,
            until=until,
            limit=limit,
            cursor=cursor,
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def get_bsr_series(
        self,
        product_id: UUID,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 1000,
        cursor: datetime | None = None,
    ) -> Sequence[SalesEstimate]:
        """Get BSR (sales rank) time-series with keyset pagination."""
        stmt = self._build_time_series_query(
            SalesEstimate,
            product_id,
            since=since,
            until=until,
            limit=limit,
            cursor=cursor,
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    def _build_time_series_query(
        self,
        model: type[Any],
        product_id: UUID,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 1000,
        cursor: datetime | None = None,
    ) -> Select[Any]:
        """Build a time-series query with keyset pagination.

        Uses the composite index (product_id, effective_date) for
        efficient range scans. Keyset pagination avoids OFFSET
        which degrades on large tables.
        """
        stmt = (
            select(model)
            .where(model.product_id == product_id)  # type: ignore[arg-type]
            .order_by(desc(model.effective_date))  # type: ignore[arg-type]
            .limit(limit)
        )

        if since is not None:
            stmt = stmt.where(model.effective_date >= since)  # type: ignore[arg-type]
        if until is not None:
            stmt = stmt.where(model.effective_date <= until)  # type: ignore[arg-type]
        if cursor is not None:
            # Keyset: return rows BEFORE the cursor timestamp
            stmt = stmt.where(model.effective_date < cursor)  # type: ignore[arg-type]

        return stmt

    # ═══════════════════════════════════════════════════════════
    # Latest Snapshots
    # ═══════════════════════════════════════════════════════════

    async def get_latest_amazon_price(
        self,
        product_id: UUID,
        is_buy_box: bool = False,
    ) -> AmazonPrice | None:
        """Get the most recent Amazon price observation."""
        stmt = (
            select(AmazonPrice)
            .where(AmazonPrice.product_id == product_id)
            .where(AmazonPrice.is_buy_box == is_buy_box)
            .order_by(desc(AmazonPrice.effective_date))
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_latest_supplier_prices(
        self,
        product_id: UUID,
    ) -> Sequence[ProductPrice]:
        """Get the most recent supplier price per supplier.

        Returns the latest price observation for each distinct supplier
        (including the NULL/generic supplier bucket), ordered by price
        ascending. Uses ORM queries so the product_id UUID comparison is
        portable across SQLite and Postgres.
        """
        stmt = (
            select(ProductPrice)
            .where(ProductPrice.product_id == product_id)
            .order_by(desc(ProductPrice.effective_date))
        )
        result = await self._session.execute(stmt)
        rows = result.scalars().all()

        latest: dict[UUID | None, ProductPrice] = {}
        for row in rows:
            if row.supplier_id not in latest:
                latest[row.supplier_id] = row
        return sorted(latest.values(), key=lambda p: p.price)

    async def get_latest_inventory(
        self,
        product_id: UUID,
    ) -> HistoricalInventory | None:
        """Get the most recent inventory snapshot."""
        stmt = (
            select(HistoricalInventory)
            .where(HistoricalInventory.product_id == product_id)
            .order_by(desc(HistoricalInventory.effective_date))
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_latest_fees(
        self,
        product_id: UUID,
    ) -> HistoricalFee | None:
        """Get the most recent fee snapshot."""
        stmt = (
            select(HistoricalFee)
            .where(HistoricalFee.product_id == product_id)
            .order_by(desc(HistoricalFee.effective_date))
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_latest_profit(
        self,
        product_id: UUID,
    ) -> ProfitCalculation | None:
        """Get the most recent profit calculation."""
        stmt = (
            select(ProfitCalculation)
            .where(ProfitCalculation.product_id == product_id)
            .order_by(desc(ProfitCalculation.effective_date))
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_latest_seller_count(
        self,
        product_id: UUID,
    ) -> SellerCount | None:
        """Get the most recent seller count snapshot."""
        stmt = (
            select(SellerCount)
            .where(SellerCount.product_id == product_id)
            .order_by(desc(SellerCount.effective_date))
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_latest_sales_estimate(
        self,
        product_id: UUID,
    ) -> SalesEstimate | None:
        """Get the most recent sales estimate."""
        stmt = (
            select(SalesEstimate)
            .where(SalesEstimate.product_id == product_id)
            .order_by(desc(SalesEstimate.effective_date))
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    # ═══════════════════════════════════════════════════════════
    # Summary Statistics (SQL Aggregation)
    # ═══════════════════════════════════════════════════════════

    async def compute_summary(
        self,
        product_id: UUID,
        table_name: str,
        value_column: str,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> dict[str, Any]:
        """Compute summary statistics for a metric using SQL aggregation.

        Uses ORM queries for cross-database compatibility.
        """
        model = self._get_model_for_table(table_name)
        if model is None:
            return {}

        value_attr = getattr(model, value_column, None)
        date_attr = getattr(model, "effective_date", None)
        if value_attr is None or date_attr is None:
            return {}

        # Get all values for Python-side computation (works on all databases)
        stmt = (
            select(value_attr, date_attr)
            .where(model.product_id == product_id)  # type: ignore[arg-type]
            .order_by(date_attr.asc())
        )
        if since is not None:
            stmt = stmt.where(date_attr >= since)
        if until is not None:
            stmt = stmt.where(date_attr <= until)

        result = await self._session.execute(stmt)
        rows = result.fetchall()

        if not rows:
            return {}

        values = sorted([float(row[0]) for row in rows if row[0] is not None])
        if not values:
            return {}

        n = len(values)
        total = sum(values)
        mean = total / n

        # Variance and stddev
        variance = sum((x - mean) ** 2 for x in values) / n
        stddev = variance ** 0.5

        def percentile(data: list[float], p: float) -> float:
            k = (p / 100.0) * (len(data) - 1)
            f = int(k)
            c = k - f
            if f + 1 < len(data):
                return data[f] * (1 - c) + data[f + 1] * c
            return data[f]

        return {
            "count": n,
            "min": values[0],
            "max": values[-1],
            "mean": mean,
            "median": percentile(values, 50),
            "stddev": stddev,
            "p10": percentile(values, 10),
            "p25": percentile(values, 25),
            "p75": percentile(values, 75),
            "p90": percentile(values, 90),
            "p95": percentile(values, 95),
            "p99": percentile(values, 99),
            "first_val": values[0],
            "last_val": values[-1],
        }

    async def compute_trend_slope(
        self,
        product_id: UUID,
        table_name: str,
        value_column: str,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> Decimal | None:
        """Compute the linear regression slope for a metric over time.

        Uses ORM queries for cross-database compatibility.

        Returns:
            Slope as change per day, or None if insufficient data.
        """
        model = self._get_model_for_table(table_name)
        if model is None:
            return None

        value_attr = getattr(model, value_column, None)
        date_attr = getattr(model, "effective_date", None)
        if value_attr is None or date_attr is None:
            return None

        stmt = (
            select(value_attr, date_attr)
            .where(model.product_id == product_id)  # type: ignore[arg-type]
            .order_by(date_attr.asc())
        )
        if since is not None:
            stmt = stmt.where(date_attr >= since)
        if until is not None:
            stmt = stmt.where(date_attr <= until)

        result = await self._session.execute(stmt)
        rows = result.fetchall()

        if len(rows) < 2:
            return None

        # Convert to numeric arrays
        import datetime as dt_module

        x_vals: list[float] = []
        y_vals: list[float] = []
        for row in rows:
            val = row[0]
            ts = row[1]
            if val is None or ts is None:
                continue
            if isinstance(ts, str):
                ts = dt_module.datetime.fromisoformat(ts)
            if isinstance(ts, dt_module.datetime):
                x_vals.append(ts.timestamp())
                y_vals.append(float(val))

        if len(x_vals) < 2:
            return None

        # Linear regression: slope = cov(x, y) / var(x)
        n = len(x_vals)
        mean_x = sum(x_vals) / n
        mean_y = sum(y_vals) / n

        cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(x_vals, y_vals, strict=False))
        var_x = sum((x - mean_x) ** 2 for x in x_vals)

        if var_x == 0:
            return None

        slope = cov / var_x
        return Decimal(str(slope))

    # ═══════════════════════════════════════════════════════════
    # Product Queries
    # ═══════════════════════════════════════════════════════════

    async def get_active_products(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[Product]:
        """Get active products for batch collection."""
        stmt = (
            select(Product)
            .where(Product.is_active == True)  # noqa: E712
            .order_by(Product.asin)
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def count_active_products(self) -> int:
        """Count active products."""
        stmt = select(func.count()).select_from(Product).where(
            Product.is_active == True,  # noqa: E712
        )
        result = await self._session.execute(stmt)
        return result.scalar_one()

    async def get_product_by_asin(self, asin: str) -> Product | None:
        """Find a product by ASIN."""
        stmt = select(Product).where(Product.asin == asin)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    # ═══════════════════════════════════════════════════════════
    # Data Point Counts (for monitoring)
    # ═══════════════════════════════════════════════════════════

    async def count_data_points(
        self,
        product_id: UUID,
        table_name: str,
    ) -> int:
        """Count total data points for a product in a table.

        Uses SQLAlchemy ORM for cross-database compatibility.
        """
        model_map = {
            "amazon_prices": AmazonPrice,
            "product_prices": ProductPrice,
            "historical_inventory": HistoricalInventory,
            "seller_counts": SellerCount,
            "historical_fees": HistoricalFee,
            "profit_calculations": ProfitCalculation,
            "sales_estimates": SalesEstimate,
            "reviews": Review,
        }
        model = model_map.get(table_name)
        if model is None:
            return 0

        stmt = select(func.count()).select_from(model).where(
            model.product_id == product_id,  # type: ignore[arg-type]
        )
        result = await self._session.execute(stmt)
        return result.scalar_one()

    async def get_oldest_data_point(
        self,
        product_id: UUID,
        table_name: str,
    ) -> datetime | None:
        """Get the timestamp of the oldest data point."""
        model = self._get_model_for_table(table_name)
        if model is None:
            return None
        stmt = (
            select(model.effective_date)  # type: ignore[attr-defined]
            .where(model.product_id == product_id)  # type: ignore[arg-type]
            .order_by(model.effective_date.asc())  # type: ignore[attr-defined]
            .limit(1)
        )
        result = await self._session.execute(stmt)
        row = result.fetchone()
        if row is None or row[0] is None:
            return None
        val = row[0]
        if isinstance(val, str):
            try:
                return datetime.fromisoformat(val)
            except (ValueError, TypeError):
                return None
        return val if isinstance(val, datetime) else None

    async def get_newest_data_point(
        self,
        product_id: UUID,
        table_name: str,
    ) -> datetime | None:
        """Get the timestamp of the newest data point."""
        model = self._get_model_for_table(table_name)
        if model is None:
            return None
        stmt = (
            select(model.effective_date)  # type: ignore[attr-defined]
            .where(model.product_id == product_id)  # type: ignore[arg-type]
            .order_by(model.effective_date.desc())  # type: ignore[attr-defined]
            .limit(1)
        )
        result = await self._session.execute(stmt)
        row = result.fetchone()
        if row is None or row[0] is None:
            return None
        val = row[0]
        if isinstance(val, str):
            try:
                return datetime.fromisoformat(val)
            except (ValueError, TypeError):
                return None
        return val if isinstance(val, datetime) else None

    def _get_model_for_table(self, table_name: str) -> type[Any] | None:
        """Get the SQLAlchemy model class for a table name."""
        model_map = {
            "amazon_prices": AmazonPrice,
            "product_prices": ProductPrice,
            "historical_inventory": HistoricalInventory,
            "seller_counts": SellerCount,
            "historical_fees": HistoricalFee,
            "profit_calculations": ProfitCalculation,
            "sales_estimates": SalesEstimate,
            "reviews": Review,
        }
        return model_map.get(table_name)
