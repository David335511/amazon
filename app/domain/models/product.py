"""Product domain model — core entity for the sourcing platform.

Each product is identified by its Amazon ASIN and optionally has UPC, EAN,
and GTIN barcodes. Products belong to a Brand and a Category. All pricing
data is stored in separate historical tables — this table only holds
identity and descriptive attributes.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.domain.models.brand import Brand
    from app.domain.models.category import Category
    from app.domain.models.order import OrderItem
    from app.domain.models.sourcing import (
        Alert,
        AmazonPrice,
        HistoricalFee,
        HistoricalInventory,
        Inventory,
        ProductPrice,
        ProfitCalculation,
        Review,
        SalesEstimate,
        SellerCount,
        SupplierProduct,
        WatchlistItem,
    )


class Product(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """A sellable product in the Amazon sourcing catalog."""

    __tablename__ = "products"

    # ── Amazon Identifiers ──────────────────────────────────
    asin: Mapped[str] = mapped_column(
        String(10), unique=True, nullable=False, index=True,
        comment="Amazon Standard Identification Number",
    )
    upc: Mapped[str | None] = mapped_column(
        String(12), nullable=True, index=True,
        comment="Universal Product Code",
    )
    ean: Mapped[str | None] = mapped_column(
        String(13), nullable=True, index=True,
        comment="European Article Number",
    )
    gtin: Mapped[str | None] = mapped_column(
        String(14), nullable=True, index=True,
        comment="Global Trade Item Number",
    )

    # ── Descriptive Attributes ──────────────────────────────
    title: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    brand_id: Mapped[str | None] = mapped_column(
        ForeignKey("brands.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    category_id: Mapped[str | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    main_image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    image_urls: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="JSON array of additional image URLs",
    )

    # ── Physical Attributes ────────────────────────────────
    price: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=0,
        comment="Current selling price (source of truth in amazon_prices table)",
    )
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    weight: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    weight_unit: Mapped[str | None] = mapped_column(String(10), nullable=True)
    dimensions: Mapped[str | None] = mapped_column(
        String(100), nullable=True,
        comment="e.g. '10x8x5 inches'",
    )

    # ── Amazon-specific Flags ────────────────────────────────
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_amazon_fba: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False,
        comment="Fulfilled by Amazon",
    )
    is_amazon_brand: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False,
        comment="Amazon-owned brand (e.g. AmazonBasics)",
    )

    # ── Relationships ───────────────────────────────────────
    brand: Mapped[Brand | None] = relationship("Brand", back_populates="products")
    category_rel: Mapped[Category | None] = relationship(
        "Category", back_populates="products",
    )

    # Commerce (existing)
    order_items: Mapped[list[OrderItem]] = relationship(
        "OrderItem", back_populates="product",
    )

    # Sourcing
    supplier_products: Mapped[list[SupplierProduct]] = relationship(
        "SupplierProduct", back_populates="product",
    )
    product_prices: Mapped[list[ProductPrice]] = relationship(
        "ProductPrice", back_populates="product",
    )
    amazon_prices: Mapped[list[AmazonPrice]] = relationship(
        "AmazonPrice", back_populates="product",
    )
    historical_fees: Mapped[list[HistoricalFee]] = relationship(
        "HistoricalFee", back_populates="product",
    )
    profit_calculations: Mapped[list[ProfitCalculation]] = relationship(
        "ProfitCalculation", back_populates="product",
    )
    seller_counts: Mapped[list[SellerCount]] = relationship(
        "SellerCount", back_populates="product",
    )
    reviews: Mapped[list[Review]] = relationship(
        "Review", back_populates="product",
    )
    sales_estimates: Mapped[list[SalesEstimate]] = relationship(
        "SalesEstimate", back_populates="product",
    )
    inventory_records: Mapped[list[Inventory]] = relationship(
        "Inventory", back_populates="product",
    )
    historical_inventory_records: Mapped[list[HistoricalInventory]] = relationship(
        "HistoricalInventory", back_populates="product",
    )
    alerts: Mapped[list[Alert]] = relationship(
        "Alert", back_populates="product",
    )
    watchlist_items: Mapped[list[WatchlistItem]] = relationship(
        "WatchlistItem", back_populates="product",
    )

    def __repr__(self) -> str:
        return f"<Product(id={self.id}, asin={self.asin}, title={self.title!r})>"

    def has_available_stock(self, quantity: int = 1) -> bool:
        """Check if the requested quantity is available via inventory.

        Note: This is a simplified check. The full implementation should
        query the Inventory table for actual stock levels.
        """
        return True  # Stock checking delegated to Inventory model

    def reduce_stock(self, quantity: int) -> None:
        """Reduce stock by the given quantity.

        Note: Stock management is delegated to the Inventory model.
        This is a placeholder for the commerce order flow.
        """

    def increase_stock(self, quantity: int) -> None:
        """Increase stock by the given quantity.

        Note: Stock management is delegated to the Inventory model.
        """
