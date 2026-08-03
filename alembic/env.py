"""Alembic environment configuration.

Loads the application's SQLAlchemy models and configures migration context
using the async database URL from settings.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig
from typing import Any

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import settings
from app.domain.models.base import Base

# Import all models so Alembic can detect them
import app.domain.models.product  # noqa: F401
import app.domain.models.order  # noqa: F401
import app.domain.models.brand  # noqa: F401
import app.domain.models.category  # noqa: F401
import app.domain.models.sourcing  # noqa: F401
import app.memory.models  # noqa: F401

# Alembic Config object
config = context.config

# Set up Python logging from alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Set target metadata for autogenerate
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    Configures the context with just a URL and not an Engine.
    Calls to context.execute() here emit the given SQL to the script output.
    """
    url = settings.database.url
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: object) -> None:
    """Run migrations with a connection."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in 'online' mode using the async engine."""
    from sqlalchemy.ext.asyncio import create_async_engine

    # Reuse the app's sslmode handling (asyncpg rejects ``sslmode``; it needs
    # ``ssl``) so managed Postgres URLs like Neon work during migrations.
    from app.core.database import _resolve_ssl

    url, ssl_arg = _resolve_ssl(settings.database.url)
    connect_args: dict[str, Any] = {}
    if ssl_arg is not None:
        connect_args["ssl"] = ssl_arg

    connectable = create_async_engine(
        url,
        poolclass=pool.NullPool,
        connect_args=connect_args,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    Uses the async engine from the application configuration.
    """
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
