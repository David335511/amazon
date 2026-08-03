"""Create the experimentation tables.

Adds ``experiments`` (lifecycle + statistical config + reproducibility snapshot),
``experiment_variants`` (arms of an experiment), ``experiment_assignments``
(deterministic subject -> variant, unique per experiment+subject),
``experiment_observations`` (one outcome per subject, unique per
experiment+subject) and ``experiment_reports`` (every generated report with its
winner, confidence, impact and params snapshot). All child rows cascade on
experiment delete.

Revision ID: 0013_experiments
Revises: 0012_multiagent
Create Date: 2026-08-09 10:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0013_experiments"
down_revision: str | None = "0012_multiagent"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "experiments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("experiment_type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("hypothesis", sa.Text(), nullable=True),
        sa.Column("primary_metric", sa.String(16), nullable=False, server_default="conversion"),
        sa.Column("alpha", sa.Float(), nullable=False, server_default="0.05"),
        sa.Column("min_sample_size", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("seed", sa.Integer(), nullable=False, server_default="42"),
        sa.Column("control_variant_key", sa.String(64), nullable=True),
        sa.Column("config_snapshot_json", sa.Text(), nullable=True),
        sa.Column("code_version", sa.String(128), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True),
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
    op.create_index("ix_experiments_experiment_type", "experiments", ["experiment_type"])
    op.create_index("ix_experiments_status", "experiments", ["status"])
    op.create_index("ix_experiments_seed", "experiments", ["seed"])

    op.create_table(
        "experiment_variants",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "experiment_id",
            sa.Uuid(),
            sa.ForeignKey("experiments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("label", sa.String(255), nullable=False, server_default=""),
        sa.Column("parameters_json", sa.Text(), nullable=True),
        sa.Column("is_control", sa.Boolean(), nullable=False, server_default="false"),
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
    op.create_index("ix_experiment_variants_experiment_id", "experiment_variants", ["experiment_id"])

    op.create_table(
        "experiment_assignments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "experiment_id",
            sa.Uuid(),
            sa.ForeignKey("experiments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "variant_id",
            sa.Uuid(),
            sa.ForeignKey("experiment_variants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("subject_key", sa.String(255), nullable=False),
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
        sa.UniqueConstraint("experiment_id", "subject_key", name="uq_assignments_exp_subject"),
    )
    op.create_index("ix_experiment_assignments_experiment_id", "experiment_assignments", ["experiment_id"])
    op.create_index("ix_experiment_assignments_subject_key", "experiment_assignments", ["subject_key"])

    op.create_table(
        "experiment_observations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "experiment_id",
            sa.Uuid(),
            sa.ForeignKey("experiments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "variant_id",
            sa.Uuid(),
            sa.ForeignKey("experiment_variants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("subject_key", sa.String(255), nullable=False),
        sa.Column("outcome", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("profit", sa.Float(), nullable=True),
        sa.Column("roi", sa.Float(), nullable=True),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("predicted", sa.Boolean(), nullable=True),
        sa.Column("ground_truth", sa.Boolean(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.UniqueConstraint("experiment_id", "subject_key", name="uq_observations_exp_subject"),
    )
    op.create_index("ix_experiment_observations_experiment_id", "experiment_observations", ["experiment_id"])
    op.create_index("ix_experiment_observations_variant_id", "experiment_observations", ["variant_id"])
    op.create_index("ix_experiment_observations_subject_key", "experiment_observations", ["subject_key"])
    op.create_index("ix_experiment_observations_recorded_at", "experiment_observations", ["recorded_at"])

    op.create_table(
        "experiment_reports",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "experiment_id",
            sa.Uuid(),
            sa.ForeignKey("experiments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("winner_variant_key", sa.String(64), nullable=True),
        sa.Column("winner_label", sa.String(255), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("metric", sa.String(16), nullable=False),
        sa.Column("profit_impact", sa.Float(), nullable=True),
        sa.Column("roi_impact", sa.Float(), nullable=True),
        sa.Column("precision", sa.Float(), nullable=True),
        sa.Column("recall", sa.Float(), nullable=True),
        sa.Column("false_positives", sa.Integer(), nullable=True),
        sa.Column("false_negatives", sa.Integer(), nullable=True),
        sa.Column("report_body", sa.Text(), nullable=False, server_default=""),
        sa.Column("params_snapshot_json", sa.Text(), nullable=True),
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
    op.create_index("ix_experiment_reports_experiment_id", "experiment_reports", ["experiment_id"])


def downgrade() -> None:
    op.drop_index("ix_experiment_reports_experiment_id", table_name="experiment_reports")
    op.drop_table("experiment_reports")
    op.drop_index("ix_experiment_observations_recorded_at", table_name="experiment_observations")
    op.drop_index("ix_experiment_observations_subject_key", table_name="experiment_observations")
    op.drop_index("ix_experiment_observations_variant_id", table_name="experiment_observations")
    op.drop_index("ix_experiment_observations_experiment_id", table_name="experiment_observations")
    op.drop_table("experiment_observations")
    op.drop_index("ix_experiment_assignments_subject_key", table_name="experiment_assignments")
    op.drop_index("ix_experiment_assignments_experiment_id", table_name="experiment_assignments")
    op.drop_table("experiment_assignments")
    op.drop_index("ix_experiment_variants_experiment_id", table_name="experiment_variants")
    op.drop_table("experiment_variants")
    op.drop_index("ix_experiments_seed", table_name="experiments")
    op.drop_index("ix_experiments_status", table_name="experiments")
    op.drop_index("ix_experiments_experiment_type", table_name="experiments")
    op.drop_table("experiments")
