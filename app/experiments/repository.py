"""Persistence layer for the experimentation platform.

Stores experiments, variants, deterministic assignments, observations and
reports. The uniqueness constraints (one assignment and one observation per
experiment + subject) guarantee that replaying the same subject stream never
duplicates data — a key part of reproducibility.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select

from app.experiments.models import (
    Assignment,
    Experiment,
    ExperimentReport,
    Observation,
    Variant,
)
from app.infrastructure.repositories.base import BaseRepository


class ExperimentRepository(BaseRepository[Experiment]):
    """Repository for all experimentation tables."""

    def __init__(self, session) -> None:
        super().__init__(session, Experiment)

    # ── Experiments ───────────────────────────────────────────────────────

    async def create_experiment(self, **kwargs: Any) -> Experiment:
        row = Experiment(**kwargs)
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        return row

    async def update_experiment(self, experiment: Experiment, **kwargs: Any) -> Experiment:
        for key, value in kwargs.items():
            if value is not None and hasattr(experiment, key):
                setattr(experiment, key, value)
        await self._session.flush()
        await self._session.refresh(experiment)
        return experiment

    async def list_experiments(
        self,
        *,
        experiment_type: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Experiment], int]:
        statement = select(Experiment)
        if experiment_type:
            statement = statement.where(Experiment.experiment_type == experiment_type)
        if status:
            statement = statement.where(Experiment.status == status)
        total = await self._count(statement)
        statement = (
            statement.order_by(Experiment.created_at.desc()).offset(offset).limit(limit)
        )
        result = await self._session.execute(statement)
        return list(result.scalars().all()), total

    async def count_for(self, kind: str) -> int:
        return await self._count(select(Experiment).where(Experiment.experiment_type == kind))

    async def stats(self) -> dict[str, Any]:
        total = await self._session.execute(select(func.count()).select_from(Experiment))
        by_type = await self._session.execute(
            select(Experiment.experiment_type, func.count()).group_by(Experiment.experiment_type)
        )
        by_status = await self._session.execute(
            select(Experiment.status, func.count()).group_by(Experiment.status)
        )
        variants = await self._session.execute(
            select(func.count()).select_from(Variant)
        )
        assignments = await self._session.execute(
            select(func.count()).select_from(Assignment)
        )
        observations = await self._session.execute(
            select(func.count()).select_from(Observation)
        )
        reports = await self._session.execute(
            select(func.count()).select_from(ExperimentReport)
        )
        return {
            "total_experiments": int(total.scalar_one()),
            "by_type": {r[0]: int(r[1]) for r in by_type.all()},
            "by_status": {r[0]: int(r[1]) for r in by_status.all()},
            "total_variants": int(variants.scalar_one()),
            "total_assignments": int(assignments.scalar_one()),
            "total_observations": int(observations.scalar_one()),
            "total_reports": int(reports.scalar_one()),
        }

    # ── Variants ──────────────────────────────────────────────────────────

    async def create_variant(self, **kwargs: Any) -> Variant:
        row = Variant(**kwargs)
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        return row

    async def list_variants(self, experiment_id: uuid.UUID) -> list[Variant]:
        result = await self._session.execute(
            select(Variant)
            .where(Variant.experiment_id == experiment_id)
            .order_by(Variant.created_at.asc())
        )
        return list(result.scalars().all())

    async def get_variant(self, experiment_id: uuid.UUID, key: str) -> Variant | None:
        result = await self._session.execute(
            select(Variant).where(
                Variant.experiment_id == experiment_id, Variant.key == key
            )
        )
        return result.scalar_one_or_none()

    async def count_variants(self, experiment_id: uuid.UUID) -> int:
        return await self._count(
            select(Variant).where(Variant.experiment_id == experiment_id)
        )

    # ── Assignments ───────────────────────────────────────────────────────

    async def get_assignment(self, experiment_id: uuid.UUID, subject_key: str) -> Assignment | None:
        result = await self._session.execute(
            select(Assignment).where(
                Assignment.experiment_id == experiment_id,
                Assignment.subject_key == subject_key,
            )
        )
        return result.scalar_one_or_none()

    async def create_assignment(self, **kwargs: Any) -> Assignment:
        row = Assignment(**kwargs)
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        return row

    async def list_assignments(
        self, experiment_id: uuid.UUID, limit: int = 50, offset: int = 0
    ) -> tuple[list[Assignment], int]:
        statement = select(Assignment).where(Assignment.experiment_id == experiment_id)
        total = await self._count(statement)
        statement = statement.order_by(Assignment.created_at.desc()).offset(offset).limit(limit)
        result = await self._session.execute(statement)
        return list(result.scalars().all()), total

    async def count_assignments(self, experiment_id: uuid.UUID) -> int:
        return await self._count(
            select(Assignment).where(Assignment.experiment_id == experiment_id)
        )

    # ── Observations ──────────────────────────────────────────────────────

    async def get_observation(self, experiment_id: uuid.UUID, subject_key: str) -> Observation | None:
        result = await self._session.execute(
            select(Observation).where(
                Observation.experiment_id == experiment_id,
                Observation.subject_key == subject_key,
            )
        )
        return result.scalar_one_or_none()

    async def create_observation(self, **kwargs: Any) -> Observation:
        row = Observation(**kwargs)
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        return row

    async def update_observation(self, observation: Observation, **kwargs: Any) -> Observation:
        """Update an existing observation in place (keeps the subject's row)."""
        for key, value in kwargs.items():
            setattr(observation, key, value)
        await self._session.flush()
        await self._session.refresh(observation)
        return observation

    async def list_observations(
        self,
        experiment_id: uuid.UUID,
        *,
        variant_id: uuid.UUID | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[Observation], int]:
        statement = select(Observation).where(Observation.experiment_id == experiment_id)
        if variant_id:
            statement = statement.where(Observation.variant_id == variant_id)
        total = await self._count(statement)
        statement = statement.order_by(Observation.recorded_at.desc()).offset(offset).limit(limit)
        result = await self._session.execute(statement)
        return list(result.scalars().all()), total

    async def count_observations(self, experiment_id: uuid.UUID) -> int:
        return await self._count(
            select(Observation).where(Observation.experiment_id == experiment_id)
        )

    # ── Reports ───────────────────────────────────────────────────────────

    async def create_report(self, **kwargs: Any) -> ExperimentReport:
        row = ExperimentReport(**kwargs)
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        return row

    async def latest_report(self, experiment_id: uuid.UUID) -> ExperimentReport | None:
        result = await self._session.execute(
            select(ExperimentReport)
            .where(ExperimentReport.experiment_id == experiment_id)
            .order_by(ExperimentReport.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_reports(
        self, experiment_id: uuid.UUID, limit: int = 20, offset: int = 0
    ) -> tuple[list[ExperimentReport], int]:
        statement = select(ExperimentReport).where(
            ExperimentReport.experiment_id == experiment_id
        )
        total = await self._count(statement)
        statement = statement.order_by(ExperimentReport.created_at.desc()).offset(offset).limit(limit)
        result = await self._session.execute(statement)
        return list(result.scalars().all()), total

    async def _count(self, statement: Any) -> int:
        result = await self._session.execute(
            select(func.count()).select_from(statement.subquery())
        )
        return int(result.scalar_one())


def observation_view(o: Observation, variant_key: str) -> dict[str, Any]:
    """Project an observation row into the shape the stats engine expects."""
    return {
        "variant_key": variant_key,
        "outcome": o.outcome,
        "profit": o.profit,
        "roi": o.roi,
        "value": o.value,
        "predicted": o.predicted,
        "ground_truth": o.ground_truth,
    }


def ensure_aware(dt: datetime) -> datetime:
    """Attach UTC to a naive datetime if needed."""
    if dt.tzinfo is not None:
        return dt
    return dt.replace(tzinfo=UTC)
