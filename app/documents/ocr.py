"""OCR provider seam for the document intelligence system.

`OCRProvider` is the ONLY contract the document subsystem uses for optical
character recognition. It is pluggable so the platform can use a local no-op
(default), Tesseract (real OCR when `pytesseract` is installed via the optional
`[documents]` extra), or any generic remote OCR service. OCR is invoked as a
fallback when the text extractor yields too little text (scanned/image-only
PDFs), and its output feeds the exact same field extractor.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.documents.config import DocumentConfig


class OCRProvider(ABC):
    """Abstract OCR provider."""

    name: str = "base"

    @abstractmethod
    async def ocr(self, data: bytes, *, mime: str | None = None) -> str:
        """Return recognized text from document/image bytes.

        Implementations return ``""`` when they cannot OCR the payload, so the
        manager treats OCR as best-effort.
        """


class LocalOCRProvider(OCRProvider):
    """Default provider: no OCR (text extraction only)."""

    name = "local"

    async def ocr(self, _data: bytes, *, mime: str | None = None) -> str:  # noqa: ARG002
        return ""


class TesseractOCRProvider(OCRProvider):
    """Real OCR via the optional `pytesseract` extra (lazily imported)."""

    name = "tesseract"

    async def ocr(self, data: bytes, *, mime: str | None = None) -> str:  # noqa: ARG002
        try:
            import io

            import pytesseract  # type: ignore[import-not-found]
            from PIL import Image  # type: ignore[import-not-found]
        except ImportError:
            return ""
        try:
            image = Image.open(io.BytesIO(data))
            return pytesseract.image_to_string(image).strip()
        except Exception:
            return ""


class HTTPOCRProvider(OCRProvider):
    """Generic remote OCR service (POST the raw bytes, read `text`)."""

    name = "http"

    def __init__(self, base_url: str, api_key: str = "") -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key

    async def ocr(self, data: bytes, *, mime: str | None = None) -> str:
        if not self._base_url:
            return ""
        try:
            import httpx

            headers = {"Content-Type": mime or "application/octet-stream"}
            if self._api_key:
                headers["Authorization"] = f"Bearer {self._api_key}"
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(self._base_url, content=data, headers=headers)
                response.raise_for_status()
            payload = response.json()
            if isinstance(payload, dict):
                return str(payload.get("text", ""))
            return str(payload)
        except Exception:
            return ""


def build_ocr_provider(config: DocumentConfig) -> OCRProvider:
    """Build the configured OCR provider (default: local no-op)."""
    provider = (config.ocr_provider or "local").lower()
    if provider == "tesseract":
        return TesseractOCRProvider()
    if provider == "http":
        return HTTPOCRProvider(config.http_base_url, config.http_api_key)
    return LocalOCRProvider()
