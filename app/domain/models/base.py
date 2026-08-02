"""SQLAlchemy declarative base and common mixins.

Design decisions:
- Uses SQLAlchemy 2.x declarative base with Mapped annotations.
- A `TimestampMixin` provides created_at / updated_at for all models.
- A `SoftDeleteMixin` adds deleted_at for non-destructive deletion.
- An `AuditMixin` adds created_by / updated_by for change tracking.
- A `Base` class with a common `__tablename__` convention.
- UUID primary keys for distributed-friendly IDs.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Abstract base class for all ORM models."""

    __abstract__ = True


class UUIDMixin:
    """Mixin that adds a UUID primary key."""

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        sort_order=-1,
    )


class TimestampMixin:
    """Mixin that adds created_at and updated_at timestamp columns."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class SoftDeleteMixin:
    """Mixin that adds deleted_at for soft deletion.

    Queries should filter `deleted_at.is_(None)` to exclude soft-deleted rows.
    """

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )


class AuditMixin:
    """Mixin that adds audit fields for change tracking."""

    created_by: Mapped[uuid.UUID | None] = mapped_column(
        nullable=True,
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        nullable=True,
    )
