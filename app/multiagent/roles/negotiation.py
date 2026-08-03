"""Negotiation Agent — build a negotiation strategy.

Derives a target discount, volume/MOQ ask and a set of tactics from the matched
supplier and the projected margin/volume. The better the margin buffer and the
larger the order volume, the more negotiating room the agent recommends.
"""

from __future__ import annotations

from typing import Any, ClassVar

from app.multiagent.base import Agent, AgentResult


class NegotiationAgent(Agent):
    role = "negotiation"
    display_name = "Negotiation Agent"
    description = "Builds a negotiation strategy (target discount, MOQ ask, tactics)."
    capabilities: ClassVar[list[str]] = ["negotiation", "tactics"]
    depends_on: ClassVar[list[str]] = ["matching", "profit"]

    async def run(self, context: Any) -> AgentResult:
        matching = context.recall("matching", {})
        profit = context.recall("profit", {})
        margin_pct = profit.get("margin_pct", 0.0)
        volume = profit.get("projected_units", 0)
        best = matching.get("best_supplier")
        moq = next(
            (o.get("moq", 1) for o in matching.get("matched", [])
             if o.get("supplier") == best),
            1,
        )
        context.trace("negotiation_start", "Building negotiation strategy", best_supplier=best)

        # Higher margin buffer / larger volume → more room to negotiate.
        room = min(0.25, max(0.05, margin_pct * 0.5 + (0.02 if volume >= 100 else 0.0)))
        target_discount = round(room, 4)
        volume_ask = max(moq, volume)

        tactics: list[str] = []
        if margin_pct >= 0.10:
            tactics.append("Lead with a volume-based discount ask at the MOQ.")
        if volume_ask > moq:
            tactics.append(f"Offer a committed order of {volume_ask} units for a better rate.")
        tactics.append("Request free or subsidised shipping above a spend threshold.")
        tactics.append("Ask for extended payment terms if volume is committed.")

        context.trace(
            "negotiation_ready",
            f"Target discount {target_discount:.0%}",
            target_discount=target_discount,
            volume_ask=volume_ask,
        )
        data = {
            "target_discount": target_discount,
            "moq": moq,
            "volume_ask": volume_ask,
            "tactics": tactics,
            "best_supplier": best,
        }
        context.share("negotiation", data)
        return AgentResult(
            role=self.role,
            summary=f"Negotiation target: {target_discount:.0%} discount with {len(tactics)} tactics.",
            data=data,
            recommendations=tactics,
            confidence=0.75,
            risk_level="low" if best else "high",
        )
