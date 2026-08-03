"""Crawler — the high-level, reusable browser automation service.

Combines every piece of the framework into one ergonomic API:

    crawler = Crawler(browser_manager)
    await crawler.launch()
    result = await crawler.fetch(
        "https://www.example.com/product/1",
        session="walmart-web",
        screenshot=True,
        archive=True,
    )

Responsibilities orchestrated here:
- Rate limiting (politeness) before each navigation.
- Automatic retries with exponential backoff on transient failures.
- Proxy assignment (and ban-tracking on proxy errors).
- CAPTCHA detection → raises `CaptchaDetectedError` or reports `blocked`.
- Session / cookie persistence across requests.
- Screenshot capture and HTML archiving.
- Request interception (resource blocking).

All output is returned as a plain `CrawlResult` — no Playwright objects leak out.
"""

from __future__ import annotations

import contextlib
import logging
import time
from typing import Any

from app.browser.captcha import CaptchaDetector
from app.browser.config import BrowserConfig
from app.browser.cookies import CookieManager
from app.browser.errors import (
    BrowserRateLimitError,
    BrowserTimeoutError,
    CaptchaDetectedError,
    ProxyError,
)
from app.browser.interceptors import RequestInterceptor
from app.browser.manager import BrowserManager
from app.browser.models import CrawlResult
from app.browser.pool import PagePool
from app.browser.rate_limiter import RateLimiter
from app.browser.retry import retry_async
from app.browser.session import SessionManager
from app.browser.storage import save_html_archive, save_screenshot

logger = logging.getLogger(__name__)


