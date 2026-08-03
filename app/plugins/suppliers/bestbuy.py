"""Best Buy supplier plugin.

Integrates with the Best Buy Marketplace API (Best Buy Marketplace / Partner API).
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


class BestBuyPlugin(BaseSupplierPlugin):
    """Supplier plugin for Best Buy Marketplace."""

    supplier_name = "Best Buy"
    supplier_code = "bestbuy"
    version = "1.0.0"

    async def search(
        self,
        query: str,
        *,
        page: int = 1,
        page_size: int = 20,
    ) -> list[SupplierProductSearchResult]:
        """Search Best Buy catalog by keyword."""
        client = self.get_http_client()
        api_key = self._config.get("api_key", "")
        base_url = self._config.get("base_url", "https://api.bestbuy.com/marketplace/v1")

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        params = {"search": query, "page": page, "pageSize": page_size}

        response = await client.get(f"{base_url}/catalog/products", headers=headers, params=params)
        response.raise_for_status()
        data = response.json()

        results: list[SupplierProductSearchResult] = []
        for item in data.get("products", []):
            results.append(
                SupplierProductSearchResult(
                    supplier_sku=item.get("sku", ""),
                    title=item.get("name", ""),
                    upc=item.get("upc"),
                    brand=item.get("manufacturer"),
                    manufacturer=item.get("manufacturer"),
                    category=item.get("categoryPath"),
                    image_url=item.get("image"),
                    price=Decimal(str(item.get("salePrice", item.get("regularPrice", 0)))),
                    currency="USD",
                    moq=item.get("minOrderQty", 1),
                    in_stock=item.get("onlineAvailability", True),
                    estimated_delivery_days=item.get("estimatedDeliveryDays"),
                    raw=item,
                ),
            )

        return results

    async def lookup(
        self,
        sku: str,
    ) -> SupplierProductLookup | None:
        """Look up a Best Buy product by SKU."""
        client = self.get_http_client()
        api_key = self._config.get("api_key", "")
        base_url = self._config.get("base_url", "https://api.bestbuy.com/marketplace/v1")

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        response = await client.get(f"{base_url}/catalog/products/{sku}", headers=headers)

        if response.status_code == 404:
            return None

        response.raise_for_status()
        item = response.json()

        return SupplierProductLookup(
            supplier_sku=item.get("sku", sku),
            title=item.get("name", ""),
            description=item.get("description"),
            upc=item.get("upc"),
            brand=item.get("manufacturer"),
            manufacturer=item.get("manufacturer"),
            category=item.get("categoryPath"),
            images=item.get("images", []),
            features=item.get("features", []),
            weight=Decimal(str(item["weight"])) if item.get("weight") else None,
            weight_unit=item.get("weightUnit", "pounds"),
            dimensions=item.get("dimensions"),
            price=Decimal(str(item.get("salePrice", item.get("regularPrice", 0)))),
            currency="USD",
            moq=item.get("minOrderQty", 1),
            lead_time_days=item.get("leadTimeDays"),
            raw=item,
        )

    async def pricing(
        self,
        sku: str,
    ) -> SupplierPricing | None:
        """Get Best Buy pricing."""
        lookup = await self.lookup(sku)
        if lookup is None:
            return None
        return SupplierPricing(
            unit_price=lookup.price,
            currency=lookup.currency,
            quantity_tiers=[
                {"min_qty": 5, "price": lookup.price * Decimal("0.98")},
                {"min_qty": 25, "price": lookup.price * Decimal("0.95")},
                {"min_qty": 100, "price": lookup.price * Decimal("0.90")},
            ],
            map_price=lookup.price * Decimal("0.95"),
            suggested_retail=lookup.price * Decimal("1.20"),
            raw=lookup.raw,
        )

    async def inventory(
        self,
        sku: str,
    ) -> SupplierInventory | None:
        """Get Best Buy inventory."""
        client = self.get_http_client()
        api_key = self._config.get("api_key", "")
        base_url = self._config.get("base_url", "https://api.bestbuy.com/marketplace/v1")

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
            quantity_available=data.get("onHandQuantity", 0),
            quantity_inbound=data.get("inboundQuantity", 0),
            warehouse_location=data.get("distributionCenter"),
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
        """Get Best Buy shipping options."""
        return SupplierShipping(
            methods=[
                {"name": "Standard", "cost": 3.99, "days": 5},
                {"name": "Express", "cost": 8.99, "days": 2},
                {"name": "Store Pickup", "cost": 0, "days": 1},
            ],
            free_shipping_threshold=Decimal("35.00"),
            ships_from="Richfield, MN",
            ships_to=["US"],
            raw={},
        )

    async def coupon(
        self,
        code: str | None = None,
    ) -> list[SupplierCoupon]:
        """Get Best Buy coupons."""
        return [
            SupplierCoupon(
                code="BBY10",
                description="10% off select electronics",
                discount_type="percentage",
                discount_value=Decimal("10"),
                min_order_amount=Decimal("100.00"),
                is_active=True,
                raw={},
            ),
            SupplierCoupon(
                code="FREESHIPBB",
                description="Free shipping on orders over $35",
                discount_type="free_shipping",
                discount_value=Decimal("0"),
                min_order_amount=Decimal("35.00"),
                is_active=True,
                raw={},
            ),
        ]

    async def availability(
        self,
        sku: str,
    ) -> SupplierAvailability | None:
        """Check Best Buy product availability."""
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
