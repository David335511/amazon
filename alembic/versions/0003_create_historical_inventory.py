"""Create historical_inventory table for append-only inventory snapshots.

Revision ID: 0003_create_historical_inventory
Revises: 0002_create_sourcing_tables
Create Date: 2025-07-31 22:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003_create_historical_inventory"
down_revision: Union[str, None] = "0002_create_sourcing_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the historical_inventory table.

    This is an append-only table for inventory snapshots. Every
    observation creates a new row — never UPDATE or DELETE.
    """
    op.create_table(
        "historical_inventory",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("supplier_id", sa.Uuid(), nullable=True),

        # Stock levels
        sa.Column("quantity_on_hand", sa.Integer(), nullable=False, server_default="0",
                  comment="Physical quantity in stock at observation time"),
        sa.Column("quantity_reserved", sa.Integer(), nullable=False, server_default="0",
                  comment="Quantity reserved for existing orders"),
        sa.Column("quantity_inbound", sa.Integer(), nullable=False, server_default="0",
                  comment="Quantity inbound from supplier"),
        sa.Column("quantity_available", sa.Integer(), nullable=False, server_default="0",
                  comment="Computed: on_hand - reserved (denormalized for query speed)"),

        # Location & Lot
        sa.Column("warehouse_location", sa.String(100), nullable=True),
        sa.Column("lot_number", sa.String(100), nullable=True),

        # Timestamps
        sa.Column("effective_date", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False,
                  comment="When this inventory snapshot was taken"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),

        # Constraints
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"], ondelete="SET NULL"),
        sa.CheckConstraint("quantity_on_hand >= 0", name="ck_historical_inventory_on_hand_non_negative"),
        sa.CheckConstraint("quantity_reserved >= 0", name="ck_historical_inventory_reserved_non_negative"),
        sa.CheckConstraint("quantity_inbound >= 0", name="ck_historical_inventory_inbound_non_negative"),
        sa.CheckConstraint("quantity_available >= 0", name="ck_historical_inventory_available_non_negative"),
    )

    # Primary time-series index
    op.create_index(
        "ix_historical_inventory_effective",
        "historical_inventory",
        ["product_id", "effective_date"],
    )

    # Secondary index for supplier-level analysis
    op.create_index(
        "ix_historical_inventory_supplier",
        "historical_inventory",
        ["product_id", "supplier_id", "effective_date"],
    )

    op.create_index(
        op.f("ix_historical_inventory_product_id"),
        "historical_inventory",
        ["product_id"],
    )


def downgrade() -> None:
    """Drop the historical_inventory table."""
    op.drop_index(op.f("ix_historical_inventory_product_id"), table_name="historical_inventory")
    op.drop_index("ix_historical_inventory_supplier", table_name="historical_inventory")
    op.drop_index("ix_historical_inventory_effective", table_name="historical_inventory")
    op.drop_table("historical_inventory")
