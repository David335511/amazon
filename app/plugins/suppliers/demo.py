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

import random
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


# ── Larger deterministic catalog generator ─────────────────────────
# Default catalog size returned by the demo supplier (curated 4 + generated).
DEFAULT_DEMO_SIZE = 500

# Fixed seed → the generated set is byte-for-byte reproducible.
_GEN_SEED = 20260803
_MODEL_LABELS = ["2-Pack", "Pro", "Mini", "Max", "Deluxe", "Plus", "Lite", "XL"]

# (category, base product name) — 120 realistic templates across 12 categories.
_CATALOG_TEMPLATES: list[tuple[str, str]] = [
    # Electronics
    ("Electronics", "Bluetooth Speaker"),
    ("Electronics", "Wireless Earbuds"),
    ("Electronics", "USB-C Wall Charger"),
    ("Electronics", "Power Bank 20000mAh"),
    ("Electronics", "LED Desk Lamp"),
    ("Electronics", "HDMI Cable 6ft"),
    ("Electronics", "Phone Grip Stand"),
    ("Electronics", "Webcam 1080p"),
    ("Electronics", "Smart Watch Band"),
    ("Electronics", "Car Phone Mount"),
    # Home & Kitchen
    ("Home & Kitchen", "Coffee Maker"),
    ("Home & Kitchen", "Air Fryer 5L"),
    ("Home & Kitchen", "Blender 1.5L"),
    ("Home & Kitchen", "Electric Kettle"),
    ("Home & Kitchen", "Nonstick Frying Pan"),
    ("Home & Kitchen", "Dish Drying Rack"),
    ("Home & Kitchen", "Storage Containers Set"),
    ("Home & Kitchen", "Measuring Cups Set"),
    ("Home & Kitchen", "Garlic Press"),
    ("Home & Kitchen", "Cutting Board Set"),
    # Beauty & Personal Care
    ("Beauty & Personal Care", "Hair Dryer"),
    ("Beauty & Personal Care", "Electric Toothbrush"),
    ("Beauty & Personal Care", "Nail Polish Set"),
    ("Beauty & Personal Care", "Makeup Brush Set"),
    ("Beauty & Personal Care", "Face Roller"),
    ("Beauty & Personal Care", "Beard Trimmer"),
    ("Beauty & Personal Care", "Curling Iron"),
    ("Beauty & Personal Care", "Bath Bombs Set"),
    ("Beauty & Personal Care", "Skincare Serum"),
    ("Beauty & Personal Care", "Hair Clips Set"),
    # Toys & Games
    ("Toys & Games", "Building Blocks Set"),
    ("Toys & Games", "Plush Teddy Bear"),
    ("Toys & Games", "RC Car"),
    ("Toys & Games", "Puzzle 1000pc"),
    ("Toys & Games", "Dollhouse"),
    ("Toys & Games", "Board Game"),
    ("Toys & Games", "Kids Art Set"),
    ("Toys & Games", "Fidget Spinner"),
    ("Toys & Games", "Remote Control Drone"),
    ("Toys & Games", "Play Kitchen"),
    # Sports & Outdoors
    ("Sports & Outdoors", "Yoga Mat"),
    ("Sports & Outdoors", "Resistance Bands Set"),
    ("Sports & Outdoors", "Dumbbell Set"),
    ("Sports & Outdoors", "Jump Rope"),
    ("Sports & Outdoors", "Camping Tent"),
    ("Sports & Outdoors", "Water Bottle 1L"),
    ("Sports & Outdoors", "Hiking Backpack"),
    ("Sports & Outdoors", "Golf Balls 12-Pack"),
    ("Sports & Outdoors", "Soccer Ball"),
    ("Sports & Outdoors", "Yoga Block"),
    # Garden & Outdoor
    ("Garden & Outdoor", "Garden Hose 50ft"),
    ("Garden & Outdoor", "Pruning Shears"),
    ("Garden & Outdoor", "Plant Pots Set"),
    ("Garden & Outdoor", "Bird Feeder"),
    ("Garden & Outdoor", "Outdoor String Lights"),
    ("Garden & Outdoor", "Solar Path Lights"),
    ("Garden & Outdoor", "Garden Gloves"),
    ("Garden & Outdoor", "Watering Can"),
    ("Garden & Outdoor", "Kneeling Pad"),
    ("Garden & Outdoor", "Patio Furniture Cover"),
    # Tools & Home Improvement
    ("Tools & Home Improvement", "Cordless Drill"),
    ("Tools & Home Improvement", "Screwdriver Set"),
    ("Tools & Home Improvement", "Tape Measure"),
    ("Tools & Home Improvement", "Toolbox"),
    ("Tools & Home Improvement", "Claw Hammer"),
    ("Tools & Home Improvement", "LED Flashlight"),
    ("Tools & Home Improvement", "Utility Knife"),
    ("Tools & Home Improvement", "Level 24in"),
    ("Tools & Home Improvement", "Wrench Set"),
    ("Tools & Home Improvement", "Stud Finder"),
    # Office Products
    ("Office Products", "Desk Organizer"),
    ("Office Products", "Mouse Pad"),
    ("Office Products", "Laptop Stand"),
    ("Office Products", "Whiteboard"),
    ("Office Products", "Stapler"),
    ("Office Products", "Paper Shredder"),
    ("Office Products", "Notebook Set"),
    ("Office Products", "Gel Pens 12-Pack"),
    ("Office Products", "Document Tray"),
    ("Office Products", "Desk Calendar"),
    # Pet Supplies
    ("Pet Supplies", "Dog Leash"),
    ("Pet Supplies", "Cat Scratcher"),
    ("Pet Supplies", "Pet Food Bowl"),
    ("Pet Supplies", "Dog Bed"),
    ("Pet Supplies", "Cat Toy Set"),
    ("Pet Supplies", "Pet Grooming Brush"),
    ("Pet Supplies", "Aquarium Filter"),
    ("Pet Supplies", "Dog Harness"),
    ("Pet Supplies", "Litter Box"),
    ("Pet Supplies", "Pet Water Fountain"),
    # Automotive
    ("Automotive", "Car Vacuum"),
    ("Automotive", "Tire Inflator"),
    ("Automotive", "Windshield Cover"),
    ("Automotive", "Seat Cover Set"),
    ("Automotive", "Floor Mats"),
    ("Automotive", "Car Charger"),
    ("Automotive", "Dashboard Camera"),
    ("Automotive", "Jump Starter"),
    ("Automotive", "Car Air Freshener"),
    ("Automotive", "Trunk Organizer"),
    # Clothing, Shoes & Jewelry
    ("Clothing, Shoes & Jewelry", "Cotton T-Shirt"),
    ("Clothing, Shoes & Jewelry", "Running Socks 6-Pack"),
    ("Clothing, Shoes & Jewelry", "Baseball Cap"),
    ("Clothing, Shoes & Jewelry", "Leather Belt"),
    ("Clothing, Shoes & Jewelry", "Sunglasses"),
    ("Clothing, Shoes & Jewelry", "Travel Wallet"),
    ("Clothing, Shoes & Jewelry", "Silk Scarf"),
    ("Clothing, Shoes & Jewelry", "Watch Strap"),
    ("Clothing, Shoes & Jewelry", "House Slippers"),
    ("Clothing, Shoes & Jewelry", "Laptop Backpack"),
    # Baby Products
    ("Baby Products", "Baby Monitor"),
    ("Baby Products", "Diaper Bag"),
    ("Baby Products", "Baby Bib Set"),
    ("Baby Products", "Car Seat Cover"),
    ("Baby Products", "Bottle Warmer"),
    ("Baby Products", "Baby Swing"),
    ("Baby Products", "Play Mat"),
    ("Baby Products", "Swaddle Blanket"),
    ("Baby Products", "Stroller Organizer"),
    ("Baby Products", "Pacifier Set"),
]


