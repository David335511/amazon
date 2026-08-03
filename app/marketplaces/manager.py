"""Marketplace manager — orchestrates provider lifecycle and unified access.

Design decisions:
- The manager is the ONLY entry point the rest of the platform uses to talk to
  marketplaces. No code outside this package may import a concrete provider.
- It wraps the registry and provides a clean, uniform API over all marketplaces.
- Handles provider initialization, configuration injection, and cleanup.
- Supports bulk operations across all enabled marketplaces.
- Error isolation — one marketplace's failure never affects another's.
- `_get_provider` returns only the `MarketplaceProvider` interface type.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.core.logging import get_logger
from app.marketplaces.base import MarketplaceProvider
from app.marketplaces.config import MarketplaceProviderConfig
from app.marketplaces.errors import (
    MarketplaceError,
    MarketplaceNotFoundError,
)
from app.marketplaces.models import (
    MarketplaceBuyBox,
    MarketplaceCompetition,
    MarketplaceFees,
    MarketplaceInventory,
    MarketplaceListing,
    MarketplaceOrder,
    MarketplacePricing,
    MarketplaceProduct,
    MarketplaceReturn,
    MarketplaceSalesEstimate,
    MarketplaceSearchResult,
    MarketplaceShipping,
)
from app.marketplaces.registry import MarketplaceRegistry

logger = get_logger(__name__)


class MarketplaceManager:
    """Manages marketplace provider lifecycle and provides unified access.

    This is the primary entry point for the rest of the application to interact
    with marketplaces. It handles:
    - Provider discovery and initialization
    - Configuration injection
    - Shared HTTP client management
    - Error isolation across providers
    - Bulk operations across all enabled marketplaces
    """

    def __init__(
        self,
        registry: MarketplaceRegistry | None = None,
        config: MarketplaceProviderConfig | None = None,
    ) -> None:
        self._registry = registry or MarketplaceRegistry()
        self._config = config or MarketplaceProviderConfig()
        self._http_client: httpx.AsyncClient | None = None
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize the marketplace manager.

        Discovers providers, creates a shared HTTP client, and initializes all
        enabled providers with their configuration.
        """
        if self._initialized:
            return

        self._registry.discover()
        self._http_client = httpx.AsyncClient(timeout=30.0)

        enabled = self._registry.get_enabled_providers(self._config)
        for code in enabled:
            try:
                config = self._config.marketplaces.get(code)
                config_dict = config.model_dump() if config else {}
                self._registry.get(code, config=config_dict, http_client=self._http_client)
                logger.info("Initialized marketplace provider: %s", code)
            except Exception as exc:
                logger.error("Failed to initialize marketplace %s: %s", code, exc)

        self._initialized = True
        logger.info(
            "Marketplace manager initialized with %d/%d providers enabled",
            len(enabled), len(self._registry.list_providers()),
        )

    async def shutdown(self) -> None:
        """Shut down the marketplace manager.

        Closes all provider instances and the shared HTTP client.
        """
        for code, instance in list(self._registry._instances.items()):
            try:
                await instance.close()
            except Exception as exc:
                logger.warning("Error closing marketplace %s: %s", code, exc)

        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

        self._initialized = False
        logger.info("Marketplace manager shut down")

    # ── Provider resolution ─────────────────────────────────

    def _get_provider(self, marketplace_code: str) -> MarketplaceProvider:
        """Get a provider instance by marketplace code (interface type only).

        Raises:
            MarketplaceNotFoundError: If the marketplace is unknown.
        """
        try:
            return self._registry.get(marketplace_code, http_client=self._http_client)
        except MarketplaceNotFoundError:
            raise
        except Exception as exc:
            raise MarketplaceError(str(exc), marketplace_code) from exc

    def list_marketplaces(self) -> list[dict[str, str]]:
        """List all discovered marketplaces with metadata."""
        return self._registry.list_providers()

    def get_enabled_marketplaces(self) -> list[str]:
        """Get codes of all enabled marketplaces."""
        return self._registry.get_enabled_providers(self._config)

    def get_capabilities(self, marketplace_code: str) -> dict[str, bool]:
        """Get supported capabilities for a marketplace."""
        return self._get_provider(marketplace_code).capabilities()

    # ── Single-Marketplace Operations ───────────────────────

    async def search(
        self,
        marketplace_code: str,
        query: str,
        *,
        page: int = 1,
        page_size: int = 20,
    ) -> list[MarketplaceSearchResult]:
        """Search a marketplace catalog by keyword."""
        provider = self._get_provider(marketplace_code)
        return await provider.search(query, page=page, page_size=page_size)

    async def lookup(
        self,
        marketplace_code: str,
        external_id: str,
    ) -> MarketplaceProduct | None:
        """Look up a product on a marketplace."""
        provider = self._get_provider(marketplace_code)
        return await provider.lookup(external_id)

    async def pricing(
        self,
        marketplace_code: str,
        external_id: str,
    ) -> MarketplacePricing | None:
        """Get pricing for a product on a marketplace."""
        provider = self._get_provider(marketplace_code)
        return await provider.pricing(external_id)

    async def fees(
        self,
        marketplace_code: str,
        external_id: str,
        price: Any | None = None,
    ) -> MarketplaceFees | None:
        """Get fees for a product on a marketplace."""
        provider = self._get_provider(marketplace_code)
        return await provider.fees(external_id, price=price)

    async def inventory(
        self,
        marketplace_code: str,
        external_id: str,
    ) -> MarketplaceInventory | None:
        """Get inventory for a product on a marketplace."""
        provider = self._get_provider(marketplace_code)
        return await provider.inventory(external_id)

    async def orders(
        self,
        marketplace_code: str,
        *,
        limit: int = 50,
    ) -> list[MarketplaceOrder]:
        """Get recent orders from a marketplace."""
        provider = self._get_provider(marketplace_code)
        return await provider.orders(limit=limit)

    async def listings(
        self,
        marketplace_code: str,
        *,
        status: str | None = None,
    ) -> list[MarketplaceListing]:
        """Get the seller's listings on a marketplace."""
        provider = self._get_provider(marketplace_code)
        return await provider.listings(status=status)

    async def competition(
        self,
        marketplace_code: str,
        external_id: str,
    ) -> MarketplaceCompetition | None:
        """Get competition for a product on a marketplace."""
        provider = self._get_provider(marketplace_code)
        return await provider.competition(external_id)

    async def sales_estimate(
        self,
        marketplace_code: str,
        external_id: str,
    ) -> MarketplaceSalesEstimate | None:
        """Get sales estimate for a product on a marketplace."""
        provider = self._get_provider(marketplace_code)
        return await provider.sales_estimate(external_id)

    async def buybox(
        self,
        marketplace_code: str,
        external_id: str,
    ) -> MarketplaceBuyBox | None:
        """Get Buy Box status for a product on a marketplace."""
        provider = self._get_provider(marketplace_code)
        return await provider.buybox(external_id)

    async def shipping(
        self,
        marketplace_code: str,
        external_id: str,
        *,
        quantity: int = 1,
        postal_code: str | None = None,
    ) -> MarketplaceShipping | None:
        """Get shipping options for a product on a marketplace."""
        provider = self._get_provider(marketplace_code)
        return await provider.shipping(
            external_id, quantity=quantity, postal_code=postal_code,
        )

    async def returns(
        self,
        marketplace_code: str,
        *,
        limit: int = 50,
    ) -> list[MarketplaceReturn]:
        """Get recent returns from a marketplace."""
        provider = self._get_provider(marketplace_code)
        return await provider.returns(limit=limit)

    # ── Cross-Marketplace Operations ────────────────────────

    async def search_all(
        self,
        query: str,
        *,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, list[MarketplaceSearchResult]]:
        """Search across all enabled marketplaces.

        Each marketplace is searched independently; failures are isolated and
        logged rather than propagating.

        Returns:
            Dict mapping marketplace_code to its search results.
        """
        results: dict[str, list[MarketplaceSearchResult]] = {}
        for code in self.get_enabled_marketplaces():
            try:
                items = await self.search(code, query, page=page, page_size=page_size)
                if items:
                    results[code] = items
            except Exception as exc:
                logger.warning("Search failed for marketplace %s: %s", code, exc)
        return results
