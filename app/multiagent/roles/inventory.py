"""Inventory Agent — recommend stock levels.

Uses the demand forecast and lead time to compute a reorder point and a
recommended order quantity, then decides whether to reorder based on current
on-hand stock.
"""

from __future__ import annotations

from typing import Any, ClassVar

from app.multiagent.base import Agent, AgentResult


class InventoryAgent(Agent):
    role = "inventory"
    display_name = "Inventory Agent"
    description = "Recommends reorder quantities and stock levels from forecast + lead time."
    capabilities: ClassVar[list[str]] = ["inventory_planning", "reorder"]
    depends_on: ClassVar[list[str]] = ["forecast", "profit"]

    async def run(self, context: Any) -> AgentResult:
        forecast = context.recall("forecast", {})
        units = forecast.get("units", 0)
        horizon = forecast.get("horizon", 1)
        lead_time = context.task.get("lead_time_days", 7)
        safety_days = context.task.get("safety_days", 3)
        on_hand = context.task.get("on_hand", 0)

        daily_rate = units / max(1, horizon * 30)
        reorder_point = round(daily_rate * (lead_time + safety_days), 0)
        reorder_qty = max(0, round(units * (1 + context.task.get("buffer_pct", 0.10))))

        action = "reorder" if on_hand < reorder_point else "hold"
        context.trace(
            "inventory_ready",
            f"Reorder point {reorder_point}, qty {reorder_qty}, action {action}",
            reorder_point=reorder_point,
            reorder_qty=reorder_qty,
        )
        data = {
            "daily_rate": round(daily_rate, 2),
            "reorder_point": int(reorder_point),
            "reorder_qty": int(reorder_qty),
            "on_hand": on_hand,
            "lead_time_days": lead_time,
            "safety_days": safety_days,
            "action": action,
        }
        context.share("inventory", data)
        return AgentResult(
            role=self.role,
            summary=(
                f"Reorder {reorder_qty} units when stock falls below {reorder_point} "
                f"(currently {on_hand} on hand)."
            ),
            data=data,
            recommendations=[
                f"Order ~{reorder_qty} units now." if action == "reorder"
                else f"Hold stock; on-hand {on_hand} exceeds the reorder point."
            ],
            confidence=0.8,
            risk_level="medium" if action == "reorder" else "low",
        )
