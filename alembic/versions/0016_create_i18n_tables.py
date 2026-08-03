"""Create the internationalization preference table.

Adds ``i18n_language_preferences`` — stores the language a user/device selected
so the choice persists across browsers, devices and sessions. Keyed by a unique
(user_id, device_id) pair; at least one key must be set.

Revision ID: 0016_i18n
Revises: 0015_learning
Create Date: 2026-08-12 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0016_i18n"
down_revision: str | None = "0015_learning"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "i18n_language_preferences",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("device_id", sa.String(128), nullable=True),
        sa.Column("language", sa.String(16), nullable=False),
        sa.Column("source", sa.String(16), nullable=False, server_default="manual"),
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
        sa.UniqueConstraint("user_id", "device_id", name="uq_i18n_pref_user_device"),
    )
    op.create_index(
        "ix_i18n_pref_user_id", "i18n_language_preferences", ["user_id"]
    )
    op.create_index(
        "ix_i18n_pref_device_id", "i18n_language_preferences", ["device_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_i18n_pref_device_id", table_name="i18n_language_preferences")
    op.drop_index("ix_i18n_pref_user_id", table_name="i18n_language_preferences")
    op.drop_table("i18n_language_preferences")
