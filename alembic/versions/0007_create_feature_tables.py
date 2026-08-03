"""Create the feature engineering tables.

Adds the ``feature_values`` table -- the feature store. One row per
(feature_key, entity_type, entity_id) holds the *current* computed value plus
its full audit trail (confidence, semantic version, computed_at, stale_after and
a JSON lineage record of the exact input signals and method that produced it).
Compute-once-and-reuse means a value is served until ``stale_after``; refresh
overwrites the row.

Revision ID: 0007_create_feature_tables
Revises: 0006_create_documents_tables
Create Date: 2026-08-03 10:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007_create_feature_tables"
down_revision: str | None = "0006_create_documents_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "feature_values",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("feature_key", sa.String(128), nullable=False),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("entity_id", sa.String(128), nullable=False),
        sa.Column("value_type", sa.String(16), nullable=False, server_default="numeric"),
        sa.Column("numeric_value", sa.Float(), nullable=True),
        sa.Column("value_json", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("version", sa.String(32), nullable=False, server_default="1.0.0"),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("stale_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lineage_json", sa.Text(), nullable=True),
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
        sa.UniqueConstraint(
            "feature_key",
            "entity_type",
            "entity_id",
            name="uq_feature_values_entity",
        ),
    )
    op.create_index("ix_feature_values_feature_key", "feature_values", ["feature_key"])
    op.create_index("ix_feature_values_entity_type", "feature_values", ["entity_type"])
    op.create_index("ix_feature_values_entity_id", "feature_values", ["entity_id"])


def downgrade() -> None:
    op.drop_index("ix_feature_values_entity_id", table_name="feature_values")
    op.drop_index("ix_feature_values_entity_type", table_name="feature_values")
    op.drop_index("ix_feature_values_feature_key", table_name="feature_values")
    op.drop_table("feature_values")