def _make_generated_item(index: int, category: str, title: str) -> dict[str, Any]:
    """Deterministically build one generated product + its analytics."""
    rng = random.Random(_GEN_SEED + index * 7919)
    # Prices skewed toward the mid-range so most products are margin-viable.
    amazon_price = round(max(12.0, min(120.0, rng.lognormvariate(3.69, 0.6))), 2)
    cost = round(amazon_price * rng.uniform(0.40, 0.60), 2)
    referral = round(amazon_price * rng.uniform(0.10, 0.16), 2)
    fulfillment = round(rng.uniform(3.0, 6.0) + amazon_price * 0.02, 2)
    storage = round(rng.uniform(0.05, 0.30), 2)
    total_fees = round(referral + fulfillment + storage, 2)
    monthly_sales = int(max(220, min(3500, rng.lognormvariate(6.5, 0.7))))
    new_sellers = rng.randint(4, 45)
    fba_sellers = int(new_sellers * rng.uniform(0.5, 0.95))
    used_sellers = rng.randint(0, 18)
    qty = rng.randint(80, 1600)
    asin_index = index + 10000
    return {
        "supplier_sku": f"DEMO-{index + 1:05d}",
        "asin": f"B0DEM{asin_index:05d}",
        "upc": f"{600000000000 + index:012d}",
        "title": title,
        "brand": _brand_for(category),
        "manufacturer": _brand_for(category),
        "category": category,
        "price": f"{cost:.2f}",
        "currency": "USD",
        "moq": rng.choice([1, 1, 2, 5, 10, 20]),
        "in_stock": rng.random() > 0.08,
        "delivery_days": rng.randint(2, 14),
        # analytics blueprint (consumed by the seeder)
        "amazon_price": Decimal(str(amazon_price)),
        "monthly_sales": monthly_sales,
        "daily_sales": round(monthly_sales / 30.4, 2),
        "monthly_revenue": round(amazon_price * monthly_sales, 2),
        "sales_rank": int(15000 / (monthly_sales ** 0.6)),
        "new_sellers": new_sellers,
        "used_sellers": used_sellers,
        "fba_sellers": fba_sellers,
        "referral_fee": Decimal(str(referral)),
        "fulfillment_fee": Decimal(str(fulfillment)),
        "storage_fee": Decimal(str(storage)),
        "total_fees": Decimal(str(total_fees)),
        "qty_available": qty,
        "buy_box_win_rate": round(rng.uniform(0.4, 0.92), 2),
    }


