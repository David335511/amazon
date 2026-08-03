"""Tests for the multi-agent orchestration framework.

Covers the framework contracts (registry auto-discovery + extensibility, agent
base, context collaboration: delegation / memory sharing / traces / tools),
the ten built-in specialist agents, the supervisor (planning, parallel-wave
execution, failure isolation), evaluation, persistence (manager + repository)
and the API.
"""

from __future__ import annotations

import asyncio
from typing import Any, ClassVar

import pytest
from httpx import AsyncClient

from app.multiagent import (
    Agent,
    AgentNotFoundError,
    AgentRegistry,
    AgentResult,
    AgentSupervisor,
    MemorySharing,
    MultiAgentConfig,
    MultiAgentManager,
    MultiAgentRepository,
    PipelineRunRequest,
    evaluate_run,
    summarize_evaluations,
)
from app.multiagent.base import AgentRun
from app.multiagent.context import AgentContext
from app.multiagent.tools import default_tools

BUILTIN_ROLES = {
    "planner",
    "research",
    "matching",
    "forecast",
    "pricing",
    "profit",
    "risk",
    "negotiation",
    "inventory",
    "reporting",
}


def make_task(**overrides: Any) -> dict[str, Any]:
    task: dict[str, Any] = {
        "asin": "B0TEST001",
        "action": "source",
        "quantity": 100,
        "target_margin": 0.30,
        "max_shipping_days": 10,
        "on_hand": 5,
        "expected_units": 200,
        "lead_time_days": 5,
        "seed": {
            "supplier_offers": [
                {
                    "supplier": "walmart",
                    "unit_price": 10.0,
                    "shipping_cost": 2.0,
                    "shipping_days": 4,
                    "in_stock": True,
                    "moq": 5,
                    "current_discount": 0.1,
                },
                {
                    "supplier": "target",
                    "unit_price": 9.0,
                    "shipping_cost": 4.0,
                    "shipping_days": 12,
                    "in_stock": True,
                    "moq": 2,
                    "current_discount": 0.0,
                },
            ]
        },
    }
    task.update(overrides)
    return task


OFFERS = [
    {
        "supplier": "walmart",
        "supplier_code": "walmart",
        "unit_price": 10.0,
        "shipping_cost": 2.0,
        "shipping_days": 4,
        "landed_cost": 12.0,
        "in_stock": True,
        "stock_status": "in_stock",
        "moq": 5,
        "current_discount": 0.1,
    },
    {
        "supplier": "target",
        "supplier_code": "target",
        "unit_price": 9.0,
        "shipping_cost": 4.0,
        "shipping_days": 12,
        "landed_cost": 13.0,
        "in_stock": True,
        "stock_status": "in_stock",
        "moq": 2,
        "current_discount": 0.0,
    },
]


def full_seed() -> dict[str, Any]:
    """A fully-populated shared memory so downstream agents run standalone."""
    return {
        "supplier_offers": [dict(o) for o in OFFERS],
        "research": {
            "asin": "B0TEST001",
            "offers": [dict(o) for o in OFFERS],
            "offer_count": 2,
        },
        "matching": {
            "matched": [dict(OFFERS[0])],
            "best_supplier": "walmart",
            "best_landed_cost": 12.0,
            "count": 1,
        },
        "forecast": {"units": 210, "horizon": 1, "trend": 0.05, "confidence": 0.7},
        "pricing": {
            "recommended_price": 17.14,
            "floor_price": 12.6,
            "unit_cost": 12.0,
            "target_margin": 0.30,
        },
        "profit": {
            "recommended_price": 17.14,
            "unit_cost": 12.0,
            "unit_margin": 5.14,
            "margin_pct": 0.30,
            "roi": 0.43,
            "total_profit": 1079.4,
            "projected_units": 210,
        },
        "risk": {"risk_score": 0.30, "risk_level": "low", "factors": []},
        "negotiation": {
            "target_discount": 0.15,
            "moq": 5,
            "volume_ask": 210,
            "tactics": ["tactic"],
            "best_supplier": "walmart",
        },
        "inventory": {
            "daily_rate": 7.0,
            "reorder_point": 56,
            "reorder_qty": 231,
            "on_hand": 5,
            "lead_time_days": 5,
            "safety_days": 3,
            "action": "reorder",
        },
    }


