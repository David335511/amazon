"""Error hierarchy for the browser automation framework.

All errors inherit from `BrowserAutomationError` so callers can catch a single
base type. Specific subclasses let callers handle distinct failure modes.
"""

from __future__ import annotations


class BrowserAutomationError(Exception):
    """Base error for all browser automation failures."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class BrowserNotAvailableError(BrowserAutomationError):
    """Playwright is not installed or a browser binary is missing."""


class BrowserLaunchError(BrowserAutomationError):
    """Failed to launch a browser instance."""


class BrowserPoolExhaustedError(BrowserAutomationError):
    """No page/browser available and the pool is at capacity."""


class BrowserPoolTimeoutError(BrowserAutomationError):
    """Timed out waiting for a free page in the pool."""


class CaptchaDetectedError(BrowserAutomationError):
    """A CAPTCHA / bot-challenge was detected on the page."""

    def __init__(self, message: str, *, provider: str | None = None) -> None:
        super().__init__(message)
        self.provider = provider


class BrowserRateLimitError(BrowserAutomationError):
    """The target rate-limited us (HTTP 429 / soft throttle)."""


class BrowserTimeoutError(BrowserAutomationError):
    """A browser operation timed out."""


class ProxyError(BrowserAutomationError):
    """A proxy is unreachable, unauthenticated, or misconfigured."""

    def __init__(self, message: str, *, proxy: str | None = None) -> None:
        super().__init__(message)
        self.proxy = proxy


class ProxyExhaustedError(BrowserAutomationError):
    """All configured proxies have been banned or failed health checks."""


class SessionNotFoundError(BrowserAutomationError):
    """A requested session does not exist."""


class SessionPersistError(BrowserAutomationError):
    """Failed to persist or load a session."""


class CookieStoreError(BrowserAutomationError):
    """Failed to read or write the cookie store."""


class FingerprintError(BrowserAutomationError):
    """Failed to generate or apply a browser fingerprint."""
