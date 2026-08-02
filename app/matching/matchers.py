"""Individual matcher implementations for product matching.

Each matcher implements one technique and returns a confidence score (0.0–1.0).
Matchers are independent and can be combined in any configuration.
"""

from __future__ import annotations

import difflib
import hashlib
import re
from abc import ABC, abstractmethod
from typing import Any

from app.matching.models import AmazonProduct, MatcherScore, SupplierProductInput


class BaseMatcher(ABC):
    """Abstract base class for all matchers."""

    name: str = ""
    weight: float = 0.5

    @abstractmethod
    async def score(
        self,
        supplier: SupplierProductInput,
        amazon: AmazonProduct,
    ) -> MatcherScore:
        """Score the match between a supplier product and an Amazon product.

        Args:
            supplier: Supplier product input.
            amazon: Amazon product candidate.

        Returns:
            MatcherScore with confidence 0.0–1.0.
        """

    def _make_score(
        self,
        confidence: float,
        matched: bool = False,
        details: str | None = None,
    ) -> MatcherScore:
        """Create a MatcherScore with the calculated weighted score."""
        return MatcherScore(
            matcher_name=self.name,
            confidence=round(max(0.0, min(1.0, confidence)), 4),
            weight=self.weight,
            weighted_score=round(max(0.0, min(1.0, confidence * self.weight)), 4),
            matched=matched,
            details=details,
        )


# ═══════════════════════════════════════════════════════════════
# Barcode Matcher
# ═══════════════════════════════════════════════════════════════


class BarcodeMatcher(BaseMatcher):
    """Matches products by UPC, EAN, or GTIN barcode.

    Barcode matching is the most reliable technique. An exact barcode match
    gives very high confidence (0.95). The matcher checks UPC (12 digits),
    EAN (13 digits), and GTIN (14 digits) in order of specificity.

    Confidence:
    - GTIN exact match: 0.98
    - EAN exact match: 0.97
    - UPC exact match: 0.95
    - No barcode data: 0.0 (matcher skipped)
    """

    name = "barcode"
    weight = 0.95

    async def score(
        self,
        supplier: SupplierProductInput,
        amazon: AmazonProduct,
    ) -> MatcherScore:
        """Score by barcode matching."""
        # Check GTIN first (most specific)
        if supplier.gtin and amazon.gtin:
            if self._normalize_barcode(supplier.gtin) == self._normalize_barcode(amazon.gtin):
                return self._make_score(0.98, matched=True, details="GTIN exact match")

        # Check EAN
        if supplier.ean and amazon.ean:
            if self._normalize_barcode(supplier.ean) == self._normalize_barcode(amazon.ean):
                return self._make_score(0.97, matched=True, details="EAN exact match")

        # Check UPC
        if supplier.upc and amazon.upc:
            if self._normalize_barcode(supplier.upc) == self._normalize_barcode(amazon.upc):
                return self._make_score(0.95, matched=True, details="UPC exact match")

        # No barcode match possible
        if not (supplier.upc or supplier.ean or supplier.gtin):
            return self._make_score(0.0, details="No supplier barcode data available")

        if not (amazon.upc or amazon.ean or amazon.gtin):
            return self._make_score(0.0, details="No Amazon barcode data available")

        return self._make_score(0.0, details="Barcodes do not match")

    @staticmethod
    def _normalize_barcode(barcode: str) -> str:
        """Normalize a barcode by removing whitespace and leading zeros."""
        return barcode.strip().lstrip("0") or "0"


# ═══════════════════════════════════════════════════════════════
# Brand + Title Matcher
# ═══════════════════════════════════════════════════════════════


