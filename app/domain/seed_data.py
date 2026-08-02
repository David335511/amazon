"""Seed data for the Amazon sourcing platform.

Provides realistic sample data for development and testing.
All prices are examples and should not be used for actual sourcing decisions.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

# ── Brands ────────────────────────────────────────────────────
BRANDS = [
    {
        "id": UUID("a0000001-0000-0000-0000-000000000001"),
        "name": "Anker",
        "slug": "anker",
        "description": "Leading charger and accessory brand",
        "website_url": "https://www.anker.com",
        "is_active": True,
    },
    {
        "id": UUID("a0000001-0000-0000-0000-000000000002"),
        "name": "Sony",
        "slug": "sony",
        "description": "Global electronics manufacturer",
        "website_url": "https://www.sony.com",
        "is_active": True,
    },
    {
        "id": UUID("a0000001-0000-0000-0000-000000000003"),
        "name": "Simple Houseware",
        "slug": "simple-houseware",
        "description": "Home organization products",
        "is_active": True,
    },
    {
        "id": UUID("a0000001-0000-0000-0000-000000000004"),
        "name": "AmazonBasics",
        "slug": "amazon-basics",
        "description": "Amazon's own brand for everyday essentials",
        "website_url": "https://www.amazon.com",
        "is_active": True,
    },
]

# ── Categories ────────────────────────────────────────────────
CATEGORIES = [
    {
        "id": UUID("b0000001-0000-0000-0000-000000000001"),
        "parent_id": None,
        "name": "Electronics",
        "slug": "electronics",
        "path": "b0000001-0000-0000-0000-000000000001",
        "level": 0,
        "amazon_category_id": "172282",
        "is_active": True,
    },
    {
        "id": UUID("b0000001-0000-0000-0000-000000000002"),
        "parent_id": UUID("b0000001-0000-0000-0000-000000000001"),
        "name": "Chargers & Cables",
        "slug": "chargers-cables",
        "path": "b0000001-0000-0000-0000-000000000001/b0000001-0000-0000-0000-000000000002",
        "level": 1,
        "amazon_category_id": "2335752011",
        "is_active": True,
    },
    {
        "id": UUID("b0000001-0000-0000-0000-000000000003"),
        "parent_id": UUID("b0000001-0000-0000-0000-000000000001"),
        "name": "Headphones",
        "slug": "headphones",
        "path": "b0000001-0000-0000-0000-000000000001/b0000001-0000-0000-0000-000000000003",
        "level": 1,
        "amazon_category_id": "172541",
        "is_active": True,
    },
    {
        "id": UUID("b0000001-0000-0000-0000-000000000004"),
        "parent_id": None,
        "name": "Home & Kitchen",
        "slug": "home-kitchen",
        "path": "b0000001-0000-0000-0000-000000000004",
        "level": 0,
        "amazon_category_id": "1055398",
        "is_active": True,
    },
    {
        "id": UUID("b0000001-0000-0000-0000-000000000005"),
        "parent_id": UUID("b0000001-0000-0000-0000-000000000004"),
        "name": "Storage & Organization",
        "slug": "storage-organization",
        "path": "b0000001-0000-0000-0000-000000000004/b0000001-0000-0000-0000-000000000005",
        "level": 1,
        "amazon_category_id": "3737721",
        "is_active": True,
    },
]

# ── Products ──────────────────────────────────────────────────
PRODUCTS = [
    {
        "id": UUID("c0000001-0000-0000-0000-000000000001"),
        "asin": "B0ABCDEFGH",
        "upc": "848061079413",
        "ean": "0848061079413",
        "gtin": "00848061079413",
        "title": "Anker PowerCore 10000mAh Portable Charger",
        "description": "Ultra-compact 10000mAh portable charger with PowerIQ technology",
        "brand_id": UUID("a0000001-0000-0000-0000-000000000001"),
        "category_id": UUID("b0000001-0000-0000-0000-000000000002"),
        "main_image_url": "https://images.example.com/anker-powercore.jpg",
        "weight": Decimal("0.50"),
        "weight_unit": "lbs",
        "dimensions": "4.0x2.4x0.8 inches",
        "is_active": True,
        "is_amazon_fba": True,
        "is_amazon_brand": False,
    },
    {
        "id": UUID("c0000001-0000-0000-0000-000000000002"),
        "asin": "B0ZYXWVUTS",
        "upc": "027242926305",
        "ean": "0027242926305",
        "gtin": "00027242926305",
        "title": "Sony WH-1000XM5 Wireless Noise Cancelling Headphones",
        "description": "Industry-leading noise cancellation with Auto NC Optimizer",
        "brand_id": UUID("a0000001-0000-0000-0000-000000000002"),
        "category_id": UUID("b0000001-0000-0000-0000-000000000003"),
        "main_image_url": "https://images.example.com/sony-wh1000xm5.jpg",
        "weight": Decimal("1.2"),
        "weight_unit": "lbs",
        "dimensions": "7.3x3.0x8.9 inches",
        "is_active": True,
        "is_amazon_fba": True,
        "is_amazon_brand": False,
    },
    {
        "id": UUID("c0000001-0000-0000-0000-000000000003"),
        "asin": "B0JKLMNOPQ",
        "upc": "848061079420",
        "ean": "0848061079420",
        "gtin": "00848061079420",
        "title": "Simple Houseware 6-Cube Organizer Shelf",
        "description": "Stackable cube storage shelf for home organization",
        "brand_id": UUID("a0000001-0000-0000-0000-000000000003"),
        "category_id": UUID("b0000001-0000-0000-0000-000000000005"),
        "main_image_url": "https://images.example.com/cube-organizer.jpg",
        "weight": Decimal("8.5"),
        "weight_unit": "lbs",
        "dimensions": "12x12x36 inches",
        "is_active": True,
        "is_amazon_fba": False,
        "is_amazon_brand": False,
    },
]

# ── Suppliers ──────────────────────────────────────────────────
SUPPLIERS = [
    {
        "id": UUID("d0000001-0000-0000-0000-000000000001"),
        "name": "Shenzhen Tech Supply Co.",
        "company_name": "Shenzhen Tech Supply Co., Ltd",
        "contact_name": "Li Wei",
        "email": "liwei@sztechsupply.cn",
        "phone": "+86-755-8288-1234",
        "website": "https://sztechsupply.alibaba.com",
        "city": "Shenzhen",
        "state": "Guangdong",
        "country": "China",
        "is_active": True,
        "rating": Decimal("4.5"),
        "notes": "Premium electronics supplier, fast shipping",
    },
    {
        "id": UUID("d0000001-0000-0000-0000-000000000002"),
        "name": "Yiwu Home Goods Inc.",
        "company_name": "Yiwu Home Goods Import & Export Co.",
        "contact_name": "Zhang Min",
        "email": "zhangmin@yiwuhome.com",
        "phone": "+86-579-8555-6789",
        "website": "https://yiwuhome.en.alibaba.com",
        "city": "Yiwu",
        "state": "Zhejiang",
        "country": "China",
        "is_active": True,
        "rating": Decimal("4.2"),
        "notes": "Home goods specialist, good MOQ terms",
    },
    {
        "id": UUID("d0000001-0000-0000-0000-000000000003"),
        "name": "US Direct Wholesale",
        "company_name": "US Direct Wholesale LLC",
        "contact_name": "John Smith",
        "email": "john@usdirectwholesale.com",
        "phone": "+1-323-555-0198",
        "website": "https://usdirectwholesale.com",
        "city": "Los Angeles",
        "state": "California",
        "country": "USA",
        "is_active": True,
        "rating": Decimal("4.8"),
        "notes": "Domestic supplier, fast delivery, higher prices",
    },
]

# ── Supplier Products ────────────────────────────────────────
SUPPLIER_PRODUCTS = [
    {
        "id": UUID("e0000001-0000-0000-0000-000000000001"),
        "product_id": UUID("c0000001-0000-0000-0000-000000000001"),
        "supplier_id": UUID("d0000001-0000-0000-0000-000000000001"),
        "supplier_sku": "ANK-PC-10000-BLK",
        "supplier_price": Decimal("12.50"),
        "currency": "USD",
        "moq": 100,
        "lead_time_days": 15,
        "is_preferred": True,
        "is_active": True,
    },
    {
        "id": UUID("e0000001-0000-0000-0000-000000000002"),
        "product_id": UUID("c0000001-0000-0000-0000-000000000001"),
        "supplier_id": UUID("d0000001-0000-0000-0000-000000000003"),
        "supplier_sku": "ANK-PC-10K-US",
        "supplier_price": Decimal("18.00"),
        "currency": "USD",
        "moq": 10,
        "lead_time_days": 3,
        "is_preferred": False,
        "is_active": True,
    },
    {
        "id": UUID("e0000001-0000-0000-0000-000000000003"),
        "product_id": UUID("c0000001-0000-0000-0000-000000000003"),
        "supplier_id": UUID("d0000001-0000-0000-0000-000000000002"),
        "supplier_sku": "SH-6CUBE-WHT",
        "supplier_price": Decimal("8.75"),
        "currency": "USD",
        "moq": 200,
        "lead_time_days": 20,
        "is_preferred": True,
        "is_active": True,
    },
]

# ── Product Prices (historical) ──────────────────────────────
PRODUCT_PRICES = [
    {
        "id": UUID("f0000001-0000-0000-0000-000000000001"),
        "product_id": UUID("c0000001-0000-0000-0000-000000000001"),
        "supplier_id": UUID("d0000001-0000-0000-0000-000000000001"),
        "price": Decimal("12.50"),
        "currency": "USD",
        "source": "supplier",
        "effective_date": datetime(2025, 1, 1, tzinfo=timezone.utc),
    },
    {
        "id": UUID("f0000001-0000-0000-0000-000000000002"),
        "product_id": UUID("c0000001-0000-0000-0000-000000000001"),
        "supplier_id": UUID("d0000001-0000-0000-0000-000000000001"),
        "price": Decimal("11.80"),
        "currency": "USD",
        "source": "supplier",
        "effective_date": datetime(2025, 3, 1, tzinfo=timezone.utc),
    },
    {
        "id": UUID("f0000001-0000-0000-0000-000000000003"),
        "product_id": UUID("c0000001-0000-0000-0000-000000000002"),
        "price": Decimal("198.00"),
        "currency": "USD",
        "source": "manual",
        "effective_date": datetime(2025, 1, 15, tzinfo=timezone.utc),
    },
]

# ── Amazon Prices (historical) ────────────────────────────────
AMAZON_PRICES = [
    {
        "id": UUID("a0000001-0000-0000-0000-000000000001"),
        "product_id": UUID("c0000001-0000-0000-0000-000000000001"),
        "price": Decimal("25.99"),
        "currency": "USD",
        "condition": "New",
        "is_amazon_fulfilled": True,
        "is_buy_box": True,
        "is_prime": True,
        "effective_date": datetime(2025, 1, 1, tzinfo=timezone.utc),
    },
    {
        "id": UUID("a0000001-0000-0000-0000-000000000002"),
        "product_id": UUID("c0000001-0000-0000-0000-000000000001"),
        "price": Decimal("24.99"),
        "currency": "USD",
        "condition": "New",
        "is_amazon_fulfilled": True,
        "is_buy_box": True,
        "is_prime": True,
        "effective_date": datetime(2025, 3, 15, tzinfo=timezone.utc),
    },
    {
        "id": UUID("a0000001-0000-0000-0000-000000000003"),
        "product_id": UUID("c0000001-0000-0000-0000-000000000002"),
        "price": Decimal("349.99"),
        "currency": "USD",
        "condition": "New",
        "is_amazon_fulfilled": True,
        "is_buy_box": True,
        "is_prime": True,
        "effective_date": datetime(2025, 1, 15, tzinfo=timezone.utc),
    },
    {
        "id": UUID("a0000001-0000-0000-0000-000000000004"),
        "product_id": UUID("c0000001-0000-0000-0000-000000000003"),
        "price": Decimal("39.99"),
        "currency": "USD",
        "condition": "New",
        "is_amazon_fulfilled": False,
        "is_buy_box": True,
        "is_prime": False,
        "effective_date": datetime(2025, 2, 1, tzinfo=timezone.utc),
    },
]

# ── Historical Fees ───────────────────────────────────────────
HISTORICAL_FEES = [
    {
        "id": UUID("80000001-0000-0000-0000-000000000001"),
        "product_id": UUID("c0000001-0000-0000-0000-000000000001"),
        "referral_fee": Decimal("3.75"),
        "closing_fee": Decimal("0.00"),
        "storage_fee": Decimal("0.15"),
        "fulfillment_fee": Decimal("4.50"),
        "other_fees": Decimal("0.00"),
        "total_fees": Decimal("8.40"),
        "currency": "USD",
        "effective_date": datetime(2025, 3, 15, tzinfo=timezone.utc),
    },
    {
        "id": UUID("80000001-0000-0000-0000-000000000002"),
        "product_id": UUID("c0000001-0000-0000-0000-000000000002"),
        "referral_fee": Decimal("52.50"),
        "closing_fee": Decimal("0.00"),
        "storage_fee": Decimal("1.20"),
        "fulfillment_fee": Decimal("6.50"),
        "other_fees": Decimal("0.00"),
        "total_fees": Decimal("60.20"),
        "currency": "USD",
        "effective_date": datetime(2025, 1, 15, tzinfo=timezone.utc),
    },
]

# ── Seller Counts ─────────────────────────────────────────────
SELLER_COUNTS = [
    {
        "id": UUID("90000001-0000-0000-0000-000000000001"),
        "product_id": UUID("c0000001-0000-0000-0000-000000000001"),
        "new_seller_count": 12,
        "used_seller_count": 5,
        "fba_seller_count": 8,
        "effective_date": datetime(2025, 3, 15, tzinfo=timezone.utc),
    },
    {
        "id": UUID("90000001-0000-0000-0000-000000000002"),
        "product_id": UUID("c0000001-0000-0000-0000-000000000002"),
        "new_seller_count": 3,
        "used_seller_count": 8,
        "fba_seller_count": 2,
        "effective_date": datetime(2025, 1, 15, tzinfo=timezone.utc),
    },
]

# ── Reviews ───────────────────────────────────────────────────
REVIEWS = [
    {
        "id": UUID("a0000001-0000-0000-0000-000000000001"),
        "product_id": UUID("c0000001-0000-0000-0000-000000000001"),
        "rating": Decimal("4.7"),
        "review_count": 45230,
        "answered_questions": 320,
        "effective_date": datetime(2025, 3, 15, tzinfo=timezone.utc),
    },
    {
        "id": UUID("a0000001-0000-0000-0000-000000000002"),
        "product_id": UUID("c0000001-0000-0000-0000-000000000002"),
        "rating": Decimal("4.5"),
        "review_count": 18750,
        "answered_questions": 890,
        "effective_date": datetime(2025, 1, 15, tzinfo=timezone.utc),
    },
]

# ── Sales Estimates ───────────────────────────────────────────
SALES_ESTIMATES = [
    {
        "id": UUID("b0000001-0000-0000-0000-000000000001"),
        "product_id": UUID("c0000001-0000-0000-0000-000000000001"),
        "estimated_monthly_sales": 8500,
        "estimated_daily_sales": Decimal("283.33"),
        "estimated_monthly_revenue": Decimal("212415.00"),
        "sales_rank": 1250,
        "sales_rank_category": "Cell Phone Accessories",
        "effective_date": datetime(2025, 3, 15, tzinfo=timezone.utc),
    },
    {
        "id": UUID("b0000001-0000-0000-0000-000000000002"),
        "product_id": UUID("c0000001-0000-0000-0000-000000000002"),
        "estimated_monthly_sales": 3200,
        "estimated_daily_sales": Decimal("106.67"),
        "estimated_monthly_revenue": Decimal("1119968.00"),
        "sales_rank": 450,
        "sales_rank_category": "Over-Ear Headphones",
        "effective_date": datetime(2025, 1, 15, tzinfo=timezone.utc),
    },
]

# ── Profit Calculations ───────────────────────────────────────
PROFIT_CALCULATIONS = [
    {
        "id": UUID("c0000001-0000-0000-0000-000000000001"),
        "product_id": UUID("c0000001-0000-0000-0000-000000000001"),
        "amazon_price_id": UUID("a0000001-0000-0000-0000-000000000002"),
        "product_price_id": UUID("f0000001-0000-0000-0000-000000000002"),
        "fee_id": UUID("80000001-0000-0000-0000-000000000001"),
        "unit_cost": Decimal("11.80"),
        "amazon_price": Decimal("24.99"),
        "referral_fee": Decimal("3.75"),
        "fulfillment_fee": Decimal("4.50"),
        "storage_fee": Decimal("0.15"),
        "other_costs": Decimal("1.50"),
        "total_cost": Decimal("21.70"),
        "gross_profit": Decimal("13.19"),
        "net_profit": Decimal("3.29"),
        "margin_percentage": Decimal("13.16"),
        "roi_percentage": Decimal("15.16"),
        "currency": "USD",
        "effective_date": datetime(2025, 3, 15, tzinfo=timezone.utc),
    },
]

# ── Users ─────────────────────────────────────────────────────
USERS = [
    {
        "id": UUID("d0000001-0000-0000-0000-000000000001"),
        "email": "alice@example.com",
        "username": "alice_sourcer",
        "password_hash": "$2b$12$LJ3m4ys3Lk0TSwHnbfOMiOXPm1Qlq5Yx5E5Y5e5Y5e5Y5e5Y5e5Y",
        "display_name": "Alice Johnson",
        "role": "admin",
        "is_active": True,
        "email_verified_at": datetime(2025, 1, 1, tzinfo=timezone.utc),
    },
    {
        "id": UUID("d0000001-0000-0000-0000-000000000002"),
        "email": "bob@example.com",
        "username": "bob_sourcer",
        "password_hash": "$2b$12$LJ3m4ys3Lk0TSwHnbfOMiOXPm1Qlq5Yx5E5Y5e5Y5e5Y5e5Y5e5Y",
        "display_name": "Bob Martinez",
        "role": "user",
        "is_active": True,
        "email_verified_at": datetime(2025, 1, 15, tzinfo=timezone.utc),
    },
]

# ── User Settings ─────────────────────────────────────────────
USER_SETTINGS = [
    {
        "id": UUID("e0000001-0000-0000-0000-000000000001"),
        "user_id": UUID("d0000001-0000-0000-0000-000000000001"),
        "default_currency": "USD",
        "profit_margin_target": Decimal("15.00"),
        "notification_preferences": {
            "email": True,
            "push": True,
            "in_app": True,
            "price_drop": True,
            "profit_threshold": True,
            "stock_alert": False,
        },
        "display_preferences": {
            "theme": "dark",
            "default_view": "table",
            "rows_per_page": 50,
        },
    },
    {
        "id": UUID("e0000001-0000-0000-0000-000000000002"),
        "user_id": UUID("d0000001-0000-0000-0000-000000000002"),
        "default_currency": "USD",
        "profit_margin_target": Decimal("20.00"),
        "notification_preferences": {
            "email": True,
            "push": False,
            "in_app": True,
            "price_drop": True,
            "profit_threshold": True,
            "stock_alert": True,
        },
        "display_preferences": {
            "theme": "light",
            "default_view": "card",
            "rows_per_page": 25,
        },
    },
]

# ── Alerts ────────────────────────────────────────────────────
ALERTS = [
    {
        "id": UUID("f0000001-0000-0000-0000-000000000001"),
        "user_id": UUID("d0000001-0000-0000-0000-000000000001"),
        "product_id": UUID("c0000001-0000-0000-0000-000000000001"),
        "alert_type": "price_drop",
        "condition": {"price_below": 20.00},
        "is_active": True,
        "is_triggered": False,
    },
    {
        "id": UUID("f0000001-0000-0000-0000-000000000002"),
        "user_id": UUID("d0000001-0000-0000-0000-000000000001"),
        "product_id": UUID("c0000001-0000-0000-0000-000000000002"),
        "alert_type": "profit_threshold",
        "condition": {"margin_above": 15.0},
        "is_active": True,
        "is_triggered": False,
    },
]

# ── Watchlist Items ───────────────────────────────────────────
WATCHLIST_ITEMS = [
    {
        "id": UUID("00000001-0000-0000-0000-000000000001"),
        "user_id": UUID("d0000001-0000-0000-0000-000000000001"),
        "product_id": UUID("c0000001-0000-0000-0000-000000000001"),
        "notes": "High volume, good margin potential",
    },
    {
        "id": UUID("00000001-0000-0000-0000-000000000002"),
        "user_id": UUID("d0000001-0000-0000-0000-000000000001"),
        "product_id": UUID("c0000001-0000-0000-0000-000000000002"),
        "notes": "Premium product, check price trends",
    },
    {
        "id": UUID("00000001-0000-0000-0000-000000000003"),
        "user_id": UUID("d0000001-0000-0000-0000-000000000002"),
        "product_id": UUID("c0000001-0000-0000-0000-000000000003"),
        "notes": "Bulky item, check FBA fees",
    },
]

# ── Notifications ─────────────────────────────────────────────
NOTIFICATIONS = [
    {
        "id": UUID("10000001-0000-0000-0000-000000000001"),
        "user_id": UUID("d0000001-0000-0000-0000-000000000001"),
        "alert_id": UUID("f0000001-0000-0000-0000-000000000001"),
        "title": "Price Drop Alert: Anker PowerCore",
        "body": "The price for Anker PowerCore 10000mAh has dropped below $20.00. Current price: $18.50",
        "channel": "in_app",
        "is_read": False,
    },
    {
        "id": UUID("10000001-0000-0000-0000-000000000002"),
        "user_id": UUID("d0000001-0000-0000-0000-000000000001"),
        "alert_id": None,
        "title": "Welcome to Amazon Sourcer Pro!",
        "body": "Start by adding products to your watchlist and setting up price alerts.",
        "channel": "in_app",
        "is_read": True,
        "read_at": datetime(2025, 1, 1, tzinfo=timezone.utc),
    },
]

# ── Inventory ─────────────────────────────────────────────────
INVENTORY = [
    {
        "id": UUID("20000001-0000-0000-0000-000000000001"),
        "product_id": UUID("c0000001-0000-0000-0000-000000000001"),
        "supplier_id": UUID("d0000001-0000-0000-0000-000000000001"),
        "quantity_on_hand": 500,
        "quantity_reserved": 23,
        "quantity_inbound": 1000,
        "warehouse_location": "A-12-B",
        "lot_number": "LOT-2025-001",
    },
    {
        "id": UUID("20000001-0000-0000-0000-000000000002"),
        "product_id": UUID("c0000001-0000-0000-0000-000000000003"),
        "supplier_id": UUID("d0000001-0000-0000-0000-000000000002"),
        "quantity_on_hand": 200,
        "quantity_reserved": 5,
        "quantity_inbound": 0,
        "warehouse_location": "B-04-C",
    },
]
