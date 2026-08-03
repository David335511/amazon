"""Benchmark tests for the document intelligence system.

Exercises the full pipeline: format detection, per-format extractors (txt,
CSV, HTML, DOCX, XLSX, PDF), field extraction (UPC/EAN/GTIN, weight,
dimensions, case quantity, model number, manufacturer, part number, warranty),
OCR fallback, persistence (raw + parsed), idempotent ingestion, full-text and
field search, and the HTTP API. Sample documents are generated in-test with the
stdlib, so no third-party document/OCR library is required.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.documents import (
    DocumentConfig,
    DocumentFormat,
    DocumentManager,
    DocumentRepository,
    DocumentType,
    LocalOCRProvider,
    OCRProvider,
    build_extractors,
    extract_barcodes,
    extract_fields,
)
from app.documents.errors import DocumentNotFoundError

# ──────────────────────────────────────────────────────────────
# Sample documents (built in-test)
# ──────────────────────────────────────────────────────────────


def spec_text() -> str:
    return """Acme Titanium Power Drill 2000
Manufacturer: Acme Tools
Model Number: TD-1000X
Part Number: P/N 4477-AB2
UPC: 012345678905
EAN: 4006381333931
Weight: 3.5 kg
Dimensions: 25 x 18 x 12 cm
Case Quantity: 24
Warranty: 2-year limited warranty
The Acme Titanium Power Drill 2000 is a high-performance unit.
"""


def invoice_text() -> str:
    return """INVOICE #INV-9981
Billed to: Retail Warehouse LLC
Acme Tools
Model: TD-1000X
Part: 4477-AB2
UPC 012345678905
Units: 6
Unit Price: $89.00
Subtotal: $534.00
Tax: $42.72
Total: $576.72
"""


def html_spec() -> str:
    return """<!DOCTYPE html>
<html><head><title>Acme Spec</title></head>
<body>
<h1>Acme TurboFan 500</h1>
<p>Manufacturer: Acme Aero</p>
<table>
  <tr><td>Model</td><td>TF-500X</td></tr>
  <tr><td>UPC</td><td>012345678905</td></tr>
  <tr><td>Weight</td><td>1.2 kg</td></tr>
  <tr><td>Warranty</td><td>3-year</td></tr>
</table>
<script>var hidden = true;</script>
</body></html>
"""


def csv_catalog() -> str:
    return "sku,model,upc,weight\nSKU1,CC-99,012345678905,0.5 kg\nSKU2,CC-98,4006381333931,1.0 kg\n"


def make_docx() -> bytes:
    """Build a minimal .docx (ZIP with word/document.xml)."""
    import io
    import zipfile

    xml = (
        b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        b"<w:body>"
        b"<w:p><w:r><w:t>Acme PowerBlender</w:t></w:r></w:p>"
        b"<w:p><w:r><w:t>Model Number: PB-700</w:t></w:r></w:p>"
        b"<w:p><w:r><w:t>Manufacturer: Acme</w:t></w:r></w:p>"
        b"<w:p><w:r><w:t>Weight: 2.0 kg</w:t></w:r></w:p>"
        b"</w:body></w:document>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", xml)
    return buf.getvalue()


def make_xlsx() -> bytes:
    """Build a minimal .xlsx (ZIP with sharedStrings + one sheet)."""
    import io
    import zipfile

    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    shared = (
        f'<?xml version="1.0"?><sst xmlns="{ns}" count="4" uniqueCount="4">'
        "<si><t>Model</t></si>"
        "<si><t>TD-9000</t></si>"
        "<si><t>Weight</t></si>"
        "<si><t>1.2 kg</t></si>"
        "</sst>"
    ).encode()
    sheet = (
        f'<?xml version="1.0"?><worksheet xmlns="{ns}"><sheetData>'
        '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>'
        '<row r="2"><c r="A2" t="s"><v>2</v></c><c r="B2" t="s"><v>3</v></c></row>'
        "</sheetData></worksheet>"
    ).encode()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/sharedStrings.xml", shared)
        archive.writestr("xl/worksheets/sheet1.xml", sheet)
    return buf.getvalue()


def make_pdf() -> bytes:
    """Build a minimal text PDF with a single content stream."""
    stream = b"BT\n/F1 12 Tf\n(Acme DataSheets) Tj\n(Model: DS-42) Tj\nET"
    length = len(stream)
    body = f"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R >>
endobj
4 0 obj
<< /Length {length} >>
stream
""".encode() + stream + b"\nendstream\nendobj\n"
    return body + b"trailer << /Root 1 0 R >>\n%%EOF\n"


