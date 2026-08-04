"""Demo supplier plugin — an offline, deterministic seed catalog.

This plugin lets the agent pipeline run end-to-end WITHOUT any external
supplier API or credentials. It returns a small curated catalog from memory
(demo products that a matching seeder also writes to the database), so the
sourcing cycle can scan → match by UPC → evaluate → log BUY/WATCH/AVOID
decisions. It is intentionally network-free and reproducible.

Design notes:
- `DEMO_CATALOG` is the single source of truth for the demo products. The
  seeder (`app.domain.demo_seed`) imports it to create matching database rows.
- All 8 plugin methods are implemented, returning the standardised models.
- The catalog is deliberately small (4 products) covering the full range of
  sourcing outcomes (BUY, WATCH, WATCH, AVOID) so it is a good teaching/demo.
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

# ── Demo catalog (source of truth) ─────────────────────────────────
# `price` is the SUPPLIER cost (what the pipeline compares against the
# Amazon price to compute profit/ROI). `asin`/`upc` are used by the seeder
# to create matching products in the database.
DEMO_CATALOG: list[dict[str, Any]] = [
    {
        "supplier_sku": "DEMO-ANK-PC10000",
        "asin": "B0DEMO0001",
        "upc": "848061079413",
        "title": "Anker PowerCore 10000mAh Portable Charger",
        "brand": "Anker",
        "manufacturer": "Anker",
        "category": "Electronics",
        "price": "11.00",
        "currency": "USD",
        "moq": 1,
        "in_stock": True,
        "delivery_days": 5,
    },
    {
        "supplier_sku": "DEMO-EARBUDS",
        "asin": "B0DEMO0002",
        "upc": "123456789012",
        "title": "Wireless Bluetooth Earbuds with Charging Case",
        "brand": "SoundPeats",
        "manufacturer": "SoundPeats",
        "category": "Electronics",
        "price": "12.00",
        "currency": "USD",
        "moq": 1,
        "in_stock": True,
        "delivery_days": 7,
    },
    {
        "supplier_sku": "DEMO-CASE",
        "asin": "B0DEMO0003",
        "upc": "098765432109",
        "title": "Silicone Phone Case for iPhone",
        "brand": "Generic",
        "manufacturer": "Generic",
        "category": "Accessories",
        "price": "11.50",
        "currency": "USD",
        "moq": 10,
        "in_stock": True,
        "delivery_days": 3,
    },
    {
        "supplier_sku": "DEMO-USBC",
        "asin": "B0DEMO0004",
        "upc": "111213141516",
        "title": "USB-C Fast Charging Cable 3ft",
        "brand": "Belkin",
        "manufacturer": "Belkin",
        "category": "Electronics",
        "price": "9.50",
        "currency": "USD",
        "moq": 20,
        "in_stock": True,
        "delivery_days": 4,
    },
]


class DemoPlugin(BaseSupplierPlugin):
    """Offline supplier returning a fixed in-memory catalog."""

    supplier_name = "Demo"
    supplier_code = "demo"
    version = "1.0.0"

    # ── Search ────────────────────────────────────────────────

    async def search(
        self,
        query: str,
        *,
        page: int = 1,
        page_size: int = 20,
    ) -> list[SupplierProductSearchResult]:
        """Return the demo catalog (optionally filtered by query)."""
        q = (query or "").strip().lower()
        items = DEMO_CATALOG
        if q:
            items = [
                item for item in DEMO_CATALOG
                if q in item["title"].lower() or q in item["brand"].lower()
            ]

        start = (page - 1) * page_size
        page_items = items[start:start + page_size]

        return [
            SupplierProductSearchResult(
                supplier_sku=item["supplier_sku"],
                title=item["title"],
                upc=item["upc"],
                brand=item["brand"],
                manufacturer=item.get("manufacturer"),
                category=item.get("category"),
                image_url=f"https://images.example.com/{item['supplier_sku']}.jpg",
                price=Decimal(item["price"]),
                currency=item["currency"],
                moq=item.get("moq", 1),
                in_stock=item.get("in_stock", True),
                estimated_delivery_days=item.get("delivery_days"),
                raw={"demo": True, "asin": item["asin"]},
            )
            for item in page_items
        ]

    # ── Lookup / Pricing / Inventory / Availability ───────────

    def _find(self, sku: str) -> dict[str, Any] | None:
        return next((i for i in DEMO_CATALOG if i["supplier_sku"] == sku), None)

    async def lookup(self, sku: str) -> SupplierProductLookup | None:
        item = self._find(sku)
        if item is None:
            return None
        return SupplierProductLookup(
            supplier_sku=item["supplier_sku"],
            title=item["title"],
            description=f"Demo {item['title']}",
            upc=item["upc"],
            brand=item["brand"],
            manufacturer=item.get("manufacturer"),
            category=item.get("category"),
            price=Decimal(item["price"]),
            currency=item["currency"],
            moq=item.get("moq", 1),
            raw={"demo": True},
        )

    async def pricing(self, sku: str) -> SupplierPricing | None:
        item = self._find(sku)
        if item is None:
            return None
        return SupplierPricing(
            unit_price=Decimal(item["price"]),
            currency=item["currency"],
            raw={"demo": True},
        )

    async def inventory(self, sku: str) -> SupplierInventory | None:
        item = self._find(sku)
        if item is None:
            return None
        return SupplierInventory(
            supplier_sku=sku,
            quantity_available=500,
            quantity_inbound=0,
            warehouse_location="DEMO-DC-01",
            is_backorderable=False,
            raw={"demo": True},
        )

    async def availability(self, sku: str) -> SupplierAvailability | None:
        item = self._find(sku)
        if item is None:
            return None
        return SupplierAvailability(
            supplier_sku=sku,
            is_available=item.get("in_stock", True),
            backorder_allowed=False,
            stock_status="in_stock" if item.get("in_stock", True) else "out_of_stock",
            raw={"demo": True},
        )

    # ── Shipping / Coupons ───────────────────────────────────

    async def shipping(
        self,
        sku: str,
        *,
        quantity: int = 1,  # noqa: ARG002 - part of plugin interface
        postal_code: str | None = None,  # noqa: ARG002 - part of plugin interface
    ) -> SupplierShipping | None:
        item = self._find(sku)
        if item is None:
            return None
        return SupplierShipping(
            methods=[
                {"name": "Standard", "cost": 3.99, "days": item.get("delivery_days", 5)},
                {"name": "Express", "cost": 9.99, "days": 2},
            ],
            free_shipping_threshold=Decimal("35.00"),
            ships_from="DEMO, USA",
            ships_to=["US", "CA"],
            raw={"demo": True},
        )

    async def coupon(self, code: str | None = None) -> list[SupplierCoupon]:  # noqa: ARG002 - part of plugin interface
        return [
            SupplierCoupon(
                code="DEMO10",
                description="10% off demo order",
                discount_type="percentage",
                discount_value=Decimal("10"),
                min_order_amount=Decimal("50"),
                is_active=True,
                raw={"demo": True},
            ),
        ]