class Crawler:
    """High-level browser automation service for suppliers and scrapers.

    Args:
        browser_manager: The shared BrowserManager.
        pool: Optional PagePool. Built from config if not provided.
        cookie_manager: Optional CookieManager.
        session_manager: Optional SessionManager.
        captcha_detector: Optional CaptchaDetector.
        rate_limiter: Optional RateLimiter (built from config if absent).
        interceptor: Optional RequestInterceptor.
        config: Browser config (used to derive pool / limiter defaults).
    """

    def __init__(
        self,
        browser_manager: BrowserManager,
        *,
        pool: PagePool | None = None,
        cookie_manager: CookieManager | None = None,
        session_manager: SessionManager | None = None,
        captcha_detector: CaptchaDetector | None = None,
        rate_limiter: RateLimiter | None = None,
        interceptor: RequestInterceptor | None = None,
        config: BrowserConfig | None = None,
    ) -> None:
        self._manager = browser_manager
        self._config = config or browser_manager.config
        self._pool = pool or PagePool(
            browser_manager,
            max_size=self._config.max_pages,
            max_idle_seconds=self._config.page_idle_timeout_seconds,
        )
        self._cookies = cookie_manager or CookieManager(self._config.cookie_file)
        self._sessions = session_manager or SessionManager(self._config.session_dir)
        self._captcha = captcha_detector or CaptchaDetector(
            enabled=self._config.captcha_detection_enabled
        )
        # If no rate limiter was given and config has delays, build one.
        if rate_limiter is None:
            rate_limiter = RateLimiter(
                delay_min_ms=self._config.request_delay_min_ms,
                delay_max_ms=self._config.request_delay_max_ms,
            )
        self._limiter = rate_limiter
        self._interceptor = interceptor or RequestInterceptor(
            block_resource_types=self._config.block_resource_types
        )

    # ── Lifecycle ───────────────────────────────────────────

    @property
    def is_available(self) -> bool:
        """Whether the underlying browser is available."""
        return self._manager.is_available

    async def launch(self) -> None:
        """Ensure the browser is launched."""
        await self._manager.launch()

    async def shutdown(self) -> None:
        """Close the pool and the browser."""
        try:
            await self._pool.aclose()
        finally:
            await self._manager.shutdown()

    # ── Primary fetch ───────────────────────────────────────

    async def fetch(
        self,
        url: str,
        *,
        session: str | None = None,
        cookies_name: str | None = None,
        screenshot: bool = False,
        archive: bool = False,
        full_page_screenshot: bool = False,
        use_pool: bool = True,
        raise_on_captcha: bool = False,
        retries: int | None = None,
    ) -> CrawlResult:
        """Navigate to a URL and extract normalized content.

        Args:
            url: Target URL.
            session: Optional named session to load/save persistent state.
            cookies_name: Optional cookie jar name to apply/persist.
            screenshot: Capture a screenshot.
            archive: Save a raw HTML archive.
            full_page_screenshot: Screenshot the full scrollable page.
            use_pool: Use the page pool (reuse pages) vs a fresh page.
            raise_on_captcha: Raise `CaptchaDetectedError` when detected.
            retries: Override retry count (defaults to config).

        Returns:
            A normalized `CrawlResult`.
        """
        await self.launch()
        max_retries = self._config.max_retries if retries is None else retries

        last_proxy: dict[str, Any] | None = None
        proxy_failures = 0

        async def attempt() -> CrawlResult:
            nonlocal last_proxy, proxy_failures
            # Politeness gate.
            delay = await self._limiter.acquire()
            if delay:
                import asyncio

                await asyncio.sleep(delay)

            page = None
            try:
                page, context, is_pooled, proxy = await self._acquire_page(use_pool, session, cookies_name)
                return await self._extract(
                    page,
                    url,
                    context=context,
                    session=session,
                    cookies_name=cookies_name,
                    screenshot=screenshot,
                    archive=archive,
                    full_page_screenshot=full_page_screenshot,
                    is_pooled=is_pooled,
                    proxy=proxy,
                )
            except CaptchaDetectedError:
                # A CAPTCHA means the identity/proxy is compromised; discard page.
                if page is not None:
                    await self._discard(page, is_pooled)
                raise
            except (ProxyError, BrowserRateLimitError) as exc:
                # Proxy likely bad — rotate and retry.
                proxy_failures += 1
                last_proxy = await self._mark_failure_and_rotate(last_proxy)
                raise exc
            except BrowserTimeoutError:
                if page is not None:
                    await self._discard(page, is_pooled)
                raise
            except Exception as exc:
                if page is not None:
                    await self._discard(page, is_pooled)
                logger.debug("Fetch attempt failed for %s: %s", url, exc)
                raise

        try:
            return await retry_async(
                attempt,
                max_retries=max_retries,
                backoff_base_ms=self._config.retry_backoff_base_ms,
            )
        except CaptchaDetectedError as exc:
            if raise_on_captcha:
                raise
            result = CrawlResult(url=url, blocked=True, error=str(exc))
            result.captcha = self._captcha_check_from_exc(exc)
            return result

    # ── Internal helpers ────────────────────────────────────

    async def _acquire_page(
        self,
        use_pool: bool,
        session: str | None,
        cookies_name: str | None,
    ) -> tuple[Any, Any, bool, dict[str, Any] | None]:
        """Get a page from the pool or create a fresh one."""
        if use_pool and session is None and cookies_name is None:
            page = await self._pool.checkout()
            with contextlib.suppress(Exception):
                await self._interceptor.install(page)
            return page, getattr(page, "context", None), True, None

        # Fresh context (isolated per request) so session/cookies don't leak.
        state = self._sessions.load_state(session) if session else None
        proxy = self._manager.proxy_manager.get_proxy()
        context = await self._manager.new_context(proxy=proxy, session_state=state)
        if cookies_name:
            await self._cookies.apply_to_context(cookies_name, context)
        page = await context.new_page()
        with contextlib.suppress(Exception):
            await self._interceptor.install(page)
        return page, context, False, proxy

    async def _extract(
        self,
        page: Any,
        url: str,
        *,
        context: Any,
        session: str | None,
        cookies_name: str | None,
        screenshot: bool,
        archive: bool,
        full_page_screenshot: bool,
        is_pooled: bool,
        proxy: dict[str, Any] | None,
    ) -> CrawlResult:
        started = time.monotonic()
        status: int | None = None
        try:
            response = await page.goto(
                url,
                timeout=self._config.navigation_timeout_ms,
                wait_until=self._config.wait_until,
            )
            if response is not None:
                status = getattr(response, "status", lambda: None)()
        except Exception as exc:
            raise BrowserTimeoutError(f"Navigation to {url} failed: {exc}") from exc

        # CAPTCHA detection.
        check = await self._captcha.check(page, url=url)
        if check.detected:
            if session:
                await self._sessions.save_state(session, {})  # don't persist poisoned state
            raise CaptchaDetectedError(
                f"CAPTCHA detected on {url} ({check.provider})",
                provider=check.provider,
            )

        # Extract content.
        title = await self._safe(page, page.title)
        html = await self._safe(page, lambda: page.content())
        text = await self._safe(
            page,
            lambda: page.evaluate(
                "() => document.body ? document.body.innerText : ''"
            ),
        )

        final_url = await self._safe(page, lambda: page.url) or url
        cookies = []
        if context is not None:
            try:
                cookies = [dict(c) for c in await context.cookies()]
            except Exception:
                cookies = []

        # Persist session / cookies after a successful load.
        if session:
            await self._sessions.persist_context(session, context)
        if cookies_name:
            await self._cookies.persist_from_context(cookies_name, context)

        # Artifacts.
        shot = None
        if screenshot:
            shot = save_screenshot(
                page,
                url=final_url,
                directory=self._config.screenshot_dir,
                full_page=full_page_screenshot,
            )
        arch = None
        if archive and html:
            arch = save_html_archive(
                url=final_url, html=html, title=title, directory=self._config.archive_dir
            )

        # Return page to the pool if it came from it.
        if is_pooled:
            await self._pool.checkin(page)

        return CrawlResult(
            url=url,
            final_url=final_url,
            status=status,
            title=title,
            html=html,
            text=text,
            screenshot=shot,
            archive=arch,
            captcha=check,
            cookies=cookies,
            elapsed_ms=int((time.monotonic() - started) * 1000),
            proxy=proxy,
        )

    async def _discard(self, page: Any, is_pooled: bool) -> None:
        if is_pooled:
            with contextlib.suppress(Exception):
                await self._pool.discard(page)
        else:
            try:
                await page.context.close()
            except Exception:
                with contextlib.suppress(Exception):
                    await page.close()

    async def _mark_failure_and_rotate(self, proxy: dict[str, Any] | None) -> dict[str, Any] | None:
        if proxy is not None:
            self._manager.proxy_manager.mark_failure(proxy)
        try:
            return self._manager.proxy_manager.get_proxy()
        except Exception:
            return None

    @staticmethod
    async def _safe(_page: Any, coro_factory: Any) -> Any:
        """Run an awaitable-producing callable, swallowing errors."""
        try:
            result = coro_factory()
            if hasattr(result, "__await__"):
                return await result
            return result
        except Exception:
            return None

    @staticmethod
    def _captcha_check_from_exc(exc: CaptchaDetectedError) -> Any:
        from app.browser.models import CaptchaCheck

        return CaptchaCheck(
            detected=True,
            provider=exc.provider,
            confidence=0.9,
            reason=exc.message,
        )