def tiny_text() -> bytes:
    return b"tiny"


# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────


def make_manager(db_session) -> DocumentManager:
    cfg = DocumentConfig()
    return DocumentManager(
        DocumentRepository(db_session),
        config=cfg,
        extractors=build_extractors(cfg),
        ocr_provider=LocalOCRProvider(),
    )


# ──────────────────────────────────────────────────────────────
# Field extraction
# ──────────────────────────────────────────────────────────────


class TestFieldExtraction:
    def test_extracts_all_fields_from_spec(self) -> None:
        fields = extract_fields(spec_text())
        assert "012345678905" in fields.upc
        assert "4006381333931" in fields.ean
        assert "012345678905" in fields.gtin
        assert any("3.5 kg" in w for w in fields.weight)
        assert any("25 x 18 x 12 cm" in d for d in fields.dimensions)
        assert any(c == "24" for c in fields.case_quantity)
        assert any("TD-1000X" in m for m in fields.model_number)
        assert any("Acme" in m for m in fields.manufacturer)
        assert any("4477-AB2" in p for p in fields.part_number)
        assert any("2-year" in w for w in fields.warranty)
        assert fields.confidence > 0.5

    def test_barcode_checksum_rejects_invalid(self) -> None:
        upc, _ean, _gtin = extract_barcodes("Invalid UPC 012345678901 here")
        # 012345678901 is NOT a valid UPC checksum.
        assert "012345678901" not in upc
        assert upc == []

    def test_empty_text_gives_empty_fields(self) -> None:
        fields = extract_fields("no structure here")
        assert fields.upc == []
        assert fields.populated_count() == 0
        assert fields.confidence == 0.0


# ──────────────────────────────────────────────────────────────
# Format detection
# ──────────────────────────────────────────────────────────────


class TestFormatDetection:
    @pytest.mark.parametrize(
        ("data", "expected"),
        [
            (spec_text().encode("utf-8"), DocumentFormat.TXT),
            (csv_catalog().encode("utf-8"), DocumentFormat.CSV),
            (html_spec().encode("utf-8"), DocumentFormat.HTML),
            (make_docx(), DocumentFormat.DOCX),
            (make_xlsx(), DocumentFormat.XLSX),
            (make_pdf(), DocumentFormat.PDF),
        ],
    )
    def test_sniffs_magic_bytes(self, db_session, data: bytes, expected: DocumentFormat) -> None:
        manager = make_manager(db_session)
        assert manager.detect_format(data) == expected

    def test_filename_takes_precedence(self, db_session) -> None:
        manager = make_manager(db_session)
        assert manager.detect_format(b"anything", filename="report.pdf") == DocumentFormat.PDF


# ──────────────────────────────────────────────────────────────
# Parsing
# ──────────────────────────────────────────────────────────────


