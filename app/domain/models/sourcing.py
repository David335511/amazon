"""Sourcing domain models — suppliers, pricing, fees, analytics, and user features.

Design principles:
- **Every price is historical**: ProductPrice, AmazonPrice, HistoricalFee are
  append-only. Never UPDATE or DELETE rows — always INSERT new records with
  the current effective_date.
- **Never overwrite history**: If a price changes, insert a new row. The
  previous row remains as an immutable record.
- **Normalized**: No duplicated data. Supplier addresses are in the suppliers
  table, not repeated across supplier_products.
- **Auditable**: All tables have created_at/updated_at. Soft delete where
  applicable.
"""

from __future__ import annotations

from decimal import Decimal
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.models.base import (
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    UUIDMixin,
)

if TYPE_CHECKING:
    from app.domain.models.product import Product


# ═══════════════════════════════════════════════════════════════
# Supplier
# ═══════════════════════════════════════════════════════════════


class Supplier(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """A product supplier/vendor.

    Stores company information and contact details. Each supplier can provide
    multiple products via the supplier_products junction table.
    """

    __tablename__ = "suppliers"

    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    company_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    website: Mapped[str | None] = mapped_column(String(500), nullable=True)
    address_line1: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address_line2: Mapped[str | None] = mapped_column(String(255), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    state: Mapped[str | None] = mapped_column(String(100), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    country: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    rating: Mapped[Decimal | None] = mapped_column(
        Numeric(3, 2), nullable=True,
        comment="Supplier rating 1.00-5.00",
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    supplier_products: Mapped[list[SupplierProduct]] = relationship(
        "SupplierProduct", back_populates="supplier",
    )

    __table_args__ = (
        CheckConstraint("rating >= 1.0 AND rating <= 5.0", name="ck_supplier_rating_range"),
    )

    def __repr__(self) -> str:
        return f"<Supplier(id={self.id}, name={self.name!r})>"


# ═══════════════════════════════════════════════════════════════
# Supplier Product (Junction)
# ═══════════════════════════════════════════════════════════════


class SupplierProduct(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """Junction table linking suppliers to products they provide.

    Each row represents a specific supplier's offering of a product, including
    their SKU, price, minimum order quantity, and lead time.
    """

    __tablename__ = "supplier_products"

    product_id: Mapped[UUID] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    supplier_id: Mapped[UUID] = mapped_column(
        ForeignKey("suppliers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    supplier_sku: Mapped[str | None] = mapped_column(
        String(100), nullable=True,
        comment="Supplier's internal SKU for this product",
    )
    supplier_price: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False,
        comment="Current price from this supplier",
    )
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    moq: Mapped[int] = mapped_column(
        Integer, default=1, nullable=False,
        comment="Minimum order quantity",
    )
    lead_time_days: Mapped[int | None] = mapped_column(
        Integer, nullable=True,
        comment="Typical lead time in days",
    )
    is_preferred: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False,
        comment="Preferred supplier for this product",
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Relationships
    product: Mapped[Product] = relationship("Product", back_populates="supplier_products")
    supplier: Mapped[Supplier] = relationship("Supplier", back_populates="supplier_products")

    __table_args__ = (
        UniqueConstraint("product_id", "supplier_id", name="uq_supplier_product"),
        CheckConstraint("moq >= 1", name="ck_supplier_product_moq"),
        CheckConstraint("supplier_price > 0", name="ck_supplier_product_price_positive"),
    )

    def __repr__(self) -> str:
        return (
            f"<SupplierProduct(product={self.product_id}, "
            f"supplier={self.supplier_id}, price={self.supplier_price})>"
        )


# ═══════════════════════════════════════════════════════════════
# Historical Prices (Append-Only)
# ═══════════════════════════════════════════════════════════════


class ProductPrice(Base, UUIDMixin, TimestampMixin):
    """Historical product cost/purchase prices — APPEND ONLY.

    Records the cost at which we can acquire a product from a supplier.
    Each new price observation creates a new row. Never UPDATE or DELETE.
    The `effective_date` indicates when this price became active.
    """

    __tablename__ = "product_prices"

    product_id: Mapped[UUID] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    supplier_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("suppliers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    price: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False,
        comment="Unit cost price",
    )
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    quantity_break: Mapped[int | None] = mapped_column(
        Integer, nullable=True,
        comment="Quantity threshold for this tier price",
    )
    source: Mapped[str] = mapped_column(
        String(50), default="manual", nullable=False,
        comment="Source of this price: supplier, manual, import, api",
    )
    effective_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        server_default=func.now(),
        comment="Date this price became effective",
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    product: Mapped[Product] = relationship("Product", back_populates="product_prices")

    __table_args__ = (
        CheckConstraint("price > 0", name="ck_product_price_positive"),
        Index("ix_product_prices_effective", "product_id", "effective_date"),
    )

    def __repr__(self) -> str:
        return (
            f"<ProductPrice(id={self.id}, product={self.product_id}, "
            f"price={self.price}, effective={self.effective_date})>"
        )


class AmazonPrice(Base, UUIDMixin, TimestampMixin):
    """Historical Amazon selling prices — APPEND ONLY.

    Records the price at which a product is listed/sold on Amazon.
    Includes condition, fulfillment channel, and buy box status.
    Each observation creates a new row. Never UPDATE or DELETE.
    """

    __tablename__ = "amazon_prices"

    product_id: Mapped[UUID] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    price: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False,
        comment="Selling price on Amazon",
    )
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    condition: Mapped[str] = mapped_column(
        String(50), default="New", nullable=False,
        comment="Product condition: New, Used, Refurbished, etc.",
    )
    is_amazon_fulfilled: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False,
        comment="Fulfilled by Amazon (FBA)",
    )
    is_buy_box: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False,
        comment="Is this the Buy Box price?",
    )
    is_prime: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False,
        comment="Eligible for Amazon Prime",
    )
    effective_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        server_default=func.now(),
        comment="Date this price was observed",
    )

    # Relationships
    product: Mapped[Product] = relationship("Product", back_populates="amazon_prices")

    __table_args__ = (
        CheckConstraint("price > 0", name="ck_amazon_price_positive"),
        Index("ix_amazon_prices_effective", "product_id", "effective_date"),
    )

    def __repr__(self) -> str:
        return (
            f"<AmazonPrice(id={self.id}, product={self.product_id}, "
            f"price={self.price}, buy_box={self.is_buy_box})>"
        )


