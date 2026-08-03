"""Planner Agent — supervision and decomposition.

The planner runs first under the supervisor. It interprets the incoming task,
decides which specialist agents to engage and in what order, and stores the plan
in shared memory for transparency. It is the "supervision" face of the
framework.
"""

from __future__ import annotations

from typing import Any, ClassVar

from app.multiagent.base import Agent, AgentResult


class PlannerAgent(Agent):
    role = "planner"
    display_name = "Planner Agent"
    description = (
        "Supervises a sourcing/fulfilment task: breaks it down, decides which "
        "specialist agents to run and in what order."
    )
    capabilities: ClassVar[list[str]] = ["planning", "supervision", "decomposition"]
    depends_on: ClassVar[list[str]] = []

    async def run(self, context: Any) -> AgentResult:
        task = context.task
        action = task.get("action") or task.get("type") or "source"
        objective = task.get("objective") or f"{action} a product"
        context.trace("plan_start", "Interpreting the incoming task", action=action)

        plan = self._build_plan(action, objective)
        context.share("planner", plan)
        context.trace(
            "plan_ready",
            f"Produced {len(plan['steps'])} planning steps",
            roles=[s["agent"] for s in plan["steps"]],
        )
        return AgentResult(
            role=self.role,
            summary=f"Planned {action} across {len(plan['steps'])} specialist agents.",
            data=plan,
            recommendations=[s["goal"] for s in plan["steps"]],
            confidence=0.9,
        )

    def _build_plan(self, action: str, objective: str) -> dict[str, Any]:
        return {
            "objective": objective,
            "action": action,
            "steps": [
                {"agent": "research", "goal": "gather supplier and product data"},
                {"agent": "matching", "goal": "match the product to suitable suppliers"},
                {"agent": "forecast", "goal": "forecast demand"},
                {"agent": "pricing", "goal": "recommend a selling price"},
                {"agent": "profit", "goal": "estimate margin, ROI and total profit"},
                {"agent": "risk", "goal": "assess sourcing risk"},
                {"agent": "negotiation", "goal": "build a negotiation strategy"},
                {"agent": "inventory", "goal": "recommend stock levels"},
                {"agent": "reporting", "goal": "consolidate findings into a report"},
            ],
        }
