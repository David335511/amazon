"""ORM model and enums for the AI memory system.

Design decisions:
- Memories are stored in their OWN table (`memories`), **completely separate
  from product data**. Nothing about a memory is a foreign key to products,
  orders or suppliers — memory rows reference those entities only as opaque
  strings inside `metadata_json`, so memory stays an independent bounded context.
- `MemorySystem` distinguishes the four memory subsystems (short-term,
  long-term, episodic, semantic). `MemoryType` classifies the *content* (what
  the memory is about).
- The embedding vector is stored as a JSON column (`embedding`), so the system
  works on any Postgres without a vector extension and can be migrated to a
  dedicated vector database later without touching the memory rows.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.models.base import Base, TimestampMixin, UUIDMixin


class MemorySystem(StrEnum):
    """The four memory subsystems.

    - SHORT_TERM: working memory; volatile, TTL-bounded, low durability.
    - LONG_TERM: durable facts that persist (consolidated from short-term).
    - EPISODIC: specific events/experiences (a purchase, a failure, a chat).
    - SEMANTIC: generalized knowledge/facts (favorites, trends, preferences).
    """

    SHORT_TERM = "short_term"
    LONG_TERM = "long_term"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"


class MemoryType(StrEnum):
    """The kind of knowledge a memory holds."""

    PURCHASE_SUCCESS = "purchase.success"
    PURCHASE_FAILURE = "purchase.failure"
    FALSE_POSITIVE = "false.positive"
    FAVORITE_SUPPLIER = "favorite.supplier"
    FAVORITE_BRAND = "favorite.brand"
    HIGH_PERFORMING_CATEGORY = "high_performing.category"
    SEASONALITY = "seasonality"
    CONVERSATION = "conversation"
    USER_PREFERENCE = "user.preference"
    GENERAL = "general"


class Memory(Base, UUIDMixin, TimestampMixin):
    """A single stored memory record."""

    __tablename__ = "memories"

    user_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, index=True,
        comment="Owning user (None = platform-global memory)",
    )
    system: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True,
        comment="One of MemorySystem values",
    )
    memory_type: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True,
        comment="One of MemoryType values",
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="JSON-encoded structured metadata (entities, amounts, ids)",
    )
    importance: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.5,
        comment="0..1 retention weight; drives consolidation/decay",
    )
    access_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )
    last_accessed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True,
        comment="When set, the memory expires (short-term lifecycle)",
    )
    embedding: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="JSON list of floats; the vector used for semantic recall",
    )

    def __repr__(self) -> str:
        return f"<Memory(id={self.id}, type={self.memory_type}, system={self.system})>"

    @staticmethod
    def encode_metadata(data: dict[str, Any] | None) -> str | None:
        """Encode a metadata dict to its JSON storage form."""
        import json

        if not data:
            return None
        return json.dumps(data)

    @staticmethod
    def decode_metadata(raw: str | None) -> dict[str, Any]:
        """Decode stored metadata JSON back to a dict."""
        import json

        if not raw:
            return {}
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return {}

    @staticmethod
    def encode_embedding(vector: list[float] | None) -> str | None:
        """Encode a float vector to its JSON storage form."""
        import json

        if vector is None:
            return None
        return json.dumps([float(v) for v in vector])

    @staticmethod
    def decode_embedding(raw: str | None) -> list[float] | None:
        """Decode stored embedding JSON back to a float list."""
        import json

        if not raw:
            return None
        try:
            return [float(v) for v in json.loads(raw)]
        except (TypeError, ValueError):
            return None


def default_system_for(memory_type: MemoryType) -> MemorySystem:
    """Map a memory type to its default memory system.

    Episodic types record specific events; semantic types record durable facts.
    Anything else defaults to short-term (working memory).
    """
    episodic = {
        MemoryType.PURCHASE_SUCCESS,
        MemoryType.PURCHASE_FAILURE,
        MemoryType.FALSE_POSITIVE,
        MemoryType.CONVERSATION,
    }
    semantic = {
        MemoryType.FAVORITE_SUPPLIER,
        MemoryType.FAVORITE_BRAND,
        MemoryType.HIGH_PERFORMING_CATEGORY,
        MemoryType.SEASONALITY,
        MemoryType.USER_PREFERENCE,
    }
    if memory_type in episodic:
        return MemorySystem.EPISODIC
    if memory_type in semantic:
        return MemorySystem.SEMANTIC
    return MemorySystem.SHORT_TERM
