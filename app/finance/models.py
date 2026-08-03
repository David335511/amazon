"""ORM models for the financial optimization engine.

Two tables:

- ``cash_ledger`` — a running record of every cash movement (payouts received,
  purchases, purchase commitments, cashback, expenses, storage, refunds). The
  available-cash balance is derived from it (starting cash + inflows - outflows).
- ``capital_allocations`` — how capital was actually allocated across
  opportunities, recording the amount, expected return, capital efficiency and
  the policy used, for dashboards and audits.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.models.base import Base, TimestampMixin, UUIDMixin


class TransactionType(StrEnum):
    """Direction of a cash movement."""

    INFLOW = "inflow"
    OUTFLOW = "outflow"


class TransactionCategory(StrEnum):
    """What a cash movement represents."""

    PAYOUT = "payout"            # cash received from sales/payouts
    PURCHASE = "purchase"        # cash spent buying inventory
    COMMITMENT = "commitment"    # cash committed to a purchase order (not yet paid)
    CASHBACK = "cashback"        # reward cashback received
    EXPENSE = "expense"          # operating expense
    STORAGE = "storage"          # storage / holding cost payment
    REFUND = "refund"            # money returned
    OTHER = "other"


class AllocationPolicy(StrEnum):
    """How capital is split across opportunities."""

    EFFICIENCY = "efficiency"      # rank by capital efficiency, greedy allocate
    EQUAL = "equal"                # equal share to each (capped by capital needed)
    CONSERVATIVE = "conservative"  # rank by efficiency * (1 - risk)


class CashTransaction(Base, UUIDMixin, TimestampMixin):
    """A single cash movement on the ledger."""

    __tablename__ = "cash_ledger"

    transaction_type: Mapped[str] = mapped_column(
        String(8), nullable=False, index=True, comment="inflow | outflow",
    )
    category: Mapped[str] = mapped_column(
        String(16), nullable=False, index=True,
        comment="payout | purchase | commitment | cashback | expense | storage | refund | other",
    )
    amount: Mapped[float] = mapped_column(
        Float, nullable=False, comment="Always positive; direction from transaction_type",
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    entity_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    occurred_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment="When the cash movement occurred",
    )

    def __repr__(self) -> str:
        return f"<CashTransaction({self.transaction_type}, {self.category}, {self.amount})>"


class CapitalAllocation(Base, UUIDMixin, TimestampMixin):
    """A capital-allocation decision for one opportunity."""

    __tablename__ = "capital_allocations"

    entity_type: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True,
    )
    entity_id: Mapped[str] = mapped_column(
        String(128), nullable=False, index=True,
    )
    allocated_amount: Mapped[float] = mapped_column(Float, nullable=False)
    units: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    expected_return: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    capital_efficiency: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    risk: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    policy: Mapped[str] = mapped_column(String(16), nullable=False, default=AllocationPolicy.EFFICIENCY.value)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        comment="When this allocation was decided",
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<CapitalAllocation({self.entity_type}/{self.entity_id}, {self.allocated_amount})>"
