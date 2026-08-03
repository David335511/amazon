"""PDF extractor.

A stdlib-only text-stream parser that handles the common case of "text PDFs"
whose content streams contain ``(...) Tj`` / ``[...] TJ`` operators (the output
of most report/word/label generators). It is intentionally not a full PDF
renderer:

- Objects are located by regex, byte ranges are decompressed (FlateDecode) and
  string literals are unescaped.
- Scanned/image-only PDFs yield little text; the `DocumentManager` then falls
  back to OCR (see `app.documents.ocr`) when OCR is enabled.

For full-fidelity parsing (vector text layout, encodings), install the optional
`[documents]` extra (pypdf) and it is used automatically via the same seam.
"""

from __future__ import annotations

import re
import zlib

from app.documents.extractors.base import ExtractionResult, Extractor
from app.documents.models import DocumentFormat

_OBJ_RE = re.compile(rb"(\d+)\s+(\d+)\s+obj\b(.*?)endobj", re.S)
_STREAM_RE = re.compile(rb"stream\r?\n(.*?)\r?\nendstream", re.S)
_TEXT_STRING_RE = re.compile(rb"\((?:[^()\\]|\\.)*\)")
_OCTAL_ESCAPES = {"0", "1", "2", "3", "4", "5", "6", "7"}


class PDFExtractor(Extractor):
    """Extractor for PDF documents."""

    format = DocumentFormat.PDF

    async def extract(self, data: bytes) -> ExtractionResult:
        if not data.lstrip().startswith(b"%PDF"):
            return ExtractionResult(format=self.format, pages=None)

        contents: list[bytes] = []
        for _, _, body in _OBJ_RE.findall(data):
            stream = _find_stream(body)
            if stream is None:
                continue
            contents.append(_decompress(stream))
            if b"/Type /Page" in body or b"/Type/Page" in body:
                pass  # page objects are discovered via page tree; kept simple

        text_parts: list[str] = []
        for content in contents:
            text_parts.append(_extract_text_operators(content))

        text = "\n".join(part for part in text_parts if part)
        pages = _count_pages(data)
        return ExtractionResult(format=self.format, text=text, pages=pages or None)


def _find_stream(body: bytes) -> bytes | None:
    match = _STREAM_RE.search(body)
    if not match:
        # Handle a stream that ends at endobj without trailing newline.
        stripped = body
        idx = stripped.find(b"stream")
        if idx == -1:
            return None
        tail = stripped[idx + len(b"stream"):]
        if b"endstream" in tail:
            return tail[: tail.find(b"endstream")]
        return None
    return match.group(1)


def _decompress(chunk: bytes) -> bytes:
    # Try FlateDecode; fall back to the raw bytes (some streams are uncompressed).
    try:
        return zlib.decompress(chunk)
    except Exception:
        return chunk


def _extract_text_operators(content: bytes) -> str:
    parts: list[str] = []
    for match in _TEXT_STRING_RE.finditer(content):
        parts.append(_unescape_pdf_string(match.group(0)))
    # Heuristic: only keep strings that look like actual text (>= 1 printable).
    kept = [p for p in parts if p and any(ch.isalnum() for ch in p)]
    return " ".join(kept)


def _unescape_pdf_string(raw: bytes) -> str:
    inner = raw[1:-1]
    out: list[str] = []
    i = 0
    n = len(inner)
    while i < n:
        byte = inner[i]
        if byte != 0x5C:  # backslash
            out.append(chr(byte))
            i += 1
            continue
        # Backslash escape.
        i += 1
        if i >= n:
            break
        c = inner[i]
        if c in (0x6E, 0x72, 0x74, 0x62, 0x66):  # n r t b f
            out.append({0x6E: "\n", 0x72: "\r", 0x74: "\t", 0x62: "\b", 0x66: "\f"}[c])
            i += 1
        elif chr(c) in _OCTAL_ESCAPES:
            digits = bytearray()
            while i < n and chr(inner[i]) in _OCTAL_ESCAPES and len(digits) < 3:
                digits.append(inner[i])
                i += 1
            out.append(chr(int(digits.decode(), 8)))
        elif c in (0x28, 0x29, 0x5C):  # ( ) \\
            out.append(chr(c))
            i += 1
        else:
            out.append(chr(c))
            i += 1
    return "".join(out)


def _count_pages(data: bytes) -> int:
    """Approximate the page count by counting /Type /Page objects."""
    return len(re.findall(rb"/Type\s*/Page(?![s])", data))
