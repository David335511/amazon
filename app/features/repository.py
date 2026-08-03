"""Persistence layer for the feature engineering platform.

The `feature_values` table holds the current computed value per
(feature_key, entity_type, entity_id) — compute-once-and-reuse. The repository
provides the latest-value read, list, upsert (insert or overwrite on refresh),
and aggregate stats.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, or_, select

from app.features.models import FeatureValue
from app.infrastructure.repositories.base import BaseRepository


class FeatureRepository(BaseRepository[FeatureValue]):
    """Repository for the `feature_values` table."""

    def __init__(self, session) -> None:
        super().__init__(session, FeatureValue)

    # ── Reads ────────────────────────────────────────────────────────────

    async def get_latest(
        self,
        feature_key: str,
        entity_type: str,
        entity_id: str,
    ) -> FeatureValue | None:
        result = await self._session.execute(
            select(FeatureValue)
            .where(
                FeatureValue.feature_key == feature_key,
                FeatureValue.entity_type == entity_type,
                FeatureValue.entity_id == entity_id,
            )
            .limit(1),
        )
        return result.scalar_one_or_none()

    async def list_values(
        self,
        *,
        feature_key: str | None = None,
        entity_type: str | None = None,
        entity_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[FeatureValue], int]:
        statement = select(FeatureValue)
        if feature_key:
            statement = statement.where(FeatureValue.feature_key == feature_key)
        if entity_type:
            statement = statement.where(FeatureValue.entity_type == entity_type)
        if entity_id:
            statement = statement.where(FeatureValue.entity_id == entity_id)
        total = await self._count(statement)
        statement = (
            statement.order_by(FeatureValue.computed_at.desc()).offset(offset).limit(limit)
        )
        result = await self._session.execute(statement)
        return list(result.scalars().all()), total

    async def count_stale(self, now: datetime | None = None) -> int:
        """Number of stored values past their refresh point."""
        cutoff = now or datetime.now(UTC)
        result = await self._session.execute(
            select(func.count()).select_from(FeatureValue).where(
                or_(FeatureValue.stale_after.is_(None), FeatureValue.stale_after < cutoff),
            ),
        )
        return int(result.scalar_one())

    # ── Writes ───────────────────────────────────────────────────────────

    async def upsert(
        self,
        *,
        feature_key: str,
        entity_type: str,
        entity_id: str,
        value_type: str,
        numeric_value: float | None,
        value_json: str,
        confidence: float,
        version: str,
        computed_at: datetime,
        stale_after: datetime | None,
        lineage_json: str | None,
    ) -> FeatureValue:
        """Insert a fresh value or overwrite the existing one (compute-once)."""
        existing = await self.get_latest(feature_key, entity_type, entity_id)
        if existing is not None:
            existing.value_type = value_type
            existing.numeric_value = numeric_value
            existing.value_json = value_json
            existing.confidence = confidence
            existing.version = version
            existing.computed_at = computed_at
            existing.stale_after = stale_after
            existing.lineage_json = lineage_json
            await self._session.flush()
            await self._session.refresh(existing)
            return existing
        row = FeatureValue(
            feature_key=feature_key,
            entity_type=entity_type,
            entity_id=entity_id,
            value_type=value_type,
            numeric_value=numeric_value,
            value_json=value_json,
            confidence=confidence,
            version=version,
            computed_at=computed_at,
            stale_after=stale_after,
            lineage_json=lineage_json,
        )
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        return row

    # ── Stats ────────────────────────────────────────────────────────────

    async def stats(self) -> dict[str, Any]:
        total = await self._session.execute(select(func.count()).select_from(FeatureValue))
        by_feature = await self._session.execute(
            select(FeatureValue.feature_key, func.count()).group_by(FeatureValue.feature_key),
        )
        return {
            "total_values": int(total.scalar_one()),
            "by_feature": {row[0]: int(row[1]) for row in by_feature.all()},
            "stale_values": await self.count_stale(),
        }

    # ── Helpers ──────────────────────────────────────────────────────────

    async def _count(self, statement: Any) -> int:
        result = await self._session.execute(
            select(func.count()).select_from(statement.subquery()),
        )
        return int(result.scalar_one())
