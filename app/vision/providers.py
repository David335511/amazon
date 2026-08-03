"""Vision provider seam.

`VisionProvider` is the ONLY contract the vision subsystem uses for
*enhanced* capabilities (OCR, named logo recognition, true barcode decoding,
remote image embeddings). It is pluggable so the platform can use a local
pure-stdlib analyzer (default, always available), Tesseract for OCR, or any
generic HTTP vision service — the subsystem never depends on a specific vendor.

The local analyzers (embedding, color, shape, size, barcode/logo heuristics,
model-number scanning) live in `app.vision.analyze` and `app.vision.text` and
always run; the provider only *overrides* pieces it genuinely supports. A method
returning ``None`` / ``""`` / ``[]`` means "fall back to the local default".
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

import httpx

from app.vision.analyze import detect_barcode, detect_logo
from app.vision.config import VisionConfig
from app.vision.models import BarcodeInfo, Image, LogoSignature, VisionCapability


class VisionProvider(ABC):
    """Pluggable provider for enhanced vision capabilities."""

    name: str = "base"
    capabilities: ClassVar[set[VisionCapability]] = set()

    @abstractmethod
    async def decode(self, data: bytes) -> Image | None:
        """Decode bytes to an Image; None means 'use the stdlib decoder'."""

    @abstractmethod
    async def ocr(self, image: Image) -> str:
        """Extract text from an image; '' means 'no OCR available'."""

    @abstractmethod
    async def embed(self, image: Image) -> list[float] | None:
        """Produce a visual embedding; None means 'use the local embedder'."""

    @abstractmethod
    async def detect_logos(self, image: Image) -> list[LogoSignature]:
        """Detect/named-identify logos; [] means 'use the local heuristic'."""

    @abstractmethod
    async def detect_barcodes(self, image: Image) -> list[BarcodeInfo]:
        """Detect/decode barcodes; [] means 'use the local heuristic'."""

    @abstractmethod
    async def is_available(self) -> bool:
        """Whether this provider is reachable/configured right now."""

    def supported(self, capability: VisionCapability) -> bool:
        """Whether this provider genuinely supports a capability."""
        return capability in self.capabilities


class LocalVisionProvider(VisionProvider):
    """The default provider: everything runs through the pure-stdlib analyzers.

    Deterministic, offline, and always available. It provides embeddings,
    color/shape/size analysis, model-number scanning, and heuristic barcode/logo
    signatures, but no real OCR (that requires an enhanced provider).
    """

    name = "local"
    capabilities: ClassVar[set[VisionCapability]] = {
        VisionCapability.IMAGE_EMBEDDING,
        VisionCapability.PACKAGE_COMPARISON,
        VisionCapability.COLOR_COMPARISON,
        VisionCapability.SHAPE_COMPARISON,
        VisionCapability.SIZE_COMPARISON,
        VisionCapability.MODEL_NUMBER_DETECTION,
        VisionCapability.BARCODE_DETECTION,
        VisionCapability.LOGO_DETECTION,
    }

    async def decode(self, _data: bytes) -> Image | None:
        return None  # stdlib decoder handles PNG/BMP

    async def ocr(self, _image: Image) -> str:
        return ""  # no real OCR; use Tesseract / an HTTP provider

    async def embed(self, _image: Image) -> list[float] | None:
        return None  # use the local deterministic embedder

    async def detect_logos(self, image: Image) -> list[LogoSignature]:
        return detect_logo(image)

    async def detect_barcodes(self, image: Image) -> list[BarcodeInfo]:
        return detect_barcode(image)

    async def is_available(self) -> bool:
        return True


class TesseractOCRProvider(VisionProvider):
    """Real OCR via Tesseract (optional, lazy-loaded).

    Requires ``pytesseract`` and a system Tesseract binary. When either is
    missing, `is_available` is False and OCR gracefully degrades to ''. Other
    capabilities fall back to the local analyzers.
    """

    name = "tesseract"
    capabilities: ClassVar[set[VisionCapability]] = {VisionCapability.OCR}

    def __init__(self) -> None:
        self._ocr = None

    def _load(self) -> object | None:
        if self._ocr is None:
            try:
                import pytesseract  # type: ignore[import-not-found]

                self._ocr = pytesseract
            except ImportError:
                self._ocr = False
        return self._ocr or None

    async def is_available(self) -> bool:
        return self._load() is not None

    async def decode(self, _data: bytes) -> Image | None:
        return None

    async def ocr(self, image: Image) -> str:
        engine = self._load()
        if engine is None:
            return ""
        try:
            from PIL import Image as PILImage  # type: ignore[import-not-found]

            pil_img = PILImage.new("RGB", (image.width, image.height))
            pil_img.putdata([pixel for row in image.pixels for pixel in row])
            return engine.image_to_string(pil_img)  # type: ignore[attr-defined]
        except Exception:
            return ""

    async def embed(self, _image: Image) -> list[float] | None:
        return None

    async def detect_logos(self, _image: Image) -> list[LogoSignature]:
        return []

    async def detect_barcodes(self, _image: Image) -> list[BarcodeInfo]:
        return []


class HTTPVisionProvider(VisionProvider):
    """A generic, provider-independent HTTP vision service.

    POSTs an image to ``{base_url}/analyze`` and expects a JSON document with
    optional keys: ``embedding``, ``ocr_text``, ``logos``, ``barcodes``. This is
    a seam for ANY vendor's vision API (configure via ``base_url``/``api_key``)
    so the platform stays decoupled from a specific provider. Falls back to the
    local analyzers when unreachable.
    """

    name = "http"
    capabilities: ClassVar[set[VisionCapability]] = {
        VisionCapability.OCR,
        VisionCapability.LOGO_DETECTION,
        VisionCapability.BARCODE_DETECTION,
        VisionCapability.IMAGE_EMBEDDING,
    }

    def __init__(self, base_url: str, api_key: str = "", timeout: float = 15.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout

    async def _post(self, image: Image) -> dict:
        from io import BytesIO

        from PIL import Image as PILImage  # type: ignore[import-not-found]

        pil_img = PILImage.new("RGB", (image.width, image.height))
        pil_img.putdata([pixel for row in image.pixels for pixel in row])
        buffer = BytesIO()
        pil_img.save(buffer, format="PNG")
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                f"{self._base_url}/analyze",
                headers=headers,
                files={"file": ("image.png", buffer.getvalue(), "image/png")},
            )
            response.raise_for_status()
            return response.json()

    async def is_available(self) -> bool:
        if not self._base_url:
            return False
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                response = await client.get(f"{self._base_url}/health")
            return response.status_code == 200
        except Exception:
            return False

    async def decode(self, _data: bytes) -> Image | None:
        return None

    async def ocr(self, image: Image) -> str:
        try:
            payload = await self._post(image)
            return str(payload.get("ocr_text", ""))
        except Exception:
            return ""

    async def embed(self, image: Image) -> list[float] | None:
        try:
            payload = await self._post(image)
            raw = payload.get("embedding")
            return [float(v) for v in raw] if isinstance(raw, list) else None
        except Exception:
            return None

    async def detect_logos(self, image: Image) -> list[LogoSignature]:
        try:
            payload = await self._post(image)
            logos = payload.get("logos", [])
            if isinstance(logos, list):
                return [LogoSignature(**item) for item in logos]
            return []
        except Exception:
            return []

    async def detect_barcodes(self, image: Image) -> list[BarcodeInfo]:
        try:
            payload = await self._post(image)
            barcodes = payload.get("barcodes", [])
            if isinstance(barcodes, list):
                return [BarcodeInfo(**item) for item in barcodes]
            return []
        except Exception:
            return []


def build_vision_provider(config: VisionConfig) -> VisionProvider:
    """Build the vision provider selected by config.

    ``local`` (default) is pure-stdlib and always available. ``tesseract``
    adds real OCR when pytesseract is installed. ``http`` delegates enhanced
    capabilities to any generic remote vision service.
    """
    provider_name = (config.provider or "local").lower()
    if provider_name == "tesseract":
        return TesseractOCRProvider()
    if provider_name == "http":
        return HTTPVisionProvider(
            base_url=config.http_base_url,
            api_key=config.http_api_key,
        )
    return LocalVisionProvider()
