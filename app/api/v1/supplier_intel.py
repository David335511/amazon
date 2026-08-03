"""Supplier intelligence API.

The router talks ONLY to `SupplierIntelManager` (via DI); it contains no
scoring logic. It exposes recording historical observations, listing them,
computing the five supplier scores, full profiles (metrics + scores +
explanation), batch profiling, explanation, capabilities and stats.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.dependencies import get_supplier_intel_manager
from app.supplier_intel import (
    ObservationCreate,
    ObservationList,
    ObservationRead,
    SupplierIntelBatchRequest,
    SupplierIntelCapabilities,
    SupplierIntelManager,
    SupplierIntelRead,
    SupplierIntelStats,
)
from app.supplier_intel.errors import (
    SupplierIntelNotFoundError,
    SupplierIntelValidationError,
)

router = APIRouter(prefix="/supplier-intel", tags=["supplier-intel"])

ManagerDep = Annotated[SupplierIntelManager, Depends(get_supplier_intel_manager)]


@router.get("/capabilities", response_model=SupplierIntelCapabilities)
async def capabilities(manager: ManagerDep) -> SupplierIntelCapabilities:
    """Report the scores and tracked metrics this deployment supports."""
    return manager.capabilities()


@router.post(
    "/observations",
    response_model=ObservationRead,
    status_code=status.HTTP_201_CREATED,
)
async def record_observation(
    request: ObservationCreate, manager: ManagerDep
) -> ObservationRead:
    """Record one historical period snapshot for a supplier."""
    return await manager.record_observation(request)


@router.get("/observations", response_model=ObservationList)
async def list_observations(
    manager: ManagerDep,
    supplier_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> ObservationList:
    """List historical observations, optionally filtered by supplier."""
    return await manager.list_observations(
        supplier_id=supplier_id, limit=limit, offset=offset
    )


@router.get("/observations/{observation_id}", response_model=ObservationRead)
async def get_observation(manager: ManagerDep, observation_id: UUID) -> ObservationRead:
    """Return a single stored observation by id."""
    try:
        return await manager.get_observation(observation_id)
    except SupplierIntelNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/scores")
async def scores(
    manager: ManagerDep, supplier_id: str = Query(min_length=1)
) -> dict:
    """Compute the five supplier scores from the historical record."""
    return await manager.scores(supplier_id)


@router.get("/profile", response_model=SupplierIntelRead)
async def profile(manager: ManagerDep, supplier_id: str = Query(min_length=1)) -> SupplierIntelRead:
    """Full supplier profile: historical metrics, scores, and AI explanation."""
    try:
        return await manager.profile(supplier_id)
    except SupplierIntelNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/profile/batch", response_model=list[SupplierIntelRead])
async def profile_batch(
    manager: ManagerDep, request: SupplierIntelBatchRequest
) -> list[SupplierIntelRead]:
    """Profile several suppliers in one call (skips suppliers with no history)."""
    try:
        return await manager.profile_batch(request)
    except SupplierIntelValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.get("/explain")
async def explain(manager: ManagerDep, supplier_id: str = Query(min_length=1)) -> dict:
    """AI explanation of a supplier's behaviour (historical)."""
    try:
        return {"supplier_id": supplier_id, "explanation": await manager.explain(supplier_id)}
    except SupplierIntelNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/suppliers", response_model=list[str])
async def suppliers(manager: ManagerDep) -> list[str]:
    """Distinct suppliers with a historical record."""
    return await manager.suppliers()


@router.get("/stats", response_model=SupplierIntelStats)
async def stats(manager: ManagerDep) -> SupplierIntelStats:
    """Aggregate statistics over the supplier-intelligence store."""
    return await manager.stats()
