"""Lazy Playwright import guard.

Playwright is a heavy optional dependency. Importing it at module load would
break the rest of the application when it is not installed (e.g. in CI unit
tests or lean deployments). All framework modules obtain Playwright through
`get_playwright()` so the package imports cleanly everywhere and fails with a
clear, actionable error only when a browser is actually needed.
"""

from __future__ import annotations

from typing import Any

from app.browser.errors import BrowserNotAvailableError

_playwright_factory: Any = None
_checked = False


def get_playwright() -> Any:
    """Return the `playwright.async_api.async_playwright` factory.

    Raises:
        BrowserNotAvailableError: If Playwright is not installed.
    """
    global _playwright_factory, _checked

    if _checked:
        if _playwright_factory is None:
            raise BrowserNotAvailableError(
                "Playwright is not installed. Install it with "
                "'pip install playwright' then 'playwright install chromium'."
            )
        return _playwright_factory

    _checked = True
    try:
        from playwright.async_api import async_playwright

        _playwright_factory = async_playwright
    except ImportError as exc:
        _playwright_factory = None
        raise BrowserNotAvailableError(
            "Playwright is not installed. Install it with "
            "'pip install playwright' then 'playwright install chromium'."
        ) from exc

    return _playwright_factory
