"""Benchmark tests for the computer-vision subsystem.

These tests exercise the full provider-independent pipeline against synthetic
images (encoded in-test via pure zlib), plus the multimodal matcher and the
HTTP API. No third-party image or vision library is required.

Synthetic fixtures:
- ``solid_png`` / ``solid_rgba_png`` / ``palette_png`` / ``bmp`` for decoding.
- ``stripes_png`` for barcode detection (alternating high-contrast columns).
- ``logo_png`` (white bg + saturated red block) for logo detection.
"""

from __future__ import annotations

import struct
import zlib

import pytest
from httpx import AsyncClient

from app.vision import (
    ImageAnalysis,
    LocalVisionProvider,
    SimilarityTarget,
    VisionConfig,
    VisionManager,
    build_vision_provider,
)
from app.vision.errors import VisionDecodeError, VisionValidationError
from app.vision.models import Image, VisionCapability
from app.vision.text import (
    attribute_overlap,
    extract_model_numbers,
    normalize_brand,
    text_similarity,
)

# ──────────────────────────────────────────────────────────────
# Synthetic image fixtures (pure stdlib)
# ──────────────────────────────────────────────────────────────


def _chunk(chunk_type: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + chunk_type
        + data
        + struct.pack(">I", zlib.crc32(chunk_type + data) & 0xFFFFFFFF)
    )


def _png_bytes(width: int, height: int, pixels: list[list[tuple[int, ...]]], color_type: int) -> bytes:
    sig = b"\x89PNG\r\n\x1a\n"
    channels = 4 if color_type == 6 else 3
    ihdr = struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)
    raw = bytearray()
    for row in pixels:
        raw.append(0)  # filter: None
        for px in row:
            raw += bytes(px[:channels])
    return sig + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + _chunk(b"IEND", b"")


def solid_png(width: int, height: int, color: tuple[int, int, int]) -> bytes:
    return _png_bytes(width, height, [[color] * width for _ in range(height)], color_type=2)


def solid_rgba_png(width: int, height: int, color: tuple[int, int, int, int]) -> bytes:
    return _png_bytes(width, height, [[color] * width for _ in range(height)], color_type=6)


def palette_png(width: int, height: int, indices: list[list[int]], palette: list[tuple[int, int, int]]) -> bytes:
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 3, 0, 0, 0)
    plte = b"".join(bytes(c) for c in palette)
    raw = bytearray()
    for row in indices:
        raw.append(0)
        raw += bytes(row)
    return (
        sig
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"PLTE", plte)
        + _chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + _chunk(b"IEND", b"")
    )


def bmp_bytes(width: int, height: int, color: tuple[int, int, int]) -> bytes:
    row_size = (width * 3 + 3) // 4 * 4
    header = bytearray(54)
    header[0:2] = b"BM"
    struct.pack_into("<I", header, 2, 54 + height * row_size)
    struct.pack_into("<I", header, 10, 54)
    struct.pack_into("<I", header, 14, 40)
    struct.pack_into("<i", header, 18, width)
    struct.pack_into("<i", header, 22, height)
    struct.pack_into("<H", header, 26, 1)
    struct.pack_into("<H", header, 28, 24)
    struct.pack_into("<I", header, 30, 0)
    rows = bytearray()
    for _ in range(height):
        for _ in range(width):
            rows += bytes((color[2], color[1], color[0]))
        rows += bytes(row_size - width * 3)
    return bytes(header) + bytes(rows)


