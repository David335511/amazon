"""Financial optimization engine.

Tracks available cash, inventory value, expected payouts, credit-card cycles,
cashback, reward points, purchase commitments, storage costs and capital
allocation — and recommends **how many units to buy**, **when to buy / reorder**,
and **which opportunity delivers the highest capital efficiency**, while
generating dashboards and reports.

All behaviour is configurable via the `FinanceConfig` (cash, credit, rewards,
costs, allocation policy). The engine is modular: the pure math lives in
`engine.py` (EOQ, reorder point, safety stock, capital efficiency, allocation),
the ledger/allocation store in the repository, and the `FinanceManager` facade
ties them together.
"""

from app.finance.config import FinanceConfig
from app.finance.engine import (
    allocate_opportunities,
    daily_demand,
    daily_std,
    economic_order_qty,
    evaluate_opportunity,
    reorder_point,
    safety_stock,
)
from app.finance.errors import (
    FinanceError,
    FinanceNotFoundError,
    FinanceValidationError,
)
from app.finance.manager import FinanceManager
from app.finance.models import (
    AllocationPolicy,
    CapitalAllocation,
    CashTransaction,
    TransactionCategory,
    TransactionType,
)
from app.finance.repository import FinanceRepository
from app.finance.schemas import (
    AllocationItem,
    AllocationRequest,
    AllocationResult,
    AllocationStoredRead,
    CashPositionRead,
    DashboardRead,
    FinanceCapabilities,
    OpportunityBatch,
    OpportunityEvaluation,
    OpportunityInput,
    ReorderRecommendation,
    ReportRead,
    ReportSection,
    TransactionCreate,
    TransactionList,
    TransactionRead,
)

__all__ = [
    "AllocationItem",
    "AllocationPolicy",
    "AllocationRequest",
    "AllocationResult",
    "AllocationStoredRead",
    "CapitalAllocation",
    "CashPositionRead",
    "CashTransaction",
    "DashboardRead",
    "FinanceCapabilities",
    "FinanceConfig",
    "FinanceError",
    "FinanceManager",
    "FinanceNotFoundError",
    "FinanceRepository",
    "FinanceValidationError",
    "OpportunityBatch",
    "OpportunityEvaluation",
    "OpportunityInput",
    "ReorderRecommendation",
    "ReportRead",
    "ReportSection",
    "TransactionCategory",
    "TransactionCreate",
    "TransactionList",
    "TransactionRead",
    "TransactionType",
    "allocate_opportunities",
    "daily_demand",
    "daily_std",
    "economic_order_qty",
    "evaluate_opportunity",
    "reorder_point",
    "safety_stock",
]
