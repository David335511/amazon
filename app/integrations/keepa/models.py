"""Pydantic models for Keepa API requests and responses.

Design decisions:
- Models are typed and validated at the boundary (API ↔ service).
- Keepa's compact integer array format is decoded into human-readable models.
- Separate request/response models for each API endpoint.
- All monetary values use Decimal for precision.
- Timestamps are converted from Keepa's epoch-minute format to datetime.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ═══════════════════════════════════════════════════════════════
# Request Models
# ═══════════════════════════════════════════════════════════════


class KeepaProductRequest(BaseModel):
    """Parameters for the Keepa Product API request.

    See: https://keepa.com/#!discuss/t/product-request-api/116
    """

    asin: str = Field(..., min_length=1, max_length=10, description="Amazon ASIN")
    domain: str = Field(default="com", description="Amazon domain code (com, co.uk, de, etc.)")
    offers: int = Field(
        default=20, ge=0, le=100,
        description="Number of offers to retrieve (0 = no offers, max 100)",
    )
    buybox: bool = Field(
        default=True,
        description="Include Buy Box data",
    )
    rating: bool = Field(
        default=True,
        description="Include review/rating data",
    )
    history: bool = Field(
        default=True,
        description="Include price history data",
    )


class KeepaCategoryRequest(BaseModel):
    """Parameters for the Keepa Category search request."""

    category_id: int | None = Field(None, description="Amazon category node ID")
    domain: str = Field(default="com", description="Amazon domain code")
    parents: bool = Field(default=False, description="Include parent categories")
    children: bool = Field(default=True, description="Include child categories")


class KeepaBestSellersRequest(BaseModel):
    """Parameters for the Keepa Best Sellers request."""

    category_id: int = Field(..., description="Amazon category node ID")
    domain: str = Field(default="com", description="Amazon domain code")


# ═══════════════════════════════════════════════════════════════
# Response Models
# ═══════════════════════════════════════════════════════════════


class KeepaPricePoint(BaseModel):
    """A single price point from Keepa's history data.

    Keepa stores time-series data in parallel integer arrays:
    - time: epoch minutes since Keepa epoch (2011-01-01)
    - price: integer * 0.001 = USD
    """

    timestamp: datetime = Field(..., description="Date/time of this price point")
    price: Decimal = Field(..., description="Price in USD")
    is_buy_box: bool = Field(default=False, description="Is this the Buy Box price?")


class KeepaOffer(BaseModel):
    """A single offer from Keepa's offer data."""

    seller_id: str | None = Field(None, description="Amazon seller ID")
    price: Decimal = Field(..., description="Offer price")
    condition: str = Field(default="New", description="Product condition")
    is_fba: bool = Field(default=False, description="Fulfilled by Amazon")
    is_prime: bool = Field(default=False, description="Prime eligible")
    delivery_days: int | None = Field(None, description="Estimated delivery days")
    seller_rating: Decimal | None = Field(None, description="Seller rating percentage")
    seller_count: int | None = Field(None, description="Seller feedback count")
    is_amazon: bool = Field(default=False, description="Sold by Amazon")


class KeepaReviewData(BaseModel):
    """Review/rating data from Keepa."""

    rating: Decimal | None = Field(None, description="Average rating (1.0-5.0)")
    review_count: int = Field(default=0, description="Total number of reviews")
    answered_questions: int = Field(default=0, description="Number of answered questions")
    rating_distribution: dict[int, int] = Field(
        default_factory=dict,
        description="Rating distribution: {5: count, 4: count, ...}",
    )


class KeepaSalesEstimate(BaseModel):
    """Sales estimate data from Keepa."""

    estimated_monthly_sales: int = Field(default=0, description="Estimated sales per month")
    estimated_daily_sales: Decimal = Field(
        default=Decimal("0"), description="Estimated sales per day",
    )
    sales_rank: int | None = Field(None, description="Current Best Sellers Rank")
    sales_rank_drops_30: int | None = Field(
        None, description="BSR rank drops in last 30 days",
    )
    sales_rank_history: list[int] | None = Field(
        None, description="Historical BSR values (lower = better)",
    )


class KeepaSellerInfo(BaseModel):
    """Seller information from Keepa."""

    seller_id: str = Field(..., description="Amazon seller ID")
    seller_name: str | None = Field(None, description="Seller display name")
    seller_rating: Decimal | None = Field(None, description="Seller rating percentage")
    seller_count: int = Field(default=0, description="Number of seller feedback ratings")
    is_amazon: bool = Field(default=False, description="Is this Amazon itself?")
    is_fba: bool = Field(default=False, description="Does this seller use FBA?")
    offers_count: int = Field(default=0, description="Number of offers from this seller")


