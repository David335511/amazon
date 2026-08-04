"""SerpApi HTTP client for retailer product lookups.

Design decisions:
- Mirrors the Keepa integration's client shape: token-bucket rate limiting,
  exponential-backoff retry with jitter, and Redis response caching.
- SerpApi authenticates via an ``api_key`` query parameter and selects the
  target marketplace via an ``engine`` query parameter (walmart_product,
  home_depot_product, ...). The engine is chosen per provider.
- Cached responses are served within the configured TTL, so repeated lookups
  do not consume free-tier quota.
- Async: uses httpx.AsyncClient for non-blocking HTTP requests.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import random
import time
from typing import Any

import httpx
from redis.asyncio import Redis

from app.core.logging import get_logger
from app.integrations.retailers.budget import RetailerBudget
from app.integrations.retailers.config import RetailerConfig
from app.integrations.retailers.models import RetailerProvider

logger = get_logger(__name__)


class RetailerRateLimiter:
    """Token bucket rate limiter for retailer API requests."""

    def __init__(self, requests_per_minute: int) -> None:
        self._min_interval = 60.0 / max(requests_per_minute, 1)
        self._last_request_time: float = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Wait until a request slot is available."""
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_request_time
            if elapsed < self._min_interval:
                wait_time = self._min_interval - elapsed
                await asyncio.sleep(wait_time)
            self._last_request_time = time.monotonic()


class RetailerCache:
    """Redis-backed cache for retailer API responses."""

    def __init__(self, redis_client: Redis | None, default_ttl: int = 3600) -> None:
        self._redis = redis_client
        self._default_ttl = default_ttl

    def _make_key(self, **params: Any) -> str:
        raw = json.dumps(params, sort_keys=True, default=str)
        digest = hashlib.sha256(raw.encode()).hexdigest()[:16]
        return f"retailer:{digest}"

    async def get(self, **params: Any) -> dict[str, Any] | None:
        if self._redis is None:
            return None
        try:
            key = self._make_key(**params)
            data = await self._redis.get(key)
            if data is not None:
                return json.loads(data)
            return None
        except Exception as exc:
            logger.warning("Retailer cache get failed: %s", exc)
            return None

    async def set(self, data: dict[str, Any], ttl: int | None = None, **params: Any) -> None:
        if self._redis is None:
            return
        try:
            key = self._make_key(**params)
            await self._redis.setex(
                key,
                ttl or self._default_ttl,
                json.dumps(data, default=str),
            )
        except Exception as exc:
            logger.warning("Retailer cache set failed: %s", exc)


