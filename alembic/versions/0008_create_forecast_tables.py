"""Create the forecasting tables.

Adds ``forecasts`` (one row per stored forecast: point prediction, 95%
confidence interval, confidence, model + method + version, ensemble members,
explanation, and an input-series snapshot for reproducibility) and
``forecast_actuals`` (realized outcomes linked to a forecast, powering
historical-accuracy scoring: MAE / MAPE / RMSE / bias).

Revision ID: 0008_create_forecast_tables
Revises: 0007_create_feature_tables
Create Date: 2026-08-04 10:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008_create_forecast_tables"
down_revision: str | None = "0007_create_feature_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "forecasts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("target", sa.String(16), nullable=False),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("entity_id", sa.String(128), nullable=False),
        sa.Column("horizon", sa.Integer(), nullable=False),
        sa.Column("model_name", sa.String(48), nullable=False),
        sa.Column("method", sa.Text(), nullable=False),
        sa.Column("version", sa.String(32), nullable=False, server_default="1.0.0"),
        sa.Column("prediction", sa.Float(), nullable=False),
        sa.Column("lower", sa.Float(), nullable=False),
        sa.Column("upper", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("used_models_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("series_json", sa.Text(), nullable=False),
        sa.Column("features_json", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("frequency", sa.String(16), nullable=True),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=True),
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
    op.create_index("ix_forecasts_target", "forecasts", ["target"])
    op.create_index("ix_forecasts_entity_type", "forecasts", ["entity_type"])
    op.create_index("ix_forecasts_entity_id", "forecasts", ["entity_id"])
    op.create_index("ix_forecasts_model_name", "forecasts", ["model_name"])

    op.create_table(
        "forecast_actuals",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "forecast_id",
            sa.Uuid(),
            sa.ForeignKey("forecasts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("model_name", sa.String(48), nullable=False),
        sa.Column("target", sa.String(16), nullable=False),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("entity_id", sa.String(128), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actual_value", sa.Float(), nullable=False),
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
    op.create_index("ix_forecast_actuals_forecast_id", "forecast_actuals", ["forecast_id"])
    op.create_index("ix_forecast_actuals_model_name", "forecast_actuals", ["model_name"])
    op.create_index("ix_forecast_actuals_target", "forecast_actuals", ["target"])


def downgrade() -> None:
    op.drop_index("ix_forecast_actuals_target", table_name="forecast_actuals")
    op.drop_index("ix_forecast_actuals_model_name", table_name="forecast_actuals")
    op.drop_index("ix_forecast_actuals_forecast_id", table_name="forecast_actuals")
    op.drop_table("forecast_actuals")
    op.drop_index("ix_forecasts_model_name", table_name="forecasts")
    op.drop_index("ix_forecasts_entity_id", table_name="forecasts")
    op.drop_index("ix_forecasts_entity_type", table_name="forecasts")
    op.drop_index("ix_forecasts_target", table_name="forecasts")
    op.drop_table("forecasts")
