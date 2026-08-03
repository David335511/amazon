"""Create the reverse-sourcing tables.

Adds ``reverse_sourcing_runs`` (one row per ASIN sourced, with inputs and
highlights) and ``reverse_sourcing_offers`` (one row per supplier per run,
capturing unit price, shipping, landed cost, availability, discount, rank and
predicted discount). Accumulated across runs, offers form the historical
per-(supplier, ASIN) price / discount series.

Revision ID: 0011_create_reverse_sourcing_tables
Revises: 0010_create_supplier_observation_tables
Create Date: 2026-08-07 10:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0011_create_reverse_sourcing_tables"
down_revision: str | None = "0010_create_supplier_observation_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reverse_sourcing_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("asin", sa.String(16), nullable=False),
        sa.Column("upc", sa.String(16), nullable=True),
        sa.Column("title", sa.String(255), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("postal_code", sa.String(16), nullable=True),
        sa.Column("currency", sa.String(8), nullable=False, server_default="USD"),
        sa.Column("best_supplier", sa.String(48), nullable=True),
        sa.Column("cheapest_supplier", sa.String(48), nullable=True),
        sa.Column("fastest_supplier", sa.String(48), nullable=True),
        sa.Column("highest_confidence_supplier", sa.String(48), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_reverse_sourcing_runs_asin", "reverse_sourcing_runs", ["asin"])

    op.create_table(
        "reverse_sourcing_offers",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "run_id",
            sa.Uuid(),
            sa.ForeignKey("reverse_sourcing_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("supplier_code", sa.String(48), nullable=False),
        sa.Column("supplier_name", sa.String(255), nullable=True),
        sa.Column("supplier_sku", sa.String(64), nullable=False, server_default=""),
        sa.Column("unit_price", sa.Float(), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(8), nullable=False, server_default="USD"),
        sa.Column("shipping_cost", sa.Float(), nullable=False, server_default="0"),
        sa.Column("shipping_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("landed_cost", sa.Float(), nullable=False, server_default="0"),
        sa.Column("in_stock", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("stock_status", sa.String(16), nullable=False, server_default="unknown"),
        sa.Column("moq", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("current_discount", sa.Float(), nullable=False, server_default="0"),
        sa.Column("predicted_discount", sa.Float(), nullable=True),
        sa.Column("rank", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_reverse_sourcing_offers_run_id", "reverse_sourcing_offers", ["run_id"])
    op.create_index(
        "ix_reverse_sourcing_offers_supplier_code", "reverse_sourcing_offers", ["supplier_code"]
    )


def downgrade() -> None:
    op.drop_index(
        "ix_reverse_sourcing_offers_supplier_code", table_name="reverse_sourcing_offers"
    )
    op.drop_index("ix_reverse_sourcing_offers_run_id", table_name="reverse_sourcing_offers")
    op.drop_table("reverse_sourcing_offers")
    op.drop_index("ix_reverse_sourcing_runs_asin", table_name="reverse_sourcing_runs")
    op.drop_table("reverse_sourcing_runs")
