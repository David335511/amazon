"""Internal offer model for reverse sourcing.

`Offer` is the engine's working representation of one supplier's offer — a
plain dataclass assembled by the engine from the supplier provider, then scored
and persisted. Kept separate from the Pydantic response schemas so the scoring
math can stay pure and dependency-free.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Offer:
    """One supplier's current offer for a product."""

    supplier_code: str
    supplier_name: str | None
    supplier_sku: str
    unit_price: float
    currency: str
    shipping_cost: float
    shipping_days: int
    landed_cost: float
    in_stock: bool
    stock_status: str
    moq: int
    current_discount: float
    predicted_discount: float | None = field(default=None)