class TestParsing:
    async def test_parse_txt(self, db_session) -> None:
        manager = make_manager(db_session)
        parsed = await manager.parse(spec_text().encode("utf-8"), filename="spec.txt")
        assert parsed.file_format == DocumentFormat.TXT
        assert parsed.pages == 1
        assert parsed.text
        assert any("TD-1000X" in m for m in parsed.fields.model_number)

    async def test_parse_docx(self, db_session) -> None:
        manager = make_manager(db_session)
        parsed = await manager.parse(make_docx(), filename="manual.docx")
        assert parsed.file_format == DocumentFormat.DOCX
        assert any("PB-700" in m for m in parsed.fields.model_number)
        assert any("Acme" in m for m in parsed.fields.manufacturer)

    async def test_parse_xlsx(self, db_session) -> None:
        manager = make_manager(db_session)
        parsed = await manager.parse(make_xlsx(), filename="spec.xlsx")
        assert parsed.file_format == DocumentFormat.XLSX
        assert any("TD-9000" in m for m in parsed.fields.model_number)
        assert any("1.2 kg" in w for w in parsed.fields.weight)

    async def test_parse_html(self, db_session) -> None:
        manager = make_manager(db_session)
        parsed = await manager.parse(html_spec().encode("utf-8"), filename="spec.html")
        assert parsed.file_format == DocumentFormat.HTML
        assert any("TF-500X" in m for m in parsed.fields.model_number)
        assert any("3-year" in w for w in parsed.fields.warranty)

    async def test_parse_csv(self, db_session) -> None:
        manager = make_manager(db_session)
        parsed = await manager.parse(csv_catalog().encode("utf-8"), filename="catalog.csv")
        assert parsed.file_format == DocumentFormat.CSV
        assert "012345678905" in parsed.fields.upc

    async def test_parse_pdf(self, db_session) -> None:
        manager = make_manager(db_session)
        parsed = await manager.parse(make_pdf(), filename="sheet.pdf")
        assert parsed.file_format == DocumentFormat.PDF
        assert parsed.pages == 1
        assert any("DS-42" in m for m in parsed.fields.model_number)

    async def test_ocr_fallback_on_tiny_text(self, db_session) -> None:
        class FakeOCR(OCRProvider):
            name = "fake"

            async def ocr(self, data: bytes, *, mime: str | None = None) -> str:  # noqa: ARG002
                return "Model: OC-777 Weight: 4.5 kg"

        cfg = DocumentConfig()
        manager = DocumentManager(
            DocumentRepository(db_session),
            config=cfg,
            extractors=build_extractors(cfg),
            ocr_provider=FakeOCR(),
        )
        parsed = await manager.parse(tiny_text(), filename="scan.txt", ocr=True)
        assert parsed.ocr_used is True
        assert any("OC-777" in m for m in parsed.fields.model_number)


# ──────────────────────────────────────────────────────────────
# Persistence & idempotency
# ──────────────────────────────────────────────────────────────


class TestStorage:
    async def test_ingest_roundtrip_raw_and_parsed(self, db_session) -> None:
        manager = make_manager(db_session)
        record = await manager.ingest(
            spec_text().encode("utf-8"),
            filename="spec.txt",
            mime="text/plain",
            doc_type=DocumentType.SPECIFICATION_SHEET,
        )
        assert record.doc_type == DocumentType.SPECIFICATION_SHEET
        assert record.file_format == DocumentFormat.TXT
        assert record.raw_size_bytes == len(spec_text().encode("utf-8"))
        assert record.text
        assert "012345678905" in record.extracted.upc
        assert len(record.sha256) == 64

        # Raw bytes round-trip.
        raw, mime = await manager.raw(record.id)
        assert raw == spec_text().encode("utf-8")
        assert mime == "text/plain"

    async def test_ingest_is_idempotent_by_sha256(self, db_session) -> None:
        manager = make_manager(db_session)
        data = spec_text().encode("utf-8")
        first = await manager.ingest(data, filename="a.txt")
        second = await manager.ingest(data, filename="b.txt")
        assert first.id == second.id
        assert first.filename == "a.txt"

    async def test_get_and_delete(self, db_session) -> None:
        manager = make_manager(db_session)
        record = await manager.ingest(invoice_text().encode("utf-8"), filename="inv.txt")
        fetched = await manager.get(record.id)
        assert fetched.id == record.id
        assert await manager.delete(record.id) is True
        with pytest.raises(DocumentNotFoundError):
            await manager.get(record.id)


# ──────────────────────────────────────────────────────────────
# Search
# ──────────────────────────────────────────────────────────────


class TestSearch:
    async def _seed(self, db_session) -> DocumentManager:
        manager = make_manager(db_session)
        await manager.ingest(spec_text().encode("utf-8"), filename="spec.txt")
        await manager.ingest(invoice_text().encode("utf-8"), filename="inv.txt")
        return manager

    async def test_fulltext_search(self, db_session) -> None:
        manager = await self._seed(db_session)
        result = await manager.search("Titanium")
        assert result.total == 1
        assert result.items[0].filename == "spec.txt"

    async def test_search_field_by_upc(self, db_session) -> None:
        manager = await self._seed(db_session)
        result = await manager.search_field("upc", "012345678905")
        assert result.total == 2  # appears in both spec and invoice

    async def test_search_field_by_model(self, db_session) -> None:
        manager = await self._seed(db_session)
        result = await manager.search_field("model_number", "TD-1000X")
        assert result.total == 2  # spec and invoice both reference this model

    async def test_search_field_unknown_returns_empty(self, db_session) -> None:
        manager = await self._seed(db_session)
        assert (await manager.search_field("bogus", "x")).total == 0

    async def test_list_filter_by_type(self, db_session) -> None:
        manager = await self._seed(db_session)
        await manager.ingest(html_spec().encode("utf-8"), filename="s.html", doc_type=DocumentType.SPECIFICATION_SHEET)
        all_docs = await manager.list()
        assert all_docs.total >= 3
        specs = await manager.list(doc_type=DocumentType.SPECIFICATION_SHEET)
        assert specs.total == 1
        assert specs.items[0].doc_type == DocumentType.SPECIFICATION_SHEET