_BRANDS = [
    "Nimbus", "Aurora", "Vertex", "Harbor", "Brightline", "Copperleaf",
    "Zenith", "Maple & Co", "Ironclad", "Lumina", "Trailhead", "Fjord",
    "NovaGear", "Solstice", "Everpeak", "Cobalt", "Timberline", "Ridgeway",
]


def _brand_for(category: str) -> str:
    """Deterministically pick a demo brand for a category."""
    return _BRANDS[sum(ord(c) for c in category) % len(_BRANDS)]


def build_demo_catalog(size: int = DEFAULT_DEMO_SIZE) -> list[dict[str, Any]]:
    """Return the curated catalog plus ``size`` deterministic products.

    The first 4 entries are always the hand-curated products (which carry the
    exact BUY/WATCH/AVOID spread used by tests). Every subsequent entry is a
    generated product with reproducible analytics. ``size`` defaults to 500.
    """
    catalog = list(DEMO_CATALOG)
    if size <= len(DEMO_CATALOG):
        return catalog
    for g in range(size - len(DEMO_CATALOG)):
        category, base_name = _CATALOG_TEMPLATES[g % len(_CATALOG_TEMPLATES)]
        pass_idx = g // len(_CATALOG_TEMPLATES)
        title = (
            base_name
            if pass_idx == 0
            else f"{base_name} ({_MODEL_LABELS[pass_idx % len(_MODEL_LABELS)]})"
        )
        catalog.append(_make_generated_item(g, category, title))
    return catalog


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
        items = build_demo_catalog()
        if q:
            items = [
                item for item in items
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
        return next((i for i in build_demo_catalog() if i["supplier_sku"] == sku), None)

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
