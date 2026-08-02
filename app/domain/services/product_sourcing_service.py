"""Product sourcing service — business logic for product analytics.

Orchestrates between the Keepa API client, the database repository,
and the response cache. Handles the full lifecycle:
1. Check cache → return if fresh
2. Check database → return if data exists
3. Fetch from Keepa → store in database → cache → return
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import ResponseCache
from app.core.logging import get_logger
from app.domain.schemas.product_sourcing import (
    BSRHistoryDTO,
    BuyBoxDTO,
    PricePointDTO,
    ProductDetailDTO,
    ProductPricingDTO,
    ProductSummaryDTO,
    RefreshResponse,
    ReviewSummaryDTO,
    SalesEstimateDTO,
    SellerCountDTO,
    SellerCountHistoryDTO,
)
from app.infrastructure.repositories.product_sourcing_repository import (
    ProductSourcingRepository,
)
from app.integrations.keepa.client import KeepaClient
from app.integrations.keepa.models import KeepaProductRequest
from app.integrations.keepa.repository import KeepaRepository

logger = get_logger(__name__)


class ProductSourcingService:
    """Business logic for product sourcing operations.

    Provides cached, paginated access to product data with automatic
    Keepa API fallback for missing or stale data.
    """

    def __init__(
        self,
        repository: ProductSourcingRepository,
        keepa_client: KeepaClient | None = None,
        keepa_repository: KeepaRepository | None = None,
        cache: ResponseCache | None = None,
    ) -> None:
        self._repository = repository
        self._keepa_client = keepa_client
        self._keepa_repository = keepa_repository
        self._cache = cache

    # ── Product Search ───────────────────────────────────────

    async def search_by_asin(
        self,
        asin: str,
    ) -> ProductDetailDTO | None:
        """Search for a product by ASIN.

        Checks the database first. If not found and Keepa is configured,
        fetches from Keepa and stores the result.

        Args:
            asin: Amazon ASIN.

        Returns:
            Product detail DTO or None if not found.
        """
        # Check database
        product = await self._repository.find_by_asin(asin)
        if product is not None:
            return await self._build_detail_dto(product)

        # Try Keepa
        if self._keepa_client is not None and self._keepa_repository is not None:
            try:
                keepa_data = await self._keepa_client.get_product(
                    KeepaProductRequest(asin=asin),
                )
                product = await self._keepa_repository.store_full_product_data(keepa_data)
                return await self._build_detail_dto(product)
            except Exception as exc:
                logger.warning("Keepa lookup failed for ASIN %s: %s", asin, exc)

        return None

    async def search_by_upc(
        self,
        upc: str,
    ) -> ProductDetailDTO | None:
        """Search for a product by UPC barcode.

        Only checks the database. Keepa does not support UPC search directly.

        Args:
            upc: Universal Product Code.

        Returns:
            Product detail DTO or None if not found.
        """
        product = await self._repository.find_by_upc(upc)
        if product is None:
            return None
        return await self._build_detail_dto(product)

    async def search_by_title(
        self,
        query: str,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[Sequence[ProductSummaryDTO], int]:
        """Search products by title with pagination.

        Args:
            query: Search query string.
            page: Page number (1-indexed).
            page_size: Items per page.

        Returns:
            Tuple of (list of product summaries, total count).
        """
        skip = (page - 1) * page_size
        products, total = await self._repository.search_by_title(
            query, skip=skip, limit=page_size,
        )

        summaries = [self._build_summary_dto(p) for p in products]
        return summaries, total

    # ── Product Details ──────────────────────────────────────

    async def get_product_detail(
        self,
        product_id: UUID,
    ) -> ProductDetailDTO | None:
        """Get complete product details by database ID.

        Args:
            product_id: Database product UUID.

        Returns:
            Product detail DTO or None if not found.
        """
        product = await self._repository.get_with_details(product_id)
        if product is None:
            return None
        return await self._build_detail_dto(product)

    # ── Historical Pricing ──────────────────────────────────

    async def get_pricing_history(
        self,
        product_id: UUID,
        *,
        days: int = 90,
    ) -> ProductPricingDTO | None:
        """Get historical pricing data for a product.

        Args:
            product_id: Database product UUID.
            days: Number of days of history to return.

        Returns:
            Product pricing DTO or None if product not found.
        """
        product = await self._repository.get(product_id)
        if product is None:
            return None

        since = datetime.now(timezone.utc).replace(tzinfo=None)
        if days > 0:
            since = since.replace(hour=0, minute=0, second=0, microsecond=0)
            since = since.replace(day=max(1, since.day - days))

        # Get price history
        amazon_prices = await self._repository.get_price_history(
            product_id, is_buy_box=False, since=since,
        )
        buy_box_prices = await self._repository.get_price_history(
            product_id, is_buy_box=True, since=since,
        )

        # Get price range
        price_min, price_max = await self._repository.get_price_range(
            product_id, since=since,
        )

        # Get latest prices
        latest_amazon = await self._repository.get_latest_price(product_id, is_buy_box=False)
        latest_buy_box = await self._repository.get_latest_price(product_id, is_buy_box=True)

        return ProductPricingDTO(
            product_id=product_id,
            asin=product.asin,
            currency="USD",
            amazon_prices=[self._build_price_point(p) for p in amazon_prices],
            buy_box_prices=[self._build_price_point(p) for p in buy_box_prices],
            current_price=latest_amazon.price if latest_amazon else None,
            current_buy_box=latest_buy_box.price if latest_buy_box else None,
            price_range_min=price_min,
            price_range_max=price_max,
        )

    # ── BSR History ──────────────────────────────────────────

    async def get_bsr_history(
        self,
        product_id: UUID,
        *,
        days: int = 90,
    ) -> BSRHistoryDTO | None:
        """Get Best Sellers Rank history.

        Args:
            product_id: Database product UUID.
            days: Number of days of history.

        Returns:
            BSR history DTO or None if product not found.
        """
        product = await self._repository.get(product_id)
        if product is None:
            return None

        history = await self._repository.get_bsr_history(product_id)

        # Get current rank from latest sales estimate
        latest_estimate = await self._repository.get_latest_sales_estimate(product_id)

        return BSRHistoryDTO(
            product_id=product_id,
            asin=product.asin,
            current_rank=latest_estimate.sales_rank if latest_estimate else None,
            history=[self._build_price_point(p) for p in history],
        )

    # ── Buy Box ─────────────────────────────────────────────

    async def get_buy_box(
        self,
        product_id: UUID,
        *,
        days: int = 90,
    ) -> BuyBoxDTO | None:
        """Get Buy Box history and current winner.

        Args:
            product_id: Database product UUID.
            days: Number of days of history.

        Returns:
            Buy Box DTO or None if product not found.
        """
        product = await self._repository.get(product_id)
        if product is None:
            return None

        since = datetime.now(timezone.utc).replace(tzinfo=None)
        if days > 0:
            since = since.replace(day=max(1, since.day - days))

        history = await self._repository.get_price_history(
            product_id, is_buy_box=True, since=since,
        )
        latest = await self._repository.get_latest_price(product_id, is_buy_box=True)

        return BuyBoxDTO(
            product_id=product_id,
            asin=product.asin,
            current_buy_box_price=latest.price if latest else None,
            current_buy_box_seller=None,  # Would come from Keepa offers data
            is_amazon_fulfilled=latest.is_amazon_fulfilled if latest else False,
            history=[self._build_price_point(p) for p in history],
        )

    # ── Seller Counts ───────────────────────────────────────

    async def get_seller_counts(
        self,
        product_id: UUID,
        *,
        days: int = 90,
    ) -> SellerCountHistoryDTO | None:
        """Get seller count history.

        Args:
            product_id: Database product UUID.
            days: Number of days of history.

        Returns:
            Seller count history DTO or None if product not found.
        """
        product = await self._repository.get(product_id)
        if product is None:
            return None

        history = await self._repository.get_seller_count_history(product_id)
        latest = await self._repository.get_latest_seller_count(product_id)

        return SellerCountHistoryDTO(
            product_id=product_id,
            asin=product.asin,
            current_new_count=latest.new_seller_count if latest else 0,
            current_fba_count=latest.fba_seller_count if latest else 0,
            history=[self._build_seller_count_dto(s) for s in history],
        )

    # ── Refresh Operations ──────────────────────────────────

    async def refresh_product(
        self,
        asin: str,
        domain: str = "com",
    ) -> RefreshResponse:
        """Refresh product data from Keepa API.

        Args:
            asin: Amazon ASIN.
            domain: Amazon domain code.

        Returns:
            Refresh response with status.
        """
        if self._keepa_client is None or self._keepa_repository is None:
            return RefreshResponse(
                asin=asin,
                status="refresh_failed",
                message="Keepa integration is not configured",
            )

        try:
            keepa_data = await self._keepa_client.get_product(
                KeepaProductRequest(asin=asin, domain=domain),
            )
            product = await self._keepa_repository.store_full_product_data(keepa_data)

            # Invalidate cache
            if self._cache is not None:
                await self._cache.invalidate("product_detail", product_id=str(product.id))
                await self._cache.invalidate("product_pricing", product_id=str(product.id))

            return RefreshResponse(
                asin=asin,
                status="refresh_completed",
                message="Product data refreshed successfully",
                product_id=product.id,
            )
        except Exception as exc:
            logger.error("Refresh failed for ASIN %s: %s", asin, exc)
            return RefreshResponse(
                asin=asin,
                status="refresh_failed",
                message=str(exc),
            )

    # ── DTO Builders ────────────────────────────────────────

    def _build_summary_dto(self, product: Any) -> ProductSummaryDTO:
        """Build a summary DTO from a product ORM object."""
        return ProductSummaryDTO(
            id=product.id,
            asin=product.asin,
            title=product.title,
            brand=product.brand.name if hasattr(product, "brand") and product.brand else None,
            main_image_url=product.main_image_url,
            price=product.price,
            currency="USD",
            is_active=product.is_active,
            created_at=product.created_at,
            updated_at=product.updated_at,
        )

    async def _build_detail_dto(self, product: Any) -> ProductDetailDTO:
        """Build a detail DTO from a product ORM object with related data."""
        # Get latest analytics
        latest_reviews = await self._repository.get_latest_reviews(product.id)
        latest_sales = await self._repository.get_latest_sales_estimate(product.id)
        latest_sellers = await self._repository.get_latest_seller_count(product.id)

        return ProductDetailDTO(
            id=product.id,
            asin=product.asin,
            title=product.title,
            description=product.description,
            brand=product.brand.name if hasattr(product, "brand") and product.brand else None,
            upc=product.upc,
            ean=product.ean,
            gtin=product.gtin,
            main_image_url=product.main_image_url,
            image_urls=[],
            dimensions=product.dimensions,
            weight=product.weight,
            weight_unit=product.weight_unit,
            price=product.price,
            buy_box_price=None,
            currency="USD",
            is_active=product.is_active,
            is_amazon_fba=product.is_amazon_fba,
            is_amazon_brand=product.is_amazon_brand,
            latest_reviews=ReviewSummaryDTO(
                rating=latest_reviews.rating if latest_reviews else None,
                review_count=latest_reviews.review_count if latest_reviews else 0,
                answered_questions=latest_reviews.answered_questions if latest_reviews else 0,
                observed_at=latest_reviews.effective_date if latest_reviews else None,
            ) if latest_reviews else None,
            latest_sales_estimate=SalesEstimateDTO(
                estimated_monthly_sales=latest_sales.estimated_monthly_sales if latest_sales else 0,
                estimated_daily_sales=latest_sales.estimated_daily_sales if latest_sales else Decimal("0"),
                sales_rank=latest_sales.sales_rank if latest_sales else None,
                observed_at=latest_sales.effective_date if latest_sales else None,
            ) if latest_sales else None,
            latest_seller_count=SellerCountDTO(
                new_seller_count=latest_sellers.new_seller_count if latest_sellers else 0,
                used_seller_count=latest_sellers.used_seller_count if latest_sellers else 0,
                fba_seller_count=latest_sellers.fba_seller_count if latest_sellers else 0,
                observed_at=latest_sellers.effective_date if latest_sellers else None,
            ) if latest_sellers else None,
            created_at=product.created_at,
            updated_at=product.updated_at,
        )

    @staticmethod
    def _build_price_point(price: Any) -> PricePointDTO:
        """Build a price point DTO from an AmazonPrice ORM object."""
        return PricePointDTO(
            timestamp=price.effective_date,
            price=price.price,
            is_buy_box=price.is_buy_box,
            condition="New",
            is_fba=price.is_amazon_fulfilled,
        )

    @staticmethod
    def _build_seller_count_dto(count: Any) -> SellerCountDTO:
        """Build a seller count DTO from a SellerCount ORM object."""
        return SellerCountDTO(
            new_seller_count=count.new_seller_count,
            used_seller_count=count.used_seller_count,
            fba_seller_count=count.fba_seller_count,
            observed_at=count.effective_date,
        )
