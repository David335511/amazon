"""Brand model — normalized brand information.

Each product belongs to exactly one brand. Brands are normalized to avoid
repeating brand names across thousands of products and to enable brand-level
analytics and filtering.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.domain.models.product import Product


class Brand(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """A product brand/manufacturer."""

    __tablename__ = "brands"

    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    logo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    website_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Relationships
    products: Mapped[list[Product]] = relationship("Product", back_populates="brand")

    def __repr__(self) -> str:
        return f"<Brand(id={self.id}, name={self.name!r})>"
