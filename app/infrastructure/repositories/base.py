"""Base repository with common CRUD operations.

Design decisions:
- Generic repository pattern with type-safe CRUD methods.
- Uses SQLAlchemy 2.x `select()` and `execute()` patterns.
- All methods are async and accept/return domain models.
- Subclasses override for domain-specific queries.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any, TypeVar

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository[ModelT: Base]:
    """Generic repository with common database operations."""

    def __init__(self, session: AsyncSession, model: type[ModelT]) -> None:
        self._session = session
        self._model = model

    async def create(self, **kwargs: Any) -> ModelT:
        """Create a new entity."""
        instance = self._model(**kwargs)
        self._session.add(instance)
        await self._session.flush()
        await self._session.refresh(instance)
        return instance

    async def get(self, id: uuid.UUID) -> ModelT | None:
        """Get an entity by its UUID primary key."""
        return await self._session.get(self._model, id)

    async def get_many(
        self,
        *,
        skip: int = 0,
        limit: int = 100,
        filters: dict[str, Any] | None = None,
        order_by: str | None = None,
        descending: bool = False,
    ) -> tuple[Sequence[ModelT], int]:
        """Get a paginated list of entities with total count.

        Returns:
            Tuple of (items, total_count).
        """
        base_query = select(self._model)

        # Apply filters
        if filters:
            base_query = self._apply_filters(base_query, filters)

        # Get total count
        count_query = select(func.count()).select_from(base_query.subquery())
        total_result = await self._session.execute(count_query)
        total = total_result.scalar_one()

        # Apply ordering
        if order_by:
            order_col = getattr(self._model, order_by, None)
            if order_col is not None:
                base_query = base_query.order_by(
                    order_col.desc() if descending else order_col.asc(),
                )

        # Apply pagination
        base_query = base_query.offset(skip).limit(limit)

        result = await self._session.execute(base_query)
        items = result.scalars().all()

        return items, total

    async def update(self, id: uuid.UUID, **kwargs: Any) -> ModelT | None:
        """Update an entity by its UUID primary key.

        Only updates the fields provided in kwargs.
        """
        instance = await self.get(id)
        if instance is None:
            return None

        for key, value in kwargs.items():
            if value is not None and hasattr(instance, key):
                setattr(instance, key, value)

        await self._session.flush()
        await self._session.refresh(instance)
        return instance

    async def delete(self, id: uuid.UUID) -> bool:
        """Delete an entity by its UUID primary key.

        Returns True if deleted, False if not found.
        """
        instance = await self.get(id)
        if instance is None:
            return False

        await self._session.delete(instance)
        await self._session.flush()
        return True

    async def exists(self, **filters: Any) -> bool:
        """Check if any entity matches the given filters."""
        query = select(self._model).filter_by(**filters).limit(1)
        result = await self._session.execute(query)
        return result.scalar_one_or_none() is not None

    def _apply_filters(
        self,
        query: Select[tuple[ModelT]],
        filters: dict[str, Any],
    ) -> Select[tuple[ModelT]]:
        """Apply dictionary filters to a query."""
        for key, value in filters.items():
            if hasattr(self._model, key):
                column = getattr(self._model, key)
                if value is None:
                    query = query.where(column.is_(None))
                elif isinstance(value, (list, tuple)):
                    query = query.where(column.in_(value))
                else:
                    query = query.where(column == value)
        return query
