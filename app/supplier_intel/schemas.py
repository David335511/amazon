"""Pydantic schemas for supplier intelligence."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.supplier_intel.base import SupplierScore
from app.supplier_intel.models import SupplierObservation


class ObservationCreate(BaseModel):
    """Record one historical period snapshot for a supplier."""

    supplier_id: str = Field(min_length=1)
    supplier_name: str | None = None
    observed_at: datetime | None = Field(
        None, description="End of the period this snapshot covers (defaults to now)"
    )

    price: float = Field(default=0.0, ge=0)
    sale_events: int = Field(default=0, ge=0)
    coupon_events: int = Field(default=0, ge=0)
    inventory_level: float = Field(default=0.0, ge=0)
    inventory_variance: float = Field(default=0.0, ge=0)
    stockouts: int = Field(default=0, ge=0)
    shipping_days: float = Field(default=0.0, ge=0)
    return_policy_score: float = Field(default=0.0, ge=0, le=1)
    customer_service_score: float = Field(default=0.0, ge=0, le=1)
    order_cancellation_rate: float = Field(default=0.0, ge=0, le=1)
    discount_depth: float = Field(default=0.0, ge=0, le=1)
    discount_events: int = Field(default=0, ge=0)

    source: str = "manual"


class ObservationRead(BaseModel):
    """A stored historical observation."""

    id: UUID
    supplier_id: str
    supplier_name: str | None
    observed_at: datetime | None
    price: float
    sale_events: int
    coupon_events: int
    inventory_level: float
    inventory_variance: float
    stockouts: int
    shipping_days: float
    return_policy_score: float
    customer_service_score: float
    order_cancellation_rate: float
    discount_depth: float
    discount_events: int
    source: str
    created_at: datetime

    @classmethod
    def from_row(cls, row: SupplierObservation) -> ObservationRead:
        return cls(
            id=row.id,
            supplier_id=row.supplier_id,
            supplier_name=row.supplier_name,
            observed_at=_as_aware(row.observed_at),
            price=row.price,
            sale_events=row.sale_events,
            coupon_events=row.coupon_events,
            inventory_level=row.inventory_level,
            inventory_variance=row.inventory_variance,
            stockouts=row.stockouts,
            shipping_days=row.shipping_days,
            return_policy_score=row.return_policy_score,
            customer_service_score=row.customer_service_score,
            order_cancellation_rate=row.order_cancellation_rate,
            discount_depth=row.discount_depth,
            discount_events=row.discount_events,
            source=row.source,
            created_at=row.created_at,
        )


class ObservationList(BaseModel):
    """Paginated list of historical observations."""

    items: list[ObservationRead]
    total: int


class ScoreRead(BaseModel):
    """One supplier score with its confidence and component breakdown."""

    name: SupplierScore
    value: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    components: dict[str, Any] = Field(default_factory=dict)


class SupplierIntelRead(BaseModel):
    """Full supplier intelligence profile (metrics + scores + explanation)."""

    supplier_id: str
    supplier_name: str | None = None
    sample_count: int
    metrics: dict[str, Any] = Field(default_factory=dict)
    scores: dict[str, ScoreRead] = Field(default_factory=dict)
    explanation: str
    computed_at: datetime


class SupplierIntelBatchRequest(BaseModel):
    """Request to profile several suppliers in one call."""

    supplier_ids: list[str] = Field(min_length=1)


class SupplierIntelCapabilities(BaseModel):
    """What supplier intelligence exposes."""

    enabled: bool
    scores: list[str]
    tracked_metrics: list[str]
    max_batch_size: int


class SupplierIntelStats(BaseModel):
    """Aggregate statistics over the supplier-intelligence store."""

    total_observations: int = 0
    suppliers: int = 0
    observations_by_supplier: dict[str, int] = Field(default_factory=dict)


def _as_aware(dt: datetime | None) -> datetime | None:
    if dt is None or dt.tzinfo is not None:
        return dt
    from datetime import UTC

    return dt.replace(tzinfo=UTC)
