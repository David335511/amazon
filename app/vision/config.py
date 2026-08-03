"""Configuration for the computer-vision subsystem.

Follows the same layered-config convention as every other subsystem: Pydantic
defaults, overridable via YAML (``config/<env>.yaml``) and environment vars.
The DI layer builds a `VisionConfig` from the raw ``vision:`` YAML block.

Everything here is provider-agnostic: the *weights* define how the matcher fuses
visual signals with catalog signals (UPC / title / brand / attributes) into a
single confidence score.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class VisionConfig(BaseSettings):
    """Runtime settings for the computer-vision subsystem."""

    enabled: bool = True

    # Provider seam. "local" (pure-stdlib, always available) is the default;
    # "tesseract" / "http" opt into external OCR/vision capabilities.
    provider: str = "local"

    # Decoding / analysis fidelity.
    max_decode_bytes: int = 10_000_000  # 10 MB
    embed_grid: int = 16  # NxN grid used for the visual embedding
    shape_grid: int = 8  # NxN grid used for the shape signature
    color_buckets: int = 4  # per-channel quantization buckets for the histogram
    dominant_color_count: int = 5
    barcode_transition_threshold: int = 28  # edges per 100px that suggest a barcode

    # Matching. A feature is reported as "matched" when its score >= threshold.
    match_threshold: float = 0.55

    # Signal weights used by the matcher (relative; only available signals count).
    weight_upc: float = 0.30
    weight_brand: float = 0.15
    weight_title: float = 0.15
    weight_attributes: float = 0.10
    weight_embedding: float = 0.10
    weight_color: float = 0.05
    weight_shape: float = 0.05
    weight_size: float = 0.03
    weight_barcode: float = 0.03
    weight_logo: float = 0.02
    weight_model: float = 0.02

    # A definitive contradiction (both UPCs present but different, or both
    # brands present but different) multiplies confidence down by this factor.
    hard_mismatch_penalty: float = 0.35

    # Optional generic remote vision provider (provider-independent HTTP).
    http_base_url: str = ""
    http_api_key: str = ""

    model_config = SettingsConfigDict(extra="ignore")
