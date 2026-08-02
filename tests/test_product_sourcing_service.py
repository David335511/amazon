"""Tests for the product sourcing service layer.

Tests the business logic for product search, detail retrieval,
pricing history, BSR, Buy Box, and seller counts.
Uses mocked repositories and Keepa clients.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.product import Product
from app.domain.models.sourcing import AmazonPrice, Review, SalesEstimate, SellerCount
from app.domain.schemas.product_sourcing import (
    BSRHistoryDTO,
    BuyBoxDTO,
    ProductDetailDTO,
    ProductPricingDTO,
    ProductSummaryDTO,
    RefreshResponse,
    SellerCountHistoryDTO,
)
from app.domain.services.product_sourcing_service import ProductSourcingService
from app.infrastructure.repositories.product_sourcing_repository import (
    ProductSourcingRepository,
)


# ── Fixtures ────────────────────────────────────────────────


@pytest.fixture
def sample_product_id() -> UUID:
    return UUID("c0000001-0000-0000-0000-000000000001")


@pytest.fixture
def sample_product(sample_product_id: UUID) -> Product:
    """Create a sample product for testing."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return Product(
        id=sample_product_id,
        asin="B0TESTASIN",
        title="Test Product for Sourcing",
        description="A test product description",
        upc="123456789012",
        ean="1234567890123",
        gtin="12345678901234",
        main_image_url="https://example.com/image.jpg",
        dimensions="10x8x5 inches",
        weight=Decimal("1.50"),
        weight_unit="pounds",
        price=Decimal("29.99"),
        is_active=True,
        is_amazon_fba=True,
        is_amazon_brand=False,
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
def sample_amazon_price(sample_product_id: UUID) -> AmazonPrice:
    """Create a sample Amazon price record."""
    return AmazonPrice(
        id=uuid4(),
        product_id=sample_product_id,
        price=Decimal("29.99"),
        currency="USD",
        condition="New",
        is_amazon_fulfilled=True,
        is_buy_box=True,
        effective_date=datetime(2025, 3, 15, tzinfo=timezone.utc),
    )


@pytest.fixture
def sample_review(sample_product_id: UUID) -> Review:
    """Create a sample review record."""
    return Review(
        id=uuid4(),
        product_id=sample_product_id,
        rating=Decimal("4.5"),
        review_count=1234,
        answered_questions=56,
        effective_date=datetime(2025, 3, 15, tzinfo=timezone.utc),
    )


@pytest.fixture
def sample_sales_estimate(sample_product_id: UUID) -> SalesEstimate:
    """Create a sample sales estimate record."""
    return SalesEstimate(
        id=uuid4(),
        product_id=sample_product_id,
        estimated_monthly_sales=1500,
        estimated_daily_sales=Decimal("50.00"),
        estimated_monthly_revenue=Decimal("44985.00"),
        sales_rank=500,
        effective_date=datetime(2025, 3, 15, tzinfo=timezone.utc),
    )


@pytest.fixture
def sample_seller_count(sample_product_id: UUID) -> SellerCount:
    """Create a sample seller count record."""
    return SellerCount(
        id=uuid4(),
        product_id=sample_product_id,
        new_seller_count=12,
        used_seller_count=5,
        fba_seller_count=8,
        effective_date=datetime(2025, 3, 15, tzinfo=timezone.utc),
    )


# ── Service Tests ───────────────────────────────────────────


