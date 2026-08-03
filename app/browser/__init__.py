"""Browser automation framework.

A modular, production-ready Playwright wrapper that supplier plugins and
scrapers use instead of implementing browser automation themselves. It bundles:

- `BrowserManager` — owns the Playwright browser lifecycle (headless/visible).
- `PagePool` — reusable pool of pages/contexts.
- `SessionManager` — persistent named browser sessions (storage state).
- `CookieManager` — persistent cookie jars.
- `ProxyManager` — proxy pool with rotation and ban-tracking.
- `CaptchaDetector` — CAPTCHA / anti-bot challenge detection.
- `RequestInterceptor` — resource blocking and header injection.
- `RateLimiter` — token-bucket politeness limiter.
- `Crawler` — the high-level service composing all of the above.

Playwright is an optional dependency, loaded lazily; the framework imports
cleanly even when Playwright is not installed.
"""

from app.browser.captcha import CaptchaDetector
from app.browser.config import (
    BrowserAutomationConfig,
    BrowserConfig,
    BrowserProxyConfig,
    FingerprintConfig,
    ProxyConfig,
)
from app.browser.cookies import CookieManager
from app.browser.crawler import Crawler
from app.browser.errors import (
    BrowserAutomationError,
    BrowserLaunchError,
    BrowserNotAvailableError,
    BrowserPoolExhaustedError,
    BrowserPoolTimeoutError,
    BrowserRateLimitError,
    BrowserTimeoutError,
    CaptchaDetectedError,
    CookieStoreError,
    FingerprintError,
    ProxyError,
    ProxyExhaustedError,
    SessionNotFoundError,
    SessionPersistError,
)
from app.browser.fingerprint import Fingerprint, FingerprintRandomizer
from app.browser.interceptors import RequestInterceptor
from app.browser.manager import BrowserManager
from app.browser.models import (
    CaptchaCheck,
    CrawlResult,
    HtmlArchive,
    ScreenshotResult,
)
from app.browser.pool import PagePool
from app.browser.proxy import ProxyManager
from app.browser.rate_limiter import RateLimiter
from app.browser.retry import retry_async
from app.browser.session import SessionManager

__all__ = [
    "BrowserAutomationConfig",
    "BrowserAutomationError",
    "BrowserConfig",
    "BrowserLaunchError",
    "BrowserManager",
    "BrowserNotAvailableError",
    "BrowserPoolExhaustedError",
    "BrowserPoolTimeoutError",
    "BrowserProxyConfig",
    "BrowserRateLimitError",
    "BrowserTimeoutError",
    "CaptchaCheck",
    "CaptchaDetectedError",
    "CaptchaDetector",
    "CookieManager",
    "CookieStoreError",
    "CrawlResult",
    "Crawler",
    "Fingerprint",
    "FingerprintConfig",
    "FingerprintError",
    "FingerprintRandomizer",
    "HtmlArchive",
    "PagePool",
    "ProxyConfig",
    "ProxyError",
    "ProxyExhaustedError",
    "ProxyManager",
    "RateLimiter",
    "RequestInterceptor",
    "ScreenshotResult",
    "SessionManager",
    "SessionNotFoundError",
    "SessionPersistError",
    "retry_async",
]
