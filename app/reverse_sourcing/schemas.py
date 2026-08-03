"""Pydantic schemas for the reverse sourcing API."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.reverse_sourcing.models import ReverseSourcingRun


class ReverseSourcingRequest(BaseModel):
    """Request to reverse-source an Amazon ASIN across all suppliers."""

    asin: str = Field(min_length=1, description="Amazon ASIN (e.g. B0TEST001)")
    upc: str | None = Field(None, description="Optional UPC to disambiguate at suppliers")
    quantity: int = Field(default=1, ge=1, le=1000)
    postal_code: str | None = None
    currency: str = "USD"


class SupplierOfferRead(BaseModel):
    """One supplier's current offer for the product."""

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
    predicted_discount: float | None = None


class HistoricalSupplierRead(BaseModel):
    """Historical price / discount series for a (supplier, ASIN) pair."""

    supplier_code: str
    sample_count: int
    prices: list[float] = Field(default_factory=list)
    discounts: list[float] = Field(default_factory=list)
    avg_price: float = 0.0
    avg_discount: float = 0.0


class RankedSupplierRead(BaseModel):
    """A supplier ranked by the reverse-sourcing score."""

    supplier_code: str
    supplier_name: str | None
    score: float = Field(ge=0.0, le=1.0)
    rank: int
    components: dict[str, float] = Field(default_factory=dict)


class SupplierHighlightRead(BaseModel):
    """A highlighted supplier (best / cheapest / fastest / highest-confidence)."""

    supplier_code: str
    supplier_name: str | None
    reason: str
    landed_cost: float
    shipping_days: int
    score: float


class ReverseSourcingRead(BaseModel):
    """Full reverse-sourcing result for an ASIN."""

    asin: str
    upc: str | None
    title: str | None
    quantity: int
    postal_code: str | None
    currency: str
    offers: list[SupplierOfferRead] = Field(default_factory=list)
    historical: dict[str, HistoricalSupplierRead] = Field(default_factory=dict)
    ranking: list[RankedSupplierRead] = Field(default_factory=list)
    highlights: dict[str, SupplierHighlightRead] = Field(default_factory=dict)
    predicted_discounts: dict[str, float | None] = Field(default_factory=dict)
    recommendations: list[str] = Field(default_factory=list)
    summary: str
    created_at: datetime


class ReverseSourcingRunRead(BaseModel):
    """A stored reverse-sourcing run (inputs + highlights + summary)."""

    id: UUID
    asin: str
    upc: str | None
    title: str | None
    quantity: int
    postal_code: str | None
    currency: str
    best_supplier: str | None
    cheapest_supplier: str | None
    fastest_supplier: str | None
    highest_confidence_supplier: str | None
    summary: str
    created_at: datetime

    @classmethod
    def from_row(cls, row: ReverseSourcingRun) -> ReverseSourcingRunRead:
        return cls(
            id=row.id,
            asin=row.asin,
            upc=row.upc,
            title=row.title,
            quantity=row.quantity,
            postal_code=row.postal_code,
            currency=row.currency,
            best_supplier=row.best_supplier,
            cheapest_supplier=row.cheapest_supplier,
            fastest_supplier=row.fastest_supplier,
            highest_confidence_supplier=row.highest_confidence_supplier,
            summary=row.summary,
            created_at=row.created_at,
        )


class ReverseSourcingList(BaseModel):
    """Paginated list of stored runs."""

    items: list[ReverseSourcingRunRead]
    total: int


class ReverseSourcingCapabilities(BaseModel):
    """What reverse sourcing exposes."""

    enabled: bool
    suppliers: list[str]
    max_suppliers: int
    features: dict[str, Any] = Field(default_factory=dict)


class ReverseSourcingStats(BaseModel):
    """Aggregate statistics over the reverse-sourcing store."""

    total_runs: int = 0
    total_offers: int = 0
    asins: int = 0
    runs_by_asin: dict[str, int] = Field(default_factory=dict)
