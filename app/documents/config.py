"""Configuration for the document intelligence system.

Follows the same layered-config convention as every other subsystem: Pydantic
defaults, overridable via YAML (``config/<env>.yaml``) and environment vars.
The DI layer builds a `DocumentConfig` from the raw ``documents:`` YAML block
(same pattern as the vision, memory and browser subsystems).
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class DocumentConfig(BaseSettings):
    """Runtime settings for the document intelligence system."""

    enabled: bool = True

    # Payload guardrail.
    max_document_bytes: int = 10 * 1024 * 1024  # 10 MB

    # OCR. "local" (no-op, always available) or "tesseract" (real OCR via the
    # optional `pytesseract`/`[documents]` extra) or "http" (generic remote OCR
    # service configured below).
    ocr_enabled: bool = False
    ocr_provider: str = "local"
    # Run OCR as a fallback when the text extractor yields fewer than this many
    # characters (covers scanned/image-only PDFs).
    ocr_min_text_length: int = 20

    # Per-format master switches (disable formats you do not want processed).
    enable_pdf: bool = True
    enable_html: bool = True
    enable_docx: bool = True
    enable_csv: bool = True
    enable_xlsx: bool = True
    enable_text: bool = True

    # Generic remote OCR service (used when ocr_provider = "http").
    http_base_url: str = ""
    http_api_key: str = ""

    model_config = SettingsConfigDict(extra="ignore")
