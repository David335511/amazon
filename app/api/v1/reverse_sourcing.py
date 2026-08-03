"""Reverse sourcing API.

The router talks ONLY to `ReverseSourcingManager` (via DI); it contains no
sourcing logic. Exposes reverse-sourcing an ASIN, retrieving stored runs,
historical supplier series, capabilities and stats.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.dependencies import get_reverse_sourcing_manager
from app.reverse_sourcing import (
    HistoricalSupplierRead,
    ReverseSourcingCapabilities,
    ReverseSourcingList,
    ReverseSourcingManager,
    ReverseSourcingRead,
    ReverseSourcingRequest,
    ReverseSourcingRunRead,
    ReverseSourcingStats,
)
from app.reverse_sourcing.errors import (
    ReverseSourcingNotFoundError,
    ReverseSourcingValidationError,
)

router = APIRouter(prefix="/reverse-sourcing", tags=["reverse-sourcing"])

ManagerDep = Annotated[ReverseSourcingManager, Depends(get_reverse_sourcing_manager)]


@router.get("/capabilities", response_model=ReverseSourcingCapabilities)
async def capabilities(manager: ManagerDep) -> ReverseSourcingCapabilities:
    """Report the suppliers and features this deployment can reverse-source."""
    return manager.capabilities()


@router.post(
    "/source",
    response_model=ReverseSourcingRead,
    status_code=status.HTTP_201_CREATED,
)
async def source(
    request: ReverseSourcingRequest, manager: ManagerDep
) -> ReverseSourcingRead:
    """Reverse-source an Amazon ASIN across every known supplier."""
    try:
        return await manager.source(request)
    except ReverseSourcingValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    except ReverseSourcingNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/runs", response_model=ReverseSourcingList)
async def list_runs(
    manager: ManagerDep,
    asin: str | None = None,
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> ReverseSourcingList:
    """List stored reverse-sourcing runs, optionally filtered by ASIN."""
    return await manager.list_runs(asin=asin, limit=limit, offset=offset)


@router.get("/runs/{run_id}", response_model=ReverseSourcingRunRead)
async def get_run(manager: ManagerDep, run_id: UUID) -> ReverseSourcingRunRead:
    """Return a stored reverse-sourcing run."""
    try:
        return await manager.get_run(run_id)
    except ReverseSourcingNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/historical", response_model=HistoricalSupplierRead)
async def historical(
    manager: ManagerDep,
    supplier_code: str = Query(min_length=1),
    asin: str = Query(min_length=1),
) -> HistoricalSupplierRead:
    """Historical price / discount series for a (supplier, ASIN) pair."""
    try:
        return await manager.historical(supplier_code, asin)
    except ReverseSourcingNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/stats", response_model=ReverseSourcingStats)
async def stats(manager: ManagerDep) -> ReverseSourcingStats:
    """Aggregate statistics over the reverse-sourcing store."""
    return await manager.stats()
