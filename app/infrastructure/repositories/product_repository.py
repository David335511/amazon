"""Product repository with domain-specific queries.

Updated for the sourcing platform: uses ASIN as the primary identifier
instead of SKU, and title/asin for search instead of name/sku.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.product import Product
from app.infrastructure.repositories.base import BaseRepository


class ProductRepository(BaseRepository[Product]):
    """Repository for Product entity operations."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Product)

    async def find_by_asin(self, asin: str) -> Product | None:
        """Find a product by its Amazon ASIN."""
        query = select(Product).where(Product.asin == asin)
        result = await self._session.execute(query)
        return result.scalar_one_or_none()

    async def find_by_upc(self, upc: str) -> Product | None:
        """Find a product by its UPC."""
        query = select(Product).where(Product.upc == upc)
        result = await self._session.execute(query)
        return result.scalar_one_or_none()

    async def find_by_category_id(
        self,
        category_id: str,
        *,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[Sequence[Product], int]:
        """Find products by category ID with pagination."""
        return await self.get_many(
            skip=skip,
            limit=limit,
            filters={"category_id": category_id, "is_active": True},
        )

    async def search(
        self,
        query: str,
        *,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[Sequence[Product], int]:
        """Search products by title or description (case-insensitive)."""
        search_pattern = f"%{query}%"
        stmt = (
            select(Product)
            .where(
                Product.title.ilike(search_pattern)
                | Product.description.ilike(search_pattern),
            )
            .offset(skip)
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        items = result.scalars().all()

        # Count total matches
        count_stmt = select(Product).where(
            Product.title.ilike(search_pattern)
            | Product.description.ilike(search_pattern),
        )
        count_result = await self._session.execute(count_stmt)
        total = len(count_result.scalars().all())

        return items, total

    async def get_active_products(
        self,
        *,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[Sequence[Product], int]:
        """Get all active products with pagination."""
        return await self.get_many(
            skip=skip,
            limit=limit,
            filters={"is_active": True},
            order_by="title",
        )

    async def find_by_brand(
        self,
        brand_id: str,
        *,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[Sequence[Product], int]:
        """Find products by brand."""
        return await self.get_many(
            skip=skip,
            limit=limit,
            filters={"brand_id": brand_id, "is_active": True},
        )
