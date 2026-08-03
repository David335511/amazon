"""Create the commerce knowledge graph tables.

Adds ``graph_nodes`` (every entity: products, brands, categories, suppliers,
marketplaces, customers, AI decisions, historical events, price changes,
inventory, seasonality — each uniquely keyed by node_type+key) and
``graph_edges`` (labelled, weighted relationships between nodes, unique per
source+target+type, cascading on node delete).

Revision ID: 0014_knowledge_graph
Revises: 0013_experiments
Create Date: 2026-08-10 10:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0014_knowledge_graph"
down_revision: str | None = "0013_experiments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "graph_nodes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("node_type", sa.String(32), nullable=False),
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("label", sa.String(255), nullable=False, server_default=""),
        sa.Column("attributes_json", sa.Text(), nullable=True),
        sa.Column("embedding_json", sa.Text(), nullable=True),
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
        sa.UniqueConstraint("node_type", "key", name="uq_graph_nodes_type_key"),
    )
    op.create_index("ix_graph_nodes_node_type", "graph_nodes", ["node_type"])
    op.create_index("ix_graph_nodes_key", "graph_nodes", ["key"])

    op.create_table(
        "graph_edges",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "source_id",
            sa.Uuid(),
            sa.ForeignKey("graph_nodes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "target_id",
            sa.Uuid(),
            sa.ForeignKey("graph_nodes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("edge_type", sa.String(32), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("attributes_json", sa.Text(), nullable=True),
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
        sa.UniqueConstraint("source_id", "target_id", "edge_type", name="uq_graph_edges_src_tgt_type"),
    )
    op.create_index("ix_graph_edges_source_id", "graph_edges", ["source_id"])
    op.create_index("ix_graph_edges_target_id", "graph_edges", ["target_id"])
    op.create_index("ix_graph_edges_edge_type", "graph_edges", ["edge_type"])


def downgrade() -> None:
    op.drop_index("ix_graph_edges_edge_type", table_name="graph_edges")
    op.drop_index("ix_graph_edges_target_id", table_name="graph_edges")
    op.drop_index("ix_graph_edges_source_id", table_name="graph_edges")
    op.drop_table("graph_edges")
    op.drop_index("ix_graph_nodes_key", table_name="graph_nodes")
    op.drop_index("ix_graph_nodes_node_type", table_name="graph_nodes")
    op.drop_table("graph_nodes")
