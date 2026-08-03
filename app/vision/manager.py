"""Vision subsystem facade.

`VisionManager` is the ONLY entry point the rest of the platform uses for image
analysis, comparison and multimodal matching. It owns the decode + analyze +
provider orchestration and exposes a small async surface:

- ``analyze(bytes)``       -> `ImageAnalysis`
- ``compare_analyses(a,b)``-> `VisionComparison`
- ``match(observed, ref)`` -> `VisionMatchResult`
- ``capabilities()``       -> which capabilities the configured provider supports

It holds no domain logic for matching (that lives in `app.vision.matcher`); it
simply decodes, extracts features with the local analyzers, overlays any
enhanced provider results (OCR, real barcodes, named logos, remote embeddings),
then delegates to the matcher.
"""

from __future__ import annotations

from app.vision.analyze import (
    build_package,
    compute_color_histogram,
    compute_embedding,
    compute_shape,
    compute_size,
)
from app.vision.config import VisionConfig
from app.vision.decode import decode_image
from app.vision.errors import VisionDecodeError, VisionValidationError
from app.vision.matcher import compare_analyses
from app.vision.matcher import match as _match
from app.vision.models import (
    Image,
    ImageAnalysis,
    SimilarityTarget,
    VisionCapabilities,
    VisionComparison,
    VisionMatchResult,
)
from app.vision.providers import LocalVisionProvider, VisionProvider
from app.vision.text import extract_model_numbers


class VisionManager:
    """Facade for the computer-vision subsystem."""

    def __init__(
        self,
        provider: VisionProvider | None = None,
        config: VisionConfig | None = None,
    ) -> None:
        self._provider = provider or LocalVisionProvider()
        self._config = config or VisionConfig()

    @property
    def provider_name(self) -> str:
        return self._provider.name

    async def decode(self, data: bytes) -> Image:
        """Decode bytes to an internal `Image`."""
        if not data:
            msg = "Empty image payload"
            raise VisionValidationError(msg)
        if len(data) > self._config.max_decode_bytes:
            msg = "Image exceeds the maximum allowed size"
            raise VisionValidationError(msg)
        if self._provider.name != "local":
            provider_image = await self._provider.decode(data)
            if provider_image is not None:
                return provider_image
        try:
            return decode_image(data)
        except VisionDecodeError as exc:
            raise VisionDecodeError(str(exc)) from exc

    async def analyze(self, data: bytes) -> ImageAnalysis:
        """Decode and analyze an image, producing the full feature set."""
        image = await self.decode(data)
        return await self.analyze_image(image)

    async def analyze_image(self, image: Image) -> ImageAnalysis:
        """Analyze an already-decoded `Image` (used by provider overrides)."""
        cfg = self._config
        embedding = await self._provider.embed(image)
        if embedding is None:
            embedding = compute_embedding(image, grid=cfg.embed_grid)
        color_histogram, dominant_colors = compute_color_histogram(
            image,
            buckets=cfg.color_buckets,
            dominant_count=cfg.dominant_color_count,
        )
        shape_signature, shape = compute_shape(image, grid=cfg.shape_grid)
        size = compute_size(image)
        package = build_package(shape, dominant_colors)

        ocr_text = await self._provider.ocr(image)
        model_numbers = extract_model_numbers(ocr_text)
        barcodes = await self._provider.detect_barcodes(image)
        logos = await self._provider.detect_logos(image)

        return ImageAnalysis(
            width=image.width,
            height=image.height,
            embedding=embedding,
            color_histogram=color_histogram,
            shape_signature=shape_signature,
            dominant_colors=dominant_colors,
            shape=shape,
            size=size,
            package=package,
            ocr_text=ocr_text,
            model_numbers=model_numbers,
            barcodes=barcodes,
            logos=logos,
            provider_used=self._provider.name,
        )

    async def compare(
        self,
        observed: bytes | ImageAnalysis,
        reference: bytes | ImageAnalysis,
    ) -> VisionComparison:
        """Compare two images (bytes or already-analyzed) feature by feature."""
        obs_an = await self._coerce_analysis(observed)
        ref_an = await self._coerce_analysis(reference)
        return compare_analyses(obs_an, ref_an, self._config)

    async def match(
        self,
        observed: SimilarityTarget,
        reference: SimilarityTarget,
    ) -> VisionMatchResult:
        """Fuse vision + catalog signals into a match result."""
        return _match(observed, reference, self._config)

    def capabilities(self) -> VisionCapabilities:
        """Report the capabilities the configured provider genuinely supports."""
        return VisionCapabilities(
            provider=self._provider.name,
            capabilities=sorted(
                (c for c in self._provider.capabilities),
                key=lambda c: c.value,
            ),
        )

    async def _coerce_analysis(self, value: bytes | ImageAnalysis) -> ImageAnalysis:
        if isinstance(value, ImageAnalysis):
            return value
        return await self.analyze(value)