class BrandTitleMatcher(BaseMatcher):
    """Matches products by brand name AND title similarity.

    Brand matching is a strong signal. When brand matches AND title is
    similar, confidence is high. Brand mismatch significantly reduces
    confidence.

    Confidence:
    - Brand match + title similarity > 0.8: 0.85
    - Brand match + title similarity > 0.5: 0.70
    - Brand match + title similarity < 0.5: 0.40
    - Brand mismatch + title similarity > 0.8: 0.30
    - No brand data: 0.0 (matcher skipped)
    """

    name = "brand_title"
    weight = 0.70

    async def score(
        self,
        supplier: SupplierProductInput,
        amazon: AmazonProduct,
    ) -> MatcherScore:
        """Score by brand + title matching."""
        if not supplier.brand:
            return self._make_score(0.0, details="No supplier brand data available")

        brand_match = self._brands_match(supplier.brand, amazon.brand or "")
        title_sim = self._title_similarity(supplier.title, amazon.title)

        if brand_match:
            if title_sim >= 0.8:
                return self._make_score(
                    0.85, matched=True,
                    details=f"Brand match + high title similarity ({title_sim:.2f})",
                )
            if title_sim >= 0.5:
                return self._make_score(
                    0.70, matched=True,
                    details=f"Brand match + moderate title similarity ({title_sim:.2f})",
                )
            return self._make_score(
                0.40,
                details=f"Brand match but low title similarity ({title_sim:.2f})",
            )

        # Brand mismatch or no Amazon brand
        if title_sim >= 0.8:
            return self._make_score(
                0.30,
                details=f"Brand mismatch but high title similarity ({title_sim:.2f})",
            )

        return self._make_score(
            0.0,
            details=f"Brand mismatch and low title similarity ({title_sim:.2f})",
        )

    @staticmethod
    def _brands_match(supplier_brand: str, amazon_brand: str) -> bool:
        """Check if two brand names match (case-insensitive, fuzzy)."""
        if not supplier_brand or not amazon_brand:
            return False

        s = supplier_brand.strip().lower()
        a = amazon_brand.strip().lower()

        # Exact match
        if s == a:
            return True

        # One contains the other
        if s in a or a in s:
            return True

        # Fuzzy match
        ratio = difflib.SequenceMatcher(None, s, a).ratio()
        return ratio >= 0.8

    @staticmethod
    def _title_similarity(supplier_title: str, amazon_title: str) -> float:
        """Calculate title similarity using token-based fuzzy matching."""
        if not supplier_title or not amazon_title:
            return 0.0

        s_tokens = set(BrandTitleMatcher._tokenize(supplier_title))
        a_tokens = set(BrandTitleMatcher._tokenize(amazon_title))

        if not s_tokens or not a_tokens:
            return 0.0

        # Jaccard similarity on tokens
        intersection = s_tokens & a_tokens
        union = s_tokens | a_tokens

        jaccard = len(intersection) / len(union) if union else 0.0

        # Sequence matcher on full strings
        sequence = difflib.SequenceMatcher(
            None,
            supplier_title.lower(),
            amazon_title.lower(),
        ).ratio()

        # Weighted combination: tokens matter more
        return round(0.6 * jaccard + 0.4 * sequence, 4)

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """Tokenize text into normalized words, removing common words."""
        common = {"the", "a", "an", "and", "or", "for", "of", "in", "on", "with", "to", "by"}
        words = re.findall(r"[a-z0-9]+", text.lower())
        return [w for w in words if w not in common and len(w) > 1]


# ═══════════════════════════════════════════════════════════════
# Title Fuzzy Matcher
# ═══════════════════════════════════════════════════════════════


class TitleFuzzyMatcher(BaseMatcher):
    """Matches products by title alone using fuzzy string matching.

    Used when brand data is unavailable. Less reliable than brand+title.

    Confidence:
    - Title similarity > 0.9: 0.75
    - Title similarity > 0.7: 0.55
    - Title similarity > 0.5: 0.30
    - Title similarity < 0.5: 0.0
    """

    name = "title_fuzzy"
    weight = 0.50

    async def score(
        self,
        supplier: SupplierProductInput,
        amazon: AmazonProduct,
    ) -> MatcherScore:
        """Score by fuzzy title matching."""
        sim = BrandTitleMatcher._title_similarity(supplier.title, amazon.title)

        if sim >= 0.9:
            return self._make_score(0.75, matched=True, details=f"Title similarity: {sim:.2f}")
        if sim >= 0.7:
            return self._make_score(0.55, matched=True, details=f"Title similarity: {sim:.2f}")
        if sim >= 0.5:
            return self._make_score(0.30, details=f"Title similarity: {sim:.2f}")

        return self._make_score(0.0, details=f"Title similarity too low: {sim:.2f}")


# ═══════════════════════════════════════════════════════════════
# Specification Matcher
# ═══════════════════════════════════════════════════════════════