def make_full_task() -> dict[str, Any]:
    task = make_task()
    task["seed"] = full_seed()
    return task


def make_supervisor() -> AgentSupervisor:
    return AgentSupervisor(AgentRegistry.discover(), config=MultiAgentConfig())


# ─────────────────────────────────────────────────────────────────────────
# Registry / extensibility
# ─────────────────────────────────────────────────────────────────────────


def test_registry_discovers_all_ten_agents() -> None:
    registry = AgentRegistry.discover()
    assert set(registry.roles()) == BUILTIN_ROLES


def test_registry_adds_new_agent_without_engine_change() -> None:
    class ExtraAgent(Agent):
        role = "extra"
        display_name = "Extra Agent"
        description = "A new agent added later."
        capabilities: ClassVar[list[str]] = ["extra"]
        depends_on: ClassVar[list[str]] = []

        async def run(self, _context: AgentContext) -> AgentResult:
            return AgentResult(role=self.role, summary="extra done", data={"ok": True})

    registry = AgentRegistry.discover()
    assert not registry.has("extra")
    registry.register(ExtraAgent())
    assert registry.has("extra")
    assert "extra" in registry.roles()


def test_registry_unknown_role_raises() -> None:
    registry = AgentRegistry.discover()
    with pytest.raises(AgentNotFoundError) as exc:
        registry.get("nope")
    assert "nope" in str(exc.value)


def test_capabilities_lists_each_agent() -> None:
    registry = AgentRegistry.discover()
    caps = registry.capabilities()
    assert len(caps) == len(BUILTIN_ROLES)
    assert all(c["role"] for c in caps)
    assert all(c["depends_on"] is not None for c in caps)


# ─────────────────────────────────────────────────────────────────────────
# Each specialist agent in isolation
# ─────────────────────────────────────────────────────────────────────────


async def run_solo(role: str, task: dict[str, Any]) -> AgentRun:
    return await make_supervisor().run_single(role, task)


@pytest.mark.asyncio
@pytest.mark.parametrize("role", sorted(BUILTIN_ROLES))
async def test_each_agent_produces_a_result(role: str) -> None:
    run = await run_solo(role, make_task())
    assert run.status == "succeeded"
    assert run.result is not None
    assert run.result.role == role
    assert run.result.summary
    assert run.traces, "agent should record at least one reasoning trace"


@pytest.mark.asyncio
async def test_planner_produces_plan() -> None:
    run = await run_solo("planner", make_task())
    data = run.result.data if run.result else {}
    assert data["action"] == "source"
    assert any(step["agent"] == "reporting" for step in data["steps"])


@pytest.mark.asyncio
async def test_research_reads_seed_offers_and_derives_landed_cost() -> None:
    run = await run_solo("research", make_task())
    data = run.result.data if run.result else {}
    assert data["offer_count"] == 2
    walmart = next(o for o in data["offers"] if o["supplier"] == "walmart")
    assert walmart["landed_cost"] == pytest.approx(12.0)  # 10 + 2 (per unit)


@pytest.mark.asyncio
async def test_matching_filters_out_of_stock_and_slow_shipping() -> None:
    task = make_full_task()
    # target is out of stock and over max_shipping_days -> only walmart matches
    task["seed"]["research"] = {
        "asin": "B0TEST001",
        "offers": [
            dict(OFFERS[0]),
            {**dict(OFFERS[1]), "in_stock": False},
        ],
        "offer_count": 2,
    }
    run = await run_solo("matching", task)
    data = run.result.data if run.result else {}
    assert data["best_supplier"] == "walmart"
    assert data["count"] == 1


@pytest.mark.asyncio
async def test_pricing_uses_markup_tool() -> None:
    run = await run_solo("pricing", make_full_task())
    assert "markup" in run.tools_used
    data = run.result.data if run.result else {}
    assert data["unit_cost"] == pytest.approx(12.0)
    assert data["recommended_price"] == pytest.approx(12.0 / 0.7, abs=0.01)


