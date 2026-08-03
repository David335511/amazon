"""Request interception: resource blocking and header injection.

Uses Playwright's `page.route` to intercept outgoing requests. This gives the
framework two capabilities suppliers commonly need:

- **Block heavy/noisy resource types** (images, media, fonts) to speed up
  scraping and reduce bandwidth.
- **Inject headers / modify requests** per-domain (e.g. a spoofed referer) and
  optionally rewrite URLs.

The interceptor is a plain callable so it is trivially unit-testable without a
browser.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Resource types Playwright recognizes.
_ALLOWED_TYPES = {
    "document", "stylesheet", "image", "media", "font", "script",
    "texttrack", "xhr", "fetch", "eventsource", "websocket", "manifest",
    "other",
}

# Trackers/ad platforms commonly found on retail sites.
_BLOCKED_DOMAINS_FRAGMENTS = [
    "doubleclick.net",
    "googlesyndication.com",
    "google-analytics.com",
    "googletagmanager.com",
    "facebook.net",
    "facebook.com/tr",
    "scorecardresearch.com",
    "adservice.google.",
    "amazon-adsystem.com",
]


class RequestInterceptor:
    """Builds and runs request interception handlers for a page."""

    def __init__(
        self,
        *,
        block_resource_types: list[str] | None = None,
        block_domains: list[str] | None = None,
        inject_headers: dict[str, str] | None = None,
    ) -> None:
        self._block_resource_types = set(block_resource_types or [])
        self._block_domains = set(block_domains or []) | set(_BLOCKED_DOMAINS_FRAGMENTS)
        self._inject_headers = inject_headers or {}

    @property
    def blocked_resource_types(self) -> set[str]:
        """Resource types currently blocked."""
        return set(self._block_resource_types)

    async def handler(self, route: Any, request: Any) -> None:
        """Playwright route handler.

        Args:
            route: A Playwright `Route`.
            request: A Playwright `Request`.
        """
        res_type = getattr(request, "resource_type", lambda: "other")()
        url = getattr(request, "url", lambda: "")()

        # Block by resource type.
        if res_type in self._block_resource_types:
            await self._abort(route, "blockedtype")
            return

        # Block by domain fragment.
        lowered = url.lower()
        if any(frag in lowered for frag in self._block_domains):
            await self._abort(route, "blockedhost")
            return

        # Continue, optionally injecting headers.
        if self._inject_headers:
            headers_raw = getattr(request, "headers", None)
            if callable(headers_raw):
                headers_raw = headers_raw()
            headers = dict(headers_raw or {})
            headers.update(self._inject_headers)
            try:
                await route.continue_(headers=headers)
                return
            except Exception as exc:
                logger.debug("Header injection failed, continuing plain: %s", exc)

        await route.continue_()

    async def _abort(self, route: Any, reason: str) -> None:
        try:
            await route.abort(reason)
        except Exception as exc:
            logger.debug("Failed to abort request: %s", exc)

    async def install(self, page: Any) -> None:
        """Register the handler on a Playwright page.

        Args:
            page: The Playwright page to intercept.
        """
        await page.route("**/*", self.handler)


def build_interceptor(config: dict[str, Any]) -> RequestInterceptor:
    """Build an interceptor from a config dict (or BrowserConfig fields)."""
    return RequestInterceptor(
        block_resource_types=config.get("block_resource_types"),
        block_domains=config.get("block_domains"),
        inject_headers=config.get("inject_headers"),
    )
