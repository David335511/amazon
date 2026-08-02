"""Keepa API HTTP client with rate limiting, retry logic, and Redis caching.

Design decisions:
- **Rate limiting**: Uses a token bucket algorithm to stay within API limits.
  Tracks request timestamps and enforces minimum intervals.
- **Retry logic**: Exponential backoff with jitter for transient failures.
  Retries on 429 (rate limit), 5xx (server errors), and network timeouts.
- **Caching**: Redis-backed cache with configurable TTL. Cache keys include
  the ASIN and domain to avoid stale cross-domain data.
- **Async**: Uses httpx.AsyncClient for non-blocking HTTP requests.
- **Secure**: API key is never logged or exposed in error messages.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import random
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

import httpx
from redis.asyncio import Redis

from app.core.logging import get_logger
from app.integrations.keepa.config import KeepaConfig
from app.integrations.keepa.models import (
    KeepaBestSellersRequest,
    KeepaBestSellersResponse,
    KeepaCategory,
    KeepaCategoryRequest,
    KeepaOffer,
    KeepaPricePoint,
    KeepaProductRequest,
    KeepaProductResponse,
    KeepaReviewData,
    KeepaSalesEstimate,
    KeepaSellerInfo,
)

logger = get_logger(__name__)

# Keepa epoch: 2011-01-01 00:00:00 UTC in minutes
KEEPA_EPOCH_MINUTES = 1293840000 // 60  # 21564000


def _keepa_minutes_to_datetime(keepa_minutes: int) -> datetime:
    """Convert Keepa's epoch-minute format to a Python datetime.

    Keepa stores timestamps as minutes since 2011-01-01.
    """
    return datetime(2011, 1, 1, tzinfo=timezone.utc) + __import__("datetime").timedelta(
        minutes=int(keepa_minutes),
    )


def _decode_keepa_price(price_int: int) -> Decimal:
    """Decode Keepa's integer price format to Decimal.

    Keepa stores prices as integers: 1999 = $19.99
    Special values: -1 = no data, 0 = out of stock
    """
    if price_int <= 0:
        return Decimal("0")
    return Decimal(str(price_int)) / Decimal("100")


class KeepaRateLimiter:
    """Token bucket rate limiter for Keepa API requests.

    Ensures we never exceed the configured requests-per-minute limit.
    Uses a sliding window approach for accuracy.
    """

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
                logger.debug(
                    "Rate limit: waiting %.2fs before next request",
                    wait_time,
                )
                await asyncio.sleep(wait_time)
            self._last_request_time = time.monotonic()


class KeepaCache:
    """Redis-backed cache for Keepa API responses.

    Cache keys are SHA-256 hashes of the request parameters to avoid
    key length issues and ensure uniqueness.
    """

    def __init__(self, redis_client: Redis | None, default_ttl: int = 300) -> None:
        self._redis = redis_client
        self._default_ttl = default_ttl

    def _make_key(self, prefix: str, **params: Any) -> str:
        """Generate a deterministic cache key from parameters."""
        raw = json.dumps(params, sort_keys=True, default=str)
        hash_digest = hashlib.sha256(raw.encode()).hexdigest()[:16]
        return f"keepa:{prefix}:{hash_digest}"

    async def get(self, prefix: str, **params: Any) -> dict[str, Any] | None:
        """Get cached response. Returns None if not found or Redis unavailable."""
        if self._redis is None:
            return None
        try:
            key = self._make_key(prefix, **params)
            data = await self._redis.get(key)
            if data is not None:
                logger.debug("Cache HIT: %s", key)
                return json.loads(data)
            logger.debug("Cache MISS: %s", key)
            return None
        except Exception as exc:
            logger.warning("Cache get failed: %s", exc)
            return None

    async def set(
        self,
        prefix: str,
        data: dict[str, Any],
        ttl: int | None = None,
        **params: Any,
    ) -> None:
        """Store response in cache with TTL."""
        if self._redis is None:
            return
        try:
            key = self._make_key(prefix, **params)
            await self._redis.setex(key, ttl or self._default_ttl, json.dumps(data, default=str))
            logger.debug("Cache SET: %s (TTL=%ds)", key, ttl or self._default_ttl)
        except Exception as exc:
            logger.warning("Cache set failed: %s", exc)

    async def invalidate(self, prefix: str, **params: Any) -> None:
        """Invalidate a cached response."""
        if self._redis is None:
            return
        try:
            key = self._make_key(prefix, **params)
            await self._redis.delete(key)
            logger.debug("Cache INVALIDATED: %s", key)
        except Exception as exc:
            logger.warning("Cache invalidate failed: %s", exc)


class KeepaClient:
    """HTTP client for the Keepa Product Intelligence API.

    Features:
    - Automatic rate limiting (token bucket)
    - Exponential backoff retry with jitter
    - Redis response caching
    - Structured logging
    - Response parsing into Pydantic models
    """

    def __init__(
        self,
        config: KeepaConfig | None = None,
        redis_client: Redis | None = None,
    ) -> None:
        self._config = config or KeepaConfig()
        self._rate_limiter = KeepaRateLimiter(self._config.requests_per_minute)
        self._cache = KeepaCache(redis_client, self._config.cache_ttl_seconds)
        self._http_client: httpx.AsyncClient | None = None
        self._last_request_time: float = 0.0

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(self._config.request_timeout),
                headers={"Accept": "application/json"},
            )
        return self._http_client

    async def close(self) -> None:
        """Close the HTTP client and release resources."""
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    async def _request(
        self,
        endpoint: str,
        params: dict[str, Any],
        cache_prefix: str,
        cache_ttl: int | None = None,
    ) -> dict[str, Any]:
        """Make a rate-limited, cached, retryable request to the Keepa API.

        Args:
            endpoint: API endpoint path (e.g., 'product', 'category').
            params: Query parameters for the request.
            cache_prefix: Prefix for cache key generation.
            cache_ttl: Override cache TTL in seconds.

        Returns:
            Parsed JSON response as a dictionary.

        Raises:
            KeepaAuthenticationError: Invalid or missing API key.
            KeepaRateLimitError: Rate limit exceeded after retries.
            KeepaRequestError: Other request failures.
        """
        if not self._config.is_configured:
            msg = "Keepa API key is not configured. Set KEEPA_API_KEY environment variable."
            raise KeepaAuthenticationError(msg)

        # Check cache first
        cached = await self._cache.get(cache_prefix, **params)
        if cached is not None:
            return cached

        # Add API key to params
        params["key"] = self._config.api_key

        # Attempt request with retries
        last_exc: Exception | None = None
        url = f"{self._config.base_url}/{endpoint}"

        for attempt in range(self._config.max_retries + 1):
            try:
                # Rate limit
                await self._rate_limiter.acquire()

                client = await self._get_client()
                response = await client.get(url, params=params)

                # Handle HTTP errors
                if response.status_code == 401:
                    raise KeepaAuthenticationError("Invalid Keepa API key")
                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", "5"))
                    logger.warning(
                        "Rate limited (429). Retrying after %ds (attempt %d/%d)",
                        retry_after, attempt + 1, self._config.max_retries + 1,
                    )
                    await asyncio.sleep(retry_after)
                    continue
                if response.status_code >= 500:
                    if attempt < self._config.max_retries:
                        delay = self._get_retry_delay(attempt)
                        logger.warning(
                            "Server error %d. Retrying in %.1fs (attempt %d/%d)",
                            response.status_code, delay, attempt + 1,
                            self._config.max_retries + 1,
                        )
                        await asyncio.sleep(delay)
                        continue
                    raise KeepaRequestError(
                        f"Keepa API returned {response.status_code}: {response.text[:200]}",
                    )

                response.raise_for_status()
                data = response.json()

                # Cache the response
                await self._cache.set(cache_prefix, data, cache_ttl, **params)

                return data

            except httpx.TimeoutException as exc:
                last_exc = exc
                if attempt < self._config.max_retries:
                    delay = self._get_retry_delay(attempt)
                    logger.warning(
                        "Request timeout. Retrying in %.1fs (attempt %d/%d)",
                        delay, attempt + 1, self._config.max_retries + 1,
                    )
                    await asyncio.sleep(delay)
                else:
                    raise KeepaRequestError(
                        f"Request timed out after {self._config.max_retries + 1} attempts",
                    ) from exc

            except httpx.HTTPStatusError as exc:
                last_exc = exc
                if attempt < self._config.max_retries and exc.response.status_code >= 500:
                    delay = self._get_retry_delay(attempt)
                    await asyncio.sleep(delay)
                else:
                    raise KeepaRequestError(
                        f"HTTP error: {exc.response.status_code} - {exc.response.text[:200]}",
                    ) from exc

        raise KeepaRequestError(
            f"Request failed after {self._config.max_retries + 1} attempts",
        ) from last_exc

    def _get_retry_delay(self, attempt: int) -> float:
        """Calculate retry delay with exponential backoff and jitter."""
        delay = min(
            self._config.retry_base_delay * (2 ** attempt),
            self._config.retry_max_delay,
        )
        jitter = random.uniform(0, delay * 0.1)
        return delay + jitter

    # ── Public API Methods ──────────────────────────────────

    async def get_product(
        self,
        request: KeepaProductRequest,
        cache_ttl: int | None = None,
    ) -> KeepaProductResponse:
        """Retrieve product data from Keepa.

        Fetches price history, sales rank history, offers, reviews,
        images, dimensions, weight, and sales estimates for a single ASIN.

        Args:
            request: Product request parameters (ASIN, domain, options).
            cache_ttl: Override cache TTL in seconds.

        Returns:
            Parsed product data response.

        Raises:
            KeepaAuthenticationError: Invalid API key.
            KeepaRequestError: API request failed.
        """
        params: dict[str, Any] = {
            "asin": request.asin,
            "domain": request.domain,
            "offers": request.offers,
            "buybox": int(request.buybox),
            "rating": int(request.rating),
            "history": int(request.history),
        }

        data = await self._request("product", params, "product", cache_ttl)
        return self._parse_product_response(data, request.asin, request.domain)

    async def get_products_batch(
        self,
        asins: list[str],
        domain: str = "com",
        max_concurrent: int = 5,
    ) -> list[KeepaProductResponse]:
        """Retrieve product data for multiple ASINs concurrently.

        Respects rate limits by using a semaphore to limit concurrency.

        Args:
            asins: List of ASINs to fetch.
            domain: Amazon domain code.
            max_concurrent: Maximum concurrent requests.

        Returns:
            List of product responses (one per ASIN).
        """
        semaphore = asyncio.Semaphore(max_concurrent)

        async def fetch(asin: str) -> KeepaProductResponse:
            async with semaphore:
                req = KeepaProductRequest(asin=asin, domain=domain)
                return await self.get_product(req)

        tasks = [fetch(asin) for asin in asins]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        products: list[KeepaProductResponse] = []
        for asin, result in zip(asins, results, strict=False):
            if isinstance(result, Exception):
                logger.error("Failed to fetch ASIN %s: %s", asin, result)
            else:
                products.append(result)

        return products

    async def get_category(
        self,
        request: KeepaCategoryRequest,
    ) -> list[KeepaCategory]:
        """Retrieve Amazon category information.

        Args:
            request: Category request parameters.

        Returns:
            List of category objects.
        """
        params: dict[str, Any] = {
            "domain": request.domain,
        }
        if request.category_id is not None:
            params["category"] = request.category_id
        if request.parents:
            params["parents"] = 1
        if request.children:
            params["children"] = 1

        data = await self._request("category", params, "category")
        return self._parse_categories(data)

    async def get_best_sellers(
        self,
        request: KeepaBestSellersRequest,
    ) -> KeepaBestSellersResponse:
        """Retrieve best sellers list for a category.

        Args:
            request: Best sellers request parameters.

        Returns:
            Best sellers response with ranked ASIN list.
        """
        params: dict[str, Any] = {
            "category": request.category_id,
            "domain": request.domain,
        }

        data = await self._request("bestsellers", params, "bestsellers")
        return KeepaBestSellersResponse(
            category_id=request.category_id,
            asins=data.get("bestSellersList", []),
            domain=request.domain,
        )

    # ── Response Parsing ────────────────────────────────────

    def _parse_product_response(
        self,
        data: dict[str, Any],
        asin: str,
        domain: str,
    ) -> KeepaProductResponse:
        """Parse the raw Keepa product API response into our model.

        Keepa returns data in a compact format with parallel integer arrays
        for time-series data. This method decodes those arrays into
        human-readable KeepaPricePoint objects.
        """
        products_raw = data.get("products", [])
        if not products_raw:
            return KeepaProductResponse(asin=asin, domain=domain)

        product = products_raw[0]

        # Parse price histories from Keepa's compact format
        amazon_history = self._parse_price_array(
            product.get("data", {}).get("AMAZON"),
            product.get("data", {}).get("AMAZON_OFFERS"),
        )
        buy_box_history = self._parse_price_array(
            product.get("data", {}).get("BUY_BOX"),
        )
        used_history = self._parse_price_array(
            product.get("data", {}).get("USED"),
            product.get("data", {}).get("USED_OFFERS"),
        )
        sales_rank_ts = self._parse_price_array(
            product.get("data", {}).get("SALES"),
        )

        # Parse offers
        offers_raw = product.get("offers", [])
        offers = self._parse_offers(offers_raw)

        # Parse review data
        reviews = self._parse_reviews(product)

        # Parse sales estimates
        sales_estimates = self._parse_sales_estimates(product)

        # Parse category tree
        category_tree = self._parse_category_tree(product)

        # Parse images
        images = product.get("imagesCSV", "").split(",") if product.get("imagesCSV") else []
        images = [f"https://images-na.ssl-images-amazon.com/images/I/{img}" for img in images if img]

        # Parse dimensions and weight
        dimensions = product.get("dimension", "")
        weight = product.get("weight", None)
        weight_unit = "pounds" if weight else None

        return KeepaProductResponse(
            asin=asin,
            domain=domain,
            title=product.get("title"),
            brand=product.get("brand"),
            description=product.get("description"),
            features=product.get("features", []),
            upc=product.get("upc"),
            ean=product.get("ean"),
            model_number=product.get("modelNumber"),
            manufacturer=product.get("manufacturer"),
            category_id=product.get("categoryId"),
            category_tree=category_tree,
            images=images,
            main_image=images[0] if images else None,
            dimensions=dimensions or None,
            weight=Decimal(str(weight)) if weight else None,
            weight_unit=weight_unit,
            current_price=_decode_keepa_price(product.get("price", -1)),
            current_buy_box_price=_decode_keepa_price(product.get("buyBoxPrice", -1)),
            current_used_price=_decode_keepa_price(product.get("usedPrice", -1)),
            currency="USD",
            amazon_price_history=amazon_history,
            buy_box_price_history=buy_box_history,
            used_price_history=used_history,
            sales_rank_history=sales_rank_ts,
            offers=offers,
            offer_count=len(offers),
            fba_offer_count=sum(1 for o in offers if o.is_fba),
            sellers=self._parse_sellers(offers_raw),
            seller_count=len({o.seller_id for o in offers if o.seller_id}),
            reviews=reviews,
            sales_estimates=sales_estimates,
            raw_data=data,
        )

    def _parse_price_array(
        self,
        *arrays: list[int] | None,
    ) -> list[KeepaPricePoint]:
        """Parse Keepa's parallel integer arrays into price points.

        Keepa stores time-series as [t0, p0, t1, p1, ...] where
        t = epoch minutes, p = price * 100.
        """
        if not arrays or not arrays[0]:
            return []

        # The first array contains [time, price, time, price, ...]
        data = arrays[0]
        if len(data) < 2:
            return []

        points: list[KeepaPricePoint] = []
        for i in range(0, len(data) - 1, 2):
            timestamp = _keepa_minutes_to_datetime(data[i])
            price = _decode_keepa_price(data[i + 1])
            points.append(KeepaPricePoint(timestamp=timestamp, price=price))

        return points

    def _parse_offers(self, offers_raw: list[dict[str, Any]]) -> list[KeepaOffer]:
        """Parse offer data from Keepa response."""
        offers: list[KeepaOffer] = []
        for offer in offers_raw:
            try:
                offers.append(
                    KeepaOffer(
                        seller_id=offer.get("sellerId"),
                        price=_decode_keepa_price(offer.get("price", 0)),
                        condition=offer.get("condition", "New"),
                        is_fba=offer.get("isFBA", False),
                        is_prime=offer.get("isPrime", False),
                        delivery_days=offer.get("deliveryDays"),
                        seller_rating=Decimal(str(offer.get("sellerRating", 0))),
                        seller_count=offer.get("sellerCount", 0),
                        is_amazon=offer.get("isAmazon", False),
                    ),
                )
            except Exception as exc:
                logger.warning("Failed to parse offer: %s", exc)
        return offers

    def _parse_reviews(self, product: dict[str, Any]) -> KeepaReviewData:
        """Parse review data from Keepa response."""
        return KeepaReviewData(
            rating=Decimal(str(product.get("rating", 0))),
            review_count=product.get("reviewCount", 0),
            answered_questions=product.get("answeredQuestions", 0),
            rating_distribution={
                5: product.get("rating_5", 0),
                4: product.get("rating_4", 0),
                3: product.get("rating_3", 0),
                2: product.get("rating_2", 0),
                1: product.get("rating_1", 0),
            },
        )

    def _parse_sales_estimates(self, product: dict[str, Any]) -> KeepaSalesEstimate:
        """Parse sales estimate data from Keepa response."""
        monthly_sales = product.get("monthlySales", 0)
        return KeepaSalesEstimate(
            estimated_monthly_sales=monthly_sales,
            estimated_daily_sales=Decimal(str(monthly_sales / 30)) if monthly_sales else Decimal("0"),
            sales_rank=product.get("salesRank"),
            sales_rank_drops_30=product.get("salesRankDrops30"),
        )

    def _parse_category_tree(self, product: dict[str, Any]) -> list[KeepaCategory]:
        """Parse category tree from Keepa response."""
        tree = product.get("categoryTree", [])
        return [
            KeepaCategory(
                category_id=cat.get("catId", 0),
                name=cat.get("name", ""),
                parent_id=cat.get("parentId"),
            )
            for cat in tree
        ]

    def _parse_sellers(self, offers_raw: list[dict[str, Any]]) -> list[KeepaSellerInfo]:
        """Parse seller information from offers data."""
        seen: set[str] = set()
        sellers: list[KeepaSellerInfo] = []
        for offer in offers_raw:
            seller_id = offer.get("sellerId")
            if seller_id and seller_id not in seen:
                seen.add(seller_id)
                sellers.append(
                    KeepaSellerInfo(
                        seller_id=seller_id,
                        seller_name=offer.get("sellerName"),
                        seller_rating=Decimal(str(offer.get("sellerRating", 0))),
                        seller_count=offer.get("sellerCount", 0),
                        is_amazon=offer.get("isAmazon", False),
                        is_fba=offer.get("isFBA", False),
                        offers_count=1,
                    ),
                )
        return sellers

    def _parse_categories(self, data: dict[str, Any]) -> list[KeepaCategory]:
        """Parse category data from Keepa response."""
        categories_raw = data.get("categories", [])
        return [
            KeepaCategory(
                category_id=cat.get("catId", 0),
                name=cat.get("name", ""),
                parent_id=cat.get("parentId"),
                children=cat.get("children", []),
            )
            for cat in categories_raw
        ]


# ═══════════════════════════════════════════════════════════════
# Custom Exceptions
# ═══════════════════════════════════════════════════════════════


class KeepaError(Exception):
    """Base exception for Keepa API errors."""


class KeepaAuthenticationError(KeepaError):
    """Raised when the API key is invalid or missing."""


class KeepaRateLimitError(KeepaError):
    """Raised when rate limit is exceeded after retries."""


class KeepaRequestError(KeepaError):
    """Raised when a request fails after all retries."""
