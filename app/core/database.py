"""Core database engine and session management.

Design decisions:
- Async SQLAlchemy 2.x with asyncpg driver for non-blocking I/O.
- Session factory is created once at startup and injected via dependencies.
- Engine is configured from Settings (pool size, echo, etc.).
- A `get_db` async generator provides per-request sessions with auto-rollback on error.
"""

from __future__ import annotations

import ssl as ssl_module
from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy import make_url
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings


def _resolve_ssl(database_url: str) -> tuple[URL, Any]:
    """Resolve libpq ``sslmode`` from a URL into an asyncpg ``ssl`` argument.

    SQLAlchemy passes URL query params through to asyncpg as keywords, but
    asyncpg rejects ``sslmode`` (it expects ``ssl``). We consume ``sslmode``
    here and strip it from the URL so managed Postgres URLs (e.g. Neon)
    work unchanged: ``?sslmode=require`` -> ``ssl=True``, ``verify-*`` -> a
    verification SSLContext, ``disable``/absent -> no SSL.
    """
    url = make_url(database_url)
    query = dict(url.query)
    sslmode = query.pop("sslmode", None)
    if not sslmode or sslmode == "disable":
        return url, None
    if sslmode == "require":
        return url.set(query=query), True
    context = ssl_module.create_default_context()
    if sslmode != "verify-full":
        context.check_hostname = False
    context.verify_mode = ssl_module.CERT_REQUIRED
    return url.set(query=query), context


def create_engine() -> AsyncEngine:
    """Create the async SQLAlchemy engine from current settings."""
    url, ssl_arg = _resolve_ssl(settings.database.url)
    connect_args: dict[str, Any] = {
        "statement_cache_size": 0,  # Disable asyncpg statement cache
    }
    if ssl_arg is not None:
        connect_args["ssl"] = ssl_arg
    return create_async_engine(
        url,
        pool_size=settings.database.pool_size,
        max_overflow=settings.database.max_overflow,
        echo=settings.database.echo,
        pool_pre_ping=settings.database.pool_pre_ping,
        pool_recycle=settings.database.pool_recycle,
        connect_args=connect_args,
    )


# Global engine and session factory — initialized at app startup
engine: AsyncEngine | None = None
async_session_factory: async_sessionmaker[AsyncSession] | None = None


async def init_db() -> None:
    """Initialize the database engine and session factory.

    Called once during application startup.
    """
    global engine, async_session_factory
    engine = create_engine()
    async_session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


async def close_db() -> None:
    """Dispose of the database engine.

    Called once during application shutdown.
    """
    global engine, async_session_factory
    if engine is not None:
        await engine.dispose()
    engine = None
    async_session_factory = None


async def get_db() -> AsyncGenerator[AsyncSession, Any]:
    """FastAPI dependency that yields an async database session.

    Rolls back and closes the session on exception.
    """
    if async_session_factory is None:
        msg = "Database not initialized. Call init_db() first."
        raise RuntimeError(msg)

    session = async_session_factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
