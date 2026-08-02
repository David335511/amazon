"""Tests for the sourcing engine — rules, scoring, and API endpoints.

Uses an in-memory SQLite database with sample product data.
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
from app.sourcing.engine import SourcingEngine
from app.sourcing.models import (
    ConfidenceLevel,
    OpportunityScore,
    ProductEvaluation,
    RiskLevel,
    RuleResult,
    RuleSeverity,
    SourcingConfig,
    SourcingResult,
    SourcingWeights,
)
from app.sourcing.rules import (
    BuyBoxStabilityRule,
    CompetitionRule,
    InventoryAvailabilityRule,
    MinimumProfitRule,
    MinimumRoiRule,
    MinimumSalesRule,
    PriceStabilityRule,
)


# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def sample_product_id() -> UUID:
    return UUID("c0000001-0000-0000-0000-000000000001")


@pytest.fixture
def sample_product(sample_product_id: UUID, db_session: AsyncSession) -> Product:
    """Create a sample product with rich historical data."""
    from app.domain.models.brand import Brand
    from app.domain.models.category import Category

    brand = Brand(
        id=UUID("a0000001-0000-0000-0000-000000000001"),
        name="Test Brand", slug="test-brand", is_active=True,
    )
    db_session.add(brand)
    category = Category(
        id=UUID("b0000001-0000-0000-0000-000000000001"),
        name="Test Category", slug="test-category", level=0, is_active=True,
    )
    db_session.add(category)

    product = Product(
        id=sample_product_id,
        asin="B0SOURCETEST",
        title="Test Sourcing Product",
        description="A product for sourcing engine testing",
        upc="123456789012",
        price=Decimal("29.99"),
        is_active=True,
        is_amazon_fba=True,
        brand_id=brand.id,
        category_id=category.id,
    )
    db_session.add(product)

    now = datetime.now(timezone.utc).replace(tzinfo=None)

    # Amazon prices (90 days of data, stable pricing)
    for i in range(13):
        ts = now - timedelta(days=i * 7)
        db_session.add(AmazonPrice(
            id=uuid4(), product_id=sample_product_id,
            price=Decimal("24.99"), currency="USD",
            condition="New", is_amazon_fulfilled=True,
            is_buy_box=(i < 10),  # ~77% win rate
            is_prime=True, effective_date=ts,
        ))

    # Supplier prices
    db_session.add(ProductPrice(
        id=uuid4(), product_id=sample_product_id,
        price=Decimal("11.80"), currency="USD",
        source="supplier", effective_date=now,
    ))
    db_session.add(ProductPrice(
        id=uuid4(), product_id=sample_product_id,
        price=Decimal("12.50"), currency="USD",
        source="supplier", effective_date=now - timedelta(days=30),
    ))

    # Seller counts (moderate competition)
    db_session.add(SellerCount(
        id=uuid4(), product_id=sample_product_id,
        new_seller_count=8, used_seller_count=3,
        fba_seller_count=5, effective_date=now,
    ))

    # Sales estimates (good volume)
    db_session.add(SalesEstimate(
        id=uuid4(), product_id=sample_product_id,
        estimated_monthly_sales=1500,
        estimated_daily_sales=Decimal("50.00"),
        estimated_monthly_revenue=Decimal("37485.00"),
        sales_rank=1250, effective_date=now,
    ))

    # Fees
    db_session.add(HistoricalFee(
        id=uuid4(), product_id=sample_product_id,
        referral_fee=Decimal("3.75"), fulfillment_fee=Decimal("4.50"),
        storage_fee=Decimal("0.15"), total_fees=Decimal("8.40"),
        effective_date=now,
    ))

    # Historical inventory
    db_session.add(HistoricalInventory(
        id=uuid4(), product_id=sample_product_id,
        quantity_on_hand=500, quantity_reserved=23,
        quantity_inbound=1000, quantity_available=477,
        warehouse_location="A-12-B", effective_date=now,
    ))

    # Current inventory
    from app.domain.models.sourcing import Inventory as CurrentInventory
    db_session.add(CurrentInventory(
        id=uuid4(), product_id=sample_product_id,
        quantity_on_hand=500, quantity_reserved=23,
        quantity_inbound=1000, warehouse_location="A-12-B",
    ))

    # Profit calculations
    db_session.add(ProfitCalculation(
        id=uuid4(), product_id=sample_product_id,
        unit_cost=Decimal("11.80"), amazon_price=Decimal("24.99"),
        referral_fee=Decimal("3.75"), fulfillment_fee=Decimal("4.50"),
        storage_fee=Decimal("0.15"), other_costs=Decimal("1.50"),
        total_cost=Decimal("21.70"), gross_profit=Decimal("13.19"),
        net_profit=Decimal("3.29"), margin_percentage=Decimal("13.16"),
        roi_percentage=Decimal("15.16"), effective_date=now,
    ))

    return product


# ═══════════════════════════════════════════════════════════════
# Rule Tests
# ═══════════════════════════════════════════════════════════════


class TestMinimumRoiRule:
    """Test the Minimum ROI rule."""

    @pytest.fixture
    def config(self) -> SourcingConfig:
        return SourcingConfig(
            min_roi_percentage=Decimal("20"),
            target_roi_percentage=Decimal("50"),
        )

    def test_above_target(self, config: SourcingConfig) -> None:
        """Test ROI above target scores 1.0."""
        rule = MinimumRoiRule()
        result = rule.evaluate(config, {"roi_percentage": Decimal("75")})
        assert result.score == Decimal("1.0")
        assert result.passed is True

    def test_above_minimum(self, config: SourcingConfig) -> None:
        """Test ROI between minimum and target."""
        rule = MinimumRoiRule()
        result = rule.evaluate(config, {"roi_percentage": Decimal("35")})
        assert Decimal("0.5") < result.score < Decimal("1.0")
        assert result.passed is True

    def test_at_minimum(self, config: SourcingConfig) -> None:
        """Test ROI at minimum scores 0.5."""
        rule = MinimumRoiRule()
        result = rule.evaluate(config, {"roi_percentage": Decimal("20")})
        assert result.score == Decimal("0.5")
        assert result.passed is True

    def test_below_minimum(self, config: SourcingConfig) -> None:
        """Test ROI below minimum scores < 0.5."""
        rule = MinimumRoiRule()
        result = rule.evaluate(config, {"roi_percentage": Decimal("10")})
        assert result.score < Decimal("0.5")
        assert result.passed is False

    def test_zero_roi(self, config: SourcingConfig) -> None:
        """Test zero ROI scores 0."""
        rule = MinimumRoiRule()
        result = rule.evaluate(config, {"roi_percentage": Decimal("0")})
        assert result.score == Decimal("0")
        assert result.passed is False

    def test_critical_failure(self, config: SourcingConfig) -> None:
        """Test that below-minimum ROI is a critical failure."""
        rule = MinimumRoiRule()
        result = rule.evaluate(config, {"roi_percentage": Decimal("5")})
        assert result.is_critical_failure is True
        assert result.severity == RuleSeverity.CRITICAL


class TestMinimumProfitRule:
    """Test the Minimum Profit rule."""

    @pytest.fixture
    def config(self) -> SourcingConfig:
        return SourcingConfig(
            min_net_profit=Decimal("2.00"),
            target_net_profit=Decimal("10.00"),
        )

    def test_above_target(self, config: SourcingConfig) -> None:
        rule = MinimumProfitRule()
        result = rule.evaluate(config, {"net_profit": Decimal("15.00")})
        assert result.score == Decimal("1.0")
        assert result.passed is True

    def test_at_minimum(self, config: SourcingConfig) -> None:
        rule = MinimumProfitRule()
        result = rule.evaluate(config, {"net_profit": Decimal("2.00")})
        assert result.score == Decimal("0.5")
        assert result.passed is True

    def test_below_minimum(self, config: SourcingConfig) -> None:
        rule = MinimumProfitRule()
        result = rule.evaluate(config, {"net_profit": Decimal("1.00")})
        assert result.score < Decimal("0.5")
        assert result.passed is False


class TestMinimumSalesRule:
    """Test the Minimum Sales rule."""

    @pytest.fixture
    def config(self) -> SourcingConfig:
        return SourcingConfig(
            min_monthly_sales=300,
            target_monthly_sales=2000,
        )

    def test_above_target(self, config: SourcingConfig) -> None:
        rule = MinimumSalesRule()
        result = rule.evaluate(config, {"estimated_monthly_sales": 3000, "net_profit": Decimal("3.00")})
        assert result.score == Decimal("1.0")
        assert result.passed is True

    def test_below_minimum(self, config: SourcingConfig) -> None:
        rule = MinimumSalesRule()
        result = rule.evaluate(config, {"estimated_monthly_sales": 100, "net_profit": Decimal("3.00")})
        assert result.score < Decimal("0.5")
        assert result.passed is False


class TestCompetitionRule:
    """Test the Competition rule."""

    @pytest.fixture
    def config(self) -> SourcingConfig:
        return SourcingConfig(
            min_new_sellers=1,
            target_new_sellers=5,
            max_new_sellers=20,
            max_fba_percentage=Decimal("70"),
        )

    def test_ideal_competition(self, config: SourcingConfig) -> None:
        rule = CompetitionRule()
        result = rule.evaluate(config, {
            "new_seller_count": 5, "fba_seller_count": 2, "total_offer_count": 8,
        })
        assert result.passed is True
        assert result.score >= Decimal("0.5")

    def test_too_many_sellers(self, config: SourcingConfig) -> None:
        rule = CompetitionRule()
        result = rule.evaluate(config, {
            "new_seller_count": 50, "fba_seller_count": 40, "total_offer_count": 60,
        })
        assert result.passed is False

    def test_high_fba(self, config: SourcingConfig) -> None:
        rule = CompetitionRule()
        result = rule.evaluate(config, {
            "new_seller_count": 5, "fba_seller_count": 5, "total_offer_count": 8,
        })
        # 100% FBA should fail
        assert result.passed is False


class TestBuyBoxStabilityRule:
    """Test the Buy Box Stability rule."""

    @pytest.fixture
    def config(self) -> SourcingConfig:
        return SourcingConfig(min_buy_box_win_rate=Decimal("60"))

    def test_high_win_rate(self, config: SourcingConfig) -> None:
        rule = BuyBoxStabilityRule()
        result = rule.evaluate(config, {"buy_box_win_rate": Decimal("90")})
        assert result.passed is True
        assert result.score >= Decimal("0.5")

    def test_low_win_rate(self, config: SourcingConfig) -> None:
        rule = BuyBoxStabilityRule()
        result = rule.evaluate(config, {"buy_box_win_rate": Decimal("30")})
        assert result.passed is False
        assert result.score < Decimal("0.5")


class TestPriceStabilityRule:
    """Test the Price Stability rule."""

    @pytest.fixture
    def config(self) -> SourcingConfig:
        return SourcingConfig(max_price_volatility=Decimal("15"))

    def test_stable_prices(self, config: SourcingConfig) -> None:
        rule = PriceStabilityRule()
        result = rule.evaluate(config, {"price_cv": Decimal("0.05")})
        assert result.passed is True

    def test_volatile_prices(self, config: SourcingConfig) -> None:
        rule = PriceStabilityRule()
        result = rule.evaluate(config, {"price_cv": Decimal("0.30")})
        assert result.passed is False


class TestInventoryAvailabilityRule:
    """Test the Inventory Availability rule."""

    @pytest.fixture
    def config(self) -> SourcingConfig:
        return SourcingConfig(min_days_of_stock=30)

    def test_well_stocked(self, config: SourcingConfig) -> None:
        rule = InventoryAvailabilityRule()
        result = rule.evaluate(config, {
            "days_of_stock": 60, "quantity_available": 500,
        })
        assert result.passed is True

    def test_low_stock(self, config: SourcingConfig) -> None:
        rule = InventoryAvailabilityRule()
        result = rule.evaluate(config, {
            "days_of_stock": 10, "quantity_available": 50,
        })
        assert result.passed is False


# ═══════════════════════════════════════════════════════════════
# Engine Tests
# ═══════════════════════════════════════════════════════════════


class TestSourcingEngine:
    """Test the full sourcing engine with real data."""

    @pytest.mark.asyncio
    async def test_evaluate_product(
        self,
        db_session: AsyncSession,
        sample_product: Product,
    ) -> None:
        """Test evaluating a single product."""
        repo = AnalyticsRepository(db_session)
        engine = SourcingEngine(repository=repo)

        evaluation = await engine.evaluate_product(sample_product.id, days=365)

        assert evaluation is not None
        assert evaluation.product_id == sample_product.id
        assert evaluation.asin == "B0SOURCETEST"
        assert evaluation.opportunity_score.total_score >= 0
        assert len(evaluation.opportunity_score.rule_results) == 7
        assert evaluation.confidence in ConfidenceLevel
        assert evaluation.risk_level in RiskLevel

    @pytest.mark.asyncio
    async def test_evaluate_products(
        self,
        db_session: AsyncSession,
        sample_product: Product,
    ) -> None:
        """Test evaluating multiple products."""
        repo = AnalyticsRepository(db_session)
        engine = SourcingEngine(repository=repo)

        result = await engine.evaluate_products([sample_product.id], days=365)

        assert isinstance(result, SourcingResult)
        assert result.total_evaluated == 1
        assert len(result.evaluations) == 1
        assert result.evaluations[0].asin == "B0SOURCETEST"

    @pytest.mark.asyncio
    async def test_evaluate_nonexistent_product(
        self,
        db_session: AsyncSession,
    ) -> None:
        """Test evaluating a non-existent product returns None."""
        repo = AnalyticsRepository(db_session)
        engine = SourcingEngine(repository=repo)

        fake_id = UUID("00000000-0000-0000-0000-000000000000")
        evaluation = await engine.evaluate_product(fake_id)
        assert evaluation is None

    @pytest.mark.asyncio
    async def test_opportunity_score_calculation(self) -> None:
        """Test the opportunity score calculation directly."""
        engine = SourcingEngine(repository=AsyncMock())  # type: ignore[arg-type]

        # Create mock rule results
        results = [
            RuleResult(
                rule_name="test", display_name="Test",
                severity=RuleSeverity.MINOR, weight=Decimal("0.5"),
                score=Decimal("1.0"), passed=True,
                summary="Perfect score",
            ),
            RuleResult(
                rule_name="test2", display_name="Test 2",
                severity=RuleSeverity.MINOR, weight=Decimal("0.5"),
                score=Decimal("0.5"), passed=True,
                summary="Half score",
            ),
        ]

        opportunity = engine._calculate_opportunity_score(results)
        # (1.0 * 0.5 + 0.5 * 0.5) / 1.0 = 0.75
        assert opportunity.weighted_score == Decimal("0.75")
        assert opportunity.total_score == Decimal("75.00")
        assert opportunity.is_viable is True

    @pytest.mark.asyncio
    async def test_critical_failure_rejects_product(self) -> None:
        """Test that a critical rule failure makes product non-viable."""
        engine = SourcingEngine(repository=AsyncMock())  # type: ignore[arg-type]

        results = [
            RuleResult(
                rule_name="critical_rule", display_name="Critical",
                severity=RuleSeverity.CRITICAL, weight=Decimal("0.5"),
                score=Decimal("0.1"), passed=False,
                is_critical_failure=True,
                summary="Failed critical rule",
            ),
            RuleResult(
                rule_name="other", display_name="Other",
                severity=RuleSeverity.MINOR, weight=Decimal("0.5"),
                score=Decimal("1.0"), passed=True,
                summary="Perfect",
            ),
        ]

        opportunity = engine._calculate_opportunity_score(results)
        assert opportunity.is_viable is False
        assert opportunity.critical_failures == 1

    @pytest.mark.asyncio
    async def test_confidence_levels(self) -> None:
        """Test confidence level determination."""
        engine = SourcingEngine(repository=AsyncMock())  # type: ignore[arg-type]

        assert engine._determine_confidence(1000) == ConfidenceLevel.VERY_HIGH
        assert engine._determine_confidence(300) == ConfidenceLevel.HIGH
        assert engine._determine_confidence(100) == ConfidenceLevel.MEDIUM
        assert engine._determine_confidence(30) == ConfidenceLevel.LOW
        assert engine._determine_confidence(5) == ConfidenceLevel.VERY_LOW

    @pytest.mark.asyncio
    async def test_risk_levels(self) -> None:
        """Test risk level determination."""
        engine = SourcingEngine(repository=AsyncMock())  # type: ignore[arg-type]

        # High score = low risk
        risk = engine._determine_risk(Decimal("90"), [])
        assert risk == RiskLevel.VERY_LOW

        # Low score = high risk
        risk = engine._determine_risk(Decimal("20"), [])
        assert risk == RiskLevel.VERY_HIGH

        # Critical failure = very high risk
        results = [
            RuleResult(
                rule_name="test", display_name="Test",
                severity=RuleSeverity.CRITICAL, weight=Decimal("1.0"),
                score=Decimal("0"), passed=False,
                is_critical_failure=True, summary="Failed",
            ),
        ]
        risk = engine._determine_risk(Decimal("80"), results)
        assert risk == RiskLevel.VERY_HIGH


# ═══════════════════════════════════════════════════════════════
# API Tests
# ═══════════════════════════════════════════════════════════════


class TestSourcingAPI:
    """Test the sourcing API endpoints."""

    @pytest_asyncio.fixture
    async def sourcing_client(
        self,
        test_app: FastAPI,
        db_session: AsyncSession,
    ) -> AsyncClient:
        """Create a client with sourcing engine overridden."""
        from app.api.v1.sourcing import get_sourcing_engine
        from app.core.database import get_db
        from app.core.redis import get_redis

        repo = AnalyticsRepository(db_session)
        engine = SourcingEngine(repository=repo)

        async def override_get_db() -> AsyncGenerator[AsyncSession, Any]:
            yield db_session

        mock_redis = AsyncMock()
        mock_redis.ping.return_value = True

        async def override_get_redis() -> AsyncGenerator[MagicMock, Any]:
            yield mock_redis

        test_app.dependency_overrides[get_db] = override_get_db
        test_app.dependency_overrides[get_redis] = override_get_redis
        test_app.dependency_overrides[get_sourcing_engine] = lambda: engine

        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

        test_app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_evaluate_product_endpoint(
        self,
        sourcing_client: AsyncClient,
        sample_product: Product,
    ) -> None:
        """Test the single product evaluation endpoint."""
        response = await sourcing_client.get(
            f"/api/v1/sourcing/evaluate/{sample_product.id}?days=365",
        )
        assert response.status_code == 200
        data = response.json()
        assert data["product_id"] == str(sample_product.id)
        assert data["asin"] == "B0SOURCETEST"
        assert "opportunity_score" in data
        assert "confidence" in data
        assert "risk_level" in data
        assert "strengths" in data
        assert "weaknesses" in data
        assert "recommendations" in data

        # Check opportunity score structure
        score = data["opportunity_score"]
        assert "total_score" in score
        assert "rule_results" in score
        assert len(score["rule_results"]) == 7

    @pytest.mark.asyncio
    async def test_evaluate_products_endpoint(
        self,
        sourcing_client: AsyncClient,
        sample_product: Product,
    ) -> None:
        """Test the batch evaluation endpoint."""
        response = await sourcing_client.post(
            f"/api/v1/sourcing/evaluate?product_ids={sample_product.id}&days=365",
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total_evaluated"] == 1
        assert len(data["evaluations"]) == 1
        assert data["evaluations"][0]["asin"] == "B0SOURCETEST"

    @pytest.mark.asyncio
    async def test_evaluate_nonexistent(
        self,
        sourcing_client: AsyncClient,
    ) -> None:
        """Test evaluating a non-existent product returns 404."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = await sourcing_client.get(
            f"/api/v1/sourcing/evaluate/{fake_id}?days=90",
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_get_default_config(
        self,
        sourcing_client: AsyncClient,
    ) -> None:
        """Test getting the default configuration."""
        response = await sourcing_client.get("/api/v1/sourcing/config")
        assert response.status_code == 200
        data = response.json()
        assert "weights" in data
        assert "min_roi_percentage" in data
        assert "min_net_profit" in data
        assert "min_monthly_sales" in data

    @pytest.mark.asyncio
    async def test_get_methodology(
        self,
        sourcing_client: AsyncClient,
    ) -> None:
        """Test getting the methodology documentation."""
        response = await sourcing_client.get("/api/v1/sourcing/methodology")
        assert response.status_code == 200
        data = response.json()
        assert data["version"] == "1.0.0"
        assert len(data["rules"]) == 7
        assert "scoring_formula" in data
        assert "viability_criteria" in data
