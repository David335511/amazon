"""Create the supplier-intelligence table.

Adds ``supplier_observations`` — the **historical** record of supplier
behaviour: one row per supplier per observed period, capturing the tracked
dimensions (price, sale/coupon frequency, inventory stability, shipping speed,
return policy, customer service, order-cancellation rate, discount patterns,
stockout frequency). The five supplier scores are computed on demand over this
history.

Revision ID: 0010_create_supplier_observation_tables
Revises: 0009_create_finance_tables
Create Date: 2026-08-06 10:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0010_create_supplier_observation_tables"
down_revision: str | None = "0009_create_finance_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "supplier_observations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("supplier_id", sa.String(128), nullable=False),
        sa.Column("supplier_name", sa.String(255), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("price", sa.Float(), nullable=False, server_default="0"),
        sa.Column("sale_events", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("coupon_events", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("inventory_level", sa.Float(), nullable=False, server_default="0"),
        sa.Column("inventory_variance", sa.Float(), nullable=False, server_default="0"),
        sa.Column("stockouts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("shipping_days", sa.Float(), nullable=False, server_default="0"),
        sa.Column("return_policy_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("customer_service_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("order_cancellation_rate", sa.Float(), nullable=False, server_default="0"),
        sa.Column("discount_depth", sa.Float(), nullable=False, server_default="0"),
        sa.Column("discount_events", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source", sa.String(32), nullable=False, server_default="manual"),
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
    op.create_index(
        "ix_supplier_observations_supplier_id", "supplier_observations", ["supplier_id"]
    )
    op.create_index(
        "ix_supplier_observations_observed_at", "supplier_observations", ["observed_at"]
    )


def downgrade() -> None:
    op.drop_index(
        "ix_supplier_observations_observed_at", table_name="supplier_observations"
    )
    op.drop_index(
        "ix_supplier_observations_supplier_id", table_name="supplier_observations"
    )
    op.drop_table("supplier_observations")
