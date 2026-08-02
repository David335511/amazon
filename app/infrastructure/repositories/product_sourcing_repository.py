"""Product sourcing repository — data access for product analytics.

Provides efficient queries for historical pricing, BSR, Buy Box,
seller counts, and product search. All time-series queries are
optimized with composite indexes on (product_id, effective_date).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Select, desc, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.models.product import Product
from app.domain.models.sourcing import (
    AmazonPrice,
    Review,
    SalesEstimate,
    SellerCount,
)
from app.infrastructure.repositories.base import BaseRepository


class ProductSourcingRepository(BaseRepository[Product]):
    """Repository for product sourcing data access.

    Provides specialized queries for:
    - Product search by ASIN, UPC, title
    - Historical pricing with time ranges
    - BSR history
    - Buy Box history
    - Seller count history
    - Latest analytics snapshots
    """

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Product)

    # ── Product Lookup ──────────────────────────────────────

    async def find_by_asin(self, asin: str) -> Product | None:
        """Find a product by its Amazon ASIN."""
        stmt = select(Product).where(Product.asin == asin)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def find_by_upc(self, upc: str) -> Product | None:
        """Find a product by its UPC barcode."""
        stmt = select(Product).where(Product.upc == upc)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def search_by_title(
        self,
        query: str,
        *,
        skip: int = 0,
        limit: int = 20,
    ) -> tuple[Sequence[Product], int]:
        """Search products by title (case-insensitive)."""
        search_pattern = f"%{query}%"
        stmt = (
            select(Product)
            .where(Product.title.ilike(search_pattern))
            .order_by(Product.title)
            .offset(skip)
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        items = result.scalars().all()

        # Count
        count_stmt = select(func.count()).select_from(Product).where(
            Product.title.ilike(search_pattern),
        )
        count_result = await self._session.execute(count_stmt)
        total = count_result.scalar_one()

        return items, total

    async def get_with_details(self, product_id: UUID) -> Product | None:
        """Get a product with all related data eagerly loaded."""
        stmt = (
            select(Product)
            .options(
                selectinload(Product.brand),
                selectinload(Product.category_rel),
            )
            .where(Product.id == product_id)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    # ── Historical Pricing ─────────────────────────────────

    async def get_price_history(
        self,
        product_id: UUID,
        *,
        limit: int = 1000,
        is_buy_box: bool | None = None,
        since: datetime | None = None,
    ) -> Sequence[AmazonPrice]:
        """Get historical Amazon prices for a product.

        Args:
            product_id: Product UUID.
            limit: Maximum number of price points.
            is_buy_box: Filter by Buy Box status (None = all).
            since: Only return prices after this date.

        Returns:
            Price history ordered by effective_date descending.
        """
        stmt = (
            select(AmazonPrice)
            .where(AmazonPrice.product_id == product_id)
            .order_by(desc(AmazonPrice.effective_date))
        )

        if is_buy_box is not None:
            stmt = stmt.where(AmazonPrice.is_buy_box == is_buy_box)
        if since is not None:
            stmt = stmt.where(AmazonPrice.effective_date >= since)

        stmt = stmt.limit(limit)
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def get_price_range(
        self,
        product_id: UUID,
        *,
        since: datetime | None = None,
    ) -> tuple[Decimal | None, Decimal | None]:
        """Get the min and max historical prices for a product.

        Returns:
            Tuple of (min_price, max_price).
        """
        stmt = select(
            func.min(AmazonPrice.price),
            func.max(AmazonPrice.price),
        ).where(AmazonPrice.product_id == product_id)

        if since is not None:
            stmt = stmt.where(AmazonPrice.effective_date >= since)

        result = await self._session.execute(stmt)
        row = result.one()
        return row[0], row[1]

    async def get_latest_price(
        self,
        product_id: UUID,
        is_buy_box: bool = False,
    ) -> AmazonPrice | None:
        """Get the most recent price observation for a product."""
        stmt = (
            select(AmazonPrice)
            .where(AmazonPrice.product_id == product_id)
            .where(AmazonPrice.is_buy_box == is_buy_box)
            .order_by(desc(AmazonPrice.effective_date))
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    # ── BSR History ────────────────────────────────────────

    async def get_bsr_history(
        self,
        product_id: UUID,
        *,
        limit: int = 500,
    ) -> Sequence[AmazonPrice]:
        """Get BSR history for a product.

        BSR is stored in the amazon_prices table with is_buy_box flag
        or can be derived from sales_estimates.

        Args:
            product_id: Product UUID.
            limit: Maximum number of data points.

        Returns:
            BSR history ordered by effective_date descending.
        """
        stmt = (
            select(AmazonPrice)
            .where(AmazonPrice.product_id == product_id)
            .where(AmazonPrice.is_buy_box == True)  # noqa: E712
            .order_by(desc(AmazonPrice.effective_date))
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    # ── Seller Counts ───────────────────────────────────────

    async def get_seller_count_history(
        self,
        product_id: UUID,
        *,
        limit: int = 500,
    ) -> Sequence[SellerCount]:
        """Get seller count history for a product.

        Args:
            product_id: Product UUID.
            limit: Maximum number of data points.

        Returns:
            Seller count history ordered by effective_date descending.
        """
        stmt = (
            select(SellerCount)
            .where(SellerCount.product_id == product_id)
            .order_by(desc(SellerCount.effective_date))
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

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

    # ── Reviews ──────────────────────────────────────────────

    async def get_latest_reviews(
        self,
        product_id: UUID,
    ) -> Review | None:
        """Get the most recent review snapshot."""
        stmt = (
            select(Review)
            .where(Review.product_id == product_id)
            .order_by(desc(Review.effective_date))
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    # ── Sales Estimates ──────────────────────────────────────

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

    # ── Aggregations ─────────────────────────────────────────

    async def get_product_count(self) -> int:
        """Get total number of active products."""
        stmt = select(func.count()).select_from(Product).where(Product.is_active == True)  # noqa: E712
        result = await self._session.execute(stmt)
        return result.scalar_one()

    async def get_recently_updated_products(
        self,
        *,
        limit: int = 20,
        hours: int = 24,
    ) -> Sequence[Product]:
        """Get products updated within the last N hours."""
        since = datetime.now(timezone.utc).replace(tzinfo=None)
        stmt = (
            select(Product)
            .where(Product.updated_at >= since)
            .order_by(desc(Product.updated_at))
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()
