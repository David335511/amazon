"""Forecasting API.

The router talks ONLY to `ForecastingManager` (via DI); it contains no
forecasting logic itself. It exposes forecast (single + batch), stored-forecast
retrieval, realized-outcome recording (which powers historical accuracy),
accuracy, capabilities and stats.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.dependencies import get_forecasting_manager
from app.forecasting import (
    AccuracyRead,
    ForecastActualRead,
    ForecastActualRequest,
    ForecastBatchRequest,
    ForecastingCapabilities,
    ForecastingManager,
    ForecastingStats,
    ForecastList,
    ForecastRead,
    ForecastRequest,
    ForecastTarget,
    ModelDefinition,
)
from app.forecasting.errors import (
    ForecastNotFoundError,
    ForecastValidationError,
)

router = APIRouter(prefix="/forecasting", tags=["forecasting"])

ManagerDep = Annotated[ForecastingManager, Depends(get_forecasting_manager)]


@router.get("/capabilities", response_model=ForecastingCapabilities)
async def capabilities(manager: ManagerDep) -> ForecastingCapabilities:
    """Report which targets and models this deployment supports."""
    return manager.capabilities()


@router.get("/models", response_model=list[ModelDefinition])
async def models(manager: ManagerDep) -> list[ModelDefinition]:
    """List the registered forecasting models (code, not DB)."""
    return manager.model_definitions()


@router.post("/forecast", response_model=ForecastRead, status_code=status.HTTP_201_CREATED)
async def forecast(request: ForecastRequest, manager: ManagerDep) -> ForecastRead:
    """Forecast a target for an entity and store the result."""
    try:
        return await manager.forecast(request)
    except ForecastValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.post("/batch", response_model=list[ForecastRead])
async def forecast_batch(
    request: ForecastBatchRequest, manager: ManagerDep
) -> list[ForecastRead]:
    """Forecast many entities/targets in one call."""
    try:
        return await manager.forecast_batch(request)
    except ForecastValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.get("/forecasts", response_model=ForecastList)
async def list_forecasts(
    manager: ManagerDep,
    target: ForecastTarget | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    model: str | None = None,
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> ForecastList:
    """List stored forecasts, optionally filtered."""
    return await manager.list_forecasts(
        target=target,
        entity_type=entity_type,
        entity_id=entity_id,
        model=model,
        limit=limit,
        offset=offset,
    )


@router.get("/forecasts/{forecast_id}", response_model=ForecastRead)
async def get_forecast(manager: ManagerDep, forecast_id: UUID) -> ForecastRead:
    """Return a stored forecast with its historical accuracy."""
    try:
        return await manager.get_forecast(forecast_id)
    except ForecastNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/forecasts/{forecast_id}/actual", response_model=ForecastActualRead, status_code=status.HTTP_201_CREATED)
async def record_actual_for_forecast(
    manager: ManagerDep,
    forecast_id: UUID,
    body: ForecastActualRequest,
) -> ForecastActualRead:
    """Record the realized outcome for a specific stored forecast."""
    body.forecast_id = forecast_id
    return await _record_actual(manager, body)


@router.post("/actuals", response_model=ForecastActualRead, status_code=status.HTTP_201_CREATED)
async def record_actual(manager: ManagerDep, body: ForecastActualRequest) -> ForecastActualRead:
    """Record a realized outcome (by forecast_id or target+entity)."""
    return await _record_actual(manager, body)


@router.get("/accuracy", response_model=list[AccuracyRead])
async def accuracy(
    manager: ManagerDep,
    model: str | None = None,
    target: ForecastTarget | None = None,
) -> list[AccuracyRead]:
    """Historical accuracy (MAE / MAPE / RMSE / bias) per model and target."""
    return await manager.accuracy(model=model, target=target)


@router.get("/stats", response_model=ForecastingStats)
async def stats(manager: ManagerDep) -> ForecastingStats:
    """Aggregate statistics over the forecasting store."""
    return await manager.stats()


async def _record_actual(manager: ForecastingManager, body: ForecastActualRequest) -> ForecastActualRead:
    try:
        return await manager.record_actual(body)
    except ForecastValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    except ForecastNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
