"""Field extraction: pull structured commerce fields out of raw document text.

This is the "intelligence" part of the document system. It combines:

- **Global regex scans** for barcodes (UPC/EAN/GTIN with checksum validation),
  weight, and physical dimensions.
- **Keyword-context line scanning** for model number, part number, manufacturer,
  case quantity and warranty (values that only make sense near a label).

Every extractor is deterministic and provider-independent; OCR output simply
feeds the same text in, so the field logic never cares how the text was obtained.
"""

from __future__ import annotations

import re

from app.documents.schemas import ExtractedFields

# ──────────────────────────────────────────────────────────────
# Barcodes (UPC / EAN / GTIN) with checksum validation
# ──────────────────────────────────────────────────────────────

_GTIN14_RE = re.compile(r"(?<!\d)(\d{14})(?!\d)")
_EAN13_RE = re.compile(r"(?<!\d)(\d{13})(?!\d)")
_UPC12_RE = re.compile(r"(?<!\d)(\d{12})(?!\d)")


def _gtin_checksum_valid(digits: str) -> bool:
    """Validate a GTIN-family checksum (UPC-A, EAN-13, GTIN-14, GTIN-8).

    The check digit is the last; the body is weighted alternately 3,1 from the
    rightmost body digit, and the check digit must complete the sum to a
    multiple of 10.
    """
    if len(digits) < 8 or not digits.isdigit():
        return False
    body = digits[:-1]
    check = int(digits[-1])
    total = 0
    for i, d in enumerate(reversed(body)):
        weight = 3 if i % 2 == 0 else 1
        total += int(d) * weight
    return (10 - (total % 10)) % 10 == check


def _extract_barcodes(text: str, pattern: re.Pattern[str]) -> list[str]:
    found: list[str] = []
    for match in pattern.finditer(text):
        code = match.group(1)
        if _gtin_checksum_valid(code):
            found.append(code)
    return _dedupe(found)


def extract_barcodes(text: str) -> tuple[list[str], list[str], list[str]]:
    """Return (upc, ean, gtin) lists from a document's text.

    A 12-digit UPC is also a valid GTIN-12; a 13-digit EAN is also a GTIN-13;
    a 14-digit code is GTIN-14 only. We report each code under every valid
    grouping so a downstream system can query by any identifier.
    """
    gtin14 = _extract_barcodes(text, _GTIN14_RE)
    ean13 = _extract_barcodes(text, _EAN13_RE)
    upc12 = _extract_barcodes(text, _UPC12_RE)

    upc = list(upc12)
    ean = list(ean13)
    gtin = _dedupe(gtin14 + ean13 + upc12)
    return upc, ean, gtin


# ──────────────────────────────────────────────────────────────
# Weight & dimensions
# ──────────────────────────────────────────────────────────────

_WEIGHT_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*"
    r"(kilograms?|kgs?|kg|grams?|g|lbs?|lb|pounds?|oz|ounces?)\b",
    re.IGNORECASE,
)

_DIMENSION_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*[x\u00d7]\s*(\d+(?:\.\d+)?)"
    r"(?:\s*[x\u00d7]\s*(\d+(?:\.\d+)?))?"
    r"\s*(mm|cm|m|inches?|in|ft)\b",
    re.IGNORECASE,
)


def extract_weight(text: str) -> list[str]:
    """Find weight mentions, returning them with a canonical unit."""
    found: list[str] = []
    for match in _WEIGHT_RE.finditer(text):
        amount, raw_unit = match.group(1), match.group(2).lower()
        unit = _canonical_unit(raw_unit)
        found.append(f"{amount} {unit}")
    return _dedupe(found)


def _canonical_unit(raw: str) -> str:
    if raw.startswith("k"):
        return "kg"
    if raw.startswith("g") and not raw.startswith("gr"):
        return "g"
    if raw in {"g", "gram", "grams"}:
        return "g"
    if raw.startswith("p"):
        return "lb"
    if raw.startswith("lb"):
        return "lb"
    if raw.startswith("oz") or raw.startswith("oun"):
        return "oz"
    return raw


def extract_dimensions(text: str) -> list[str]:
    """Find physical dimensions as 'L x W x H' strings with units."""
    found: list[str] = []
    for match in _DIMENSION_RE.finditer(text):
        a, b = match.group(1), match.group(2)
        c = match.group(3)
        unit = match.group(4).lower().replace("inches", "in").replace("inch", "in")
        if c is not None:
            found.append(f"{a} x {b} x {c} {unit}")
        else:
            found.append(f"{a} x {b} {unit}")
    return _dedupe(found)


# ──────────────────────────────────────────────────────────────
# Keyword-context scanning
# ──────────────────────────────────────────────────────────────

_TOKEN_RE = re.compile(r"([A-Za-z0-9][A-Za-z0-9\-/._]{1,32})")
_NUMBER_RE = re.compile(r"(\d+(?:\.\d+)?)")
_WARRANTY_RE = re.compile(
    r"(?:\d+(?:\.\d+)?\s*[-\u2013]?\s*(?:year|month|yr|mo)s?|lifetime|limited\s+lifetime)",
    re.IGNORECASE,
)

