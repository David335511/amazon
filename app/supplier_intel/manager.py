"""Supplier intelligence facade.

`SupplierIntelManager` is the ONLY entry point for recording historical
observations and computing supplier scores / explanations. It owns the
repository and the config:

- **Everything is historical**: scores and explanations are always computed on
  demand over the full stored observation series for a supplier — never a live
  snapshot, never a stale cached aggregate.
- **Pure scoring**: `compute_scores` / `summarize` / `explain` live in
  `app.supplier_intel.scoring` (deterministic, stdlib-only, unit-tested).
- **AI explanation**: a deterministic reasoning narrative over the scores and
  metric summary — a seam for real LLM providers.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from app.supplier_intel.base import TRACKED_METRICS, SupplierScore
from app.supplier_intel.config import SupplierIntelConfig
from app.supplier_intel.errors import (
    SupplierIntelNotFoundError,
    SupplierIntelValidationError,
)
from app.supplier_intel.repository import SupplierIntelRepository
from app.supplier_intel.schemas import (
    ObservationCreate,
    ObservationList,
    ObservationRead,
    ScoreRead,
    SupplierIntelBatchRequest,
    SupplierIntelCapabilities,
    SupplierIntelRead,
    SupplierIntelStats,
)
from app.supplier_intel.scoring import compute_scores, explain, summarize


class SupplierIntelManager:
    """Facade for supplier intelligence."""

    def __init__(
        self,
        repository: SupplierIntelRepository,
        config: SupplierIntelConfig | None = None,
    ) -> None:
        self._repo = repository
        self._config = config or SupplierIntelConfig()

    # ── Introspection ────────────────────────────────────────────────────

    def capabilities(self) -> SupplierIntelCapabilities:
        return SupplierIntelCapabilities(
            enabled=self._config.enabled,
            scores=[s.value for s in SupplierScore],
            tracked_metrics=TRACKED_METRICS,
            max_batch_size=self._config.max_batch_size,
        )

    # ── Record / retrieve history ─────────────────────────────────────────

    async def record_observation(self, request: ObservationCreate) -> ObservationRead:
        observed_at = request.observed_at or datetime.now(UTC)
        row = await self._repo.create_observation(
            supplier_id=request.supplier_id,
            supplier_name=request.supplier_name,
            observed_at=observed_at,
            price=request.price,
            sale_events=request.sale_events,
            coupon_events=request.coupon_events,
            inventory_level=request.inventory_level,
            inventory_variance=request.inventory_variance,
            stockouts=request.stockouts,
            shipping_days=request.shipping_days,
            return_policy_score=request.return_policy_score,
            customer_service_score=request.customer_service_score,
            order_cancellation_rate=request.order_cancellation_rate,
            discount_depth=request.discount_depth,
            discount_events=request.discount_events,
            source=request.source,
        )
        return ObservationRead.from_row(row)

    async def list_observations(
        self,
        *,
        supplier_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> ObservationList:
        rows, total = await self._repo.list_observations(
            supplier_id=supplier_id, limit=limit, offset=offset
        )
        return ObservationList(
            items=[ObservationRead.from_row(r) for r in rows], total=total
        )

    async def suppliers(self) -> list[str]:
        return await self._repo.suppliers()

    async def get_observation(self, observation_id: UUID) -> ObservationRead:
        row = await self._repo.get_observation(observation_id)
        if row is None:
            raise SupplierIntelNotFoundError(f"Observation {observation_id} not found")
        return ObservationRead.from_row(row)

    # ── Scoring / explanation ─────────────────────────────────────────────

    async def scores(self, supplier_id: str) -> dict[str, ScoreRead]:
        obs = await self._repo.observations_for(supplier_id)
        raw = compute_scores(obs, self._config)
        return {
            key: ScoreRead(name=SupplierScore(key), **value)
            for key, value in raw.items()
        }

    async def profile(self, supplier_id: str) -> SupplierIntelRead:
        obs = await self._repo.observations_for(supplier_id)
        if not obs:
            raise SupplierIntelNotFoundError(
                f"No historical observations for supplier {supplier_id!r}"
            )
        raw = compute_scores(obs, self._config)
        metrics = summarize(obs, self._config)
        scores = {
            key: ScoreRead(name=SupplierScore(key), **value)
            for key, value in raw.items()
        }
        return SupplierIntelRead(
            supplier_id=supplier_id,
            supplier_name=obs[-1].supplier_name,
            sample_count=len(obs),
            metrics=metrics,
            scores=scores,
            explanation=explain(raw, metrics),
            computed_at=datetime.now(UTC),
        )

    async def profile_batch(
        self, request: SupplierIntelBatchRequest
    ) -> list[SupplierIntelRead]:
        if len(request.supplier_ids) > self._config.max_batch_size:
            raise SupplierIntelValidationError(
                f"Batch size {len(request.supplier_ids)} exceeds max "
                f"{self._config.max_batch_size}"
            )
        out: list[SupplierIntelRead] = []
        for sid in request.supplier_ids:
            try:
                out.append(await self.profile(sid))
            except SupplierIntelNotFoundError:
                continue
        return out

    async def explain(self, supplier_id: str) -> str:
        obs = await self._repo.observations_for(supplier_id)
        if not obs:
            raise SupplierIntelNotFoundError(
                f"No historical observations for supplier {supplier_id!r}"
            )
        raw = compute_scores(obs, self._config)
        metrics = summarize(obs, self._config)
        return explain(raw, metrics)

    # ── Stats ─────────────────────────────────────────────────────────────

    async def stats(self) -> SupplierIntelStats:
        return SupplierIntelStats(**await self._repo.stats())
