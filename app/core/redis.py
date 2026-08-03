"""Redis connection management.

Design decisions:
- Uses redis.asyncio for non-blocking operations.
- Connection pool is created once at startup.
- Health check pings Redis to verify connectivity.
- A `get_redis` dependency provides the client to route handlers.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from redis.asyncio import ConnectionPool, Redis

from app.config import settings

# Global Redis client — initialized at app startup
redis_client: Redis | None = None
redis_pool: ConnectionPool | None = None


async def init_redis() -> None:
    """Initialize the Redis connection pool and client.

    Called once during application startup.
    """
    global redis_client, redis_pool
    redis_pool = ConnectionPool.from_url(
        settings.redis.url,
        socket_connect_timeout=settings.redis.socket_connect_timeout,
        socket_timeout=settings.redis.socket_timeout,
        retry_on_timeout=settings.redis.retry_on_timeout,
        health_check_interval=settings.redis.health_check_interval,
        socket_keepalive=settings.redis.socket_keepalive,
        decode_responses=True,
        protocol=2,
    )
    redis_client = Redis.from_pool(redis_pool)


async def close_redis() -> None:
    """Close the Redis connection pool.

    Called once during application shutdown.
    """
    global redis_client, redis_pool
    if redis_client is not None:
        await redis_client.aclose()
    if redis_pool is not None:
        await redis_pool.disconnect()
    redis_client = None
    redis_pool = None


async def get_redis() -> AsyncGenerator[Redis, Any]:
    """FastAPI dependency that yields the Redis client."""
    if redis_client is None:
        msg = "Redis not initialized. Call init_redis() first."
        raise RuntimeError(msg)
    yield redis_client


async def check_redis_health() -> bool:
    """Ping Redis to verify connectivity.

    Returns True if Redis responds, False otherwise.
    """
    if redis_client is None:
        return False
    try:
        return await redis_client.ping()
    except Exception:
        return False
