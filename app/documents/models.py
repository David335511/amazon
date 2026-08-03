"""ORM model and enums for the document intelligence system.

Design decisions:
- Documents are stored in their OWN table (`documents`), completely separate
  from product/order data. A row holds BOTH the raw bytes (`raw_blob`) and the
  parsed representation (`text` + `extracted_json` + `metadata_json`), so a
  document is fully self-contained and reproducible.
- `DocumentType` classifies the *kind* of document (manual, spec sheet,
  invoice, ...). `DocumentFormat` records the physical container.
- `sha256` is a content hash used for idempotent ingestion (re-uploading the
  same bytes returns the existing row instead of duplicating).
- `extracted_json` is the JSON-serialized `ExtractedFields` map (UPC, weight,
  dimensions, model number, ...); `metadata_json` holds document-level metadata
  (title, author, page count, ...). Both are plain JSON text so the schema needs
  no JSON/vector extension and works on any Postgres.
"""

from __future__ import annotations

from enum import StrEnum

from sqlalchemy import Boolean, Float, Integer, LargeBinary, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.models.base import Base, TimestampMixin, UUIDMixin


class DocumentType(StrEnum):
    """The kind of document the platform understands."""

    PRODUCT_MANUAL = "product_manual"
    SPECIFICATION_SHEET = "specification_sheet"
    INVOICE = "invoice"
    OTHER = "other"


class DocumentFormat(StrEnum):
    """Physical container formats the system can parse."""

    PDF = "pdf"
    HTML = "html"
    DOCX = "docx"
    CSV = "csv"
    XLSX = "xlsx"
    TXT = "txt"
    MARKDOWN = "md"
    JSON = "json"


class Document(Base, UUIDMixin, TimestampMixin):
    """A single stored document (raw + parsed)."""

    __tablename__ = "documents"

    user_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, index=True,
        comment="Owning user (None = platform-global document)",
    )
    doc_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default=DocumentType.OTHER.value, index=True,
        comment="One of DocumentType values",
    )
    file_format: Mapped[str] = mapped_column(
        String(16), nullable=False, index=True,
        comment="One of DocumentFormat values",
    )
    filename: Mapped[str | None] = mapped_column(String(500), nullable=True)
    raw_mime: Mapped[str | None] = mapped_column(String(128), nullable=True)
    raw_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    sha256: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True,
        comment="Content hash; enables idempotent ingestion",
    )

    # Raw document bytes (the original file, byte-for-byte).
    raw_blob: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)

    # Parsed representation.
    text: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="Full extracted text; used for full-text search",
    )
    extracted_json: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="JSON-serialized ExtractedFields (UPC, weight, dimensions, ...)",
    )
    metadata_json: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="JSON-serialized document metadata (title, pages, author, ...)",
    )

    pages: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ocr_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    confidence: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0,
        comment="0..1 field-extraction confidence",
    )

    def __repr__(self) -> str:
        return f"<Document(id={self.id}, format={self.file_format}, type={self.doc_type})>"
