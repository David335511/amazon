"""Product matching engine — matches supplier products to Amazon ASINs.

Uses multiple techniques with weighted confidence scoring:
- UPC/EAN/GTIN exact match
- Brand + title similarity
- Brand + specification matching
- Fuzzy title matching
- Image similarity (perceptual hash)
- Text embedding similarity

Each technique produces a confidence score. The final confidence is a
weighted average. Every match includes an explanation of which fields
matched and which were rejected.
"""

from app.matching.engine import ProductMatchEngine, MatchResult
from app.matching.matchers import (
    BarcodeMatcher,
    BrandTitleMatcher,
    EmbeddingMatcher,
    ImageMatcher,
    SpecificationMatcher,
    TitleFuzzyMatcher,
)
from app.matching.models import (
    AmazonProduct,
    MatchExplanation,
    MatchRequest,
    MatchResponse,
    MatcherScore,
    SupplierProductInput,
)

__all__ = [
    "ProductMatchEngine",
    "MatchResult",
    "MatcherContribution",
    "BarcodeMatcher",
    "BrandTitleMatcher",
    "EmbeddingMatcher",
    "ImageMatcher",
    "SpecificationMatcher",
    "TitleFuzzyMatcher",
    "AmazonProduct",
    "MatchExplanation",
    "MatchRequest",
    "MatchResponse",
    "MatcherScore",
    "SupplierProductInput",
]
