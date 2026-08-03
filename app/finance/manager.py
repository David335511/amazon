"""Financial optimization facade.

`FinanceManager` is the ONLY entry point for tracking cash, evaluating
opportunities, allocating capital and generating dashboards/reports.

It tracks **available cash** (ledger-derived), **inventory value**, **expected
payouts**, **credit-card cycles**, **cashback**, **reward points**, **purchase
commitments**, **storage costs**, and **capital allocation** — and recommends
how many units to buy, when to buy/reorder, and which opportunity is most
capital-efficient.

Forward-looking / positional inputs (inventory value, expected payouts,
outstanding credit, reward points) are supplied via the ``signals`` dict so the
engine stays decoupled from the rest of the platform; the ledger provides the
realized cash base.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.finance.config import FinanceConfig
from app.finance.engine import daily_demand, evaluate_opportunity
from app.finance.errors import FinanceValidationError
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


class FinanceManager:
    """Facade for the financial optimization engine."""

    def __init__(self, repository: FinanceRepository, config: FinanceConfig | None = None) -> None:
        self._repo = repository
        self._config = config or FinanceConfig()

    # ── Capabilities ─────────────────────────────────────────────────────

    def capabilities(self) -> FinanceCapabilities:
        return FinanceCapabilities(
            enabled=self._config.enabled,
            currency=self._config.currency,
            allocation_policy=self._config.allocation_policy,
            credit_card={
                "limit": self._config.credit_card_limit,
                "billing_cycle_days": self._config.billing_cycle_days,
                "grace_period_days": self._config.grace_period_days,
            },
            rewards={
                "cashback_rate": self._config.cashback_rate,
                "reward_points_value": self._config.reward_points_value,
                "points_per_dollar": self._config.points_per_dollar,
            },
            costs={
                "holding_cost_rate": self._config.holding_cost_rate,
                "order_cost": self._config.order_cost,
            },
        )

    # ── Cash position ────────────────────────────────────────────────────

    async def cash_position(self, signals: dict[str, Any] | None = None) -> CashPositionRead:
        s = signals or {}
        ledger_cash = await self._repo.cash_balance(self._config.starting_cash)

        available_cash = float(s.get("available_cash", ledger_cash))
        inventory_value = float(s.get("inventory_value", 0.0))
        expected_payouts = float(s.get("expected_payouts", 0.0))
        purchase_commitments = float(
            s.get("purchase_commitments", await self._repo.sum_outflows_by_category("commitment"))
        )
        outstanding_credit = float(s.get("outstanding_credit", 0.0))
        reward_points = float(s.get("reward_points", 0.0))

        available_credit = max(0.0, self._config.credit_card_limit - outstanding_credit)
        projected_cashback = float(s.get("projected_cashback", self._config.cashback_rate * 0.0))
        reward_points_value = reward_points * self._config.reward_points_value
        storage_cost_per_period = (
            inventory_value * self._config.holding_cost_rate / 365.0 * 30.0
        )  # monthly storage estimate

        net_liquidity = (
            available_cash
            + expected_payouts
            + available_credit
            + projected_cashback
            - purchase_commitments
        )
        usable_capital = max(
            0.0, (net_liquidity * self._config.investable_fraction) - self._config.min_cash_reserve
        )

        return CashPositionRead(
            available_cash=round(available_cash, 2),
            inventory_value=round(inventory_value, 2),
            expected_payouts=round(expected_payouts, 2),
            purchase_commitments=round(purchase_commitments, 2),
            credit_card_limit=self._config.credit_card_limit,
            outstanding_credit=round(outstanding_credit, 2),
            available_credit=round(available_credit, 2),
            projected_cashback=round(projected_cashback, 2),
            reward_points=round(reward_points, 2),
            reward_points_value=round(reward_points_value, 2),
            storage_cost_per_period=round(storage_cost_per_period, 2),
            net_liquidity=round(net_liquidity, 2),
            usable_capital=round(usable_capital, 2),
        )

    # ── Ledger ────────────────────────────────────────────────────────────

    async def record_transaction(self, request: TransactionCreate) -> TransactionRead:
        row = await self._repo.create_transaction(
            transaction_type=request.transaction_type.value,
            category=request.category.value,
            amount=request.amount,
            description=request.description,
            entity_type=request.entity_type,
            entity_id=request.entity_id,
            occurred_at=request.occurred_at,
        )
        return TransactionRead.from_row(row)

    async def list_transactions(
        self,
        *,
        category: str | None = None,
        transaction_type: str | None = None,
        entity_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> TransactionList:
        rows, total = await self._repo.list_transactions(
            category=category,
            transaction_type=transaction_type,
            entity_id=entity_id,
            limit=limit,
            offset=offset,
        )
        return TransactionList(items=[TransactionRead.from_row(r) for r in rows], total=total)

    # ── Opportunities ─────────────────────────────────────────────────────

    async def evaluate(self, opportunity: OpportunityInput) -> OpportunityEvaluation:
        budget = await self._usable_budget()
        return OpportunityEvaluation.from_eval(
            evaluate_opportunity(opportunity, self._config, budget)
        )

    async def evaluate_many(self, batch: OpportunityBatch) -> list[OpportunityEvaluation]:
        if len(batch.opportunities) > self._config.max_batch_size:
            raise FinanceValidationError(
                f"Batch size {len(batch.opportunities)} exceeds max {self._config.max_batch_size}"
            )
        budget = await self._usable_budget()
        return [
            OpportunityEvaluation.from_eval(
                evaluate_opportunity(opp, self._config, budget)
            )
            for opp in batch.opportunities
        ]

    # ── Allocation ────────────────────────────────────────────────────────

    async def allocate(self, request: AllocationRequest) -> AllocationResult:
        if len(request.opportunities) > self._config.max_batch_size:
            raise FinanceValidationError(
                f"Batch size {len(request.opportunities)} exceeds max {self._config.max_batch_size}"
            )
        if request.budget is None:
            budget = await self._usable_budget()
        else:
            budget = request.budget
        policy = request.policy.value if request.policy else self._config.allocation_policy

        from app.finance.engine import allocate_opportunities

        result = allocate_opportunities(request.opportunities, self._config, budget, policy=policy)

        now = datetime.now(UTC)
        for alloc in result["allocations"]:
            await self._repo.create_allocation(
                entity_type=alloc["entity_type"],
                entity_id=alloc["entity_id"],
                allocated_amount=alloc["allocated"],
                units=alloc["units"],
                expected_return=alloc["expected_return"],
                capital_efficiency=alloc["capital_efficiency"],
                risk=alloc["risk"],
                policy=policy,
                decided_at=now,
                notes=f"Allocated {alloc['allocated']} ({policy} policy)",
            )

        return AllocationResult(
            budget=round(budget, 2),
            total_allocated=result["total_allocated"],
            expected_total_return=result["expected_total_return"],
            policy=result["policy"],
            reserved=result["reserved"],
            allocations=[
                AllocationItem(**a) for a in result["allocations"]
            ],
        )

    # ── Reorder recommendation ────────────────────────────────────────────

    async def reorder(self, opportunity: OpportunityInput) -> ReorderRecommendation:
        eval_dict = evaluate_opportunity(opportunity, self._config, await self._usable_budget())
        d = daily_demand(opportunity.expected_demand, opportunity.demand_period)
        return ReorderRecommendation(
            entity_type=opportunity.entity_type,
            entity_id=opportunity.entity_id,
            reorder_point=eval_dict["reorder_point"],
            safety_stock=eval_dict["safety_stock"],
            current_stock=opportunity.current_stock,
            daily_demand=round(d, 4),
            days_until_reorder=eval_dict["days_until_reorder"],
            buy_now=eval_dict["buy_now"],
            suggested_qty=eval_dict["recommended_order_qty"],
            best_day_to_buy=eval_dict["best_day_to_buy"],
            reasoning=eval_dict["reasoning"],
        )

    # ── Dashboards / reports ─────────────────────────────────────────────

    async def dashboard(self, signals: dict[str, Any] | None = None) -> DashboardRead:
        position = await self.cash_position(signals)
        tx_rows, _ = await self._repo.list_transactions(limit=10, offset=0)
        alloc_rows, _ = await self._repo.list_allocations(limit=10, offset=0)
        summary = {
            "total_transactions": (await self._repo.stats())["total_transactions"],
            "total_allocations": len(alloc_rows),
            "net_liquidity": position.net_liquidity,
            "usable_capital": position.usable_capital,
            "reserve_ratio": round(position.available_cash / position.net_liquidity, 2)
            if position.net_liquidity
            else 0.0,
        }
        return DashboardRead(
            generated_at=datetime.now(UTC),
            cash_position=position,
            recent_transactions=[TransactionRead.from_row(r) for r in tx_rows],
            top_allocations=[AllocationStoredRead.from_row(r) for r in alloc_rows],
            summary=summary,
        )

    async def report(self, signals: dict[str, Any] | None = None) -> ReportRead:
        position = await self.cash_position(signals)
        stats = await self._repo.stats()
        currency = self._config.currency

        sections = [
            self._cash_section(position, currency),
            self._ledger_section(stats, currency),
            self._allocation_section(),
            self._config_section(),
        ]
        markdown = "\n\n".join(s.markdown for s in sections)
        return ReportRead(
            generated_at=datetime.now(UTC),
            currency=currency,
            sections=sections,
            markdown=markdown,
        )

    # ── Internals ─────────────────────────────────────────────────────────

    async def _usable_budget(self) -> float | None:
        position = await self.cash_position()
        return position.usable_capital

    def _cash_section(self, position: CashPositionRead, currency: str) -> ReportSection:
        md = "\n".join(
            [
                f"## Cash position ({currency})",
                f"- Available cash: **{position.available_cash:,.2f}**",
                f"- Inventory value: {position.inventory_value:,.2f}",
                f"- Expected payouts: {position.expected_payouts:,.2f}",
                f"- Purchase commitments: {position.purchase_commitments:,.2f}",
                f"- Available credit: {position.available_credit:,.2f} "
                f"(limit {position.credit_card_limit:,.2f})",
                f"- Projected cashback: {position.projected_cashback:,.2f}",
                f"- Reward points value: {position.reward_points_value:,.2f}",
                f"- Storage cost (monthly): {position.storage_cost_per_period:,.2f}",
                f"- **Net liquidity: {position.net_liquidity:,.2f}**",
                f"- **Usable capital: {position.usable_capital:,.2f}**",
            ]
        )
        return ReportSection(
            title="Cash position",
            markdown=md,
            data=position.model_dump(),
        )

    def _ledger_section(self, stats: dict[str, Any], currency: str) -> ReportSection:
        by_cat = stats["by_category"]
        md = "\n".join(
            [f"## Ledger ({currency})", f"- Total transactions: {stats['total_transactions']}"]
            + [f"- {k}: {v}" for k, v in sorted(by_cat.items())]
        )
        return ReportSection(title="Ledger", markdown=md, data=by_cat)

    def _allocation_section(self) -> ReportSection:
        return ReportSection(
            title="Capital allocation",
            markdown=(
                "Allocation policy: "
                f"**{self._config.allocation_policy}**. Allocations are stored via "
                "`POST /finance/allocate`; recent ones appear on the dashboard."
            ),
            data={"policy": self._config.allocation_policy},
        )

    def _config_section(self) -> ReportSection:
        md = "\n".join(
            [
                "## Configuration",
                f"- Allocation policy: {self._config.allocation_policy}",
                f"- Investable fraction: {self._config.investable_fraction}",
                f"- Holding cost rate (annual): {self._config.holding_cost_rate}",
                f"- Credit limit: {self._config.credit_card_limit}",
                f"- Billing cycle: {self._config.billing_cycle_days} days, "
                f"grace {self._config.grace_period_days} days",
                f"- Cashback rate: {self._config.cashback_rate}",
                f"- Reward point value: {self._config.reward_points_value}",
            ]
        )
        return ReportSection(title="Configuration", markdown=md, data=self._config.model_dump())
