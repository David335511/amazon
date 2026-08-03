"""Forecasting facade.

`ForecastingManager` is the ONLY entry point for producing, storing, retrieving
and scoring forecasts. It owns the model registry and the repository:

- **Modular models**: statistical (always), ML (sklearn, opt-in), LLM reasoning
  (opt-in), and `ensemble` (inverse-variance combination) — all behind the same
  `ForecastModel` interface.
- **Full provenance**: every stored forecast carries its method, version,
  confidence interval, explanation, ensemble members and an input-series
  snapshot.
- **Historical accuracy**: recording a realized outcome (via `record_actual`)
  makes every subsequent forecast report the model's actual MAE / MAPE / RMSE /
  bias for that target.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from app.forecasting.base import ForecastConfig, ForecastContext, ForecastTarget
from app.forecasting.errors import (
    ForecastNotFoundError,
    ForecastValidationError,
)
from app.forecasting.registry import build_models
from app.forecasting.repository import ForecastingRepository
from app.forecasting.schemas import (
    AccuracyRead,
    ForecastActualRead,
    ForecastActualRequest,
    ForecastBatchRequest,
    ForecastingCapabilities,
    ForecastingStats,
    ForecastList,
    ForecastRead,
    ForecastRequest,
    ModelDefinition,
)


class ForecastingManager:
    """Facade for the forecasting platform."""

    def __init__(
        self,
        repository: ForecastingRepository,
        config: ForecastConfig | None = None,
        models: dict[str, Any] | None = None,
    ) -> None:
        self._repo = repository
        self._config = config or ForecastConfig()
        self._models = models or build_models(self._config)

    # ── Introspection ────────────────────────────────────────────────────

    def model_definitions(self) -> list[ModelDefinition]:
        return [
            ModelDefinition(
                name=model.name,
                method=model.method,
                version=model.version,
                family=model.family,
                supports=list(model.supports),
            )
            for model in self._models.values()
        ]

    def capabilities(self) -> ForecastingCapabilities:
        return ForecastingCapabilities(
            enabled=self._config.enabled,
            targets=list(ForecastTarget),
            models=self.model_definitions(),
            default_model=self._config.default_model,
            max_horizon=self._config.max_horizon,
        )

    # ── Forecast ──────────────────────────────────────────────────────────

    async def forecast(self, request: ForecastRequest) -> ForecastRead:
        self._validate(request)
        model = self._resolve_model(request.model)
        ctx = ForecastContext(
            target=request.target,
            entity_type=request.entity_type,
            entity_id=request.entity_id,
            horizon=request.horizon,
            series=request.series,
            frequency=request.frequency,
            features=request.features,
            metadata=request.metadata,
        )
        result = model.forecast(ctx)

        accuracy = await self._repo.accuracy_all()
        acc = _find_accuracy(accuracy, model.name, request.target)

        row = await self._repo.create_forecast(
            target=request.target.value,
            entity_type=request.entity_type,
            entity_id=request.entity_id,
            horizon=request.horizon,
            model_name=model.name,
            method=model.method,
            version=model.version,
            prediction=result.prediction,
            lower=result.lower,
            upper=result.upper,
            confidence=result.confidence,
            explanation=result.explanation,
            used_models_json=json.dumps(result.used_models),
            series_json=json.dumps(request.series),
            features_json=json.dumps(request.features) if request.features else None,
            metadata_json=json.dumps(request.metadata) if request.metadata else None,
            frequency=request.frequency,
            as_of=request.as_of,
        )
        return ForecastRead.from_row(row, historical_accuracy=acc)

    async def forecast_batch(self, request: ForecastBatchRequest) -> list[ForecastRead]:
        if len(request.requests) > self._config.max_batch_size:
            raise ForecastValidationError(
                f"Batch size {len(request.requests)} exceeds max {self._config.max_batch_size}"
            )
        out = []
        for item in request.requests:
            out.append(
                await self.forecast(
                    ForecastRequest(
                        target=item.target,
                        entity_type=item.entity_type,
                        entity_id=item.entity_id,
                        horizon=item.horizon,
                        series=item.series,
                        frequency=item.frequency,
                        features=item.features,
                        metadata=item.metadata,
                        model=item.model,
                    )
                )
            )
        return out

    # ── Retrieve ──────────────────────────────────────────────────────────

    async def get_forecast(self, forecast_id: UUID) -> ForecastRead:
        row = await self._repo.get_forecast(forecast_id)
        if row is None:
            raise ForecastNotFoundError(f"Forecast {forecast_id} not found")
        accuracy = await self._repo.accuracy_all()
        acc = _find_accuracy(accuracy, row.model_name, row.target)
        return ForecastRead.from_row(row, historical_accuracy=acc)

    async def list_forecasts(
        self,
        *,
        target: ForecastTarget | None = None,
        entity_type: str | None = None,
        entity_id: str | None = None,
        model: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> ForecastList:
        rows, total = await self._repo.list_forecasts(
            target=target.value if target else None,
            entity_type=entity_type,
            entity_id=entity_id,
            model=model,
            limit=limit,
            offset=offset,
        )
        return ForecastList(items=[ForecastRead.from_row(r) for r in rows], total=total)

    # ── Actuals / accuracy ────────────────────────────────────────────────

    async def record_actual(self, request: ForecastActualRequest) -> ForecastActualRead:
        if request.forecast_id is not None:
            forecast = await self._repo.get_forecast(request.forecast_id)
        elif request.target and request.entity_type and request.entity_id:
            forecast = await self._latest_for_entity(
                request.target, request.entity_type, request.entity_id
            )
        else:
            raise ForecastValidationError(
                "Provide either forecast_id or target + entity_type + entity_id"
            )
        if forecast is None:
            raise ForecastNotFoundError("No matching forecast found to record an actual against")
        row = await self._repo.record_actual(
            forecast=forecast,
            actual_value=request.actual_value,
            as_of=request.as_of,
        )
        return ForecastActualRead.from_row(row)

    async def accuracy(
        self,
        *,
        model: str | None = None,
        target: ForecastTarget | None = None,
    ) -> list[AccuracyRead]:
        data = await self._repo.accuracy_all()
        items = []
        for d in data:
            if model and d["model_name"] != model:
                continue
            if target and d["target"] != target.value:
                continue
            items.append(
                AccuracyRead(
                    model_name=d["model_name"],
                    target=ForecastTarget(d["target"]),
                    sample_count=d["sample_count"],
                    mae=d["mae"],
                    mape=d["mape"],
                    rmse=d["rmse"],
                    bias=d["bias"],
                )
            )
        return items

    async def stats(self) -> ForecastingStats:
        return ForecastingStats(**await self._repo.stats())

    # ── Internals ─────────────────────────────────────────────────────────

    def _validate(self, request: ForecastRequest) -> None:
        if request.horizon > self._config.max_horizon:
            raise ForecastValidationError(
                f"Horizon {request.horizon} exceeds max {self._config.max_horizon}"
            )
        if not request.series:
            raise ForecastValidationError("Forecast series must not be empty")

    def _resolve_model(self, requested: str | None):
        name = requested or self._config.default_model
        model = self._models.get(name)
        if model is None:
            known = ", ".join(sorted(self._models)) or "(none)"
            raise ForecastValidationError(f"Unknown forecast model {name!r}. Known: {known}")
        return model

    async def _latest_for_entity(
        self, target: ForecastTarget, entity_type: str, entity_id: str
    ):
        rows, _ = await self._repo.list_forecasts(
            target=target.value,
            entity_type=entity_type,
            entity_id=entity_id,
            limit=1,
            offset=0,
        )
        return rows[0] if rows else None


def _find_accuracy(data: list[dict[str, Any]], model_name: str, target: str) -> dict[str, Any]:
    for d in data:
        if d["model_name"] == model_name and d["target"] == target:
            return d
    return {"sample_count": 0}
