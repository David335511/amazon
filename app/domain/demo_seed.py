"""Seed demo products + Amazon analytics data for the sourcing agent.

Pairs with the `demo` supplier plugin (``app.plugins.suppliers.demo``). The
demo plugin returns a fixed catalog from memory; this seeder writes matching
products + Amazon analytics rows into the database so the sourcing pipeline
can scan → match by UPC → evaluate → log BUY/WATCH/AVOID decisions, entirely
offline and deterministically.

Idempotent: products are keyed by ASIN; re-running only inserts analytics
rows for products that do not yet have them.

Analytics values are chosen to produce a representative spread of outcomes:
  - Anker PowerCore 10000mAh  → BUY   (high ROI, strong sales, light competition)
  - Wireless Earbuds          → WATCH (decent ROI, moderate sales/competition)
  - USB-C Fast Charging Cable → WATCH (good ROI, low sales volume)
  - Silicone Phone Case       → AVOID (negative margin, high competition)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.product import Product
from app.domain.models.sourcing import (
    AmazonPrice,
    HistoricalFee,
    HistoricalInventory,
    ProductPrice,
    SalesEstimate,
    SellerCount,
)
from app.plugins.suppliers.demo import DEMO_CATALOG

# Analytics blueprint per product (keyed by supplier_sku).
# amazon_price / sales / sellers / fees / inventory drive the sourcing rules.
_ANALYTICS: dict[str, dict[str, object]] = {
    "DEMO-ANK-PC10000": {
        "amazon_price": Decimal("29.99"),
        "monthly_sales": 2200,
        "daily_sales": Decimal("73.33"),
        "monthly_revenue": Decimal("65978.00"),
        "sales_rank": 820,
        "new_sellers": 6,
        "used_sellers": 2,
        "fba_sellers": 4,
        "referral_fee": Decimal("4.20"),
        "fulfillment_fee": Decimal("4.50"),
        "storage_fee": Decimal("0.15"),
        "total_fees": Decimal("8.85"),
        "qty_available": 800,
        "buy_box_win_rate": 0.77,
    },
    "DEMO-EARBUDS": {
        "amazon_price": Decimal("24.99"),
        "monthly_sales": 620,
        "daily_sales": Decimal("20.67"),
        "monthly_revenue": Decimal("15493.00"),
        "sales_rank": 3400,
        "new_sellers": 14,
        "used_sellers": 5,
        "fba_sellers": 9,
        "referral_fee": Decimal("3.75"),
        "fulfillment_fee": Decimal("4.30"),
        "storage_fee": Decimal("0.12"),
        "total_fees": Decimal("8.17"),
        "qty_available": 260,
        "buy_box_win_rate": 0.62,
    },
    "DEMO-USBC": {
        "amazon_price": Decimal("19.99"),
        "monthly_sales": 520,
        "daily_sales": Decimal("17.33"),
        "monthly_revenue": Decimal("10394.00"),
        "sales_rank": 4600,
        "new_sellers": 11,
        "used_sellers": 4,
        "fba_sellers": 7,
        "referral_fee": Decimal("3.00"),
        "fulfillment_fee": Decimal("3.80"),
        "storage_fee": Decimal("0.10"),
        "total_fees": Decimal("6.90"),
        "qty_available": 900,
        "buy_box_win_rate": 0.70,
    },
    "DEMO-CASE": {
        "amazon_price": Decimal("9.99"),
        "monthly_sales": 210,
        "daily_sales": Decimal("7.00"),
        "monthly_revenue": Decimal("2097.00"),
        "sales_rank": 9800,
        "new_sellers": 34,
        "used_sellers": 12,
        "fba_sellers": 26,
        "referral_fee": Decimal("1.50"),
        "fulfillment_fee": Decimal("3.60"),
        "storage_fee": Decimal("0.08"),
        "total_fees": Decimal("5.18"),
        "qty_available": 120,
        "buy_box_win_rate": 0.40,
    },
}


async def seed_sourcing_demo(db: AsyncSession) -> dict[str, object]:
    """Insert demo products + analytics; return per-product outcome summary."""
    now = datetime.now(UTC)
    created_products = 0
    analytics_written = 0

    for item in DEMO_CATALOG:
        blueprint = _ANALYTICS[item["supplier_sku"]]

        # Find existing product by ASIN.
        existing = await db.execute(
            select(Product).where(Product.asin == item["asin"])
        )
        product = existing.scalar_one_or_none()

        if product is None:
            product = Product(
                id=uuid4(),
                asin=item["asin"],
                upc=item["upc"],
                title=item["title"],
                description=f"Demo product: {item['title']}",
                price=Decimal(item["price"]),
                currency=item["currency"],
                is_active=True,
                is_amazon_fba=True,
            )
            db.add(product)
            await db.flush()
            created_products += 1

        # Skip analytics if this product already has a recent Amazon price
        # snapshot (idempotency).
        has_price = await db.execute(
            select(AmazonPrice)
            .where(AmazonPrice.product_id == product.id)
            .limit(1)
        )
        if has_price.scalar_one_or_none() is not None:
            continue

        amazon_price: Decimal = blueprint["amazon_price"]  # type: ignore[assignment]

        # Amazon price history (13 weekly observations, ~77% buy-box win rate).
        buy_box_count = round(blueprint["buy_box_win_rate"] * 13)  # type: ignore[operator]
        for i in range(13):
            ts = now - timedelta(days=i * 7)
            db.add(AmazonPrice(
                id=uuid4(),
                product_id=product.id,
                price=amazon_price,
                currency="USD",
                condition="New",
                is_amazon_fulfilled=True,
                is_buy_box=(i < buy_box_count),
                is_prime=True,
                effective_date=ts,
            ))

        # Supplier cost (matches the demo catalog price).
        db.add(ProductPrice(
            id=uuid4(),
            product_id=product.id,
            price=Decimal(item["price"]),
            currency=item["currency"],
            source="demo",
            effective_date=now,
        ))

        # Competition snapshot.
        db.add(SellerCount(
            id=uuid4(),
            product_id=product.id,
            new_seller_count=blueprint["new_sellers"],
            used_seller_count=blueprint["used_sellers"],
            fba_seller_count=blueprint["fba_sellers"],
            effective_date=now,
        ))

        # Sales estimate.
        db.add(SalesEstimate(
            id=uuid4(),
            product_id=product.id,
            estimated_monthly_sales=blueprint["monthly_sales"],
            estimated_daily_sales=blueprint["daily_sales"],
            estimated_monthly_revenue=blueprint["monthly_revenue"],
            sales_rank=blueprint["sales_rank"],
            effective_date=now,
        ))

        # Fees.
        db.add(HistoricalFee(
            id=uuid4(),
            product_id=product.id,
            referral_fee=blueprint["referral_fee"],
            fulfillment_fee=blueprint["fulfillment_fee"],
            storage_fee=blueprint["storage_fee"],
            total_fees=blueprint["total_fees"],
            effective_date=now,
        ))

        # Historical inventory.
        db.add(HistoricalInventory(
            id=uuid4(),
            product_id=product.id,
            quantity_on_hand=blueprint["qty_available"],
            quantity_reserved=0,
            quantity_inbound=0,
            quantity_available=blueprint["qty_available"],
            warehouse_location="DEMO-A-01",
            effective_date=now,
        ))

        analytics_written += 1

    await db.commit()
    return {
        "products_created": created_products,
        "products_seeded": len(DEMO_CATALOG),
        "analytics_written": analytics_written,
        "supplier": "demo",
        "note": "Run a sourcing cycle (or restart the agent) to evaluate these.",
    }
