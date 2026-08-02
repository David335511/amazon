"""Product sourcing DTOs — clean API contracts separate from database models.

Design decisions:
- DTOs are pure Pydantic models with no ORM dependencies.
- Response DTOs use `model_config = ConfigDict(from_attributes=True)` for
  optional ORM conversion, but the primary path is service → DTO directly.
- Pagination is built into list responses for consistency.
- All monetary values use Decimal for precision.
- Timestamps use datetime with timezone awareness.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# ═══════════════════════════════════════════════════════════════
# Request DTOs
# ═══════════════════════════════════════════════════════════════


class ProductSearchRequest(BaseModel):
    """Search products by title with pagination."""

    q: str = Field(..., min_length=1, max_length=500, description="Search query")
    page: int = Field(default=1, ge=1, description="Page number")
    page_size: int = Field(default=20, ge=1, le=100, description="Items per page")
    domain: str = Field(default="com", description="Amazon domain code")


class ProductRefreshRequest(BaseModel):
    """Request to refresh product data from Keepa."""

    asin: str = Field(..., min_length=1, max_length=10, description="Amazon ASIN")
    domain: str = Field(default="com", description="Amazon domain code")
    wait_for_result: bool = Field(
        default=False,
        description="If True, wait for refresh to complete. If False, process async.",
    )


class ProductBatchRefreshRequest(BaseModel):
    """Request to refresh multiple products."""

    asins: list[str] = Field(..., min_length=1, max_length=100, description="List of ASINs")
    domain: str = Field(default="com", description="Amazon domain code")


# ═══════════════════════════════════════════════════════════════
# Response DTOs
# ═══════════════════════════════════════════════════════════════


class PricePointDTO(BaseModel):
    """A single price observation point."""

    timestamp: datetime = Field(..., description="When this price was observed")
    price: Decimal = Field(..., description="Price value")
    is_buy_box: bool = Field(default=False, description="Is this the Buy Box price?")
    condition: str = Field(default="New", description="Product condition")
    is_fba: bool = Field(default=False, description="Fulfilled by Amazon")


class ReviewSummaryDTO(BaseModel):
    """Product review summary."""

    rating: Decimal | None = Field(None, description="Average rating (1.0-5.0)")
    review_count: int = Field(default=0, description="Total review count")
    answered_questions: int = Field(default=0, description="Answered questions count")
    observed_at: datetime | None = Field(None, description="When this data was observed")


class SalesEstimateDTO(BaseModel):
    """Sales estimate data."""

    estimated_monthly_sales: int = Field(default=0, description="Estimated sales per month")
    estimated_daily_sales: Decimal = Field(default=Decimal("0"), description="Estimated sales per day")
    sales_rank: int | None = Field(None, description="Best Sellers Rank")
    observed_at: datetime | None = Field(None, description="When this estimate was generated")


class SellerCountDTO(BaseModel):
    """Seller count snapshot."""

    new_seller_count: int = Field(default=0, description="New-condition sellers")
    used_seller_count: int = Field(default=0, description="Used-condition sellers")
    fba_seller_count: int = Field(default=0, description="FBA sellers")
    observed_at: datetime | None = Field(None, description="When this count was observed")


class ProductSummaryDTO(BaseModel):
    """Summary product information for list/search results."""

    id: UUID = Field(..., description="Database product ID")
    asin: str = Field(..., description="Amazon ASIN")
    title: str = Field(..., description="Product title")
    brand: str | None = Field(None, description="Brand name")
    main_image_url: str | None = Field(None, description="Main product image")
    price: Decimal | None = Field(None, description="Current price")
    currency: str = Field(default="USD", description="Currency")
    is_active: bool = Field(default=True, description="Is product active?")
    created_at: datetime = Field(..., description="When product was added")
    updated_at: datetime = Field(..., description="Last update timestamp")

    model_config = ConfigDict(from_attributes=True)


class ProductDetailDTO(BaseModel):
    """Complete product details with all associated data."""

    # Identity
    id: UUID = Field(..., description="Database product ID")
    asin: str = Field(..., description="Amazon ASIN")
    title: str = Field(..., description="Product title")
    description: str | None = Field(None, description="Product description")
    brand: str | None = Field(None, description="Brand name")
    upc: str | None = Field(None, description="UPC barcode")
    ean: str | None = Field(None, description="EAN barcode")
    gtin: str | None = Field(None, description="GTIN barcode")

    # Media
    main_image_url: str | None = Field(None, description="Main product image")
    image_urls: list[str] = Field(default_factory=list, description="Additional images")

    # Physical
    dimensions: str | None = Field(None, description="Product dimensions")
    weight: Decimal | None = Field(None, description="Product weight")
    weight_unit: str | None = Field(None, description="Weight unit")

    # Pricing
    price: Decimal | None = Field(None, description="Current Amazon price")
    buy_box_price: Decimal | None = Field(None, description="Current Buy Box price")
    currency: str = Field(default="USD", description="Currency")

    # Amazon flags
    is_active: bool = Field(default=True, description="Is product active?")
    is_amazon_fba: bool = Field(default=False, description="Fulfilled by Amazon")
    is_amazon_brand: bool = Field(default=False, description="Amazon-owned brand")

    # Latest analytics
    latest_reviews: ReviewSummaryDTO | None = Field(None, description="Latest review data")
    latest_sales_estimate: SalesEstimateDTO | None = Field(None, description="Latest sales estimate")
    latest_seller_count: SellerCountDTO | None = Field(None, description="Latest seller count")

    # Timestamps
    created_at: datetime = Field(..., description="When product was added")
    updated_at: datetime = Field(..., description="Last update timestamp")

    model_config = ConfigDict(from_attributes=True)


class ProductPricingDTO(BaseModel):
    """Historical pricing data for a product."""

    product_id: UUID = Field(..., description="Database product ID")
    asin: str = Field(..., description="Amazon ASIN")
    currency: str = Field(default="USD", description="Currency")
    amazon_prices: list[PricePointDTO] = Field(
        default_factory=list, description="Amazon price history",
    )
    buy_box_prices: list[PricePointDTO] = Field(
        default_factory=list, description="Buy Box price history",
    )
    current_price: Decimal | None = Field(None, description="Most recent Amazon price")
    current_buy_box: Decimal | None = Field(None, description="Most recent Buy Box price")
    price_range_min: Decimal | None = Field(None, description="Minimum historical price")
    price_range_max: Decimal | None = Field(None, description="Maximum historical price")


class BSRHistoryDTO(BaseModel):
    """Best Sellers Rank history."""

    product_id: UUID = Field(..., description="Database product ID")
    asin: str = Field(..., description="Amazon ASIN")
    current_rank: int | None = Field(None, description="Current BSR")
    history: list[PricePointDTO] = Field(
        default_factory=list, description="BSR history (lower = better)",
    )


class BuyBoxDTO(BaseModel):
    """Buy Box history and current winner."""

    product_id: UUID = Field(..., description="Database product ID")
    asin: str = Field(..., description="Amazon ASIN")
    current_buy_box_price: Decimal | None = Field(None, description="Current Buy Box price")
    current_buy_box_seller: str | None = Field(None, description="Current Buy Box seller ID")
    is_amazon_fulfilled: bool = Field(default=False, description="Is Buy Box FBA?")
    history: list[PricePointDTO] = Field(
        default_factory=list, description="Buy Box price history",
    )


class SellerCountHistoryDTO(BaseModel):
    """Seller count history."""

    product_id: UUID = Field(..., description="Database product ID")
    asin: str = Field(..., description="Amazon ASIN")
    current_new_count: int = Field(default=0, description="Current new sellers")
    current_fba_count: int = Field(default=0, description="Current FBA sellers")
    history: list[SellerCountDTO] = Field(
        default_factory=list, description="Seller count history",
    )


# ═══════════════════════════════════════════════════════════════
# Paginated Responses
# ═══════════════════════════════════════════════════════════════


class PaginatedResponse(BaseModel):
    """Base paginated response with metadata."""

    total: int = Field(..., description="Total number of items")
    page: int = Field(..., description="Current page number")
    page_size: int = Field(..., description="Items per page")
    total_pages: int = Field(..., description="Total number of pages")


class ProductSearchResponse(PaginatedResponse):
    """Paginated product search results."""

    items: list[ProductSummaryDTO] = Field(default_factory=list, description="Product list")
    query: str = Field(..., description="Original search query")


class RefreshResponse(BaseModel):
    """Response for a product refresh operation."""

    asin: str = Field(..., description="Amazon ASIN")
    status: str = Field(..., description="refresh_started, refresh_completed, refresh_failed")
    message: str | None = Field(None, description="Status message")
    product_id: UUID | None = Field(None, description="Database product ID (if completed)")


class BatchRefreshResponse(BaseModel):
    """Response for batch refresh operation."""

    total: int = Field(..., description="Total ASINs requested")
    succeeded: int = Field(..., description="Successfully refreshed")
    failed: int = Field(..., description="Failed to refresh")
    results: list[RefreshResponse] = Field(default_factory=list, description="Per-ASIN results")