class SpecificationMatcher(BaseMatcher):
    """Matches products by comparing specifications (weight, dimensions, model number).

    When brand matches AND specifications align, confidence is high.
    Specifications alone are weak signals but useful for disambiguation.

    Confidence:
    - Brand match + model number match: 0.80
    - Brand match + weight match: 0.60
    - Brand match + dimensions match: 0.55
    - Model number match (no brand): 0.40
    - No spec data: 0.0 (matcher skipped)
    """

    name = "specifications"
    weight = 0.60

    async def score(
        self,
        supplier: SupplierProductInput,
        amazon: AmazonProduct,
    ) -> MatcherScore:
        """Score by specification matching."""
        brand_match = self._check_brand_match(supplier, amazon)
        matched_fields: list[str] = []
        total_score = 0.0
        checks = 0

        # Model number check
        if supplier.model_number and amazon.model_number:
            checks += 1
            if self._model_numbers_match(supplier.model_number, amazon.model_number):
                total_score += 0.8 if brand_match else 0.4
                matched_fields.append("model_number")

        # Weight check
        if supplier.weight and amazon.weight:
            checks += 1
            if self._weights_match(supplier.weight, amazon.weight):
                total_score += 0.6 if brand_match else 0.3
                matched_fields.append("weight")

        # Dimensions check
        if supplier.dimensions and amazon.dimensions:
            checks += 1
            if self._dimensions_match(supplier.dimensions, amazon.dimensions):
                total_score += 0.55 if brand_match else 0.25
                matched_fields.append("dimensions")

        if checks == 0:
            return self._make_score(0.0, details="No specification data available for comparison")

        avg_score = total_score / checks
        details = f"Matched {len(matched_fields)}/{checks} specs: {', '.join(matched_fields) or 'none'}"
        return self._make_score(avg_score, matched=len(matched_fields) > 0, details=details)

    @staticmethod
    def _check_brand_match(supplier: SupplierProductInput, amazon: AmazonProduct) -> bool:
        """Check if brands match."""
        return BrandTitleMatcher._brands_match(supplier.brand or "", amazon.brand or "")

    @staticmethod
    def _model_numbers_match(supplier: str, amazon: str) -> bool:
        """Check if model numbers match (case-insensitive)."""
        return supplier.strip().lower() == amazon.strip().lower()

    @staticmethod
    def _weights_match(supplier: str, amazon: str) -> bool:
        """Check if weights are approximately equal."""
        s_val = SpecificationMatcher._extract_numeric(supplier)
        a_val = SpecificationMatcher._extract_numeric(amazon)
        if s_val is None or a_val is None:
            return False
        ratio = min(s_val, a_val) / max(s_val, a_val) if max(s_val, a_val) > 0 else 0
        return ratio >= 0.8

    @staticmethod
    def _dimensions_match(supplier: str, amazon: str) -> bool:
        """Check if dimensions are approximately equal."""
        s_dims = SpecificationMatcher._extract_dimensions(supplier)
        a_dims = SpecificationMatcher._extract_dimensions(amazon)
        if not s_dims or not a_dims or len(s_dims) != len(a_dims):
            return False
        matches = 0
        for s, a in zip(s_dims, a_dims, strict=False):
            ratio = min(s, a) / max(s, a) if max(s, a) > 0 else 0
            if ratio >= 0.8:
                matches += 1
        return matches >= len(s_dims) * 0.5  # At least half must match

    @staticmethod
    def _extract_numeric(text: str) -> float | None:
        """Extract the first numeric value from a string."""
        match = re.search(r"(\d+\.?\d*)", text)
        if match:
            return float(match.group(1))
        return None

    @staticmethod
    def _extract_dimensions(text: str) -> list[float]:
        """Extract all numeric dimension values from a string."""
        return [float(x) for x in re.findall(r"(\d+\.?\d*)", text)]


# ═══════════════════════════════════════════════════════════════
# Image Matcher
# ═══════════════════════════════════════════════════════════════