# ──────────────────────────────────────────────────────────────
# Capabilities & stats
# ──────────────────────────────────────────────────────────────


class TestIntrospection:
    async def test_capabilities(self, db_session) -> None:
        manager = make_manager(db_session)
        caps = manager.capabilities()
        assert DocumentFormat.PDF in caps.formats
        assert DocumentFormat.DOCX in caps.formats
        assert caps.ocr_available is False
        assert caps.ocr_provider == "local"

    async def test_stats(self, db_session) -> None:
        manager = make_manager(db_session)
        await manager.ingest(spec_text().encode("utf-8"), filename="spec.txt")
        await manager.ingest(invoice_text().encode("utf-8"), filename="inv.txt")
        stats = await manager.stats()
        assert stats.total == 2
        assert stats.by_format.get("txt") == 2
        assert stats.total_bytes > 0


# ──────────────────────────────────────────────────────────────
# HTTP API
# ──────────────────────────────────────────────────────────────


class TestAPI:
    async def test_ingest_endpoint(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/documents/ingest",
            files={"file": ("spec.txt", spec_text().encode("utf-8"), "text/plain")},
            data={"doc_type": "specification_sheet"},
        )
        assert response.status_code == 201
        payload = response.json()
        assert payload["file_format"] == "txt"
        assert payload["doc_type"] == "specification_sheet"
        assert payload["extracted"]["upc"] == ["012345678905"]
        assert len(payload["id"]) == 36  # uuid4

    async def test_parse_endpoint(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/documents/parse",
            files={"file": ("spec.txt", spec_text().encode("utf-8"), "text/plain")},
        )
        assert response.status_code == 200
        assert response.json()["fields"]["model_number"] == ["TD-1000X"]

    async def test_search_endpoint(self, client: AsyncClient) -> None:
        await client.post(
            "/api/v1/documents/ingest",
            files={"file": ("spec.txt", spec_text().encode("utf-8"), "text/plain")},
        )
        response = await client.get("/api/v1/documents/search", params={"q": "Titanium"})
        assert response.status_code == 200
        assert response.json()["total"] == 1

    async def test_search_fields_endpoint(self, client: AsyncClient) -> None:
        await client.post(
            "/api/v1/documents/ingest",
            files={"file": ("inv.txt", invoice_text().encode("utf-8"), "text/plain")},
        )
        response = await client.get(
            "/api/v1/documents/search/fields",
            params={"field": "upc", "value": "012345678905"},
        )
        assert response.status_code == 200
        assert response.json()["total"] == 1

    async def test_get_and_raw_endpoints(self, client: AsyncClient) -> None:
        created = await client.post(
            "/api/v1/documents/ingest",
            files={"file": ("spec.txt", spec_text().encode("utf-8"), "text/plain")},
        )
        doc_id = created.json()["id"]

        got = await client.get(f"/api/v1/documents/{doc_id}")
        assert got.status_code == 200
        assert got.json()["filename"] == "spec.txt"

        raw = await client.get(f"/api/v1/documents/{doc_id}/raw")
        assert raw.status_code == 200
        assert raw.content == spec_text().encode("utf-8")

    async def test_delete_endpoint(self, client: AsyncClient) -> None:
        created = await client.post(
            "/api/v1/documents/ingest",
            files={"file": ("spec.txt", spec_text().encode("utf-8"), "text/plain")},
        )
        doc_id = created.json()["id"]
        response = await client.delete(f"/api/v1/documents/{doc_id}")
        assert response.status_code == 204
        assert (await client.get(f"/api/v1/documents/{doc_id}")).status_code == 404

    async def test_capabilities_endpoint(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/documents/capabilities")
        assert response.status_code == 200
        assert response.json()["ocr_provider"] == "local"

    async def test_parse_unknown_extension(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/documents/parse",
            files={"file": ("x.bin", spec_text().encode("utf-8"), "application/octet-stream")},
        )
        assert response.status_code == 200  # falls back to content sniffing -> txt
