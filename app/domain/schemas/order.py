"""Pydantic schemas for order API requests and responses.

Design decisions:
- Order creation accepts a list of line items with product IDs and quantities.
- The service layer resolves prices and calculates totals.
- Status transitions are validated at the service layer, not in schemas.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field, field_validator


class OrderItemCreate(BaseModel):
    """Schema for creating an order line item."""

    product_id: uuid.UUID
    quantity: int = Field(..., gt=0, le=10_000)


class OrderCreate(BaseModel):
    """Schema for creating a new order."""

    customer_id: uuid.UUID
    items: list[OrderItemCreate] = Field(..., min_length=1, max_length=100)
    shipping_address: str | None = Field(None, max_length=10_000)
    notes: str | None = Field(None, max_length=5_000)

    @field_validator("items")
    @classmethod
    def validate_unique_products(cls, v: list[OrderItemCreate]) -> list[OrderItemCreate]:
        """Ensure no duplicate product IDs in the order."""
        product_ids = [item.product_id for item in v]
        if len(product_ids) != len(set(product_ids)):
            msg = "Duplicate product IDs are not allowed in a single order"
            raise ValueError(msg)
        return v


class OrderItemResponse(BaseModel):
    """Schema for order line item responses."""

    id: uuid.UUID
    product_id: uuid.UUID
    quantity: int
    unit_price: Decimal
    currency: str
    subtotal: Decimal

    model_config = ConfigDict(from_attributes=True)


class OrderResponse(BaseModel):
    """Schema for order API responses."""

    id: uuid.UUID
    customer_id: uuid.UUID
    status: str
    total_amount: Decimal
    currency: str
    shipping_address: str | None
    notes: str | None
    items: list[OrderItemResponse]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class OrderListResponse(BaseModel):
    """Schema for paginated order list responses."""

    items: list[OrderResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class OrderStatusUpdate(BaseModel):
    """Schema for updating order status."""

    status: str = Field(..., min_length=1, max_length=50)
    notes: str | None = None

    VALID_STATUSES: ClassVar[frozenset[str]] = frozenset(
        {
            "pending",
            "confirmed",
            "processing",
            "shipped",
            "delivered",
            "cancelled",
            "refunded",
        }
    )

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        """Ensure status is one of the valid values."""
        normalized = v.strip().lower()
        if normalized not in cls.VALID_STATUSES:
            msg = f"Invalid status '{v}'. Must be one of: {', '.join(sorted(cls.VALID_STATUSES))}"
            raise ValueError(msg)
        return normalized
