"""Pydantic schemas for the forecasting API."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.forecasting.base import ForecastTarget
from app.forecasting.models import Forecast, ForecastActual


class ForecastRequest(BaseModel):
    """Request to forecast one target for one entity."""

    target: ForecastTarget
    entity_type: str = Field(min_length=1)
    entity_id: str = Field(min_length=1)
    horizon: int = Field(default=1, ge=1, le=36)
    series: list[float] = Field(min_length=1)
    frequency: str | None = None
    features: dict[str, float] = Field(default_factory=dict)
    metadata: dict[str, str] = Field(default_factory=dict)
    # Optional: name a specific model (e.g. "moving_average", "llm_reasoning").
    # When None, the configured default (usually "ensemble") is used.
    model: str | None = None
    # Optional period the historical series ends at.
    as_of: datetime | None = None


class ForecastBatchItem(BaseModel):
    """One item in a batch-forecast request."""

    target: ForecastTarget
    entity_type: str = Field(min_length=1)
    entity_id: str = Field(min_length=1)
    horizon: int = Field(default=1, ge=1, le=36)
    series: list[float] = Field(min_length=1)
    frequency: str | None = None
    features: dict[str, float] = Field(default_factory=dict)
    metadata: dict[str, str] = Field(default_factory=dict)
    model: str | None = None


class ForecastBatchRequest(BaseModel):
    """Request to forecast several entities/targets in one call."""

    requests: list[ForecastBatchItem] = Field(min_length=1)


class ForecastRead(BaseModel):
    """A stored (or just-computed) forecast with its full provenance."""

    id: UUID
    target: ForecastTarget
    entity_type: str
    entity_id: str
    horizon: int
    model_name: str
    method: str
    version: str
    prediction: float
    lower: float
    upper: float
    confidence: float = Field(ge=0.0, le=1.0)
    explanation: str
    used_models: list[str] = Field(default_factory=list)
    historical_accuracy: dict[str, Any] = Field(default_factory=dict)
    series: list[float] = Field(default_factory=list)
    frequency: str | None
    as_of: datetime | None
    created_at: datetime

    @classmethod
    def from_row(cls, row: Forecast, historical_accuracy: dict[str, Any] | None = None) -> ForecastRead:
        import json

        return cls(
            id=row.id,
            target=ForecastTarget(row.target),
            entity_type=row.entity_type,
            entity_id=row.entity_id,
            horizon=row.horizon,
            model_name=row.model_name,
            method=row.method,
            version=row.version,
            prediction=row.prediction,
            lower=row.lower,
            upper=row.upper,
            confidence=row.confidence,
            explanation=row.explanation,
            used_models=json.loads(row.used_models_json) if row.used_models_json else [],
            historical_accuracy=historical_accuracy or {},
            series=json.loads(row.series_json) if row.series_json else [],
            frequency=row.frequency,
            as_of=_as_aware(row.as_of),
            created_at=row.created_at,
        )


class ForecastList(BaseModel):
    """Paginated list of stored forecasts."""

    items: list[ForecastRead]
    total: int


class ForecastActualRequest(BaseModel):
    """Record a realized outcome.

    Provide either ``forecast_id`` (link to an exact forecast) or a
    ``target`` + ``entity_type`` + ``entity_id`` (link to the latest forecast
    for that entity).
    """

    forecast_id: UUID | None = None
    target: ForecastTarget | None = None
    entity_type: str | None = None
    entity_id: str | None = None
    as_of: datetime | None = None
    actual_value: float


class ForecastActualRead(BaseModel):
    """A recorded realized outcome."""

    id: UUID
    forecast_id: UUID
    model_name: str
    target: ForecastTarget
    entity_type: str
    entity_id: str
    actual_value: float
    as_of: datetime | None
    created_at: datetime

    @classmethod
    def from_row(cls, row: ForecastActual) -> ForecastActualRead:
        return cls(
            id=row.id,
            forecast_id=row.forecast_id,
            model_name=row.model_name,
            target=ForecastTarget(row.target),
            entity_type=row.entity_type,
            entity_id=row.entity_id,
            actual_value=row.actual_value,
            as_of=_as_aware(row.as_of),
            created_at=row.created_at,
        )


class AccuracyRead(BaseModel):
    """Historical accuracy of a model on a target (computed from actuals)."""

    model_name: str
    target: ForecastTarget
    sample_count: int
    mae: float | None = None
    mape: float | None = None
    rmse: float | None = None
    bias: float | None = None


class ModelDefinition(BaseModel):
    """Metadata for a registered forecasting model (from code, not DB)."""

    name: str
    method: str
    version: str
    family: str
    supports: list[ForecastTarget]


class ForecastingCapabilities(BaseModel):
    """Which targets / models this deployment supports."""

    enabled: bool
    targets: list[ForecastTarget]
    models: list[ModelDefinition]
    default_model: str
    max_horizon: int


class ForecastingStats(BaseModel):
    """Aggregate statistics over the forecasting store."""

    total_forecasts: int = 0
    by_target: dict[str, int] = Field(default_factory=dict)
    by_model: dict[str, int] = Field(default_factory=dict)
    total_actuals: int = 0


def _as_aware(dt: datetime | None) -> datetime | None:
    if dt is None or dt.tzinfo is not None:
        return dt
    from datetime import UTC

    return dt.replace(tzinfo=UTC)
