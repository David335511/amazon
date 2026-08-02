"""HistoricalInventory — append-only inventory snapshots.

Design decisions:
- Every inventory observation creates a new row. Never UPDATE or DELETE.
- Timestamped with effective_date for time-series analysis.
- Composite index on (product_id, effective_date) for range queries.
- Partition-ready: effective_date is the natural partition key.
- Stores the full inventory state at the time of observation.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.models.base import Base, TimestampMixin, UUIDMixin


class HistoricalInventory(Base, UUIDMixin, TimestampMixin):
    """Append-only inventory snapshots — NEVER UPDATE OR DELETE.

    Each row captures the complete inventory state for a product at a
    point in time. This enables trend analysis, stock-out detection,
    and reorder point optimization.

    For current inventory state, use the `inventory` table instead.
    """

    __tablename__ = "historical_inventory"

    product_id: Mapped[UUID] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    supplier_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("suppliers.id", ondelete="SET NULL"),
        nullable=True,
    )

    # ── Stock Levels ────────────────────────────────────────
    quantity_on_hand: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False,
        comment="Physical quantity in stock at observation time",
    )
    quantity_reserved: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False,
        comment="Quantity reserved for existing orders",
    )
    quantity_inbound: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False,
        comment="Quantity inbound from supplier",
    )
    quantity_available: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False,
        comment="Computed: on_hand - reserved (denormalized for query speed)",
    )

    # ── Location & Lot ────────────────────────────────────
    warehouse_location: Mapped[str | None] = mapped_column(
        String(100), nullable=True,
        comment="Warehouse aisle/bin location at observation time",
    )
    lot_number: Mapped[str | None] = mapped_column(
        String(100), nullable=True,
        comment="Manufacturing lot/batch number",
    )

    # ── Timestamp ─────────────────────────────────────────
    effective_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        server_default=func.now(),
        comment="When this inventory snapshot was taken",
    )

    # Relationships
    product: Mapped["Product"] = relationship(  # type: ignore[name-defined]
        "Product", back_populates="historical_inventory_records",
    )

    __table_args__ = (
        CheckConstraint(
            "quantity_on_hand >= 0",
            name="ck_historical_inventory_on_hand_non_negative",
        ),
        CheckConstraint(
            "quantity_reserved >= 0",
            name="ck_historical_inventory_reserved_non_negative",
        ),
        CheckConstraint(
            "quantity_inbound >= 0",
            name="ck_historical_inventory_inbound_non_negative",
        ),
        CheckConstraint(
            "quantity_available >= 0",
            name="ck_historical_inventory_available_non_negative",
        ),
        # Primary index for time-series queries
        Index(
            "ix_historical_inventory_effective",
            "product_id",
            "effective_date",
        ),
        # Secondary index for supplier-level analysis
        Index(
            "ix_historical_inventory_supplier",
            "product_id",
            "supplier_id",
            "effective_date",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<HistoricalInventory(id={self.id}, product={self.product_id}, "
            f"on_hand={self.quantity_on_hand}, effective={self.effective_date})>"
        )
