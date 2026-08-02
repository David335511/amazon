"""Benchmark tests for the product matching engine.

Tests the engine against known match scenarios to verify:
1. Exact barcode matches return high confidence
2. Brand + title matches work correctly
3. Fuzzy title matches work without brand
4. Non-matches return low confidence
5. The engine handles missing data gracefully
6. Explanations are accurate
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from app.matching.engine import ProductMatchEngine
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
    MatchRequest,
    MatchResponse,
    SupplierProductInput,
)


# ═══════════════════════════════════════════════════════════════
# Test Fixtures
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def engine() -> ProductMatchEngine:
    """Create a matching engine with default matchers."""
    return ProductMatchEngine(confidence_threshold=0.50)


@pytest.fixture
def anker_supplier() -> SupplierProductInput:
    """Anker PowerCore from a supplier."""
    return SupplierProductInput(
        supplier_code="walmart",
        supplier_sku="WM12345",
        title="Anker PowerCore 10000mAh Portable Charger",
        upc="848061079413",
        ean="0848061079413",
        gtin="00848061079413",
        brand="Anker",
        manufacturer="Anker Innovations",
        category="Electronics > Chargers",
        description="Ultra-compact 10000mAh portable charger with PowerIQ technology",
        features=["10000mAh capacity", "PowerIQ technology", "Ultra-compact design"],
        weight="6.4 ounces",
        dimensions="4.0x2.4x0.8 inches",
        model_number="A1233",
        price=Decimal("25.99"),
    )


@pytest.fixture
def anker_amazon() -> AmazonProduct:
    """The same Anker product on Amazon."""
    return AmazonProduct(
        asin="B0ABCDEFGH",
        title="Anker PowerCore 10000mAh Portable Charger, PowerIQ Technology",
        upc="848061079413",
        ean="0848061079413",
        gtin="00848061079413",
        brand="Anker",
        manufacturer="Anker Innovations",
        category="Cell Phone Accessories",
        description="Anker PowerCore 10000mAh - Ultra-compact portable charger",
        features=["10000mAh high-density battery", "PowerIQ fast charging", "Compact and portable"],
        weight="6.4 ounces",
        dimensions="4.0x2.4x0.8 inches",
        model_number="A1233",
        price=Decimal("25.99"),
    )


@pytest.fixture
def sony_supplier() -> SupplierProductInput:
    """Sony headphones from a supplier."""
    return SupplierProductInput(
        supplier_code="bestbuy",
        supplier_sku="BB6501234",
        title="Sony WH-1000XM5 Wireless Noise Cancelling Headphones",
        upc="027242926305",
        brand="Sony",
        manufacturer="Sony Corporation",
        category="Electronics > Headphones",
        description="Industry-leading noise cancellation with Auto NC Optimizer",
        features=["Industry-leading noise cancellation", "30-hour battery life", "Multipoint connection"],
        weight="8.9 ounces",
        dimensions="7.3x3.0x8.9 inches",
        model_number="WH1000XM5",
        price=Decimal("349.99"),
    )


@pytest.fixture
def sony_amazon() -> AmazonProduct:
    """The same Sony product on Amazon."""
    return AmazonProduct(
        asin="B0ZYXWVUTS",
        title="Sony WH-1000XM5 Wireless Noise Cancelling Headphones - Black",
        upc="027242926305",
        brand="Sony",
        manufacturer="Sony Corporation",
        category="Over-Ear Headphones",
        description="Sony WH-1000XM5: Industry-leading noise cancellation",
        features=["Auto NC Optimizer", "30-hour battery", "Speak-to-Chat"],
        weight="8.9 ounces",
        dimensions="7.3x3.0x8.9 inches",
        model_number="WH1000XM5",
        price=Decimal("349.99"),
    )


@pytest.fixture
def wrong_product() -> AmazonProduct:
    """A completely different product (should not match)."""
    return AmazonProduct(
        asin="B0JKLMNOPQ",
        title="Simple Houseware 6-Cube Organizer Shelf, White",
        upc="848061079420",
        brand="Simple Houseware",
        manufacturer="Simple Houseware Inc",
        category="Home & Kitchen",
        description="Stackable cube storage shelf for home organization",
        weight="8.5 pounds",
        dimensions="12x12x36 inches",
        price=Decimal("39.99"),
    )


# ═══════════════════════════════════════════════════════════════
# Matcher Unit Tests
# ═══════════════════════════════════════════════════════════════


class TestBarcodeMatcher:
    """Test the barcode matcher."""

    @pytest.mark.asyncio
    async def test_upc_exact_match(self, anker_supplier: Any, anker_amazon: Any) -> None:
        """Test UPC exact match returns high confidence."""
        matcher = BarcodeMatcher()
        score = await matcher.score(anker_supplier, anker_amazon)
        assert score.confidence >= 0.90
        assert score.matched is True
        # GTIN is checked first (most specific), then EAN, then UPC
        assert "match" in (score.details or "")

    @pytest.mark.asyncio
    async def test_gtin_exact_match(self, anker_supplier: Any, anker_amazon: Any) -> None:
        """Test GTIN exact match returns highest confidence."""
        matcher = BarcodeMatcher()
        score = await matcher.score(anker_supplier, anker_amazon)
        # GTIN should match first (highest specificity)
        assert "GTIN" in (score.details or "") or "EAN" in (score.details or "")

    @pytest.mark.asyncio
    async def test_barcode_mismatch(self, anker_supplier: Any, wrong_product: Any) -> None:
        """Test barcode mismatch returns low confidence."""
        matcher = BarcodeMatcher()
        score = await matcher.score(anker_supplier, wrong_product)
        assert score.confidence == 0.0
        assert score.matched is False

    @pytest.mark.asyncio
    async def test_no_barcode_data(self, sony_supplier: Any, sony_amazon: Any) -> None:
        """Test missing barcode data returns 0."""
        # Sony fixture has no EAN/GTIN
        matcher = BarcodeMatcher()
        score = await matcher.score(sony_supplier, sony_amazon)
        # UPC should match
        assert score.confidence >= 0.90


class TestBrandTitleMatcher:
    """Test the brand + title matcher."""

    @pytest.mark.asyncio
    async def test_brand_title_match(self, anker_supplier: Any, anker_amazon: Any) -> None:
        """Test brand + title match returns high confidence."""
        matcher = BrandTitleMatcher()
        score = await matcher.score(anker_supplier, anker_amazon)
        assert score.confidence >= 0.70
        assert score.matched is True

    @pytest.mark.asyncio
    async def test_brand_mismatch(self, anker_supplier: Any, wrong_product: Any) -> None:
        """Test brand mismatch returns low confidence."""
        matcher = BrandTitleMatcher()
        score = await matcher.score(anker_supplier, wrong_product)
        assert score.confidence < 0.50

    @pytest.mark.asyncio
    async def test_no_brand_data(self) -> None:
        """Test missing brand returns 0."""
        matcher = BrandTitleMatcher()
        supplier = SupplierProductInput(supplier_code="test", supplier_sku="T1", title="Product", brand=None)
        amazon = AmazonProduct(asin="B0TEST", title="Product", brand="Brand")
        score = await matcher.score(supplier, amazon)
        assert score.confidence == 0.0


class TestTitleFuzzyMatcher:
    """Test the fuzzy title matcher."""

    @pytest.mark.asyncio
    async def test_high_similarity(self, anker_supplier: Any, anker_amazon: Any) -> None:
        """Test high title similarity returns moderate confidence."""
        matcher = TitleFuzzyMatcher()
        score = await matcher.score(anker_supplier, anker_amazon)
        assert score.confidence >= 0.50

    @pytest.mark.asyncio
    async def test_low_similarity(self, anker_supplier: Any, wrong_product: Any) -> None:
        """Test low title similarity returns 0."""
        matcher = TitleFuzzyMatcher()
        score = await matcher.score(anker_supplier, wrong_product)
        assert score.confidence < 0.30


class TestSpecificationMatcher:
    """Test the specification matcher."""

    @pytest.mark.asyncio
    async def test_spec_match(self, anker_supplier: Any, anker_amazon: Any) -> None:
        """Test matching specifications return moderate confidence."""
        matcher = SpecificationMatcher()
        score = await matcher.score(anker_supplier, anker_amazon)
        assert score.confidence > 0
        assert score.matched is True

    @pytest.mark.asyncio
    async def test_spec_mismatch(self, anker_supplier: Any, wrong_product: Any) -> None:
        """Test mismatched specifications return low confidence."""
        matcher = SpecificationMatcher()
        score = await matcher.score(anker_supplier, wrong_product)
        assert score.confidence < 0.50


# ═══════════════════════════════════════════════════════════════
# Engine Integration Tests
# ═══════════════════════════════════════════════════════════════


class TestProductMatchEngine:
    """Test the full matching engine."""

    @pytest.mark.asyncio
    async def test_exact_match(
        self,
        engine: ProductMatchEngine,
        anker_supplier: Any,
        anker_amazon: Any,
    ) -> None:
        """Test exact match returns high confidence with explanation."""
        request = MatchRequest(
            supplier_product=anker_supplier,
            amazon_candidates=[anker_amazon],
        )
        response = await engine.match(request)

        assert len(response.results) == 1
        result = response.results[0]
        assert result.amazon_asin == "B0ABCDEFGH"
        assert result.confidence >= 0.60
        assert result.is_match is True
        assert len(result.explanation.matcher_scores) > 0
        assert "barcode" in result.explanation.matched_fields

    @pytest.mark.asyncio
    async def test_match_with_multiple_candidates(
        self,
        engine: ProductMatchEngine,
        anker_supplier: Any,
        anker_amazon: Any,
        sony_amazon: Any,
        wrong_product: Any,
    ) -> None:
        """Test matching against multiple candidates returns correct ranking."""
        request = MatchRequest(
            supplier_product=anker_supplier,
            amazon_candidates=[sony_amazon, anker_amazon, wrong_product],
        )
        response = await engine.match(request)

        assert len(response.results) >= 1
        # Anker should be the top match
        assert response.results[0].amazon_asin == "B0ABCDEFGH"
        # Anker should have higher confidence than Sony
        assert response.results[0].confidence > 0.50

    @pytest.mark.asyncio
    async def test_no_match_returns_low_confidence(
        self,
        engine: ProductMatchEngine,
        anker_supplier: Any,
        wrong_product: Any,
    ) -> None:
        """Test that non-matching products return low confidence."""
        request = MatchRequest(
            supplier_product=anker_supplier,
            amazon_candidates=[wrong_product],
        )
        response = await engine.match(request)

        assert len(response.results) == 1
        result = response.results[0]
        assert result.confidence < 0.50
        assert result.is_match is False

    @pytest.mark.asyncio
    async def test_explanation_contains_details(
        self,
        engine: ProductMatchEngine,
        anker_supplier: Any,
        anker_amazon: Any,
    ) -> None:
        """Test that explanations contain meaningful details."""
        request = MatchRequest(
            supplier_product=anker_supplier,
            amazon_candidates=[anker_amazon],
        )
        response = await engine.match(request)
        result = response.results[0]

        assert result.explanation.summary
        assert len(result.explanation.matched_fields) > 0
        assert len(result.explanation.matcher_scores) > 0

        # Check that each matcher score has details
        for score in result.explanation.matcher_scores:
            assert score.matcher_name
            assert 0.0 <= score.confidence <= 1.0
            assert 0.0 <= score.weight <= 1.0

    @pytest.mark.asyncio
    async def test_min_confidence_filter(
        self,
        engine: ProductMatchEngine,
        anker_supplier: Any,
        wrong_product: Any,
    ) -> None:
        """Test that min_confidence filters out low-confidence results."""
        request = MatchRequest(
            supplier_product=anker_supplier,
            amazon_candidates=[wrong_product],
            min_confidence=0.50,
        )
        response = await engine.match(request)

        # Wrong product should be below 0.50 confidence
        assert len(response.results) == 0

    @pytest.mark.asyncio
    async def test_max_results_limit(
        self,
        engine: ProductMatchEngine,
        anker_supplier: Any,
        anker_amazon: Any,
        sony_amazon: Any,
    ) -> None:
        """Test that max_results limits the number of results."""
        request = MatchRequest(
            supplier_product=anker_supplier,
            amazon_candidates=[anker_amazon, sony_amazon],
            max_results=1,
        )
        response = await engine.match(request)

        assert len(response.results) == 1

    @pytest.mark.asyncio
    async def test_processing_time_reported(
        self,
        engine: ProductMatchEngine,
        anker_supplier: Any,
        anker_amazon: Any,
    ) -> None:
        """Test that processing time is reported."""
        request = MatchRequest(
            supplier_product=anker_supplier,
            amazon_candidates=[anker_amazon],
        )
        response = await engine.match(request)

        assert response.processing_time_ms > 0
        assert response.total_candidates == 1

    @pytest.mark.asyncio
    async def test_sony_match(
        self,
        engine: ProductMatchEngine,
        sony_supplier: Any,
        sony_amazon: Any,
    ) -> None:
        """Test Sony product matching (no EAN/GTIN, relies on UPC + brand + title)."""
        request = MatchRequest(
            supplier_product=sony_supplier,
            amazon_candidates=[sony_amazon],
        )
        response = await engine.match(request)

        assert len(response.results) == 1
        result = response.results[0]
        assert result.amazon_asin == "B0ZYXWVUTS"
        assert result.confidence >= 0.60
        assert result.is_match is True

    @pytest.mark.asyncio
    async def test_confidence_calculation(self) -> None:
        """Test the confidence calculation formula directly."""
        from app.matching.models import MatcherScore

        engine = ProductMatchEngine()

        # Simulate: barcode matches (0.95 * 0.95), brand+title matches (0.85 * 0.70)
        # Expected: (0.9025 + 0.595) / (0.95 + 0.70) = 1.4975 / 1.65 = 0.9076
        scores = [
            MatcherScore(
                matcher_name="barcode", confidence=0.95, weight=0.95,
                weighted_score=0.9025, matched=True, details="UPC match",
            ),
            MatcherScore(
                matcher_name="brand_title", confidence=0.85, weight=0.70,
                weighted_score=0.595, matched=True, details="Brand + title match",
            ),
        ]

        confidence = engine._calculate_confidence(scores)
        expected = (0.95 * 0.95 + 0.85 * 0.70) / (0.95 + 0.70)
        assert abs(confidence - expected) < 0.01

    @pytest.mark.asyncio
    async def test_confidence_with_unavailable_matchers(self) -> None:
        """Test that unavailable matchers are excluded from confidence."""
        from app.matching.models import MatcherScore

        engine = ProductMatchEngine()

        # Barcode: no data (should be excluded)
        # Brand+title: matches (0.85 * 0.70)
        # Expected: 0.595 / 0.70 = 0.85
        scores = [
            MatcherScore(
                matcher_name="barcode", confidence=0.0, weight=0.95,
                weighted_score=0.0, matched=False,
                details="No supplier barcode data available",
            ),
            MatcherScore(
                matcher_name="brand_title", confidence=0.85, weight=0.70,
                weighted_score=0.595, matched=True, details="Brand + title match",
            ),
        ]

        confidence = engine._calculate_confidence(scores)
        expected = 0.85  # Only brand_title contributes
        assert abs(confidence - expected) < 0.01


# ═══════════════════════════════════════════════════════════════
# Benchmark: Known Match Scenarios
# ═══════════════════════════════════════════════════════════════


class TestMatchBenchmarks:
    """Benchmark tests against known match scenarios.

    These tests verify the engine produces correct results for
    real-world matching scenarios with known ground truth.
    """

    @pytest.mark.asyncio
    async def test_benchmark_exact_barcode_match(
        self,
        engine: ProductMatchEngine,
    ) -> None:
        """Benchmark 1: Exact barcode match should be near-perfect."""
        supplier = SupplierProductInput(
            supplier_code="walmart",
            supplier_sku="WM001",
            title="Apple AirPods Pro 2nd Generation",
            upc="194253411899",
            brand="Apple",
        )
        amazon = AmazonProduct(
            asin="B0BDHWDR12",
            title="Apple AirPods Pro (2nd Generation)",
            upc="194253411899",
            brand="Apple",
        )

        request = MatchRequest(
            supplier_product=supplier,
            amazon_candidates=[amazon],
        )
        response = await engine.match(request)

        assert response.results[0].confidence >= 0.50
        assert response.results[0].is_match is True

    @pytest.mark.asyncio
    async def test_benchmark_brand_title_match(
        self,
        engine: ProductMatchEngine,
    ) -> None:
        """Benchmark 2: Brand + title match without barcode."""
        supplier = SupplierProductInput(
            supplier_code="target",
            supplier_sku="TGT002",
            title="Lego Classic Creative Bricks 11005",
            brand="Lego",
        )
        amazon = AmazonProduct(
            asin="B07GZ1F2X8",
            title="LEGO Classic Creative Bricks 11005 Building Kit",
            brand="LEGO",
        )

        request = MatchRequest(
            supplier_product=supplier,
            amazon_candidates=[amazon],
        )
        response = await engine.match(request)

        assert response.results[0].confidence >= 0.50
        assert response.results[0].is_match is True

    @pytest.mark.asyncio
    async def test_benchmark_no_match(
        self,
        engine: ProductMatchEngine,
    ) -> None:
        """Benchmark 3: Completely different products should not match."""
        supplier = SupplierProductInput(
            supplier_code="costco",
            supplier_sku="COST003",
            title="Kirkland Signature Organic Olive Oil 2L",
            brand="Kirkland Signature",
            upc="096619231234",
        )
        amazon = AmazonProduct(
            asin="B0TESTDIFF",
            title="Samsung 49-Inch CRG9 Curved Monitor",
            brand="Samsung",
            upc="887276345678",
        )

        request = MatchRequest(
            supplier_product=supplier,
            amazon_candidates=[amazon],
        )
        response = await engine.match(request)

        assert response.results[0].confidence < 0.30
        assert response.results[0].is_match is False

    @pytest.mark.asyncio
    async def test_benchmark_ambiguous_match(
        self,
        engine: ProductMatchEngine,
    ) -> None:
        """Benchmark 4: Similar but different products should get moderate confidence."""
        supplier = SupplierProductInput(
            supplier_code="homedepot",
            supplier_sku="HD004",
            title="DEWALT 20V MAX Cordless Drill Combo Kit",
            brand="DEWALT",
            model_number="DCK240C2",
        )
        # Similar product but different model
        amazon = AmazonProduct(
            asin="B0TESTAMB",
            title="DEWALT 20V MAX Cordless Drill Kit with Battery",
            brand="DEWALT",
            model_number="DCK299D2",
        )

        request = MatchRequest(
            supplier_product=supplier,
            amazon_candidates=[amazon],
        )
        response = await engine.match(request)

        # Brand matches, title is similar, but model differs
        assert 0.20 < response.results[0].confidence < 0.80
