"""Persistence layer for the AI memory system.

Memory rows live in their own `memories` table, fully separate from product
data. The repository exposes the domain-specific queries the manager needs for
recall and lifecycle consolidation.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.repositories.base import BaseRepository
from app.memory.models import Memory, MemorySystem, MemoryType


class MemoryRepository(BaseRepository[Memory]):
    """Repository for the `memories` table."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Memory)

    # ── Queries ─────────────────────────────────────────────

    async def find_by_type(
        self,
        memory_type: MemoryType,
        *,
        user_id: str | None = None,
        limit: int = 100,
    ) -> list[Memory]:
        query = select(Memory).where(Memory.memory_type == memory_type.value)
        query = self._apply_user(query, user_id)
        query = query.order_by(desc(Memory.created_at)).limit(limit)
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def find_by_system(
        self,
        system: MemorySystem,
        *,
        user_id: str | None = None,
        limit: int = 100,
    ) -> list[Memory]:
        query = select(Memory).where(Memory.system == system.value)
        query = self._apply_user(query, user_id)
        query = query.order_by(desc(Memory.created_at)).limit(limit)
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def list_all(
        self,
        *,
        user_id: str | None = None,
        system: MemorySystem | None = None,
        memory_type: MemoryType | None = None,
        limit: int = 200,
    ) -> list[Memory]:
        query = select(Memory)
        query = self._apply_user(query, user_id)
        if system is not None:
            query = query.where(Memory.system == system.value)
        if memory_type is not None:
            query = query.where(Memory.memory_type == memory_type.value)
        query = query.order_by(desc(Memory.created_at)).limit(limit)
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def recall_keyword(
        self,
        query: str,
        *,
        memory_types: set[MemoryType] | None = None,
        systems: set[MemorySystem] | None = None,
        user_id: str | None = None,
        limit: int = 10,
    ) -> list[Memory]:
        """Recall by literal keyword match on title/content.

        Used as a fallback when embedding search is unavailable or disabled.
        """
        pattern = f"%{query}%"
        statement = select(Memory).where(
            or_(Memory.title.ilike(pattern), Memory.content.ilike(pattern)),
        )
        if memory_types:
            statement = statement.where(Memory.memory_type.in_([t.value for t in memory_types]))
        if systems:
            statement = statement.where(Memory.system.in_([s.value for s in systems]))
        statement = self._apply_user(statement, user_id)
        statement = statement.order_by(desc(Memory.importance), desc(Memory.created_at)).limit(limit)
        result = await self._session.execute(statement)
        return list(result.scalars().all())

    async def load_embeddings(
        self,
        *,
        memory_types: set[MemoryType] | None = None,
        systems: set[MemorySystem] | None = None,
        user_id: str | None = None,
    ) -> list[tuple[Any, list[float]]]:
        """Load ``(memory_id, embedding)`` pairs for vector search."""
        statement = select(Memory.id, Memory.embedding).where(Memory.embedding.is_not(None))
        if memory_types:
            statement = statement.where(Memory.memory_type.in_([t.value for t in memory_types]))
        if systems:
            statement = statement.where(Memory.system.in_([s.value for s in systems]))
        statement = self._apply_user(statement, user_id)
        result = await self._session.execute(statement)
        pairs: list[tuple[Any, list[float]]] = []
        for row in result.all():
            vector = Memory.decode_embedding(row[1])
            if vector:
                pairs.append((row[0], vector))
        return pairs

    async def get_many_by_ids(self, ids: list[Any]) -> list[Memory]:
        """Load full memory records by id (preserving order is not required)."""
        if not ids:
            return []
        result = await self._session.execute(select(Memory).where(Memory.id.in_(ids)))
        return list(result.scalars().all())

    # ── Lifecycle helpers ───────────────────────────────────

    async def list_expired(self) -> list[Memory]:
        """Short-term memories past their expiry."""
        now = datetime.now(UTC)
        result = await self._session.execute(
            select(Memory).where(
                Memory.expires_at.is_not(None),
                Memory.expires_at < now,
            ),
        )
        return list(result.scalars().all())

    async def list_promotable(self, threshold: float) -> list[Memory]:
        """Episodic/short-term memories with importance >= threshold."""
        result = await self._session.execute(
            select(Memory).where(
                Memory.system.in_([MemorySystem.EPISODIC.value, MemorySystem.SHORT_TERM.value]),
                Memory.importance >= threshold,
            ),
        )
        return list(result.scalars().all())

    async def list_decayable(self) -> list[Memory]:
        """Episodic memories that should have their importance decayed."""
        result = await self._session.execute(
            select(Memory).where(Memory.system == MemorySystem.EPISODIC.value),
        )
        return list(result.scalars().all())

    async def touch(self, memory: Memory) -> None:
        """Mark a memory as accessed (boost retrieval recency)."""
        memory.access_count += 1
        memory.last_accessed_at = datetime.now(UTC)
        await self._session.flush()

    async def counts(self) -> tuple[dict[str, int], dict[str, int]]:
        """Return (by_system, by_type) count maps."""
        sys_result = await self._session.execute(
            select(Memory.system, func.count()).group_by(Memory.system),
        )
        type_result = await self._session.execute(
            select(Memory.memory_type, func.count()).group_by(Memory.memory_type),
        )
        by_system = {row[0]: int(row[1]) for row in sys_result.all()}
        by_type = {row[0]: int(row[1]) for row in type_result.all()}
        return by_system, by_type

    async def total(self) -> int:
        result = await self._session.execute(select(func.count()).select_from(Memory))
        return int(result.scalar_one())

    async def delete_many(self, memories: Sequence[Memory]) -> int:
        """Delete several memories, returning the count removed."""
        for memory in memories:
            await self._session.delete(memory)
        await self._session.flush()
        return len(memories)

    def _apply_user(self, statement: Any, user_id: str | None) -> Any:
        """Optionally scope a query to a user. None = global memories only.

        Note: platform-global memories have user_id NULL. When a user is given,
        we match their rows plus global rows (so shared knowledge is always
        recallable).
        """
        if user_id is None:
            return statement.where(Memory.user_id.is_(None))
        return statement.where(
            or_(Memory.user_id == user_id, Memory.user_id.is_(None)),
        )
