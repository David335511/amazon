"""Domain models — all SQLAlchemy ORM models for the Amazon sourcing platform."""

from app.domain.models.base import Base, UUIDMixin, TimestampMixin, SoftDeleteMixin, AuditMixin
from app.domain.models.brand import Brand
from app.domain.models.category import Category
from app.domain.models.product import Product
from app.domain.models.order import Order, OrderItem
from app.domain.models.sourcing import (
    Alert,
    AmazonPrice,
    HistoricalFee,
    HistoricalInventory,
    Inventory,
    Notification,
    ProductPrice,
    ProfitCalculation,
    Review,
    SalesEstimate,
    SellerCount,
    Supplier,
    SupplierProduct,
    User,
    UserSettings,
    WatchlistItem,
)

__all__ = [
    "Base",
    "UUIDMixin",
    "TimestampMixin",
    "SoftDeleteMixin",
    "AuditMixin",
    "Brand",
    "Category",
    "Product",
    "Order",
    "OrderItem",
    "Supplier",
    "SupplierProduct",
    "ProductPrice",
    "AmazonPrice",
    "HistoricalFee",
    "HistoricalInventory",
    "SellerCount",
    "Review",
    "SalesEstimate",
    "ProfitCalculation",
    "Inventory",
    "User",
    "UserSettings",
    "Alert",
    "WatchlistItem",
    "Notification",
]
