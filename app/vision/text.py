"""Text helpers for the computer-vision subsystem.

Model-number detection and textual similarity (title/brand) are pure functions
so they are fully provider-independent. Real OCR (turning pixels into text) is a
provider capability; once OCR text is available, this module scans it for model
numbers and scores title/brand similarity.
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Any

# Common product model-number shapes: a short alphanumeric prefix plus digits,
# or a lone alphanumeric code. Applied to OCR text / titles / attributes.
_MODEL_PATTERNS = (
    re.compile(r"\b[A-Z]{1,4}[- _]?[0-9]{2,6}[A-Z0-9]{0,4}\b"),
    re.compile(r"\b[A-Z]{1,3}[0-9]{3,6}\b"),
)

_TOKEN_SPLIT = re.compile(r"[\W_]+")


def normalize_brand(value: str | None) -> str:
    """Normalize a brand for comparison (lowercase, stripped)."""
    return (value or "").strip().lower()


def tokenize(value: str | None) -> list[str]:
    """Split text into lowercase alphanumeric tokens."""
    if not value:
        return []
    return [token for token in _TOKEN_SPLIT.split(value.lower()) if token]


def token_embedding(value: str | None, dim: int = 128) -> list[float]:
    """Deterministic bag-of-tokens hashing embedding for short text."""
    vector = [0.0] * dim
    for token in tokenize(value):
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        index = int.from_bytes(digest, "little") % dim
        sign = 1.0 if digest[0] % 2 == 0 else -1.0
        vector[index] += sign
    norm = math.sqrt(sum(v * v for v in vector))
    if norm > 0:
        vector = [v / norm for v in vector]
    return vector


def text_similarity(a: str | None, b: str | None) -> float:
    """Cosine similarity between two strings using token hashing."""
    if not a or not b:
        return 0.0
    va, vb = token_embedding(a), token_embedding(b)
    dot = sum(x * y for x, y in zip(va, vb, strict=False))
    na = math.sqrt(sum(x * x for x in va))
    nb = math.sqrt(sum(y * y for y in vb))
    if na == 0 or nb == 0:
        return 0.0
    return max(0.0, min(1.0, dot / (na * nb)))


def extract_model_numbers(text: str | None) -> list[str]:
    """Extract candidate model numbers from text (deduplicated, ordered)."""
    if not text:
        return []
    seen: set[str] = set()
    found: list[str] = []
    for pattern in _MODEL_PATTERNS:
        for match in pattern.findall(text):
            key = re.sub(r"[\s_-]", "", match).upper()
            if key and key not in seen:
                seen.add(key)
                found.append(match.strip())
    return found


def normalize_attributes(attributes: dict[str, Any] | None) -> dict[str, str]:
    """Normalize an attribute map into lowercase str->str pairs."""
    out: dict[str, str] = {}
    for key, value in (attributes or {}).items():
        if value is None:
            continue
        out[str(key).strip().lower()] = str(value).strip().lower()
    return out


def attribute_overlap(a: dict[str, Any] | None, b: dict[str, Any] | None) -> float:
    """Fraction of shared attribute key/value pairs (0..1)."""
    na, nb = normalize_attributes(a), normalize_attributes(b)
    if not na or not nb:
        return 0.0
    shared = sum(1 for key, value in na.items() if nb.get(key) == value)
    union = len(set(na) | set(nb)) or 1
    return shared / union
