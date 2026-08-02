"""Tests for the historical analytics module.

Tests the repository, service, scheduler, and API endpoints.
Uses an in-memory SQLite database and mocked dependencies.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.repository import AnalyticsRepository
from app.analytics.schemas import (
    AnalyticsSnapshot,
    CollectionStatus,
    HistoricalSummary,
    MultiMetricSummary,
    PriceSnapshot,
    TimeSeriesPoint,
    TrendDirection,
)
from app.analytics.service import AnalyticsService
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
from app.main import create_app


# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def sample_product_id() -> UUID:
    return UUID("c0000001-0000-0000-0000-000000000001")


@pytest.fixture
def sample_product(sample_product_id: UUID, db_session: AsyncSession) -> Product:
    """Create a sample product in the database."""
    import uuid
    from app.domain.models.brand import Brand
    from app.domain.models.category import Category

    # Create brand
    brand = Brand(
        id=UUID("a0000001-0000-0000-0000-000000000001"),
        name="Test Brand",
        slug="test-brand",
        is_active=True,
    )
    db_session.add(brand)

    # Create category
    category = Category(
        id=UUID("b0000001-0000-0000-0000-000000000001"),
        name="Test Category",
        slug="test-category",
        level=0,
        is_active=True,
    )
    db_session.add(category)

    # Create product
    product = Product(
        id=sample_product_id,
        asin="B0TESTANALYTICS",
        title="Test Analytics Product",
        description="A product for analytics testing",
        upc="123456789012",
        price=Decimal("29.99"),
        is_active=True,
        is_amazon_fba=True,
        brand_id=UUID("a0000001-0000-0000-0000-000000000001"),
        category_id=UUID("b0000001-0000-0000-0000-000000000001"),
    )
    db_session.add(product)

    # Create some historical data
    now = datetime.now(timezone.utc)
    for i in range(10):
        ts = now - timedelta(days=i * 7)

        # Amazon prices
        db_session.add(AmazonPrice(
            id=uuid.uuid4(),
            product_id=sample_product_id,
            price=Decimal(f"{25 + i}.99"),
            currency="USD",
            condition="New",
            is_amazon_fulfilled=True,
            is_buy_box=(i % 2 == 0),
            is_prime=True,
            effective_date=ts,
        ))

        # Seller counts
        db_session.add(SellerCount(
            id=uuid.uuid4(),
            product_id=sample_product_id,
            new_seller_count=10 + i,
            used_seller_count=5,
            fba_seller_count=8,
            effective_date=ts,
        ))

        # Sales estimates (BSR)
        db_session.add(SalesEstimate(
            id=uuid.uuid4(),
            product_id=sample_product_id,
            estimated_monthly_sales=1000 + i * 100,
            estimated_daily_sales=Decimal(f"{33 + i}.33"),
            estimated_monthly_revenue=Decimal(f"{25000 + i * 2500}.00"),
            sales_rank=500 + i * 50,
            effective_date=ts,
        ))

        # Historical fees
        db_session.add(HistoricalFee(
            id=uuid.uuid4(),
            product_id=sample_product_id,
            referral_fee=Decimal("3.75"),
            fulfillment_fee=Decimal("4.50"),
            storage_fee=Decimal("0.15"),
            total_fees=Decimal("8.40"),
            effective_date=ts,
        ))

        # Profit calculations
        db_session.add(ProfitCalculation(
            id=uuid.uuid4(),
            product_id=sample_product_id,
            unit_cost=Decimal("11.80"),
            amazon_price=Decimal(f"{25 + i}.99"),
            referral_fee=Decimal("3.75"),
            fulfillment_fee=Decimal("4.50"),
            storage_fee=Decimal("0.15"),
            other_costs=Decimal("1.50"),
            total_cost=Decimal("21.70"),
            gross_profit=Decimal(f"{14 + i}.19"),
            net_profit=Decimal(f"{3 + i}.29"),
            margin_percentage=Decimal(f"{13 + i}.16"),
            roi_percentage=Decimal(f"{15 + i}.16"),
            effective_date=ts,
        ))

    # Historical inventory
    db_session.add(HistoricalInventory(
        id=uuid.uuid4(),
        product_id=sample_product_id,
        quantity_on_hand=500,
        quantity_reserved=23,
        quantity_inbound=1000,
        quantity_available=477,
        warehouse_location="A-12-B",
        effective_date=now,
    ))

    # Current inventory
    from app.domain.models.sourcing import Inventory as CurrentInventory
    db_session.add(CurrentInventory(
        id=uuid.uuid4(),
        product_id=sample_product_id,
        quantity_on_hand=500,
        quantity_reserved=23,
        quantity_inbound=1000,
        warehouse_location="A-12-B",
    ))

    return product


# ═══════════════════════════════════════════════════════════════
# Repository Tests
# ═══════════════════════════════════════════════════════════════


class TestAnalyticsRepository:
    """Test the analytics repository with an in-memory database."""

    @pytest.mark.asyncio
    async def test_get_amazon_price_series(
        self,
        db_session: AsyncSession,
        sample_product: Product,
    ) -> None:
        """Test retrieving Amazon price time-series."""
        repo = AnalyticsRepository(db_session)
        prices = await repo.get_amazon_price_series(sample_product.id, limit=5)
        assert len(prices) == 5
        assert all(p.product_id == sample_product.id for p in prices)
        # Should be ordered by effective_date DESC
        for i in range(len(prices) - 1):
            assert prices[i].effective_date >= prices[i + 1].effective_date

    @pytest.mark.asyncio
    async def test_get_amazon_price_series_with_since(
        self,
        db_session: AsyncSession,
        sample_product: Product,
    ) -> None:
        """Test filtering by date range."""
        repo = AnalyticsRepository(db_session)
        since = (datetime.now(timezone.utc) - timedelta(days=30)).replace(tzinfo=None)
        prices = await repo.get_amazon_price_series(
            sample_product.id, since=since,
        )
        assert all(p.effective_date >= since for p in prices)

    @pytest.mark.asyncio
    async def test_get_amazon_price_series_with_cursor(
        self,
        db_session: AsyncSession,
        sample_product: Product,
    ) -> None:
        """Test keyset pagination."""
        repo = AnalyticsRepository(db_session)
        # Get first page
        page1 = await repo.get_amazon_price_series(sample_product.id, limit=3)
        assert len(page1) == 3

        # Get next page using cursor
        cursor = page1[-1].effective_date
        page2 = await repo.get_amazon_price_series(
            sample_product.id, limit=3, cursor=cursor,
        )
        assert len(page2) >= 1
        # All page2 timestamps should be before the cursor
        assert all(p.effective_date < cursor for p in page2)

    @pytest.mark.asyncio
    async def test_get_seller_count_series(
        self,
        db_session: AsyncSession,
        sample_product: Product,
    ) -> None:
        """Test retrieving seller count time-series."""
        repo = AnalyticsRepository(db_session)
        counts = await repo.get_seller_count_series(sample_product.id)
        assert len(counts) == 10
        assert all(c.product_id == sample_product.id for c in counts)

    @pytest.mark.asyncio
    async def test_get_inventory_series(
        self,
        db_session: AsyncSession,
        sample_product: Product,
    ) -> None:
        """Test retrieving historical inventory time-series."""
        repo = AnalyticsRepository(db_session)
        inventory = await repo.get_inventory_series(sample_product.id)
        assert len(inventory) == 1
        assert inventory[0].quantity_on_hand == 500

    @pytest.mark.asyncio
    async def test_get_fee_series(
        self,
        db_session: AsyncSession,
        sample_product: Product,
    ) -> None:
        """Test retrieving fee time-series."""
        repo = AnalyticsRepository(db_session)
        fees = await repo.get_fee_series(sample_product.id)
        assert len(fees) == 10
        assert all(f.product_id == sample_product.id for f in fees)

    @pytest.mark.asyncio
    async def test_get_profit_series(
        self,
        db_session: AsyncSession,
        sample_product: Product,
    ) -> None:
        """Test retrieving profit time-series."""
        repo = AnalyticsRepository(db_session)
        profits = await repo.get_profit_series(sample_product.id)
        assert len(profits) == 10
        assert all(p.product_id == sample_product.id for p in profits)

    @pytest.mark.asyncio
    async def test_get_bsr_series(
        self,
        db_session: AsyncSession,
        sample_product: Product,
    ) -> None:
        """Test retrieving BSR time-series."""
        repo = AnalyticsRepository(db_session)
        bsr = await repo.get_bsr_series(sample_product.id)
        assert len(bsr) == 10
        assert all(b.product_id == sample_product.id for b in bsr)

    @pytest.mark.asyncio
    async def test_latest_snapshots(
        self,
        db_session: AsyncSession,
        sample_product: Product,
    ) -> None:
        """Test retrieving latest snapshots."""
        repo = AnalyticsRepository(db_session)

        # Latest Amazon price
        price = await repo.get_latest_amazon_price(sample_product.id)
        assert price is not None
        assert price.product_id == sample_product.id

        # Latest seller count
        sellers = await repo.get_latest_seller_count(sample_product.id)
        assert sellers is not None

        # Latest inventory
        inv = await repo.get_latest_inventory(sample_product.id)
        assert inv is not None
        assert inv.quantity_on_hand == 500

        # Latest fees
        fees = await repo.get_latest_fees(sample_product.id)
        assert fees is not None

        # Latest profit
        profit = await repo.get_latest_profit(sample_product.id)
        assert profit is not None

    @pytest.mark.asyncio
    async def test_count_data_points(
        self,
        db_session: AsyncSession,
        sample_product: Product,
    ) -> None:
        """Test counting data points."""
        repo = AnalyticsRepository(db_session)
        count = await repo.count_data_points(sample_product.id, "amazon_prices")
        assert count == 10

    @pytest.mark.asyncio
    async def test_get_active_products(
        self,
        db_session: AsyncSession,
        sample_product: Product,
    ) -> None:
        """Test listing active products."""
        repo = AnalyticsRepository(db_session)
        products = await repo.get_active_products(limit=10)
        assert len(products) >= 1
        assert products[0].is_active is True


# ═══════════════════════════════════════════════════════════════
# Service Tests
# ═══════════════════════════════════════════════════════════════


class TestAnalyticsService:
    """Test the analytics service with mocked repository."""

    @pytest.mark.asyncio
    async def test_collect_snapshot(
        self,
        db_session: AsyncSession,
        sample_product: Product,
    ) -> None:
        """Test collecting a complete analytics snapshot."""
        repo = AnalyticsRepository(db_session)
        service = AnalyticsService(repository=repo)

        snapshot = await service.collect_snapshot(sample_product.id)

        assert snapshot.product_id == sample_product.id
        assert snapshot.asin == "B0TESTANALYTICS"
        assert snapshot.status in (
            CollectionStatus.SUCCESS,
            CollectionStatus.PARTIAL,
        )

        # Should have price data
        if snapshot.prices:
            assert snapshot.prices.amazon_price is not None

        # Should have seller data
        if snapshot.sellers:
            assert snapshot.sellers.new_seller_count >= 0

        # Should have inventory data
        if snapshot.inventory:
            assert snapshot.inventory.quantity_on_hand >= 0

    @pytest.mark.asyncio
    async def test_collect_snapshot_not_found(self) -> None:
        """Test collecting snapshot for non-existent product."""
        repo = AsyncMock(spec=AnalyticsRepository)
        repo.get = AsyncMock(return_value=None)
        service = AnalyticsService(repository=repo)  # type: ignore[arg-type]

        fake_id = UUID("00000000-0000-0000-0000-000000000000")
        snapshot = await service.collect_snapshot(fake_id)

        assert snapshot.status == CollectionStatus.FAILED
        assert len(snapshot.errors) > 0

    @pytest.mark.asyncio
    async def test_get_time_series(
        self,
        db_session: AsyncSession,
        sample_product: Product,
    ) -> None:
        """Test retrieving time-series data."""
        repo = AnalyticsRepository(db_session)
        service = AnalyticsService(repository=repo)

        points, total = await service.get_time_series(
            sample_product.id, "amazon_price", limit=5,
        )

        assert len(points) == 5
        assert total >= 10
        assert all(isinstance(p, TimeSeriesPoint) for p in points)
        assert all(p.value > 0 for p in points)

    @pytest.mark.asyncio
    async def test_get_time_series_bsr(
        self,
        db_session: AsyncSession,
        sample_product: Product,
    ) -> None:
        """Test retrieving BSR time-series."""
        repo = AnalyticsRepository(db_session)
        service = AnalyticsService(repository=repo)

        points, total = await service.get_time_series(
            sample_product.id, "bsr", limit=5,
        )

        assert len(points) == 5
        assert all(p.value > 0 for p in points)

    @pytest.mark.asyncio
    async def test_get_time_series_invalid_metric(
        self,
        db_session: AsyncSession,
        sample_product: Product,
    ) -> None:
        """Test that invalid metric returns empty."""
        repo = AnalyticsRepository(db_session)
        service = AnalyticsService(repository=repo)

        points, total = await service.get_time_series(
            sample_product.id, "invalid_metric",
        )

        assert len(points) == 0
        assert total == 0

    @pytest.mark.asyncio
    async def test_compute_summary(
        self,
        db_session: AsyncSession,
        sample_product: Product,
    ) -> None:
        """Test computing summary statistics."""
        repo = AnalyticsRepository(db_session)
        service = AnalyticsService(repository=repo)

        summary = await service.compute_summary(
            sample_product.id, "amazon_price", days=365,
        )

        assert summary is not None
        assert summary.product_id == sample_product.id
        assert summary.metric == "amazon_price"
        assert summary.data_point_count == 10
        assert summary.min is not None
        assert summary.max is not None
        assert summary.mean is not None
        assert summary.median is not None
        assert summary.trend in (
            TrendDirection.UP, TrendDirection.DOWN,
            TrendDirection.FLAT, TrendDirection.INSUFFICIENT_DATA,
        )

    @pytest.mark.asyncio
    async def test_compute_summary_no_data(
        self,
        db_session: AsyncSession,
        sample_product: Product,
    ) -> None:
        """Test summary with no data returns empty summary."""
        repo = AnalyticsRepository(db_session)
        service = AnalyticsService(repository=repo)

        # Use a metric with no data
        summary = await service.compute_summary(
            sample_product.id, "supplier_price", days=365,
        )

        assert summary is not None
        assert summary.data_point_count == 0
        assert summary.trend == TrendDirection.INSUFFICIENT_DATA

    @pytest.mark.asyncio
    async def test_compute_multi_metric_summary(
        self,
        db_session: AsyncSession,
        sample_product: Product,
    ) -> None:
        """Test computing multi-metric summary."""
        repo = AnalyticsRepository(db_session)
        service = AnalyticsService(repository=repo)

        result = await service.compute_multi_metric_summary(
            sample_product.id,
            ["amazon_price", "net_profit", "bsr"],
            days=365,
        )

        assert isinstance(result, MultiMetricSummary)
        assert result.asin == "B0TESTANALYTICS"
        assert "amazon_price" in result.metrics
        assert "net_profit" in result.metrics
        assert "bsr" in result.metrics

    @pytest.mark.asyncio
    async def test_collect_batch(
        self,
        db_session: AsyncSession,
        sample_product: Product,
    ) -> None:
        """Test batch collection."""
        repo = AnalyticsRepository(db_session)
        service = AnalyticsService(repository=repo)

        result = await service.collect_batch(
            product_ids=[sample_product.id],
        )

        assert result.total_products == 1
        assert result.succeeded >= 0
        assert result.total_duration_ms > 0


# ═══════════════════════════════════════════════════════════════
# API Tests
# ═══════════════════════════════════════════════════════════════


class TestAnalyticsAPI:
    """Test the analytics API endpoints."""

    @pytest_asyncio.fixture
    async def analytics_client(
        self,
        test_app: FastAPI,
        db_session: AsyncSession,
    ) -> AsyncClient:
        """Create a client with analytics service overridden."""
        from app.analytics.repository import AnalyticsRepository
        from app.analytics.service import AnalyticsService
        from app.api.v1.analytics import get_analytics_service
        from app.core.database import get_db
        from app.core.redis import get_redis
        from unittest.mock import AsyncMock
        from httpx import ASGITransport, AsyncClient

        async def override_get_db() -> AsyncGenerator[AsyncSession, Any]:
            yield db_session

        mock_redis = AsyncMock()
        mock_redis.ping.return_value = True

        async def override_get_redis() -> AsyncGenerator[MagicMock, Any]:
            yield mock_redis

        # Override the analytics service to use our session
        repo = AnalyticsRepository(db_session)
        svc = AnalyticsService(repository=repo)

        test_app.dependency_overrides[get_db] = override_get_db
        test_app.dependency_overrides[get_redis] = override_get_redis
        test_app.dependency_overrides[get_analytics_service] = lambda: svc

        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

        test_app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_get_time_series_endpoint(
        self,
        analytics_client: AsyncClient,
        sample_product: Product,
    ) -> None:
        """Test the time-series API endpoint."""
        response = await analytics_client.get(
            f"/api/v1/analytics/products/{sample_product.id}/time-series/"
            f"amazon_price?days=365&limit=5",
        )
        assert response.status_code == 200
        data = response.json()
        assert data["product_id"] == str(sample_product.id)
        assert data["metric"] == "amazon_price"
        assert len(data["data_points"]) == 5
        assert data["total_points"] >= 10
        assert data["summary"] is not None

    @pytest.mark.asyncio
    async def test_get_time_series_invalid_metric(
        self,
        analytics_client: AsyncClient,
        sample_product: Product,
    ) -> None:
        """Test that invalid metric returns 422."""
        response = await analytics_client.get(
            f"/api/v1/analytics/products/{sample_product.id}/time-series/"
            f"invalid_metric?days=90",
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_get_time_series_not_found(
        self,
        analytics_client: AsyncClient,
    ) -> None:
        """Test that non-existent product returns 404."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = await analytics_client.get(
            f"/api/v1/analytics/products/{fake_id}/time-series/"
            f"amazon_price?days=90",
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_get_multi_metric_summary(
        self,
        analytics_client: AsyncClient,
        sample_product: Product,
    ) -> None:
        """Test the multi-metric summary endpoint."""
        response = await analytics_client.get(
            f"/api/v1/analytics/products/{sample_product.id}/summary?"
            f"metrics=amazon_price,net_profit,bsr&days=365",
        )
        assert response.status_code == 200
        data = response.json()
        assert data["asin"] == "B0TESTANALYTICS"
        assert "amazon_price" in data["metrics"]
        assert "net_profit" in data["metrics"]
        assert "bsr" in data["metrics"]

    @pytest.mark.asyncio
    async def test_get_single_metric_summary(
        self,
        analytics_client: AsyncClient,
        sample_product: Product,
    ) -> None:
        """Test the single metric summary endpoint."""
        response = await analytics_client.get(
            f"/api/v1/analytics/products/{sample_product.id}/summary/"
            f"amazon_price?days=365",
        )
        assert response.status_code == 200
        data = response.json()
        assert data["metric"] == "amazon_price"
        assert data["data_point_count"] == 10
        assert data["min"] is not None
        assert data["max"] is not None

    @pytest.mark.asyncio
    async def test_collect_snapshot_endpoint(
        self,
        analytics_client: AsyncClient,
        sample_product: Product,
    ) -> None:
        """Test the collect snapshot endpoint."""
        response = await analytics_client.post(
            f"/api/v1/analytics/products/{sample_product.id}/collect",
        )
        assert response.status_code == 200
        data = response.json()
        assert data["product_id"] == str(sample_product.id)
        assert data["asin"] == "B0TESTANALYTICS"
        assert data["status"] in ("success", "partial", "failed")

    @pytest.mark.asyncio
    async def test_collect_batch_endpoint(
        self,
        analytics_client: AsyncClient,
        sample_product: Product,
    ) -> None:
        """Test the batch collect endpoint."""
        response = await analytics_client.post(
            f"/api/v1/analytics/collect/batch?"
            f"product_ids={sample_product.id}&limit=10",
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total_products"] == 1

    @pytest.mark.asyncio
    async def test_get_data_coverage(
        self,
        analytics_client: AsyncClient,
        sample_product: Product,
    ) -> None:
        """Test the data coverage endpoint."""
        response = await analytics_client.get(
            f"/api/v1/analytics/products/{sample_product.id}/coverage",
        )
        assert response.status_code == 200
        data = response.json()
        assert data["asin"] == "B0TESTANALYTICS"
        assert "tables" in data
        assert "amazon_prices" in data["tables"]
        assert data["tables"]["amazon_prices"]["count"] >= 10

    @pytest.mark.asyncio
    async def test_list_metrics(
        self,
        analytics_client: AsyncClient,
    ) -> None:
        """Test the list metrics endpoint."""
        response = await analytics_client.get("/api/v1/analytics/metrics")
        assert response.status_code == 200
        data = response.json()
        assert "metrics" in data
        assert len(data["metrics"]) >= 15
        metric_names = [m["name"] for m in data["metrics"]]
        assert "amazon_price" in metric_names
        assert "net_profit" in metric_names
        assert "bsr" in metric_names
