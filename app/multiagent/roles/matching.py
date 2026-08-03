"""Matching Agent — match a product to the most suitable suppliers.

Ranks the offers from the research agent by landed cost while honouring task
constraints (availability, max shipping time). Produces a shortlist plus the
single best supplier.
"""

from __future__ import annotations

from typing import Any, ClassVar

from app.multiagent.base import Agent, AgentResult


class MatchingAgent(Agent):
    role = "matching"
    display_name = "Matching Agent"
    description = "Matches a product to suitable suppliers based on cost and constraints."
    capabilities: ClassVar[list[str]] = ["matching", "ranking"]
    depends_on: ClassVar[list[str]] = ["research"]

    async def run(self, context: Any) -> AgentResult:
        research = context.recall("research", {})
        offers = research.get("offers", [])
        max_shipping = context.task.get("max_shipping_days", 30)
        context.trace("matching_start", "Ranking supplier offers", offers=len(offers))

        eligible = []
        for offer in offers:
            if not offer.get("in_stock", True):
                continue
            if offer.get("shipping_days", 0) > max_shipping:
                continue
            eligible.append(offer)
        eligible.sort(key=lambda o: o.get("landed_cost", 0.0))
        best = eligible[0] if eligible else None

        context.trace(
            "matching_done",
            f"Matched {len(eligible)} eligible suppliers",
            best_supplier=best.get("supplier") if best else None,
        )
        data = {
            "matched": eligible,
            "best_supplier": best.get("supplier") if best else None,
            "best_landed_cost": best.get("landed_cost") if best else None,
            "count": len(eligible),
        }
        context.share("matching", data)
        recommendations = []
        if best:
            recommendations.append(f"Shortlist {best['supplier']} as the best match.")
            if len(eligible) > 1:
                recommendations.append(
                    f"Keep {eligible[1]['supplier']} as an alternative source."
                )
        else:
            recommendations.append("No suppliers meet the availability / shipping constraints.")
        return AgentResult(
            role=self.role,
            summary=f"Matched {len(eligible)} supplier(s).",
            data=data,
            recommendations=recommendations,
            confidence=0.85 if best else 0.5,
            risk_level="low" if best else "high",
        )
