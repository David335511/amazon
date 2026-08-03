"""Pydantic schemas for the AI memory system API.

`MemoryRead` mirrors the persisted ORM row (via `from_attributes=True`);
`MemoryCreate` is the input contract for storing a new memory.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.memory.models import MemorySystem, MemoryType


class MemoryCreate(BaseModel):
    """Payload for storing a new memory."""

    memory_type: MemoryType
    title: str = Field(min_length=1, max_length=500)
    content: str = ""
    # If omitted, `default_system_for(memory_type)` is applied.
    system: MemorySystem | None = None
    user_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    # Optional TTL (seconds); sets `expires_at` for short-term memories.
    ttl_seconds: int | None = Field(default=None, gt=0)


class MemoryRead(BaseModel):
    """A memory record as returned by the API."""

    id: UUID
    user_id: str | None
    system: MemorySystem
    memory_type: MemoryType
    title: str
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    importance: float
    access_count: int
    last_accessed_at: datetime | None
    expires_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MemoryRecallResult(BaseModel):
    """A memory retrieved by a recall query, with its similarity score."""

    memory: MemoryRead
    score: float


class ConsolidationReport(BaseModel):
    """Result of a memory lifecycle consolidation pass."""

    expired_deleted: int = 0
    promoted: int = 0
    decayed: int = 0
    purged: int = 0
    remaining: int = 0


class MemoryStats(BaseModel):
    """Aggregate statistics over stored memories."""

    total: int
    by_system: dict[str, int] = Field(default_factory=dict)
    by_type: dict[str, int] = Field(default_factory=dict)
