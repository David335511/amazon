"""Document intelligence system.

Ingests, parses, stores (raw + parsed) and searches documents: product manuals,
specification sheets, invoices, and any other structured file the platform
receives. Supports PDF, HTML, DOCX, CSV, XLSX and plain text (txt / markdown /
json), with pluggable OCR.

The pipeline is:
    bytes -> detect format -> extractor (per format) -> OCR fallback
          -> field extraction (UPC/EAN/GTIN, weight, dimensions, case quantity,
             model number, manufacturer, part number, warranty)
          -> persist raw blob + parsed fields -> full-text & field search

Everything is driven through `DocumentManager` and the `/api/v1/documents`
endpoints. Parsers and OCR providers are seams: a pure-stdlib core is always
available, and richer libraries (pypdf, Pillow + pytesseract, remote OCR) plug
in behind the same interfaces.
"""

from app.documents.config import DocumentConfig
from app.documents.errors import (
    DocumentError,
    DocumentExtractionError,
    DocumentNotFoundError,
    DocumentUnsupportedError,
    DocumentValidationError,
)
from app.documents.extractors import build_extractors
from app.documents.fields import extract_barcodes, extract_fields
from app.documents.manager import DocumentManager
from app.documents.models import Document, DocumentFormat, DocumentType
from app.documents.ocr import (
    HTTPOCRProvider,
    LocalOCRProvider,
    OCRProvider,
    TesseractOCRProvider,
    build_ocr_provider,
)
from app.documents.repository import DocumentRepository
from app.documents.schemas import (
    DocumentCapabilities,
    DocumentList,
    DocumentRead,
    DocumentStats,
    DocumentSummary,
    ExtractedFields,
    ParsedDocument,
    Table,
)

__all__ = [
    "Document",
    "DocumentCapabilities",
    "DocumentConfig",
    "DocumentError",
    "DocumentExtractionError",
    "DocumentFormat",
    "DocumentList",
    "DocumentManager",
    "DocumentNotFoundError",
    "DocumentRead",
    "DocumentRepository",
    "DocumentStats",
    "DocumentSummary",
    "DocumentType",
    "DocumentUnsupportedError",
    "DocumentValidationError",
    "ExtractedFields",
    "HTTPOCRProvider",
    "LocalOCRProvider",
    "OCRProvider",
    "ParsedDocument",
    "Table",
    "TesseractOCRProvider",
    "build_extractors",
    "build_ocr_provider",
    "extract_barcodes",
    "extract_fields",
]
