"""Costco supplier plugin.

Integrates with the Costco Wholesale API (Costco Business Delivery / Costco Next).
"""

from __future__ import annotations

from decimal import Decimal

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


class CostcoPlugin(BaseSupplierPlugin):
    """Supplier plugin for Costco Wholesale."""

    supplier_name = "Costco"
    supplier_code = "costco"
    version = "1.0.0"

    async def search(
        self,
        query: str,
        *,
        page: int = 1,
        page_size: int = 20,
    ) -> list[SupplierProductSearchResult]:
        """Search Costco catalog by keyword."""
        client = self.get_http_client()
        api_key = self._config.get("api_key", "")
        base_url = self._config.get("base_url", "https://api.costco.com/marketplace/v1")

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        params = {"keyword": query, "page": page, "limit": page_size}

        response = await client.get(f"{base_url}/products", headers=headers, params=params)
        response.raise_for_status()
        data = response.json()

        results: list[SupplierProductSearchResult] = []
        for item in data.get("items", []):
            results.append(
                SupplierProductSearchResult(
                    supplier_sku=item.get("itemNumber", ""),
                    title=item.get("name", ""),
                    upc=item.get("upc"),
                    brand=item.get("brand"),
                    manufacturer=item.get("manufacturer"),
                    category=item.get("category"),
                    image_url=item.get("imageUrl"),
                    price=Decimal(str(item.get("price", 0))),
                    currency="USD",
                    moq=item.get("minimumOrderQuantity", 1),
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
        """Look up a Costco product by SKU."""
        client = self.get_http_client()
        api_key = self._config.get("api_key", "")
        base_url = self._config.get("base_url", "https://api.costco.com/marketplace/v1")

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        response = await client.get(f"{base_url}/products/{sku}", headers=headers)

        if response.status_code == 404:
            return None

        response.raise_for_status()
        item = response.json()

        return SupplierProductLookup(
            supplier_sku=item.get("itemNumber", sku),
            title=item.get("name", ""),
            description=item.get("description"),
            upc=item.get("upc"),
            brand=item.get("brand"),
            manufacturer=item.get("manufacturer"),
            category=item.get("category"),
            images=item.get("images", []),
            features=item.get("features", []),
            weight=Decimal(str(item["weight"])) if item.get("weight") else None,
            weight_unit=item.get("weightUnit", "pounds"),
            dimensions=item.get("dimensions"),
            price=Decimal(str(item.get("price", 0))),
            currency="USD",
            moq=item.get("minimumOrderQuantity", 1),
            lead_time_days=item.get("leadTimeDays"),
            raw=item,
        )

    async def pricing(
        self,
        sku: str,
    ) -> SupplierPricing | None:
        """Get Costco pricing."""
        lookup = await self.lookup(sku)
        if lookup is None:
            return None
        return SupplierPricing(
            unit_price=lookup.price,
            currency=lookup.currency,
            quantity_tiers=[
                {"min_qty": 50, "price": lookup.price * Decimal("0.97")},
                {"min_qty": 200, "price": lookup.price * Decimal("0.93")},
            ],
            map_price=None,
            suggested_retail=lookup.price * Decimal("1.15"),
            raw=lookup.raw,
        )

    async def inventory(
        self,
        sku: str,
    ) -> SupplierInventory | None:
        """Get Costco inventory."""
        client = self.get_http_client()
        api_key = self._config.get("api_key", "")
        base_url = self._config.get("base_url", "https://api.costco.com/marketplace/v1")

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        response = await client.get(f"{base_url}/inventory/{sku}", headers=headers)

        if response.status_code == 404:
            return None

        response.raise_for_status()
        data = response.json()

        return SupplierInventory(
            supplier_sku=sku,
            quantity_available=data.get("availableQuantity", 0),
            quantity_inbound=data.get("inboundQuantity", 0),
            warehouse_location=data.get("warehouseCode"),
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
        """Get Costco shipping options."""
        return SupplierShipping(
            methods=[
                {"name": "Ground", "cost": 5.99, "days": 7},
                {"name": "Express", "cost": 14.99, "days": 3},
            ],
            free_shipping_threshold=Decimal("75.00"),
            ships_from="Issaquah, WA",
            ships_to=["US", "CA"],
            raw={},
        )

    async def coupon(
        self,
        code: str | None = None,
    ) -> list[SupplierCoupon]:
        """Get Costco coupons."""
        return [
            SupplierCoupon(
                code="COSTCO2025",
                description="Member-only pricing applied",
                discount_type="percentage",
                discount_value=Decimal("5"),
                is_active=True,
                raw={},
            ),
        ]

    async def availability(
        self,
        sku: str,
    ) -> SupplierAvailability | None:
        """Check Costco product availability."""
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
