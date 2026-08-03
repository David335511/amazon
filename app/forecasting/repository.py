"""Persistence layer for the forecasting platform.

Stores ``forecasts`` (with full provenance and an input-series snapshot) and
``forecast_actuals`` (realized outcomes). Historical accuracy (MAE / MAPE /
RMSE / bias) is computed on demand per (model, target) from the actuals joined
to the forecasts they verify — always current, no cached aggregates to drift.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select

from app.forecasting.models import Forecast, ForecastActual
from app.infrastructure.repositories.base import BaseRepository


class ForecastingRepository(BaseRepository[Forecast]):
    """Repository for the `forecasts` and `forecast_actuals` tables."""

    def __init__(self, session) -> None:
        super().__init__(session, Forecast)

    # ── Forecasts ─────────────────────────────────────────────────────────

    async def create_forecast(
        self,
        *,
        target: str,
        entity_type: str,
        entity_id: str,
        horizon: int,
        model_name: str,
        method: str,
        version: str,
        prediction: float,
        lower: float,
        upper: float,
        confidence: float,
        explanation: str,
        used_models_json: str,
        series_json: str,
        features_json: str | None,
        metadata_json: str | None,
        frequency: str | None,
        as_of: datetime | None,
    ) -> Forecast:
        row = Forecast(
            target=target,
            entity_type=entity_type,
            entity_id=entity_id,
            horizon=horizon,
            model_name=model_name,
            method=method,
            version=version,
            prediction=prediction,
            lower=lower,
            upper=upper,
            confidence=confidence,
            explanation=explanation,
            used_models_json=used_models_json,
            series_json=series_json,
            features_json=features_json,
            metadata_json=metadata_json,
            frequency=frequency,
            as_of=as_of,
        )
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        return row

    async def get_forecast(self, forecast_id: UUID) -> Forecast | None:
        result = await self._session.execute(
            select(Forecast).where(Forecast.id == forecast_id)
        )
        return result.scalar_one_or_none()

    async def list_forecasts(
        self,
        *,
        target: str | None = None,
        entity_type: str | None = None,
        entity_id: str | None = None,
        model: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[Forecast], int]:
        statement = select(Forecast)
        if target:
            statement = statement.where(Forecast.target == target)
        if entity_type:
            statement = statement.where(Forecast.entity_type == entity_type)
        if entity_id:
            statement = statement.where(Forecast.entity_id == entity_id)
        if model:
            statement = statement.where(Forecast.model_name == model)
        total = await self._count(statement)
        statement = (
            statement.order_by(Forecast.created_at.desc()).offset(offset).limit(limit)
        )
        result = await self._session.execute(statement)
        return list(result.scalars().all()), total

    # ── Actuals ───────────────────────────────────────────────────────────

    async def record_actual(
        self,
        *,
        forecast: Forecast,
        actual_value: float,
        as_of: datetime | None,
    ) -> ForecastActual:
        row = ForecastActual(
            forecast_id=forecast.id,
            model_name=forecast.model_name,
            target=forecast.target,
            entity_type=forecast.entity_type,
            entity_id=forecast.entity_id,
            as_of=as_of,
            actual_value=actual_value,
        )
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        return row

    async def get_actuals_for_forecast(self, forecast_id: UUID) -> list[ForecastActual]:
        result = await self._session.execute(
            select(ForecastActual).where(ForecastActual.forecast_id == forecast_id)
        )
        return list(result.scalars().all())

    # ── Accuracy (computed on demand) ─────────────────────────────────────

    async def accuracy_all(self) -> list[dict[str, Any]]:
        """Historical accuracy per (model, target) computed from actuals."""
        statement = (
            select(
                ForecastActual.model_name,
                ForecastActual.target,
                Forecast.prediction,
                ForecastActual.actual_value,
            )
            .join(Forecast, Forecast.id == ForecastActual.forecast_id)
        )
        result = await self._session.execute(statement)

        by_key: dict[tuple[str, str], list[tuple[float, float]]] = defaultdict(list)
        for model_name, target, prediction, actual in result.all():
            by_key[(model_name, target)].append((prediction, actual))

        out: list[dict[str, Any]] = []
        for (model_name, target), pairs in sorted(by_key.items()):
            errors = [actual - pred for pred, actual in pairs]
            abs_errors = [abs(e) for e in errors]
            mae = sum(abs_errors) / len(errors)
            mape = sum(
                abs(e) / max(abs(actual), 1e-9) for _, actual, e in pairs_with_errors(pairs, errors)
            ) / len(errors)
            rmse = (sum(e * e for e in errors) / len(errors)) ** 0.5
            bias = sum(errors) / len(errors)
            out.append(
                {
                    "model_name": model_name,
                    "target": target,
                    "sample_count": len(pairs),
                    "mae": mae,
                    "mape": mape,
                    "rmse": rmse,
                    "bias": bias,
                }
            )
        return out

    # ── Stats ─────────────────────────────────────────────────────────────

    async def stats(self) -> dict[str, Any]:
        total = await self._session.execute(select(func.count()).select_from(Forecast))
        by_target = await self._session.execute(
            select(Forecast.target, func.count()).group_by(Forecast.target)
        )
        by_model = await self._session.execute(
            select(Forecast.model_name, func.count()).group_by(Forecast.model_name)
        )
        actuals = await self._session.execute(
            select(func.count()).select_from(ForecastActual)
        )
        return {
            "total_forecasts": int(total.scalar_one()),
            "by_target": {r[0]: int(r[1]) for r in by_target.all()},
            "by_model": {r[0]: int(r[1]) for r in by_model.all()},
            "total_actuals": int(actuals.scalar_one()),
        }

    # ── Helpers ───────────────────────────────────────────────────────────

    async def _count(self, statement: Any) -> int:
        result = await self._session.execute(
            select(func.count()).select_from(statement.subquery())
        )
        return int(result.scalar_one())


def pairs_with_errors(pairs, errors):  # type: ignore[no-untyped-def]
    """Pair (prediction, actual) with its signed error for MAPE computation."""
    for (pred, actual), err in zip(pairs, errors, strict=True):
        yield pred, actual, err
