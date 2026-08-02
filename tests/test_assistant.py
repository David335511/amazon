"""Tests for the AI assistant — capability detection, retrieval, engine, and API.

Uses mocked LLM responses and an in-memory SQLite database.
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

from app.ai.base import LLMConfig, LLMProvider, LLMResponse
from app.assistant.engine import AssistantEngine, CAPABILITY_KEYWORDS
from app.assistant.models import (
    AssistantCapability,
    AssistantQuery,
    AssistantResponse,
    DataSource,
    RetrievedContext,
)
from app.assistant.retriever import AssistantRetriever
from app.domain.models.product import Product
from app.domain.models.sourcing import (
    AmazonPrice,
    HistoricalFee,
    HistoricalInventory,
    ProductPrice,
    ProfitCalculation,
    SalesEstimate,
    SellerCount,
    Supplier,
    SupplierProduct,
)


# ═══════════════════════════════════════════════════════════════
# Mock LLM Provider
# ═══════════════════════════════════════════════════════════════


class MockAssistantLLM(LLMProvider):
    """Mock LLM provider for assistant testing."""

    provider_name = "mock-assistant"

    def __init__(self) -> None:
        super().__init__()

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        config: LLMConfig | None = None,
    ) -> LLMResponse:
        return LLMResponse(
            content='{"answer": "This product is profitable because it has a strong margin of 15% and healthy sales volume of 1,500 units per month.", "confidence": "high", "structured_data": {"net_profit": 3.29, "roi": 15.16}}',
            model="mock-model",
            provider="mock-assistant",
            usage={"total_tokens": 150},
            finish_reason="stop",
            latency_ms=50.0,
        )

    async def is_available(self) -> bool:
        return True


# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def sample_product_id() -> UUID:
    return UUID("c0000001-0000-0000-0000-000000000001")


@pytest.fixture
def sample_product(sample_product_id: UUID, db_session: AsyncSession) -> Product:
    """Create a sample product with rich data for assistant testing."""
    from app.domain.models.brand import Brand
    from app.domain.models.category import Category

    brand = Brand(id=UUID("a0000001-0000-0000-0000-000000000001"), name="Test Brand", slug="test-brand", is_active=True)
    db_session.add(brand)
    category = Category(id=UUID("b0000001-0000-0000-0000-000000000001"), name="Test Category", slug="test-category", level=0, is_active=True)
    db_session.add(category)

    product = Product(
        id=sample_product_id, asin="B0ASSISTANT", title="Test Assistant Product",
        description="A product for assistant testing", upc="123456789012",
        price=Decimal("24.99"), is_active=True, is_amazon_fba=True,
        brand_id=brand.id, category_id=category.id,
    )
    db_session.add(product)

    now = datetime.now(timezone.utc).replace(tzinfo=None)

    # Amazon prices
    for i in range(10):
        db_session.add(AmazonPrice(
            id=uuid4(), product_id=sample_product_id,
            price=Decimal("24.99"), currency="USD", condition="New",
            is_amazon_fulfilled=True, is_buy_box=(i < 7), is_prime=True,
            effective_date=now - timedelta(days=i * 7),
        ))

    # Supplier prices
    db_session.add(ProductPrice(id=uuid4(), product_id=sample_product_id, price=Decimal("11.80"), currency="USD", source="supplier", effective_date=now))

    # Seller counts
    db_session.add(SellerCount(id=uuid4(), product_id=sample_product_id, new_seller_count=8, used_seller_count=3, fba_seller_count=5, effective_date=now))

    # Sales estimates
    db_session.add(SalesEstimate(id=uuid4(), product_id=sample_product_id, estimated_monthly_sales=1500, estimated_daily_sales=Decimal("50.00"), estimated_monthly_revenue=Decimal("37485.00"), sales_rank=1250, effective_date=now))

    # Fees
    db_session.add(HistoricalFee(id=uuid4(), product_id=sample_product_id, referral_fee=Decimal("3.75"), fulfillment_fee=Decimal("4.50"), storage_fee=Decimal("0.15"), total_fees=Decimal("8.40"), effective_date=now))

    # Inventory
    db_session.add(HistoricalInventory(id=uuid4(), product_id=sample_product_id, quantity_on_hand=500, quantity_reserved=23, quantity_inbound=1000, quantity_available=477, effective_date=now))

    # Profit calculation
    db_session.add(ProfitCalculation(id=uuid4(), product_id=sample_product_id, unit_cost=Decimal("11.80"), amazon_price=Decimal("24.99"), referral_fee=Decimal("3.75"), fulfillment_fee=Decimal("4.50"), storage_fee=Decimal("0.15"), other_costs=Decimal("1.50"), total_cost=Decimal("21.70"), gross_profit=Decimal("13.19"), net_profit=Decimal("3.29"), margin_percentage=Decimal("13.16"), roi_percentage=Decimal("15.16"), effective_date=now))

    # Supplier
    supplier = Supplier(id=UUID("d0000001-0000-0000-0000-000000000001"), name="Test Supplier", is_active=True, rating=Decimal("4.5"))
    db_session.add(supplier)
    db_session.add(SupplierProduct(id=uuid4(), product_id=sample_product_id, supplier_id=supplier.id, supplier_sku="TST-001", supplier_price=Decimal("11.80"), moq=100, lead_time_days=15, is_active=True))

    return product


# ═══════════════════════════════════════════════════════════════
# Capability Detection Tests
# ═══════════════════════════════════════════════════════════════


class TestCapabilityDetection:
    """Test auto-detection of capabilities from questions."""

    def test_detect_why_profitable(self) -> None:
        engine = AssistantEngine(db=AsyncMock())  # type: ignore[arg-type]
        assert engine._detect_capability("Why is this product profitable?") == AssistantCapability.WHY_PROFITABLE
        assert engine._detect_capability("What makes this ASIN profitable?") == AssistantCapability.WHY_PROFITABLE

    def test_detect_find_similar(self) -> None:
        engine = AssistantEngine(db=AsyncMock())  # type: ignore[arg-type]
        assert engine._detect_capability("Find similar products") == AssistantCapability.FIND_SIMILAR
        assert engine._detect_capability("Show me alternatives like this") == AssistantCapability.FIND_SIMILAR

    def test_detect_predict_sale(self) -> None:
        engine = AssistantEngine(db=AsyncMock())  # type: ignore[arg-type]
        assert engine._detect_capability("Predict next month's sales") == AssistantCapability.PREDICT_NEXT_SALE
        assert engine._detect_capability("Sales forecast for B0TEST") == AssistantCapability.PREDICT_NEXT_SALE

    def test_detect_future_roi(self) -> None:
        engine = AssistantEngine(db=AsyncMock())  # type: ignore[arg-type]
        assert engine._detect_capability("What will the ROI be next quarter?") == AssistantCapability.ESTIMATE_FUTURE_ROI
        assert engine._detect_capability("Estimate future ROI") == AssistantCapability.ESTIMATE_FUTURE_ROI

    def test_detect_summarize(self) -> None:
        engine = AssistantEngine(db=AsyncMock())  # type: ignore[arg-type]
        assert engine._detect_capability("What are today's best opportunities?") == AssistantCapability.SUMMARIZE_OPPORTUNITIES
        assert engine._detect_capability("Summarize top products to buy") == AssistantCapability.SUMMARIZE_OPPORTUNITIES

    def test_detect_replacement_supplier(self) -> None:
        engine = AssistantEngine(db=AsyncMock())  # type: ignore[arg-type]
        assert engine._detect_capability("Find a replacement supplier") == AssistantCapability.FIND_REPLACEMENT_SUPPLIERS
        assert engine._detect_capability("Are there cheaper suppliers?") == AssistantCapability.FIND_REPLACEMENT_SUPPLIERS

    def test_detect_buy_inventory(self) -> None:
        engine = AssistantEngine(db=AsyncMock())  # type: ignore[arg-type]
        assert engine._detect_capability("Should I buy more inventory?") == AssistantCapability.BUY_MORE_INVENTORY
        assert engine._detect_capability("When should I reorder?") == AssistantCapability.BUY_MORE_INVENTORY

    def test_detect_purchase_order(self) -> None:
        engine = AssistantEngine(db=AsyncMock())  # type: ignore[arg-type]
        assert engine._detect_capability("Generate a purchase order") == AssistantCapability.GENERATE_PURCHASE_ORDER
        assert engine._detect_capability("Create a PO for this product") == AssistantCapability.GENERATE_PURCHASE_ORDER

    def test_detect_explain_calculation(self) -> None:
        engine = AssistantEngine(db=AsyncMock())  # type: ignore[arg-type]
        assert engine._detect_capability("How was the ROI calculated?") == AssistantCapability.EXPLAIN_CALCULATION
        assert engine._detect_capability("Explain the profit calculation") == AssistantCapability.EXPLAIN_CALCULATION

    def test_detect_general_query(self) -> None:
        engine = AssistantEngine(db=AsyncMock())  # type: ignore[arg-type]
        assert engine._detect_capability("Tell me about this product") == AssistantCapability.GENERAL_QUERY
        assert engine._detect_capability("What data do you have?") == AssistantCapability.GENERAL_QUERY


# ═══════════════════════════════════════════════════════════════
# Retriever Tests
# ═══════════════════════════════════════════════════════════════


class TestAssistantRetriever:
    """Test the data retrieval layer."""

    @pytest.mark.asyncio
    async def test_get_product(self, db_session: AsyncSession, sample_product: Product) -> None:
        retriever = AssistantRetriever(db=db_session)
        ctx = await retriever.get_product(product_id=sample_product.id)
        assert ctx is not None
        assert ctx.source == DataSource.PRODUCT_DATABASE
        assert "B0ASSISTANT" in ctx.summary

    @pytest.mark.asyncio
    async def test_get_product_by_asin(self, db_session: AsyncSession, sample_product: Product) -> None:
        retriever = AssistantRetriever(db=db_session)
        ctx = await retriever.get_product(asin="B0ASSISTANT")
        assert ctx is not None
        assert ctx.data.get("asin") == "B0ASSISTANT"

    @pytest.mark.asyncio
    async def test_get_profit_data(self, db_session: AsyncSession, sample_product: Product) -> None:
        retriever = AssistantRetriever(db=db_session)
        contexts = await retriever.get_profit_data(sample_product.id)
        assert len(contexts) >= 3  # price, supplier, fees, profit
        sources = [c.source for c in contexts]
        assert DataSource.AMAZON_PRICES in sources
        assert DataSource.HISTORICAL_FEES in sources

    @pytest.mark.asyncio
    async def test_get_sales_data(self, db_session: AsyncSession, sample_product: Product) -> None:
        retriever = AssistantRetriever(db=db_session)
        contexts = await retriever.get_sales_data(sample_product.id)
        assert len(contexts) >= 1
        assert any(c.source == DataSource.SALES_ESTIMATES for c in contexts)

    @pytest.mark.asyncio
    async def test_get_competition_data(self, db_session: AsyncSession, sample_product: Product) -> None:
        retriever = AssistantRetriever(db=db_session)
        contexts = await retriever.get_competition_data(sample_product.id)
        assert len(contexts) >= 1
        assert contexts[0].source == DataSource.SELLER_COUNTS

    @pytest.mark.asyncio
    async def test_get_inventory_data(self, db_session: AsyncSession, sample_product: Product) -> None:
        retriever = AssistantRetriever(db=db_session)
        contexts = await retriever.get_inventory_data(sample_product.id)
        assert len(contexts) >= 1
        assert contexts[0].source == DataSource.HISTORICAL_INVENTORY

    @pytest.mark.asyncio
    async def test_get_suppliers_for_product(self, db_session: AsyncSession, sample_product: Product) -> None:
        retriever = AssistantRetriever(db=db_session)
        contexts = await retriever.get_suppliers_for_product(sample_product.id)
        assert len(contexts) >= 1
        assert contexts[0].source == DataSource.SUPPLIER_DATABASE

    @pytest.mark.asyncio
    async def test_find_similar_products(self, db_session: AsyncSession, sample_product: Product) -> None:
        retriever = AssistantRetriever(db=db_session)
        contexts = await retriever.find_similar_products(sample_product.id)
        # May be empty if no similar products exist
        assert isinstance(contexts, list)

    @pytest.mark.asyncio
    async def test_get_recent_opportunities(self, db_session: AsyncSession, sample_product: Product) -> None:
        retriever = AssistantRetriever(db=db_session)
        contexts = await retriever.get_recent_opportunities(days=30)
        assert len(contexts) >= 1


# ═══════════════════════════════════════════════════════════════
# Engine Tests
# ═══════════════════════════════════════════════════════════════


class TestAssistantEngine:
    """Test the assistant engine with mock LLM."""

    @pytest.mark.asyncio
    async def test_answer_with_llm(self, db_session: AsyncSession, sample_product: Product) -> None:
        """Test answering with a mock LLM provider."""
        llm = MockAssistantLLM()
        engine = AssistantEngine(db=db_session, llm_provider=llm)

        query = AssistantQuery(
            question="Why is this product profitable?",
            product_id=sample_product.id,
        )
        response = await engine.answer(query)

        assert isinstance(response, AssistantResponse)
        assert response.answer is not None
        assert "profitable" in response.answer.lower()
        assert response.capability == AssistantCapability.WHY_PROFITABLE
        assert response.provider_used == "mock-assistant"
        assert len(response.contexts) > 0

    @pytest.mark.asyncio
    async def test_answer_without_llm(self, db_session: AsyncSession, sample_product: Product) -> None:
        """Test fallback when no LLM provider is available."""
        engine = AssistantEngine(db=db_session, llm_provider=None)

        query = AssistantQuery(
            question="Why is this profitable?",
            product_id=sample_product.id,
        )
        response = await engine.answer(query)

        assert isinstance(response, AssistantResponse)
        assert response.provider_used == "fallback"
        assert response.confidence == "low"
        assert len(response.contexts) > 0

    @pytest.mark.asyncio
    async def test_answer_with_asin(self, db_session: AsyncSession, sample_product: Product) -> None:
        """Test answering with an ASIN instead of product_id."""
        engine = AssistantEngine(db=db_session, llm_provider=None)

        query = AssistantQuery(
            question="Find similar products",
            asin="B0ASSISTANT",
        )
        response = await engine.answer(query)

        assert isinstance(response, AssistantResponse)
        assert response.capability == AssistantCapability.FIND_SIMILAR

    @pytest.mark.asyncio
    async def test_answer_no_product(self, db_session: AsyncSession) -> None:
        """Test answering without a product reference."""
        engine = AssistantEngine(db=db_session, llm_provider=None)

        query = AssistantQuery(
            question="Summarize today's opportunities",
        )
        response = await engine.answer(query)

        assert isinstance(response, AssistantResponse)
        assert response.capability == AssistantCapability.SUMMARIZE_OPPORTUNITIES

    @pytest.mark.asyncio
    async def test_answer_buy_inventory(self, db_session: AsyncSession, sample_product: Product) -> None:
        """Test inventory question."""
        engine = AssistantEngine(db=db_session, llm_provider=None)

        query = AssistantQuery(
            question="Should I buy more inventory?",
            product_id=sample_product.id,
        )
        response = await engine.answer(query)

        assert isinstance(response, AssistantResponse)
        assert response.capability == AssistantCapability.BUY_MORE_INVENTORY

    @pytest.mark.asyncio
    async def test_answer_purchase_order(self, db_session: AsyncSession, sample_product: Product) -> None:
        """Test purchase order question."""
        engine = AssistantEngine(db=db_session, llm_provider=None)

        query = AssistantQuery(
            question="Generate a purchase order for 100 units",
            product_id=sample_product.id,
            quantity=100,
        )
        response = await engine.answer(query)

        assert isinstance(response, AssistantResponse)
        assert response.capability == AssistantCapability.GENERATE_PURCHASE_ORDER


# ═══════════════════════════════════════════════════════════════
# API Tests
# ═══════════════════════════════════════════════════════════════


class TestAssistantAPI:
    """Test the assistant API endpoints."""

    @pytest_asyncio.fixture
    async def assistant_client(
        self,
        test_app: FastAPI,
        db_session: AsyncSession,
    ) -> AsyncClient:
        """Create a client with assistant dependencies."""
        from app.api.v1.assistant import router as assistant_router
        from app.core.database import get_db
        from app.core.redis import get_redis
        from unittest.mock import AsyncMock, MagicMock

        async def override_get_db() -> AsyncGenerator[AsyncSession, Any]:
            yield db_session

        mock_redis = AsyncMock()
        mock_redis.ping.return_value = True

        async def override_get_redis() -> AsyncGenerator[MagicMock, Any]:
            yield mock_redis

        test_app.dependency_overrides[get_db] = override_get_db
        test_app.dependency_overrides[get_redis] = override_get_redis

        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

        test_app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_ask_endpoint(
        self,
        assistant_client: AsyncClient,
        sample_product: Product,
    ) -> None:
        """Test the ask endpoint."""
        response = await assistant_client.post(
            "/api/v1/assistant/ask",
            json={
                "question": "Why is this product profitable?",
                "product_id": str(sample_product.id),
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "answer" in data
        assert "capability" in data
        assert "contexts" in data
        assert data["capability"] == "why_profitable"

    @pytest.mark.asyncio
    async def test_ask_with_asin(
        self,
        assistant_client: AsyncClient,
    ) -> None:
        """Test asking with an ASIN."""
        response = await assistant_client.post(
            "/api/v1/assistant/ask",
            json={
                "question": "Find similar products",
                "asin": "B0ASSISTANT",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["capability"] == "find_similar"

    @pytest.mark.asyncio
    async def test_ask_general(
        self,
        assistant_client: AsyncClient,
    ) -> None:
        """Test a general question."""
        response = await assistant_client.post(
            "/api/v1/assistant/ask",
            json={
                "question": "Summarize today's opportunities",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["capability"] == "summarize_opportunities"

    @pytest.mark.asyncio
    async def test_list_capabilities(
        self,
        assistant_client: AsyncClient,
    ) -> None:
        """Test listing capabilities."""
        response = await assistant_client.get("/api/v1/assistant/capabilities")
        assert response.status_code == 200
        data = response.json()
        assert "capabilities" in data
        assert data["total"] >= 9
