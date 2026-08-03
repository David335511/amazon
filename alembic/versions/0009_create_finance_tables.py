"""Create the financial optimization tables.

Adds ``cash_ledger`` (a running record of every cash movement: payouts,
purchases, purchase commitments, cashback, expenses, storage, refunds) and
``capital_allocations`` (capital-allocation decisions with expected return,
capital efficiency, risk and policy, for dashboards and audits).

Revision ID: 0009_create_finance_tables
Revises: 0008_create_forecast_tables
Create Date: 2026-08-05 10:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009_create_finance_tables"
down_revision: str | None = "0008_create_forecast_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cash_ledger",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("transaction_type", sa.String(8), nullable=False),
        sa.Column("category", sa.String(16), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("entity_type", sa.String(32), nullable=True),
        sa.Column("entity_id", sa.String(128), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
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
    op.create_index("ix_cash_ledger_transaction_type", "cash_ledger", ["transaction_type"])
    op.create_index("ix_cash_ledger_category", "cash_ledger", ["category"])

    op.create_table(
        "capital_allocations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("entity_id", sa.String(128), nullable=False),
        sa.Column("allocated_amount", sa.Float(), nullable=False),
        sa.Column("units", sa.Float(), nullable=False, server_default="0"),
        sa.Column("expected_return", sa.Float(), nullable=False, server_default="0"),
        sa.Column("capital_efficiency", sa.Float(), nullable=False, server_default="0"),
        sa.Column("risk", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("policy", sa.String(16), nullable=False, server_default="efficiency"),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
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
    op.create_index("ix_capital_allocations_entity_type", "capital_allocations", ["entity_type"])
    op.create_index("ix_capital_allocations_entity_id", "capital_allocations", ["entity_id"])


def downgrade() -> None:
    op.drop_index("ix_capital_allocations_entity_id", table_name="capital_allocations")
    op.drop_index("ix_capital_allocations_entity_type", table_name="capital_allocations")
    op.drop_table("capital_allocations")
    op.drop_index("ix_cash_ledger_category", table_name="cash_ledger")
    op.drop_index("ix_cash_ledger_transaction_type", table_name="cash_ledger")
    op.drop_table("cash_ledger")
