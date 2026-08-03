"""ORM models for reverse sourcing.

Two tables:

- ``reverse_sourcing_runs`` — one row per reverse-sourcing run for an ASIN,
  recording the inputs (ASIN, UPC, quantity, destination) and the resulting
  highlights + summary.
- ``reverse_sourcing_offers`` — one row per supplier per run, capturing the
  supplier's offer (unit price, shipping, landed cost, availability, discount,
  rank, predicted discount). Accumulated across runs this becomes the
  **historical** per-(supplier, ASIN) price / discount series.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.models.base import Base, TimestampMixin, UUIDMixin


class ReverseSourcingRun(Base, UUIDMixin, TimestampMixin):
    """A single reverse-sourcing run for an Amazon ASIN."""

    __tablename__ = "reverse_sourcing_runs"

    asin: Mapped[str] = mapped_column(
        String(16), nullable=False, index=True,
        comment="Amazon ASIN being sourced",
    )
    upc: Mapped[str | None] = mapped_column(String(16), nullable=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    postal_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD")

    best_supplier: Mapped[str | None] = mapped_column(String(48), nullable=True)
    cheapest_supplier: Mapped[str | None] = mapped_column(String(48), nullable=True)
    fastest_supplier: Mapped[str | None] = mapped_column(String(48), nullable=True)
    highest_confidence_supplier: Mapped[str | None] = mapped_column(String(48), nullable=True)

    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")

    def __repr__(self) -> str:
        return f"<ReverseSourcingRun({self.asin}, {self.created_at})>"


class ReverseSourcingOffer(Base, UUIDMixin, TimestampMixin):
    """One supplier's offer captured during a reverse-sourcing run."""

    __tablename__ = "reverse_sourcing_offers"

    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("reverse_sourcing_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    supplier_code: Mapped[str] = mapped_column(
        String(48), nullable=False, index=True,
        comment="Supplier code (walmart, target, ...)",
    )
    supplier_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    supplier_sku: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    unit_price: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD")
    shipping_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    shipping_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    landed_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    in_stock: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    stock_status: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")
    moq: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    current_discount: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    predicted_discount: Mapped[float | None] = mapped_column(Float, nullable=True)
    rank: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<ReverseSourcingOffer({self.supplier_code}, landed={self.landed_cost})>"