class HistoricalFee(Base, UUIDMixin, TimestampMixin):
    """Historical Amazon fee data — APPEND ONLY.

    Records all Amazon-related fees for a product at a point in time.
    Includes referral fees, fulfillment fees, storage fees, and any other
    charges. Each observation creates a new row.
    """

    __tablename__ = "historical_fees"

    product_id: Mapped[UUID] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    referral_fee: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=0, nullable=False,
        comment="Amazon referral fee (percentage of sale price)",
    )
    closing_fee: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=0, nullable=False,
        comment="Amazon closing fee (media products)",
    )
    storage_fee: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=0, nullable=False,
        comment="Monthly storage fee",
    )
    fulfillment_fee: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=0, nullable=False,
        comment="FBA fulfillment fee per unit",
    )
    other_fees: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=0, nullable=False,
        comment="Any other Amazon fees",
    )
    total_fees: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=0, nullable=False,
        comment="Sum of all fees",
    )
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    effective_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        server_default=func.now(),
        comment="Date these fees were observed",
    )

    # Relationships
    product: Mapped[Product] = relationship("Product", back_populates="historical_fees")

    __table_args__ = (
        CheckConstraint("total_fees >= 0", name="ck_fees_total_non_negative"),
        Index("ix_historical_fees_effective", "product_id", "effective_date"),
    )

    def __repr__(self) -> str:
        return (
            f"<HistoricalFee(id={self.id}, product={self.product_id}, "
            f"total={self.total_fees})>"
        )


# ═══════════════════════════════════════════════════════════════
# Analytics (Append-Only)
# ═══════════════════════════════════════════════════════════════


