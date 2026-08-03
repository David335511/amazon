"""Filesystem helpers for persisting crawl artifacts (HTML archives, screenshots).

These helpers keep IO out of the Crawler so it stays focused on orchestration.
Artifacts are written atomically and named by a sanitized slug + timestamp.
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.browser.models import HtmlArchive, ScreenshotResult

logger = logging.getLogger(__name__)


def slugify(url: str, limit: int = 60) -> str:
    """Turn a URL into a filesystem-safe slug."""
    host = re.sub(r"^https?://", "", url).split("/")[0]
    host = re.sub(r"[^a-zA-Z0-9_.-]", "_", host)
    return host[:limit] or "page"


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix="art", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def save_screenshot(
    page: Any,
    *,
    url: str,
    directory: str,
    full_page: bool = False,
    file_type: str = "png",
) -> ScreenshotResult | None:
    """Capture and save a screenshot of a Playwright page.

    Returns:
        A `ScreenshotResult`, or ``None`` if capture failed.
    """
    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
    name = f"{slugify(url)}_{ts}.{file_type}"
    path = Path(directory) / name
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = page.screenshot(full_page=full_page, type=file_type)
        _atomic_write(path, data)
        return ScreenshotResult(path=str(path), size_bytes=len(data), full_page=full_page)
    except Exception as exc:
        logger.warning("Screenshot capture failed for %s: %s", url, exc)
        return None


def save_html_archive(
    *,
    url: str,
    html: str,
    title: str | None,
    directory: str,
) -> HtmlArchive | None:
    """Save raw HTML for a page as a timestamped archive.

    Returns:
        An `HtmlArchive`, or ``None`` if writing failed.
    """
    if not html:
        return None
    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
    name = f"{slugify(url)}_{ts}.html"
    path = Path(directory) / name
    try:
        _atomic_write(path, html.encode("utf-8"))
        return HtmlArchive(
            path=str(path),
            size_bytes=len(html.encode("utf-8")),
            url=url,
            title=title,
            captured_at=datetime.now(UTC),
        )
    except Exception as exc:
        logger.warning("HTML archive write failed for %s: %s", url, exc)
        return None
