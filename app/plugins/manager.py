"""Plugin manager — orchestrates plugin lifecycle and provides unified access.

Design decisions:
- The manager wraps the registry and provides a clean API for the rest
  of the application.
- It handles plugin initialization, configuration injection, and cleanup.
- Supports bulk operations across all enabled suppliers.
- Error isolation — one supplier failure doesn't affect others.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.core.logging import get_logger
from app.plugins.base import BaseSupplierPlugin
from app.plugins.config import SupplierConfig, SupplierPluginConfig
from app.plugins.errors import PluginError, PluginNotFoundError
from app.plugins.models import (
    SupplierAvailability,
    SupplierCoupon,
    SupplierInventory,
    SupplierPricing,
    SupplierProductLookup,
    SupplierProductSearchResult,
    SupplierShipping,
)
from app.plugins.registry import PluginRegistry

logger = get_logger(__name__)


class PluginManager:
    """Manages supplier plugin lifecycle and provides unified access.

    This is the primary entry point for the rest of the application
    to interact with supplier plugins. It handles:
    - Plugin discovery and initialization
    - Configuration injection
    - Shared HTTP client management
    - Error isolation across suppliers
    - Bulk operations across all enabled suppliers
    """

    def __init__(
        self,
        registry: PluginRegistry | None = None,
        config: SupplierPluginConfig | None = None,
    ) -> None:
        self._registry = registry or PluginRegistry()
        self._config = config or SupplierPluginConfig()
        self._http_client: httpx.AsyncClient | None = None
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize the plugin manager.

        Discovers plugins, creates a shared HTTP client, and
        initializes all enabled plugins with their configuration.
        """
        if self._initialized:
            return

        self._registry.discover()
        self._http_client = httpx.AsyncClient(timeout=30.0)

        # Initialize enabled plugins
        enabled = self._registry.get_enabled_plugins(self._config)
        for code in enabled:
            try:
                supplier_config = self._config.suppliers.get(code)
                config_dict = supplier_config.model_dump() if supplier_config else {}
                self._registry.get(code, config=config_dict, http_client=self._http_client)
                logger.info("Initialized plugin: %s", code)
            except Exception as exc:
                logger.error("Failed to initialize plugin %s: %s", code, exc)

        self._initialized = True
        logger.info(
            "Plugin manager initialized with %d/%d plugins enabled",
            len(enabled), len(self._registry.list_plugins()),
        )

    async def shutdown(self) -> None:
        """Shut down the plugin manager.

        Closes all plugin instances and the shared HTTP client.
        """
        for code, instance in list(self._registry._instances.items()):
            try:
                await instance.close()
            except Exception as exc:
                logger.warning("Error closing plugin %s: %s", code, exc)

        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

        self._initialized = False
        logger.info("Plugin manager shut down")

    # ── Single Supplier Operations ──────────────────────────

    def _get_plugin(self, supplier_code: str) -> BaseSupplierPlugin:
        """Get a plugin instance by supplier code.

        Raises:
            PluginNotFoundError: If the plugin is not found.
        """
        try:
            return self._registry.get(supplier_code, http_client=self._http_client)
        except PluginNotFoundError:
            raise
        except Exception as exc:
            raise PluginError(str(exc), supplier_code) from exc

    async def search(
        self,
        supplier_code: str,
        query: str,
        *,
        page: int = 1,
        page_size: int = 20,
    ) -> list[SupplierProductSearchResult]:
        """Search for products from a specific supplier."""
        plugin = self._get_plugin(supplier_code)
        return await plugin.search(query, page=page, page_size=page_size)

    async def lookup(
        self,
        supplier_code: str,
        sku: str,
    ) -> SupplierProductLookup | None:
        """Look up a product by SKU from a specific supplier."""
        plugin = self._get_plugin(supplier_code)
        return await plugin.lookup(sku)

    async def pricing(
        self,
        supplier_code: str,
        sku: str,
    ) -> SupplierPricing | None:
        """Get pricing from a specific supplier."""
        plugin = self._get_plugin(supplier_code)
        return await plugin.pricing(sku)

    async def inventory(
        self,
        supplier_code: str,
        sku: str,
    ) -> SupplierInventory | None:
        """Get inventory from a specific supplier."""
        plugin = self._get_plugin(supplier_code)
        return await plugin.inventory(sku)

    async def shipping(
        self,
        supplier_code: str,
        sku: str,
        *,
        quantity: int = 1,
        postal_code: str | None = None,
    ) -> SupplierShipping | None:
        """Get shipping options from a specific supplier."""
        plugin = self._get_plugin(supplier_code)
        return await plugin.shipping(sku, quantity=quantity, postal_code=postal_code)

    async def coupon(
        self,
        supplier_code: str,
        code: str | None = None,
    ) -> list[SupplierCoupon]:
        """Get coupons from a specific supplier."""
        plugin = self._get_plugin(supplier_code)
        return await plugin.coupon(code)

    async def availability(
        self,
        supplier_code: str,
        sku: str,
    ) -> SupplierAvailability | None:
        """Check availability from a specific supplier."""
        plugin = self._get_plugin(supplier_code)
        return await plugin.availability(sku)

    # ── Cross-Supplier Operations ───────────────────────────

    async def search_all(
        self,
        query: str,
        *,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, list[SupplierProductSearchResult]]:
        """Search for products across all enabled suppliers.

        Returns:
            Dict mapping supplier_code to list of search results.
        """
        results: dict[str, list[SupplierProductSearchResult]] = {}
        enabled = self._registry.get_enabled_plugins(self._config)

        for code in enabled:
            try:
                plugin = self._get_plugin(code)
                items = await plugin.search(query, page=page, page_size=page_size)
                if items:
                    results[code] = items
            except Exception as exc:
                logger.warning("Search failed for supplier %s: %s", code, exc)

        return results

    async def lookup_all(
        self,
        sku_map: dict[str, str],
    ) -> dict[str, SupplierProductLookup | None]:
        """Look up products across multiple suppliers.

        Args:
            sku_map: Dict mapping supplier_code to SKU.

        Returns:
            Dict mapping supplier_code to lookup result.
        """
        results: dict[str, SupplierProductLookup | None] = {}
        for code, sku in sku_map.items():
            try:
                results[code] = await self.lookup(code, sku)
            except Exception as exc:
                logger.warning("Lookup failed for supplier %s: %s", code, exc)
                results[code] = None
        return results

    async def compare_pricing(
        self,
        sku_map: dict[str, str],
    ) -> dict[str, SupplierPricing | None]:
        """Compare pricing across multiple suppliers.

        Args:
            sku_map: Dict mapping supplier_code to SKU.

        Returns:
            Dict mapping supplier_code to pricing info.
        """
        results: dict[str, SupplierPricing | None] = {}
        for code, sku in sku_map.items():
            try:
                results[code] = await self.pricing(code, sku)
            except Exception as exc:
                logger.warning("Pricing check failed for supplier %s: %s", code, exc)
                results[code] = None
        return results

    # ── Plugin Metadata ────────────────────────────────────

    def list_suppliers(self) -> list[dict[str, str]]:
        """List all discovered suppliers with metadata."""
        return self._registry.list_plugins()

    def get_enabled_suppliers(self) -> list[str]:
        """Get codes of all enabled suppliers."""
        return self._registry.get_enabled_plugins(self._config)
