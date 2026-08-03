"""Standardized data models for the marketplace abstraction layer.

Design decisions:
- ALL marketplace providers share these models. No marketplace-specific type
  may leak past the provider boundary (the "anti-corruption layer").
- Every model carries a ``marketplace`` code so callers always know the source.
- Monetary values use Decimal for precision.
- Optional fields use None for "not available".
- Every model has a ``supported`` flag. When a marketplace cannot provide a
  capability, the provider returns the model with ``supported=False`` so the
  platform can degrade gracefully instead of crashing or leaking "not
  implemented" exceptions.
- A ``raw`` field holds marketplace-specific metadata for advanced/debug use.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field


class MarketplaceResult(BaseModel):
    """Base for all marketplace result models."""

    marketplace: str = Field(..., description="Marketplace code (e.g. 'amazon')")
    supported: bool = Field(default=True, description="Does this marketplace support the capability?")
    raw: dict[str, Any] = Field(default_factory=dict, description="Raw marketplace data")


class MarketplaceSearchResult(MarketplaceResult):
    """A single product search result from a marketplace."""

    external_id: str = Field(..., description="Marketplace product identifier (ASIN/SKU/item_id)")
    title: str = Field(..., description="Product title")
    brand: str | None = Field(None, description="Brand name")
    category: str | None = Field(None, description="Product category")
    image_url: str | None = Field(None, description="Product image URL")
    product_url: str | None = Field(None, description="Product page URL")
    price: Decimal | None = Field(None, description="Current price")
    currency: str = Field(default="USD", description="Currency code")
    condition: str | None = Field(None, description="Condition (new/used/refurbished)")
    in_stock: bool = Field(default=True, description="Is it in stock?")
    rating: Decimal | None = Field(None, description="Average rating (1.0-5.0)")
    review_count: int = Field(default=0, description="Number of reviews")
    seller: str | None = Field(None, description="Selling entity name")


class MarketplaceProduct(MarketplaceResult):
    """Detailed product information from a marketplace."""

    external_id: str = Field(..., description="Marketplace product identifier")
    title: str = Field(..., description="Product title")
    description: str | None = Field(None, description="Full description")
    brand: str | None = Field(None, description="Brand name")
    manufacturer: str | None = Field(None, description="Manufacturer name")
    category: str | None = Field(None, description="Product category")
    category_tree: list[str] = Field(default_factory=list, description="Category breadcrumb")
    images: list[str] = Field(default_factory=list, description="Product image URLs")
    main_image: str | None = Field(None, description="Primary image URL")
    features: list[str] = Field(default_factory=list, description="Bullet points")
    upc: str | None = Field(None, description="UPC/EAN/GTIN identifier")
    ean: str | None = Field(None, description="EAN identifier")
    model_number: str | None = Field(None, description="Manufacturer model number")
    weight: Decimal | None = Field(None, description="Product weight")
    weight_unit: str | None = Field(None, description="Weight unit")
    dimensions: str | None = Field(None, description="Product dimensions")
    price: Decimal | None = Field(None, description="Current price")
    currency: str = Field(default="USD", description="Currency code")
    condition: str | None = Field(None, description="Condition")
    product_url: str | None = Field(None, description="Product page URL")
    rating: Decimal | None = Field(None, description="Average rating")
    review_count: int = Field(default=0, description="Number of reviews")
    availability: str | None = Field(None, description="Stock availability text")


class MarketplacePricing(MarketplaceResult):
    """Pricing information for a product on a marketplace."""

    external_id: str = Field("", description="Marketplace product identifier")
    list_price: Decimal | None = Field(None, description="Manufacturer/list price")
    current_price: Decimal | None = Field(None, description="Current selling price")
    min_price: Decimal | None = Field(None, description="Lowest offer price")
    max_price: Decimal | None = Field(None, description="Highest offer price")
    currency: str = Field(default="USD", description="Currency code")
    quantity_tiers: list[dict[str, Decimal]] = Field(
        default_factory=list,
        description="Volume pricing tiers: [{'min_qty': 10, 'price': 8.50}, ...]",
    )
    effective_date: datetime | None = Field(None, description="Price effective date")


class MarketplaceFees(MarketplaceResult):
    """Fee structure for selling a product on a marketplace."""

    external_id: str = Field("", description="Marketplace product identifier")
    referral_fee: Decimal | None = Field(None, description="Referral/selling commission")
    closing_fee: Decimal | None = Field(None, description="Per-unit closing fee")
    payment_processing_fee: Decimal | None = Field(None, description="Payment processing fee")
    fulfillment_fee: Decimal | None = Field(None, description="Fulfillment/shipping fee")
    storage_fee: Decimal | None = Field(None, description="Storage fee (if applicable)")
    subscription_fee: Decimal | None = Field(None, description="Fixed subscription fee")
    other_fees: Decimal | None = Field(None, description="Any other applicable fees")
    currency: str = Field(default="USD", description="Currency code")
    fee_total: Decimal | None = Field(None, description="Sum of all fees")


class MarketplaceInventory(MarketplaceResult):
    """Inventory/stock information from a marketplace."""

    external_id: str = Field("", description="Marketplace product identifier")
    quantity_available: int = Field(default=0, ge=0, description="Available quantity")
    quantity_inbound: int = Field(default=0, ge=0, description="Inbound quantity")
    quantity_reserved: int = Field(default=0, ge=0, description="Reserved/unavailable quantity")
    status: str = Field(
        default="unknown",
        description="Stock status: in_stock, low_stock, out_of_stock, discontinued",
    )
    warehouse_location: str | None = Field(None, description="Fulfillment center/location")
    is_backorderable: bool = Field(default=False, description="Can be backordered?")


class MarketplaceOrderItem(MarketplaceResult):
    """A single line item within an order."""

    line_item_id: str = Field("", description="Line item identifier")
    external_id: str = Field("", description="Marketplace product identifier")
    sku: str | None = Field(None, description="Seller SKU")
    quantity: int = Field(default=1, ge=1, description="Quantity ordered")
    unit_price: Decimal | None = Field(None, description="Unit price")
    currency: str = Field(default="USD", description="Currency code")
    status: str | None = Field(None, description="Line item status")


class MarketplaceOrder(MarketplaceResult):
    """An order from a marketplace."""

    order_id: str = Field(..., description="Marketplace order identifier")
    status: str | None = Field(None, description="Order status")
    created_at: datetime | None = Field(None, description="Order creation time")
    buyer: str | None = Field(None, description="Buyer display name")
    currency: str = Field(default="USD", description="Currency code")
    total_amount: Decimal | None = Field(None, description="Order total")
    items: list[MarketplaceOrderItem] = Field(default_factory=list, description="Order line items")
    fulfillment_channel: str | None = Field(None, description="FBM/FBA/other")


class MarketplaceListing(MarketplaceResult):
    """A seller's own listing on a marketplace."""

    listing_id: str = Field("", description="Listing identifier")
    external_id: str = Field("", description="Marketplace product identifier")
    title: str = Field("", description="Listing title")
    sku: str | None = Field(None, description="Seller SKU")
    price: Decimal | None = Field(None, description="Listed price")
    currency: str = Field(default="USD", description="Currency code")
    quantity: int = Field(default=0, ge=0, description="Listed quantity")
    status: str | None = Field(None, description="Listing status (active/inactive)")
    product_url: str | None = Field(None, description="Listing URL")
    created_at: datetime | None = Field(None, description="Creation time")


