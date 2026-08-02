"""Make products.sku nullable.

The ORM ``Product`` model does not define a ``sku`` column (the API schema and
create service don't provide one), but migration ``0001`` created it as
``NOT NULL``. That made any INSERT of a new product fail with a NOT NULL
violation. Relax the constraint so product creation works with the current
model. Postgres still enforces uniqueness for non-null values.

Revision ID: 0004_make_products_sku_nullable
Revises: 0c11104244e9
Create Date: 2026-08-02 20:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004_make_products_sku_nullable"
down_revision: str | None = "0c11104244e9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "products",
        "sku",
        existing_type=sa.String(100),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "products",
        "sku",
        existing_type=sa.String(100),
        nullable=False,
    )
