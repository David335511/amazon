"""Order domain models.

Represents customer orders and their line items.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.domain.models.product import Product


class Order(Base, TimestampMixin, UUIDMixin):
    """A customer order."""

    __tablename__ = "orders"

    customer_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(50),
        default="pending",
        nullable=False,
        index=True,
    )
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(precision=14, scale=2),
        default=Decimal("0.00"),
        nullable=False,
    )
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    shipping_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    items: Mapped[list[OrderItem]] = relationship(
        "OrderItem",
        back_populates="order",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Order(id={self.id}, customer={self.customer_id}, status={self.status!r})>"

    def recalculate_total(self) -> None:
        """Recalculate the order total from line items."""
        self.total_amount = sum(
            (item.unit_price * item.quantity for item in self.items),
            Decimal("0.00"),
        )


class OrderItem(Base, TimestampMixin, UUIDMixin):
    """A single line item within an order."""

    __tablename__ = "order_items"

    order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"),
        nullable=False,
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    unit_price: Mapped[Decimal] = mapped_column(
        Numeric(precision=12, scale=2),
        nullable=False,
    )
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)

    # Relationships
    order: Mapped[Order] = relationship("Order", back_populates="items")
    product: Mapped[Product] = relationship("Product", back_populates="order_items")

    def __repr__(self) -> str:
        return f"<OrderItem(id={self.id}, product={self.product_id}, qty={self.quantity})>"

    @property
    def subtotal(self) -> Decimal:
        """Calculate the line item subtotal."""
        return self.unit_price * self.quantity