@pytest.mark.asyncio
async def test_profit_computes_margin_roi_total() -> None:
    run = await run_solo("profit", make_full_task())
    data = run.result.data if run.result else {}
    assert data["margin_pct"] == pytest.approx(0.30, abs=0.001)
    assert data["total_profit"] == pytest.approx(data["unit_margin"] * 210, abs=0.01)


@pytest.mark.asyncio
async def test_forecast_uses_baseline_from_task() -> None:
    run = await run_solo("forecast", make_task())
    data = run.result.data if run.result else {}
    assert data["units"] == pytest.approx(200 * 1.05, abs=1)


@pytest.mark.asyncio
async def test_risk_levels_low_and_high() -> None:
    low = await run_solo("risk", make_task())
    assert low.result.data["risk_level"] in ("low", "medium", "high")
    # Degraded inputs -> higher risk
    task = make_task()
    task["seed"]["matching"] = {"count": 1, "best_supplier": None, "matched": [], "best_landed_cost": None}
    task["seed"]["profit"] = {"margin_pct": 0.0, "projected_units": 0}
    task["seed"]["forecast"] = {"confidence": 0.2}
    high = await run_solo("risk", task)
    assert high.result.data["risk_score"] > low.result.data["risk_score"]


@pytest.mark.asyncio
async def test_negotiation_builds_strategy() -> None:
    run = await run_solo("negotiation", make_full_task())
    data = run.result.data if run.result else {}
    assert data["target_discount"] > 0
    assert data["tactics"]
    assert data["best_supplier"] == "walmart"


@pytest.mark.asyncio
async def test_inventory_reorder_action() -> None:
    run = await run_solo("inventory", make_full_task())  # on_hand=5 < reorder point
    data = run.result.data if run.result else {}
    assert data["action"] == "reorder"
    assert data["reorder_qty"] > 0


@pytest.mark.asyncio
async def test_reporting_consolidates_and_produces_report() -> None:
    run = await run_solo("reporting", make_full_task())
    data = run.result.data if run.result else {}
    assert data["report"].startswith("##")
    assert data["top_recommendation"]


# ─────────────────────────────────────────────────────────────────────────
# Collaboration primitives
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_context_memory_share_and_recall() -> None:
    context = AgentContext(task={}, run_id="r1")
    context.share("a", 1)
    assert context.recall("a") == 1
    assert context.recall("missing", "x") == "x"
    assert context.has("a")


@pytest.mark.asyncio
async def test_tool_usage_recorded_on_run() -> None:
    run = await run_solo("pricing", make_task())
    assert "markup" in run.tools_used
    assert any(t.step == "tool_used" for t in run.traces)


@pytest.mark.asyncio
async def test_memory_sharing_store_and_recall() -> None:
    memory = MemorySharing()
    await memory.remember(role="research", key="asin", value="B0TEST001")
    items = await memory.recall(role="research")
    assert items[0][1] == "B0TEST001"
    assert memory.snapshot()["research:asin"] == "B0TEST001"


@pytest.mark.asyncio
async def test_task_delegation_via_registry() -> None:
    class DelegatorAgent(Agent):
        role = "delegator"
        depends_on: ClassVar[list[str]] = []

        async def run(self, context: AgentContext) -> AgentResult:
            delegated = await context.delegate("research", {"asin": "B0TEST001"})
            return AgentResult(
                role=self.role,
                summary=f"delegated to {delegated.role}",
                data={"delegated_role": delegated.role, "delegated_summary": delegated.summary},
            )

    registry = AgentRegistry.discover()
    registry.register(DelegatorAgent())
    sup = AgentSupervisor(registry, config=MultiAgentConfig())
    run = await sup.run_single("delegator", make_task())
    assert run.status == "succeeded"
    assert run.delegations, "delegation should be recorded"
    assert run.delegations[0].role == "research"
    assert run.delegations[0].result is not None
    assert run.result.data["delegated_role"] == "research"


# ─────────────────────────────────────────────────────────────────────────
# Supervisor
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_supervisor_runs_full_pipeline() -> None:
    result = await make_supervisor().run_pipeline(make_task())
    assert result.status == "succeeded"
    roles = {r.role for r in result.runs}
    assert roles == BUILTIN_ROLES
    assert result.report
    assert len(result.evaluations) == len(BUILTIN_ROLES)
    assert set(result.shared_memory) >= {
        "planner", "research", "matching", "forecast",
        "pricing", "profit", "risk", "negotiation", "inventory", "reporting",
    }


