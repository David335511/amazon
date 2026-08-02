"""Category model — hierarchical product categorization.

Uses an adjacency list (parent_id) with a materialized path for efficient
subtree queries. Supports arbitrary depth nesting for Amazon's deep
category trees.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.domain.models.product import Product


class Category(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """A product category in a hierarchical taxonomy."""

    __tablename__ = "categories"

    parent_id: Mapped[str | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    path: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="Materialized path for subtree queries, e.g. 'root_id/parent_id/this_id'",
    )
    level: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False,
        comment="Depth in hierarchy (0 = root)",
    )
    amazon_category_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True, unique=True,
        comment="Amazon's internal category/node ID",
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Self-referential relationship
    parent: Mapped[Category | None] = relationship(
        "Category",
        remote_side="Category.id",
        back_populates="children",
    )
    children: Mapped[list[Category]] = relationship(
        "Category",
        back_populates="parent",
        cascade="all, delete-orphan",
    )

    # Products in this category
    products: Mapped[list[Product]] = relationship("Product", back_populates="category_rel")

    def __repr__(self) -> str:
        return f"<Category(id={self.id}, name={self.name!r}, level={self.level})>"
