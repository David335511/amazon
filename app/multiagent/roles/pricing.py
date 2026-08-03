"""Pricing Agent — recommend a selling price.

Derives a recommended price from the best supplier's landed cost and a target
margin (from the task or a default), using the `markup` tool. Also computes a
floor price (minimum acceptable margin) so downstream profit analysis has a
realistic band.
"""

from __future__ import annotations

from typing import Any, ClassVar

from app.multiagent.base import Agent, AgentResult


class PricingAgent(Agent):
    role = "pricing"
    display_name = "Pricing Agent"
    description = "Recommends a selling price based on landed cost and target margin."
    capabilities: ClassVar[list[str]] = ["pricing", "margin_calculation"]
    default_tools: ClassVar[list[str]] = ["markup"]
    depends_on: ClassVar[list[str]] = ["matching", "forecast"]

    async def run(self, context: Any) -> AgentResult:
        matching = context.recall("matching", {})
        unit_cost = matching.get("best_landed_cost")
        context.trace("pricing_start", "Pricing from landed cost", unit_cost=unit_cost)

        if unit_cost is None:
            unit_cost = context.task.get("target_cost", 0.0)

        target_margin = context.task.get("target_margin", 0.30)
        min_margin = context.task.get("min_margin", 0.05)

        price = None
        if context.tool_registry is not None and context.tool_registry.has("markup"):
            try:
                price = await context.use_tool(
                    "markup", cost=unit_cost, target_margin=target_margin
                )
            except Exception:
                price = None
        if price is None:
            price = round(unit_cost / (1 - target_margin), 2)

        floor_price = round(unit_cost * (1 + min_margin), 2)
        context.trace(
            "pricing_ready",
            f"Recommended price {price} (floor {floor_price})",
            price=price,
            floor_price=floor_price,
        )
        data = {
            "recommended_price": price,
            "floor_price": floor_price,
            "unit_cost": unit_cost,
            "target_margin": target_margin,
            "currency": context.task.get("currency", "USD"),
        }
        context.share("pricing", data)
        return AgentResult(
            role=self.role,
            summary=f"Recommended price {price} with a {target_margin:.0%} target margin.",
            data=data,
            recommendations=[
                f"List at {price} for a {target_margin:.0%} margin.",
                f"Do not price below {floor_price} to protect margin.",
            ],
            confidence=0.8 if unit_cost else 0.5,
        )