def stripes_png(width: int = 96, height: int = 30) -> bytes:
    pixels = []
    for _ in range(height):
        row = []
        for x in range(width):
            row.append((0, 0, 0) if (x // 2) % 2 == 0 else (255, 255, 255))
        pixels.append(row)
    return _png_bytes(width, height, pixels, color_type=2)


def logo_png(width: int = 48, height: int = 48) -> bytes:
    pixels = []
    for y in range(height):
        row = []
        for x in range(width):
            if x < 16 and y < 16:
                row.append((220, 20, 20))  # saturated red logo block
            else:
                row.append((250, 250, 250))
        pixels.append(row)
    return _png_bytes(width, height, pixels, color_type=2)


async def _manager() -> VisionManager:
    return VisionManager(config=VisionConfig())


# ──────────────────────────────────────────────────────────────
# Decoding
# ──────────────────────────────────────────────────────────────


class TestDecode:
    async def test_decode_rgb_png(self) -> None:
        data = solid_png(4, 3, (10, 20, 30))
        image = await (await _manager()).decode(data)
        assert image.width == 4
        assert image.height == 3
        assert image.pixels[0][0] == (10, 20, 30)
        assert image.pixels[2][3] == (10, 20, 30)

    async def test_decode_rgba_png_blends_alpha(self) -> None:
        # Red at 50% alpha over white -> pink (255, ~128, ~128).
        data = solid_rgba_png(2, 2, (255, 0, 0, 128))
        image = await (await _manager()).decode(data)
        r, g, b = image.pixels[0][0]
        assert r == 255
        assert 120 <= g <= 135
        assert 120 <= b <= 135

    async def test_decode_palette_png(self) -> None:
        palette = [(255, 0, 0), (0, 255, 0)]
        indices = [[0, 1], [1, 0]]
        data = palette_png(2, 2, indices, palette)
        image = await (await _manager()).decode(data)
        assert image.pixels[0][0] == (255, 0, 0)
        assert image.pixels[0][1] == (0, 255, 0)

    async def test_decode_bmp(self) -> None:
        data = bmp_bytes(3, 2, (5, 6, 7))
        image = await (await _manager()).decode(data)
        assert image.width == 3
        assert image.height == 2
        assert image.pixels[0][0] == (5, 6, 7)
        assert image.pixels[1][2] == (5, 6, 7)

    async def test_decode_invalid_raises(self) -> None:
        with pytest.raises(VisionDecodeError):
            await (await _manager()).decode(b"not-an-image")

    async def test_decode_empty_rejected(self) -> None:
        with pytest.raises((VisionDecodeError, VisionValidationError)):
            await (await _manager()).decode(b"")


# ──────────────────────────────────────────────────────────────
# Analysis
# ──────────────────────────────────────────────────────────────


class TestAnalyze:
    async def test_analysis_produces_all_features(self) -> None:
        manager = await _manager()
        analysis = await manager.analyze(solid_png(32, 32, (255, 0, 0)))
        assert isinstance(analysis, ImageAnalysis)
        assert analysis.width == 32
        assert analysis.height == 32
        assert len(analysis.embedding) == 16 * 16 * 3
        assert len(analysis.color_histogram) == 64
        assert len(analysis.shape_signature) == 64
        assert analysis.shape.aspect_ratio == pytest.approx(1.0, abs=0.01)
        assert analysis.shape.orientation == "square"
        assert analysis.provider_used == "local"
        assert analysis.dominant_colors, "expected at least one dominant color"
        # Solid red image: the dominant color should be red-ish.
        top = analysis.dominant_colors[0]
        assert top.r > 200 and top.g < 60 and top.b < 60

    async def test_analysis_is_deterministic(self) -> None:
        manager = await _manager()
        a = await manager.analyze(solid_png(20, 20, (40, 80, 160)))
        b = await manager.analyze(solid_png(20, 20, (40, 80, 160)))
        assert a.embedding == b.embedding
        assert a.color_histogram == b.color_histogram

    async def test_detects_barcode_pattern(self) -> None:
        analysis = await (await _manager()).analyze(stripes_png())
        assert analysis.barcodes
        assert analysis.barcodes[0].detected is True

    async def test_detects_logo_signature(self) -> None:
        analysis = await (await _manager()).analyze(logo_png())
        assert analysis.logos
        assert analysis.logos[0].r > 150  # the saturated red logo
        assert analysis.logos[0].g < 100

    async def test_plain_image_has_no_barcode(self) -> None:
        analysis = await (await _manager()).analyze(solid_png(48, 48, (0, 128, 255)))
        assert not analysis.barcodes


# ──────────────────────────────────────────────────────────────
# Similarity
# ──────────────────────────────────────────────────────────────


class TestSimilarity:
    async def test_identical_images_high_similarity(self) -> None:
        manager = await _manager()
        data = solid_png(40, 40, (200, 60, 60))
        a = await manager.analyze(data)
        b = await manager.analyze(data)
        comparison = await manager.compare(a, b)
        assert comparison.overall_visual_similarity > 0.9
        by_name = {f.feature: f.similarity for f in comparison.features}
        assert by_name["embedding"] > 0.99
        assert by_name["color"] > 0.99

    async def test_different_colors_low_similarity(self) -> None:
        manager = await _manager()
        red = await manager.analyze(solid_png(40, 40, (255, 0, 0)))
        blue = await manager.analyze(solid_png(40, 40, (0, 0, 255)))
        comparison = await manager.compare(red, blue)
        by_name = {f.feature: f.similarity for f in comparison.features}
        assert by_name["embedding"] < 0.4
        assert by_name["color"] < 0.4


# ──────────────────────────────────────────────────────────────
# Text helpers
# ──────────────────────────────────────────────────────────────


class TestText:
    def test_extract_model_numbers(self) -> None:
        found = extract_model_numbers("Model XYZ-12345 revision B")
        assert any("XYZ12345" in m.replace("-", "").upper() for m in found)

    def test_brand_normalization(self) -> None:
        assert normalize_brand("  Sony  ") == "sony"
        assert normalize_brand("APPLE") == "apple"

    def test_text_similarity(self) -> None:
        assert text_similarity("Sony WH-1000XM5 Headphones", "Sony WH-1000XM5 Headphones") > 0.9
        assert text_similarity("A completely different title", "Unrelated Widget Thing") < 0.5

    def test_attribute_overlap(self) -> None:
        a = {"color": "black", "size": "10", "material": "metal"}
        b = {"color": "black", "size": "10"}
        assert attribute_overlap(a, b) > 0.5
        assert attribute_overlap(a, {}) == 0.0


# ──────────────────────────────────────────────────────────────
# Matcher (vision + catalog fusion)
# ──────────────────────────────────────────────────────────────


class TestMatcher:
    async def _obs(self, manager: VisionManager, data: bytes, **kwargs: str) -> SimilarityTarget:
        analysis = await manager.analyze(data)
        return SimilarityTarget(analysis=analysis, **kwargs)

    async def test_matches_on_catalog_signals(self) -> None:
        manager = await _manager()
        observed = await self._obs(manager, solid_png(20, 20, (10, 10, 10)), upc="012345678905", brand="Acme")
        reference = SimilarityTarget(upc="012345678905", brand="Acme", title="Acme Gadget Pro")
        result = await manager.match(observed, reference)
        assert result.confidence > 0.7
        matched = {f.feature for f in result.matched_features}
        assert "upc" in matched
        assert "brand" in matched
        assert result.explanation

    async def test_hard_upc_mismatch_dragged_down(self) -> None:
        manager = await _manager()
        observed = await self._obs(manager, solid_png(20, 20, (10, 10, 10)), upc="012345678905")
        reference = SimilarityTarget(upc="999999999999")
        result = await manager.match(observed, reference)
        assert result.confidence < 0.2
        assert "upc" in {f.feature for f in result.unmatched_features}

    async def test_vision_plus_title_raises_confidence(self) -> None:
        manager = await _manager()
        data = solid_png(40, 40, (180, 90, 30))
        observed = await self._obs(manager, data)
        same = await self._obs(manager, data)
        reference = SimilarityTarget(analysis=same.analysis, title="Copper Coffee Maker")
        observed_with_title = SimilarityTarget(analysis=observed.analysis, title="Copper Coffee Maker")
        result = await manager.match(observed_with_title, reference)
        assert result.overall_similarity > 0.9
        assert "embedding" in {f.feature for f in result.matched_features}
        assert "title" in {f.feature for f in result.matched_features}

    async def test_attribute_mismatch_is_unmatched(self) -> None:
        manager = await _manager()
        observed = SimilarityTarget(attributes={"color": "black", "size": "10"})
        reference = SimilarityTarget(attributes={"color": "white", "size": "10"})
        result = await manager.match(observed, reference)
        attrs = next((f for f in result.matched_features + result.unmatched_features if f.feature == "attributes"), None)
        assert attrs is not None
        assert attrs.matched is False

    async def test_no_signals_yields_zero(self) -> None:
        manager = await _manager()
        result = await manager.match(SimilarityTarget(), SimilarityTarget())
        assert result.confidence == 0.0
        assert not result.matched_features

    async def test_compare_returns_feature_breakdown(self) -> None:
        manager = await _manager()
        a = await manager.analyze(solid_png(32, 32, (200, 200, 200)))
        b = await manager.analyze(solid_png(32, 32, (200, 200, 200)))
        comparison = await manager.compare(a, b)
        names = {f.feature for f in comparison.features}
        assert {"embedding", "color", "shape", "size", "package"} <= names


# ──────────────────────────────────────────────────────────────
# Providers
# ──────────────────────────────────────────────────────────────


class FakeOCRProvider(LocalVisionProvider):
    """Local provider that also supplies OCR text."""

    async def ocr(self, _image: Image) -> str:
        return "Sony Headphones MODEL WH1000XM5"


class TestProviders:
    def test_factory_defaults_to_local(self) -> None:
        provider = build_vision_provider(VisionConfig())
        assert isinstance(provider, LocalVisionProvider)
        assert VisionCapability.IMAGE_EMBEDDING in provider.capabilities
        assert VisionCapability.OCR not in provider.capabilities

    async def test_provider_ocr_enriches_analysis(self) -> None:
        manager = VisionManager(provider=FakeOCRProvider(), config=VisionConfig())
        analysis = await manager.analyze(solid_png(20, 20, (100, 100, 100)))
        assert "Sony" in analysis.ocr_text
        assert any("WH1000XM5" in m for m in analysis.model_numbers)

    async def test_provider_override_embedding(self) -> None:
        class FixedEmbedder(LocalVisionProvider):
            async def embed(self, _image: Image) -> list[float]:
                return [0.5, 0.5]

        manager = VisionManager(provider=FixedEmbedder(), config=VisionConfig())
        analysis = await manager.analyze(solid_png(10, 10, (1, 2, 3)))
        assert analysis.embedding == [0.5, 0.5]

    async def test_capabilities(self) -> None:
        manager = await _manager()
        caps = manager.capabilities()
        assert caps.provider == "local"
        assert VisionCapability.COLOR_COMPARISON in caps.capabilities


# ──────────────────────────────────────────────────────────────
# HTTP API
# ──────────────────────────────────────────────────────────────


class TestAPI:
    async def test_analyze_endpoint(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/vision/analyze",
            files={"file": ("red.png", solid_png(16, 16, (255, 0, 0)), "image/png")},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["width"] == 16
        assert payload["provider_used"] == "local"
        assert payload["dominant_colors"]

    async def test_match_endpoint(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/vision/match",
            files={"file": ("gray.png", solid_png(16, 16, (80, 80, 80)), "image/png")},
            data={
                "reference_upc": "012345678905",
                "reference_brand": "Acme",
                "reference_title": "Acme Widget",
                "observed_upc": "012345678905",
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert "confidence" in payload
        assert payload["explanation"]
        matched = {f["feature"] for f in payload["matched_features"]}
        assert "upc" in matched

    async def test_capabilities_endpoint(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/vision/capabilities")
        assert response.status_code == 200
        assert response.json()["provider"] == "local"

    async def test_compare_endpoint(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/vision/compare",
            files={
                "observed": ("a.png", solid_png(16, 16, (50, 120, 200)), "image/png"),
                "reference": ("b.png", solid_png(16, 16, (50, 120, 200)), "image/png"),
            },
        )
        assert response.status_code == 200
        assert response.json()["overall_visual_similarity"] > 0.9

    async def test_invalid_image_returns_422(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/vision/analyze",
            files={"file": ("bad.bin", b"not an image", "application/octet-stream")},
        )
        assert response.status_code == 422
