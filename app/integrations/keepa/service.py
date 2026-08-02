"""Keepa service layer — business logic for fetching and processing Keepa data.

Design decisions:
- The service orchestrates the client (API calls) and repository (DB storage).
- It handles the full lifecycle: fetch → parse → store → return.
- Background refresh jobs use this service to update data periodically.
- All methods are idempotent — calling them multiple times is safe.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.integrations.keepa.client import KeepaClient
from app.integrations.keepa.models import (
    KeepaBestSellersRequest,
    KeepaBestSellersResponse,
    KeepaCategory,
    KeepaCategoryRequest,
    KeepaProductRequest,
    KeepaProductResponse,
)
from app.integrations.keepa.repository import KeepaRepository

logger = get_logger(__name__)


class KeepaService:
    """Business logic for Keepa data operations.

    Provides high-level methods that combine API fetching with
    database persistence. Used by API routes and background jobs.
    """

    def __init__(
        self,
        client: KeepaClient,
        repository: KeepaRepository,
    ) -> None:
        self._client = client
        self._repository = repository

    # ── Product Data ────────────────────────────────────────

    async def fetch_and_store_product(
        self,
        asin: str,
        domain: str = "com",
        store_in_db: bool = True,
    ) -> KeepaProductResponse:
        """Fetch product data from Keepa and optionally store in database.

        This is the primary method for retrieving product data. It:
        1. Fetches data from the Keepa API (with caching)
        2. Parses the response into our model
        3. Optionally stores all data in the database
        4. Returns the parsed response

        Args:
            asin: Amazon ASIN to fetch.
            domain: Amazon domain code (com, co.uk, de, etc.).
            store_in_db: If True, persist data to the database.

        Returns:
            Parsed Keepa product response with all available data.
        """
        request = KeepaProductRequest(asin=asin, domain=domain)
        data = await self._client.get_product(request)

        if store_in_db:
            try:
                product = await self._repository.store_full_product_data(data)
                logger.info(
                    "Stored Keepa data for ASIN %s (product_id=%s)",
                    asin, product.id,
                )
            except Exception as exc:
                logger.error(
                    "Failed to store Keepa data for ASIN %s: %s",
                    asin, exc,
                )

        return data

    async def fetch_and_store_batch(
        self,
        asins: list[str],
        domain: str = "com",
        max_concurrent: int = 5,
    ) -> list[KeepaProductResponse]:
        """Fetch and store data for multiple ASINs.

        Args:
            asins: List of ASINs to fetch.
            domain: Amazon domain code.
            max_concurrent: Maximum concurrent API requests.

        Returns:
            List of parsed product responses.
        """
        results: list[KeepaProductResponse] = []
        for asin in asins:
            try:
                data = await self.fetch_and_store_product(asin, domain)
                results.append(data)
            except Exception as exc:
                logger.error("Failed to process ASIN %s: %s", asin, exc)
        return results

    # ── Category Data ──────────────────────────────────────

    async def get_category(
        self,
        category_id: int | None = None,
        domain: str = "com",
    ) -> list[KeepaCategory]:
        """Retrieve Amazon category information.

        Args:
            category_id: Amazon category node ID (None = root categories).
            domain: Amazon domain code.

        Returns:
            List of category objects.
        """
        request = KeepaCategoryRequest(category_id=category_id, domain=domain)
        return await self._client.get_category(request)

    async def get_best_sellers(
        self,
        category_id: int,
        domain: str = "com",
    ) -> KeepaBestSellersResponse:
        """Retrieve best sellers list for a category.

        Args:
            category_id: Amazon category node ID.
            domain: Amazon domain code.

        Returns:
            Best sellers response with ranked ASIN list.
        """
        request = KeepaBestSellersRequest(category_id=category_id, domain=domain)
        return await self._client.get_best_sellers(request)

    # ── Product Lookup ──────────────────────────────────────

    async def lookup_product_by_asin(
        self,
        asin: str,
        domain: str = "com",
    ) -> KeepaProductResponse | None:
        """Look up a product by ASIN, checking the database first.

        If the product exists in the database with recent data (within
        the cache TTL), return cached data. Otherwise, fetch from Keepa.

        Args:
            asin: Amazon ASIN.
            domain: Amazon domain code.

        Returns:
            Product response or None if not found.
        """
        # Always fetch from Keepa (with Redis caching handled by the client)
        try:
            return await self.fetch_and_store_product(asin, domain, store_in_db=True)
        except Exception as exc:
            logger.warning("Keepa lookup failed for ASIN %s: %s", asin, exc)
            return None

    # ── Refresh Operations ──────────────────────────────────

    async def refresh_product_data(
        self,
        product_id: UUID,
        asin: str,
        domain: str = "com",
    ) -> KeepaProductResponse | None:
        """Refresh data for an existing product.

        Fetches fresh data from Keepa and updates the database.
        Used by the background refresh scheduler.

        Args:
            product_id: Database product UUID.
            asin: Amazon ASIN.
            domain: Amazon domain code.

        Returns:
            Updated product response or None on failure.
        """
        try:
            return await self.fetch_and_store_product(asin, domain, store_in_db=True)
        except Exception as exc:
            logger.error(
                "Failed to refresh product %s (ASIN %s): %s",
                product_id, asin, exc,
            )
            return None

    async def refresh_watchlist_products(
        self,
        watchlist_items: list[dict[str, Any]],
    ) -> dict[str, int]:
        """Refresh data for all products in a user's watchlist.

        Args:
            watchlist_items: List of dicts with 'product_id', 'asin', 'domain'.

        Returns:
            Dict with 'success' and 'failed' counts.
        """
        results = {"success": 0, "failed": 0}
        for item in watchlist_items:
            try:
                result = await self.refresh_product_data(
                    product_id=item["product_id"],
                    asin=item["asin"],
                    domain=item.get("domain", "com"),
                )
                if result is not None:
                    results["success"] += 1
                else:
                    results["failed"] += 1
            except Exception:
                results["failed"] += 1

        logger.info(
            "Watchlist refresh complete: %d success, %d failed",
            results["success"], results["failed"],
        )
        return results