class CompetitorOffer(MarketplaceResult):
    """A single competitor offer for a product."""

    seller: str | None = Field(None, description="Seller name/identifier")
    price: Decimal | None = Field(None, description="Offer price")
    currency: str = Field(default="USD", description="Currency code")
    condition: str | None = Field(None, description="Condition")
    is_fulfilled_by_platform: bool = Field(default=False, description="Platform-fulfilled (FBA etc.)")
    is_prime: bool = Field(default=False, description="Fast-delivery eligible")
    seller_rating: Decimal | None = Field(None, description="Seller rating")
    delivery_days: int | None = Field(None, description="Estimated delivery days")


class MarketplaceCompetition(MarketplaceResult):
    """Competitive landscape for a product on a marketplace."""

    external_id: str = Field("", description="Marketplace product identifier")
    offers: list[CompetitorOffer] = Field(default_factory=list, description="Competitor offers")
    competitive_price: Decimal | None = Field(None, description="Lowest competitive price")
    currency: str = Field(default="USD", description="Currency code")
    offer_count: int = Field(default=0, description="Number of competing offers")
    rank: int | None = Field(None, description="Product rank within category (lower = better)")


class MarketplaceSalesEstimate(MarketplaceResult):
    """Estimated sales for a product on a marketplace."""

    external_id: str = Field("", description="Marketplace product identifier")
    estimated_monthly_sales: int = Field(default=0, description="Estimated sales per month")
    estimated_daily_sales: Decimal = Field(
        default=Decimal("0"), description="Estimated sales per day",
    )
    sales_rank: int | None = Field(None, description="Current category sales rank")
    confidence: Decimal | None = Field(None, description="Confidence score (0.0-1.0)")
    as_of: datetime | None = Field(None, description="Estimate timestamp")