_MODEL_KEYWORDS = ("model number", "model no", "model #", "m/n", "model")
_PART_KEYWORDS = ("part number", "part no", "part #", "p/n", "catalog #", "item #", "part#")
_MANUFACTURER_KEYWORDS = (
    "manufacturer", "manufactured by", "mfr", "brand", "made by", "company",
)
_CASE_QTY_KEYWORDS = (
    "case quantity", "units per case", "quantity per case", "per case",
    "pieces per case", "pack qty", "qty per case", "case of",
)
_WARRANTY_KEYWORDS = ("warranty", "guarantee")


def _lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _context_tokens(line: str, keywords: tuple[str, ...]) -> list[str]:
    """Return the token(s) that follow any of the given keywords on a line.

    For ``"Model: XZY-1000"`` this returns ``["XZY-1000"]``.
    """
    lowered = line.lower()
    for keyword in keywords:
        idx = lowered.find(keyword.lower())
        if idx == -1:
            continue
        suffix = line[idx + len(keyword):]
        # Drop a leading label separator.
        suffix = suffix.lstrip(": \t-=|#")
        tokens = _TOKEN_RE.findall(suffix)
        if tokens:
            return tokens
    return []


def _context_number(line: str, keywords: tuple[str, ...]) -> str | None:
    """Return the number that follows any of the given keywords on a line."""
    lowered = line.lower()
    for keyword in keywords:
        idx = lowered.find(keyword.lower())
        if idx == -1:
            continue
        suffix = line[idx + len(keyword):].lstrip(": \t=#")
        match = _NUMBER_RE.search(suffix)
        if match:
            return match.group(1)
    return None


def _context_warranty(line: str) -> str | None:
    lowered = line.lower()
    if not any(k in lowered for k in _WARRANTY_KEYWORDS):
        return None
    # Look within the whole line (warranty text often wraps the value).
    match = _WARRANTY_RE.search(line)
    if not match:
        return None
    span = match.group(0)
    if "year" in span or "yr" in span or "month" in span or "mo" in span:
        return span.lower()
    return span.lower()


def extract_model_numbers(text: str) -> list[str]:
    found: list[str] = []
    for line in _lines(text):
        found.extend(_context_tokens(line, _MODEL_KEYWORDS))
    # Also scan whole text for plausible standalone model tokens as a fallback.
    # Only tokens containing a digit are plausible model numbers (avoids
    # picking up arbitrary words).
    if not found:
        fallback = [t for t in _TOKEN_RE.findall(text) if any(ch.isdigit() for ch in t)]
        found.extend(fallback)
    return _dedupe(_drop_noise(found), max_results=8)


def extract_part_numbers(text: str) -> list[str]:
    found: list[str] = []
    for line in _lines(text):
        found.extend(_context_tokens(line, _PART_KEYWORDS))
    return _dedupe(_drop_noise(found), max_results=8)


def extract_manufacturers(text: str) -> list[str]:
    found: list[str] = []
    for line in _lines(text):
        found.extend(_context_tokens(line, _MANUFACTURER_KEYWORDS))
    return _dedupe(found, max_results=5)


def extract_case_quantities(text: str) -> list[str]:
    found: list[str] = []
    for line in _lines(text):
        number = _context_number(line, _CASE_QTY_KEYWORDS)
        if number:
            found.append(number)
    return _dedupe(found, max_results=3)


def extract_warranties(text: str) -> list[str]:
    found: list[str] = []
    for line in _lines(text):
        value = _context_warranty(line)
        if value:
            found.append(value)
    return _dedupe(found, max_results=3)


# ──────────────────────────────────────────────────────────────
# Orchestration
# ──────────────────────────────────────────────────────────────


def extract_fields(text: str) -> ExtractedFields:
    """Extract every supported field from a document's text."""
    upc, ean, gtin = extract_barcodes(text)
    fields = ExtractedFields(
        upc=upc,
        ean=ean,
        gtin=gtin,
        weight=extract_weight(text),
        dimensions=extract_dimensions(text),
        case_quantity=extract_case_quantities(text),
        model_number=extract_model_numbers(text),
        manufacturer=extract_manufacturers(text),
        part_number=extract_part_numbers(text),
        warranty=extract_warranties(text),
    )
    fields.confidence = compute_confidence(fields)
    return fields


def compute_confidence(fields: ExtractedFields) -> float:
    """Estimate extraction confidence from how many field groups were found.

    Ranges 0..1; more populated field groups raise confidence, up to a cap so a
    single barcode alone never scores perfect.
    """
    populated = fields.populated_count()
    if populated == 0:
        return 0.0
    return min(0.95, 0.25 + populated * 0.10)


def _drop_noise(values: list[str]) -> list[str]:
    """Remove tokens that are just label words, not real model/part numbers."""
    noise = {"p/n", "pn", "part", "part no", "part number", "model", "model no",
             "m/n", "sku", "n/a", "none", "na", "type", "no", "#"}
    return [v for v in values if v.strip().lower() not in noise]


def _dedupe(values: list[str], max_results: int = 12) -> list[str]:
    """Deduplicate while preserving order, optionally capped."""
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        key = value.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(value.strip())
        if len(out) >= max_results:
            break
    return out
