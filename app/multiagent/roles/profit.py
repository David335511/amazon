"""Profit Agent — estimate margin, ROI and total profit.

Combines the pricing decision, the matched supplier's cost and the demand
forecast into unit economics: per-unit margin, margin percentage, return on
cost (ROI) and total projected profit over the forecast horizon.
"""

from __future__ import annotations

from typing import Any, ClassVar

from app.multiagent.base import Agent, AgentResult


class ProfitAgent(Agent):
    role = "profit"
    display_name = "Profit Agent"
    description = "Estimates margin, ROI and total profit for a sourcing decision."
    capabilities: ClassVar[list[str]] = ["profit_analysis", "unit_economics"]
    depends_on: ClassVar[list[str]] = ["pricing", "matching", "forecast"]

    async def run(self, context: Any) -> AgentResult:
        pricing = context.recall("pricing", {})
        matching = context.recall("matching", {})
        forecast = context.recall("forecast", {})

        price = pricing.get("recommended_price", 0.0)
        unit_cost = pricing.get("unit_cost", 0.0) or matching.get("best_landed_cost") or 0.0
        units = forecast.get("units", 0)
        context.trace(
            "profit_start", "Estimating unit economics",
            price=price, unit_cost=unit_cost, units=units,
        )

        unit_margin = round(price - unit_cost, 2)
        margin_pct = round(unit_margin / price, 4) if price else 0.0
        roi = round(unit_margin / unit_cost, 4) if unit_cost else 0.0
        total_profit = round(unit_margin * units, 2)

        context.trace(
            "profit_ready",
            f"Margin {unit_margin} ({margin_pct:.0%}), ROI {roi:.0%}, total {total_profit}",
            unit_margin=unit_margin,
            margin_pct=margin_pct,
            roi=roi,
            total_profit=total_profit,
        )
        data = {
            "recommended_price": price,
            "unit_cost": unit_cost,
            "unit_margin": unit_margin,
            "margin_pct": margin_pct,
            "roi": roi,
            "total_profit": total_profit,
            "projected_units": units,
            "currency": context.task.get("currency", "USD"),
        }
        context.share("profit", data)
        profitable = margin_pct >= context.task.get("min_margin", 0.05)
        return AgentResult(
            role=self.role,
            summary=(
                f"Unit margin {unit_margin} ({margin_pct:.0%}); ROI {roi:.0%}; "
                f"~{total_profit} total on {units} units."
            ),
            data=data,
            recommendations=[
                f"Expected profit ~{total_profit} over {units} units."
                if profitable else
                "Margin is below target — reconsider price or cost before committing."
            ],
            confidence=0.85 if price and unit_cost else 0.5,
            risk_level="low" if profitable else "high",
        )
