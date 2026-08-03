"""MemoryManager — the single entry point for the AI memory system.

The rest of the platform stores and retrieves memories ONLY through this
facade. It coordinates the persistence repository, the embedding provider, the
vector store, and the memory lifecycle (short-term expiry, consolidation of
important memories to long-term, importance decay of episodic memories).

Domain convenience methods (`record_successful_purchase`, `add_favorite_supplier`,
...) encode how each kind of knowledge is stored, so callers never deal with
raw memory plumbing.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from app.memory.config import MemoryConfig
from app.memory.embedding import EmbeddingProvider, build_embedding_provider
from app.memory.errors import MemoryEmbeddingError, MemoryNotFoundError
from app.memory.models import (
    Memory,
    MemorySystem,
    MemoryType,
    default_system_for,
)
from app.memory.repository import MemoryRepository
from app.memory.schemas import (
    ConsolidationReport,
    MemoryCreate,
    MemoryRead,
    MemoryRecallResult,
    MemoryStats,
)
from app.memory.vector import InMemoryVectorStore, VectorStore

# Default importance per memory type (drives retention/consolidation).
DEFAULT_IMPORTANCE: dict[MemoryType, float] = {
    MemoryType.PURCHASE_SUCCESS: 0.80,
    MemoryType.PURCHASE_FAILURE: 0.75,
    MemoryType.FALSE_POSITIVE: 0.60,
    MemoryType.FAVORITE_SUPPLIER: 0.85,
    MemoryType.FAVORITE_BRAND: 0.80,
    MemoryType.HIGH_PERFORMING_CATEGORY: 0.80,
    MemoryType.SEASONALITY: 0.70,
    MemoryType.CONVERSATION: 0.50,
    MemoryType.USER_PREFERENCE: 0.85,
    MemoryType.GENERAL: 0.50,
}


class MemoryManager:
    """Facade for storing, retrieving and maintaining AI memories."""

    def __init__(
        self,
        repository: MemoryRepository,
        *,
        embedding_provider: EmbeddingProvider | None = None,
        vector_store: VectorStore | None = None,
        config: MemoryConfig | None = None,
    ) -> None:
        self._repo = repository
        self._config = config or MemoryConfig()
        self._embedding_provider = embedding_provider or build_embedding_provider(self._config)
        self._vector_store = vector_store or InMemoryVectorStore()
        self._provider_available: bool | None = None

    async def _embeddings_available(self) -> bool:
        if not self._config.embedding_enabled:
            return False
        if self._provider_available is None:
            try:
                self._provider_available = await self._embedding_provider.is_available()
            except Exception:
                self._provider_available = False
        return self._provider_available

    # ── Storing ─────────────────────────────────────────────

    async def remember(
        self,
        memory_type: MemoryType,
        title: str,
        content: str = "",
        *,
        system: MemorySystem | None = None,
        user_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        importance: float | None = None,
        ttl_seconds: int | None = None,
    ) -> MemoryRead:
        """Store a memory and return the persisted record.

        Args:
            memory_type: What the memory is about.
            title: Short human-readable label.
            content: Longer detail.
            system: Memory system; defaults per type. Forced to short-term when
                a TTL is given.
            user_id: Owning user (None = platform-global).
            metadata: Structured extra data (ids, amounts, entities).
            importance: 0..1 retention weight; defaults per type.
            ttl_seconds: Optional TTL; sets `expires_at` for short-term memory.
        """
        if system is None:
            system = default_system_for(memory_type)
        if ttl_seconds is not None:
            system = MemorySystem.SHORT_TERM

        importance = importance if importance is not None else DEFAULT_IMPORTANCE[memory_type]
        now = datetime.now(UTC)
        expires_at: datetime | None = None
        if ttl_seconds is not None:
            expires_at = now + timedelta(seconds=ttl_seconds)
        elif system == MemorySystem.SHORT_TERM:
            expires_at = now + timedelta(seconds=self._config.short_term_ttl_seconds)

        embedding = await self._compute_embedding(f"{title} {content}".strip())

        memory = await self._repo.create(
            user_id=user_id,
            system=system.value,
            memory_type=memory_type.value,
            title=title,
            content=content,
            metadata_json=Memory.encode_metadata(metadata or {}),
            importance=importance,
            expires_at=expires_at,
            embedding=Memory.encode_embedding(embedding),
        )
        return self._to_read(memory)

    async def remember_from(self, create: MemoryCreate) -> MemoryRead:
        """Store a memory from the API input schema."""
        return await self.remember(
            create.memory_type,
            create.title,
            create.content,
            system=create.system,
            user_id=create.user_id,
            metadata=create.metadata,
            importance=create.importance,
            ttl_seconds=create.ttl_seconds,
        )

    # ── Domain convenience: episodic memory ─────────────────

    async def record_successful_purchase(
        self,
        *,
        external_id: str,
        supplier: str,
        price: float,
        quantity: int = 1,
        profit: float | None = None,
        user_id: str | None = None,
    ) -> MemoryRead:
        """Remember that a purchase succeeded (outcome + profitability)."""
        return await self.remember(
            MemoryType.PURCHASE_SUCCESS,
            title=f"Successful purchase: {external_id}",
            content=f"Purchased {quantity} of {external_id} from {supplier}.",
            user_id=user_id,
            metadata={
                "external_id": external_id,
                "supplier": supplier,
                "price": price,
                "quantity": quantity,
                "profit": profit,
            },
        )

    async def record_failed_purchase(
        self,
        *,
        external_id: str,
        supplier: str,
        reason: str,
        user_id: str | None = None,
    ) -> MemoryRead:
        """Remember that a purchase failed (so the agent avoids repeating it)."""
        return await self.remember(
            MemoryType.PURCHASE_FAILURE,
            title=f"Failed purchase: {external_id}",
            content=f"Purchase of {external_id} from {supplier} failed: {reason}",
            user_id=user_id,
            metadata={"external_id": external_id, "supplier": supplier, "reason": reason},
        )

    async def record_false_positive(
        self,
        *,
        external_id: str,
        reason: str,
        user_id: str | None = None,
    ) -> MemoryRead:
        """Remember that an opportunity was a false positive (so we learn)."""
        return await self.remember(
            MemoryType.FALSE_POSITIVE,
            title=f"False positive: {external_id}",
            content=f"Opportunity {external_id} turned out to be a false positive: {reason}",
            user_id=user_id,
            metadata={"external_id": external_id, "reason": reason},
        )

    async def remember_conversation(
        self,
        *,
        user_id: str,
        question: str,
        answer: str,
    ) -> MemoryRead:
        """Remember a past user conversation."""
        return await self.remember(
            MemoryType.CONVERSATION,
            title=question[:120],
            content=f"Q: {question}\nA: {answer}",
            user_id=user_id,
            metadata={"question": question, "answer": answer},
        )

    # ── Domain convenience: semantic memory ─────────────────

    async def add_favorite_supplier(
        self,
        *,
        supplier_code: str,
        supplier_name: str,
        reason: str = "",
        user_id: str | None = None,
    ) -> MemoryRead:
        """Record a favorite supplier."""
        return await self.remember(
            MemoryType.FAVORITE_SUPPLIER,
            title=f"Favorite supplier: {supplier_name}",
            content=f"{supplier_name} ({supplier_code}) is a preferred supplier.{(' ' + reason) if reason else ''}",
            user_id=user_id,
            metadata={"supplier_code": supplier_code, "supplier_name": supplier_name, "reason": reason},
        )

    async def add_favorite_brand(
        self,
        *,
        brand_name: str,
        reason: str = "",
        user_id: str | None = None,
    ) -> MemoryRead:
        """Record a favorite brand."""
        return await self.remember(
            MemoryType.FAVORITE_BRAND,
            title=f"Favorite brand: {brand_name}",
            content=f"{brand_name} is a preferred brand.{(' ' + reason) if reason else ''}",
            user_id=user_id,
            metadata={"brand_name": brand_name, "reason": reason},
        )

    async def note_high_performing_category(
        self,
        *,
        category: str,
        avg_profit: float | None = None,
        reason: str = "",
        user_id: str | None = None,
    ) -> MemoryRead:
        """Record that a category performs well."""
        return await self.remember(
            MemoryType.HIGH_PERFORMING_CATEGORY,
            title=f"High-performing category: {category}",
            content=f"{category} is a high-performing category.{(' ' + reason) if reason else ''}",
            user_id=user_id,
            metadata={"category": category, "avg_profit": avg_profit, "reason": reason},
        )

    async def note_seasonality(
        self,
        *,
        scope: str,
        peak_months: list[str],
        reason: str = "",
        user_id: str | None = None,
    ) -> MemoryRead:
        """Record seasonal demand for a category/product."""
        return await self.remember(
            MemoryType.SEASONALITY,
            title=f"Seasonality: {scope}",
            content=f"{scope} peaks in {', '.join(peak_months)}.{(' ' + reason) if reason else ''}",
            user_id=user_id,
            metadata={"scope": scope, "peak_months": peak_months, "reason": reason},
        )

    async def set_user_preference(
        self,
        *,
        user_id: str,
        key: str,
        value: Any,
    ) -> MemoryRead:
        """Record a user preference."""
        return await self.remember(
            MemoryType.USER_PREFERENCE,
            title=f"Preference: {key}",
            content=f"{key} = {value}",
            user_id=user_id,
            metadata={"key": key, "value": value},
        )

    # ── Retrieval ───────────────────────────────────────────

    async def recall(
        self,
        query: str,
        *,
        memory_types: set[MemoryType] | None = None,
        systems: set[MemorySystem] | None = None,
        user_id: str | None = None,
        top_k: int | None = None,
        threshold: float | None = None,
    ) -> list[MemoryRecallResult]:
        """Recall memories relevant to a query.

        Uses embedding (vector) search when available, else falls back to
        keyword search. Returns results ranked by similarity.
        """
        top_k = top_k or self._config.recall_top_k
        threshold = threshold if threshold is not None else self._config.recall_threshold

        if await self._embeddings_available():
            return await self._recall_vector(query, memory_types, systems, user_id, top_k, threshold)
        return await self._recall_keyword(query, memory_types, systems, user_id, top_k)

    async def _recall_vector(
        self,
        query: str,
        memory_types: set[MemoryType] | None,
        systems: set[MemorySystem] | None,
        user_id: str | None,
        top_k: int,
        threshold: float,
    ) -> list[MemoryRecallResult]:
        try:
            query_vector = await self._embedding_provider.embed(query)
        except MemoryEmbeddingError:
            return await self._recall_keyword(query, memory_types, systems, user_id, top_k)

        candidates = await self._repo.load_embeddings(
            memory_types=memory_types,
            systems=systems,
            user_id=user_id,
        )
        ranked = self._vector_store.rank(
            query_vector,
            candidates,
            top_k=top_k,
            threshold=threshold,
        )
        ids = [mid for mid, _score in ranked]
        records = {m.id: m for m in await self._repo.get_many_by_ids(ids)}

        results: list[MemoryRecallResult] = []
        for memory_id, score in ranked:
            memory = records.get(memory_id)
            if memory is None:
                continue
            # Build the read from the loaded state first; `touch` flushes and
            # expires the row (onupdate), so accessing it afterwards would lazy-load.
            results.append(MemoryRecallResult(memory=self._to_read(memory), score=round(score, 4)))
            await self._repo.touch(memory)
        return results

    async def _recall_keyword(
        self,
        query: str,
        memory_types: set[MemoryType] | None,
        systems: set[MemorySystem] | None,
        user_id: str | None,
        limit: int,
    ) -> list[MemoryRecallResult]:
        memories = await self._repo.recall_keyword(
            query,
            memory_types=memory_types,
            systems=systems,
            user_id=user_id,
            limit=limit,
        )
        return [MemoryRecallResult(memory=self._to_read(m), score=1.0) for m in memories]

    async def recall_recent(
        self,
        *,
        systems: set[MemorySystem] | None = None,
        user_id: str | None = None,
        limit: int | None = None,
    ) -> list[MemoryRead]:
        """Return the most recent memories (defaults to short-term)."""
        systems = systems or {MemorySystem.SHORT_TERM}
        limit = limit or self._config.recall_recent_limit
        memories: list[Memory] = []
        for system in systems:
            memories.extend(
                await self._repo.find_by_system(system, user_id=user_id, limit=limit),
            )
        memories.sort(key=lambda m: m.created_at, reverse=True)
        return [self._to_read(m) for m in memories[:limit]]

    async def get_by_type(
        self,
        memory_type: MemoryType,
        *,
        user_id: str | None = None,
        limit: int | None = None,
    ) -> list[MemoryRead]:
        memories = await self._repo.find_by_type(
            memory_type,
            user_id=user_id,
            limit=limit or self._config.max_results_per_type,
        )
        return [self._to_read(m) for m in memories]

    async def get(self, memory_id: UUID) -> MemoryRead:
        memory = await self._repo.get(memory_id)
        if memory is None:
            raise MemoryNotFoundError(memory_id)
        return self._to_read(memory)

    async def delete(self, memory_id: UUID) -> bool:
        return await self._repo.delete(memory_id)

    async def list(
        self,
        *,
        user_id: str | None = None,
        system: MemorySystem | None = None,
        memory_type: MemoryType | None = None,
        limit: int = 200,
    ) -> list[MemoryRead]:
        memories = await self._repo.list_all(
            user_id=user_id,
            system=system,
            memory_type=memory_type,
            limit=limit,
        )
        return [self._to_read(m) for m in memories]

    # ── Lifecycle ───────────────────────────────────────────

    async def consolidate(self) -> ConsolidationReport:
        """Run one memory-lifecycle pass.

        Steps:
        1. Delete expired short-term memories.
        2. Promote important episodic/short-term memories to long-term.
        3. Decay episodic-memory importance; purge those below the floor.
        """
        report = ConsolidationReport()

        expired = await self._repo.list_expired()
        report.expired_deleted = await self._repo.delete_many(expired)

        promotable = await self._repo.list_promotable(self._config.consolidation_importance_threshold)
        for memory in promotable:
            memory.system = MemorySystem.LONG_TERM.value
            memory.expires_at = None
        report.promoted = len(promotable)

        decayable = await self._repo.list_decayable()
        to_purge: list[Memory] = []
        for memory in decayable:
            memory.importance -= self._config.decay_factor
            if memory.importance < self._config.min_importance:
                to_purge.append(memory)
        report.decayed = len(decayable) - len(to_purge)
        report.purged = await self._repo.delete_many(to_purge)

        await self._repo._session.flush()
        report.remaining = await self._repo.total()
        return report

    async def stats(self) -> MemoryStats:
        total = await self._repo.total()
        by_system, by_type = await self._repo.counts()
        return MemoryStats(total=total, by_system=by_system, by_type=by_type)

    # ── Helpers ─────────────────────────────────────────────

    async def _compute_embedding(self, text: str) -> list[float] | None:
        if not text or not await self._embeddings_available():
            return None
        try:
            return await self._embedding_provider.embed(text)
        except MemoryEmbeddingError:
            return None

    @staticmethod
    def _to_read(memory: Memory) -> MemoryRead:
        return MemoryRead(
            id=memory.id,
            user_id=memory.user_id,
            system=MemorySystem(memory.system),
            memory_type=MemoryType(memory.memory_type),
            title=memory.title,
            content=memory.content,
            metadata=Memory.decode_metadata(memory.metadata_json),
            importance=memory.importance,
            access_count=memory.access_count,
            last_accessed_at=memory.last_accessed_at,
            expires_at=memory.expires_at,
            created_at=memory.created_at,
            updated_at=memory.updated_at,
        )