class SellerCount(Base, UUIDMixin, TimestampMixin):
    """Historical seller count data — APPEND ONLY.

    Tracks the number of sellers offering a product on Amazon, broken down
    by new/used and FBA. Used for competition analysis.
    """

    __tablename__ = "seller_counts"

    product_id: Mapped[UUID] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    new_seller_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False,
        comment="Number of sellers offering new condition",
    )
    used_seller_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False,
        comment="Number of sellers offering used condition",
    )
    fba_seller_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False,
        comment="Number of FBA sellers",
    )
    effective_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        server_default=func.now(),
        comment="Date this count was observed",
    )

    # Relationships
    product: Mapped[Product] = relationship("Product", back_populates="seller_counts")

    __table_args__ = (
        CheckConstraint("new_seller_count >= 0", name="ck_seller_count_new_non_negative"),
        CheckConstraint("used_seller_count >= 0", name="ck_seller_count_used_non_negative"),
        CheckConstraint("fba_seller_count >= 0", name="ck_seller_count_fba_non_negative"),
        Index("ix_seller_counts_effective", "product_id", "effective_date"),
    )

    def __repr__(self) -> str:
        return (
            f"<SellerCount(id={self.id}, product={self.product_id}, "
            f"new={self.new_seller_count}, fba={self.fba_seller_count})>"
        )


class Review(Base, UUIDMixin, TimestampMixin):
    """Historical product review data — APPEND ONLY.

    Captures the aggregate review metrics for a product at a point in time.
    Includes average rating, total review count, and answered questions.
    """

    __tablename__ = "reviews"

    product_id: Mapped[UUID] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    rating: Mapped[Decimal] = mapped_column(
        Numeric(3, 2), nullable=False,
        comment="Average rating (1.00-5.00)",
    )
    review_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False,
        comment="Total number of reviews",
    )
    answered_questions: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False,
        comment="Number of answered questions",
    )
    effective_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        server_default=func.now(),
        comment="Date this review snapshot was taken",
    )

    # Relationships
    product: Mapped[Product] = relationship("Product", back_populates="reviews")

    __table_args__ = (
        CheckConstraint("rating >= 1.0 AND rating <= 5.0", name="ck_review_rating_range"),
        CheckConstraint("review_count >= 0", name="ck_review_count_non_negative"),
        Index("ix_reviews_effective", "product_id", "effective_date"),
    )

    def __repr__(self) -> str:
        return (
            f"<Review(id={self.id}, product={self.product_id}, "
            f"rating={self.rating}, count={self.review_count})>"
        )


class SalesEstimate(Base, UUIDMixin, TimestampMixin):
    """Historical sales estimate data — APPEND ONLY.

    Stores estimated sales volume and revenue for a product. Used for
    demand analysis and profit forecasting.
    """

    __tablename__ = "sales_estimates"

    product_id: Mapped[UUID] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    estimated_monthly_sales: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False,
        comment="Estimated sales per month",
    )
    estimated_daily_sales: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), default=0, nullable=False,
        comment="Estimated sales per day",
    )
    estimated_monthly_revenue: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=0, nullable=False,
        comment="Estimated monthly revenue in currency",
    )
    sales_rank: Mapped[int | None] = mapped_column(
        Integer, nullable=True,
        comment="Best Sellers Rank (lower is better)",
    )
    sales_rank_category: Mapped[str | None] = mapped_column(
        String(255), nullable=True,
        comment="Category for the sales rank",
    )
    effective_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        server_default=func.now(),
        comment="Date this estimate was generated",
    )

    # Relationships
    product: Mapped[Product] = relationship("Product", back_populates="sales_estimates")

    __table_args__ = (
        CheckConstraint(
            "estimated_monthly_sales >= 0",
            name="ck_sales_estimate_monthly_non_negative",
        ),
        Index("ix_sales_estimates_effective", "product_id", "effective_date"),
    )

    def __repr__(self) -> str:
        return (
            f"<SalesEstimate(id={self.id}, product={self.product_id}, "
            f"monthly={self.estimated_monthly_sales})>"
        )


# ═══════════════════════════════════════════════════════════════
# Profit Calculations (Append-Only)
# ═══════════════════════════════════════════════════════════════


