"""Exception hierarchy for the document intelligence system.

Follows the error-hierarchy convention used by the marketplace, memory and event
layers: a small base class plus specific subtypes so callers can handle known
failures while a generic `DocumentError` catches everything else.
"""

from __future__ import annotations


class DocumentError(Exception):
    """Base error for all document-intelligence failures."""


class DocumentNotFoundError(DocumentError):
    """Raised when a requested document record does not exist."""

    def __init__(self, document_id: object) -> None:
        self.document_id = document_id
        super().__init__(f"Document not found: {document_id}")


class DocumentValidationError(DocumentError):
    """Raised when a document payload, format or config is invalid."""


class DocumentUnsupportedError(DocumentValidationError):
    """Raised when a document format is not supported by this deployment."""


class DocumentExtractionError(DocumentError):
    """Raised when text/field extraction fails for a document."""
