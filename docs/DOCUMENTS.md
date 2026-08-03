# Document Intelligence System

Provider-independent document understanding for the Amazon AI Commerce
Platform. Ingests product manuals, specification sheets and invoices; extracts
structured commerce fields; stores **both** the raw document and the parsed
representation; and exposes full-text and field-level search.

**Everything runs on the Python standard library** — no required third-party
document/OCR dependency. Rich parsing (full PDF layout) and real OCR plug in
through provider seams.

---

## Pipeline

```
bytes ─► detect format ─► extractor (PDF/HTML/DOCX/CSV/XLSX/TXT)
                         └► OCR fallback (scanned/image-only)
        ─► field extraction ─► persist raw blob + parsed fields
        ─► full-text & field search
```

`DocumentManager` is the ONLY entry point. Parsing is deterministic and
**idempotent ingestion** is built in: re-uploading the same bytes (same
`sha256`) returns the existing row instead of duplicating.

---

## Formats supported

| Format | Local extractor | Notes |
|---|---|---|
| **PDF** | ✅ stdlib text-stream | reads `(...) Tj` / `[...] TJ` operators; `[documents]` extra adds pypdf |
| **HTML** | ✅ stdlib `html.parser` | visible text + `<table>` extraction (spec sheets are often HTML tables) |
| **DOCX** | ✅ stdlib ZIP+XML | `word/document.xml` paragraphs + tables |
| **CSV** | ✅ stdlib `csv` | tabular data surfaced as text + table |
| **XLSX** | ✅ stdlib ZIP+XML | `sharedStrings` + worksheet cells |
| **TXT / Markdown / JSON** | ✅ | lenient multi-encoding decode |

Format is resolved from the filename extension, then MIME type, then **magic
bytes** (so even an extension-less upload is handled).

---

## Fields extracted

| Field | Method |
|---|---|
| **UPC / EAN / GTIN** | regex over 12/13/14-digit codes with **checksum validation** |
| **Weight** | `3.5 kg`, `12 oz`, `2 lbs`, ... with canonical units |
| **Dimensions** | `25 x 18 x 12 cm` (L×W×H), `8.5 x 11 in`, ... |
| **Case quantity** | keyword context (`case of`, `units per case`, `per case`, ...) |
| **Model number** | keyword context + digit-bearing token fallback |
| **Manufacturer** | keyword context (`manufacturer:`, `brand`, `mfr`, ...) |
| **Part number** | keyword context (`part number`, `p/n`, `item #`, ...) |
| **Warranty** | keyword context (`warranty`, `2-year`, `limited lifetime`, ...) |

Every field returns a **list of candidate values** (a document can legitimately
contain more than one). A **confidence score** (0..1) reflects how many field
groups were populated.

---

## Storage: raw + parsed

A `documents` table row holds BOTH representations, so a document is fully
self-contained and reproducible:

```
documents
  raw_blob        original file bytes (byte-for-byte)
  sha256          content hash → idempotent ingestion
  text            full extracted text (search target)
  extracted_json  JSON ExtractedFields (UPC, weight, dimensions, ...)
  metadata_json   document metadata (title, pages, ...)
  pages, ocr_used, confidence, doc_type, file_format
```

List/search queries **defer loading `raw_blob`** so a large corpus stays cheap;
the raw bytes are served only by the explicit `/{id}/raw` endpoint.

---

## OCR

`OCRProvider` is the pluggable seam used as a **fallback when a document yields
too little text** (scanned/image-only PDFs). Its output feeds the exact same
field extractor.

| Provider | Config `ocr_provider` | Requires |
|---|---|---|
| `local` (default) | `local` | nothing (no-op) |
| `tesseract` | `tesseract` | `pip install '.[documents]'` (Pillow + pytesseract) |
| `http` | `http` | any remote OCR service (`http_base_url` / `http_api_key`) |

---

## API

All routes under `/api/v1/documents` (API-key auth when Phase 0 security is on).

| Endpoint | Method | Purpose |
|---|---|---|
| `/documents/ingest` | POST | upload + parse + store (raw + parsed), dedup by sha256 |
| `/documents/parse` | POST | parse and return fields/text **without storing** |
| `/documents/` | GET | list, filter by `doc_type` / `format` |
| `/documents/search?q=` | GET | full-text search over text + fields |
| `/documents/search/fields?field=&value=` | GET | search by a specific field (UPC, model, ...) |
| `/documents/{id}` | GET | parsed record |
| `/documents/{id}/raw` | GET | original raw bytes |
| `/documents/{id}` | DELETE | remove a document |
| `/documents/capabilities` | GET | supported formats + OCR provider |
| `/documents/stats` | GET | corpus statistics |

### Example: ingest

```
POST /api/v1/documents/ingest
Content-Type: multipart/form-data
  file       (spec_sheet.pdf)
  doc_type   specification_sheet
  ocr        true
```

Response `DocumentRead`:

```json
{
  "id": "…uuid…",
  "doc_type": "specification_sheet",
  "file_format": "pdf",
  "raw_size_bytes": 123456,
  "sha256": "…",
  "pages": 8,
  "confidence": 0.85,
  "text": "Acme … Model Number: TD-1000X …",
  "extracted": {
    "upc": ["012345678905"],
    "ean": ["4006381333931"],
    "weight": ["3.5 kg"],
    "dimensions": ["25 x 18 x 12 cm"],
    "case_quantity": ["24"],
    "model_number": ["TD-1000X"],
    "manufacturer": ["Acme"],
    "part_number": ["4477-AB2"],
    "warranty": ["2-year"]
  }
}
```

### Example: field search

```
GET /api/v1/documents/search/fields?field=model_number&value=TD-1000X
```

---

## Wiring

- **DI**: `get_document_manager()` in `app/core/dependencies.py` (repository per
  request + shared extractor map / OCR provider from `settings.documents`).
- **Config**: `config/<env>.yaml` → `documents:` block, validated into
  `DocumentConfig`. Per-format switches and the OCR provider are tunable there.
- **API**: `app/api/v1/documents.py`, registered in `app/api/v1/__init__.py`.
- **Migration**: `alembic/versions/0006_create_documents_tables.py` (head).

### Configuration (`documents:` block)

```yaml
documents:
  enabled: true
  max_document_bytes: 10485760     # 10 MB payload guardrail
  ocr_enabled: false               # fallback OCR
  ocr_provider: local              # local | tesseract | http
  ocr_min_text_length: 20          # run OCR when extracted text is shorter
  enable_pdf: true                 # per-format master switches
  enable_html: true
  enable_docx: true
  enable_csv: true
  enable_xlsx: true
  enable_text: true
```

---

## Production notes

- **Raw blob in Postgres** (`bytea`) works now; for a very large corpus, move
  `raw_blob` to object storage (S3/R2/GCS) and keep a path in the row. The
  schema and API are already structured so the raw surface is a seam.
- **Search** uses `ILIKE` on extracted text/fields (portable across Postgres and
  the sqlite test DB). For high-scale full-text search, add Postgres `tsvector`
  or a search service (Meilisearch/OpenSearch) over the same `text` column.
- **Encodings / locales**: field extraction is regex + keyword based. For
  localization, externalize keyword lists per locale.
- **Field confidence** is a simple populated-groups heuristic; tune the weights
  or hook in a classifier for higher-fidelity extraction.
- **Parsing is bounded** (`max_document_bytes`) and each extractor is safe on
  arbitrary input (a corrupt file yields an empty result, not an exception),
  so untrusted uploads are handled gracefully.
