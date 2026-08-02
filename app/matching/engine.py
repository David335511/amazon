"""Product matching engine — orchestrates matchers and calculates confidence.

Design decisions:
- The engine runs all registered matchers against each candidate.
- Confidence is a weighted average of all matcher scores.
- Matchers that can't run (missing data) are excluded from the average.
- Results are sorted by confidence (highest first).
- Every result includes a full explanation of how it was determined.
"""

from __future__ import annotations

import time
from typing import Any

from app.core.logging import get_logger
from app.matching.matchers import (
    BarcodeMatcher,
    BaseMatcher,
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
    MatchResult,
    MatcherScore,
    SupplierProductInput,
)

logger = get_logger(__name__)

# Default matchers with their weights
DEFAULT_MATCHERS: list[BaseMatcher] = [
    BarcodeMatcher(),       # weight: 0.95
    BrandTitleMatcher(),    # weight: 0.70
    SpecificationMatcher(), # weight: 0.60
    EmbeddingMatcher(),     # weight: 0.65
    TitleFuzzyMatcher(),    # weight: 0.50
    ImageMatcher(),         # weight: 0.40
]


class ProductMatchEngine:
    """Orchestrates product matching across multiple techniques.

    The engine:
    1. Runs all registered matchers against each Amazon candidate
    2. Calculates a weighted confidence score
    3. Generates explanations with matched/rejected fields
    4. Returns results sorted by confidence

    Usage:
        engine = ProductMatchEngine()
        response = await engine.match(request)
        best_match = response.results[0]
    """

    def __init__(
        self,
        matchers: list[BaseMatcher] | None = None,
        confidence_threshold: float = 0.50,
    ) -> None:
        """Initialize the matching engine.

        Args:
            matchers: List of matcher instances. Uses defaults if None.
            confidence_threshold: Minimum confidence to consider a match valid.
        """
        self._matchers = matchers or DEFAULT_MATCHERS
        self._threshold = confidence_threshold

    async def match(self, request: MatchRequest) -> MatchResponse:
        """Match a supplier product against Amazon candidates.

        Args:
            request: Match request with supplier product and candidates.

        Returns:
            Match response with results sorted by confidence.
        """
        start_time = time.monotonic()
        results: list[MatchResult] = []

        for amazon in request.amazon_candidates:
            result = await self._evaluate_candidate(request.supplier_product, amazon)
            if result.confidence >= request.min_confidence:
                results.append(result)

        # Sort by confidence descending
        results.sort(key=lambda r: r.confidence, reverse=True)

        # Limit results
        results = results[:request.max_results]

        processing_time = (time.monotonic() - start_time) * 1000

        return MatchResponse(
            results=results,
            total_candidates=len(request.amazon_candidates),
            processing_time_ms=round(processing_time, 2),
        )

    async def _evaluate_candidate(
        self,
        supplier: SupplierProductInput,
        amazon: AmazonProduct,
    ) -> MatchResult:
        """Evaluate a single Amazon candidate against the supplier product.

        Runs all matchers, calculates weighted confidence, and generates
        an explanation.

        Args:
            supplier: Supplier product input.
            amazon: Amazon product candidate.

        Returns:
            Match result with confidence and explanation.
        """
        scores: list[MatcherScore] = []
        matched_fields: list[str] = []
        rejected_fields: list[str] = []
        unavailable_fields: list[str] = []

        for matcher in self._matchers:
            try:
                score = await matcher.score(supplier, amazon)
                scores.append(score)

                if score.confidence > 0:
                    if score.matched:
                        matched_fields.append(matcher.name)
                    else:
                        rejected_fields.append(matcher.name)
                else:
                    if score.details and "not available" in (score.details or "").lower():
                        unavailable_fields.append(matcher.name)
                    else:
                        rejected_fields.append(matcher.name)

            except Exception as exc:
                logger.warning("Matcher %s failed: %s", matcher.name, exc)
                scores.append(
                    MatcherScore(
                        matcher_name=matcher.name,
                        confidence=0.0,
                        weight=matcher.weight,
                        weighted_score=0.0,
                        matched=False,
                        details=f"Error: {exc}",
                    ),
                )
                unavailable_fields.append(matcher.name)

        # Calculate weighted confidence
        confidence = self._calculate_confidence(scores)

        # Generate explanation
        explanation = self._generate_explanation(
            scores, matched_fields, rejected_fields, unavailable_fields,
        )

        return MatchResult(
            amazon_asin=amazon.asin,
            amazon_title=amazon.title,
            confidence=round(confidence, 4),
            explanation=explanation,
            is_match=confidence >= self._threshold,
        )

    def _calculate_confidence(self, scores: list[MatcherScore]) -> float:
        """Calculate weighted confidence from all matcher scores.

        The formula is:
            confidence = Σ(confidence_i * weight_i) / Σ(weight_i)

        Where i iterates over matchers that had available data.
        Matchers with no data (confidence = 0, no data available) are
        excluded from both numerator and denominator.

        Returns:
            Weighted confidence score (0.0–1.0).
        """
        total_weighted = 0.0
        total_weight = 0.0

        unavailable_indicators = [
            "not available", "no data", "no supplier", "no amazon",
            "could not", "unavailable", "missing",
            "no specification", "no embedding", "no image",
            "image data not",
        ]

        for score in scores:
            # Include matchers that ran (even if they scored 0)
            # Exclude matchers that couldn't run due to missing data
            details_lower = (score.details or "").lower()
            is_unavailable = any(indicator in details_lower for indicator in unavailable_indicators)

            if score.confidence == 0.0 and is_unavailable:
                continue

            total_weighted += score.confidence * score.weight
            total_weight += score.weight

        if total_weight == 0:
            return 0.0

        return total_weighted / total_weight

    def _generate_explanation(
        self,
        scores: list[MatcherScore],
        matched_fields: list[str],
        rejected_fields: list[str],
        unavailable_fields: list[str],
    ) -> MatchExplanation:
        """Generate a human-readable explanation of the match.

        Args:
            scores: All matcher scores.
            matched_fields: Fields that contributed positively.
            rejected_fields: Fields that were checked but didn't match.
            unavailable_fields: Fields that had no data.

        Returns:
            Match explanation.
        """
        # Build summary
        if matched_fields:
            top = max(scores, key=lambda s: s.confidence)
            summary = (
                f"Match found via {top.matcher_name} "
                f"(confidence: {top.confidence:.2f}). "
                f"{len(matched_fields)}/{len(scores)} matchers contributed."
            )
        else:
            summary = (
                f"No strong match. "
                f"{len(rejected_fields)} matchers rejected, "
                f"{len(unavailable_fields)} had no data."
            )

        return MatchExplanation(
            summary=summary,
            matched_fields=sorted(matched_fields),
            rejected_fields=sorted(rejected_fields),
            unavailable_fields=sorted(unavailable_fields),
            matcher_scores=sorted(scores, key=lambda s: s.confidence, reverse=True),
        )

    def add_matcher(self, matcher: BaseMatcher) -> None:
        """Add a custom matcher to the engine.

        Args:
            matcher: Matcher instance to add.
        """
        self._matchers.append(matcher)

    def set_threshold(self, threshold: float) -> None:
        """Set the confidence threshold for a valid match.

        Args:
            threshold: Minimum confidence (0.0–1.0).
        """
        self._threshold = max(0.0, min(1.0, threshold))
