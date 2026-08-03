"""Plain-text extractor (txt / markdown / json).

Handles UTF-8 and common encodings via a lenient decode, and pulls table-shaped
rows out of CSV-like plain text as a bonus. JSON is surfaced as pretty text so
the same downstream pipeline (field scanning + search) applies uniformly.
"""

from __future__ import annotations

import csv
import io
import json

from app.documents.extractors.base import ExtractionResult, Extractor
from app.documents.models import DocumentFormat


class PlainTextExtractor(Extractor):
    """Extractor for txt, markdown and json documents."""

    format = DocumentFormat.TXT

    def __init__(self, format: DocumentFormat = DocumentFormat.TXT) -> None:
        self.format = format

    async def extract(self, data: bytes) -> ExtractionResult:
        text = _decode(data)
        tables: list[list[list[str]]] = []

        if self.format == DocumentFormat.JSON:
            try:
                obj = json.loads(text)
                text = json.dumps(obj, indent=2, ensure_ascii=False)
            except (ValueError, TypeError):
                pass

        # CSV-shaped rows embedded in plain text.
        if _looks_like_csv(text):
            try:
                rows = list(csv.reader(io.StringIO(text)))
                if len(rows) >= 2 and rows[0]:
                    tables.append(rows)
            except Exception:
                pass

        return ExtractionResult(
            format=self.format,
            text=text,
            tables=tables,
            pages=1,
        )


def _decode(data: bytes) -> str:
    for encoding in ("utf-8", "utf-16", "latin-1"):
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, ValueError):
            continue
    return data.decode("utf-8", errors="replace")


def _looks_like_csv(text: str) -> bool:
    head = "\n".join(text.splitlines()[:5])
    lines = [ln for ln in head.splitlines() if ln.strip()]
    if len(lines) < 2:
        return False
    sample = lines[0]
    return sample.count(",") >= 1 and all(ln.count(",") == sample.count(",") for ln in lines[1:])
