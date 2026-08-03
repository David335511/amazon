"""PagePool — reusable pool of browser pages/contexts.

Creating a browser context and page is comparatively expensive (new process,
fresh profile). The PagePool keeps a bounded set of idle (context, page) pairs
and hands them out on demand, dramatically reducing per-request overhead for
high-frequency crawling.

Semantics:
- ``checkout()`` returns a page that is temporarily "in use".
- ``checkin(page)`` returns it to the idle pool for reuse.
- Idle pages that exceed ``max_idle_seconds`` are recycled (closed).
- If the pool is full and no page is free, ``checkout()`` waits up to
  ``wait_timeout_seconds`` for one to be returned, then raises.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections import deque
from typing import Any

from app.browser.errors import BrowserPoolTimeoutError

logger = logging.getLogger(__name__)


class PagePool:
    """A bounded pool of reusable browser pages.

    Args:
        browser_manager: The manager used to create fresh pages.
        max_size: Maximum number of pages to hold (idle + in-use).
        max_idle_seconds: Close idle pages older than this.
        wait_timeout_seconds: How long to wait for a free page when at capacity.
    """

    def __init__(
        self,
        browser_manager: Any,
        *,
        max_size: int = 8,
        max_idle_seconds: int = 120,
        wait_timeout_seconds: int = 30,
    ) -> None:
        self._manager = browser_manager
        self._max_size = max(1, max_size)
        self._max_idle_seconds = max_idle_seconds
        self._wait_timeout = wait_timeout_seconds

        self._idle: deque[tuple[float, Any, Any]] = deque()  # (ts, context, page)
        self._in_use: set[Any] = set()
        self._condition = asyncio.Condition()

    @property
    def size(self) -> int:
        """Current number of pages (idle + in-use)."""
        return len(self._idle) + len(self._in_use)

    @property
    def idle_count(self) -> int:
        """Number of currently idle pages."""
        return len(self._idle)

    @property
    def in_use_count(self) -> int:
        """Number of currently in-use pages."""
        return len(self._in_use)

    @property
    def is_full(self) -> bool:
        """Whether the pool is at capacity."""
        return self.size >= self._max_size

    async def checkout(self) -> Any:
        """Acquire an idle page (creating one if possible).

        Returns:
            A Playwright page ready for use.

        Raises:
            BrowserPoolTimeoutError: If the pool is full and no page becomes
                free within the wait timeout.
        """
        async with self._condition:
            deadline = time.monotonic() + self._wait_timeout
            while True:
                await self._recycle_idle()

                if self._idle:
                    _, context, page = self._idle.popleft()
                    self._in_use.add(page)
                    return page

                if not self.is_full:
                    try:
                        context = await self._manager.new_context()
                        page = await context.new_page()
                    except Exception:
                        # Pool may have been closed by a concurrent task; retry.
                        if not self.is_full:
                            raise
                        page = None
                    if page is not None:
                        self._in_use.add(page)
                        return page

                # At capacity — wait for a checkin.
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise BrowserPoolTimeoutError(
                        f"Page pool exhausted after {self._wait_timeout}s "
                        f"({self.size}/{self._max_size} pages in use)."
                    )
                try:
                    await asyncio.wait_for(self._condition.wait(), timeout=remaining)
                except TimeoutError as exc:
                    raise BrowserPoolTimeoutError(
                        f"Page pool exhausted after {self._wait_timeout}s."
                    ) from exc

    async def checkin(self, page: Any) -> None:
        """Return a page to the idle pool for reuse.

        Args:
            page: The page previously returned by ``checkout()``.
        """
        async with self._condition:
            if page in self._in_use:
                self._in_use.discard(page)
                context = getattr(page, "context", None)
                self._idle.append((time.monotonic(), context, page))
            self._condition.notify_all()

    async def discard(self, page: Any) -> None:
        """Close a page permanently (e.g. after a CAPTCHA or hard error)."""
        async with self._condition:
            self._in_use.discard(page)
            self._condition.notify_all()
        try:
            await page.close()
        except Exception as exc:
            logger.debug("Error closing discarded page: %s", exc)

    async def clear(self) -> None:
        """Close all pages and reset the pool."""
        async with self._condition:
            to_close = list(self._idle) + [(None, None, p) for p in self._in_use]
            self._idle.clear()
            self._in_use.clear()
            self._condition.notify_all()
        for _, _, page in to_close:
            if page is not None:
                with contextlib.suppress(Exception):
                    await page.close()
        logger.info("Page pool cleared.")

    async def _recycle_idle(self) -> None:
        """Close and drop idle pages that have exceeded the idle timeout."""
        now = time.monotonic()
        keep: deque[tuple[float, Any, Any]] = deque()
        while self._idle:
            ts, context, page = self._idle.popleft()
            if now - ts > self._max_idle_seconds:
                with contextlib.suppress(Exception):
                    await page.close()
            else:
                keep.append((ts, context, page))
        self._idle = keep

    async def aclose(self) -> None:
        """Alias for ``clear`` (used by framework shutdown)."""
        await self.clear()
