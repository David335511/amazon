"""Extractor seam for the document intelligence system.

`Extractor` is the ONLY contract a format parser must satisfy. Each extractor
turns raw bytes into a normalized `ExtractionResult` (text, lines, tables,
metadata, page count) that the `DocumentManager` then passes to the field
extractor. Parsers never depend on a specific vendor library; enhanced parsers
(pypdf, Pillow, OCR) plug in behind the same interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from app.documents.models import DocumentFormat


@dataclass
class ExtractionResult:
    """Normalized output of a single extractor."""

    format: DocumentFormat
    text: str = ""
    tables: list[list[list[str]]] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)
    pages: int | None = None

    @property
    def lines(self) -> list[str]:
        """Split text into non-empty lines (for line-based field scanning)."""
        return [line.strip() for line in self.text.splitlines() if line.strip()]


class Extractor(ABC):
    """Abstract base for a document-format extractor."""

    format: DocumentFormat

    @abstractmethod
    async def extract(self, data: bytes) -> ExtractionResult:
        """Parse bytes and return the normalized result.

        Implementations must be deterministic and safe on arbitrary input; a
        corrupt payload should return an empty result rather than raise, so the
        manager can fall back to OCR or record a low-confidence parse.
        """
