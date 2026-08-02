"""Data models for the product matching engine.

Design decisions:
- Input and output models are separate from supplier/Amazon models.
- Every match includes an explanation with per-matcher scores.
- Matched and rejected fields are tracked for transparency.
- Confidence is always 0.0–1.0.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field


# ═══════════════════════════════════════════════════════════════
# Input Models
# ═══════════════════════════════════════════════════════════════


class SupplierProductInput(BaseModel):
    """A product from a supplier that needs to be matched to an Amazon ASIN."""

    supplier_code: str = Field(..., description="Supplier code (e.g., 'walmart')")
    supplier_sku: str = Field(..., description="Supplier's SKU")
    title: str = Field(..., description="Product title")
    upc: str | None = Field(None, description="UPC barcode (12 digits)")
    ean: str | None = Field(None, description="EAN barcode (13 digits)")
    gtin: str | None = Field(None, description="GTIN barcode (14 digits)")
    brand: str | None = Field(None, description="Brand name")
    manufacturer: str | None = Field(None, description="Manufacturer name")
    category: str | None = Field(None, description="Product category")
    description: str | None = Field(None, description="Product description")
    features: list[str] = Field(default_factory=list, description="Product features/bullet points")
    image_url: str | None = Field(None, description="Product image URL")
    image_data: bytes | None = Field(None, description="Raw image bytes for perceptual hashing")
    weight: str | None = Field(None, description="Product weight (e.g., '1.5 pounds')")
    dimensions: str | None = Field(None, description="Product dimensions (e.g., '10x8x5 inches')")
    model_number: str | None = Field(None, description="Manufacturer model number")
    price: Decimal | None = Field(None, description="Supplier price")
    raw: dict[str, Any] = Field(default_factory=dict, description="Raw supplier data")


class AmazonProduct(BaseModel):
    """An Amazon product to match against."""

    asin: str = Field(..., description="Amazon ASIN")
    title: str = Field(..., description="Product title")
    upc: str | None = Field(None, description="UPC barcode")
    ean: str | None = Field(None, description="EAN barcode")
    gtin: str | None = Field(None, description="GTIN barcode")
    brand: str | None = Field(None, description="Brand name")
    manufacturer: str | None = Field(None, description="Manufacturer name")
    category: str | None = Field(None, description="Product category")
    description: str | None = Field(None, description="Product description")
    features: list[str] = Field(default_factory=list, description="Product features")
    image_url: str | None = Field(None, description="Product image URL")
    image_data: bytes | None = Field(None, description="Raw image bytes for perceptual hashing")
    weight: str | None = Field(None, description="Product weight")
    dimensions: str | None = Field(None, description="Product dimensions")
    model_number: str | None = Field(None, description="Model number")
    price: Decimal | None = Field(None, description="Amazon price")
    embedding: list[float] | None = Field(None, description="Pre-computed text embedding")


class MatchRequest(BaseModel):
    """A request to match a supplier product against Amazon products."""

    supplier_product: SupplierProductInput = Field(..., description="Supplier product to match")
    amazon_candidates: list[AmazonProduct] = Field(
        ..., description="Amazon products to match against",
    )
    min_confidence: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="Minimum confidence threshold (0.0 = return all)",
    )
    max_results: int = Field(
        default=5, ge=1, le=20,
        description="Maximum number of match results to return",
    )


# ═══════════════════════════════════════════════════════════════
# Output Models
# ═══════════════════════════════════════════════════════════════


class MatcherScore(BaseModel):
    """Score from a single matcher technique."""

    matcher_name: str = Field(..., description="Name of the matcher (e.g., 'barcode', 'brand_title')")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score 0.0-1.0")
    weight: float = Field(..., ge=0.0, le=1.0, description="Weight assigned to this matcher")
    weighted_score: float = Field(..., ge=0.0, le=1.0, description="confidence * weight")
    matched: bool = Field(default=False, description="Did this matcher find a match?")
    details: str | None = Field(None, description="Human-readable explanation of this score")


class MatchExplanation(BaseModel):
    """Explanation of how a match was determined."""

    summary: str = Field(..., description="One-line summary of the match")
    matched_fields: list[str] = Field(
        default_factory=list,
        description="Fields that contributed positively to the match",
    )
    rejected_fields: list[str] = Field(
        default_factory=list,
        description="Fields that were checked but did not match",
    )
    unavailable_fields: list[str] = Field(
        default_factory=list,
        description="Fields that were not available for comparison",
    )
    matcher_scores: list[MatcherScore] = Field(
        default_factory=list,
        description="Individual scores from each matcher",
    )


class MatchResult(BaseModel):
    """A single match result between a supplier product and an Amazon product."""

    amazon_asin: str = Field(..., description="Matched Amazon ASIN")
    amazon_title: str = Field(..., description="Matched Amazon product title")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Overall confidence score")
    explanation: MatchExplanation = Field(..., description="How this match was determined")
    is_match: bool = Field(default=False, description="Is this considered a valid match?")


class MatcherContribution(BaseModel):
    """Contribution of a single matcher to the overall result."""

    matcher_name: str = Field(..., description="Matcher name")
    score: float = Field(..., ge=0.0, le=1.0, description="Raw score from this matcher")
    weight: float = Field(..., ge=0.0, le=1.0, description="Matcher weight")
    details: str | None = Field(None, description="Details about this matcher's result")


class MatchResponse(BaseModel):
    """Complete response from the matching engine."""

    results: list[MatchResult] = Field(
        default_factory=list,
        description="Match results sorted by confidence (highest first)",
    )
    total_candidates: int = Field(..., description="Number of Amazon candidates evaluated")
    processing_time_ms: float = Field(..., description="Time taken to process in milliseconds")
