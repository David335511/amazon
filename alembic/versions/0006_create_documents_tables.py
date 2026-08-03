"""Create the document intelligence tables.

Adds the ``documents`` table -- the document system's own storage, fully
separate from product/order data. Each row holds BOTH the raw document bytes
(``raw_blob``) and the parsed representation (``text`` + ``extracted_json`` +
``metadata_json``), so a document is self-contained and reproducible.
``sha256`` enables idempotent ingestion. ``extracted_json`` / ``metadata_json``
are JSON text so the schema needs no JSON/vector extension.

Revision ID: 0006_create_documents_tables
Revises: 0005_create_memory_tables
Create Date: 2026-08-03 09:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006_create_documents_tables"
down_revision: str | None = "0005_create_memory_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.String(128), nullable=True),
        sa.Column("doc_type", sa.String(32), nullable=False, server_default="other"),
        sa.Column("file_format", sa.String(16), nullable=False),
        sa.Column("filename", sa.String(500), nullable=True),
        sa.Column("raw_mime", sa.String(128), nullable=True),
        sa.Column("raw_size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("raw_blob", sa.LargeBinary(), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("extracted_json", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("pages", sa.Integer(), nullable=True),
        sa.Column("ocr_used", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
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
    op.create_index("ix_documents_user_id", "documents", ["user_id"])
    op.create_index("ix_documents_doc_type", "documents", ["doc_type"])
    op.create_index("ix_documents_file_format", "documents", ["file_format"])
    op.create_index("ix_documents_sha256", "documents", ["sha256"])


def downgrade() -> None:
    op.drop_index("ix_documents_sha256", table_name="documents")
    op.drop_index("ix_documents_file_format", table_name="documents")
    op.drop_index("ix_documents_doc_type", table_name="documents")
    op.drop_index("ix_documents_user_id", table_name="documents")
    op.drop_table("documents")