class TestProductSourcingService:
    """Test the product sourcing service with mocked repository."""

    @pytest.mark.asyncio
    async def test_search_by_asin_found(
        self,
        sample_product: Product,
        sample_product_id: UUID,
    ) -> None:
        """Test searching by ASIN when product exists in database."""
        repo = AsyncMock(spec=ProductSourcingRepository)
        repo.find_by_asin = AsyncMock(return_value=sample_product)
        repo.get_latest_reviews = AsyncMock(return_value=None)
        repo.get_latest_sales_estimate = AsyncMock(return_value=None)
        repo.get_latest_seller_count = AsyncMock(return_value=None)

        service = ProductSourcingService(repository=repo)  # type: ignore[arg-type]
        result = await service.search_by_asin("B0TESTASIN")

        assert result is not None
        assert result.asin == "B0TESTASIN"
        assert result.title == "Test Product for Sourcing"
        assert result.price == Decimal("29.99")

    @pytest.mark.asyncio
    async def test_search_by_asin_not_found(self) -> None:
        """Test searching by ASIN when product does not exist."""
        repo = AsyncMock(spec=ProductSourcingRepository)
        repo.find_by_asin = AsyncMock(return_value=None)

        service = ProductSourcingService(repository=repo)  # type: ignore[arg-type]
        result = await service.search_by_asin("B0MISSING")

        assert result is None

    @pytest.mark.asyncio
    async def test_search_by_upc_found(
        self,
        sample_product: Product,
    ) -> None:
        """Test searching by UPC when product exists."""
        repo = AsyncMock(spec=ProductSourcingRepository)
        repo.find_by_upc = AsyncMock(return_value=sample_product)
        repo.get_latest_reviews = AsyncMock(return_value=None)
        repo.get_latest_sales_estimate = AsyncMock(return_value=None)
        repo.get_latest_seller_count = AsyncMock(return_value=None)

        service = ProductSourcingService(repository=repo)  # type: ignore[arg-type]
        result = await service.search_by_upc("123456789012")

        assert result is not None
        assert result.upc == "123456789012"

    @pytest.mark.asyncio
    async def test_search_by_title_paginated(
        self,
        sample_product: Product,
    ) -> None:
        """Test searching by title with pagination."""
        repo = AsyncMock(spec=ProductSourcingRepository)
        repo.search_by_title = AsyncMock(return_value=([sample_product], 1))

        service = ProductSourcingService(repository=repo)  # type: ignore[arg-type]
        items, total = await service.search_by_title("Test", page=1, page_size=20)

        assert total == 1
        assert len(items) == 1
        assert items[0].asin == "B0TESTASIN"
        assert isinstance(items[0], ProductSummaryDTO)

    @pytest.mark.asyncio
    async def test_get_product_detail(
        self,
        sample_product: Product,
        sample_product_id: UUID,
        sample_review: Review,
        sample_sales_estimate: SalesEstimate,
        sample_seller_count: SellerCount,
    ) -> None:
        """Test getting complete product details."""
        repo = AsyncMock(spec=ProductSourcingRepository)
        repo.get = AsyncMock(return_value=sample_product)
        repo.get_with_details = AsyncMock(return_value=sample_product)
        repo.get_latest_reviews = AsyncMock(return_value=sample_review)
        repo.get_latest_sales_estimate = AsyncMock(return_value=sample_sales_estimate)
        repo.get_latest_seller_count = AsyncMock(return_value=sample_seller_count)

        service = ProductSourcingService(repository=repo)  # type: ignore[arg-type]
        result = await service.get_product_detail(sample_product_id)

        assert result is not None
        assert isinstance(result, ProductDetailDTO)
        assert result.asin == "B0TESTASIN"
        assert result.latest_reviews is not None
        assert result.latest_reviews.rating == Decimal("4.5")
        assert result.latest_reviews.review_count == 1234
        assert result.latest_sales_estimate is not None
        assert result.latest_sales_estimate.estimated_monthly_sales == 1500
        assert result.latest_seller_count is not None
        assert result.latest_seller_count.new_seller_count == 12

    @pytest.mark.asyncio
    async def test_get_pricing_history(
        self,
        sample_product: Product,
        sample_product_id: UUID,
        sample_amazon_price: AmazonPrice,
    ) -> None:
        """Test getting pricing history."""
        repo = AsyncMock(spec=ProductSourcingRepository)
        repo.get = AsyncMock(return_value=sample_product)
        repo.get_price_history = AsyncMock(return_value=[sample_amazon_price])
        repo.get_price_range = AsyncMock(return_value=(Decimal("29.99"), Decimal("29.99")))
        repo.get_latest_price = AsyncMock(return_value=sample_amazon_price)

        service = ProductSourcingService(repository=repo)  # type: ignore[arg-type]
        result = await service.get_pricing_history(sample_product_id, days=90)

        assert result is not None
        assert isinstance(result, ProductPricingDTO)
        assert result.asin == "B0TESTASIN"
        assert len(result.amazon_prices) == 1
        assert result.current_price == Decimal("29.99")

    @pytest.mark.asyncio
    async def test_get_bsr_history(
        self,
        sample_product: Product,
        sample_product_id: UUID,
        sample_amazon_price: AmazonPrice,
        sample_sales_estimate: SalesEstimate,
    ) -> None:
        """Test getting BSR history."""
        repo = AsyncMock(spec=ProductSourcingRepository)
        repo.get = AsyncMock(return_value=sample_product)
        repo.get_bsr_history = AsyncMock(return_value=[sample_amazon_price])
        repo.get_latest_sales_estimate = AsyncMock(return_value=sample_sales_estimate)

        service = ProductSourcingService(repository=repo)  # type: ignore[arg-type]
        result = await service.get_bsr_history(sample_product_id, days=90)

        assert result is not None
        assert isinstance(result, BSRHistoryDTO)
        assert result.current_rank == 500
        assert len(result.history) == 1

    @pytest.mark.asyncio
    async def test_get_buy_box(
        self,
        sample_product: Product,
        sample_product_id: UUID,
        sample_amazon_price: AmazonPrice,
    ) -> None:
        """Test getting Buy Box history."""
        repo = AsyncMock(spec=ProductSourcingRepository)
        repo.get = AsyncMock(return_value=sample_product)
        repo.get_price_history = AsyncMock(return_value=[sample_amazon_price])
        repo.get_latest_price = AsyncMock(return_value=sample_amazon_price)

        service = ProductSourcingService(repository=repo)  # type: ignore[arg-type]
        result = await service.get_buy_box(sample_product_id, days=90)

        assert result is not None
        assert isinstance(result, BuyBoxDTO)
        assert result.current_buy_box_price == Decimal("29.99")
        assert len(result.history) == 1

    @pytest.mark.asyncio
    async def test_get_seller_counts(
        self,
        sample_product: Product,
        sample_product_id: UUID,
        sample_seller_count: SellerCount,
    ) -> None:
        """Test getting seller count history."""
        repo = AsyncMock(spec=ProductSourcingRepository)
        repo.get = AsyncMock(return_value=sample_product)
        repo.get_seller_count_history = AsyncMock(return_value=[sample_seller_count])
        repo.get_latest_seller_count = AsyncMock(return_value=sample_seller_count)

        service = ProductSourcingService(repository=repo)  # type: ignore[arg-type]
        result = await service.get_seller_counts(sample_product_id, days=90)

        assert result is not None
        assert isinstance(result, SellerCountHistoryDTO)
        assert result.current_new_count == 12
        assert result.current_fba_count == 8
        assert len(result.history) == 1

    @pytest.mark.asyncio
    async def test_refresh_product_no_keepa(self) -> None:
        """Test refresh when Keepa is not configured."""
        repo = AsyncMock(spec=ProductSourcingRepository)
        service = ProductSourcingService(repository=repo)  # type: ignore[arg-type]

        result = await service.refresh_product("B0TESTASIN")
        assert result.status == "refresh_failed"
        assert "not configured" in (result.message or "")

    @pytest.mark.asyncio
    async def test_get_product_detail_not_found(
        self,
        sample_product_id: UUID,
    ) -> None:
        """Test getting details for non-existent product."""
        repo = AsyncMock(spec=ProductSourcingRepository)
        repo.get = AsyncMock(return_value=None)
        repo.get_with_details = AsyncMock(return_value=None)

        service = ProductSourcingService(repository=repo)  # type: ignore[arg-type]
        result = await service.get_product_detail(sample_product_id)

        assert result is None
