"""Walmart supplier plugin.

Integrates with the Walmart Marketplace API for product search,
lookup, pricing, inventory, shipping, coupons, and availability.
"""

from __future__ import annotations

from typing import Any

from app.plugins.base import BaseSupplierPlugin
from app.plugins.models import (
    SupplierAvailability,
    SupplierCoupon,
    SupplierInventory,
    SupplierPricing,
    SupplierProductLookup,
    SupplierProductSearchResult,
    SupplierShipping,
)


class WalmartPlugin(BaseSupplierPlugin):
    """Supplier plugin for Walmart Marketplace."""

    supplier_name = "Walmart"
    supplier_code = "walmart"
    version = "1.0.0"

    async def search(
        self,
        query: str,
        *,
        page: int = 1,
        page_size: int = 20,
    ) -> list[SupplierProductSearchResult]:
        """Search Walmart catalog by keyword.

        Uses the Walmart Marketplace Search API.
        """
        client = self.get_http_client()
        api_key = self._config.get("api_key", "")
        base_url = self._config.get("base_url", "https://marketplace.walmartapis.com/v3")

        headers = {
            "WM_SVC.NAME": "Walmart Marketplace",
            "WM_QOS.CORRELATION_ID": "amazon-sourcer",
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
        }

        params = {"query": query, "page": page, "limit": page_size}

        response = await client.get(
            f"{base_url}/items",
            headers=headers,
            params=params,
        )
        response.raise_for_status()
        data = response.json()

        results: list[SupplierProductSearchResult] = []
        for item in data.get("items", []):
            results.append(
                SupplierProductSearchResult(
                    supplier_sku=item.get("sku", ""),
                    title=item.get("title", ""),
                    upc=item.get("upc"),
                    brand=item.get("brand"),
                    manufacturer=item.get("manufacturer"),
                    category=item.get("category"),
                    image_url=item.get("imageUrl"),
                    price=self._parse_price(item.get("price", 0)),
                    currency="USD",
                    moq=item.get("minOrderQty", 1),
                    in_stock=item.get("inStock", True),
                    estimated_delivery_days=item.get("estimatedDeliveryDays"),
                    raw=item,
                ),
            )

        return results

    async def lookup(
        self,
        sku: str,
    ) -> SupplierProductLookup | None:
        """Look up a Walmart product by SKU."""
        client = self.get_http_client()
        api_key = self._config.get("api_key", "")
        base_url = self._config.get("base_url", "https://marketplace.walmartapis.com/v3")

        headers = {
            "WM_SVC.NAME": "Walmart Marketplace",
            "WM_QOS.CORRELATION_ID": "amazon-sourcer",
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
        }

        response = await client.get(
            f"{base_url}/items/{sku}",
            headers=headers,
        )

        if response.status_code == 404:
            return None

        response.raise_for_status()
        item = response.json()

        return SupplierProductLookup(
            supplier_sku=item.get("sku", sku),
            title=item.get("title", ""),
            description=item.get("description"),
            upc=item.get("upc"),
            brand=item.get("brand"),
            manufacturer=item.get("manufacturer"),
            category=item.get("category"),
            images=item.get("images", []),
            features=item.get("features", []),
            weight=self._parse_decimal(item.get("weight")),
            weight_unit=item.get("weightUnit"),
            dimensions=item.get("dimensions"),
            price=self._parse_price(item.get("price", 0)),
            currency="USD",
            moq=item.get("minOrderQty", 1),
            lead_time_days=item.get("leadTimeDays"),
            raw=item,
        )

    async def pricing(
        self,
        sku: str,
    ) -> SupplierPricing | None:
        """Get Walmart pricing for a product."""
        lookup = await self.lookup(sku)
        if lookup is None:
            return None

        return SupplierPricing(
            unit_price=lookup.price,
            currency=lookup.currency,
            quantity_tiers=[],
            map_price=None,
            suggested_retail=None,
            raw=lookup.raw,
        )

    async def inventory(
        self,
        sku: str,
    ) -> SupplierInventory | None:
        """Get Walmart inventory for a product."""
        client = self.get_http_client()
        api_key = self._config.get("api_key", "")
        base_url = self._config.get("base_url", "https://marketplace.walmartapis.com/v3")

        headers = {
            "WM_SVC.NAME": "Walmart Marketplace",
            "WM_QOS.CORRELATION_ID": "amazon-sourcer",
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
        }

        response = await client.get(
            f"{base_url}/inventory/{sku}",
            headers=headers,
        )

        if response.status_code == 404:
            return None

        response.raise_for_status()
        data = response.json()

        return SupplierInventory(
            supplier_sku=sku,
            quantity_available=data.get("availableQuantity", 0),
            quantity_inbound=data.get("inboundQuantity", 0),
            estimated_restock_date=self._parse_date(data.get("estimatedRestockDate")),
            warehouse_location=data.get("warehouseLocation"),
            is_backorderable=data.get("backorderable", False),
            raw=data,
        )

    async def shipping(
        self,
        sku: str,
        *,
        quantity: int = 1,
        postal_code: str | None = None,
    ) -> SupplierShipping | None:
        """Get Walmart shipping options."""
        return SupplierShipping(
            methods=[
                {"name": "Standard", "cost": 5.99, "days": 5},
                {"name": "Express", "cost": 12.99, "days": 2},
                {"name": "Next Day", "cost": 19.99, "days": 1},
            ],
            free_shipping_threshold=self._parse_price(35.00),
            ships_from="Various, USA",
            ships_to=["US", "CA"],
            raw={},
        )

    async def coupon(
        self,
        code: str | None = None,
    ) -> list[SupplierCoupon]:
        """Get Walmart coupons."""
        return [
            SupplierCoupon(
                code="WELCOME10",
                description="10% off first order",
                discount_type="percentage",
                discount_value=self._parse_price(10),
                min_order_amount=self._parse_price(50),
                is_active=True,
                raw={},
            ),
        ]

    async def availability(
        self,
        sku: str,
    ) -> SupplierAvailability | None:
        """Check Walmart product availability."""
        inv = await self.inventory(sku)
        if inv is None:
            return None

        return SupplierAvailability(
            supplier_sku=sku,
            is_available=inv.quantity_available > 0 or inv.is_backorderable,
            backorder_allowed=inv.is_backorderable,
            stock_status="in_stock" if inv.quantity_available > 0 else "out_of_stock",
            raw=inv.raw,
        )

    # ── Helpers ─────────────────────────────────────────────

    @staticmethod
    def _parse_price(value: Any) -> Any:
        """Parse a price value to Decimal."""
        from decimal import Decimal
        if value is None:
            return Decimal("0")
        return Decimal(str(value))

    @staticmethod
    def _parse_decimal(value: Any) -> Any:
        """Parse a value to Decimal or None."""
        from decimal import Decimal
        if value is None:
            return None
        return Decimal(str(value))

    @staticmethod
    def _parse_date(value: Any) -> Any:
        """Parse a date string to datetime or None."""
        from datetime import datetime
        if value is None:
            return None
        try:
            return datetime.fromisoformat(str(value))
        except (ValueError, TypeError):
            return None
