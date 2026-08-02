"""Pydantic schemas for product API requests and responses.

Design decisions:
- Schemas are separate from ORM models to decouple API contracts from persistence.
- `ProductCreate` / `ProductUpdate` define strict input validation.
- `ProductResponse` includes computed fields and serialization config.
- Uses Decimal for monetary values to avoid floating-point errors.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProductCreate(BaseModel):
    """Schema for creating a new product."""

    asin: str = Field(..., min_length=1, max_length=10, pattern=r"^[A-Z0-9]+$")
    title: str = Field(..., min_length=1, max_length=500)
    description: str | None = Field(None, max_length=10_000)
    price: Decimal = Field(default=Decimal("0.00"), ge=0, max_digits=12, decimal_places=2)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    upc: str | None = Field(None, min_length=12, max_length=12, pattern=r"^\d{12}$")
    ean: str | None = Field(None, min_length=13, max_length=13, pattern=r"^\d{13}$")
    gtin: str | None = Field(None, min_length=14, max_length=14, pattern=r"^\d{14}$")
    brand_id: str | None = None
    category_id: str | None = None
    main_image_url: str | None = Field(None, max_length=500)
    weight: Decimal | None = Field(None, gt=0, max_digits=10, decimal_places=2)
    weight_unit: str | None = Field(None, max_length=10)
    dimensions: str | None = Field(None, max_length=100)

    @field_validator("asin")
    @classmethod
    def validate_asin(cls, v: str) -> str:
        """Ensure ASIN is uppercase and trimmed."""
        return v.strip().upper()


class ProductUpdate(BaseModel):
    """Schema for updating an existing product (partial update)."""

    title: str | None = Field(None, min_length=1, max_length=500)
    description: str | None = Field(None, max_length=10_000)
    upc: str | None = Field(None, min_length=12, max_length=12, pattern=r"^\d{12}$")
    ean: str | None = Field(None, min_length=13, max_length=13, pattern=r"^\d{13}$")
    gtin: str | None = Field(None, min_length=14, max_length=14, pattern=r"^\d{14}$")
    brand_id: str | None = None
    category_id: str | None = None
    main_image_url: str | None = Field(None, max_length=500)
    weight: Decimal | None = Field(None, gt=0, max_digits=10, decimal_places=2)
    weight_unit: str | None = Field(None, max_length=10)
    dimensions: str | None = Field(None, max_length=100)
    is_active: bool | None = None
    is_amazon_fba: bool | None = None


class ProductResponse(BaseModel):
    """Schema for product API responses."""

    id: uuid.UUID
    asin: str
    title: str
    description: str | None
    price: Decimal
    currency: str
    upc: str | None
    ean: str | None
    gtin: str | None
    brand_id: uuid.UUID | None
    category_id: uuid.UUID | None
    main_image_url: str | None
    weight: Decimal | None
    weight_unit: str | None
    dimensions: str | None
    is_active: bool
    is_amazon_fba: bool
    is_amazon_brand: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProductListResponse(BaseModel):
    """Schema for paginated product list responses."""

    items: list[ProductResponse]
    total: int
    page: int
    page_size: int
    total_pages: int