class ProfitCalculation(Base, UUIDMixin, TimestampMixin):
    """Historical profit calculations — APPEND ONLY.

    Each row represents a profit calculation at a point in time, derived
    from the product cost, Amazon price, and fees. Foreign keys reference
    the specific price/fee rows used in the calculation for full auditability.
    """

    __tablename__ = "profit_calculations"

    product_id: Mapped[UUID] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    amazon_price_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("amazon_prices.id", ondelete="SET NULL"),
        nullable=True,
    )
    product_price_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("product_prices.id", ondelete="SET NULL"),
        nullable=True,
    )
    fee_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("historical_fees.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Input values (snapshot at calculation time)
    unit_cost: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False,
        comment="Cost per unit from supplier",
    )
    amazon_price: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False,
        comment="Selling price on Amazon",
    )
    referral_fee: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=0, nullable=False,
    )
    fulfillment_fee: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=0, nullable=False,
    )
    storage_fee: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=0, nullable=False,
    )
    other_costs: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=0, nullable=False,
        comment="Shipping, prep, labeling, etc.",
    )

    # Calculated values
    total_cost: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False,
        comment="unit_cost + all fees + other_costs",
    )
    gross_profit: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False,
        comment="amazon_price - unit_cost",
    )
    net_profit: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False,
        comment="amazon_price - total_cost",
    )
    margin_percentage: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False,
        comment="(net_profit / amazon_price) * 100",
    )
    roi_percentage: Mapped[Decimal] = mapped_column(
        Numeric(8, 2), nullable=False,
        comment="(net_profit / total_cost) * 100",
    )
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    effective_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        server_default=func.now(),
        comment="Date of this profit calculation",
    )

    # Relationships
    product: Mapped[Product] = relationship("Product", back_populates="profit_calculations")

    __table_args__ = (
        Index("ix_profit_calculations_effective", "product_id", "effective_date"),
    )

    def __repr__(self) -> str:
        return (
            f"<ProfitCalculation(id={self.id}, product={self.product_id}, "
            f"net_profit={self.net_profit}, margin={self.margin_percentage}%)>"
        )


# ═══════════════════════════════════════════════════════════════
# Inventory
# ═══════════════════════════════════════════════════════════════


class Inventory(Base, UUIDMixin, TimestampMixin):
    """Inventory tracking for products.

    Tracks physical stock levels including on-hand, reserved, and inbound
    quantities. Supports warehouse location tracking and lot management.
    """

    __tablename__ = "inventory"

    product_id: Mapped[UUID] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    supplier_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("suppliers.id", ondelete="SET NULL"),
        nullable=True,
    )
    quantity_on_hand: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False,
        comment="Physical quantity in stock",
    )
    quantity_reserved: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False,
        comment="Quantity reserved for existing orders",
    )
    quantity_inbound: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False,
        comment="Quantity inbound from supplier",
    )
    warehouse_location: Mapped[str | None] = mapped_column(
        String(100), nullable=True,
        comment="Warehouse aisle/bin location",
    )
    lot_number: Mapped[str | None] = mapped_column(
        String(100), nullable=True,
        comment="Manufacturing lot/batch number",
    )
    expiry_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment="Expiry date for perishable goods",
    )

    # Relationships
    product: Mapped[Product] = relationship("Product", back_populates="inventory_records")

    __table_args__ = (
        CheckConstraint(
            "quantity_on_hand >= 0",
            name="ck_inventory_on_hand_non_negative",
        ),
        CheckConstraint(
            "quantity_reserved >= 0",
            name="ck_inventory_reserved_non_negative",
        ),
        CheckConstraint(
            "quantity_inbound >= 0",
            name="ck_inventory_inbound_non_negative",
        ),
        Index("ix_inventory_product_supplier", "product_id", "supplier_id"),
    )

    @property
    def available_quantity(self) -> int:
        """Calculate available quantity (on_hand - reserved)."""
        return max(0, self.quantity_on_hand - self.quantity_reserved)

    def __repr__(self) -> str:
        return (
            f"<Inventory(id={self.id}, product={self.product_id}, "
            f"on_hand={self.quantity_on_hand})>"
        )


# ═══════════════════════════════════════════════════════════════
# User Features
# ═══════════════════════════════════════════════════════════════


