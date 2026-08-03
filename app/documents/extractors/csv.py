"""CSV extractor.

Uses the stdlib `csv` module to parse tabular data. The table is surfaced both
as extracted text (rendered rows) and as structured tables, so field scanning
finds labels like ``UPC`` regardless of column position.
"""

from __future__ import annotations

import csv
import io

from app.documents.extractors.base import ExtractionResult, Extractor
from app.documents.models import DocumentFormat


class CSVExtractor(Extractor):
    """Extractor for comma-separated-value documents."""

    format = DocumentFormat.CSV

    async def extract(self, data: bytes) -> ExtractionResult:
        text = _decode(data)
        try:
            rows = list(csv.reader(io.StringIO(text)))
        except Exception:
            return ExtractionResult(format=self.format, text=text, tables=[], pages=1)

        rows = _clean(rows)
        # Render a readable text form: "col1, col2 ..." per row.
        rendered = "\n".join(", ".join(cell for cell in row) for row in rows)
        return ExtractionResult(
            format=self.format,
            text=rendered or text,
            tables=[rows] if rows else [],
            pages=1,
        )


def _decode(data: bytes) -> str:
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, ValueError):
            continue
    return data.decode("utf-8", errors="replace")


def _clean(rows: list[list[str]]) -> list[list[str]]:
    out: list[list[str]] = []
    for row in rows:
        if not row or all(not cell.strip() for cell in row):
            continue
        out.append([cell.strip() for cell in row])
    return out
