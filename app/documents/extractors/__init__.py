"""Format extractors for the document intelligence system.

`build_extractors(config)` returns the enabled ``{DocumentFormat: Extractor}``
map, honoring the per-format master switches in `DocumentConfig`. The manager
uses this map to dispatch raw bytes to the right parser.
"""

from __future__ import annotations

from collections.abc import Mapping

from app.documents.config import DocumentConfig
from app.documents.extractors.base import ExtractionResult, Extractor
from app.documents.extractors.csv import CSVExtractor
from app.documents.extractors.docx import DOCXExtractor
from app.documents.extractors.html import HTMLExtractor
from app.documents.extractors.pdf import PDFExtractor
from app.documents.extractors.text import PlainTextExtractor
from app.documents.extractors.xlsx import XLSXExtractor
from app.documents.models import DocumentFormat

__all__ = [
    "CSVExtractor",
    "DOCXExtractor",
    "ExtractionResult",
    "Extractor",
    "HTMLExtractor",
    "PDFExtractor",
    "PlainTextExtractor",
    "XLSXExtractor",
    "build_extractors",
]


def build_extractors(config: DocumentConfig) -> Mapping[DocumentFormat, Extractor]:
    """Build the enabled extractor map from configuration."""
    extractors: dict[DocumentFormat, Extractor] = {}

    def _add(fmt: DocumentFormat, extractor: Extractor, flag: bool) -> None:
        if flag:
            extractors[fmt] = extractor

    _add(DocumentFormat.PDF, PDFExtractor(), config.enable_pdf)
    _add(DocumentFormat.HTML, HTMLExtractor(), config.enable_html)
    _add(DocumentFormat.DOCX, DOCXExtractor(), config.enable_docx)
    _add(DocumentFormat.CSV, CSVExtractor(), config.enable_csv)
    _add(DocumentFormat.XLSX, XLSXExtractor(), config.enable_xlsx)
    _add(DocumentFormat.MARKDOWN, PlainTextExtractor(DocumentFormat.MARKDOWN), config.enable_text)
    _add(DocumentFormat.JSON, PlainTextExtractor(DocumentFormat.JSON), config.enable_text)
    _add(DocumentFormat.TXT, PlainTextExtractor(), config.enable_text)
    return extractors
