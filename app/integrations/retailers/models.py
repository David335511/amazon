"""Pydantic models for retailer (Walmart / Home Depot) product data.

Design decisions:
- A single normalized RetailerProduct model represents data from any supported
  retailer so the sourcing engine can consume a consistent shape.
- Parsing is defensive: every field falls back to a sensible default because
  third-party payloads can vary between retailers and over time.
- All monetary values use Decimal for precision.
- Raw payloads are retained for debugging and advanced use.
"""

from __future__ import annotations

from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, Field, field_validator

# ═══════════════════════════════════════════════════════════════
# Enums
# ═══════════════════════════════════════════════════════════════


class RetailerProvider(str, Enum):
    """Supported retailers."""

    WALMART = "walmart"
    HOME_DEPOT = "home_depot"

    @property
    def serp_engine(self) -> str:
        """SerpApi engine name for this provider."""
        return {
            RetailerProvider.WALMART: "walmart_product",
            RetailerProvider.HOME_DEPOT: "home_depot_product",
        }[self]

    @property
    def display_name(self) -> str:
        return {
            RetailerProvider.WALMART: "Walmart",
            RetailerProvider.HOME_DEPOT: "Home Depot",
        }[self]


# ═══════════════════════════════════════════════════════════════
# Request Models
# ═══════════════════════════════════════════════════════════════


class RetailerLookupRequest(BaseModel):
    """Parameters for a retailer product lookup."""

    product_id: str = Field(
        ...,
        min_length=1,
        description="Retailer item number / product id",
    )
    provider: RetailerProvider = Field(
        ...,
        description="Which retailer to query",
    )
    country: str = Field(
        default="us",
        description="Marketplace country code (us, ca, mx, ...)",
    )
    delivery_zip: str | None = Field(
        None,
        description="Zip code for delivery/store-localized results",
    )
    store_id: str | None = Field(
        None,
        description="Retailer store id for store-localized results",
    )


# ═══════════════════════════════════════════════════════════════
# Response Models
# ═══════════════════════════════════════════════════════════════


class RetailerPrice(BaseModel):
    """Pricing snapshot from a retailer."""

    current: Decimal | None = Field(None, description="Current selling price")
    original: Decimal | None = Field(None, description="Original / list price, if any")
    currency: str = Field(default="USD", description="Currency code")

    @property
    def is_on_sale(self) -> bool:
        """True if current price is below the original price."""
        if self.current is None or self.original is None:
            return False
        return self.current < self.original

    @property
    def savings(self) -> Decimal | None:
        """Absolute savings when on sale, else None."""
        if self.current is None or self.original is None:
            return None
        if self.current >= self.original:
            return None
        return self.original - self.current


class RetailerRating(BaseModel):
    """Rating and review volume from a retailer."""

    rating: Decimal | None = Field(None, description="Average rating (e.g. 4.5/5)")
    review_count: int = Field(default=0, description="Number of reviews")
    rating_max: Decimal = Field(default=Decimal("5"), description="Rating scale maximum")


class RetailerProduct(BaseModel):
    """Normalized product data from a retailer (Walmart / Home Depot)."""

    provider: RetailerProvider = Field(..., description="Retailer that supplied the data")
    product_id: str = Field(..., description="Retailer item number / product id")

    # Identity
    title: str | None = Field(None, description="Product title")
    brand: str | None = Field(None, description="Product brand")
    model_number: str | None = Field(None, description="Manufacturer model number")
    upc: str | None = Field(None, description="Universal Product Code")
    sku: str | None = Field(None, description="Retailer SKU, if any")
    url: str | None = Field(None, description="Canonical product URL")

    # Pricing
    price: RetailerPrice = Field(default_factory=RetailerPrice, description="Pricing snapshot")

    # Ratings
    rating: RetailerRating = Field(default_factory=RetailerRating, description="Rating data")

    # Availability / competition
    availability: str | None = Field(None, description="Availability status text")
    in_stock: bool | None = Field(None, description="Whether the item is in stock")
    seller_count: int | None = Field(None, description="Approx. seller/offer count, if reported")

    # Media
    image: str | None = Field(None, description="Primary product image URL")

    # Raw payload (for debugging / advanced use)
    raw_data: dict | None = Field(None, description="Raw provider response data")

    @field_validator("price", mode="before")
    @classmethod
    def parse_price(cls, v: object) -> object:
        """Coerce a bare price into a RetailerPrice."""
        if isinstance(v, (int, float, str)):
            return RetailerPrice(current=Decimal(str(v)))
        return v

    @field_validator("rating", mode="before")
    @classmethod
    def parse_rating(cls, v: object) -> object:
        """Coerce a bare rating into a RetailerRating."""
        if isinstance(v, (int, float, str)):
            return RetailerRating(rating=Decimal(str(v)))
        return v

    @field_validator("product_id", "title", "brand", "model_number", "upc", "sku", "url")
    @classmethod
    def strip_strings(cls, v: object) -> object:
        """Strip whitespace from identifier/string fields."""
        if isinstance(v, str):
            return v.strip()
        return v
