"""Multilingual AI support — language detection.

Pure-stdlib, deterministic detection over Unicode character ranges. We never call
an external service, so detection is reproducible and offline. It only decides
which *output* language to use; it does not translate anything.

Design decisions:
- Detect CJK vs Latin scripts by counting classified letters.
- A short mixed string (e.g. an ASIN) is intentionally ambiguous -> falls back to
  the default language with ``script == "unknown"``.
- Detection is a hint only; callers can override with an explicit language.
"""

from __future__ import annotations

from dataclasses import dataclass

# CJK / East-Asian scripts.
_CJK_RANGES: list[tuple[int, int]] = [
    (0x3400, 0x4DBF),  # CJK Extension A
    (0x4E00, 0x9FFF),  # CJK Unified Ideographs
    (0x3040, 0x30FF),  # Hiragana + Katakana
    (0xAC00, 0xD7AF),  # Hangul Syllables
    (0xF900, 0xFAFF),  # CJK Compatibility Ideographs
    (0xFF00, 0xFFEF),  # Fullwidth Forms (punctuation, fullwidth Latin)
]


def _is_cjk(char: str) -> bool:
    o = ord(char)
    return any(lo <= o <= hi for lo, hi in _CJK_RANGES)


def _is_latin(char: str) -> bool:
    return char.isascii() and char.isalpha()


@dataclass(frozen=True)
class DetectionResult:
    """Result of a language-detection call."""

    detected_language: str
    confidence: float
    script: str
    supported: bool
    sample_text: str | None = None


def detect_language(
    text: str,
    *,
    supported: list[str] | None = None,
    default: str = "en",
) -> DetectionResult:
    """Detect the language of ``text`` from its script mix.

    Args:
        text: The text to classify (may be empty).
        supported: Whitelist of languages that count as detected.
        default: Language returned when nothing can be determined.

    Returns:
        A :class:`DetectionResult`.
    """
    supported = supported or ["en", "zh-CN"]

    cjk = 0
    latin = 0
    sample = text.strip()[:80]
    for char in text:
        if _is_cjk(char):
            cjk += 1
        elif _is_latin(char):
            latin += 1

    total = cjk + latin
    if total == 0:
        return DetectionResult(
            detected_language=default, confidence=0.0, script="unknown",
            supported=default in supported, sample_text=sample,
        )

    cjk_ratio = cjk / total
    latin_ratio = latin / total

    if cjk_ratio >= 0.5 and "zh-CN" in supported:
        return DetectionResult(
            detected_language="zh-CN", confidence=round(cjk_ratio, 3),
            script="cjk", supported=True, sample_text=sample,
        )
    if latin_ratio >= 0.5 and "en" in supported:
        return DetectionResult(
            detected_language="en", confidence=round(latin_ratio, 3),
            script="latin", supported=True, sample_text=sample,
        )
    return DetectionResult(
        detected_language=default, confidence=0.0, script="unknown",
        supported=default in supported, sample_text=sample,
    )
