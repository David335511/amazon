"""Document intelligence API.

The router talks ONLY to `DocumentManager` (via DI); it contains no
document-domain logic itself. It exposes ingest, parse, list, search (full-text
and field-level), raw retrieval, stats and capabilities.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)

from app.core.dependencies import get_document_manager
from app.documents import (
    DocumentCapabilities,
    DocumentList,
    DocumentManager,
    DocumentRead,
    DocumentStats,
    DocumentType,
    ParsedDocument,
)
from app.documents.errors import DocumentNotFoundError, DocumentValidationError

router = APIRouter(prefix="/documents", tags=["documents"])

ManagerDep = Annotated[DocumentManager, Depends(get_document_manager)]

# Static routes (capabilities / stats / search) are declared before the dynamic
# `/{document_id}` route so path matching never swallows them.


@router.get("/capabilities", response_model=DocumentCapabilities)
async def capabilities(manager: ManagerDep) -> DocumentCapabilities:
    """Report which formats and OCR provider this deployment supports."""
    return manager.capabilities()


@router.get("/stats", response_model=DocumentStats)
async def stats(manager: ManagerDep) -> DocumentStats:
    """Aggregate statistics over the stored document corpus."""
    return await manager.stats()


@router.get("/search", response_model=DocumentList)
async def search(
    manager: ManagerDep,
    q: str = Query(min_length=1),
    doc_type: DocumentType | None = None,
    user_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> DocumentList:
    """Full-text search over extracted document text and fields."""
    return await manager.search(q, doc_type=doc_type, user_id=user_id, limit=limit, offset=offset)


@router.get("/search/fields", response_model=DocumentList)
async def search_fields(
    manager: ManagerDep,
    field: str = Query(pattern="^(upc|ean|gtin|weight|dimensions|case_quantity|model_number|manufacturer|part_number|warranty)$"),
    value: str = Query(min_length=1),
    doc_type: DocumentType | None = None,
    user_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> DocumentList:
    """Search documents by a specific extracted field (e.g. UPC, model number)."""
    return await manager.search_field(field, value, doc_type=doc_type, user_id=user_id, limit=limit)


@router.get("/", response_model=DocumentList)
async def list_documents(
    manager: ManagerDep,
    doc_type: DocumentType | None = None,
    format: str | None = Query(default=None, alias="format"),
    user_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> DocumentList:
    """List stored documents, optionally filtered by type/format."""
    file_format = _parse_format(format)
    return await manager.list(
        doc_type=doc_type,
        file_format=file_format,
        user_id=user_id,
        limit=limit,
        offset=offset,
    )


@router.post("/ingest", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
async def ingest(
    manager: ManagerDep,
    file: UploadFile = File(...),
    doc_type: DocumentType = Form(DocumentType.OTHER),
    ocr: bool = Form(False),
    user_id: str | None = Form(None),
) -> DocumentRead:
    """Parse and store a document (raw + parsed), deduplicating by content hash."""
    data = await _read_upload(file)
    try:
        return await manager.ingest(
            data,
            filename=file.filename,
            mime=file.content_type,
            doc_type=doc_type,
            ocr=ocr,
            user_id=user_id,
        )
    except DocumentValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.post("/parse", response_model=ParsedDocument)
async def parse(
    manager: ManagerDep,
    file: UploadFile = File(...),
    ocr: bool = Form(False),
) -> ParsedDocument:
    """Parse a document and return the extracted text + fields (not stored)."""
    data = await _read_upload(file)
    try:
        return await manager.parse(data, filename=file.filename, mime=file.content_type, ocr=ocr)
    except DocumentValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.get("/{document_id}", response_model=DocumentRead)
async def get_document(manager: ManagerDep, document_id: UUID) -> DocumentRead:
    """Return a stored document's parsed record (raw served separately)."""
    try:
        return await manager.get(document_id)
    except DocumentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/{document_id}/raw")
async def get_raw(manager: ManagerDep, document_id: UUID) -> Response:
    """Return the original raw document bytes."""
    try:
        raw_bytes, mime = await manager.raw(document_id)
    except DocumentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    media_type = mime or "application/octet-stream"
    return Response(content=raw_bytes, media_type=media_type)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(manager: ManagerDep, document_id: UUID) -> None:
    """Delete a stored document."""
    try:
        await manager.delete(document_id)
    except DocumentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


async def _read_upload(file: UploadFile) -> bytes:
    return await file.read()


def _parse_format(value: str | None):
    if value is None:
        return None
    from app.documents import DocumentFormat

    try:
        return DocumentFormat(value)
    except ValueError:
        return None
