"""DOCX extractor.

A `.docx` file is a ZIP archive; the body lives in ``word/document.xml``. This
uses only the stdlib (``zipfile`` + ``xml.etree``) to pull paragraphs and
tables, with the standard namespace aliases. A real Office document produced by
Word/Google Docs opens reliably; corrupt files yield an empty result.
"""

from __future__ import annotations

import io
import zipfile
from xml.etree import ElementTree as ET

from app.documents.extractors.base import ExtractionResult, Extractor
from app.documents.models import DocumentFormat

_W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class DOCXExtractor(Extractor):
    """Extractor for Word .docx documents."""

    format = DocumentFormat.DOCX

    async def extract(self, data: bytes) -> ExtractionResult:
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                xml_bytes = archive.read("word/document.xml")
        except Exception:
            return ExtractionResult(format=self.format, pages=None)

        root = _parse_xml(xml_bytes)
        if root is None:
            return ExtractionResult(format=self.format, pages=None)

        paragraphs: list[str] = []
        tables: list[list[list[str]]] = []

        body = root.find(f"{_W_NS}body")
        if body is not None:
            _walk(body, paragraphs, tables)

        text = "\n".join(paragraphs)
        return ExtractionResult(
            format=self.format,
            text=text,
            tables=tables,
            pages=1,
        )


def _parse_xml(data: bytes) -> ET.Element | None:
    try:
        return ET.fromstring(data)
    except ET.ParseError:
        return None


def _walk(element: ET.Element, paragraphs: list[str], tables: list[list[list[str]]]) -> None:
    for child in element:
        tag = child.tag
        if tag == f"{_W_NS}p":
            paragraphs.append(_para_text(child))
        elif tag == f"{_W_NS}tbl":
            table = _table_text(child)
            if table:
                tables.append(table)
        else:
            _walk(child, paragraphs, tables)


def _para_text(paragraph: ET.Element) -> str:
    parts: list[str] = []
    for node in paragraph.iter():
        if node.tag == f"{_W_NS}t" and node.text:
            parts.append(node.text)
    return "".join(parts).strip()


def _table_text(table: ET.Element) -> list[list[str]]:
    rows: list[list[str]] = []
    for row in table.iter(f"{_W_NS}tr"):
        cells: list[str] = []
        for cell in row.iter(f"{_W_NS}tc"):
            cell_text = " ".join(
                p
                for p in ("".join(t.text or "" for t in para.iter(f"{_W_NS}t")) for para in cell.iter(f"{_W_NS}p"))
                if p.strip()
            )
            cells.append(cell_text.strip())
        if any(cells):
            rows.append(cells)
    return rows
