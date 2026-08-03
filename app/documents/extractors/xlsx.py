"""XLSX (Excel) extractor.

An `.xlsx` file is a ZIP archive. Text lives in ``xl/sharedStrings.xml`` (shared
string table) and the sheet cell references point into it. This stdlib-only
implementation reads every sheet and renders each row as a text line, surfacing
labelled columns for field scanning. Only inline/shared strings are read
(numeric/formula cells appear empty) — a real Excel library can be plugged in
via the `[documents]` extra for full fidelity.
"""

from __future__ import annotations

import io
import zipfile
from collections import defaultdict
from xml.etree import ElementTree as ET

from app.documents.extractors.base import ExtractionResult, Extractor
from app.documents.models import DocumentFormat

_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


class XLSXExtractor(Extractor):
    """Extractor for Excel .xlsx workbooks."""

    format = DocumentFormat.XLSX

    async def extract(self, data: bytes) -> ExtractionResult:
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                names = archive.namelist()
                shared = _read_shared_strings(archive, names)
                sheet_files = _sheet_files(names)
                rendered_lines: list[str] = []
                tables: list[list[list[str]]] = []
                for sheet_file in sheet_files:
                    rows = _read_sheet(archive, sheet_file, shared)
                    for row in rows:
                        if any(cell.strip() for cell in row):
                            rendered_lines.append("\t".join(cell for cell in row))
                    if rows:
                        tables.append(rows)
        except Exception:
            return ExtractionResult(format=self.format, pages=None)

        return ExtractionResult(
            format=self.format,
            text="\n".join(rendered_lines),
            tables=tables,
            pages=1,
        )


def _read_shared_strings(archive: zipfile.ZipFile, names: list[str]) -> list[str]:
    path = "xl/sharedStrings.xml"
    if path not in names:
        return []
    try:
        root = ET.fromstring(archive.read(path))
    except ET.ParseError:
        return []
    strings: list[str] = []
    for si in root.findall(f"{_NS}si"):
        strings.append("".join(t.text or "" for t in si.iter(f"{_NS}t")))
    return strings


def _sheet_files(names: list[str]) -> list[str]:
    """Return worksheet XML paths in numeric order."""
    files = [
        n
        for n in names
        if n.startswith("xl/worksheets/") and n.endswith(".xml")
    ]
    files.sort(key=_sheet_number)
    return files


def _sheet_number(path: str) -> int:
    base = path.rsplit("/", 1)[-1].replace(".xml", "")
    digits = "".join(ch for ch in base if ch.isdigit())
    return int(digits) if digits else 0


def _read_sheet(archive: zipfile.ZipFile, sheet_file: str, shared: list[str]) -> list[list[str]]:
    try:
        root = ET.fromstring(archive.read(sheet_file))
    except (KeyError, ET.ParseError):
        return []

    # Cells -> text by coordinate, rows -> sorted cell text.
    cell_map: dict[int, dict[int, str]] = defaultdict(dict)
    max_col = 0
    max_row = 0
    for cell in root.iter(f"{_NS}c"):
        ref = cell.attrib.get("r", "")
        t = cell.attrib.get("t", "")
        col, row = _parse_ref(ref)
        if row is None:
            continue
        value = _cell_value(cell, t, shared)
        if value is None:
            continue
        cell_map[row][col] = value
        max_col = max(max_col, col)
        max_row = max(max_row, row)

    rows: list[list[str]] = []
    for r in range(1, max_row + 1):
        row_cells = cell_map.get(r, {})
        rows.append([row_cells.get(c, "") for c in range(0, max_col + 1)])
    return rows


def _cell_value(cell: ET.Element, t: str, shared: list[str]) -> str | None:
    inline = cell.find(f"{_NS}v")
    if inline is None or not inline.text:
        return None
    if t == "s":
        try:
            idx = int(inline.text)
            return shared[idx] if idx < len(shared) else None
        except (ValueError, IndexError):
            return None
    if t == "inlineStr":
        return "".join(node.text or "" for node in cell.iter(f"{_NS}t"))
    return inline.text


def _parse_ref(ref: str) -> tuple[int, int | None]:
    """Parse an A1-style cell reference into (col, row)."""
    import re

    match = re.match(r"([A-Z]+)(\d+)", ref)
    if not match:
        return 0, None
    col = 0
    for ch in match.group(1):
        col = col * 26 + (ord(ch) - ord("A") + 1)
    return col - 1, int(match.group(2))
