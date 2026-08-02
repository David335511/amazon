"""Integration tests for the product sourcing API endpoints.

Tests the full HTTP layer: request validation, response formatting,
error handling, and pagination. Uses mocked service layer.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.domain.schemas.product_sourcing import (
    BSRHistoryDTO,
    BuyBoxDTO,
    ProductDetailDTO,
    ProductPricingDTO,
    ProductSummaryDTO,
    RefreshResponse,
    ReviewSummaryDTO,
    SalesEstimateDTO,
    SellerCountDTO,
    SellerCountHistoryDTO,
)
from app.domain.services.product_sourcing_service import ProductSourcingService
from app.main import create_app


# ── Fixtures ────────────────────────────────────────────────


@pytest.fixture
def sample_product_id() -> UUID:
    return UUID("c0000001-0000-0000-0000-000000000001")


@pytest.fixture
def mock_detail_dto(sample_product_id: UUID) -> ProductDetailDTO:
    """Create a sample product detail DTO."""
    now = __import__("datetime").datetime.now()
    return ProductDetailDTO(
        id=sample_product_id,
        asin="B0TESTASIN",
        title="Test Product",
        description="A test product",
        upc="123456789012",
        main_image_url="https://example.com/image.jpg",
        dimensions="10x8x5 inches",
        weight=Decimal("1.50"),
        weight_unit="pounds",
        price=Decimal("29.99"),
        buy_box_price=Decimal("28.99"),
        is_active=True,
        is_amazon_fba=True,
        is_amazon_brand=False,
        latest_reviews=ReviewSummaryDTO(
            rating=Decimal("4.5"),
            review_count=1234,
            answered_questions=56,
        ),
        latest_sales_estimate=SalesEstimateDTO(
            estimated_monthly_sales=1500,
            estimated_daily_sales=Decimal("50.00"),
            sales_rank=500,
        ),
        latest_seller_count=SellerCountDTO(
            new_seller_count=12,
            used_seller_count=5,
            fba_seller_count=8,
        ),
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
def mock_pricing_dto(sample_product_id: UUID) -> ProductPricingDTO:
    """Create a sample pricing DTO."""
    return ProductPricingDTO(
        product_id=sample_product_id,
        asin="B0TESTASIN",
        current_price=Decimal("29.99"),
        current_buy_box=Decimal("28.99"),
        price_range_min=Decimal("25.00"),
        price_range_max=Decimal("35.00"),
    )


@pytest.fixture
def mock_bsr_dto(sample_product_id: UUID) -> BSRHistoryDTO:
    """Create a sample BSR DTO."""
    return BSRHistoryDTO(
        product_id=sample_product_id,
        asin="B0TESTASIN",
        current_rank=500,
    )


@pytest.fixture
def mock_buybox_dto(sample_product_id: UUID) -> BuyBoxDTO:
    """Create a sample Buy Box DTO."""
    return BuyBoxDTO(
        product_id=sample_product_id,
        asin="B0TESTASIN",
        current_buy_box_price=Decimal("28.99"),
        is_amazon_fulfilled=True,
    )


@pytest.fixture
def mock_seller_count_dto(sample_product_id: UUID) -> SellerCountHistoryDTO:
    """Create a sample seller count DTO."""
    return SellerCountHistoryDTO(
        product_id=sample_product_id,
        asin="B0TESTASIN",
        current_new_count=12,
        current_fba_count=8,
    )


# ── API Tests ───────────────────────────────────────────────


class TestProductSourcingAPI:
    """Test the product sourcing API endpoints with mocked service."""

    @pytest.fixture
    def app_with_mock(
        self,
        mock_detail_dto: ProductDetailDTO,
        mock_pricing_dto: ProductPricingDTO,
        mock_bsr_dto: BSRHistoryDTO,
        mock_buybox_dto: BuyBoxDTO,
        mock_seller_count_dto: SellerCountHistoryDTO,
    ) -> FastAPI:
        """Create a FastAPI app with mocked sourcing service."""
        app = create_app()
        test_product_id = UUID("c0000001-0000-0000-0000-000000000001")

        # Create mock service
        mock_service = AsyncMock(spec=ProductSourcingService)
        mock_service.search_by_asin = AsyncMock(return_value=mock_detail_dto)
        mock_service.search_by_upc = AsyncMock(return_value=mock_detail_dto)
        mock_service.search_by_title = AsyncMock(return_value=([], 0))
        mock_service.get_product_detail = AsyncMock(return_value=mock_detail_dto)
        mock_service.get_pricing_history = AsyncMock(return_value=mock_pricing_dto)
        mock_service.get_bsr_history = AsyncMock(return_value=mock_bsr_dto)
        mock_service.get_buy_box = AsyncMock(return_value=mock_buybox_dto)
        mock_service.get_seller_counts = AsyncMock(return_value=mock_seller_count_dto)
        mock_service.refresh_product = AsyncMock(
            return_value=RefreshResponse(
                asin="B0TESTASIN",
                status="refresh_completed",
                message="OK",
                product_id=test_product_id,
            ),
        )

        # Override dependency
        from app.api.v1.products_sourcing import get_sourcing_service
        app.dependency_overrides[get_sourcing_service] = lambda: mock_service

        return app

    @pytest.fixture
    def client(self, app_with_mock: FastAPI) -> AsyncClient:
        """Create an HTTP client."""
        transport = ASGITransport(app=app_with_mock)
        return AsyncClient(transport=transport, base_url="http://test")

    @pytest.mark.asyncio
    async def test_search_by_asin_found(
        self,
        client: AsyncClient,
        sample_product_id: UUID,
    ) -> None:
        """Test searching by ASIN returns product details."""
        response = await client.get("/api/v1/products/search/asin/B0TESTASIN")
        assert response.status_code == 200
        data = response.json()
        assert data["asin"] == "B0TESTASIN"
        assert data["title"] == "Test Product"
        assert data["price"] == "29.99"

    @pytest.mark.asyncio
    async def test_search_by_upc_found(
        self,
        client: AsyncClient,
    ) -> None:
        """Test searching by UPC returns product details."""
        response = await client.get("/api/v1/products/search/upc/123456789012")
        assert response.status_code == 200
        data = response.json()
        assert data["upc"] == "123456789012"

    @pytest.mark.asyncio
    async def test_search_by_title(
        self,
        client: AsyncClient,
    ) -> None:
        """Test searching by title returns paginated results."""
        response = await client.get("/api/v1/products/search/title?q=test")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert data["query"] == "test"

    @pytest.mark.asyncio
    async def test_search_by_title_missing_query(
        self,
        client: AsyncClient,
    ) -> None:
        """Test that search requires a query parameter."""
        response = await client.get("/api/v1/products/search/title")
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_get_pricing_history(
        self,
        client: AsyncClient,
        sample_product_id: UUID,
    ) -> None:
        """Test getting pricing history."""
        response = await client.get(
            f"/api/v1/products/{sample_product_id}/pricing?days=90",
        )
        assert response.status_code == 200
        data = response.json()
        assert data["asin"] == "B0TESTASIN"
        assert data["current_price"] == "29.99"

    @pytest.mark.asyncio
    async def test_get_bsr_history(
        self,
        client: AsyncClient,
        sample_product_id: UUID,
    ) -> None:
        """Test getting BSR history."""
        response = await client.get(
            f"/api/v1/products/{sample_product_id}/bsr?days=90",
        )
        assert response.status_code == 200
        data = response.json()
        assert data["current_rank"] == 500

    @pytest.mark.asyncio
    async def test_get_buy_box(
        self,
        client: AsyncClient,
        sample_product_id: UUID,
    ) -> None:
        """Test getting Buy Box history."""
        response = await client.get(
            f"/api/v1/products/{sample_product_id}/buy-box?days=90",
        )
        assert response.status_code == 200
        data = response.json()
        assert data["current_buy_box_price"] == "28.99"

    @pytest.mark.asyncio
    async def test_get_seller_counts(
        self,
        client: AsyncClient,
        sample_product_id: UUID,
    ) -> None:
        """Test getting seller count history."""
        response = await client.get(
            f"/api/v1/products/{sample_product_id}/sellers?days=90",
        )
        assert response.status_code == 200
        data = response.json()
        assert data["current_new_count"] == 12
        assert data["current_fba_count"] == 8

    @pytest.mark.asyncio
    async def test_refresh_product(
        self,
        client: AsyncClient,
    ) -> None:
        """Test refreshing product data."""
        response = await client.post(
            "/api/v1/products/refresh",
            json={"asin": "B0TESTASIN", "domain": "com"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["asin"] == "B0TESTASIN"
        assert data["status"] == "refresh_completed"
