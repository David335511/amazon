"""BrowserManager — owns the Playwright process and browser lifecycle.

The single owner of the underlying Playwright browser. Responsibilities:
- Lazily start/stop Playwright and the browser.
- Support both headless and visible modes.
- Create isolated contexts with viewport / UA / locale / timezone / DPR,
  applying fingerprint randomization and per-context proxies.
- Install request interception on pages.

Playwright is loaded lazily so this module (and the whole framework) imports
cleanly without Playwright installed.
"""

from __future__ import annotations

import logging
from typing import Any

from app.browser._playwright import get_playwright
from app.browser.config import BrowserConfig
from app.browser.errors import BrowserLaunchError
from app.browser.fingerprint import FingerprintRandomizer
from app.browser.interceptors import RequestInterceptor
from app.browser.proxy import ProxyManager

logger = logging.getLogger(__name__)


class BrowserManager:
    """Orchestrates the Playwright browser lifecycle.

    Args:
        config: Browser config (or a plain dict).
        proxy_manager: Optional proxy pool to draw proxies from.
        fingerprint_randomizer: Optional fingerprint generator.
    """

    def __init__(
        self,
        config: BrowserConfig | dict[str, Any] | None = None,
        proxy_manager: ProxyManager | None = None,
        fingerprint_randomizer: FingerprintRandomizer | None = None,
    ) -> None:
        self._config = (
            config if isinstance(config, BrowserConfig) else BrowserConfig.model_validate(config or {})
        )
        self._proxy_manager = proxy_manager or ProxyManager(
            self._config.proxy if self._config.proxy else None
        )
        self._fingerprint = fingerprint_randomizer or FingerprintRandomizer(
            self._config.fingerprint
        )
        self._interceptor = RequestInterceptor(
            block_resource_types=self._config.block_resource_types
        )

        self._playwright: Any = None
        self._browser: Any = None
        self._launched = False
        self._launch_error: str | None = None

    # ── Availability & lifecycle ────────────────────────────

    @property
    def is_available(self) -> bool:
        """Whether a browser has been launched and is ready."""
        return self._launched and self._browser is not None

    @property
    def browser(self) -> Any:
        """The launched Playwright Browser (raises if not launched)."""
        if not self.is_available:
            raise BrowserLaunchError("Browser is not launched; call launch() first.")
        return self._browser

    @property
    def headless(self) -> bool:
        """Whether the browser runs without a visible window."""
        return self._config.headless and not self._config.visible

    @property
    def config(self) -> BrowserConfig:
        """The resolved browser configuration."""
        return self._config

    @property
    def proxy_manager(self) -> ProxyManager:
        """The proxy pool used by this manager."""
        return self._proxy_manager

    async def launch(self) -> None:
        """Start Playwright and the browser.

        Raises:
            BrowserLaunchError: If Playwright is missing or the browser fails
                to start.
        """
        if self.is_available:
            return

        try:
            pw_factory = get_playwright()
            self._playwright = await pw_factory().start()
        except Exception as exc:
            self._launch_error = str(exc)
            logger.error("Failed to start Playwright: %s", exc)
            raise BrowserLaunchError(str(exc)) from exc

        launch_options: dict[str, Any] = {
            "headless": self.headless,
        }
        if self._config.slow_mo:
            launch_options["slow_mo"] = self._config.slow_mo
        if self._config.executable_path:
            launch_options["executable_path"] = self._config.executable_path
        if self._config.channel:
            launch_options["channel"] = self._config.channel
        if self._config.launch_args:
            launch_options["args"] = self._config.launch_args

        try:
            self._browser = await self._playwright.chromium.launch(**launch_options)
        except Exception as exc:
            self._launch_error = str(exc)
            await self._stop_playwright()
            raise BrowserLaunchError(f"Failed to launch Chromium: {exc}") from exc

        self._launched = True
        mode = "visible" if not self.headless else "headless"
        logger.info("Browser launched (%s mode).", mode)

    async def shutdown(self) -> None:
        """Close the browser and stop Playwright."""
        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception as exc:
                logger.warning("Error closing browser: %s", exc)
            self._browser = None
        await self._stop_playwright()
        self._launched = False

    async def _stop_playwright(self) -> None:
        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception as exc:
                logger.warning("Error stopping Playwright: %s", exc)
            self._playwright = None

    # ── Context / page creation ─────────────────────────────

    async def new_context(
        self,
        *,
        proxy: dict[str, Any] | None = None,
        fingerprint: Any | None = None,
        session_state: dict[str, Any] | None = None,
        extra_args: list[str] | None = None,
    ) -> Any:
        """Create an isolated browser context.

        Args:
            proxy: Optional proxy dict (Playwright format). Defaults to the
                next proxy from the pool.
            fingerprint: Optional pre-generated fingerprint.
            session_state: Optional Playwright storage-state dict to seed.
            extra_args: Optional extra browser args for this context.

        Returns:
            A Playwright `BrowserContext`.
        """
        ctx_opts = self._context_options(proxy, fingerprint)
        ctx_opts["ignore_https_errors"] = True
        if extra_args:
            ctx_opts.setdefault("args", []).extend(extra_args)

        ctx = await self.browser.new_context(**ctx_opts)
        if session_state:
            cookies = session_state.get("cookies") or []
            if cookies:
                try:
                    await ctx.add_cookies(cookies)
                except Exception as exc:
                    logger.debug("Could not seed session cookies: %s", exc)
        return ctx

    async def new_page(
        self,
        *,
        proxy: dict[str, Any] | None = None,
        fingerprint: Any | None = None,
        session_state: dict[str, Any] | None = None,
        install_interceptor: bool = True,
    ) -> Any:
        """Create a new page on a fresh context.

        Args:
            proxy: Optional proxy dict. Defaults to the next pool proxy.
            fingerprint: Optional pre-generated fingerprint.
            session_state: Optional storage-state to seed.
            install_interceptor: Whether to install resource blocking.

        Returns:
            A tuple-friendly object; callers may use
            ``(context, page) = await manager.new_page_with_context(...)`` or
            the returned page's ``context`` attribute.
        """
        ctx = await self.new_context(
            proxy=proxy,
            fingerprint=fingerprint,
            session_state=session_state,
        )
        page = await ctx.new_page()
        if install_interceptor:
            try:
                await self._interceptor.install(page)
            except Exception as exc:
                logger.debug("Interceptor install failed: %s", exc)
        return page

    def _context_options(
        self,
        proxy: dict[str, Any] | None,
        fingerprint: Any | None,
    ) -> dict[str, Any]:
        fp = fingerprint or self._fingerprint.generate()
        opts: dict[str, Any] = {
            "viewport": {
                "width": fp.viewport[0],
                "height": fp.viewport[1],
            },
            "device_scale_factor": fp.device_scale_factor,
            "locale": fp.locale,
        }
        if fp.user_agent:
            opts["user_agent"] = fp.user_agent
        if fp.timezone_id:
            opts["timezone_id"] = fp.timezone_id

        effective_proxy = proxy if proxy is not None else self._proxy_manager.get_proxy()
        if effective_proxy:
            opts["proxy"] = effective_proxy
        return opts
