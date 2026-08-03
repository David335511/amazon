"""Test configuration and fixtures.

Design decisions:
- Uses aiosqlite for an in-memory test database (fast, no external deps).
- Test settings override production settings for isolation.
- Fixtures create fresh database tables for each test function.
- Redis is mocked to avoid requiring a running Redis instance.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Import all models so they register with Base.metadata
from app.config import Settings
from app.core.database import get_db
from app.core.redis import get_redis
from app.documents.models import Document  # noqa: F401  (register documents table)
from app.domain.models.base import Base
from app.experiments.models import (  # noqa: F401  (register experiment tables)
    Assignment,
    Experiment,
    ExperimentReport,
    Observation,
    Variant,
)
from app.features.models import FeatureValue  # noqa: F401  (register feature store table)
from app.i18n.models import LanguagePreference  # noqa: F401  (register i18n preference table)
from app.finance.models import (  # noqa: F401  (register finance tables)
    CapitalAllocation,
    CashTransaction,
)
from app.forecasting.models import (  # noqa: F401  (register forecasting tables)
    Forecast,
    ForecastActual,
)
from app.knowledge_graph.models import (  # noqa: F401  (register knowledge-graph tables)
    GraphEdge,
    GraphNode,
)
from app.learning.models import (  # noqa: F401  (register learning tables)
    LearningPrediction,
    LearningRecommendation,
    LearningRun,
)
from app.main import create_app
from app.memory.models import Memory  # noqa: F401  (register memories table)
from app.multiagent.models import (  # noqa: F401  (register multi-agent tables)
    MultiAgentEvaluation,
    MultiAgentRun,
    MultiAgentTrace,
)
from app.reverse_sourcing.models import (  # noqa: F401  (register reverse-sourcing tables)
    ReverseSourcingOffer,
    ReverseSourcingRun,
)
from app.supplier_intel.models import (
    SupplierObservation,  # noqa: F401  (register supplier-intel table)
)


@pytest.fixture(scope="session")
def test_settings() -> Settings:
    """Load test settings."""
    return Settings.load("testing")


@pytest.fixture(scope="session")
def test_app() -> FastAPI:
    """Create a FastAPI application instance for testing."""
    return create_app()


@pytest_asyncio.fixture(scope="function")
async def db_session() -> AsyncGenerator[AsyncSession, Any]:
    """Create a fresh in-memory SQLite database for each test.

    Uses aiosqlite for fast, isolated test runs.
    """
    test_engine = create_async_engine(
        "sqlite+aiosqlite://",
        echo=False,
        connect_args={"check_same_thread": False},
    )

    # Create all tables
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Create session factory
    test_session_factory = async_sessionmaker(
        test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    # Create a session
    async with test_session_factory() as session:
        yield session

    # Clean up
    await test_engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def client(
    test_app: FastAPI,
    db_session: AsyncSession,
) -> AsyncGenerator[AsyncClient, Any]:
    """Create an HTTP client with overridden dependencies.

    Uses the in-memory database session and a mock Redis client.
    """

    async def override_get_db() -> AsyncGenerator[AsyncSession, Any]:
        yield db_session

    # Mock Redis
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


@pytest_asyncio.fixture(scope="function")
async def product_payload() -> dict[str, Any]:
    """Standard product creation payload."""
    return {
        "asin": "B0TEST001",
        "title": "Test Product",
        "description": "A test product for unit testing",
        "price": "29.99",
        "currency": "USD",
        "upc": "123456789012",
        "weight": "0.50",
        "weight_unit": "lbs",
    }


@pytest_asyncio.fixture(scope="function")
async def created_product(
    client: AsyncClient,
    product_payload: dict[str, Any],
) -> dict[str, Any]:
    """Create a product via the API and return the response data."""
    response = await client.post("/api/v1/products/", json=product_payload)
    assert response.status_code == 201
    return response.json()  # type: ignore[no-any-return]
