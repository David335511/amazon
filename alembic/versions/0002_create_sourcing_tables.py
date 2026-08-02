"""Create sourcing platform schema: brands, categories, suppliers, pricing, analytics, users.

Revision ID: 0002_create_sourcing_tables
Revises: 0001_create_initial_tables
Create Date: 2025-01-01 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002_create_sourcing_tables"
down_revision: Union[str, None] = "0001_create_initial_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create all sourcing platform tables."""

    # ═══════════════════════════════════════════════════════════
    # Brands
    # ═══════════════════════════════════════════════════════════
    op.create_table(
        "brands",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("logo_url", sa.String(500), nullable=True),
        sa.Column("website_url", sa.String(500), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index(op.f("ix_brands_name"), "brands", ["name"])

    # ═══════════════════════════════════════════════════════════
    # Categories (self-referential hierarchy)
    # ═══════════════════════════════════════════════════════════
    op.create_table(
        "categories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(255), nullable=False),
        sa.Column("path", sa.Text(), nullable=True,
                  comment="Materialized path for subtree queries, e.g. 'root_id/parent_id/this_id'"),
        sa.Column("level", sa.Integer(), nullable=False, server_default="0",
                  comment="Depth in hierarchy (0 = root)"),
        sa.Column("amazon_category_id", sa.String(100), nullable=True,
                  comment="Amazon's internal category/node ID"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("amazon_category_id"),
        sa.ForeignKeyConstraint(["parent_id"], ["categories.id"], ondelete="SET NULL"),
    )
    op.create_index(op.f("ix_categories_parent_id"), "categories", ["parent_id"])
    op.create_index(op.f("ix_categories_slug"), "categories", ["slug"])

    # ═══════════════════════════════════════════════════════════
    # Update Products table — add sourcing columns
    # ═══════════════════════════════════════════════════════════
    # Rename old columns to new schema
    op.alter_column("products", "name", new_column_name="title")
    op.alter_column("products", "price", new_column_name="legacy_price")
    op.alter_column("products", "stock_quantity", new_column_name="legacy_stock_quantity")

    # Add new columns
    op.add_column("products", sa.Column("asin", sa.String(10), nullable=True))
    op.add_column("products", sa.Column("upc", sa.String(12), nullable=True))
    op.add_column("products", sa.Column("ean", sa.String(13), nullable=True))
    op.add_column("products", sa.Column("gtin", sa.String(14), nullable=True))
    op.add_column("products", sa.Column("brand_id", sa.Uuid(), nullable=True))
    op.add_column("products", sa.Column("category_id", sa.Uuid(), nullable=True))
    op.add_column("products", sa.Column("main_image_url", sa.String(500), nullable=True))
    op.add_column("products", sa.Column("image_urls", sa.Text(), nullable=True))
    op.add_column("products", sa.Column("weight", sa.Numeric(10, 2), nullable=True))
    op.add_column("products", sa.Column("weight_unit", sa.String(10), nullable=True))
    op.add_column("products", sa.Column("dimensions", sa.String(100), nullable=True))
    op.add_column("products", sa.Column("is_amazon_fba", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("products", sa.Column("is_amazon_brand", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("products", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))

    # Add foreign keys
    op.create_foreign_key("fk_products_brand_id", "products", "brands", ["brand_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_products_category_id", "products", "categories", ["category_id"], ["id"], ondelete="SET NULL")

    # Add indexes
    op.create_index(op.f("ix_products_asin"), "products", ["asin"], unique=True)
    op.create_index(op.f("ix_products_upc"), "products", ["upc"])
    op.create_index(op.f("ix_products_ean"), "products", ["ean"])
    op.create_index(op.f("ix_products_gtin"), "products", ["gtin"])
    op.create_index(op.f("ix_products_brand_id"), "products", ["brand_id"])
    op.create_index(op.f("ix_products_category_id"), "products", ["category_id"])
    op.create_index(op.f("ix_products_title"), "products", ["title"])

    # Drop old indexes that changed
    op.drop_index("ix_products_name", table_name="products")
    op.drop_index("ix_products_category", table_name="products")

    # ═══════════════════════════════════════════════════════════
    # Suppliers
    # ═══════════════════════════════════════════════════════════
    op.create_table(
        "suppliers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("company_name", sa.String(255), nullable=True),
        sa.Column("contact_name", sa.String(255), nullable=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("phone", sa.String(50), nullable=True),
        sa.Column("website", sa.String(500), nullable=True),
        sa.Column("address_line1", sa.String(255), nullable=True),
        sa.Column("address_line2", sa.String(255), nullable=True),
        sa.Column("city", sa.String(100), nullable=True),
        sa.Column("state", sa.String(100), nullable=True),
        sa.Column("postal_code", sa.String(20), nullable=True),
        sa.Column("country", sa.String(100), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("rating", sa.Numeric(3, 2), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("rating >= 1.0 AND rating <= 5.0", name="ck_supplier_rating_range"),
    )
    op.create_index(op.f("ix_suppliers_name"), "suppliers", ["name"])

    # ═══════════════════════════════════════════════════════════
    # Supplier Products (junction)
    # ═══════════════════════════════════════════════════════════
    op.create_table(
        "supplier_products",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("supplier_id", sa.Uuid(), nullable=False),
        sa.Column("supplier_sku", sa.String(100), nullable=True),
        sa.Column("supplier_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("moq", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("lead_time_days", sa.Integer(), nullable=True),
        sa.Column("is_preferred", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("product_id", "supplier_id", name="uq_supplier_product"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"], ondelete="CASCADE"),
        sa.CheckConstraint("moq >= 1", name="ck_supplier_product_moq"),
        sa.CheckConstraint("supplier_price > 0", name="ck_supplier_product_price_positive"),
    )
    op.create_index(op.f("ix_supplier_products_product_id"), "supplier_products", ["product_id"])
    op.create_index(op.f("ix_supplier_products_supplier_id"), "supplier_products", ["supplier_id"])

    # ═══════════════════════════════════════════════════════════
    # Product Prices (historical, append-only)
    # ═══════════════════════════════════════════════════════════
    op.create_table(
        "product_prices",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("supplier_id", sa.Uuid(), nullable=True),
        sa.Column("price", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("quantity_break", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(50), nullable=False, server_default="manual"),
        sa.Column("effective_date", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"], ondelete="SET NULL"),
        sa.CheckConstraint("price > 0", name="ck_product_price_positive"),
    )
    op.create_index(op.f("ix_product_prices_product_id"), "product_prices", ["product_id"])
    op.create_index(op.f("ix_product_prices_supplier_id"), "product_prices", ["supplier_id"])
    op.create_index("ix_product_prices_effective", "product_prices", ["product_id", "effective_date"])

    # ═══════════════════════════════════════════════════════════
    # Amazon Prices (historical, append-only)
    # ═══════════════════════════════════════════════════════════
    op.create_table(
        "amazon_prices",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("price", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("condition", sa.String(50), nullable=False, server_default="New"),
        sa.Column("is_amazon_fulfilled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_buy_box", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_prime", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("effective_date", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.CheckConstraint("price > 0", name="ck_amazon_price_positive"),
    )
    op.create_index(op.f("ix_amazon_prices_product_id"), "amazon_prices", ["product_id"])
    op.create_index("ix_amazon_prices_effective", "amazon_prices", ["product_id", "effective_date"])

    # ═══════════════════════════════════════════════════════════
    # Historical Fees (historical, append-only)
    # ═══════════════════════════════════════════════════════════
    op.create_table(
        "historical_fees",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("referral_fee", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("closing_fee", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("storage_fee", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("fulfillment_fee", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("other_fees", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("total_fees", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("effective_date", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.CheckConstraint("total_fees >= 0", name="ck_fees_total_non_negative"),
    )
    op.create_index(op.f("ix_historical_fees_product_id"), "historical_fees", ["product_id"])
    op.create_index("ix_historical_fees_effective", "historical_fees", ["product_id", "effective_date"])

    # ═══════════════════════════════════════════════════════════
    # Seller Counts (historical, append-only)
    # ═══════════════════════════════════════════════════════════
    op.create_table(
        "seller_counts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("new_seller_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("used_seller_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fba_seller_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("effective_date", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.CheckConstraint("new_seller_count >= 0", name="ck_seller_count_new_non_negative"),
        sa.CheckConstraint("used_seller_count >= 0", name="ck_seller_count_used_non_negative"),
        sa.CheckConstraint("fba_seller_count >= 0", name="ck_seller_count_fba_non_negative"),
    )
    op.create_index(op.f("ix_seller_counts_product_id"), "seller_counts", ["product_id"])
    op.create_index("ix_seller_counts_effective", "seller_counts", ["product_id", "effective_date"])

    # ═══════════════════════════════════════════════════════════
    # Reviews (historical, append-only)
    # ═══════════════════════════════════════════════════════════
    op.create_table(
        "reviews",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("rating", sa.Numeric(3, 2), nullable=False),
        sa.Column("review_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("answered_questions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("effective_date", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.CheckConstraint("rating >= 1.0 AND rating <= 5.0", name="ck_review_rating_range"),
        sa.CheckConstraint("review_count >= 0", name="ck_review_count_non_negative"),
    )
    op.create_index(op.f("ix_reviews_product_id"), "reviews", ["product_id"])
    op.create_index("ix_reviews_effective", "reviews", ["product_id", "effective_date"])

    # ═══════════════════════════════════════════════════════════
    # Sales Estimates (historical, append-only)
    # ═══════════════════════════════════════════════════════════
    op.create_table(
        "sales_estimates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("estimated_monthly_sales", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("estimated_daily_sales", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("estimated_monthly_revenue", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("sales_rank", sa.Integer(), nullable=True),
        sa.Column("sales_rank_category", sa.String(255), nullable=True),
        sa.Column("effective_date", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.CheckConstraint("estimated_monthly_sales >= 0", name="ck_sales_estimate_monthly_non_negative"),
    )
    op.create_index(op.f("ix_sales_estimates_product_id"), "sales_estimates", ["product_id"])
    op.create_index("ix_sales_estimates_effective", "sales_estimates", ["product_id", "effective_date"])

    # ═══════════════════════════════════════════════════════════
    # Profit Calculations (historical, append-only)
    # ═══════════════════════════════════════════════════════════
    op.create_table(
        "profit_calculations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("amazon_price_id", sa.Uuid(), nullable=True),
        sa.Column("product_price_id", sa.Uuid(), nullable=True),
        sa.Column("fee_id", sa.Uuid(), nullable=True),
        sa.Column("unit_cost", sa.Numeric(12, 2), nullable=False),
        sa.Column("amazon_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("referral_fee", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("fulfillment_fee", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("storage_fee", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("other_costs", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("total_cost", sa.Numeric(12, 2), nullable=False),
        sa.Column("gross_profit", sa.Numeric(12, 2), nullable=False),
        sa.Column("net_profit", sa.Numeric(12, 2), nullable=False),
        sa.Column("margin_percentage", sa.Numeric(5, 2), nullable=False),
        sa.Column("roi_percentage", sa.Numeric(8, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("effective_date", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["amazon_price_id"], ["amazon_prices.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["product_price_id"], ["product_prices.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["fee_id"], ["historical_fees.id"], ondelete="SET NULL"),
    )
    op.create_index(op.f("ix_profit_calculations_product_id"), "profit_calculations", ["product_id"])
    op.create_index("ix_profit_calculations_effective", "profit_calculations", ["product_id", "effective_date"])

    # ═══════════════════════════════════════════════════════════
    # Inventory
    # ═══════════════════════════════════════════════════════════
    op.create_table(
        "inventory",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("supplier_id", sa.Uuid(), nullable=True),
        sa.Column("quantity_on_hand", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("quantity_reserved", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("quantity_inbound", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("warehouse_location", sa.String(100), nullable=True),
        sa.Column("lot_number", sa.String(100), nullable=True),
        sa.Column("expiry_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"], ondelete="SET NULL"),
        sa.CheckConstraint("quantity_on_hand >= 0", name="ck_inventory_on_hand_non_negative"),
        sa.CheckConstraint("quantity_reserved >= 0", name="ck_inventory_reserved_non_negative"),
        sa.CheckConstraint("quantity_inbound >= 0", name="ck_inventory_inbound_non_negative"),
    )
    op.create_index(op.f("ix_inventory_product_id"), "inventory", ["product_id"])
    op.create_index("ix_inventory_product_supplier", "inventory", ["product_id", "supplier_id"])

    # ═══════════════════════════════════════════════════════════
    # Users
    # ═══════════════════════════════════════════════════════════
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("username", sa.String(100), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=True),
        sa.Column("avatar_url", sa.String(500), nullable=True),
        sa.Column("role", sa.String(50), nullable=False, server_default="user"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
        sa.UniqueConstraint("username"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"])
    op.create_index(op.f("ix_users_username"), "users", ["username"])

    # ═══════════════════════════════════════════════════════════
    # User Settings (1:1 with users)
    # ═══════════════════════════════════════════════════════════
    op.create_table(
        "user_settings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("default_currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("profit_margin_target", sa.Numeric(5, 2), nullable=True),
        sa.Column("notification_preferences", sa.JSON(), nullable=True),
        sa.Column("display_preferences", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )

    # ═══════════════════════════════════════════════════════════
    # Alerts
    # ═══════════════════════════════════════════════════════════
    op.create_table(
        "alerts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=True),
        sa.Column("alert_type", sa.String(50), nullable=False),
        sa.Column("condition", sa.JSON(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("is_triggered", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("last_triggered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
    )
    op.create_index(op.f("ix_alerts_user_id"), "alerts", ["user_id"])
    op.create_index(op.f("ix_alerts_product_id"), "alerts", ["product_id"])
    op.create_index("ix_alerts_user_type", "alerts", ["user_id", "alert_type"])

    # ═══════════════════════════════════════════════════════════
    # Watchlist Items
    # ═══════════════════════════════════════════════════════════
    op.create_table(
        "watchlist_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "product_id", name="uq_watchlist_user_product"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
    )
    op.create_index(op.f("ix_watchlist_items_user_id"), "watchlist_items", ["user_id"])
    op.create_index(op.f("ix_watchlist_items_product_id"), "watchlist_items", ["product_id"])

    # ═══════════════════════════════════════════════════════════
    # Notifications
    # ═══════════════════════════════════════════════════════════
    op.create_table(
        "notifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("alert_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("channel", sa.String(50), nullable=False, server_default="in_app"),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["alert_id"], ["alerts.id"], ondelete="SET NULL"),
    )
    op.create_index(op.f("ix_notifications_user_id"), "notifications", ["user_id"])
    op.create_index("ix_notifications_user_read", "notifications", ["user_id", "is_read"])


def downgrade() -> None:
    """Drop all sourcing platform tables in reverse dependency order."""
    op.drop_table("notifications")
    op.drop_table("watchlist_items")
    op.drop_table("alerts")
    op.drop_table("user_settings")
    op.drop_table("users")
    op.drop_table("inventory")
    op.drop_table("profit_calculations")
    op.drop_table("sales_estimates")
    op.drop_table("reviews")
    op.drop_table("seller_counts")
    op.drop_table("historical_fees")
    op.drop_table("amazon_prices")
    op.drop_table("product_prices")
    op.drop_table("supplier_products")
    op.drop_table("suppliers")

    # Revert products table changes
    op.drop_constraint("fk_products_brand_id", "products", type_="foreignkey")
    op.drop_constraint("fk_products_category_id", "products", type_="foreignkey")
    op.drop_index("ix_products_asin", table_name="products")
    op.drop_index("ix_products_upc", table_name="products")
    op.drop_index("ix_products_ean", table_name="products")
    op.drop_index("ix_products_gtin", table_name="products")
    op.drop_index("ix_products_brand_id", table_name="products")
    op.drop_index("ix_products_category_id", table_name="products")
    op.drop_index("ix_products_title", table_name="products")

    op.drop_column("products", "deleted_at")
    op.drop_column("products", "is_amazon_brand")
    op.drop_column("products", "is_amazon_fba")
    op.drop_column("products", "dimensions")
    op.drop_column("products", "weight_unit")
    op.drop_column("products", "weight")
    op.drop_column("products", "image_urls")
    op.drop_column("products", "main_image_url")
    op.drop_column("products", "category_id")
    op.drop_column("products", "brand_id")
    op.drop_column("products", "gtin")
    op.drop_column("products", "ean")
    op.drop_column("products", "upc")
    op.drop_column("products", "asin")

    op.alter_column("products", "title", new_column_name="name")
    op.alter_column("products", "legacy_price", new_column_name="price")
    op.alter_column("products", "legacy_stock_quantity", new_column_name="stock_quantity")

    op.create_index(op.f("ix_products_name"), "products", ["name"])
    op.create_index(op.f("ix_products_category"), "products", ["category"])

    op.drop_table("categories")
    op.drop_table("brands")
