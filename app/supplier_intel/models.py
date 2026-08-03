"""ORM model for supplier intelligence.

One table, ``supplier_observations``, stores the **historical** record: a row
per supplier per observed period. Each row captures the tracked dimensions
(price, sales, coupons, inventory, shipping, returns, customer service,
cancellations, discounts, stockouts). The five supplier scores are *computed on
demand* over this history — never cached as stale snapshots.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.models.base import Base, TimestampMixin, UUIDMixin


class SupplierObservation(Base, UUIDMixin, TimestampMixin):
    """One period snapshot of a supplier's behaviour."""

    __tablename__ = "supplier_observations"

    supplier_id: Mapped[str] = mapped_column(
        String(128), nullable=False, index=True,
        comment="Supplier identifier (plugin code, SKU namespace, UUID)",
    )
    supplier_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    observed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True,
        comment="End of the period this snapshot covers",
    )

    # Tracked dimensions (per period).
    price: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    sale_events: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    coupon_events: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    inventory_level: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    inventory_variance: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    stockouts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    shipping_days: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    return_policy_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    customer_service_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    order_cancellation_rate: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0,
    )
    discount_depth: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    discount_events: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    source: Mapped[str] = mapped_column(
        String(32), nullable=False, default="manual",
        comment="Where the observation came from (plugin, manual, sync, ...)",
    )

    def __repr__(self) -> str:
        return f"<SupplierObservation({self.supplier_id}, {self.observed_at}, price={self.price})>"