class User(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """Platform user account.

    Stores authentication credentials, profile information, and role-based
    access control. Supports email verification and last login tracking.
    """

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True,
    )
    username: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, index=True,
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    role: Mapped[str] = mapped_column(
        String(50), default="user", nullable=False,
        comment="user, admin, manager",
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    email_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    # Relationships
    settings: Mapped[UserSettings | None] = relationship(
        "UserSettings", back_populates="user", uselist=False,
    )
    alerts: Mapped[list[Alert]] = relationship("Alert", back_populates="user")
    watchlist_items: Mapped[list[WatchlistItem]] = relationship(
        "WatchlistItem", back_populates="user",
    )
    notifications: Mapped[list[Notification]] = relationship(
        "Notification", back_populates="user",
    )

    def __repr__(self) -> str:
        return f"<User(id={self.id}, email={self.email!r}, role={self.role})>"


class UserSettings(Base, UUIDMixin, TimestampMixin):
    """Per-user application settings.

    One-to-one with User. Stores preferences for currency, profit targets,
    notification delivery, and UI display options.
    """

    __tablename__ = "user_settings"

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    default_currency: Mapped[str] = mapped_column(
        String(3), default="USD", nullable=False,
    )
    profit_margin_target: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 2), nullable=True,
        comment="Target profit margin percentage",
    )
    notification_preferences: Mapped[dict | None] = mapped_column(
        JSON, nullable=True,
        comment="JSON: email, push, in_app preferences",
    )
    display_preferences: Mapped[dict | None] = mapped_column(
        JSON, nullable=True,
        comment="JSON: UI theme, layout, columns",
    )

    # Relationships
    user: Mapped[User] = relationship("User", back_populates="settings")

    def __repr__(self) -> str:
        return f"<UserSettings(user={self.user_id}, currency={self.default_currency})>"


class Alert(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """User-defined alerts for product events.

    Alerts watch for specific conditions (price drops, profit thresholds,
    stock changes) and trigger notifications when conditions are met.
    """

    __tablename__ = "alerts"

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    product_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment="NULL for global alerts (e.g., any product in watchlist)",
    )
    alert_type: Mapped[str] = mapped_column(
        String(50), nullable=False,
        comment="price_drop, profit_threshold, stock_alert, price_increase, fee_change, new_seller",
    )
    condition: Mapped[dict] = mapped_column(
        JSON, nullable=False,
        comment="JSON: e.g. {'price_below': 10.00, 'margin_above': 30}",
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_triggered: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False,
        comment="Has this alert been triggered?",
    )
    last_triggered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    # Relationships
    user: Mapped[User] = relationship("User", back_populates="alerts")
    product: Mapped[Product | None] = relationship("Product", back_populates="alerts")

    __table_args__ = (
        Index("ix_alerts_user_type", "user_id", "alert_type"),
    )

    def __repr__(self) -> str:
        return (
            f"<Alert(id={self.id}, user={self.user_id}, "
            f"type={self.alert_type}, active={self.is_active})>"
        )


class WatchlistItem(Base, UUIDMixin, TimestampMixin):
    """User watchlist — products a user is tracking.

    Many-to-many between users and products with personal notes.
    """

    __tablename__ = "watchlist_items"

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    product_id: Mapped[UUID] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    user: Mapped[User] = relationship("User", back_populates="watchlist_items")
    product: Mapped[Product] = relationship("Product", back_populates="watchlist_items")

    __table_args__ = (
        UniqueConstraint("user_id", "product_id", name="uq_watchlist_user_product"),
    )

    def __repr__(self) -> str:
        return (
            f"<WatchlistItem(user={self.user_id}, product={self.product_id})>"
        )


class Notification(Base, UUIDMixin, TimestampMixin):
    """User notifications generated by alerts or system events.

    Supports multiple delivery channels (in_app, email, push) and tracks
    read status for the in-app notification center.
    """

    __tablename__ = "notifications"

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    alert_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("alerts.id", ondelete="SET NULL"),
        nullable=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    channel: Mapped[str] = mapped_column(
        String(50), default="in_app", nullable=False,
        comment="in_app, email, push, sms",
    )
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    # Relationships
    user: Mapped[User] = relationship("User", back_populates="notifications")

    __table_args__ = (
        Index("ix_notifications_user_read", "user_id", "is_read"),
    )

    def __repr__(self) -> str:
        return (
            f"<Notification(id={self.id}, user={self.user_id}, "
            f"title={self.title!r}, read={self.is_read})>"
        )


# Import HistoricalInventory from its own module to keep this file focused
from app.domain.models.historical_inventory import HistoricalInventory  # noqa: E402, F811
