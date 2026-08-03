"""Engine-free helper tools always available to agents.

These are pure math / logic tools that need no external service, so the default
pipeline works end-to-end even with zero configured integrations. Engine-backed
tools (reverse sourcing, forecasting, supplier intel) are added by the DI layer.
"""

from __future__ import annotations

from typing import Any

from app.multiagent.base import Tool


class LandedCostTool(Tool):
    """Compute landed cost = unit_price * quantity + shipping."""

    name = "landed_cost"
    description = "Compute landed cost as unit_price * quantity + shipping."

    async def invoke(self, _context: Any, **kwargs: Any) -> Any:
        unit_price = float(kwargs.get("unit_price", 0.0))
        shipping = float(kwargs.get("shipping", 0.0))
        quantity = int(kwargs.get("quantity", 1))
        return round(unit_price * quantity + shipping, 2)


class MarkupTool(Tool):
    """Derive a selling price from cost and a target margin fraction."""

    name = "markup"
    description = "Price = cost / (1 - target_margin); margin is 0..1."

    async def invoke(self, _context: Any, **kwargs: Any) -> Any:
        cost = float(kwargs.get("cost", 0.0))
        margin = max(0.0, min(0.95, float(kwargs.get("target_margin", 0.30))))
        if (1 - margin) <= 0:
            return cost
        return round(cost / (1 - margin), 2)


def default_tools() -> list[Tool]:
    """The pure tools always registered for every agent."""
    return [LandedCostTool(), MarkupTool()]
