"""Benchmark tests for the financial optimization engine.

Covers the pure math (EOQ, reorder point, safety stock, capital efficiency,
allocation), the manager (cash position from ledger + signals, transactions,
evaluate, allocate, reorder, dashboard, report), and the HTTP API.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.finance import (
    AllocationPolicy,
    AllocationRequest,
    FinanceConfig,
    FinanceManager,
    FinanceRepository,
    OpportunityInput,
    TransactionCreate,
    TransactionType,
)
from app.finance.engine import (
    allocate_opportunities,
    daily_demand,
    daily_std,
    economic_order_qty,
    evaluate_opportunity,
    reorder_point,
    safety_stock,
)
from app.finance.models import TransactionCategory

DEFAULT_CFG = FinanceConfig(
    starting_cash=10000.0,
    credit_card_limit=5000.0,
    holding_cost_rate=0.25,
    order_cost=5.0,
    service_level_z=1.65,
    max_units_per_order=1000,
)


def make_manager(db_session: AsyncSession, config: FinanceConfig | None = None) -> FinanceManager:
    return FinanceManager(FinanceRepository(db_session), config=config or DEFAULT_CFG)


def opp_a() -> OpportunityInput:
    return OpportunityInput(
        entity_type="product",
        entity_id="A",
        unit_cost=10,
        unit_price=15,
        expected_demand=30,
        demand_period="day",
        lead_time_days=10,
        current_stock=100,
        demand_std=5,
        risk=0.2,
    )


def opp_b() -> OpportunityInput:
    return OpportunityInput(
        entity_type="product",
        entity_id="B",
        unit_cost=20,
        unit_price=22,
        expected_demand=10,
        demand_period="day",
        lead_time_days=5,
        current_stock=50,
        risk=0.5,
    )


# ──────────────────────────────────────────────────────────────
# Pure engine math
# ──────────────────────────────────────────────────────────────


class TestEngineMath:
    def test_daily_demand_normalization(self) -> None:
        assert daily_demand(30, "day") == pytest.approx(30)
        assert daily_demand(7, "week") == pytest.approx(1)
        assert daily_demand(30, "month") == pytest.approx(1)

    def test_daily_std(self) -> None:
        assert daily_std(5, "day") == pytest.approx(5)
        # weekly std of 7 -> daily std = 7 / sqrt(7)
        assert daily_std(7, "week") == pytest.approx(7 / (7**0.5))

    def test_safety_stock_and_reorder_point(self) -> None:
        ss = safety_stock(1.65, 5, 10)
        assert ss == pytest.approx(1.65 * 5 * (10**0.5))
        rop = reorder_point(30, 10, ss)
        assert rop == pytest.approx(300 + ss)

    def test_eoq(self) -> None:
        eoq = economic_order_qty(30, 10, 5, 0.25)
        assert eoq == pytest.approx((2 * 30 * 365 * 5 / (10 * 0.25)) ** 0.5)


class TestEvaluateOpportunity:
    def test_buy_now_and_qty_capped_by_budget(self) -> None:
        ev = evaluate_opportunity(opp_a(), DEFAULT_CFG, budget=2000)
        assert ev["buy_now"] is True
        assert ev["recommended_order_qty"] == 200  # 2000 / 10 unit cost
        assert ev["capital_required"] == pytest.approx(2000)
        assert ev["reorder_point"] == pytest.approx(round(1.65 * 5 * (10**0.5) + 300, 2))
        assert ev["days_until_reorder"] == 0
        assert ev["expected_profit"] == pytest.approx(1000)  # 200 * $5 margin
        assert ev["capital_efficiency"] > 0
        assert ev["reasoning"]

    def test_not_buy_now_when_stock_healthy(self) -> None:
        opp = opp_a()
        opp.current_stock = 400
        ev = evaluate_opportunity(opp, DEFAULT_CFG, budget=None)
        assert ev["buy_now"] is False
        assert ev["days_until_reorder"] > 0
        assert ev["recommended_order_qty"] > 0  # EOQ

    def test_no_capital_means_no_buy(self) -> None:
        ev = evaluate_opportunity(opp_a(), DEFAULT_CFG, budget=0)
        assert ev["recommended_order_qty"] == 0
        assert ev["capital_required"] == 0


class TestAllocate:
    def test_efficiency_policy_ranks_by_capital_efficiency(self) -> None:
        result = allocate_opportunities([opp_a(), opp_b()], DEFAULT_CFG, budget=3000)
        allocs = result["allocations"]
        # A (efficiency ~0.02) beats B (~0.004) -> A gets the full budget.
        assert allocs[0]["entity_id"] == "A"
        assert allocs[0]["allocated"] == pytest.approx(3000)
        assert allocs[1]["allocated"] == 0
        assert result["total_allocated"] == pytest.approx(3000)
        assert result["expected_total_return"] > 0

    def test_total_never_exceeds_budget(self) -> None:
        result = allocate_opportunities([opp_a(), opp_b()], DEFAULT_CFG, budget=1000)
        assert result["total_allocated"] <= 1000
        assert result["reserved"] == pytest.approx(1000 - result["total_allocated"])

    def test_equal_policy_splits_equally(self) -> None:
        cfg = FinanceConfig(**DEFAULT_CFG.model_dump())
        cfg.allocation_policy = "equal"
        result = allocate_opportunities([opp_a(), opp_b()], cfg, budget=1000)
        assert len(result["allocations"]) == 2
        for a in result["allocations"]:
            assert a["allocated"] == pytest.approx(500)


# ──────────────────────────────────────────────────────────────
# Manager — cash position
# ──────────────────────────────────────────────────────────────


class TestCashPosition:
    async def test_cash_derived_from_ledger(self, db_session) -> None:
        mgr = make_manager(db_session)
        await mgr.record_transaction(
            TransactionCreate(transaction_type=TransactionType.INFLOW, category=TransactionCategory.PAYOUT, amount=2000)
        )
        await mgr.record_transaction(
            TransactionCreate(transaction_type=TransactionType.OUTFLOW, category=TransactionCategory.PURCHASE, amount=3000)
        )
        pos = await mgr.cash_position()
        assert pos.available_cash == pytest.approx(10000 + 2000 - 3000)

    async def test_cash_position_with_signals(self, db_session) -> None:
        mgr = make_manager(db_session)
        pos = await mgr.cash_position(
            {
                "inventory_value": 5000,
                "expected_payouts": 1000,
                "outstanding_credit": 2000,
                "reward_points": 500,
            }
        )
        assert pos.inventory_value == 5000
        assert pos.expected_payouts == 1000
        assert pos.available_credit == pytest.approx(3000)  # 5000 limit - 2000
        assert pos.reward_points_value == pytest.approx(5.0)  # 500 * 0.01
        assert pos.storage_cost_per_period == pytest.approx(round(5000 * 0.25 / 365 * 30, 2))
        # net = cash(10000) + payouts(1000) + credit(3000) - commitments(0)
        assert pos.net_liquidity == pytest.approx(14000)
        # usable = 14000 * 0.8
        assert pos.usable_capital == pytest.approx(11200)

    async def test_commitments_reduce_liquidity(self, db_session) -> None:
        mgr = make_manager(db_session)
        await mgr.record_transaction(
            TransactionCreate(transaction_type=TransactionType.OUTFLOW, category=TransactionCategory.COMMITMENT, amount=2000)
        )
        pos = await mgr.cash_position()
        assert pos.purchase_commitments == pytest.approx(2000)


# ──────────────────────────────────────────────────────────────
# Manager — transactions / evaluate / allocate / reorder
# ──────────────────────────────────────────────────────────────


class TestManagerFlow:
    async def test_record_and_list_transactions(self, db_session) -> None:
        mgr = make_manager(db_session)
        await mgr.record_transaction(
            TransactionCreate(
                transaction_type=TransactionType.INFLOW,
                category=TransactionCategory.CASHBACK,
                amount=50,
                description="card cashback",
            )
        )
        listed = await mgr.list_transactions(category=TransactionCategory.CASHBACK.value)
        assert listed.total == 1
        assert listed.items[0].amount == 50
        assert listed.items[0].category == TransactionCategory.CASHBACK

    async def test_evaluate(self, db_session) -> None:
        mgr = make_manager(db_session)
        ev = await mgr.evaluate(opp_a())
        assert ev.recommended_order_qty > 0
        assert ev.buy_now is True
        assert ev.capital_efficiency > 0

    async def test_evaluate_many(self, db_session) -> None:
        mgr = make_manager(db_session)
        from app.finance import OpportunityBatch

        evs = await mgr.evaluate_many(OpportunityBatch(opportunities=[opp_a(), opp_b()]))
        assert len(evs) == 2

    async def test_allocate_stores_allocations(self, db_session) -> None:
        mgr = make_manager(db_session)
        result = await mgr.allocate(
            AllocationRequest(budget=3000, opportunities=[opp_a(), opp_b()])
        )
        assert result.budget == 3000
        assert result.total_allocated == pytest.approx(3000)
        assert result.allocations[0].entity_id == "A"
        # stored
        stored, _ = await mgr._repo.list_allocations()
        assert len(stored) == 2

    async def test_allocate_equal_policy(self, db_session) -> None:
        mgr = make_manager(db_session)
        result = await mgr.allocate(
            AllocationRequest(
                budget=1000,
                policy=AllocationPolicy.EQUAL,
                opportunities=[opp_a(), opp_b()],
            )
        )
        assert result.policy == "equal"
        assert all(a.allocated == pytest.approx(500) for a in result.allocations)

    async def test_allocate_budget_defaults_to_usable_capital(self, db_session) -> None:
        mgr = make_manager(db_session)
        result = await mgr.allocate(
            AllocationRequest(opportunities=[opp_a(), opp_b()])
        )
        # No signals -> credit fully available: net = 10000 cash + 5000 credit.
        # usable = 15000 * 0.8
        assert result.budget == pytest.approx(12000)  # usable capital

    async def test_reorder(self, db_session) -> None:
        mgr = make_manager(db_session)
        opp = opp_a()
        opp.current_stock = 400
        r = await mgr.reorder(opp)
        assert r.buy_now is False
        assert r.days_until_reorder > 0
        assert r.suggested_qty > 0
        assert r.reorder_point > 0
        assert r.daily_demand == pytest.approx(30)

    async def test_dashboard(self, db_session) -> None:
        mgr = make_manager(db_session)
        await mgr.allocate(AllocationRequest(budget=2000, opportunities=[opp_a()]))
        dash = await mgr.dashboard()
        assert dash.generated_at
        assert dash.cash_position.available_cash >= 0
        assert len(dash.top_allocations) == 1

    async def test_report(self, db_session) -> None:
        mgr = make_manager(db_session)
        report = await mgr.report()
        assert report.currency == "USD"
        assert len(report.sections) >= 3
        assert report.markdown
        assert "Cash position" in report.markdown

    async def test_capabilities(self, db_session) -> None:
        mgr = make_manager(db_session)
        caps = mgr.capabilities()
        assert caps.enabled is True
        assert caps.currency == "USD"
        assert caps.credit_card["limit"] == 5000
        assert caps.rewards["cashback_rate"] == 0.02


# ──────────────────────────────────────────────────────────────
# HTTP API
# ──────────────────────────────────────────────────────────────


class TestAPI:
    async def test_cash_endpoint(self, client: AsyncClient) -> None:
        response = await client.get(
            "/api/v1/finance/cash",
            params={"inventory_value": 5000, "expected_payouts": 1000},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["inventory_value"] == 5000
        assert "net_liquidity" in data
        assert "usable_capital" in data

    async def test_transactions_endpoint(self, client: AsyncClient) -> None:
        created = await client.post(
            "/api/v1/finance/transactions",
            json={"transaction_type": "inflow", "category": "payout", "amount": 500},
        )
        assert created.status_code == 201
        assert created.json()["amount"] == 500

        listed = await client.get("/api/v1/finance/transactions")
        assert listed.status_code == 200
        assert listed.json()["total"] >= 1

    async def test_evaluate_endpoint(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/finance/opportunities/evaluate",
            json={
                "entity_type": "product",
                "entity_id": "A",
                "unit_cost": 10,
                "unit_price": 15,
                "expected_demand": 30,
                "demand_period": "day",
                "lead_time_days": 10,
                "current_stock": 100,
                "demand_std": 5,
                "risk": 0.2,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["buy_now"] is True
        assert data["recommended_order_qty"] > 0
        assert data["reasoning"]

    async def test_evaluate_batch_endpoint(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/finance/opportunities/evaluate/batch",
            json={
                "opportunities": [
                    {"entity_type": "product", "entity_id": "A", "unit_cost": 10, "expected_demand": 30},
                    {"entity_type": "product", "entity_id": "B", "unit_cost": 20, "expected_demand": 10},
                ]
            },
        )
        assert response.status_code == 200
        assert len(response.json()) == 2

    async def test_allocate_endpoint(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/finance/allocate",
            json={
                "budget": 3000,
                "opportunities": [
                    {"entity_type": "product", "entity_id": "A", "unit_cost": 10, "unit_price": 15, "expected_demand": 30, "current_stock": 100, "risk": 0.2},
                    {"entity_type": "product", "entity_id": "B", "unit_cost": 20, "unit_price": 22, "expected_demand": 10, "current_stock": 50, "risk": 0.5},
                ],
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total_allocated"] == pytest.approx(3000)
        assert data["allocations"][0]["entity_id"] == "A"

    async def test_reorder_endpoint(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/finance/reorder",
            json={
                "entity_type": "product",
                "entity_id": "A",
                "unit_cost": 10,
                "expected_demand": 30,
                "current_stock": 400,
                "lead_time_days": 10,
            },
        )
        assert response.status_code == 200
        assert response.json()["buy_now"] is False

    async def test_dashboard_endpoint(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/finance/dashboard")
        assert response.status_code == 200
        assert "cash_position" in response.json()
        assert "summary" in response.json()

    async def test_report_endpoint(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/finance/report")
        assert response.status_code == 200
        data = response.json()
        assert data["currency"] == "USD"
        assert len(data["sections"]) >= 3

    async def test_capabilities_endpoint(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/finance/capabilities")
        assert response.status_code == 200
        assert response.json()["currency"] == "USD"
        assert response.json()["allocation_policy"] == "efficiency"
