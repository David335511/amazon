"""HTML extractor.

Uses the stdlib `html.parser` to strip markup and collect visible text, plus
`<table>` structures (spec sheets and invoices are frequently HTML tables). The
same extractor handles `.htm` and `.html`.
"""

from __future__ import annotations

from html.parser import HTMLParser

from app.documents.extractors.base import ExtractionResult, Extractor
from app.documents.models import DocumentFormat

_BLOCK_TAGS = {
    "p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr",
    "section", "article", "blockquote", "pre",
}
_SKIP_TAGS = {"script", "style", "head", "noscript"}


class _HTMLTextAndTables(HTMLParser):
    """Collect visible text and tabular structures from an HTML document."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0
        self._tables: list[list[list[str]]] = []
        self._cur_table: list[list[str]] | None = None
        self._cur_row: list[str] | None = None
        self._cur_cell: str = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:  # noqa: ARG002
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        if tag == "table" and self._cur_table is None:
            self._cur_table = []
        elif tag == "tr" and self._cur_table is not None:
            self._cur_row = []
        elif tag in ("td", "th") and self._cur_row is not None:
            self._cur_cell = ""

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
        if tag in ("td", "th") and self._cur_row is not None:
            self._cur_row.append(self._cur_cell.strip())
            self._cur_cell = ""
        elif tag == "tr" and self._cur_row is not None and self._cur_table is not None:
            self._cur_table.append(self._cur_row)
            self._cur_row = None
        elif tag == "table" and self._cur_table is not None:
            self._tables.append(self._cur_table)
            self._cur_table = None

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        self._parts.append(data)
        self._cur_cell += data

    def text(self) -> str:
        joined: list[str] = []
        for part in self._parts:
            stripped = part.strip()
            if stripped:
                if joined and joined[-1].endswith(("\n", " ")):
                    joined.append(stripped)
                else:
                    joined.append(" " + stripped if joined else stripped)
        raw = "".join(joined)
        # Normalize multiple spaces.
        import re

        return re.sub(r" {2,}", " ", raw).strip()


class HTMLExtractor(Extractor):
    """Extractor for HTML documents."""

    format = DocumentFormat.HTML

    async def extract(self, data: bytes) -> ExtractionResult:
        text = _decode(data)
        parser = _HTMLTextAndTables()
        try:
            parser.feed(text)
            parser.close()
        except Exception:
            return ExtractionResult(format=self.format, text=_strip_tags_fallback(text), pages=1)
        return ExtractionResult(
            format=self.format,
            text=parser.text(),
            tables=parser._tables,
            pages=1,
        )


def _decode(data: bytes) -> str:
    for encoding in ("utf-8", "utf-16", "latin-1"):
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, ValueError):
            continue
    return data.decode("utf-8", errors="replace")


def _strip_tags_fallback(text: str) -> str:
    import re

    text = re.sub(r"<script.*?</script>", "", text, flags=re.S | re.I)
    text = re.sub(r"<style.*?</style>", "", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()
