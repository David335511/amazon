"""CAPTCHA / bot-challenge detection.

Scans a page for the common signals of a CAPTCHA or anti-bot wall: known
selectors, iframes, URL fragments, titles, and status codes. Returns a
`CaptchaCheck` with provider and confidence so callers can decide whether to
retry with a fresh fingerprint/proxy or give up.
"""

from __future__ import annotations

import re
from typing import Any

from app.browser.models import CaptchaCheck

# Provider → detection signals
_PROVIDER_SELECTORS: dict[str, list[str]] = {
    "recaptcha": [
        "iframe[src*='recaptcha']",
        ".g-recaptcha",
        "div.g-recaptcha",
        "#recaptcha",
    ],
    "hcaptcha": [
        "iframe[src*='hcaptcha']",
        ".h-captcha",
        "div.h-captcha",
        "#hcaptcha",
    ],
    "cloudflare": [
        "iframe[src*='challenges.cloudflare.com']",
        "#challenge-running",
        "#cf-challenge-running",
        ".cf-turnstile",
        "#turnstile-wrapper",
    ],
    "arkose": [
        "iframe[src*='arkoselabs']",
        "#arkose-iframe",
        ".arkose",
    ],
    "generic": [
        "#captcha",
        "form[name='captcha']",
        "input[name='captcha_code']",
        ".captcha-image",
        "body[onload*='captcha']",
    ],
}

_URL_PATTERNS: dict[str, re.Pattern[str]] = {
    "cloudflare": re.compile(r"cloudflare|cf-?challenge|/cdn-cgi/", re.IGNORECASE),
    "recaptcha": re.compile(r"recaptcha", re.IGNORECASE),
    "hcaptcha": re.compile(r"hcaptcha", re.IGNORECASE),
}

_TITLE_PATTERNS: dict[str, re.Pattern[str]] = {
    "cloudflare": re.compile(r"just a moment|attention required", re.IGNORECASE),
    "generic": re.compile(r"captcha|verify you are human|are you human", re.IGNORECASE),
}

_BODY_TEXT_PATTERNS: dict[str, re.Pattern[str]] = {
    "cloudflare": re.compile(r"verify you are human", re.IGNORECASE),
    "generic": re.compile(
        r"(?is)(captcha|bot check|verify you are human|"
        r"automated access is denied|unusual traffic|security check)"
    ),
}

_STATUS_CODE_HINTS: dict[int, str] = {
    403: "cloudflare",
    429: "rate_limited",
}


class CaptchaDetector:
    """Detects CAPTCHA and anti-bot challenges on a page."""

    def __init__(self, *, enabled: bool = True) -> None:
        self._enabled = enabled

    async def check(self, page: Any, *, url: str | None = None) -> CaptchaCheck:
        """Scan a Playwright page for CAPTCHA signals.

        Args:
            page: A Playwright `Page` (or a duck-typed fake in tests).
            url: Optional known URL (avoids a page.url read when available).

        Returns:
            A `CaptchaCheck` describing what (if anything) was detected.
        """
        if not self._enabled:
            return CaptchaCheck(detected=False)

        current_url = url or page.url
        signals: list[tuple[str, float]] = []

        # 1. URL patterns
        for provider, pattern in _URL_PATTERNS.items():
            if pattern.search(current_url):
                signals.append((provider, 0.9))

        # 2. Selector presence
        for provider, selectors in _PROVIDER_SELECTORS.items():
            for sel in selectors:
                try:
                    # Playwright locator.count() is synchronous.
                    count = page.locator(sel).count()
                except Exception:
                    count = 0
                if count and count > 0:
                    signals.append((provider, 0.85))
                    break

        # 3. Title patterns
        title = ""
        try:
            title = (await page.title()) or ""
        except Exception:
            title = ""
        for provider, pattern in _TITLE_PATTERNS.items():
            if pattern.search(title):
                signals.append((provider, 0.8))

        # 4. Body text (sampled, bounded)
        try:
            body = (await page.evaluate("() => document.body ? document.body.innerText.slice(0, 5000) : ''")) or ""
        except Exception:
            body = ""
        for provider, pattern in _BODY_TEXT_PATTERNS.items():
            if pattern.search(body):
                signals.append((provider, 0.7))

        if not signals:
            return CaptchaCheck(detected=False, page_url=current_url)

        # Highest confidence signal wins; aggregate confidence.
        best = max(signals, key=lambda s: s[1])
        provider = best[0]
        confidence = min(1.0, sum(s for _, s in signals) / len(signals) + 0.1)
        reason = ", ".join(f"{p}:{round(c, 2)}" for p, c in signals)
        return CaptchaCheck(
            detected=True,
            provider=provider,
            confidence=round(confidence, 2),
            reason=reason,
            page_url=current_url,
        )