class MarketplaceBuyBox(MarketplaceResult):
    """Buy Box / featured-offer information for a product."""

    external_id: str = Field("", description="Marketplace product identifier")
    is_winner: bool = Field(default=False, description="Is the buyer's offer winning the Buy Box?")
    buy_box_price: Decimal | None = Field(None, description="Buy Box price")
    currency: str = Field(default="USD", description="Currency code")
    winner_seller: str | None = Field(None, description="Seller currently holding the Buy Box")
    is_fulfilled_by_platform: bool = Field(default=False, description="Buy Box held by platform fulfillment")
    offer_count: int = Field(default=0, description="Number of offers competing for the Buy Box")


class MarketplaceShippingOption(MarketplaceResult):
    """A single shipping method available for a product/order."""

    method: str = Field("", description="Shipping method name")
    carrier: str | None = Field(None, description="Carrier name")
    cost: Decimal | None = Field(None, description="Shipping cost")
    currency: str = Field(default="USD", description="Currency code")
    estimated_days_min: int | None = Field(None, description="Min delivery days")
    estimated_days_max: int | None = Field(None, description="Max delivery days")
    destination_countries: list[str] = Field(default_factory=list, description="Countries served")


class MarketplaceShipping(MarketplaceResult):
    """Shipping options and details for a product/order."""

    external_id: str = Field("", description="Marketplace product identifier")
    options: list[MarketplaceShippingOption] = Field(
        default_factory=list, description="Available shipping methods",
    )
    free_shipping_threshold: Decimal | None = Field(None, description="Order amount for free shipping")
    ships_from: str | None = Field(None, description="Origin location")
    ships_to: list[str] = Field(default_factory=list, description="Destination countries")
    currency: str = Field(default="USD", description="Currency code")


class MarketplaceReturn(MarketplaceResult):
    """A return/refund record from a marketplace."""

    return_id: str = Field("", description="Return identifier")
    order_id: str = Field("", description="Related order identifier")
    external_id: str = Field("", description="Marketplace product identifier")
    status: str | None = Field(None, description="Return status")
    reason: str | None = Field(None, description="Return reason")
    requested_at: datetime | None = Field(None, description="Return request time")
    refund_amount: Decimal | None = Field(None, description="Refund amount")
    currency: str = Field(default="USD", description="Currency code")
