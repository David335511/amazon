"""Persistence layer for the financial optimization engine.

The `cash_ledger` table records every cash movement; available cash is derived
from it (starting cash + inflows - outflows). `capital_allocations` stores each
allocation decision for dashboards and audits.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select

from app.finance.models import CapitalAllocation, CashTransaction
from app.infrastructure.repositories.base import BaseRepository


class FinanceRepository(BaseRepository[CashTransaction]):
    """Repository for `cash_ledger` and `capital_allocations`."""

    def __init__(self, session) -> None:
        super().__init__(session, CashTransaction)

    # ── Ledger ────────────────────────────────────────────────────────────

    async def create_transaction(
        self,
        *,
        transaction_type: str,
        category: str,
        amount: float,
        description: str | None,
        entity_type: str | None,
        entity_id: str | None,
        occurred_at: datetime | None,
    ) -> CashTransaction:
        row = CashTransaction(
            transaction_type=transaction_type,
            category=category,
            amount=amount,
            description=description,
            entity_type=entity_type,
            entity_id=entity_id,
            occurred_at=occurred_at,
        )
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        return row

    async def list_transactions(
        self,
        *,
        category: str | None = None,
        transaction_type: str | None = None,
        entity_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[CashTransaction], int]:
        statement = select(CashTransaction)
        if category:
            statement = statement.where(CashTransaction.category == category)
        if transaction_type:
            statement = statement.where(CashTransaction.transaction_type == transaction_type)
        if entity_id:
            statement = statement.where(CashTransaction.entity_id == entity_id)
        total = await self._count(statement)
        statement = (
            statement.order_by(CashTransaction.occurred_at.desc().nullslast())
            .order_by(CashTransaction.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.execute(statement)
        return list(result.scalars().all()), total

    async def cash_balance(self, starting_cash: float) -> float:
        """Available cash = starting cash + inflows - outflows."""
        inflows = await self._sum_by_type(TransactionTypeStr.INFLOW)
        outflows = await self._sum_by_type(TransactionTypeStr.OUTFLOW)
        return starting_cash + inflows - outflows

    async def sum_outflows_by_category(self, category: str) -> float:
        """Total outflow recorded for a category (e.g. purchase commitments)."""
        result = await self._session.execute(
            select(func.coalesce(func.sum(CashTransaction.amount), 0.0)).where(
                CashTransaction.transaction_type == TransactionTypeStr.OUTFLOW,
                CashTransaction.category == category,
            )
        )
        return float(result.scalar_one())

    # ── Allocations ───────────────────────────────────────────────────────

    async def create_allocation(
        self,
        *,
        entity_type: str,
        entity_id: str,
        allocated_amount: float,
        units: float,
        expected_return: float,
        capital_efficiency: float,
        risk: float,
        policy: str,
        decided_at: datetime,
        notes: str | None,
    ) -> CapitalAllocation:
        row = CapitalAllocation(
            entity_type=entity_type,
            entity_id=entity_id,
            allocated_amount=allocated_amount,
            units=units,
            expected_return=expected_return,
            capital_efficiency=capital_efficiency,
            risk=risk,
            policy=policy,
            decided_at=decided_at,
            notes=notes,
        )
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        return row

    async def list_allocations(
        self, *, entity_id: str | None = None, limit: int = 50, offset: int = 0
    ) -> tuple[list[CapitalAllocation], int]:
        statement = select(CapitalAllocation)
        if entity_id:
            statement = statement.where(CapitalAllocation.entity_id == entity_id)
        total = await self._count(statement)
        statement = (
            statement.order_by(CapitalAllocation.decided_at.desc()).offset(offset).limit(limit)
        )
        result = await self._session.execute(statement)
        return list(result.scalars().all()), total

    # ── Stats ─────────────────────────────────────────────────────────────

    async def stats(self) -> dict[str, Any]:
        total_tx = await self._session.execute(select(func.count()).select_from(CashTransaction))
        by_category = await self._session.execute(
            select(CashTransaction.category, func.count()).group_by(CashTransaction.category)
        )
        total_alloc = await self._session.execute(
            select(func.count()).select_from(CapitalAllocation)
        )
        return {
            "total_transactions": int(total_tx.scalar_one()),
            "by_category": {r[0]: int(r[1]) for r in by_category.all()},
            "total_allocations": int(total_alloc.scalar_one()),
        }

    # ── Helpers ───────────────────────────────────────────────────────────

    async def _sum_by_type(self, transaction_type: str) -> float:
        result = await self._session.execute(
            select(func.coalesce(func.sum(CashTransaction.amount), 0.0)).where(
                CashTransaction.transaction_type == transaction_type
            )
        )
        return float(result.scalar_one())

    async def _count(self, statement: Any) -> int:
        result = await self._session.execute(
            select(func.count()).select_from(statement.subquery())
        )
        return int(result.scalar_one())


class TransactionTypeStr:
    """Plain-string constants (mirror the enum values) for SQL filters."""

    INFLOW = "inflow"
    OUTFLOW = "outflow"


def _as_aware(dt: datetime | None) -> datetime | None:
    if dt is None or dt.tzinfo is not None:
        return dt
    return dt.replace(tzinfo=UTC)