@pytest.mark.asyncio
async def test_supervisor_resolves_parallel_waves() -> None:
    sup = make_supervisor()
    roles = [r for r in MultiAgentConfig().default_pipeline_roles if r != "planner"]
    waves = sup._resolve_waves(roles)
    flat = [r for wave in waves for r in wave]
    assert set(flat) == set(roles)
    # wave2 runs matching + forecast concurrently (both depend only on research)
    assert "matching" in waves[1] and "forecast" in waves[1]
    # wave with negotiation+inventory+risk run together (parallel)
    assert len(waves[-2]) >= 2
    # reporting depends on everything -> runs last, alone
    assert waves[-1] == ["reporting"]


@pytest.mark.asyncio
async def test_supervisor_parallel_execution_speeds_pipeline() -> None:
    class SlowA(Agent):
        role = "slow_a"
        depends_on: ClassVar[list[str]] = []

        async def run(self, _context: AgentContext) -> AgentResult:
            await asyncio.sleep(0.3)
            return AgentResult(role=self.role, summary="slow a")

    class SlowB(Agent):
        role = "slow_b"
        depends_on: ClassVar[list[str]] = []

        async def run(self, _context: AgentContext) -> AgentResult:
            await asyncio.sleep(0.3)
            return AgentResult(role=self.role, summary="slow b")

    registry = AgentRegistry.discover()
    registry.register(SlowA())
    registry.register(SlowB())
    sup = AgentSupervisor(registry, config=MultiAgentConfig())
    result = await sup.run_pipeline({"seed": {}}, roles=["slow_a", "slow_b"])
    # Two independent agents run in parallel (~300ms) rather than serial (~600ms).
    assert result.duration_ms < 550


@pytest.mark.asyncio
async def test_supervisor_isolates_failures() -> None:
    class FailingAgent(Agent):
        role = "failing"
        depends_on: ClassVar[list[str]] = []

        async def run(self, _context: AgentContext) -> AgentResult:
            raise RuntimeError("boom")

    registry = AgentRegistry.discover()
    registry.register(FailingAgent())
    sup = AgentSupervisor(registry, config=MultiAgentConfig())
    result = await sup.run_pipeline({"seed": {}}, roles=["failing", "research"])
    assert result.status == "degraded"
    failing = next(r for r in result.runs if r.role == "failing")
    assert failing.status == "failed"
    assert "boom" in failing.error
    # research still succeeded independently
    assert any(r.role == "research" and r.status == "succeeded" for r in result.runs)


# ─────────────────────────────────────────────────────────────────────────
# Evaluation
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_evaluation_scores_success_and_completeness() -> None:
    run = await run_solo("research", make_task())
    ev = evaluate_run(run)
    assert ev.success is True
    assert ev.role == "research"
    assert 0 < ev.score <= 1.0


def test_evaluation_penalizes_failure() -> None:
    run = AgentRun(run_id="r", role="x", status="failed", error="oops")
    ev = evaluate_run(run)
    assert ev.success is False
    assert ev.score == 0.0


def test_evaluation_summarize_per_role() -> None:
    summary = summarize_evaluations(
        [
            evaluate_run(AgentRun(run_id="1", role="a", status="succeeded")),
            evaluate_run(AgentRun(run_id="2", role="a", status="failed")),
        ]
    )
    assert summary["a"]["runs"] == 2
    assert summary["a"]["success_rate"] == 0.5


# ─────────────────────────────────────────────────────────────────────────
# Manager + persistence (in-memory DB)
# ─────────────────────────────────────────────────────────────────────────


def make_manager(db_session) -> MultiAgentManager:
    return MultiAgentManager(MultiAgentRepository(db_session), config=MultiAgentConfig())


@pytest.mark.asyncio
async def test_manager_pipeline_persists_run_traces_evaluations(db_session) -> None:
    manager = make_manager(db_session)
    read = await manager.run_pipeline(PipelineRunRequest(task=make_task()))
    assert read.status == "succeeded"
    runs, total = await manager.list_runs()
    assert total == 1
    detail = await manager.get_run(runs[0].id)
    assert detail is not None
    assert len(detail.traces) >= len(BUILTIN_ROLES)
    assert len(detail.evaluations) == len(BUILTIN_ROLES)
    assert set(detail.shared_memory) >= {"planner", "reporting"}


