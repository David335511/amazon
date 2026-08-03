"""Persistence layer for the continuous-learning platform."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select

from app.infrastructure.repositories.base import BaseRepository
from app.learning.models import (
    LearningPrediction,
    LearningRecommendation,
    LearningRun,
    RecommendationStatus,
)


class LearningRepository(BaseRepository[LearningPrediction]):
    """Repository for prediction / recommendation / run tables."""

    def __init__(self, session) -> None:
        super().__init__(session, LearningPrediction)

    # ── Predictions ───────────────────────────────────────────────────────

    async def create_prediction(self, **kwargs: Any) -> LearningPrediction:
        row = LearningPrediction(**kwargs)
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        return row

    async def update_prediction(self, prediction: LearningPrediction, **kwargs: Any) -> LearningPrediction:
        for key, value in kwargs.items():
            if value is not None and hasattr(prediction, key):
                setattr(prediction, key, value)
        await self._session.flush()
        await self._session.refresh(prediction)
        return prediction

    async def get_by_external_id(self, external_id: str) -> LearningPrediction | None:
        result = await self._session.execute(
            select(LearningPrediction).where(LearningPrediction.external_id == external_id)
        )
        return result.scalar_one_or_none()

    async def find_unresolved(
        self,
        *,
        prediction_type: str,
        subject_key: str,
        decision_id: str | None,
        model_version: str | None,
        limit: int = 10,
    ) -> list[LearningPrediction]:
        statement = (
            select(LearningPrediction)
            .where(
                LearningPrediction.prediction_type == prediction_type,
                LearningPrediction.subject_key == subject_key,
                LearningPrediction.actual_value.is_(None),
            )
            .order_by(LearningPrediction.predicted_at.desc())
        )
        if decision_id:
            statement = statement.where(LearningPrediction.decision_id == decision_id)
        if model_version:
            statement = statement.where(LearningPrediction.model_version == model_version)
        result = await self._session.execute(statement.limit(limit))
        return list(result.scalars().all())

    async def list_predictions(
        self,
        *,
        prediction_type: str | None = None,
        decision_type: str | None = None,
        model_version: str | None = None,
        resolved_only: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[LearningPrediction], int]:
        statement = select(LearningPrediction)
        if prediction_type:
            statement = statement.where(LearningPrediction.prediction_type == prediction_type)
        if decision_type:
            statement = statement.where(LearningPrediction.decision_type == decision_type)
        if model_version:
            statement = statement.where(LearningPrediction.model_version == model_version)
        if resolved_only:
            statement = statement.where(LearningPrediction.actual_value.is_not(None))
        total = await self._count(statement)
        statement = (
            statement.order_by(LearningPrediction.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.execute(statement)
        return list(result.scalars().all()), total

    async def resolved_predictions(
        self, *, limit: int = 5000, prediction_type: str | None = None
    ) -> list[LearningPrediction]:
        statement = (
            select(LearningPrediction)
            .where(LearningPrediction.actual_value.is_not(None))
            .order_by(LearningPrediction.created_at.asc())
        )
        if prediction_type:
            statement = statement.where(LearningPrediction.prediction_type == prediction_type)
        result = await self._session.execute(statement.limit(limit))
        return list(result.scalars().all())

    # ── Runs ──────────────────────────────────────────────────────────────

    async def next_run_number(self) -> int:
        result = await self._session.execute(select(func.max(LearningRun.run_number)))
        max_number = result.scalar_one()
        return int(max_number) + 1 if max_number is not None else 1

    async def create_run(self, **kwargs: Any) -> LearningRun:
        row = LearningRun(**kwargs)
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        return row

    async def update_run(self, run: LearningRun, **kwargs: Any) -> LearningRun:
        for key, value in kwargs.items():
            if value is not None and hasattr(run, key):
                setattr(run, key, value)
        await self._session.flush()
        await self._session.refresh(run)
        return run

    async def get_run(self, run_id: uuid.UUID) -> LearningRun | None:
        result = await self._session.execute(
            select(LearningRun).where(LearningRun.id == run_id)
        )
        return result.scalar_one_or_none()

    async def latest_run(self) -> LearningRun | None:
        result = await self._session.execute(
            select(LearningRun).order_by(LearningRun.run_number.desc()).limit(1)
        )
        return result.scalar_one_or_none()

    async def list_runs(self, limit: int = 50, offset: int = 0) -> tuple[list[LearningRun], int]:
        statement = select(LearningRun)
        total = await self._count(statement)
        statement = statement.order_by(LearningRun.run_number.desc()).offset(offset).limit(limit)
        result = await self._session.execute(statement)
        return list(result.scalars().all()), total

    # ── Recommendations ───────────────────────────────────────────────────

    async def create_recommendation(self, **kwargs: Any) -> LearningRecommendation:
        row = LearningRecommendation(**kwargs)
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        return row

    async def list_recommendations(
        self,
        *,
        status: str | None = None,
        target_type: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[LearningRecommendation], int]:
        statement = select(LearningRecommendation)
        if status:
            statement = statement.where(LearningRecommendation.status == status)
        if target_type:
            statement = statement.where(LearningRecommendation.target_type == target_type)
        total = await self._count(statement)
        statement = statement.order_by(LearningRecommendation.severity.desc()).offset(offset).limit(limit)
        result = await self._session.execute(statement)
        return list(result.scalars().all()), total

    async def get_recommendation(self, rec_id: uuid.UUID) -> LearningRecommendation | None:
        result = await self._session.execute(
            select(LearningRecommendation).where(LearningRecommendation.id == rec_id)
        )
        return result.scalar_one_or_none()

    async def update_recommendation_status(
        self, recommendation: LearningRecommendation, status: str
    ) -> LearningRecommendation:
        recommendation.status = status
        await self._session.flush()
        await self._session.refresh(recommendation)
        return recommendation

    async def count_recommendations(self, status: str | None = None) -> int:
        statement = select(LearningRecommendation)
        if status:
            statement = statement.where(LearningRecommendation.status == status)
        return await self._count(statement)

    async def count_resolved(self) -> int:
        return await self._count(
            select(LearningPrediction).where(LearningPrediction.actual_value.is_not(None))
        )

    async def count_unresolved(self) -> int:
        return await self._count(
            select(LearningPrediction).where(LearningPrediction.actual_value.is_(None))
        )

    async def stats(self) -> dict[str, Any]:
        total = await self._count(select(LearningPrediction))
        resolved = await self.count_resolved()
        by_type = await self._session.execute(
            select(LearningPrediction.prediction_type, func.count())
            .group_by(LearningPrediction.prediction_type)
        )
        open_recs = await self.count_recommendations(RecommendationStatus.OPEN.value)
        completed_runs = await self._count(
            select(LearningRun).where(LearningRun.status == "completed")
        )
        last_run = await self.latest_run()
        return {
            "total_predictions": int(total),
            "resolved_predictions": int(resolved),
            "unresolved_predictions": int(total - resolved),
            "open_recommendations": int(open_recs),
            "runs_completed": int(completed_runs),
            "last_run_number": last_run.run_number if last_run else None,
            "by_prediction_type": {r[0]: int(r[1]) for r in by_type.all()},
        }

    async def _count(self, statement: Any) -> int:
        result = await self._session.execute(
            select(func.count()).select_from(statement.subquery())
        )
        return int(result.scalar_one())


def ensure_aware(dt: datetime) -> datetime:
    """Attach UTC to a naive datetime if needed."""
    if dt.tzinfo is not None:
        return dt
    return dt.replace(tzinfo=UTC)
