"""Engine-backed tools wired through DI.

These wrap the platform's engines (reverse sourcing, supplier intelligence) so
agents can use real platform capabilities as tools. They are optional: an agent
falls back to shared-memory seed data whenever a tool is not registered. The
`reverse_source` / `supplier_scores` tools are bound to request-scoped managers
in `app/core/dependencies.py`.
"""

from __future__ import annotations

from typing import Any

from app.multiagent.base import Tool
from app.reverse_sourcing import ReverseSourcingRequest


class ReverseSourceTool(Tool):
    """Reverse-source an ASIN across every known supplier (normalised offers)."""

    name = "reverse_source"
    description = "Reverse-source an ASIN across all known suppliers."

    def __init__(self, manager: Any) -> None:
        self._manager = manager

    async def invoke(self, _context: Any, **kwargs: Any) -> Any:
        request = ReverseSourcingRequest(
            asin=kwargs.get("asin") or "",
            quantity=int(kwargs.get("quantity", 1)),
        )
        result = await self._manager.source(request)
        offers: list[dict[str, Any]] = []
        for o in result.offers:
            offers.append(
                {
                    "supplier": o.supplier_code,
                    "supplier_code": o.supplier_code,
                    "supplier_name": o.supplier_name,
                    "sku": o.supplier_sku,
                    "unit_price": o.unit_price,
                    "shipping_cost": o.shipping_cost,
                    "shipping_days": o.shipping_days,
                    "landed_cost": o.landed_cost,
                    "in_stock": o.in_stock,
                    "stock_status": o.stock_status,
                    "moq": o.moq,
                    "current_discount": o.current_discount,
                }
            )
        return offers


class SupplierScoresTool(Tool):
    """Return the supplier-intelligence scores for a supplier code."""

    name = "supplier_scores"
    description = "Return supplier-intelligence scores (reliability, risk, ...) for a code."

    def __init__(self, manager: Any) -> None:
        self._manager = manager

    async def invoke(self, _context: Any, **kwargs: Any) -> Any:
        supplier_code = kwargs.get("supplier_code") or ""
        scores = await self._manager.scores(supplier_code)
        return {name: score.value for name, score in scores.items()}
