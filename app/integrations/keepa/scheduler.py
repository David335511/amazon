"""Background refresh jobs for Keepa data.

Design decisions:
- Uses asyncio for non-blocking periodic execution.
- Configurable refresh intervals per data type.
- Graceful shutdown via cancellation tokens.
- Structured logging for observability.
- Error isolation — one failed refresh doesn't affect others.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from app.core.logging import get_logger
from app.integrations.keepa.service import KeepaService

logger = get_logger(__name__)


class KeepaRefreshJob:
    """Background job that periodically refreshes Keepa product data.

    Supports multiple refresh strategies:
    - Watchlist refresh: Refresh all products in a user's watchlist.
    - Category refresh: Refresh best sellers in a category.
    - Batch refresh: Refresh a fixed list of ASINs.

    Each refresh strategy runs at its own configurable interval.
    """

    def __init__(
        self,
        service: KeepaService,
        watchlist_provider: Callable[[], list[dict[str, Any]]] | None = None,
        watchlist_interval: int = 3600,  # 1 hour
        batch_asins: list[str] | None = None,
        batch_interval: int = 86400,  # 24 hours
    ) -> None:
        self._service = service
        self._watchlist_provider = watchlist_provider
        self._watchlist_interval = watchlist_interval
        self._batch_asins = batch_asins or []
        self._batch_interval = batch_interval
        self._tasks: list[asyncio.Task[Any]] = []
        self._running = False

    # ── Lifecycle ───────────────────────────────────────────

    def start(self) -> None:
        """Start all background refresh tasks."""
        if self._running:
            logger.warning("KeepaRefreshJob is already running")
            return

        self._running = True

        if self._watchlist_provider is not None:
            task = asyncio.create_task(self._run_watchlist_refresh())
            self._tasks.append(task)
            logger.info(
                "Started watchlist refresh job (interval=%ds)",
                self._watchlist_interval,
            )

        if self._batch_asins:
            task = asyncio.create_task(self._run_batch_refresh())
            self._tasks.append(task)
            logger.info(
                "Started batch refresh job for %d ASINs (interval=%ds)",
                len(self._batch_asins), self._batch_interval,
            )

        if not self._tasks:
            logger.warning("KeepaRefreshJob started with no tasks configured")

    async def stop(self) -> None:
        """Stop all background refresh tasks gracefully."""
        self._running = False
        for task in self._tasks:
            task.cancel()

        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
            self._tasks.clear()

        logger.info("KeepaRefreshJob stopped")

    # ── Refresh Loops ───────────────────────────────────────

    async def _run_watchlist_refresh(self) -> None:
        """Periodically refresh all products in the watchlist."""
        while self._running:
            try:
                await asyncio.sleep(self._watchlist_interval)

                if not self._running:
                    break

                if self._watchlist_provider is None:
                    continue

                watchlist = self._watchlist_provider()
                if not watchlist:
                    logger.debug("Watchlist is empty, skipping refresh")
                    continue

                logger.info(
                    "Starting watchlist refresh for %d products",
                    len(watchlist),
                )
                results = await self._service.refresh_watchlist_products(watchlist)
                logger.info(
                    "Watchlist refresh complete: %s", results,
                )

            except asyncio.CancelledError:
                logger.info("Watchlist refresh task cancelled")
                break
            except Exception as exc:
                logger.error("Watchlist refresh error: %s", exc)
                await asyncio.sleep(60)  # Wait before retrying

    async def _run_batch_refresh(self) -> None:
        """Periodically refresh a fixed batch of ASINs."""
        while self._running:
            try:
                await asyncio.sleep(self._batch_interval)

                if not self._running:
                    break

                if not self._batch_asins:
                    continue

                logger.info(
                    "Starting batch refresh for %d ASINs",
                    len(self._batch_asins),
                )
                results = await self._service.fetch_and_store_batch(
                    self._batch_asins,
                )
                logger.info(
                    "Batch refresh complete: %d products refreshed",
                    len(results),
                )

            except asyncio.CancelledError:
                logger.info("Batch refresh task cancelled")
                break
            except Exception as exc:
                logger.error("Batch refresh error: %s", exc)
                await asyncio.sleep(60)

    # ── One-shot Refresh ─────────────────────────────────────

    async def refresh_single(self, asin: str, domain: str = "com") -> bool:
        """Refresh a single product immediately.

        Args:
            asin: Amazon ASIN.
            domain: Amazon domain code.

        Returns:
            True if refresh succeeded, False otherwise.
        """
        try:
            result = await self._service.fetch_and_store_product(asin, domain)
            return result is not None
        except Exception as exc:
            logger.error("Single refresh failed for ASIN %s: %s", asin, exc)
            return False

    async def refresh_batch(self, asins: list[str], domain: str = "com") -> int:
        """Refresh a batch of products immediately.

        Args:
            asins: List of ASINs to refresh.
            domain: Amazon domain code.

        Returns:
            Number of successfully refreshed products.
        """
        results = await self._service.fetch_and_store_batch(asins, domain)
        return len(results)
