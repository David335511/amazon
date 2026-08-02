"""TranslationCache — Redis-backed cache for translations.

Design decisions:
- Redis cache for production use with configurable TTL.
- Falls back to in-memory dict if Redis is unavailable.
- Cache keys include language and module for granular invalidation.
- Supports preloading all modules for a language at startup.
"""

from __future__ import annotations

import json
from typing import Any

from redis.asyncio import Redis

from app.core.logging import get_logger

logger = get_logger(__name__)

CACHE_PREFIX = "i18n"
DEFAULT_TTL = 3600  # 1 hour


class TranslationCache:
    """Redis-backed cache for translation data.

    Usage:
        cache = TranslationCache(redis_client)
        await cache.set('en', 'dashboard', data)
        data = await cache.get('en', 'dashboard')
    """

    def __init__(self, redis: Redis | None = None, default_ttl: int = DEFAULT_TTL) -> None:
        self._redis = redis
        self._default_ttl = default_ttl
        self._local: dict[str, dict[str, Any]] = {}  # Fallback when Redis is unavailable

    def _make_key(self, language: str, module: str) -> str:
        return f"{CACHE_PREFIX}:{language}:{module}"

    async def get(self, language: str, module: str) -> dict[str, Any] | None:
        """Get cached translations."""
        if self._redis is not None:
            try:
                data = await self._redis.get(self._make_key(language, module))
                if data:
                    return json.loads(data)
            except Exception as exc:
                logger.warning("Redis cache get failed: %s", exc)

        # Fallback to local cache
        return self._local.get(language, {}).get(module)

    async def set(
        self,
        language: str,
        module: str,
        data: dict[str, Any],
        ttl: int | None = None,
    ) -> None:
        """Cache translations."""
        if self._redis is not None:
            try:
                await self._redis.setex(
                    self._make_key(language, module),
                    ttl or self._default_ttl,
                    json.dumps(data, ensure_ascii=False),
                )
            except Exception as exc:
                logger.warning("Redis cache set failed: %s", exc)

        # Local fallback
        if language not in self._local:
            self._local[language] = {}
        self._local[language][module] = data

    async def invalidate(self, language: str | None = None, module: str | None = None) -> None:
        """Invalidate cached translations."""
        if self._redis is not None:
            try:
                if language and module:
                    await self._redis.delete(self._make_key(language, module))
                elif language:
                    # Scan and delete all keys for this language
                    cursor = 0
                    pattern = f"{CACHE_PREFIX}:{language}:*"
                    while True:
                        cursor, keys = await self._redis.scan(
                            cursor=cursor, match=pattern, count=100,
                        )
                        if keys:
                            await self._redis.delete(*keys)
                        if cursor == 0:
                            break
                else:
                    # Clear all i18n cache
                    cursor = 0
                    while True:
                        cursor, keys = await self._redis.scan(
                            cursor=cursor, match=f"{CACHE_PREFIX}:*", count=100,
                        )
                        if keys:
                            await self._redis.delete(*keys)
                        if cursor == 0:
                            break
            except Exception as exc:
                logger.warning("Redis cache invalidate failed: %s", exc)

        # Clear local cache
        if language:
            self._local.pop(language, None)
        else:
            self._local.clear()
