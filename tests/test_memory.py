"""Tests for the AI memory system.

Verifies:
- The four memory systems and ten memory types, plus default-system mapping.
- The repository (persistence separate from product data) and its queries.
- MemoryManager: storing, domain convenience methods, getters, recall.
- Embedding search (vector recall) and keyword fallback.
- Lifecycle: short-term expiry, promotion to long-term, episodic decay/purge.
- Stats and error handling.
- The /api/v1/memory endpoints.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.memory import (
    InMemoryVectorStore,
    MemoryConfig,
    MemoryManager,
    MemoryRepository,
    MemorySystem,
    MemoryType,
    build_embedding_provider,
    default_system_for,
)
from app.memory.errors import MemoryNotFoundError
from app.memory.schemas import MemoryRecallResult


def _manager(db: AsyncSession, **cfg: object) -> MemoryManager:
    config = MemoryConfig(**cfg)
    return MemoryManager(
        MemoryRepository(db),
        embedding_provider=build_embedding_provider(config),
        vector_store=InMemoryVectorStore(),
        config=config,
    )


# ── Enums & mapping ────────────────────────────────────────


class TestModel:
    def test_four_memory_systems(self) -> None:
        assert {s for s in MemorySystem} == {
            MemorySystem.SHORT_TERM,
            MemorySystem.LONG_TERM,
            MemorySystem.EPISODIC,
            MemorySystem.SEMANTIC,
        }

    def test_ten_memory_types(self) -> None:
        assert len(set(MemoryType)) == 10

    def test_default_system_mapping(self) -> None:
        assert default_system_for(MemoryType.PURCHASE_SUCCESS) == MemorySystem.EPISODIC
        assert default_system_for(MemoryType.PURCHASE_FAILURE) == MemorySystem.EPISODIC
        assert default_system_for(MemoryType.FALSE_POSITIVE) == MemorySystem.EPISODIC
        assert default_system_for(MemoryType.CONVERSATION) == MemorySystem.EPISODIC
        assert default_system_for(MemoryType.FAVORITE_SUPPLIER) == MemorySystem.SEMANTIC
        assert default_system_for(MemoryType.FAVORITE_BRAND) == MemorySystem.SEMANTIC
        assert default_system_for(MemoryType.HIGH_PERFORMING_CATEGORY) == MemorySystem.SEMANTIC
        assert default_system_for(MemoryType.SEASONALITY) == MemorySystem.SEMANTIC
        assert default_system_for(MemoryType.USER_PREFERENCE) == MemorySystem.SEMANTIC
        assert default_system_for(MemoryType.GENERAL) == MemorySystem.SHORT_TERM


# ── Repository ─────────────────────────────────────────────


class TestRepository:
    async def test_create_and_find_by_type(self, db_session: AsyncSession) -> None:
        repo = MemoryRepository(db_session)
        await repo.create(
            user_id="u1",
            system=MemorySystem.SEMANTIC.value,
            memory_type=MemoryType.FAVORITE_SUPPLIER.value,
            title="Favorite supplier: Acme",
            content="Acme is preferred",
            metadata_json='{"supplier_code": "acme"}',
            importance=0.9,
        )
        found = await repo.find_by_type(MemoryType.FAVORITE_SUPPLIER, user_id="u1")
        assert len(found) == 1
        assert found[0].title == "Favorite supplier: Acme"

    async def test_counts_and_total(self, db_session: AsyncSession) -> None:
        repo = MemoryRepository(db_session)
        await repo.create(
            system=MemorySystem.SEMANTIC.value,
            memory_type=MemoryType.FAVORITE_BRAND.value,
            title="x",
            content="y",
        )
        await repo.create(
            system=MemorySystem.EPISODIC.value,
            memory_type=MemoryType.PURCHASE_SUCCESS.value,
            title="a",
            content="b",
        )
        assert await repo.total() == 2
        by_system, by_type = await repo.counts()
        assert by_system[MemorySystem.SEMANTIC.value] == 1
        assert by_type[MemoryType.PURCHASE_SUCCESS.value] == 1

    async def test_recall_keyword(self, db_session: AsyncSession) -> None:
        repo = MemoryRepository(db_session)
        await repo.create(
            system=MemorySystem.SEMANTIC.value,
            memory_type=MemoryType.FAVORITE_SUPPLIER.value,
            title="Favorite supplier",
            content="Acme supplies premium widgets",
            importance=0.9,
        )
        hits = await repo.recall_keyword("supplier", limit=5)
        assert len(hits) == 1


# ── Manager: storing ───────────────────────────────────────


class TestRemember:
    async def test_remember_auto_system_and_embedding(self, db_session: AsyncSession) -> None:
        mgr = _manager(db_session)
        mem = await mgr.remember(
            MemoryType.FAVORITE_SUPPLIER,
            "Favorite supplier",
            "Acme is preferred",
        )
        assert mem.system == MemorySystem.SEMANTIC
        assert mem.importance == pytest.approx(0.85)  # per-type default
        # Embedding computed by the local provider and persisted.
        assert await mgr._repo.get(mem.id) is not None

    async def test_remember_ttl_forces_short_term(self, db_session: AsyncSession) -> None:
        mgr = _manager(db_session)
        mem = await mgr.remember(
            MemoryType.GENERAL,
            "Note",
            "working memory",
            ttl_seconds=3600,
        )
        assert mem.system == MemorySystem.SHORT_TERM
        assert mem.expires_at is not None
        # sqlite returns naive datetimes; compare tz-agnostically.
        assert mem.expires_at.replace(tzinfo=None) > datetime.now(UTC).replace(tzinfo=None)

    async def test_remember_explicit_system_and_metadata(self, db_session: AsyncSession) -> None:
        mgr = _manager(db_session)
        mem = await mgr.remember(
            MemoryType.GENERAL,
            "Note",
            "stored",
            system=MemorySystem.LONG_TERM,
            metadata={"source": "test", "count": 3},
        )
        assert mem.system == MemorySystem.LONG_TERM
        assert mem.metadata["count"] == 3


# ── Manager: domain convenience methods ────────────────────


class TestConvenience:
    async def test_episodic_records(self, db_session: AsyncSession) -> None:
        mgr = _manager(db_session)
        success = await mgr.record_successful_purchase(
            external_id="B0X", supplier="Acme", price=10.0, profit=3.0
        )
        failure = await mgr.record_failed_purchase(
            external_id="B0Y", supplier="Beta", reason="out of stock"
        )
        fp = await mgr.record_false_positive(external_id="B0Z", reason="bad margins")

        assert success.system == MemorySystem.EPISODIC
        assert success.memory_type == MemoryType.PURCHASE_SUCCESS
        assert failure.memory_type == MemoryType.PURCHASE_FAILURE
        assert fp.memory_type == MemoryType.FALSE_POSITIVE

    async def test_semantic_records(self, db_session: AsyncSession) -> None:
        mgr = _manager(db_session)
        supplier = await mgr.add_favorite_supplier(supplier_code="acme", supplier_name="Acme")
        brand = await mgr.add_favorite_brand(brand_name="Apple")
        category = await mgr.note_high_performing_category(category="Electronics", avg_profit=12.0)
        season = await mgr.note_seasonality(scope="Coats", peak_months=["Nov", "Dec"])

        assert supplier.system == MemorySystem.SEMANTIC
        assert supplier.memory_type == MemoryType.FAVORITE_SUPPLIER
        assert brand.memory_type == MemoryType.FAVORITE_BRAND
        assert category.metadata["avg_profit"] == 12.0
        assert season.memory_type == MemoryType.SEASONALITY

    async def test_conversation_and_preference(self, db_session: AsyncSession) -> None:
        mgr = _manager(db_session)
        conv = await mgr.remember_conversation(
            user_id="u1", question="Which supplier?", answer="Acme"
        )
        pref = await mgr.set_user_preference(user_id="u1", key="currency", value="EUR")

        assert conv.memory_type == MemoryType.CONVERSATION
        assert conv.user_id == "u1"
        assert pref.memory_type == MemoryType.USER_PREFERENCE
        assert pref.metadata == {"key": "currency", "value": "EUR"}

    async def test_getters_by_type(self, db_session: AsyncSession) -> None:
        mgr = _manager(db_session)
        await mgr.add_favorite_supplier(supplier_code="acme", supplier_name="Acme")
        await mgr.add_favorite_supplier(supplier_code="beta", supplier_name="Beta")
        await mgr.add_favorite_brand(brand_name="Apple")

        suppliers = await mgr.get_by_type(MemoryType.FAVORITE_SUPPLIER)
        assert len(suppliers) == 2
        brands = await mgr.get_by_type(MemoryType.FAVORITE_BRAND)
        assert len(brands) == 1


# ── Recall ─────────────────────────────────────────────────


class TestRecall:
    async def test_vector_recall_ranks_relevant(self, db_session: AsyncSession) -> None:
        mgr = _manager(db_session)
        await mgr.add_favorite_supplier(supplier_code="acme", supplier_name="Acme")
        await mgr.note_seasonality(scope="Winter coats", peak_months=["Nov", "Dec"])

        results = await mgr.recall("preferred supplier", top_k=5)
        assert isinstance(results[0], MemoryRecallResult)
        # The supplier memory should rank above the unrelated seasonality memory.
        assert results[0].memory.memory_type == MemoryType.FAVORITE_SUPPLIER
        assert results[0].score > 0

    async def test_recall_keyword_fallback(self, db_session: AsyncSession) -> None:
        mgr = _manager(db_session, embedding_enabled=False)
        await mgr.add_favorite_supplier(supplier_code="acme", supplier_name="Acme")
        await mgr.note_seasonality(scope="Coats", peak_months=["Nov"])

        results = await mgr.recall("Acme", top_k=5)
        assert len(results) == 1
        assert results[0].memory.memory_type == MemoryType.FAVORITE_SUPPLIER

    async def test_recall_recent(self, db_session: AsyncSession) -> None:
        mgr = _manager(db_session)
        m1 = await mgr.remember(MemoryType.GENERAL, "First", "note", ttl_seconds=3600)
        m2 = await mgr.remember(MemoryType.GENERAL, "Second", "note", ttl_seconds=3600)
        # Force distinct created_at values (sqlite server_default has 1s precision).
        orm1 = await mgr._repo.get(m1.id)
        orm2 = await mgr._repo.get(m2.id)
        orm1.created_at = datetime.now(UTC) - timedelta(seconds=10)
        orm2.created_at = datetime.now(UTC)
        await db_session.flush()

        recent = await mgr.recall_recent(limit=10)
        assert [m.title for m in recent] == ["Second", "First"]

    async def test_get_and_delete(self, db_session: AsyncSession) -> None:
        mgr = _manager(db_session)
        mem = await mgr.remember(MemoryType.GENERAL, "Note", "x")
        got = await mgr.get(mem.id)
        assert got.id == mem.id

        assert await mgr.delete(mem.id) is True
        assert await mgr.delete(mem.id) is False
        with pytest.raises(MemoryNotFoundError):
            await mgr.get(mem.id)


# ── Lifecycle ──────────────────────────────────────────────


class TestLifecycle:
    async def test_expire_short_term(self, db_session: AsyncSession) -> None:
        mgr = _manager(db_session)
        mem = await mgr.remember(MemoryType.GENERAL, "Note", "ephemeral", ttl_seconds=3600)
        orm = await mgr._repo.get(mem.id)
        orm.expires_at = datetime.now(UTC) - timedelta(seconds=10)
        await db_session.flush()

        report = await mgr.consolidate()
        assert report.expired_deleted == 1

    async def test_promote_important_episodic_to_long_term(self, db_session: AsyncSession) -> None:
        mgr = _manager(db_session)
        await mgr.record_successful_purchase(external_id="B0X", supplier="Acme", price=5.0)
        # importance default 0.8 >= threshold 0.7 -> promoted.

        report = await mgr.consolidate()
        assert report.promoted >= 1

        promoted = await mgr.get_by_type(MemoryType.PURCHASE_SUCCESS)
        assert all(m.system == MemorySystem.LONG_TERM for m in promoted)

    async def test_decay_and_purge_episodic(self, db_session: AsyncSession) -> None:
        # Aggressive decay + high floor so the memory is purged after one pass.
        mgr = _manager(
            db_session,
            decay_factor=0.6,
            min_importance=0.55,
            consolidation_importance_threshold=0.9,
        )
        await mgr.record_false_positive(external_id="B0Z", reason="bad")  # importance 0.6
        report = await mgr.consolidate()
        assert report.purged == 1
        assert await mgr.get_by_type(MemoryType.FALSE_POSITIVE) == []


# ── Stats ──────────────────────────────────────────────────


class TestStats:
    async def test_stats(self, db_session: AsyncSession) -> None:
        mgr = _manager(db_session)
        await mgr.add_favorite_supplier(supplier_code="acme", supplier_name="Acme")
        await mgr.record_successful_purchase(external_id="B0X", supplier="Acme", price=5.0)

        stats = await mgr.stats()
        assert stats.total == 2
        assert stats.by_system[MemorySystem.SEMANTIC.value] == 1
        assert stats.by_system[MemorySystem.EPISODIC.value] == 1
        assert stats.by_type[MemoryType.FAVORITE_SUPPLIER.value] == 1


# ── API ────────────────────────────────────────────────────


class TestAPI:
    async def test_create_and_list(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/memory/",
            json={"memory_type": "favorite.supplier", "title": "Favorite supplier", "content": "Acme"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["system"] == "semantic"
        assert body["memory_type"] == "favorite.supplier"

        listed = await client.get("/api/v1/memory/")
        assert listed.status_code == 200
        assert len(listed.json()) == 1

    async def test_recall_endpoint(self, client: AsyncClient) -> None:
        await client.post(
            "/api/v1/memory/",
            json={"memory_type": "favorite.supplier", "title": "Favorite supplier", "content": "Acme is preferred"},
        )
        resp = await client.get("/api/v1/memory/recall", params={"q": "preferred supplier"})
        assert resp.status_code == 200
        results = resp.json()
        assert len(results) >= 1
        assert results[0]["memory"]["memory_type"] == "favorite.supplier"
        assert results[0]["score"] > 0

    async def test_types_and_stats_and_consolidate(self, client: AsyncClient) -> None:
        await client.post(
            "/api/v1/memory/",
            json={"memory_type": "favorite.brand", "title": "Favorite brand", "content": "Apple"},
        )
        types_resp = await client.get("/api/v1/memory/types/favorite.brand")
        assert len(types_resp.json()) == 1

        stats_resp = await client.get("/api/v1/memory/stats")
        assert stats_resp.json()["total"] == 1

        cons_resp = await client.post("/api/v1/memory/consolidate")
        assert cons_resp.status_code == 200
        assert cons_resp.json()["remaining"] == 1

    async def test_get_and_delete(self, client: AsyncClient) -> None:
        created = await client.post(
            "/api/v1/memory/",
            json={"memory_type": "general", "title": "Note", "content": "x"},
        )
        memory_id = created.json()["id"]

        got = await client.get(f"/api/v1/memory/{memory_id}")
        assert got.status_code == 200

        deleted = await client.delete(f"/api/v1/memory/{memory_id}")
        assert deleted.status_code == 204

        missing = await client.get(f"/api/v1/memory/{memory_id}")
        assert missing.status_code == 404
