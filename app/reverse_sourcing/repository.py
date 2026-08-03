"""Persistence layer for reverse sourcing.

Stores ``reverse_sourcing_runs`` and ``reverse_sourcing_offers``. Historical
per-(supplier, ASIN) price / discount series are derived by joining offers to
their runs across time.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func, select

from app.infrastructure.repositories.base import BaseRepository
from app.reverse_sourcing.models import ReverseSourcingOffer, ReverseSourcingRun


class ReverseSourcingRepository(BaseRepository[ReverseSourcingRun]):
    """Repository for reverse-sourcing runs and offers."""

    def __init__(self, session) -> None:
        super().__init__(session, ReverseSourcingRun)

    async def create_run(
        self,
        *,
        asin: str,
        upc: str | None,
        title: str | None,
        quantity: int,
        postal_code: str | None,
        currency: str,
        best_supplier: str | None,
        cheapest_supplier: str | None,
        fastest_supplier: str | None,
        highest_confidence_supplier: str | None,
        summary: str,
        offers: list[dict[str, Any]],
    ) -> ReverseSourcingRun:
        run = ReverseSourcingRun(
            asin=asin,
            upc=upc,
            title=title,
            quantity=quantity,
            postal_code=postal_code,
            currency=currency,
            best_supplier=best_supplier,
            cheapest_supplier=cheapest_supplier,
            fastest_supplier=fastest_supplier,
            highest_confidence_supplier=highest_confidence_supplier,
            summary=summary,
        )
        self._session.add(run)
        await self._session.flush()
        for data in offers:
            self._session.add(ReverseSourcingOffer(run_id=run.id, **data))
        await self._session.flush()
        await self._session.refresh(run)
        return run

    async def get_run(self, run_id: UUID) -> ReverseSourcingRun | None:
        result = await self._session.execute(
            select(ReverseSourcingRun).where(ReverseSourcingRun.id == run_id)
        )
        return result.scalar_one_or_none()

    async def list_runs(
        self,
        *,
        asin: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[ReverseSourcingRun], int]:
        statement = select(ReverseSourcingRun)
        if asin:
            statement = statement.where(ReverseSourcingRun.asin == asin)
        total = await self._count(statement)
        statement = (
            statement.order_by(ReverseSourcingRun.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.execute(statement)
        return list(result.scalars().all()), total

    async def historical_for_supplier(
        self,
        supplier_code: str,
        asin: str,
    ) -> dict[str, Any] | None:
        """Historical price / discount series for a (supplier, ASIN) pair."""
        statement = (
            select(ReverseSourcingOffer)
            .join(ReverseSourcingRun, ReverseSourcingRun.id == ReverseSourcingOffer.run_id)
            .where(
                ReverseSourcingRun.asin == asin,
                ReverseSourcingOffer.supplier_code == supplier_code,
            )
            .order_by(ReverseSourcingRun.created_at.asc())
        )
        result = await self._session.execute(statement)
        rows = list(result.scalars().all())
        if not rows:
            return None
        prices = [float(r.unit_price) for r in rows]
        discounts = [float(r.current_discount) for r in rows]
        return {
            "sample_count": len(rows),
            "prices": prices,
            "discounts": discounts,
            "avg_price": round(sum(prices) / len(prices), 4),
            "avg_discount": round(sum(discounts) / len(discounts), 4),
        }

    async def stats(self) -> dict[str, Any]:
        runs = await self._session.execute(
            select(func.count()).select_from(ReverseSourcingRun)
        )
        offers = await self._session.execute(
            select(func.count()).select_from(ReverseSourcingOffer)
        )
        by_asin = await self._session.execute(
            select(ReverseSourcingRun.asin, func.count()).group_by(ReverseSourcingRun.asin)
        )
        asins = await self._session.execute(
            select(ReverseSourcingRun.asin).distinct()
        )
        return {
            "total_runs": int(runs.scalar_one()),
            "total_offers": int(offers.scalar_one()),
            "asins": len(asins.all()),
            "runs_by_asin": {r[0]: int(r[1]) for r in by_asin.all()},
        }

    async def _count(self, statement: Any) -> int:
        result = await self._session.execute(
            select(func.count()).select_from(statement.subquery())
        )
        return int(result.scalar_one())