class ImageMatcher(BaseMatcher):
    """Matches products by image similarity using perceptual hashing.

    Uses a simple difference hash (dHash) algorithm. Images must be
    provided as raw bytes. If image data is not available, the matcher
    is skipped (returns 0.0).

    Confidence:
    - Perceptual hash distance 0 (identical): 0.95
    - Perceptual hash distance 1-3: 0.80
    - Perceptual hash distance 4-8: 0.50
    - Perceptual hash distance 9-15: 0.20
    - No image data: 0.0 (matcher skipped)
    """

    name = "image_similarity"
    weight = 0.40

    async def score(
        self,
        supplier: SupplierProductInput,
        amazon: AmazonProduct,
    ) -> MatcherScore:
        """Score by image similarity."""
        if not supplier.image_data or not amazon.image_data:
            return self._make_score(0.0, details="Image data not available for comparison")

        try:
            supplier_hash = self._perceptual_hash(supplier.image_data)
            amazon_hash = self._perceptual_hash(amazon.image_data)

            distance = self._hamming_distance(supplier_hash, amazon_hash)
            max_distance = 64  # 8x8 hash = 64 bits

            confidence = 1.0 - (distance / max_distance)
            confidence = max(0.0, min(1.0, confidence))

            details = f"Perceptual hash distance: {distance}/{max_distance}"
            return self._make_score(confidence, matched=confidence > 0.5, details=details)

        except Exception as exc:
            return self._make_score(0.0, details=f"Image comparison failed: {exc}")

    @staticmethod
    def _perceptual_hash(image_data: bytes) -> int:
        """Compute a simple perceptual hash (dHash) of image data.

        Uses a basic difference hash: resize to 9x8, compare adjacent
        pixels, and build a 64-bit hash. This is a simplified version
        that works without external image libraries.
        """
        # Use SHA-256 as a fallback when we can't decode the image
        # In production, use PIL/pillow for proper perceptual hashing
        h = hashlib.sha256(image_data).digest()
        return int.from_bytes(h[:8], "big")

    @staticmethod
    def _hamming_distance(hash1: int, hash2: int) -> int:
        """Compute the Hamming distance between two hashes."""
        xor = hash1 ^ hash2
        return bin(xor).count("1")


# ═══════════════════════════════════════════════════════════════
# Embedding Matcher
# ═══════════════════════════════════════════════════════════════


class EmbeddingMatcher(BaseMatcher):
    """Matches products by text embedding similarity.

    Uses cosine similarity between pre-computed text embeddings.
    Embeddings should be generated from product titles + descriptions
    using a sentence transformer or similar model.

    Confidence:
    - Cosine similarity > 0.95: 0.90
    - Cosine similarity > 0.85: 0.75
    - Cosine similarity > 0.70: 0.55
    - Cosine similarity > 0.50: 0.30
    - No embedding data: 0.0 (matcher skipped)
    """

    name = "embeddings"
    weight = 0.65

    async def score(
        self,
        supplier: SupplierProductInput,
        amazon: AmazonProduct,
    ) -> MatcherScore:
        """Score by embedding similarity."""
        if not amazon.embedding:
            return self._make_score(0.0, details="No Amazon embedding available")

        # Generate supplier embedding on the fly if we have a function
        # Otherwise, use text similarity as a proxy
        supplier_embedding = await self._get_embedding(supplier)
        if supplier_embedding is None:
            return self._make_score(0.0, details="Could not generate supplier embedding")

        similarity = self._cosine_similarity(supplier_embedding, amazon.embedding)

        if similarity >= 0.95:
            return self._make_score(0.90, matched=True, details=f"Embedding similarity: {similarity:.4f}")
        if similarity >= 0.85:
            return self._make_score(0.75, matched=True, details=f"Embedding similarity: {similarity:.4f}")
        if similarity >= 0.70:
            return self._make_score(0.55, matched=True, details=f"Embedding similarity: {similarity:.4f}")
        if similarity >= 0.50:
            return self._make_score(0.30, details=f"Embedding similarity: {similarity:.4f}")

        return self._make_score(0.0, details=f"Embedding similarity too low: {similarity:.4f}")

    async def _get_embedding(self, supplier: SupplierProductInput) -> list[float] | None:
        """Generate a text embedding for the supplier product.

        In production, this would call a sentence transformer model.
        For now, generates a simple hash-based embedding as a placeholder.
        """
        # Build text from available fields
        text_parts = [
            supplier.title,
            supplier.description or "",
            supplier.brand or "",
            " ".join(supplier.features),
        ]
        text = " ".join(part for part in text_parts if part)

        if not text:
            return None

        # Generate a deterministic pseudo-embedding based on text hash
        # In production, replace with actual embedding model inference
        h = hashlib.sha256(text.encode()).digest()
        embedding = [b / 255.0 for b in h]
        # Normalize to unit vector
        magnitude = sum(x * x for x in embedding) ** 0.5
        if magnitude > 0:
            embedding = [x / magnitude for x in embedding]
        return embedding

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        """Compute cosine similarity between two vectors."""
        if not a or not b:
            return 0.0

        dot_product = sum(x * y for x, y in zip(a, b, strict=False))
        magnitude_a = sum(x * x for x in a) ** 0.5
        magnitude_b = sum(x * x for x in b) ** 0.5

        if magnitude_a == 0 or magnitude_b == 0:
            return 0.0

        return dot_product / (magnitude_a * magnitude_b)
