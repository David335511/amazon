"""Background refresh job for retailer (Walmart / Home Depot) lookups.

Design decisions:
- Mirrors the Keepa integration's scheduler shape (asyncio task, graceful
  shutdown, error isolation per product).
- Paces lookups against the monthly SerpApi search budget via
  ``RetailerBudget.daily_allowance()``: on each cycle it refreshes up to
  ``daily_allowance`` products (e.g. ~8/day for a 250/month plan), so the
  month's quota is spread out instead of being consumed in the first few runs.
- The monthly budget is also enforced at the HTTP-client level
  (``RetailerBudgetExceededError``), so even manual/one-off lookups can never
  overrun the quota.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from app.core.logging import get_logger
from app.integrations.retailers.budget import RetailerBudget
from app.integrations.retailers.client import RetailerBudgetExceededError
from app.integrations.retailers.models import RetailerLookupRequest
from app.integrations.retailers.service import RetailerService

logger = get_logger(__name__)


class RetailerRefreshJob:
    """Background job that periodically refreshes retailer product data.

    Each cycle fetches up to ``RetailerBudget.daily_allowance()`` products from
    ``monitor_provider`` (a callable returning the lookups to check), so the
    monthly SerpApi search budget lasts the whole month.
    """

    def __init__(
        self,
        service: RetailerService,
        budget: RetailerBudget,
        monitor_provider: Callable[[], list[RetailerLookupRequest]] | None = None,
        interval: int = 21600,  # 6 hours
    ) -> None:
        self._service = service
        self._budget = budget
        self._monitor_provider = monitor_provider
        self._interval = interval
        self._tasks: list[asyncio.Task[object]] = []
        self._running = False

    # ── Lifecycle ───────────────────────────────────────────

    def start(self) -> None:
        """Start the background refresh loop."""
        if self._running:
            logger.warning("RetailerRefreshJob is already running")
            return
        self._running = True
        task = asyncio.create_task(self._run())
        self._tasks.append(task)
        logger.info("Started retailer refresh job (interval=%ds)", self._interval)

    async def stop(self) -> None:
        """Stop the background refresh loop gracefully."""
        self._running = False
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
            self._tasks.clear()
        logger.info("RetailerRefreshJob stopped")

    # ── Refresh Loop ────────────────────────────────────────

    async def _run(self) -> None:
        """Periodically refresh watched retailer products, budget permitting."""
        while self._running:
            try:
                await asyncio.sleep(self._interval)

                if not self._running:
                    break
                if self._monitor_provider is None:
                    continue

                requests = self._monitor_provider()
                if not requests:
                    logger.debug("Retailer monitor list is empty; skipping cycle")
                    continue

                await self._refresh_cycle(requests)

            except asyncio.CancelledError:
                logger.info("Retailer refresh task cancelled")
                break
            except Exception as exc:
                logger.error("Retailer refresh error: %s", exc)
                await asyncio.sleep(60)  # Wait before retrying

    async def _refresh_cycle(self, requests: list[RetailerLookupRequest]) -> int:
        """Run a single refresh cycle over ``requests``, budget permitting.

        Fetches at most ``RetailerBudget.daily_allowance()`` products and stops
        early once the monthly budget is exhausted.

        Returns the number of products refreshed.
        """
        allowance = await self._budget.daily_allowance()
        if allowance <= 0:
            logger.info("Retailer monthly budget exhausted; skipping cycle")
            return 0

        logger.info(
            "Refreshing up to %d retailer products (daily allowance=%d)",
            allowance,
            allowance,
        )
        refreshed = 0
        for request in requests:
            if refreshed >= allowance:
                break
            try:
                await self._service.fetch_product(request)
                refreshed += 1
            except RetailerBudgetExceededError:
                logger.info("Retailer monthly budget exhausted mid-cycle")
                break
            except Exception as exc:
                logger.error(
                    "Retailer refresh failed for %s (%s): %s",
                    request.product_id,
                    request.provider.value,
                    exc,
                )

        logger.info("Retailer refresh cycle complete (%d refreshed)", refreshed)
        return refreshed

    # ── One-shot Refresh ────────────────────────────────────

    async def refresh_single(self, request: RetailerLookupRequest) -> bool:
        """Refresh a single retailer product immediately (budget permitting).

        Returns True on success, False if the request failed or the monthly
        budget is exhausted.
        """
        try:
            await self._service.fetch_product(request)
            return True
        except RetailerBudgetExceededError:
            logger.info("Retailer monthly budget exhausted; refusing %s", request.product_id)
            return False
        except Exception as exc:
            logger.error(
                "Retailer single refresh failed for %s (%s): %s",
                request.product_id,
                request.provider.value,
                exc,
            )
            return False
