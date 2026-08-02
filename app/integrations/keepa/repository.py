"""Keepa data repository — stores fetched Keepa data in the sourcing database.

Design decisions:
- All price data is stored in the existing historical tables (product_prices,
  amazon_prices, historical_fees, seller_counts, reviews, sales_estimates).
- Product metadata (title, brand, images, dimensions, weight) updates the
  products table.
- The repository is append-only for historical data — never overwrite.
- Batch operations use async gather for efficiency.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.product import Product
from app.domain.models.sourcing import (
    AmazonPrice,
    ProductPrice,
    Review,
    SalesEstimate,
    SellerCount,
)
from app.integrations.keepa.models import KeepaProductResponse
from app.infrastructure.repositories.base import BaseRepository


class KeepaRepository:
    """Repository for persisting Keepa API data to the database.

    Maps Keepa response models to the existing sourcing database schema.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_product(self, data: KeepaProductResponse) -> Product:
        """Create or update a product record from Keepa data.

        Updates product metadata (title, brand, images, dimensions, weight)
        if the product already exists. Creates a new product if not.

        Args:
            data: Parsed Keepa product response.

        Returns:
            The created or updated Product record.
        """
        # Check if product exists by ASIN
        stmt = select(Product).where(Product.asin == data.asin)
        result = await self._session.execute(stmt)
        product = result.scalar_one_or_none()

        if product is None:
            product = Product(
                asin=data.asin,
                title=data.title or "",
                description=data.description,
                main_image_url=data.main_image,
                weight=data.weight,
                weight_unit=data.weight_unit,
                dimensions=data.dimensions,
                price=data.current_price or Decimal("0"),
                is_active=True,
            )
            self._session.add(product)
        else:
            # Update mutable fields
            if data.title:
                product.title = data.title
            if data.description:
                product.description = data.description
            if data.main_image:
                product.main_image_url = data.main_image
            if data.weight:
                product.weight = data.weight
            if data.dimensions:
                product.dimensions = data.dimensions
            if data.current_price:
                product.price = data.current_price

        await self._session.flush()
        return product

    async def store_amazon_price(
        self,
        product_id: UUID,
        price: Decimal,
        is_buy_box: bool = False,
        is_fba: bool = False,
        condition: str = "New",
        effective_date: datetime | None = None,
    ) -> AmazonPrice:
        """Store a single Amazon price observation (append-only).

        Args:
            product_id: Product UUID.
            price: The observed price.
            is_buy_box: Is this the Buy Box price?
            is_fba: Is this Fulfilled by Amazon?
            condition: Product condition.
            effective_date: When this price was observed.

        Returns:
            The created AmazonPrice record.
        """
        record = AmazonPrice(
            product_id=product_id,
            price=price,
            currency="USD",
            condition=condition,
            is_amazon_fulfilled=is_fba,
            is_buy_box=is_buy_box,
            effective_date=effective_date or datetime.now(timezone.utc),
        )
        self._session.add(record)
        await self._session.flush()
        return record

    async def store_price_history(
        self,
        product_id: UUID,
        price_points: list,
        is_buy_box: bool = False,
    ) -> list[AmazonPrice]:
        """Store multiple Amazon price history points (append-only).

        Args:
            product_id: Product UUID.
            price_points: List of KeepaPricePoint objects.
            is_buy_box: Are these Buy Box prices?

        Returns:
            List of created AmazonPrice records.
        """
        records: list[AmazonPrice] = []
        for point in price_points:
            record = AmazonPrice(
                product_id=product_id,
                price=point.price,
                currency="USD",
                condition="New",
                is_amazon_fulfilled=False,
                is_buy_box=is_buy_box or point.is_buy_box,
                effective_date=point.timestamp,
            )
            self._session.add(record)
            records.append(record)

        if records:
            await self._session.flush()

        return records

    async def store_reviews(
        self,
        product_id: UUID,
        data: Any,
        effective_date: datetime | None = None,
    ) -> Review:
        """Store a review snapshot (append-only).

        Args:
            product_id: Product UUID.
            data: KeepaReviewData object.
            effective_date: When this snapshot was taken.

        Returns:
            The created Review record.
        """
        record = Review(
            product_id=product_id,
            rating=data.rating or Decimal("0"),
            review_count=data.review_count,
            answered_questions=data.answered_questions,
            effective_date=effective_date or datetime.now(timezone.utc),
        )
        self._session.add(record)
        await self._session.flush()
        return record

    async def store_sales_estimate(
        self,
        product_id: UUID,
        data: Any,
        effective_date: datetime | None = None,
    ) -> SalesEstimate:
        """Store a sales estimate snapshot (append-only).

        Args:
            product_id: Product UUID.
            data: KeepaSalesEstimate object.
            effective_date: When this estimate was generated.

        Returns:
            The created SalesEstimate record.
        """
        record = SalesEstimate(
            product_id=product_id,
            estimated_monthly_sales=data.estimated_monthly_sales,
            estimated_daily_sales=data.estimated_daily_sales,
            estimated_monthly_revenue=Decimal("0"),
            sales_rank=data.sales_rank,
            effective_date=effective_date or datetime.now(timezone.utc),
        )
        self._session.add(record)
        await self._session.flush()
        return record

    async def store_seller_count(
        self,
        product_id: UUID,
        new_count: int,
        used_count: int = 0,
        fba_count: int = 0,
        effective_date: datetime | None = None,
    ) -> SellerCount:
        """Store a seller count snapshot (append-only).

        Args:
            product_id: Product UUID.
            new_count: Number of new-condition sellers.
            used_count: Number of used-condition sellers.
            fba_count: Number of FBA sellers.
            effective_date: When this count was observed.

        Returns:
            The created SellerCount record.
        """
        record = SellerCount(
            product_id=product_id,
            new_seller_count=new_count,
            used_seller_count=used_count,
            fba_seller_count=fba_count,
            effective_date=effective_date or datetime.now(timezone.utc),
        )
        self._session.add(record)
        await self._session.flush()
        return record

    async def store_full_product_data(
        self,
        data: KeepaProductResponse,
    ) -> Product:
        """Store all product data from a Keepa response in one operation.

        This is the primary entry point for persisting Keepa data.
        It stores:
        1. Product metadata (upsert)
        2. Amazon price history (append-only)
        3. Buy Box price history (append-only)
        4. Review snapshot (append-only)
        5. Sales estimate (append-only)
        6. Seller count (append-only)

        Args:
            data: Parsed Keepa product response.

        Returns:
            The upserted Product record.
        """
        # 1. Upsert product metadata
        product = await self.upsert_product(data)

        # 2. Store Amazon price history (sample every 10th point to avoid overload)
        if data.amazon_price_history:
            sampled = data.amazon_price_history[::10]  # Every 10th point
            await self.store_price_history(product.id, sampled, is_buy_box=False)

        # 3. Store Buy Box price history
        if data.buy_box_price_history:
            sampled = data.buy_box_price_history[::10]
            await self.store_price_history(product.id, sampled, is_buy_box=True)

        # 4. Store current prices
        if data.current_price and data.current_price > 0:
            await self.store_amazon_price(
                product.id, data.current_price, is_buy_box=False,
            )
        if data.current_buy_box_price and data.current_buy_box_price > 0:
            await self.store_amazon_price(
                product.id, data.current_buy_box_price, is_buy_box=True,
            )

        # 5. Store review snapshot
        if data.reviews.review_count > 0:
            await self.store_reviews(product.id, data.reviews)

        # 6. Store sales estimate
        if data.sales_estimates.estimated_monthly_sales > 0:
            await self.store_sales_estimate(product.id, data.sales_estimates)

        # 7. Store seller count
        if data.seller_count > 0:
            await self.store_seller_count(
                product.id,
                new_count=data.seller_count,
                fba_count=data.fba_offer_count,
            )

        return product
