"""Persistence layer for the document intelligence system.

Document rows live in their own `documents` table, fully separate from product
data. The repository exposes CRUD plus the search queries the manager needs.
List/search queries use `defer(Document.raw_blob)` so large raw payloads are
never loaded when only summaries are needed (a production-critical detail for a
document corpus).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from app.documents.models import Document
from app.infrastructure.repositories.base import BaseRepository

# Field names eligible for field-level search (must match ExtractedFields keys).
SEARCHABLE_FIELDS = {
    "upc",
    "ean",
    "gtin",
    "weight",
    "dimensions",
    "case_quantity",
    "model_number",
    "manufacturer",
    "part_number",
    "warranty",
}


class DocumentRepository(BaseRepository[Document]):
    """Repository for the `documents` table."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Document)

    # ── Reads ────────────────────────────────────────────────────────────

    async def find_by_sha256(self, sha256: str) -> Document | None:
        result = await self._session.execute(
            select(Document).where(Document.sha256 == sha256).limit(1),
        )
        return result.scalar_one_or_none()

    async def list_summary(
        self,
        *,
        doc_type: str | None = None,
        file_format: str | None = None,
        user_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[Document], int]:
        base = select(Document).options(defer(Document.raw_blob))
        filters = {}
        if doc_type:
            filters["doc_type"] = doc_type
        if file_format:
            filters["file_format"] = file_format
        query = self._apply_filters(base, filters)
        query = self._apply_user(query, user_id)
        total = await self._count(query)
        query = query.order_by(Document.created_at.desc()).offset(offset).limit(limit)
        result = await self._session.execute(query)
        return list(result.scalars().all()), total

    async def search(
        self,
        query: str,
        *,
        doc_type: str | None = None,
        user_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[Document], int]:
        """Full-text search over extracted text and extracted fields."""
        pattern = f"%{query.strip()}%"
        statement = select(Document).options(defer(Document.raw_blob)).where(
            or_(
                Document.text.ilike(pattern),
                Document.extracted_json.ilike(pattern),
            ),
        )
        statement = self._apply_user(statement, user_id)
        if doc_type:
            statement = self._apply_filters(statement, {"doc_type": doc_type})
        total = await self._count(statement)
        statement = (
            statement.order_by(Document.confidence.desc(), Document.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.execute(statement)
        return list(result.scalars().all()), total

    async def search_field(
        self,
        field: str,
        value: str,
        *,
        doc_type: str | None = None,
        user_id: str | None = None,
        limit: int = 50,
    ) -> list[Document]:
        """Search documents that have a given extracted field with a given value."""
        if field not in SEARCHABLE_FIELDS:
            return []
        statement = select(Document).options(defer(Document.raw_blob)).where(
            Document.extracted_json.is_not(None),
            Document.extracted_json.ilike(f'%"{field}"%'),
            Document.extracted_json.ilike(f"%{value.strip()}%"),
        )
        statement = self._apply_user(statement, user_id)
        if doc_type:
            statement = self._apply_filters(statement, {"doc_type": doc_type})
        statement = statement.order_by(Document.created_at.desc()).limit(limit)
        result = await self._session.execute(statement)
        return list(result.scalars().all())

    # ── Stats ────────────────────────────────────────────────────────────

    async def stats(self) -> dict[str, Any]:
        type_rows = await self._session.execute(
            select(Document.doc_type, func.count()).group_by(Document.doc_type),
        )
        format_rows = await self._session.execute(
            select(Document.file_format, func.count()).group_by(Document.file_format),
        )
        total = await self._session.execute(select(func.count()).select_from(Document))
        bytes_rows = await self._session.execute(select(func.coalesce(func.sum(Document.raw_size_bytes), 0)))
        ocr_rows = await self._session.execute(
            select(func.count()).select_from(Document).where(Document.ocr_used.is_(True)),
        )
        return {
            "total": int(total.scalar_one()),
            "by_type": {row[0]: int(row[1]) for row in type_rows.all()},
            "by_format": {row[0]: int(row[1]) for row in format_rows.all()},
            "total_bytes": int(bytes_rows.scalar_one()),
            "ocr_documents": int(ocr_rows.scalar_one()),
        }

    # ── Helpers ──────────────────────────────────────────────────────────

    async def _count(self, statement: Any) -> int:
        result = await self._session.execute(select(func.count()).select_from(statement.subquery()))
        return int(result.scalar_one())

    def _apply_user(self, statement: Any, user_id: str | None) -> Any:
        if user_id is None:
            return statement.where(Document.user_id.is_(None))
        return statement.where(or_(Document.user_id == user_id, Document.user_id.is_(None)))
