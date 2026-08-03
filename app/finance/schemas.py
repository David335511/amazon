"""Pydantic schemas for the financial optimization API."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.finance.errors import FinanceValidationError
from app.finance.models import (
    AllocationPolicy,
    CapitalAllocation,
    CashTransaction,
    TransactionCategory,
    TransactionType,
)

# ──────────────────────────────────────────────────────────────
# Cash position / ledger
# ──────────────────────────────────────────────────────────────


class CashPositionRead(BaseModel):
    """A snapshot of liquidity: tracked and derived from the ledger + signals."""

    available_cash: float
    inventory_value: float
    expected_payouts: float
    purchase_commitments: float
    credit_card_limit: float
    outstanding_credit: float
    available_credit: float
    projected_cashback: float
    reward_points: float
    reward_points_value: float
    storage_cost_per_period: float
    net_liquidity: float
    usable_capital: float


class TransactionCreate(BaseModel):
    """Record a cash movement on the ledger."""

    transaction_type: TransactionType
    category: TransactionCategory
    amount: float = Field(gt=0)
    description: str | None = None
    entity_type: str | None = None
    entity_id: str | None = None
    occurred_at: datetime | None = None

    @field_validator("amount")
    @classmethod
    def _amount_positive(cls, v: float) -> float:
        if v <= 0:
            raise FinanceValidationError("Transaction amount must be positive")
        return v


class TransactionRead(BaseModel):
    """A recorded cash movement."""

    id: UUID
    transaction_type: TransactionType
    category: TransactionCategory
    amount: float
    description: str | None
    entity_type: str | None
    entity_id: str | None
    occurred_at: datetime | None
    created_at: datetime

    @classmethod
    def from_row(cls, row: CashTransaction) -> TransactionRead:
        return cls(
            id=row.id,
            transaction_type=TransactionType(row.transaction_type),
            category=TransactionCategory(row.category),
            amount=row.amount,
            description=row.description,
            entity_type=row.entity_type,
            entity_id=row.entity_id,
            occurred_at=_as_aware(row.occurred_at),
            created_at=row.created_at,
        )


class TransactionList(BaseModel):
    """Paginated ledger."""

    items: list[TransactionRead]
    total: int


# ──────────────────────────────────────────────────────────────
# Opportunities / recommendations / allocation
# ──────────────────────────────────────────────────────────────


class OpportunityInput(BaseModel):
    """An opportunity (candidate purchase/investment) to evaluate."""

    entity_type: str = Field(min_length=1)
    entity_id: str = Field(min_length=1)
    unit_cost: float = Field(gt=0)
    unit_price: float | None = Field(default=None, gt=0)
    expected_demand: float = Field(default=0, ge=0)  # per demand_period
    demand_period: Literal["day", "week", "month", "year"] = "day"
    lead_time_days: float = Field(default=7, ge=0)
    order_cost: float | None = Field(default=None, gt=0)
    current_stock: float = Field(default=0, ge=0)
    demand_std: float = Field(default=0, ge=0)
    expected_profit: float | None = Field(default=None)
    payback_days: float | None = Field(default=None, gt=0)
    risk: float = Field(default=0.5, ge=0.0, le=1.0)
    max_units: int | None = Field(default=None, gt=0)


class OpportunityEvaluation(BaseModel):
    """The engine's recommendation for one opportunity."""

    entity_type: str
    entity_id: str
    recommended_order_qty: int
    capital_required: float
    reorder_point: float
    safety_stock: float
    days_until_reorder: float
    buy_now: bool
    best_day_to_buy: int
    capital_efficiency: float
    expected_profit: float
    holding_cost: float
    payback_days: float
    risk: float
    reasoning: str

    @classmethod
    def from_eval(cls, e: dict) -> OpportunityEvaluation:
        return cls(
            entity_type=e["entity_type"],
            entity_id=e["entity_id"],
            recommended_order_qty=e["recommended_order_qty"],
            capital_required=e["capital_required"],
            reorder_point=e["reorder_point"],
            safety_stock=e["safety_stock"],
            days_until_reorder=e["days_until_reorder"],
            buy_now=e["buy_now"],
            best_day_to_buy=e["best_day_to_buy"],
            capital_efficiency=e["capital_efficiency"],
            expected_profit=e["expected_profit"],
            holding_cost=e["holding_cost"],
            payback_days=e["payback_days"],
            risk=e["risk"],
            reasoning=e["reasoning"],
        )


class OpportunityBatch(BaseModel):
    """Evaluate many opportunities (for ranking) without allocating."""

    opportunities: list[OpportunityInput] = Field(min_length=1)


class AllocationRequest(BaseModel):
    """Allocate a budget across a set of opportunities."""

    budget: float | None = Field(default=None, ge=0)
    policy: AllocationPolicy | None = None
    opportunities: list[OpportunityInput] = Field(min_length=1)


class AllocationItem(BaseModel):
    """A single allocation within an allocation result."""

    entity_type: str
    entity_id: str
    allocated: float
    units: float
    fraction: float
    capital_efficiency: float
    expected_return: float
    risk: float
    recommended_order_qty: int


class AllocationResult(BaseModel):
    """The outcome of a capital-allocation run."""

    budget: float
    total_allocated: float
    expected_total_return: float
    policy: str
    reserved: float
    allocations: list[AllocationItem]


class ReorderRecommendation(BaseModel):
    """A reorder decision for a single entity (reorder point / timing / qty)."""

    entity_type: str
    entity_id: str
    reorder_point: float
    safety_stock: float
    current_stock: float
    daily_demand: float
    days_until_reorder: float
    buy_now: bool
    suggested_qty: int
    best_day_to_buy: int
    reasoning: str


# ──────────────────────────────────────────────────────────────
# Dashboards / reports / capabilities
# ──────────────────────────────────────────────────────────────


class AllocationStoredRead(BaseModel):
    """A stored capital-allocation record."""

    id: UUID
    entity_type: str
    entity_id: str
    allocated_amount: float
    units: float
    expected_return: float
    capital_efficiency: float
    risk: float
    policy: str
    decided_at: datetime
    notes: str | None

    @classmethod
    def from_row(cls, row: CapitalAllocation) -> AllocationStoredRead:
        return cls(
            id=row.id,
            entity_type=row.entity_type,
            entity_id=row.entity_id,
            allocated_amount=row.allocated_amount,
            units=row.units,
            expected_return=row.expected_return,
            capital_efficiency=row.capital_efficiency,
            risk=row.risk,
            policy=row.policy,
            decided_at=_as_aware(row.decided_at),
            notes=row.notes,
        )


class DashboardRead(BaseModel):
    """A cash + allocation dashboard snapshot."""

    generated_at: datetime
    cash_position: CashPositionRead
    recent_transactions: list[TransactionRead]
    top_allocations: list[AllocationStoredRead]
    summary: dict[str, float | int | str]


class ReportSection(BaseModel):
    """One named section of the finance report."""

    title: str
    markdown: str
    data: dict = Field(default_factory=dict)


class ReportRead(BaseModel):
    """A structured finance report (dashboards + narratives)."""

    generated_at: datetime
    currency: str
    sections: list[ReportSection]
    markdown: str


class FinanceCapabilities(BaseModel):
    """Which features / policy / currency this deployment supports."""

    enabled: bool
    currency: str
    allocation_policy: str
    credit_card: dict[str, float | int]
    rewards: dict[str, float]
    costs: dict[str, float]


def _as_aware(dt: datetime | None) -> datetime | None:
    if dt is None or dt.tzinfo is not None:
        return dt
    return dt.replace(tzinfo=UTC)