class SerpApiClient:
    """HTTP client for SerpApi retailer product lookups.

    Features:
    - Automatic rate limiting (token bucket)
    - Exponential backoff retry with jitter
    - Redis response caching (free-tier quota friendly)
    - Structured logging
    """

    def __init__(
        self,
        config: RetailerConfig | None = None,
        redis_client: Redis | None = None,
    ) -> None:
        self._config = config or RetailerConfig()
        self._rate_limiter = RetailerRateLimiter(self._config.requests_per_minute)
        self._cache = RetailerCache(redis_client, self._config.cache_ttl_seconds)
        self._budget = RetailerBudget(self._config.monthly_budget, redis_client)
        self._http_client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(self._config.request_timeout),
                headers={"Accept": "application/json"},
            )
        return self._http_client

    async def close(self) -> None:
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    async def _request(
        self, params: dict[str, Any], cache_ttl: int | None = None
    ) -> dict[str, Any]:
        """Make a rate-limited, cached, retryable request to SerpApi.

        Args:
            params: Query parameters (engine + provider-specific fields).
            cache_ttl: Override cache TTL in seconds.

        Returns:
            Parsed JSON response as a dictionary.

        Raises:
            RetailerAuthenticationError: Invalid or missing API key.
            RetailerRateLimitError: Rate limit exceeded after retries.
            RetailerRequestError: Other request failures.
        """
        if not self._config.is_configured:
            msg = "SerpApi key is not configured. Set SERPAPI_API_KEY environment variable."
            raise RetailerAuthenticationError(msg)

        # Cache check (do not include the api key in the cache key)
        cache_params = {k: v for k, v in params.items() if k != "api_key"}
        cached = await self._cache.get(**cache_params)
        if cached is not None:
            return cached

        # Reserve a search against the monthly budget. Only network calls (i.e.
        # cache misses) count toward the budget; a successful response consumes
        # the token, while a failure returns it via release().
        if not await self._budget.try_acquire():
            raise RetailerBudgetExceededError(
                "Monthly retailer search budget exhausted "
                f"({self._config.monthly_budget}/month). "
                "Set SERPAPI_MONTHLY_BUDGET higher or wait for next month.",
            )

        try:
            return await self._request_uncached(params, cache_ttl)
        except Exception:
            # Request did not consume a search on SerpApi's side (auth/network/
            # rate-limit failure), so return the token to the budget.
            await self._budget.release()
            raise

    async def _request_uncached(
        self, params: dict[str, Any], cache_ttl: int | None = None
    ) -> dict[str, Any]:
        """Perform the actual (non-cached) SerpApi request with retries."""
        # Add api key to query params
        params["api_key"] = self._config.api_key
        cache_params = {k: v for k, v in params.items() if k != "api_key"}

        last_exc: Exception | None = None
        for attempt in range(self._config.max_retries + 1):
            try:
                await self._rate_limiter.acquire()
                client = await self._get_client()
                response = await client.get(self._config.base_url, params=params)

                if response.status_code == 401:
                    raise RetailerAuthenticationError("Invalid SerpApi key")
                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", "3"))
                    await asyncio.sleep(retry_after)
                    continue
                if response.status_code >= 500:
                    if attempt < self._config.max_retries:
                        await asyncio.sleep(self._get_retry_delay(attempt))
                        continue
                    raise RetailerRequestError(
                        f"SerpApi returned {response.status_code}: {response.text[:200]}",
                    )

                response.raise_for_status()
                data = response.json()

                # A successful response may still carry a SerpApi error block.
                if isinstance(data, dict) and data.get("error"):
                    raise RetailerRequestError(f"SerpApi error: {data['error']}")

                await self._cache.set(data, cache_ttl, **cache_params)
                return data

            except httpx.TimeoutException as exc:
                last_exc = exc
                if attempt < self._config.max_retries:
                    await asyncio.sleep(self._get_retry_delay(attempt))
                else:
                    raise RetailerRequestError(
                        f"Request timed out after {self._config.max_retries + 1} attempts",
                    ) from exc

            except httpx.HTTPStatusError as exc:
                last_exc = exc
                if attempt < self._config.max_retries and exc.response.status_code >= 500:
                    await asyncio.sleep(self._get_retry_delay(attempt))
                else:
                    raise RetailerRequestError(
                        f"HTTP error: {exc.response.status_code} - {exc.response.text[:200]}",
                    ) from exc

        raise RetailerRequestError(
            f"Request failed after {self._config.max_retries + 1} attempts",
        ) from last_exc

    def _get_retry_delay(self, attempt: int) -> float:
        delay = min(
            self._config.retry_base_delay * (2**attempt),
            self._config.retry_max_delay,
        )
        return delay + random.uniform(0, delay * 0.1)

    # ── Public API Methods ──────────────────────────────────

    async def fetch_product(
        self,
        provider: RetailerProvider,
        product_id: str,
        *,
        country: str = "us",
        delivery_zip: str | None = None,
        store_id: str | None = None,
        cache_ttl: int | None = None,
    ) -> dict[str, Any]:
        """Fetch the raw retailer product payload from SerpApi.

        Args:
            provider: Retailer to query (selects the SerpApi engine).
            product_id: Retailer item number / product id.
            country: Marketplace country code.
            delivery_zip: Optional zip for store-localized results.
            store_id: Optional retailer store id.
            cache_ttl: Override cache TTL in seconds.

        Returns:
            Raw SerpApi response dictionary.
        """
        params: dict[str, Any] = {
            "engine": provider.serp_engine,
            "product_id": product_id,
            "country": country,
        }
        if delivery_zip:
            params["delivery_zip"] = delivery_zip
        if store_id:
            params["store_id"] = store_id

        return await self._request(params, cache_ttl)


# ═══════════════════════════════════════════════════════════════
# Custom Exceptions
# ═══════════════════════════════════════════════════════════════


class RetailerError(Exception):
    """Base exception for retailer API errors."""


class RetailerAuthenticationError(RetailerError):
    """Raised when the API key is invalid or missing."""


class RetailerRateLimitError(RetailerError):
    """Raised when the rate limit is exceeded after retries."""


class RetailerBudgetExceededError(RetailerError):
    """Raised when the monthly retailer search budget is exhausted."""


class RetailerRequestError(RetailerError):
    """Raised when a request fails after all retries."""
