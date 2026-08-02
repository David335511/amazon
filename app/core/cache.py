"""Caching utilities for API responses.

Design decisions:
- Generic cache-aside pattern with async Redis support.
- Automatic serialization/deserialization of Pydantic models.
- Configurable TTL per cache namespace.
- Graceful degradation when Redis is unavailable.
- Cache key generation from request parameters.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Any, TypeVar

from pydantic import BaseModel
from redis.asyncio import Redis

from app.core.logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T", bound=BaseModel)


class ResponseCache:
    """Redis-backed cache for API responses with Pydantic serialization."""

    def __init__(self, redis_client: Redis | None, default_ttl: int = 300) -> None:
        self._redis = redis_client
        self._default_ttl = default_ttl

    def _make_key(self, namespace: str, **params: Any) -> str:
        """Generate a deterministic cache key from parameters."""
        raw = json.dumps(params, sort_keys=True, default=str)
        hash_digest = hashlib.sha256(raw.encode()).hexdigest()[:16]
        return f"api:{namespace}:{hash_digest}"

    async def get(
        self,
        namespace: str,
        response_model: type[T],
        **params: Any,
    ) -> T | None:
        """Get a cached response and deserialize it into a Pydantic model.

        Args:
            namespace: Cache namespace (e.g., 'product_detail', 'pricing').
            response_model: Pydantic model class for deserialization.
            **params: Parameters for cache key generation.

        Returns:
            Deserialized response model, or None if cache miss.
        """
        if self._redis is None:
            return None
        try:
            key = self._make_key(namespace, **params)
            data = await self._redis.get(key)
            if data is not None:
                parsed = json.loads(data)
                logger.debug("Cache HIT: %s", key)
                return response_model.model_validate(parsed)
            logger.debug("Cache MISS: %s", key)
            return None
        except Exception as exc:
            logger.warning("Cache get failed: %s", exc)
            return None

    async def set(
        self,
        namespace: str,
        data: BaseModel,
        ttl: int | None = None,
        **params: Any,
    ) -> None:
        """Cache a response with TTL.

        Args:
            namespace: Cache namespace.
            data: Pydantic model to cache (serialized to JSON).
            ttl: Override TTL in seconds.
            **params: Parameters for cache key generation.
        """
        if self._redis is None:
            return
        try:
            key = self._make_key(namespace, **params)
            serialized = data.model_dump_json()
            await self._redis.setex(key, ttl or self._default_ttl, serialized)
            logger.debug("Cache SET: %s (TTL=%ds)", key, ttl or self._default_ttl)
        except Exception as exc:
            logger.warning("Cache set failed: %s", exc)

    async def invalidate(self, namespace: str, **params: Any) -> None:
        """Invalidate a cached response.

        Args:
            namespace: Cache namespace.
            **params: Parameters for cache key generation.
        """
        if self._redis is None:
            return
        try:
            key = self._make_key(namespace, **params)
            await self._redis.delete(key)
            logger.debug("Cache INVALIDATED: %s", key)
        except Exception as exc:
            logger.warning("Cache invalidate failed: %s", exc)

    async def invalidate_namespace(self, namespace: str) -> None:
        """Invalidate all cache entries in a namespace.

        Uses Redis SCAN to find matching keys.

        Args:
            namespace: Cache namespace to clear.
        """
        if self._redis is None:
            return
        try:
            cursor = 0
            pattern = f"api:{namespace}:*"
            while True:
                cursor, keys = await self._redis.scan(cursor=cursor, match=pattern, count=100)
                if keys:
                    await self._redis.delete(*keys)
                if cursor == 0:
                    break
            logger.debug("Cache namespace INVALIDATED: %s (%d keys)", namespace, len(keys))
        except Exception as exc:
            logger.warning("Cache namespace invalidate failed: %s", exc)


def cache_response(
    namespace: str,
    ttl: int | None = None,
) -> Callable[..., Any]:
    """Decorator that caches the return value of an async function.

    The decorated function must return a Pydantic BaseModel.
    Cache keys are derived from the function name and arguments.

    Args:
        namespace: Cache namespace.
        ttl: Cache TTL in seconds.

    Returns:
        Decorated function with caching.
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        async def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
            cache: ResponseCache | None = getattr(self, "_cache", None)
            if cache is None:
                return await func(self, *args, **kwargs)

            # Build cache params from function arguments
            cache_params: dict[str, Any] = {}
            if args:
                cache_params["args"] = [str(a) for a in args]
            if kwargs:
                cache_params.update({k: str(v) for k, v in kwargs.items()})

            # Try cache
            result = await cache.get(namespace, Any, **cache_params)  # type: ignore[type-var]
            if result is not None:
                return result

            # Execute and cache
            result = await func(self, *args, **kwargs)
            if isinstance(result, BaseModel):
                await cache.set(namespace, result, ttl=ttl, **cache_params)
            return result

        return wrapper

    return decorator