class KeepaCategory(BaseModel):
    """Amazon category information from Keepa."""

    category_id: int = Field(..., description="Amazon category node ID")
    name: str = Field(..., description="Category name")
    parent_id: int | None = Field(None, description="Parent category node ID")
    children: list[int] = Field(default_factory=list, description="Child category node IDs")


class KeepaBestSellersResponse(BaseModel):
    """Best sellers list response from Keepa."""

    category_id: int = Field(..., description="Category node ID")
    asins: list[str] = Field(default_factory=list, description="List of ASINs in rank order")
    domain: str = Field(default="com", description="Amazon domain")


class KeepaProductResponse(BaseModel):
    """Complete product data response from Keepa.

    This is the primary response model. It contains all data returned
    by the Keepa Product API for a single ASIN.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    asin: str = Field(..., description="Amazon ASIN")
    domain: str = Field(default="com", description="Amazon domain")
    title: str | None = Field(None, description="Product title")
    brand: str | None = Field(None, description="Product brand")
    description: str | None = Field(None, description="Product description")
    features: list[str] = Field(default_factory=list, description="Product bullet points")
    upc: str | None = Field(None, description="Universal Product Code")
    ean: str | None = Field(None, description="European Article Number")
    model_number: str | None = Field(None, description="Manufacturer model number")
    manufacturer: str | None = Field(None, description="Manufacturer name")
    category_id: int | None = Field(None, description="Amazon category node ID")
    category_tree: list[KeepaCategory] = Field(
        default_factory=list, description="Category breadcrumb tree",
    )

    # Images
    images: list[str] = Field(default_factory=list, description="Product image URLs")
    main_image: str | None = Field(None, description="Main product image URL")

    # Dimensions & Weight
    dimensions: str | None = Field(None, description="Product dimensions (e.g. '10x8x5 inches')")
    weight: Decimal | None = Field(None, description="Product weight")
    weight_unit: str | None = Field(None, description="Weight unit (pounds, ounces, etc.)")

    # Current pricing
    current_price: Decimal | None = Field(None, description="Current Amazon price")
    current_buy_box_price: Decimal | None = Field(None, description="Current Buy Box price")
    current_used_price: Decimal | None = Field(None, description="Current lowest used price")
    currency: str = Field(default="USD", description="Currency code")

    # Price history (time series)
    amazon_price_history: list[KeepaPricePoint] = Field(
        default_factory=list, description="Amazon price history",
    )
    buy_box_price_history: list[KeepaPricePoint] = Field(
        default_factory=list, description="Buy Box price history",
    )
    used_price_history: list[KeepaPricePoint] = Field(
        default_factory=list, description="Used price history",
    )
    sales_rank_history: list[KeepaPricePoint] = Field(
        default_factory=list, description="Sales rank history (lower = better)",
    )

    # Offers
    offers: list[KeepaOffer] = Field(default_factory=list, description="Current offers")
    offer_count: int = Field(default=0, description="Total number of offers")
    fba_offer_count: int = Field(default=0, description="Number of FBA offers")

    # Sellers
    sellers: list[KeepaSellerInfo] = Field(
        default_factory=list, description="Seller information",
    )
    seller_count: int = Field(default=0, description="Number of unique sellers")

    # Reviews
    reviews: KeepaReviewData = Field(
        default_factory=KeepaReviewData, description="Review data",
    )

    # Sales estimates
    sales_estimates: KeepaSalesEstimate = Field(
        default_factory=KeepaSalesEstimate, description="Sales estimate data",
    )

    # Raw data (for debugging / advanced use)
    raw_data: dict[str, Any] | None = Field(
        None, description="Raw Keepa API response data",
    )

    @field_validator("current_price", "current_buy_box_price", "current_used_price", mode="before")
    @classmethod
    def parse_price(cls, v: Any) -> Decimal | None:
        """Parse price values, handling None and empty strings."""
        if v is None or v == "":
            return None
        return Decimal(str(v))

    @field_validator("weight", mode="before")
    @classmethod
    def parse_weight(cls, v: Any) -> Decimal | None:
        """Parse weight values."""
        if v is None or v == "":
            return None
        return Decimal(str(v))
