"""Integration tests for the Keepa service and repository layers.

Tests the full flow: client → service → repository → database.
Uses an in-memory SQLite database and mocked HTTP responses.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.product import Product
from app.domain.models.sourcing import AmazonPrice, Review, SalesEstimate, SellerCount
from app.integrations.keepa.client import KeepaClient
from app.integrations.keepa.config import KeepaConfig
from app.integrations.keepa.models import (
    KeepaProductResponse,
    KeepaReviewData,
    KeepaSalesEstimate,
)
from app.integrations.keepa.repository import KeepaRepository
from app.integrations.keepa.service import KeepaService


# ── Fixtures ────────────────────────────────────────────────


@pytest.fixture
def keepa_config() -> KeepaConfig:
    """Create a test Keepa configuration."""
    return KeepaConfig(
        api_key="test-key",
        max_retries=1,
        retry_base_delay=0.01,
        requests_per_minute=120,
        cache_ttl_seconds=0,
    )


@pytest.fixture
def mock_product_response() -> KeepaProductResponse:
    """Create a realistic mock Keepa product response."""
    return KeepaProductResponse(
        asin="B0TESTINT",
        domain="com",
        title="Integration Test Product",
        brand="TestBrand",
        description="A product for integration testing",
        features=["Feature A", "Feature B"],
        upc="123456789012",
        main_image="https://images.example.com/test.jpg",
        images=["https://images.example.com/test.jpg"],
        dimensions="10x8x5 inches",
        weight=Decimal("1.50"),
        weight_unit="pounds",
        current_price=Decimal("29.99"),
        current_buy_box_price=Decimal("28.99"),
        currency="USD",
        reviews=KeepaReviewData(
            rating=Decimal("4.5"),
            review_count=1234,
            answered_questions=56,
            rating_distribution={5: 800, 4: 300, 3: 100, 2: 20, 1: 14},
        ),
        sales_estimates=KeepaSalesEstimate(
            estimated_monthly_sales=1500,
            estimated_daily_sales=Decimal("50.00"),
            sales_rank=500,
        ),
        offer_count=5,
        fba_offer_count=3,
        seller_count=5,
    )


# ── Repository Tests ─────────────────────────────────────────


class TestKeepaRepository:
    """Test the Keepa repository layer with an in-memory database."""

    @pytest.mark.asyncio
    async def test_upsert_product_creates_new(
        self,
        db_session: AsyncSession,
        mock_product_response: KeepaProductResponse,
    ) -> None:
        """Test that upsert creates a new product when none exists."""
        repo = KeepaRepository(db_session)
        product = await repo.upsert_product(mock_product_response)

        assert product.asin == "B0TESTINT"
        assert product.title == "Integration Test Product"
        assert product.price == Decimal("29.99")
        assert product.id is not None

    @pytest.mark.asyncio
    async def test_upsert_product_updates_existing(
        self,
        db_session: AsyncSession,
        mock_product_response: KeepaProductResponse,
    ) -> None:
        """Test that upsert updates an existing product."""
        repo = KeepaRepository(db_session)

        # First insert
        product = await repo.upsert_product(mock_product_response)
        original_id = product.id

        # Update with new data
        updated_response = mock_product_response.model_copy(
            update={"title": "Updated Title", "current_price": Decimal("24.99")},
        )
        product = await repo.upsert_product(updated_response)

        assert product.id == original_id
        assert product.title == "Updated Title"
        assert product.price == Decimal("24.99")

    @pytest.mark.asyncio
    async def test_store_amazon_price(
        self,
        db_session: AsyncSession,
        mock_product_response: KeepaProductResponse,
    ) -> None:
        """Test storing an Amazon price observation."""
        repo = KeepaRepository(db_session)
        product = await repo.upsert_product(mock_product_response)

        price = await repo.store_amazon_price(
            product_id=product.id,
            price=Decimal("29.99"),
            is_buy_box=True,
        )

        assert price.product_id == product.id
        assert price.price == Decimal("29.99")
        assert price.is_buy_box is True

    @pytest.mark.asyncio
    async def test_store_reviews(
        self,
        db_session: AsyncSession,
        mock_product_response: KeepaProductResponse,
    ) -> None:
        """Test storing a review snapshot."""
        repo = KeepaRepository(db_session)
        product = await repo.upsert_product(mock_product_response)

        review = await repo.store_reviews(product.id, mock_product_response.reviews)

        assert review.product_id == product.id
        assert review.rating == Decimal("4.5")
        assert review.review_count == 1234

    @pytest.mark.asyncio
    async def test_store_sales_estimate(
        self,
        db_session: AsyncSession,
        mock_product_response: KeepaProductResponse,
    ) -> None:
        """Test storing a sales estimate."""
        repo = KeepaRepository(db_session)
        product = await repo.upsert_product(mock_product_response)

        estimate = await repo.store_sales_estimate(
            product.id, mock_product_response.sales_estimates,
        )

        assert estimate.product_id == product.id
        assert estimate.estimated_monthly_sales == 1500
        assert estimate.sales_rank == 500

    @pytest.mark.asyncio
    async def test_store_seller_count(
        self,
        db_session: AsyncSession,
        mock_product_response: KeepaProductResponse,
    ) -> None:
        """Test storing a seller count snapshot."""
        repo = KeepaRepository(db_session)
        product = await repo.upsert_product(mock_product_response)

        count = await repo.store_seller_count(
            product.id, new_count=10, fba_count=5,
        )

        assert count.product_id == product.id
        assert count.new_seller_count == 10
        assert count.fba_seller_count == 5

    @pytest.mark.asyncio
    async def test_store_full_product_data(
        self,
        db_session: AsyncSession,
        mock_product_response: KeepaProductResponse,
    ) -> None:
        """Test storing all product data in one operation."""
        repo = KeepaRepository(db_session)
        product = await repo.store_full_product_data(mock_product_response)

        assert product.asin == "B0TESTINT"
        assert product.title == "Integration Test Product"

        # Verify related data was stored
        assert product.id is not None


# ── Service Tests ───────────────────────────────────────────


class TestKeepaService:
    """Test the Keepa service layer with mocked client."""

    @pytest.mark.asyncio
    async def test_fetch_and_store_product(
        self,
        db_session: AsyncSession,
        keepa_config: KeepaConfig,
        mock_product_response: KeepaProductResponse,
    ) -> None:
        """Test the full fetch-and-store flow."""
        # Create mocked client
        client = KeepaClient(keepa_config)
        client.get_product = AsyncMock(return_value=mock_product_response)  # type: ignore[method-assign]

        # Create service with real repository
        repo = KeepaRepository(db_session)
        service = KeepaService(client, repo)

        # Execute
        result = await service.fetch_and_store_product("B0TESTINT", store_in_db=True)

        # Verify response
        assert result.asin == "B0TESTINT"
        assert result.title == "Integration Test Product"
        assert result.current_price == Decimal("29.99")

        # Verify data was stored in DB
        product = await repo.upsert_product(mock_product_response)
        assert product.asin == "B0TESTINT"

        await client.close()

    @pytest.mark.asyncio
    async def test_fetch_and_store_batch(
        self,
        db_session: AsyncSession,
        keepa_config: KeepaConfig,
    ) -> None:
        """Test batch fetch and store."""
        client = KeepaClient(keepa_config)

        async def mock_get_product(req: Any) -> KeepaProductResponse:
            return KeepaProductResponse(
                asin=req.asin,
                title=f"Product {req.asin}",
                reviews=KeepaReviewData(),
                sales_estimates=KeepaSalesEstimate(),
            )

        client.get_product = mock_get_product  # type: ignore[method-assign]

        repo = KeepaRepository(db_session)
        service = KeepaService(client, repo)

        results = await service.fetch_and_store_batch(["B0TESTASIN", "B0TESTAS02"])

        assert len(results) == 2
        assert results[0].asin == "B0TESTASIN"
        assert results[1].asin == "B0TESTAS02"

        await client.close()

    @pytest.mark.asyncio
    async def test_lookup_product_by_asin(
        self,
        db_session: AsyncSession,
        keepa_config: KeepaConfig,
        mock_product_response: KeepaProductResponse,
    ) -> None:
        """Test product lookup by ASIN."""
        client = KeepaClient(keepa_config)
        client.get_product = AsyncMock(return_value=mock_product_response)  # type: ignore[method-assign]

        repo = KeepaRepository(db_session)
        service = KeepaService(client, repo)

        result = await service.lookup_product_by_asin("B0TESTINT")
        assert result is not None
        assert result.asin == "B0TESTINT"

        await client.close()

    @pytest.mark.asyncio
    async def test_lookup_product_not_found(
        self,
        db_session: AsyncSession,
        keepa_config: KeepaConfig,
    ) -> None:
        """Test product lookup when API fails."""
        client = KeepaClient(keepa_config)
        client.get_product = AsyncMock(side_effect=Exception("API error"))  # type: ignore[method-assign]

        repo = KeepaRepository(db_session)
        service = KeepaService(client, repo)

        result = await service.lookup_product_by_asin("B0INVALID")
        assert result is None

        await client.close()
