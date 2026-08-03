"""Abstract base class for all supplier plugins.

Design decisions:
- ABC enforces that all plugins implement the same 8 methods.
- Each method returns standardized Pydantic models — no supplier-specific types.
- Plugins receive a config dict and an optional HTTP client.
- Methods are async for non-blocking I/O.
- The `supplier_name` and `supplier_code` class attributes identify the plugin.
- Plugins are discovered by subclassing `BaseSupplierPlugin`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import httpx

from app.plugins.models import (
    SupplierAvailability,
    SupplierCoupon,
    SupplierInventory,
    SupplierPricing,
    SupplierProductLookup,
    SupplierProductSearchResult,
    SupplierShipping,
)


class BaseSupplierPlugin(ABC):
    """Abstract base class that all supplier plugins must implement.

    Each plugin represents one supplier (e.g., Walmart, Target).
    All 8 methods must be implemented. Methods return standardized
    Pydantic models — no supplier-specific types leak out of plugins.

    Class attributes:
        supplier_name: Human-readable supplier name (e.g., "Walmart").
        supplier_code: Short code for the supplier (e.g., "walmart").
        version: Plugin version string.
    """

    supplier_name: str = ""
    supplier_code: str = ""
    version: str = "1.0.0"

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        http_client: httpx.AsyncClient | None = None,
        crawler: Any | None = None,
    ) -> None:
        """Initialize the plugin.

        Args:
            config: Supplier-specific configuration (API keys, endpoints, etc.).
            http_client: Shared HTTP client for connection pooling.
            crawler: Optional shared browser-automation Crawler. Supplier plugins
                that need to scrape a website should use this instead of
                implementing browser automation themselves.
        """
        self._config = config or {}
        self._http_client = http_client
        self._crawler = crawler

    def get_crawler(self) -> Any:
        """Get the shared browser-automation crawler for this plugin.

        Use this for browser-based scraping instead of hand-rolling Playwright.
        The crawler provides rate limiting, retries, CAPTCHA detection, proxy
        rotation, session/cookie persistence, screenshots and HTML archiving.

        Raises:
            ValueError: If no crawler was injected (caller must wire it via
                the plugin manager).
        """
        if self._crawler is None:
            raise ValueError(
                f"Plugin '{self.supplier_code}' has no crawler injected. "
                "Wire a crawler through the plugin manager."
            )
        return self._crawler

    @abstractmethod
    async def search(
        self,
        query: str,
        *,
        page: int = 1,
        page_size: int = 20,
    ) -> list[SupplierProductSearchResult]:
        """Search for products by keyword.

        Args:
            query: Search query string.
            page: Page number (1-indexed).
            page_size: Results per page.

        Returns:
            List of search results.
        """

    @abstractmethod
    async def lookup(
        self,
        sku: str,
    ) -> SupplierProductLookup | None:
        """Look up a product by the supplier's SKU.

        Args:
            sku: Supplier's SKU identifier.

        Returns:
            Product details or None if not found.
        """

    @abstractmethod
    async def pricing(
        self,
        sku: str,
    ) -> SupplierPricing | None:
        """Get pricing information for a product.

        Args:
            sku: Supplier's SKU identifier.

        Returns:
            Pricing information or None if not found.
        """

    @abstractmethod
    async def inventory(
        self,
        sku: str,
    ) -> SupplierInventory | None:
        """Get inventory/stock information for a product.

        Args:
            sku: Supplier's SKU identifier.

        Returns:
            Inventory information or None if not found.
        """

    @abstractmethod
    async def shipping(
        self,
        sku: str,
        *,
        quantity: int = 1,
        postal_code: str | None = None,
    ) -> SupplierShipping | None:
        """Get shipping options and costs for a product.

        Args:
            sku: Supplier's SKU identifier.
            quantity: Number of units.
            postal_code: Destination postal code for rate calculation.

        Returns:
            Shipping information or None if not available.
        """

    @abstractmethod
    async def coupon(
        self,
        code: str | None = None,
    ) -> list[SupplierCoupon]:
        """Get available coupons/discounts.

        Args:
            code: Specific coupon code to look up (None = all active).

        Returns:
            List of available coupons.
        """

    @abstractmethod
    async def availability(
        self,
        sku: str,
    ) -> SupplierAvailability | None:
        """Check product availability.

        Args:
            sku: Supplier's SKU identifier.

        Returns:
            Availability status or None if not found.
        """

    def get_http_client(self) -> httpx.AsyncClient:
        """Get or create an HTTP client for this plugin.

        Uses the shared client if provided, otherwise creates one.
        """
        if self._http_client is not None:
            return self._http_client
        return httpx.AsyncClient(timeout=30.0)

    async def close(self) -> None:  # noqa: B027 - optional hook for subclasses
        """Clean up resources. Override if the plugin holds resources."""
