"""Create the continuous-learning platform tables.

Adds ``learning_predictions`` (predicted vs actual profit / sales / ROI / risk
with model version and feature snapshot), ``learning_runs`` (versioned
continuous-learning cycles) and ``learning_recommendations`` (improvement
proposals: prompts, feature weights, matching algorithms, forecast models, rule
thresholds).

Revision ID: 0015_learning
Revises: 0014_knowledge_graph
Create Date: 2026-08-10 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0015_learning"
down_revision: str | None = "0014_knowledge_graph"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "learning_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("run_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="running"),
        sa.Column("params_snapshot_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("summary_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.UniqueConstraint("run_number", name="uq_learning_runs_run_number"),
    )

    op.create_table(
        "learning_predictions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("prediction_type", sa.String(16), nullable=False),
        sa.Column("subject_key", sa.String(128), nullable=False),
        sa.Column("decision_type", sa.String(24), nullable=False),
        sa.Column("decision_id", sa.String(128), nullable=True),
        sa.Column("model_version", sa.String(32), nullable=False, server_default="1.0.0"),
        sa.Column("predicted_value", sa.Float(), nullable=False),
        sa.Column("actual_value", sa.Float(), nullable=True),
        sa.Column("predicted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("features_json", sa.Text(), nullable=True),
        sa.Column("context_json", sa.Text(), nullable=True),
        sa.Column("external_id", sa.String(128), nullable=True),
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
        sa.UniqueConstraint("external_id", name="uq_learning_predictions_external_id"),
    )
    op.create_index("ix_learning_predictions_prediction_type", "learning_predictions", ["prediction_type"])
    op.create_index("ix_learning_predictions_subject_key", "learning_predictions", ["subject_key"])
    op.create_index("ix_learning_predictions_decision_type", "learning_predictions", ["decision_type"])
    op.create_index("ix_learning_predictions_decision_id", "learning_predictions", ["decision_id"])
    op.create_index("ix_learning_predictions_model_version", "learning_predictions", ["model_version"])

    op.create_table(
        "learning_recommendations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "run_id",
            sa.Uuid(),
            sa.ForeignKey("learning_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("target_type", sa.String(24), nullable=False),
        sa.Column("target_id", sa.String(128), nullable=True),
        sa.Column("issue_type", sa.String(24), nullable=False),
        sa.Column("severity", sa.Float(), nullable=False, server_default="0"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("current_value", sa.Float(), nullable=True),
        sa.Column("proposed_value", sa.Float(), nullable=True),
        sa.Column("proposed_action", sa.Text(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("evidence_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(16), nullable=False, server_default="open"),
        sa.Column("model_version", sa.String(32), nullable=True),
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
    op.create_index("ix_learning_recommendations_run_id", "learning_recommendations", ["run_id"])
    op.create_index("ix_learning_recommendations_target_type", "learning_recommendations", ["target_type"])
    op.create_index("ix_learning_recommendations_target_id", "learning_recommendations", ["target_id"])
    op.create_index("ix_learning_recommendations_status", "learning_recommendations", ["status"])


def downgrade() -> None:
    op.drop_index("ix_learning_recommendations_status", table_name="learning_recommendations")
    op.drop_index("ix_learning_recommendations_target_id", table_name="learning_recommendations")
    op.drop_index("ix_learning_recommendations_target_type", table_name="learning_recommendations")
    op.drop_index("ix_learning_recommendations_run_id", table_name="learning_recommendations")
    op.drop_table("learning_recommendations")
    op.drop_index("ix_learning_predictions_model_version", table_name="learning_predictions")
    op.drop_index("ix_learning_predictions_decision_id", table_name="learning_predictions")
    op.drop_index("ix_learning_predictions_decision_type", table_name="learning_predictions")
    op.drop_index("ix_learning_predictions_subject_key", table_name="learning_predictions")
    op.drop_index("ix_learning_predictions_prediction_type", table_name="learning_predictions")
    op.drop_table("learning_predictions")
    op.drop_index("uq_learning_runs_run_number", table_name="learning_runs")
    op.drop_table("learning_runs")
