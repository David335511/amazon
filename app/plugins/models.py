"""Standardized data models for supplier plugin I/O.

Design decisions:
- All plugins use the same models — no supplier-specific types leak out.
- Monetary values use Decimal for precision.
- Optional fields use None for "not available" rather than sentinel values.
- Every model has a `raw` field for supplier-specific metadata.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field


class SupplierProductSearchResult(BaseModel):
    """Result from a supplier product search."""

    supplier_sku: str = Field(..., description="Supplier's SKU for this product")
    title: str = Field(..., description="Product title")
    upc: str | None = Field(None, description="UPC barcode")
    brand: str | None = Field(None, description="Brand name")
    manufacturer: str | None = Field(None, description="Manufacturer name")
    category: str | None = Field(None, description="Product category")
    image_url: str | None = Field(None, description="Product image URL")
    price: Decimal = Field(..., gt=0, description="Unit price")
    currency: str = Field(default="USD", description="Currency code")
    moq: int = Field(default=1, ge=1, description="Minimum order quantity")
    in_stock: bool = Field(default=True, description="Is in stock?")
    estimated_delivery_days: int | None = Field(None, description="Estimated delivery time")
    raw: dict[str, Any] = Field(default_factory=dict, description="Raw supplier data")


class SupplierProductLookup(BaseModel):
    """Result from a supplier product lookup by SKU/UPC."""

    supplier_sku: str = Field(..., description="Supplier's SKU")
    title: str = Field(..., description="Product title")
    description: str | None = Field(None, description="Full description")
    upc: str | None = Field(None, description="UPC barcode")
    brand: str | None = Field(None, description="Brand name")
    manufacturer: str | None = Field(None, description="Manufacturer name")
    category: str | None = Field(None, description="Product category")
    images: list[str] = Field(default_factory=list, description="Product images")
    features: list[str] = Field(default_factory=list, description="Bullet points")
    weight: Decimal | None = Field(None, description="Product weight")
    weight_unit: str | None = Field(None, description="Weight unit")
    dimensions: str | None = Field(None, description="Product dimensions")
    price: Decimal = Field(..., gt=0, description="Unit price")
    currency: str = Field(default="USD", description="Currency code")
    moq: int = Field(default=1, ge=1, description="Minimum order quantity")
    lead_time_days: int | None = Field(None, description="Manufacturing lead time")
    raw: dict[str, Any] = Field(default_factory=dict, description="Raw supplier data")


class SupplierPricing(BaseModel):
    """Pricing information from a supplier."""

    unit_price: Decimal = Field(..., gt=0, description="Price per unit")
    currency: str = Field(default="USD", description="Currency code")
    quantity_tiers: list[dict[str, Decimal]] = Field(
        default_factory=list,
        description="Volume pricing tiers: [{'min_qty': 10, 'price': 8.50}, ...]",
    )
    map_price: Decimal | None = Field(None, description="Minimum Advertised Price")
    suggested_retail: Decimal | None = Field(None, description="MSRP")
    effective_date: datetime | None = Field(None, description="Price effective date")
    raw: dict[str, Any] = Field(default_factory=dict, description="Raw supplier data")


class SupplierInventory(BaseModel):
    """Inventory information from a supplier."""

    supplier_sku: str = Field(..., description="Supplier's SKU")
    quantity_available: int = Field(default=0, ge=0, description="Available quantity")
    quantity_inbound: int = Field(default=0, ge=0, description="Inbound quantity")
    estimated_restock_date: datetime | None = Field(None, description="Expected restock date")
    warehouse_location: str | None = Field(None, description="Warehouse/DC location")
    is_backorderable: bool = Field(default=False, description="Can be backordered?")
    raw: dict[str, Any] = Field(default_factory=dict, description="Raw supplier data")


class SupplierShipping(BaseModel):
    """Shipping options and costs from a supplier."""

    methods: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Available shipping methods: [{'name': 'Standard', 'cost': 5.99, 'days': 5}, ...]",
    )
    free_shipping_threshold: Decimal | None = Field(
        None, description="Order amount for free shipping",
    )
    ships_from: str | None = Field(None, description="Origin location")
    ships_to: list[str] = Field(default_factory=list, description="Destination countries")
    raw: dict[str, Any] = Field(default_factory=dict, description="Raw supplier data")


class SupplierCoupon(BaseModel):
    """Coupon/discount information from a supplier."""

    code: str = Field(..., description="Coupon code")
    description: str | None = Field(None, description="Coupon description")
    discount_type: str = Field(
        ..., description="Discount type: percentage, fixed_amount, free_shipping",
    )
    discount_value: Decimal = Field(..., gt=0, description="Discount amount or percentage")
    min_order_amount: Decimal | None = Field(None, description="Minimum order for coupon")
    valid_from: datetime | None = Field(None, description="Coupon start date")
    valid_until: datetime | None = Field(None, description="Coupon expiry date")
    is_active: bool = Field(default=True, description="Is coupon currently active?")
    raw: dict[str, Any] = Field(default_factory=dict, description="Raw supplier data")


class SupplierAvailability(BaseModel):
    """Product availability status from a supplier."""

    supplier_sku: str = Field(..., description="Supplier's SKU")
    is_available: bool = Field(..., description="Is product available for order?")
    estimated_delivery_days: int | None = Field(None, description="Delivery estimate")
    backorder_allowed: bool = Field(default=False, description="Can be backordered?")
    backorder_eta: datetime | None = Field(None, description="Backorder ETA")
    stock_status: str = Field(
        default="unknown",
        description="Stock status: in_stock, low_stock, out_of_stock, discontinued, backorder",
    )
    raw: dict[str, Any] = Field(default_factory=dict, description="Raw supplier data")
