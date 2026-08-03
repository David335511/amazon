"""Result models for the browser automation framework.

These are the standardized, provider-agnostic data structures produced by the
framework. No Playwright objects leak into callers — only plain Pydantic models.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class CaptchaCheck(BaseModel):
    """Result of a CAPTCHA / bot-challenge scan of a page."""

    detected: bool = Field(default=False)
    provider: str | None = Field(
        default=None, description="recaptcha, hcaptcha, cloudflare, generic"
    )
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str | None = Field(default=None)
    page_url: str | None = Field(default=None)


class ScreenshotResult(BaseModel):
    """Metadata about a captured screenshot."""

    path: str = Field(default="")
    size_bytes: int = Field(default=0)
    full_page: bool = Field(default=False)


class HtmlArchive(BaseModel):
    """Metadata about a saved HTML archive of a page."""

    path: str = Field(default="")
    size_bytes: int = Field(default=0)
    url: str = Field(default="")
    title: str | None = Field(default=None)
    captured_at: datetime = Field(default_factory=datetime.utcnow)


class CrawlResult(BaseModel):
    """The normalized output of a single crawl/fetch operation."""

    url: str = Field(default="")
    final_url: str | None = Field(default=None)
    status: int | None = Field(default=None)
    title: str | None = Field(default=None)
    html: str | None = Field(default=None)
    text: str | None = Field(default=None)
    screenshot: ScreenshotResult | None = Field(default=None)
    archive: HtmlArchive | None = Field(default=None)
    captcha: CaptchaCheck | None = Field(default=None)
    blocked: bool = Field(default=False)
    cookies: list[dict[str, Any]] = Field(default_factory=list)
    elapsed_ms: int = Field(default=0)
    proxy: str | None = Field(default=None)
    error: str | None = Field(default=None)
    raw: dict[str, Any] | None = Field(default=None)
