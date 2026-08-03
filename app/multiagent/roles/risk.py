"""Risk Agent — assess sourcing risk.

Scores the risk of a sourcing decision from supplier reliability, shipping
speed, demand uncertainty, margin buffer and supplier concentration. Produces a
0..1 risk score, a qualitative level, and the key contributing factors.
"""

from __future__ import annotations

from typing import Any, ClassVar

from app.multiagent.base import Agent, AgentResult


class RiskAgent(Agent):
    role = "risk"
    display_name = "Risk Agent"
    description = "Assesses the risk of a sourcing decision and its key factors."
    capabilities: ClassVar[list[str]] = ["risk_assessment"]
    default_tools: ClassVar[list[str]] = ["supplier_scores"]
    depends_on: ClassVar[list[str]] = ["matching", "profit", "forecast"]

    async def run(self, context: Any) -> AgentResult:
        matching = context.recall("matching", {})
        profit = context.recall("profit", {})
        forecast = context.recall("forecast", {})
        best = next(
            (o for o in matching.get("matched", [])
             if o.get("supplier") == matching.get("best_supplier")),
            None,
        )
        context.trace("risk_start", "Assessing sourcing risk", best_supplier=best)

        reliability = 0.5
        if context.tool_registry is not None and context.tool_registry.has("supplier_scores"):
            try:
                scores = await context.use_tool(
                    "supplier_scores",
                    supplier_code=matching.get("best_supplier"),
                )
                reliability = scores.get("reliability", 0.5) if isinstance(scores, dict) else 0.5
            except Exception:
                reliability = 0.5

        shipping_days = best.get("shipping_days", 0) if best else 30
        max_shipping = context.task.get("max_shipping_days", 30)
        shipping_risk = min(1.0, shipping_days / max_shipping) if max_shipping else 0.5

        demand_confidence = forecast.get("confidence", 0.7)
        demand_risk = 1.0 - demand_confidence

        margin_pct = profit.get("margin_pct", 0.0)
        min_margin = context.task.get("min_margin", 0.05)
        margin_risk = 0.0 if margin_pct >= min_margin else min(1.0, (min_margin - margin_pct) / min_margin)

        concentration_risk = 1.0 if matching.get("count", 0) <= 1 else 0.0

        risk_score = round(
            0.35 * (1.0 - reliability)
            + 0.20 * shipping_risk
            + 0.20 * demand_risk
            + 0.15 * margin_risk
            + 0.10 * concentration_risk,
            4,
        )
        level = "low" if risk_score < 0.33 else ("medium" if risk_score < 0.66 else "high")
        factors = [
            f"reliability={reliability:.2f}",
            f"shipping_risk={shipping_risk:.2f}",
            f"demand_risk={demand_risk:.2f}",
            f"margin_risk={margin_risk:.2f}",
            f"concentration_risk={concentration_risk:.2f}",
        ]
        context.trace("risk_ready", f"Risk {level} ({risk_score:.2f})", risk_score=risk_score)
        data = {
            "risk_score": risk_score,
            "risk_level": level,
            "factors": factors,
        }
        context.share("risk", data)
        return AgentResult(
            role=self.role,
            summary=f"Risk assessment: {level} ({risk_score:.2f}).",
            data=data,
            recommendations=[f"Sourcing risk is {level} — {'proceed with monitoring' if level != 'high' else 'mitigate concentration / margin risk before committing'}."],
            confidence=0.8,
            risk_level=level,
        )
