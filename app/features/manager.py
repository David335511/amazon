"""Feature engineering facade.

`FeatureManager` is the ONLY entry point for computing, storing, refreshing and
retrieving feature values. Core behaviours:

- **Compute once, reuse**: `calculate` returns a stored value if it is still
  fresh (`computed_at + ttl`); otherwise it recomputes and persists it.
- **Refresh**: `refresh` forces a recompute and overwrites the stored value.
- **Retrieve**: `get` returns the stored value without recomputing.
- **Batch**: `calculate_batch` computes many features in one call.
- **Full provenance**: every value is stored with version + lineage.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from app.features.base import EntityContext, FeatureComputer
from app.features.config import FeatureConfig
from app.features.errors import FeatureValidationError
from app.features.lineage import build_lineage
from app.features.models import FeatureValue, FeatureValueType
from app.features.registry import feature_registry
from app.features.repository import FeatureRepository
from app.features.schemas import (
    FeatureBatchItem,
    FeatureCapabilities,
    FeatureDefinitionRead,
    FeatureStats,
    FeatureValueList,
    FeatureValueRead,
)
from app.features.signals import SignalBundle, SignalProvider, build_signal_provider


def _as_aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


class FeatureManager:
    """Facade for the feature engineering platform."""

    def __init__(
        self,
        repository: FeatureRepository,
        config: FeatureConfig | None = None,
        signal_provider: SignalProvider | None = None,
    ) -> None:
        self._repo = repository
        self._config = config or FeatureConfig()
        self._signal_provider = signal_provider or build_signal_provider(self._config)
        self._registry = feature_registry()

    # ── Definitions / introspection ──────────────────────────────────────

    def definitions(self) -> list[FeatureDefinitionRead]:
        return [self._definition(cls) for cls in sorted(self._registry.values(), key=lambda c: c.key)]

    def definition(self, feature_key: str) -> FeatureDefinitionRead:
        cls = self._require(feature_key)
        return self._definition(cls)

    def capabilities(self) -> FeatureCapabilities:
        return FeatureCapabilities(
            enabled=self._config.enabled,
            feature_count=len(self._registry),
            features=self.definitions(),
            signal_provider=self._signal_provider.name,
            default_ttl_seconds=self._config.default_ttl_seconds,
        )

    # ── Calculate / refresh / retrieve ───────────────────────────────────

    async def calculate(
        self,
        feature_key: str,
        entity_type: str,
        entity_id: str,
        *,
        force: bool = False,
        signals: dict[str, Any] | None = None,
    ) -> FeatureValueRead:
        """Return a fresh feature value, computing it only if needed."""
        computer = self._require(feature_key)()

        if not force:
            stored = await self._repo.get_latest(feature_key, entity_type, entity_id)
            if stored is not None and self._is_fresh(stored):
                return self._to_read(stored, computer)

        return await self._compute_and_store(computer, entity_type, entity_id, signals)

    async def refresh(
        self,
        feature_key: str,
        entity_type: str,
        entity_id: str,
        *,
        signals: dict[str, Any] | None = None,
    ) -> FeatureValueRead:
        """Force recomputation and overwrite the stored value."""
        computer = self._require(feature_key)()
        return await self._compute_and_store(computer, entity_type, entity_id, signals)

    async def get(
        self,
        feature_key: str,
        entity_type: str,
        entity_id: str,
    ) -> FeatureValueRead:
        """Retrieve the stored value without recomputing."""
        computer = self._require(feature_key)()
        stored = await self._repo.get_latest(feature_key, entity_type, entity_id)
        if stored is None:
            from app.features.errors import FeatureNotFoundError

            raise FeatureNotFoundError(feature_key, entity_type, entity_id)
        return self._to_read(stored, computer)

    async def calculate_batch(
        self,
        requests: list[FeatureBatchItem],
        *,
        force: bool = False,
        signals: dict[str, Any] | None = None,
    ) -> list[FeatureValueRead]:
        """Calculate many feature values in one call (respects batch limit)."""
        if len(requests) > self._config.max_batch_size:
            raise FeatureValidationError(
                f"Batch size {len(requests)} exceeds max {self._config.max_batch_size}"
            )
        results = []
        for item in requests:
            results.append(
                await self.calculate(
                    item.feature_key,
                    item.entity_type,
                    item.entity_id,
                    force=force,
                    signals=signals,
                )
            )
        return results

    # ── List / stats ─────────────────────────────────────────────────────

    async def list_values(
        self,
        *,
        feature_key: str | None = None,
        entity_type: str | None = None,
        entity_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> FeatureValueList:
        items, total = await self._repo.list_values(
            feature_key=feature_key,
            entity_type=entity_type,
            entity_id=entity_id,
            limit=limit,
            offset=offset,
        )
        reads = []
        for row in items:
            computer = self._registry.get(row.feature_key)
            reads.append(self._to_read(row, computer) if computer else self._to_read(row, None))
        return FeatureValueList(items=reads, total=total)

    async def stats(self) -> FeatureStats:
        data = await self._repo.stats()
        return FeatureStats(**data)

    # ── Internals ────────────────────────────────────────────────────────

    def _require(self, feature_key: str) -> type[FeatureComputer]:
        cls = self._registry.get(feature_key)
        if cls is None:
            known = ", ".join(sorted(self._registry)) or "(none)"
            raise FeatureValidationError(f"Unknown feature key: {feature_key!r}. Known: {known}")
        return cls

    async def _compute_and_store(
        self,
        computer: FeatureComputer,
        entity_type: str,
        entity_id: str,
        signals_override: dict[str, Any] | None,
    ) -> FeatureValueRead:
        entity = EntityContext(entity_type=entity_type, entity_id=entity_id)
        bundle = await self._resolve_signals(entity, signals_override)
        result = await computer.compute(entity, bundle)

        now = datetime.now(UTC)
        ttl = computer.ttl_seconds or self._config.default_ttl_seconds
        stale_after = now + timedelta(seconds=ttl)

        value = result.value
        value_type = computer.value_type
        numeric_value = None
        if value_type == FeatureValueType.NUMERIC and isinstance(value, (int, float)):
            numeric_value = float(value)

        lineage = build_lineage(
            feature_key=computer.key,
            method=computer.formula or computer.__class__.__name__,
            version=computer.version,
            computed_at=now,
            value=value,
            used_signals=result.used_signals,
            notes=result.notes,
        )

        row = await self._repo.upsert(
            feature_key=computer.key,
            entity_type=entity_type,
            entity_id=entity_id,
            value_type=value_type.value,
            numeric_value=numeric_value,
            value_json=json.dumps(value),
            confidence=result.confidence,
            version=computer.version,
            computed_at=now,
            stale_after=stale_after,
            lineage_json=json.dumps(lineage),
        )
        return self._to_read(row, computer)

    async def _resolve_signals(
        self,
        entity: EntityContext,
        override: dict[str, Any] | None,
    ) -> SignalBundle:
        base = await self._signal_provider.fetch_signals(entity)
        if not override:
            return base
        extra = build_signal_provider_override(override)
        merged = dict(base._signals)
        merged.update(extra._signals)
        return SignalBundle(merged)

    def _is_fresh(self, row: FeatureValue) -> bool:
        stale = _as_aware(row.stale_after)
        if stale is None:
            return True
        return datetime.now(UTC) < stale

    def _definition(self, cls: type[FeatureComputer]) -> FeatureDefinitionRead:
        return FeatureDefinitionRead(
            key=cls.key,
            name=cls.name,
            description=cls.description,
            formula=cls.formula,
            version=cls.version,
            value_type=cls.value_type,
            required_signals=list(cls.required_signals),
            ttl_seconds=cls.ttl_seconds,
        )

    def _to_read(self, row: FeatureValue, computer: FeatureComputer | None) -> FeatureValueRead:
        value = json.loads(row.value_json) if row.value_json else None
        ttl = (computer.ttl_seconds if computer else None) or self._config.default_ttl_seconds
        return FeatureValueRead(
            id=row.id,
            feature_key=row.feature_key,
            feature_name=computer.name if computer else row.feature_key,
            entity_type=row.entity_type,
            entity_id=row.entity_id,
            value_type=FeatureValueType(row.value_type),
            value=value,
            confidence=row.confidence,
            version=row.version,
            computed_at=row.computed_at,
            stale_after=_as_aware(row.stale_after),
            ttl_seconds=ttl,
            lineage=json.loads(row.lineage_json) if row.lineage_json else {},
        )


def build_signal_provider_override(signals: dict[str, Any]) -> SignalBundle:
    """Wrap caller-provided signal overrides with provenance metadata."""
    from app.features.signals import SignalInfo

    return SignalBundle(
        {k: SignalInfo(value=v, source="override", version="1.0.0") for k, v in signals.items()}
    )
