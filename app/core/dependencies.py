"""Dependency injection container and shared dependencies.

Design decisions:
- FastAPI's dependency injection system is used for all service/resolution.
- A `Container` class provides factory methods for services and repositories.
- This keeps wiring in one place and makes testing easy (override deps).
- The container is initialized at startup with the async session factory.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.logging import get_logger
from app.domain.services.order_service import OrderService
from app.domain.services.product_service import ProductService
from app.infrastructure.repositories.order_repository import OrderRepository
from app.infrastructure.repositories.product_repository import ProductRepository

logger = get_logger(__name__)


class Container:
    """Dependency injection container.

    Provides factory methods for creating services and repositories.
    Each factory receives its dependencies via constructor injection.
    """

    @staticmethod
    def product_repository(db: AsyncSession) -> ProductRepository:
        """Create a ProductRepository instance."""
        return ProductRepository(db)

    @staticmethod
    def order_repository(db: AsyncSession) -> OrderRepository:
        """Create an OrderRepository instance."""
        return OrderRepository(db)

    @staticmethod
    def product_service(repo: ProductRepository) -> ProductService:
        """Create a ProductService instance."""
        return ProductService(repo)

    @staticmethod
    def order_service(repo: OrderRepository) -> OrderService:
        """Create an OrderService instance."""
        return OrderService(repo)


# ──────────────────────────────────────────────────────────────
# Convenience dependencies
# ──────────────────────────────────────────────────────────────


async def get_product_service(
    db: AsyncSession = Depends(get_db),
) -> AsyncGenerator[ProductService, Any]:
    """Dependency that yields a ProductService with a DB session."""
    repo = ProductRepository(db)
    yield ProductService(repo)


async def get_order_service(
    db: AsyncSession = Depends(get_db),
) -> AsyncGenerator[OrderService, Any]:
    """Dependency that yields an OrderService with a DB session."""
    repo = OrderRepository(db)
    yield OrderService(repo)


def get_request_id(request: Request) -> str:
    """Extract or generate a request ID from the incoming request."""
    return request.headers.get("X-Request-Id", "")
