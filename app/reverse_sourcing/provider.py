"""Supplier provider seam for reverse sourcing.

The reverse-sourcing engine talks ONLY to a `SupplierProvider` — never to a
plugin directly. This is what makes it plug-and-play: adding a supplier is just
adding a file to ``app/plugins/suppliers/`` (auto-discovered by the plugin
registry) and the engine keeps working unchanged. `PluginManagerProvider`
adapts the existing `PluginManager` to this interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.plugins import (
    PluginManager,
    SupplierAvailability,
    SupplierCoupon,
    SupplierPricing,
    SupplierProductSearchResult,
    SupplierShipping,
)


class SupplierProvider(ABC):
    """Abstract access to supplier plugins via their standard interface."""

    @abstractmethod
    def enabled_suppliers(self) -> list[str]:
        """Return the codes of all enabled suppliers."""

    @abstractmethod
    async def find_product(
        self,
        code: str,
        query: str,
        upc: str | None,
    ) -> SupplierProductSearchResult | None:
        """Find the product at a supplier matching an ASIN/UPC query.

        Returns the matching `SupplierProductSearchResult` (which carries the
        supplier's SKU) or None if the supplier does not carry it.
        """

    @abstractmethod
    async def pricing(self, code: str, sku: str) -> SupplierPricing | None:
        """Get current pricing for a supplier SKU."""

    @abstractmethod
    async def availability(self, code: str, sku: str) -> SupplierAvailability | None:
        """Get stock/availability for a supplier SKU."""

    @abstractmethod
    async def shipping(
        self,
        code: str,
        sku: str,
        quantity: int,
        postal_code: str | None,
    ) -> SupplierShipping | None:
        """Get shipping options for a supplier SKU."""

    @abstractmethod
    async def coupon(self, code: str) -> list[SupplierCoupon]:
        """Get active coupons/discounts from a supplier."""


class PluginManagerProvider(SupplierProvider):
    """Adapts the existing `PluginManager` to the `SupplierProvider` seam."""

    def __init__(self, manager: PluginManager) -> None:
        self._manager = manager

    def enabled_suppliers(self) -> list[str]:
        return self._manager.get_enabled_suppliers()

    async def find_product(
        self,
        code: str,
        query: str,
        upc: str | None,
    ) -> SupplierProductSearchResult | None:
        try:
            results = await self._manager.search(code, query, page_size=10)
        except Exception:
            return None
        if not results:
            return None
        if upc:
            for result in results:
                if result.upc and str(result.upc) == str(upc):
                    return result
        return results[0]

    async def pricing(self, code: str, sku: str) -> SupplierPricing | None:
        try:
            return await self._manager.pricing(code, sku)
        except Exception:
            return None

    async def availability(self, code: str, sku: str) -> SupplierAvailability | None:
        try:
            return await self._manager.availability(code, sku)
        except Exception:
            return None

    async def shipping(
        self,
        code: str,
        sku: str,
        quantity: int,
        postal_code: str | None,
    ) -> SupplierShipping | None:
        try:
            return await self._manager.shipping(
                code, sku, quantity=quantity, postal_code=postal_code
            )
        except Exception:
            return None

    async def coupon(self, code: str) -> list[SupplierCoupon]:
        try:
            return await self._manager.coupon(code)
        except Exception:
            return []
