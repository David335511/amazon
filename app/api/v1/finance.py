"""Financial optimization API.

The router talks ONLY to `FinanceManager` (via DI); it contains no financial
logic itself. It exposes cash position, ledger recording/listing, opportunity
evaluation (single + batch), capital allocation, reorder recommendations,
dashboards, reports, and capabilities.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.dependencies import get_finance_manager
from app.finance import (
    AllocationRequest,
    AllocationResult,
    CashPositionRead,
    DashboardRead,
    FinanceCapabilities,
    FinanceManager,
    OpportunityBatch,
    OpportunityEvaluation,
    OpportunityInput,
    ReorderRecommendation,
    ReportRead,
    TransactionCreate,
    TransactionList,
    TransactionRead,
)
from app.finance.errors import FinanceValidationError

router = APIRouter(prefix="/finance", tags=["finance"])

ManagerDep = Annotated[FinanceManager, Depends(get_finance_manager)]


@router.get("/capabilities", response_model=FinanceCapabilities)
async def capabilities(manager: ManagerDep) -> FinanceCapabilities:
    """Report the engine's currency, policy, credit and rewards configuration."""
    return manager.capabilities()


@router.get("/cash", response_model=CashPositionRead)
async def cash(
    manager: ManagerDep,
    inventory_value: float = Query(default=0.0),
    expected_payouts: float = Query(default=0.0),
    outstanding_credit: float = Query(default=0.0),
    reward_points: float = Query(default=0.0),
) -> CashPositionRead:
    """Current cash position (available cash, inventory, payouts, credit, rewards)."""
    return await manager.cash_position(
        {
            "inventory_value": inventory_value,
            "expected_payouts": expected_payouts,
            "outstanding_credit": outstanding_credit,
            "reward_points": reward_points,
        }
    )


@router.post("/transactions", response_model=TransactionRead, status_code=status.HTTP_201_CREATED)
async def record_transaction(body: TransactionCreate, manager: ManagerDep) -> TransactionRead:
    """Record a cash movement on the ledger (payout, purchase, commitment, ...)."""
    try:
        return await manager.record_transaction(body)
    except FinanceValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.get("/transactions", response_model=TransactionList)
async def list_transactions(
    manager: ManagerDep,
    category: str | None = None,
    transaction_type: str | None = None,
    entity_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> TransactionList:
    """List the cash ledger, optionally filtered."""
    return await manager.list_transactions(
        category=category,
        transaction_type=transaction_type,
        entity_id=entity_id,
        limit=limit,
        offset=offset,
    )


@router.post("/opportunities/evaluate", response_model=OpportunityEvaluation)
async def evaluate(body: OpportunityInput, manager: ManagerDep) -> OpportunityEvaluation:
    """Evaluate one opportunity: units to buy, reorder point, capital efficiency."""
    try:
        return await manager.evaluate(body)
    except FinanceValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.post("/opportunities/evaluate/batch", response_model=list[OpportunityEvaluation])
async def evaluate_batch(body: OpportunityBatch, manager: ManagerDep) -> list[OpportunityEvaluation]:
    """Evaluate many opportunities (for ranking), without allocating."""
    try:
        return await manager.evaluate_many(body)
    except FinanceValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.post("/allocate", response_model=AllocationResult)
async def allocate(body: AllocationRequest, manager: ManagerDep) -> AllocationResult:
    """Allocate a budget across opportunities by the configured policy."""
    try:
        return await manager.allocate(body)
    except FinanceValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.post("/reorder", response_model=ReorderRecommendation)
async def reorder(body: OpportunityInput, manager: ManagerDep) -> ReorderRecommendation:
    """Reorder decision for one entity: when to buy and how many units."""
    try:
        return await manager.reorder(body)
    except FinanceValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.get("/dashboard", response_model=DashboardRead)
async def dashboard(manager: ManagerDep) -> DashboardRead:
    """A cash + allocation dashboard snapshot."""
    return await manager.dashboard()


@router.get("/report", response_model=ReportRead)
async def report(manager: ManagerDep) -> ReportRead:
    """A structured finance report (cash, ledger, allocation, configuration)."""
    return await manager.report()
