"""Target supplier plugin.

Integrates with the Target Marketplace API (Target+ / Target Partner API).
"""

from __future__ import annotations

from decimal import Decimal
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


class TargetPlugin(BaseSupplierPlugin):
    """Supplier plugin for Target Marketplace."""

    supplier_name = "Target"
    supplier_code = "target"
    version = "1.0.0"

    async def search(
        self,
        query: str,
        *,
        page: int = 1,
        page_size: int = 20,
    ) -> list[SupplierProductSearchResult]:
        """Search Target catalog by keyword."""
        client = self.get_http_client()
        api_key = self._config.get("api_key", "")
        base_url = self._config.get("base_url", "https://api.target.com/marketplace/v1")

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        params = {"keyword": query, "page": page, "size": page_size}

        response = await client.get(f"{base_url}/products/search", headers=headers, params=params)
        response.raise_for_status()
        data = response.json()

        results: list[SupplierProductSearchResult] = []
        for item in data.get("products", []):
            results.append(
                SupplierProductSearchResult(
                    supplier_sku=item.get("partnerProductId", item.get("dpci", "")),
                    title=item.get("title", ""),
                    upc=item.get("upc"),
                    brand=item.get("brand"),
                    category=item.get("category"),
                    image_url=item.get("mainImageUrl"),
                    price=Decimal(str(item.get("price", 0))),
                    currency="USD",
                    moq=item.get("minimumOrderQuantity", 1),
                    in_stock=item.get("availableToPromiseQuantity", 0) > 0,
                    estimated_delivery_days=item.get("estimatedDeliveryDays"),
                    raw=item,
                ),
            )

        return results

    async def lookup(
        self,
        sku: str,
    ) -> SupplierProductLookup | None:
        """Look up a Target product by SKU."""
        client = self.get_http_client()
        api_key = self._config.get("api_key", "")
        base_url = self._config.get("base_url", "https://api.target.com/marketplace/v1")

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
            supplier_sku=item.get("partnerProductId", sku),
            title=item.get("title", ""),
            description=item.get("description"),
            upc=item.get("upc"),
            brand=item.get("brand"),
            manufacturer=item.get("manufacturer"),
            category=item.get("category"),
            images=item.get("images", []),
            features=item.get("features", []),
            weight=Decimal(str(item["weight"])) if item.get("weight") else None,
            weight_unit=item.get("weightUnit"),
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
        """Get Target pricing."""
        lookup = await self.lookup(sku)
        if lookup is None:
            return None
        return SupplierPricing(
            unit_price=lookup.price,
            currency=lookup.currency,
            quantity_tiers=[],
            raw=lookup.raw,
        )

    async def inventory(
        self,
        sku: str,
    ) -> SupplierInventory | None:
        """Get Target inventory."""
        client = self.get_http_client()
        api_key = self._config.get("api_key", "")
        base_url = self._config.get("base_url", "https://api.target.com/marketplace/v1")

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
        """Get Target shipping options."""
        return SupplierShipping(
            methods=[
                {"name": "Standard", "cost": 4.99, "days": 5},
                {"name": "Express", "cost": 9.99, "days": 3},
                {"name": "Premium", "cost": 14.99, "days": 1},
            ],
            free_shipping_threshold=Decimal("35.00"),
            ships_from="Minneapolis, MN",
            ships_to=["US"],
            raw={},
        )

    async def coupon(
        self,
        code: str | None = None,
    ) -> list[SupplierCoupon]:
        """Get Target coupons."""
        return [
            SupplierCoupon(
                code="TARGET5",
                description="$5 off orders over $50",
                discount_type="fixed_amount",
                discount_value=Decimal("5.00"),
                min_order_amount=Decimal("50.00"),
                is_active=True,
                raw={},
            ),
            SupplierCoupon(
                code="FREESHIP",
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
        """Check Target product availability."""
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
