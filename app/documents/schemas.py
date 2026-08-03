"""Pydantic schemas for the document intelligence system API.

`ParsedDocument` is the pure in-memory result of parsing bytes. `ExtractedFields`
holds the structured commerce fields the system pulls out of a document. The
`DocumentRead` schema mirrors a persisted row but without the raw blob (which is
served separately via the `/{id}/raw` endpoint to keep list/search payloads
light).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.documents.models import DocumentFormat, DocumentType


class ExtractedFields(BaseModel):
    """Structured commerce fields extracted from a document.

    Each field holds a list of candidate values (a document can legitimately
    contain more than one), keeping order of discovery. Empty lists mean the
    field was not found.
    """

    upc: list[str] = Field(default_factory=list)
    ean: list[str] = Field(default_factory=list)
    gtin: list[str] = Field(default_factory=list)
    weight: list[str] = Field(default_factory=list)
    dimensions: list[str] = Field(default_factory=list)
    case_quantity: list[str] = Field(default_factory=list)
    model_number: list[str] = Field(default_factory=list)
    manufacturer: list[str] = Field(default_factory=list)
    part_number: list[str] = Field(default_factory=list)
    warranty: list[str] = Field(default_factory=list)

    # 0..1 confidence in the extraction, derived from how many fields matched.
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    def populated_count(self) -> int:
        """Number of field groups with at least one value."""
        return sum(1 for v in _field_groups(self) if v)


def _field_groups(fields: ExtractedFields) -> list[list[str]]:
    return [
        fields.upc,
        fields.ean,
        fields.gtin,
        fields.weight,
        fields.dimensions,
        fields.case_quantity,
        fields.model_number,
        fields.manufacturer,
        fields.part_number,
        fields.warranty,
    ]


class Table(BaseModel):
    """A tabular block extracted from a document (e.g. an invoice line table)."""

    headers: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)


class ParsedDocument(BaseModel):
    """The in-memory result of parsing a document's bytes."""

    file_format: DocumentFormat
    text: str = ""
    lines: list[str] = Field(default_factory=list)
    tables: list[Table] = Field(default_factory=list)
    pages: int | None = None
    fields: ExtractedFields = Field(default_factory=ExtractedFields)
    metadata: dict[str, Any] = Field(default_factory=dict)
    ocr_used: bool = False


class DocumentRead(BaseModel):
    """A stored document as returned by the API (raw bytes served separately)."""

    id: UUID
    user_id: str | None
    doc_type: DocumentType
    file_format: DocumentFormat
    filename: str | None
    raw_mime: str | None
    raw_size_bytes: int
    sha256: str
    pages: int | None
    ocr_used: bool
    confidence: float
    text: str | None
    extracted: ExtractedFields = Field(default_factory=ExtractedFields)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DocumentSummary(BaseModel):
    """A lightweight search/list item (no text body)."""

    id: UUID
    user_id: str | None
    doc_type: DocumentType
    file_format: DocumentFormat
    filename: str | None
    raw_size_bytes: int
    sha256: str
    pages: int | None
    ocr_used: bool
    confidence: float
    extracted: ExtractedFields = Field(default_factory=ExtractedFields)
    created_at: datetime
    updated_at: datetime


class DocumentList(BaseModel):
    """Paginated list response for search/list endpoints."""

    items: list[DocumentSummary]
    total: int


class DocumentStats(BaseModel):
    """Aggregate statistics over the document corpus."""

    total: int = 0
    by_type: dict[str, int] = Field(default_factory=dict)
    by_format: dict[str, int] = Field(default_factory=dict)
    total_bytes: int = 0
    ocr_documents: int = 0


class DocumentCapabilities(BaseModel):
    """Which formats / capabilities this deployment genuinely supports."""

    formats: list[DocumentFormat]
    ocr_provider: str
    ocr_available: bool
    max_document_bytes: int
