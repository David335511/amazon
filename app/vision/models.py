"""Data models for the computer-vision subsystem.

- `Image` is the *internal* pixel representation (a dataclass, not exposed over
  the API). Every analysis primitive works purely on an `Image`, so all feature
  extraction is provider-independent.
- The remaining types are Pydantic models and are returned by the API, so they
  carry validation, serialization, and schema documentation for free.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


@dataclass
class Image:
    """A decoded RGB image. `pixels[rows][cols]` -> (r, g, b) each 0..255."""

    width: int
    height: int
    pixels: list[list[tuple[int, int, int]]] = field(default_factory=list)


class VisionCapability(StrEnum):
    """Capabilities a vision provider may genuinely support.

    The local provider always supports the deterministic primitives (embeddings,
    color, shape, size, model-number scanning, heuristic barcode/logo); OCR and
    high-confidence barcode decoding require an enhanced provider.
    """

    IMAGE_EMBEDDING = "image_embedding"
    OCR = "ocr"
    LOGO_DETECTION = "logo_detection"
    PACKAGE_COMPARISON = "package_comparison"
    COLOR_COMPARISON = "color_comparison"
    SHAPE_COMPARISON = "shape_comparison"
    SIZE_COMPARISON = "size_comparison"
    MODEL_NUMBER_DETECTION = "model_number_detection"
    BARCODE_DETECTION = "barcode_detection"


class ColorInfo(BaseModel):
    """A dominant color and its share of the image."""

    hex: str = Field(description="Hex color, e.g. #ff0000")
    r: int = Field(ge=0, le=255)
    g: int = Field(ge=0, le=255)
    b: int = Field(ge=0, le=255)
    fraction: float = Field(ge=0.0, le=1.0, description="Share of image pixels")


class ShapeInfo(BaseModel):
    """Coarse geometric description of an image/subject."""

    aspect_ratio: float = Field(ge=0.0, description="width / height")
    orientation: str = Field(
        description="'landscape', 'portrait' or 'square'",
    )
    pixel_area: int = Field(ge=0)


class SizeInfo(BaseModel):
    """Relative size/proportion information.

    Pixel data alone cannot determine physical dimensions, so size is expressed
    as *proportions*: aspect ratio and relative pixel area. Provide real-world
    scale (e.g. in a product attribute) to derive physical size.
    """

    aspect_ratio: float = Field(ge=0.0)
    pixel_area: int = Field(ge=0)
    width: int = Field(ge=0)
    height: int = Field(ge=0)


class BarcodeInfo(BaseModel):
    """A detected barcode region.

    The local provider detects the *presence* and style of a barcode pattern
    (a high-contrast vertical-line structure) but cannot decode its value —
    decoding requires a provider with a barcode library (zbar/OpenCV).
    """

    detected: bool
    barcode_type: str = "unknown"
    value: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)


class LogoSignature(BaseModel):
    """A local signature for a logo-like (saturated colored) region.

    The local provider produces a deterministic signature (dominant saturated
    color + spatial fraction) that supports *comparison* between images. Real
    logo recognition (naming the logo) requires an enhanced provider.
    """

    name: str = ""
    hex: str = ""
    r: int = 0
    g: int = 0
    b: int = 0
    fraction: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)


class PackageInfo(BaseModel):
    """Packaging-level summary (shape + dominant colors of the subject)."""

    aspect_ratio: float
    orientation: str
    dominant_colors: list[ColorInfo] = Field(default_factory=list)


class ImageAnalysis(BaseModel):
    """The full set of features extracted from a single image."""

    width: int = Field(ge=0)
    height: int = Field(ge=0)
    # Deterministic visual embedding (a compact, comparable feature vector).
    embedding: list[float] = Field(default_factory=list)
    # Quantized color histogram (for color comparison).
    color_histogram: list[float] = Field(default_factory=list)
    # Normalized luminance grid (for shape comparison).
    shape_signature: list[float] = Field(default_factory=list)
    dominant_colors: list[ColorInfo] = Field(default_factory=list)
    shape: ShapeInfo
    size: SizeInfo
    package: PackageInfo
    # Enhanced-capability results (empty when no provider supports them).
    ocr_text: str = ""
    model_numbers: list[str] = Field(default_factory=list)
    barcodes: list[BarcodeInfo] = Field(default_factory=list)
    logos: list[LogoSignature] = Field(default_factory=list)
    provider_used: str = "local"


class SimilarityTarget(BaseModel):
    """The reference product the observed image is compared against.

    Vision features (``analysis``) are optional: matching works with just the
    catalog signals (UPC / title / brand / attributes) and degrades gracefully
    when a signal is absent.
    """

    analysis: ImageAnalysis | None = None
    upc: str | None = None
    title: str | None = None
    brand: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class FeatureMatch(BaseModel):
    """A single feature-level comparison result."""

    feature: str  # e.g. "upc", "brand", "title", "color", "shape", ...
    kind: str  # "catalog" or "vision"
    matched: bool
    score: float = Field(ge=0.0, le=1.0)
    detail: str = Field(description="Human-readable explanation")
    weight: float = Field(ge=0.0)


class VisionMatchResult(BaseModel):
    """The fused match result: confidence, explanation and feature breakdown."""

    confidence: float = Field(ge=0.0, le=1.0, description="Fused 0..1 confidence")
    overall_similarity: float = Field(
        ge=0.0,
        le=1.0,
        description="Visual similarity from the image embedding alone",
    )
    matched_features: list[FeatureMatch] = Field(default_factory=list)
    unmatched_features: list[FeatureMatch] = Field(default_factory=list)
    explanation: str = Field(description="Human-readable match rationale")
    provider_used: str = "local"


class FeatureSimilarity(BaseModel):
    """One feature-level similarity in a direct image comparison."""

    feature: str
    similarity: float = Field(ge=0.0, le=1.0)
    detail: str


class VisionComparison(BaseModel):
    """Result of comparing two images feature by feature."""

    overall_visual_similarity: float = Field(ge=0.0, le=1.0)
    features: list[FeatureSimilarity] = Field(default_factory=list)


class VisionCapabilities(BaseModel):
    """Which capabilities the configured provider genuinely supports."""

    provider: str
    capabilities: list[VisionCapability] = Field(default_factory=list)