@pytest.mark.asyncio
async def test_manager_stats(db_session) -> None:
    manager = make_manager(db_session)
    await manager.run_pipeline(PipelineRunRequest(task=make_task()))
    stats = await manager.stats()
    assert stats.total_runs == 1
    assert stats.total_evaluations == len(BUILTIN_ROLES)
    assert stats.runs_by_status.get("succeeded") == 1
    assert stats.evaluation_summary


@pytest.mark.asyncio
async def test_manager_run_single_persists(db_session) -> None:
    manager = make_manager(db_session)
    read = await manager.run_agent("research", make_task())
    assert read.role == "research"
    assert read.status == "succeeded"
    stats = await manager.stats()
    assert stats.total_runs == 1
    assert stats.total_evaluations == 1


@pytest.mark.asyncio
async def test_manager_unknown_role_raises(db_session) -> None:
    manager = make_manager(db_session)
    with pytest.raises(AgentNotFoundError):
        await manager.run_agent("nope", {"seed": {}})


# ─────────────────────────────────────────────────────────────────────────
# API
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_api_capabilities(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/multiagent/capabilities")
    assert resp.status_code == 200
    data = resp.json()
    assert set(data["roles"]) == BUILTIN_ROLES
    assert "task_delegation" in data["collaboration"]
    assert "planner" in data["default_pipeline_roles"]


@pytest.mark.asyncio
async def test_api_pipeline(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/multiagent/pipeline", json={"task": make_task()})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "succeeded"
    assert len(data["runs"]) == len(BUILTIN_ROLES)
    assert data["report"]
    assert len(data["evaluations"]) == len(BUILTIN_ROLES)


@pytest.mark.asyncio
async def test_api_single_agent_run(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/multiagent/agents/research/run", json={"task": make_task()}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["role"] == "research"
    assert data["status"] == "succeeded"


@pytest.mark.asyncio
async def test_api_unknown_agent_404(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/multiagent/agents/nope/run", json={"task": {"seed": {}}}
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_api_runs_and_detail(client: AsyncClient) -> None:
    await client.post("/api/v1/multiagent/pipeline", json={"task": make_task()})
    resp = await client.get("/api/v1/multiagent/runs")
    assert resp.status_code == 200
    runs = resp.json()
    assert len(runs) == 1
    run_id = runs[0]["id"]
    detail = await client.get(f"/api/v1/multiagent/runs/{run_id}")
    assert detail.status_code == 200
    body = detail.json()
    assert len(body["traces"]) >= len(BUILTIN_ROLES)
    assert len(body["evaluations"]) == len(BUILTIN_ROLES)
    traces = await client.get(f"/api/v1/multiagent/runs/{run_id}/traces")
    assert traces.status_code == 200
    assert traces.json()


@pytest.mark.asyncio
async def test_api_evaluations(client: AsyncClient) -> None:
    await client.post("/api/v1/multiagent/pipeline", json={"task": make_task()})
    resp = await client.get("/api/v1/multiagent/evaluations")
    assert resp.status_code == 200
    evals = resp.json()
    assert len(evals) == len(BUILTIN_ROLES)
    assert all(e["role"] for e in evals)


@pytest.mark.asyncio
async def test_api_stats(client: AsyncClient) -> None:
    await client.post("/api/v1/multiagent/pipeline", json={"task": make_task()})
    resp = await client.get("/api/v1/multiagent/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_runs"] == 1
    assert data["evaluation_summary"]


@pytest.mark.asyncio
async def test_api_agents_discovery(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/multiagent/agents")
    assert resp.status_code == 200
    assert len(resp.json()) == len(BUILTIN_ROLES)


# ─────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────


def test_default_pipeline_roles_are_the_ten_agents() -> None:
    assert set(MultiAgentConfig().default_pipeline_roles) == BUILTIN_ROLES


def test_default_tools_include_pure_helpers() -> None:
    names = [t.name for t in default_tools()]
    assert {"landed_cost", "markup"} <= set(names)
