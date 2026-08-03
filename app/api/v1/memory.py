"""AI memory API — store, list, recall and maintain AI memories.

The router talks ONLY to `MemoryManager` (via DI); it contains no memory-domain
logic itself.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.dependencies import get_memory_manager
from app.memory import (
    ConsolidationReport,
    MemoryCreate,
    MemoryManager,
    MemoryRead,
    MemoryRecallResult,
    MemoryStats,
    MemorySystem,
    MemoryType,
)
from app.memory.errors import MemoryNotFoundError

router = APIRouter(prefix="/memory", tags=["memory"])

ManagerDep = Annotated[MemoryManager, Depends(get_memory_manager)]


@router.get("/", response_model=list[MemoryRead])
async def list_memories(
    manager: ManagerDep,
    user_id: str | None = None,
    system: MemorySystem | None = None,
    memory_type: MemoryType | None = None,
    limit: int = Query(default=200, ge=1, le=500),
) -> list[MemoryRead]:
    """List stored memories, optionally filtered by user/system/type."""
    return await manager.list(
        user_id=user_id,
        system=system,
        memory_type=memory_type,
        limit=limit,
    )


@router.post("/", response_model=MemoryRead, status_code=status.HTTP_201_CREATED)
async def create_memory(manager: ManagerDep, create: MemoryCreate) -> MemoryRead:
    """Store a new memory."""
    return await manager.remember_from(create)


@router.get("/recall", response_model=list[MemoryRecallResult])
async def recall(
    manager: ManagerDep,
    q: str = Query(min_length=1),
    user_id: str | None = None,
    top_k: int = Query(default=10, ge=1, le=50),
) -> list[MemoryRecallResult]:
    """Semantically recall memories relevant to a query."""
    return await manager.recall(q, user_id=user_id, top_k=top_k)


@router.get("/recent", response_model=list[MemoryRead])
async def recent(
    manager: ManagerDep,
    user_id: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
) -> list[MemoryRead]:
    """Return the most recent short-term memories."""
    return await manager.recall_recent(user_id=user_id, limit=limit)


@router.get("/types/{memory_type}", response_model=list[MemoryRead])
async def by_type(
    manager: ManagerDep,
    memory_type: MemoryType,
    user_id: str | None = None,
) -> list[MemoryRead]:
    """List memories of a specific type (favorites, preferences, ...)."""
    return await manager.get_by_type(memory_type, user_id=user_id)


@router.get("/stats", response_model=MemoryStats)
async def stats(manager: ManagerDep) -> MemoryStats:
    """Return aggregate memory statistics."""
    return await manager.stats()


@router.post("/consolidate", response_model=ConsolidationReport)
async def consolidate(manager: ManagerDep) -> ConsolidationReport:
    """Run a memory-lifecycle consolidation pass (expire/promote/decay)."""
    return await manager.consolidate()


@router.get("/{memory_id}", response_model=MemoryRead)
async def get_memory(manager: ManagerDep, memory_id: UUID) -> MemoryRead:
    """Fetch a single memory by id."""
    try:
        return await manager.get(memory_id)
    except MemoryNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="memory_not_found",
        ) from exc


@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(manager: ManagerDep, memory_id: UUID) -> None:
    """Delete a memory by id."""
    deleted = await manager.delete(memory_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="memory_not_found",
        )
