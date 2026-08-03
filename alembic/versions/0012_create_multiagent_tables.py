"""Create the multi-agent tables.

Adds ``multiagent_runs`` (one row per supervised pipeline), ``multiagent_traces``
(per-agent reasoning steps, replayable) and ``multiagent_evaluations`` (per-agent
quality metrics). The run-id foreign keys cascade so deleting a run removes its
traces and evaluations.

Revision ID: 0012_multiagent
Revises: 0011_reverse_sourcing
Create Date: 2026-08-08 10:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0012_multiagent"
down_revision: str | None = "0011_reverse_sourcing"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "multiagent_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("task_type", sa.String(64), nullable=False, server_default="general"),
        sa.Column("status", sa.String(16), nullable=False, server_default="succeeded"),
        sa.Column("task_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("shared_memory_json", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Float(), nullable=False, server_default="0"),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
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
    op.create_index("ix_multiagent_runs_task_type", "multiagent_runs", ["task_type"])

    op.create_table(
        "multiagent_traces",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "run_id",
            sa.Uuid(),
            sa.ForeignKey("multiagent_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("agent_role", sa.String(64), nullable=False),
        sa.Column("step", sa.String(128), nullable=False, server_default=""),
        sa.Column("detail", sa.Text(), nullable=False, server_default=""),
        sa.Column("data_json", sa.Text(), nullable=True),
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
    op.create_index("ix_multiagent_traces_run_id", "multiagent_traces", ["run_id"])
    op.create_index("ix_multiagent_traces_agent_role", "multiagent_traces", ["agent_role"])

    op.create_table(
        "multiagent_evaluations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "run_id",
            sa.Uuid(),
            sa.ForeignKey("multiagent_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("agent_role", sa.String(64), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("latency_ms", sa.Float(), nullable=False, server_default="0"),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("completeness", sa.Float(), nullable=False, server_default="0"),
        sa.Column("tool_usage", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
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
    op.create_index("ix_multiagent_evaluations_run_id", "multiagent_evaluations", ["run_id"])
    op.create_index(
        "ix_multiagent_evaluations_agent_role", "multiagent_evaluations", ["agent_role"]
    )


def downgrade() -> None:
    op.drop_index("ix_multiagent_evaluations_agent_role", table_name="multiagent_evaluations")
    op.drop_index("ix_multiagent_evaluations_run_id", table_name="multiagent_evaluations")
    op.drop_table("multiagent_evaluations")
    op.drop_index("ix_multiagent_traces_agent_role", table_name="multiagent_traces")
    op.drop_index("ix_multiagent_traces_run_id", table_name="multiagent_traces")
    op.drop_table("multiagent_traces")
    op.drop_index("ix_multiagent_runs_task_type", table_name="multiagent_runs")
    op.drop_table("multiagent_runs")
