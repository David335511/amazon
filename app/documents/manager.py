"""Document intelligence facade.

`DocumentManager` is the ONLY entry point the rest of the platform uses for
parsing, storing and searching documents. It owns the orchestration: format
detection -> extractor dispatch -> OCR fallback -> field extraction, plus the
persistence (raw + parsed) and search surface.

Production behaviour:
- **Idempotent ingestion**: re-uploading identical bytes (same sha256) returns
  the existing row instead of duplicating.
- **OCR fallback**: when a document yields too little text and OCR is enabled,
  the configured OCR provider is invoked and its output feeds the same field
  extractor.
- **Cheap list/search**: repository queries defer loading the raw blob.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from app.documents.config import DocumentConfig
from app.documents.errors import (
    DocumentNotFoundError,
    DocumentUnsupportedError,
    DocumentValidationError,
)
from app.documents.extractors import ExtractionResult, build_extractors
from app.documents.fields import extract_fields
from app.documents.models import Document, DocumentFormat, DocumentType
from app.documents.ocr import OCRProvider, build_ocr_provider
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

_EXTENSION_TO_FORMAT = {
    ".pdf": DocumentFormat.PDF,
    ".htm": DocumentFormat.HTML,
    ".html": DocumentFormat.HTML,
    ".docx": DocumentFormat.DOCX,
    ".csv": DocumentFormat.CSV,
    ".xlsx": DocumentFormat.XLSX,
    ".txt": DocumentFormat.TXT,
    ".text": DocumentFormat.TXT,
    ".md": DocumentFormat.MARKDOWN,
    ".markdown": DocumentFormat.MARKDOWN,
    ".json": DocumentFormat.JSON,
}

_MIME_TO_FORMAT = {
    "application/pdf": DocumentFormat.PDF,
    "text/html": DocumentFormat.HTML,
    "application/xhtml+xml": DocumentFormat.HTML,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": DocumentFormat.DOCX,
    "text/csv": DocumentFormat.CSV,
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": DocumentFormat.XLSX,
    "text/plain": DocumentFormat.TXT,
    "text/markdown": DocumentFormat.MARKDOWN,
    "application/json": DocumentFormat.JSON,
}


class DocumentManager:
    """Facade for the document intelligence system."""

    def __init__(
        self,
        repository: DocumentRepository,
        config: DocumentConfig | None = None,
        extractors: Mapping[DocumentFormat, Any] | None = None,
        ocr_provider: OCRProvider | None = None,
    ) -> None:
        self._repo = repository
        self._config = config or DocumentConfig()
        self._extractors = extractors if extractors is not None else build_extractors(self._config)
        self._ocr = ocr_provider if ocr_provider is not None else build_ocr_provider(self._config)

    # ── Parsing (pure, in-memory) ────────────────────────────────────────

    async def parse(
        self,
        data: bytes,
        *,
        filename: str | None = None,
        mime: str | None = None,
        ocr: bool | None = None,
    ) -> ParsedDocument:
        """Parse bytes into a `ParsedDocument` without storing anything."""
        self._validate_size(data)
        fmt = self.detect_format(data, filename=filename, mime=mime)
        result = await self._extract(fmt, data)
        ocr_text = ""
        if self._should_ocr(ocr, result.text):
            ocr_text = await self._ocr.ocr(data, mime=mime)
        text = _combine_text(result.text, ocr_text)
        fields = extract_fields(text)
        tables = [Table(headers=row[0] if row else [], rows=row[1:]) for row in result.tables]
        metadata = dict(result.metadata)
        return ParsedDocument(
            file_format=fmt,
            text=text,
            lines=[ln for ln in text.splitlines() if ln.strip()],
            tables=tables,
            pages=result.pages,
            fields=fields,
            metadata=metadata,
            ocr_used=bool(ocr_text),
        )

    # ── Storage ──────────────────────────────────────────────────────────

    async def ingest(
        self,
        data: bytes,
        *,
        filename: str | None = None,
        mime: str | None = None,
        doc_type: DocumentType = DocumentType.OTHER,
        ocr: bool | None = None,
        user_id: str | None = None,
    ) -> DocumentRead:
        """Parse and persist a document (raw + parsed), deduplicating by sha256."""
        self._validate_size(data)
        sha256 = hashlib.sha256(data).hexdigest()

        existing = await self._repo.find_by_sha256(sha256)
        if existing is not None:
            return self._to_read(existing)

        fmt = self.detect_format(data, filename=filename, mime=mime)
        parsed = await self.parse(data, filename=filename, mime=mime, ocr=ocr)

        document = await self._repo.create(
            user_id=user_id,
            doc_type=doc_type.value,
            file_format=fmt.value,
            filename=filename,
            raw_mime=mime,
            raw_size_bytes=len(data),
            sha256=sha256,
            raw_blob=data,
            text=parsed.text or None,
            extracted_json=_dump(parsed.fields.model_dump()),
            metadata_json=_dump(parsed.metadata),
            pages=parsed.pages,
            ocr_used=parsed.ocr_used,
            confidence=parsed.fields.confidence,
        )
        return self._to_read(document)

    async def get(self, document_id: UUID) -> DocumentRead:
        document = await self._repo.get(document_id)
        if document is None:
            raise DocumentNotFoundError(document_id)
        return self._to_read(document)

    async def raw(self, document_id: UUID) -> tuple[bytes, str | None]:
        """Return (raw bytes, mime) for a stored document."""
        document = await self._repo.get(document_id)
        if document is None:
            raise DocumentNotFoundError(document_id)
        return document.raw_blob, document.raw_mime

    async def delete(self, document_id: UUID) -> bool:
        document = await self._repo.get(document_id)
        if document is None:
            raise DocumentNotFoundError(document_id)
        return await self._repo.delete(document_id)

    # ── Search / list ────────────────────────────────────────────────────

    async def list(
        self,
        *,
        doc_type: DocumentType | None = None,
        file_format: DocumentFormat | None = None,
        user_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> DocumentList:
        items, total = await self._repo.list_summary(
            doc_type=doc_type.value if doc_type else None,
            file_format=file_format.value if file_format else None,
            user_id=user_id,
            limit=limit,
            offset=offset,
        )
        return DocumentList(items=[self._to_summary(d) for d in items], total=total)

    async def search(
        self,
        query: str,
        *,
        doc_type: DocumentType | None = None,
        user_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> DocumentList:
        items, total = await self._repo.search(
            query,
            doc_type=doc_type.value if doc_type else None,
            user_id=user_id,
            limit=limit,
            offset=offset,
        )
        return DocumentList(items=[self._to_summary(d) for d in items], total=total)

    async def search_field(
        self,
        field: str,
        value: str,
        *,
        doc_type: DocumentType | None = None,
        user_id: str | None = None,
        limit: int = 50,
    ) -> DocumentList:
        items = await self._repo.search_field(
            field,
            value,
            doc_type=doc_type.value if doc_type else None,
            user_id=user_id,
            limit=limit,
        )
        return DocumentList(items=[self._to_summary(d) for d in items], total=len(items))

    # ── Introspection ────────────────────────────────────────────────────

    async def stats(self) -> DocumentStats:
        data = await self._repo.stats()
        return DocumentStats(**data)

    def capabilities(self) -> DocumentCapabilities:
        return DocumentCapabilities(
            formats=sorted(self._extractors.keys(), key=lambda f: f.value),
            ocr_provider=self._ocr.name,
            ocr_available=self._ocr.name != "local",
            max_document_bytes=self._config.max_document_bytes,
        )

    # ── Internals ────────────────────────────────────────────────────────

    def detect_format(
        self,
        data: bytes,
        *,
        filename: str | None = None,
        mime: str | None = None,
    ) -> DocumentFormat:
        """Resolve a document format from filename, mime, or magic bytes."""
        if filename:
            ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
            fmt = _EXTENSION_TO_FORMAT.get("." + ext)
            if fmt is not None and fmt in self._extractors:
                return fmt
        if mime:
            fmt = _MIME_TO_FORMAT.get(mime.split(";")[0].strip().lower())
            if fmt is not None and fmt in self._extractors:
                return fmt
        return self._sniff(data)

    def _sniff(self, data: bytes) -> DocumentFormat:
        head = data[:8]
        if data.lstrip().startswith(b"%PDF"):
            fmt = DocumentFormat.PDF
        elif head.startswith(b"PK"):
            fmt = _zip_format(data)
        elif data[:256].lstrip().lower().startswith((b"<!doctype html", b"<html", b"<?xml")) or b"<html" in data[:2048].lower():
            fmt = DocumentFormat.HTML
        elif _looks_like_csv(data):
            fmt = DocumentFormat.CSV
        else:
            fmt = DocumentFormat.TXT
        if fmt in self._extractors:
            return fmt
        if DocumentFormat.TXT in self._extractors:
            return DocumentFormat.TXT
        raise DocumentUnsupportedError(f"Unsupported or disabled document format: {fmt.value}")

    async def _extract(self, fmt: DocumentFormat, data: bytes) -> ExtractionResult:
        extractor = self._extractors.get(fmt)
        if extractor is None:
            raise DocumentUnsupportedError(f"No enabled extractor for format: {fmt.value}")
        return await extractor.extract(data)

    def _should_ocr(self, ocr_flag: bool | None, extracted_text: str) -> bool:
        if not (self._config.ocr_enabled or ocr_flag):
            return False
        if self._ocr.name == "local":
            return False
        return len(extracted_text.strip()) < self._config.ocr_min_text_length

    def _validate_size(self, data: bytes) -> None:
        if not data:
            raise DocumentValidationError("Empty document payload")
        if len(data) > self._config.max_document_bytes:
            raise DocumentValidationError("Document exceeds the maximum allowed size")

    def _to_read(self, document: Document) -> DocumentRead:
        extracted = _load_fields(document.extracted_json)
        return DocumentRead(
            id=document.id,
            user_id=document.user_id,
            doc_type=DocumentType(document.doc_type),
            file_format=DocumentFormat(document.file_format),
            filename=document.filename,
            raw_mime=document.raw_mime,
            raw_size_bytes=document.raw_size_bytes,
            sha256=document.sha256,
            pages=document.pages,
            ocr_used=document.ocr_used,
            confidence=document.confidence,
            text=document.text,
            extracted=extracted,
            metadata=_load_json(document.metadata_json),
            created_at=document.created_at,
            updated_at=document.updated_at,
        )

    def _to_summary(self, document: Document) -> DocumentSummary:
        extracted = _load_fields(document.extracted_json)
        return DocumentSummary(
            id=document.id,
            user_id=document.user_id,
            doc_type=DocumentType(document.doc_type),
            file_format=DocumentFormat(document.file_format),
            filename=document.filename,
            raw_size_bytes=document.raw_size_bytes,
            sha256=document.sha256,
            pages=document.pages,
            ocr_used=document.ocr_used,
            confidence=document.confidence,
            extracted=extracted,
            created_at=document.created_at,
            updated_at=document.updated_at,
        )


# ── Module helpers ──────────────────────────────────────────────────────


def _zip_format(data: bytes) -> DocumentFormat:
    import io
    import zipfile

    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = archive.namelist()
    except Exception:
        return DocumentFormat.TXT
    if "word/document.xml" in names:
        return DocumentFormat.DOCX
    if any(n.startswith("xl/worksheets/") for n in names):
        return DocumentFormat.XLSX
    return DocumentFormat.TXT


def _looks_like_csv(data: bytes) -> bool:
    try:
        head = data[:4096].decode("utf-8", errors="replace")
    except Exception:
        return False
    lines = [ln for ln in head.splitlines()[:5] if ln.strip()]
    if len(lines) < 2:
        return False
    return all(ln.count(",") >= 1 for ln in lines[1:])


def _combine_text(extracted: str, ocr_text: str) -> str:
    extracted = extracted.strip()
    ocr_text = ocr_text.strip()
    if not ocr_text:
        return extracted
    if extracted:
        return f"{extracted}\n{ocr_text}"
    return ocr_text


def _dump(value: Any) -> str:
    return json.dumps(value)


def _load_json(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return {}


def _load_fields(raw: str | None) -> ExtractedFields:
    return ExtractedFields.model_validate(_load_json(raw))
