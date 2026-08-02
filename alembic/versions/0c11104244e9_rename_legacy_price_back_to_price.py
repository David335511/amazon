"""Rename legacy_price back to price

Revision ID: 0c11104244e9
Revises: 0003_create_historical_inventory
Create Date: 2026-08-01 13:38:45.809155
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0c11104244e9'
down_revision: Union[str, None] = '0003_create_historical_inventory'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Rename legacy_price back to price
    op.alter_column('products', 'legacy_price', new_column_name='price')


def downgrade() -> None:
    # Rename price back to legacy_price
    op.alter_column('products', 'price', new_column_name='legacy_price')
