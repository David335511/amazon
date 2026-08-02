"""Analytics scheduler — periodic data collection for historical snapshots.

Design decisions:
- Configurable collection intervals per data type.
- Graceful shutdown via asyncio cancellation.
- Error isolation — one failed collection doesn't affect others.
- Structured logging for observability.
- Supports both time-based and count-based scheduling.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from app.analytics.service import AnalyticsService
from app.core.logging import get_logger

logger = get_logger(__name__)


class AnalyticsScheduler:
    """Background job that periodically collects analytics snapshots.

    Supports multiple collection strategies:
    - Full collection: Collect snapshots for all active products.
    - Watchlist collection: Collect for a specific set of products.
    - Single product: Collect for one product on demand.

    Each strategy runs at its own configurable interval.
    """

    def __init__(
        self,
        service: AnalyticsService,
        full_collection_interval: int = 3600,  # 1 hour
        watchlist_provider: Callable[[], list[UUID]] | None = None,
        watchlist_interval: int = 900,  # 15 minutes
        batch_size: int = 50,
    ) -> None:
        self._service = service
        self._full_collection_interval = full_collection_interval
        self._watchlist_provider = watchlist_provider
        self._watchlist_interval = watchlist_interval
        self._batch_size = batch_size
        self._tasks: list[asyncio.Task[Any]] = []
        self._running = False

    # ── Lifecycle ───────────────────────────────────────────

    def start(self) -> None:
        """Start all background collection tasks."""
        if self._running:
            logger.warning("AnalyticsScheduler is already running")
            return

        self._running = True

        # Full collection (all active products)
        task = asyncio.create_task(self._run_full_collection())
        self._tasks.append(task)
        logger.info(
            "Started full analytics collection (interval=%ds, batch_size=%d)",
            self._full_collection_interval, self._batch_size,
        )

        # Watchlist collection (if provider is configured)
        if self._watchlist_provider is not None:
            task = asyncio.create_task(self._run_watchlist_collection())
            self._tasks.append(task)
            logger.info(
                "Started watchlist analytics collection (interval=%ds)",
                self._watchlist_interval,
            )

        logger.info("AnalyticsScheduler started with %d task(s)", len(self._tasks))

    async def stop(self) -> None:
        """Stop all background collection tasks gracefully."""
        self._running = False
        for task in self._tasks:
            task.cancel()

        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
            self._tasks.clear()

        logger.info("AnalyticsScheduler stopped")

    # ── Collection Loops ──────────────────────────────────────

    async def _run_full_collection(self) -> None:
        """Periodically collect snapshots for all active products.

        Processes products in batches to avoid overwhelming the database.
        """
        while self._running:
            try:
                await asyncio.sleep(self._full_collection_interval)

                if not self._running:
                    break

                logger.info("Starting full analytics collection")
                total_products = await self._service._repo.count_active_products()
                offset = 0
                total_collected = 0

                while offset < total_products:
                    if not self._running:
                        break

                    result = await self._service.collect_batch(
                        limit=self._batch_size,
                        offset=offset,
                    )
                    total_collected += result.succeeded + result.partial
                    offset += self._batch_size

                    logger.info(
                        "Batch complete: %d/%d (succeeded=%d, partial=%d, failed=%d)",
                        offset, total_products,
                        result.succeeded, result.partial, result.failed,
                    )

                logger.info(
                    "Full collection complete: %d/%d products collected",
                    total_collected, total_products,
                )

            except asyncio.CancelledError:
                logger.info("Full collection task cancelled")
                break
            except Exception as exc:
                logger.error("Full collection error: %s", exc)
                await asyncio.sleep(60)  # Wait before retrying

    async def _run_watchlist_collection(self) -> None:
        """Periodically collect snapshots for watchlist products."""
        while self._running:
            try:
                await asyncio.sleep(self._watchlist_interval)

                if not self._running or self._watchlist_provider is None:
                    break

                product_ids = self._watchlist_provider()
                if not product_ids:
                    logger.debug("Watchlist is empty, skipping collection")
                    continue

                logger.info(
                    "Starting watchlist collection for %d products",
                    len(product_ids),
                )
                result = await self._service.collect_batch(product_ids=product_ids)
                logger.info(
                    "Watchlist collection complete: succeeded=%d, partial=%d, failed=%d",
                    result.succeeded, result.partial, result.failed,
                )

            except asyncio.CancelledError:
                logger.info("Watchlist collection task cancelled")
                break
            except Exception as exc:
                logger.error("Watchlist collection error: %s", exc)
                await asyncio.sleep(60)

    # ── On-demand Collection ─────────────────────────────────

    async def collect_product(self, product_id: UUID) -> bool:
        """Collect a snapshot for a single product immediately.

        Args:
            product_id: Product UUID.

        Returns:
            True if collection succeeded (or partially succeeded).
        """
        try:
            snapshot = await self._service.collect_snapshot(product_id)
            if snapshot.status in ("success", "partial"):
                logger.info(
                    "On-demand collection for %s: %s",
                    snapshot.asin, snapshot.status,
                )
                return True
            logger.warning(
                "On-demand collection for %s failed: %s",
                snapshot.asin, snapshot.errors,
            )
            return False
        except Exception as exc:
            logger.error("On-demand collection error: %s", exc)
            return False

    async def collect_batch(
        self,
        product_ids: list[UUID],
    ) -> int:
        """Collect snapshots for multiple products immediately.

        Args:
            product_ids: List of product UUIDs.

        Returns:
            Number of successfully collected products.
        """
        result = await self._service.collect_batch(product_ids=product_ids)
        return result.succeeded + result.partial
