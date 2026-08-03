"""Persistence layer for supplier intelligence.

Stores the historical ``supplier_observations`` series. Scores are computed on
demand from this history by the scoring module — the repository only persists
and retrieves raw observations.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select

from app.infrastructure.repositories.base import BaseRepository
from app.supplier_intel.models import SupplierObservation


class SupplierIntelRepository(BaseRepository[SupplierObservation]):
    """Repository for the `supplier_observations` table."""

    def __init__(self, session) -> None:
        super().__init__(session, SupplierObservation)

    async def create_observation(
        self,
        *,
        supplier_id: str,
        supplier_name: str | None,
        observed_at: datetime | None,
        price: float,
        sale_events: int,
        coupon_events: int,
        inventory_level: float,
        inventory_variance: float,
        stockouts: int,
        shipping_days: float,
        return_policy_score: float,
        customer_service_score: float,
        order_cancellation_rate: float,
        discount_depth: float,
        discount_events: int,
        source: str,
    ) -> SupplierObservation:
        row = SupplierObservation(
            supplier_id=supplier_id,
            supplier_name=supplier_name,
            observed_at=observed_at,
            price=price,
            sale_events=sale_events,
            coupon_events=coupon_events,
            inventory_level=inventory_level,
            inventory_variance=inventory_variance,
            stockouts=stockouts,
            shipping_days=shipping_days,
            return_policy_score=return_policy_score,
            customer_service_score=customer_service_score,
            order_cancellation_rate=order_cancellation_rate,
            discount_depth=discount_depth,
            discount_events=discount_events,
            source=source,
        )
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        return row

    async def get_observation(self, observation_id: UUID) -> SupplierObservation | None:
        result = await self._session.execute(
            select(SupplierObservation).where(SupplierObservation.id == observation_id)
        )
        return result.scalar_one_or_none()

    async def list_observations(
        self,
        *,
        supplier_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[SupplierObservation], int]:
        statement = select(SupplierObservation)
        if supplier_id:
            statement = statement.where(SupplierObservation.supplier_id == supplier_id)
        total = await self._count(statement)
        statement = (
            statement.order_by(SupplierObservation.observed_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.execute(statement)
        return list(result.scalars().all()), total

    async def observations_for(self, supplier_id: str) -> list[SupplierObservation]:
        """Return the FULL history for a supplier (for scoring)."""
        result = await self._session.execute(
            select(SupplierObservation)
            .where(SupplierObservation.supplier_id == supplier_id)
            .order_by(SupplierObservation.observed_at.asc())
        )
        return list(result.scalars().all())

    async def suppliers(self) -> list[str]:
        result = await self._session.execute(
            select(SupplierObservation.supplier_id).distinct()
        )
        return [r[0] for r in result.all()]

    async def stats(self) -> dict[str, Any]:
        total = await self._session.execute(
            select(func.count()).select_from(SupplierObservation)
        )
        by_supplier = await self._session.execute(
            select(
                SupplierObservation.supplier_id, func.count()
            ).group_by(SupplierObservation.supplier_id)
        )
        suppliers = await self._session.execute(
            select(SupplierObservation.supplier_id).distinct()
        )
        return {
            "total_observations": int(total.scalar_one()),
            "suppliers": len(suppliers.all()),
            "observations_by_supplier": {r[0]: int(r[1]) for r in by_supplier.all()},
        }

    async def _count(self, statement: Any) -> int:
        result = await self._session.execute(
            select(func.count()).select_from(statement.subquery())
        )
        return int(result.scalar_one())
