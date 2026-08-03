"""Feature engineering API.

The router talks ONLY to `FeatureManager` (via DI); it contains no feature
logic itself. It exposes feature definitions, calculation, refresh, retrieval,
batch calculation, listing and stats.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.dependencies import get_feature_manager
from app.features import (
    FeatureBatchRequest,
    FeatureCalculateRequest,
    FeatureCapabilities,
    FeatureDefinitionRead,
    FeatureManager,
    FeatureStats,
    FeatureValueList,
    FeatureValueRead,
)
from app.features.errors import FeatureNotFoundError, FeatureValidationError

router = APIRouter(prefix="/features", tags=["features"])

ManagerDep = Annotated[FeatureManager, Depends(get_feature_manager)]


# ── Definitions (living documentation) ───────────────────────────────


@router.get("/definitions", response_model=list[FeatureDefinitionRead])
async def list_definitions(manager: ManagerDep) -> list[FeatureDefinitionRead]:
    """List every registered feature with its method, version and signals."""
    return manager.definitions()


@router.get("/definitions/{feature_key}", response_model=FeatureDefinitionRead)
async def get_definition(manager: ManagerDep, feature_key: str) -> FeatureDefinitionRead:
    """Return the definition (method, version, signals) for one feature."""
    try:
        return manager.definition(feature_key)
    except FeatureValidationError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


# ── Introspection ────────────────────────────────────────────────────


@router.get("/capabilities", response_model=FeatureCapabilities)
async def capabilities(manager: ManagerDep) -> FeatureCapabilities:
    """Which features and signal provider this deployment supports."""
    return manager.capabilities()


@router.get("/stats", response_model=FeatureStats)
async def stats(manager: ManagerDep) -> FeatureStats:
    """Aggregate statistics over the stored feature store."""
    return await manager.stats()


# ── Calculation / refresh / batch ────────────────────────────────────


@router.post("/calculate", response_model=FeatureValueRead)
async def calculate(
    manager: ManagerDep,
    request: FeatureCalculateRequest,
) -> FeatureValueRead:
    """Compute a feature (or return the stored fresh value)."""
    try:
        return await manager.calculate(
            request.feature_key,
            request.entity_type,
            request.entity_id,
            force=request.force,
            signals=request.signals or None,
        )
    except FeatureValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.post("/refresh", response_model=FeatureValueRead)
async def refresh(
    manager: ManagerDep,
    request: FeatureCalculateRequest,
) -> FeatureValueRead:
    """Force recomputation and overwrite the stored value."""
    try:
        return await manager.refresh(
            request.feature_key,
            request.entity_type,
            request.entity_id,
            signals=request.signals or None,
        )
    except FeatureValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.post("/batch", response_model=list[FeatureValueRead])
async def calculate_batch(
    manager: ManagerDep,
    request: FeatureBatchRequest,
) -> list[FeatureValueRead]:
    """Compute many feature values in one call."""
    try:
        return await manager.calculate_batch(
            request.requests,
            force=request.force,
            signals=request.signals or None,
        )
    except FeatureValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


# ── Retrieve / list ──────────────────────────────────────────────────


@router.get("/value", response_model=FeatureValueRead)
async def get_value(
    manager: ManagerDep,
    feature_key: str = Query(min_length=1),
    entity_type: str = Query(min_length=1),
    entity_id: str = Query(min_length=1),
) -> FeatureValueRead:
    """Retrieve a stored feature value without recomputing."""
    try:
        return await manager.get(feature_key, entity_type, entity_id)
    except FeatureNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except FeatureValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.get("/values", response_model=FeatureValueList)
async def list_values(
    manager: ManagerDep,
    feature_key: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> FeatureValueList:
    """List stored feature values, optionally filtered."""
    return await manager.list_values(
        feature_key=feature_key,
        entity_type=entity_type,
        entity_id=entity_id,
        limit=limit,
        offset=offset,
    )
