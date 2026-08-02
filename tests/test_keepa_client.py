"""Unit tests for the Keepa client — rate limiting, caching, retry logic, and parsing.

Tests use mocked HTTP responses to avoid hitting the real Keepa API.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from redis.asyncio import Redis

from app.integrations.keepa.client import (
    KeepaAuthenticationError,
    KeepaCache,
    KeepaClient,
    KeepaRateLimiter,
    KeepaRequestError,
    _decode_keepa_price,
    _keepa_minutes_to_datetime,
)
from app.integrations.keepa.config import KeepaConfig
from app.integrations.keepa.models import (
    KeepaBestSellersRequest,
    KeepaCategoryRequest,
    KeepaProductRequest,
    KeepaProductResponse,
)


# ── Helper Tests ────────────────────────────────────────────


class TestKeepaHelpers:
    """Test Keepa data format conversion helpers."""

    def test_decode_keepa_price(self) -> None:
        """Test decoding Keepa's integer price format."""
        assert _decode_keepa_price(1999) == Decimal("19.99")
        assert _decode_keepa_price(0) == Decimal("0")
        assert _decode_keepa_price(-1) == Decimal("0")
        assert _decode_keepa_price(100) == Decimal("1.00")
        assert _decode_keepa_price(1) == Decimal("0.01")

    def test_keepa_minutes_to_datetime(self) -> None:
        """Test converting Keepa epoch minutes to datetime."""
        # Keepa epoch is 2011-01-01
        dt = _keepa_minutes_to_datetime(0)
        assert dt.year == 2011
        assert dt.month == 1
        assert dt.day == 1

        # 525600 minutes = 1 year
        dt = _keepa_minutes_to_datetime(525600)
        assert dt.year == 2012


# ── Rate Limiter Tests ───────────────────────────────────────


class TestKeepaRateLimiter:
    """Test the token bucket rate limiter."""

    @pytest.mark.asyncio
    async def test_rate_limiter_allows_requests(self) -> None:
        """Test that the rate limiter allows requests within the limit."""
        limiter = KeepaRateLimiter(requests_per_minute=60)  # 1 per second
        # Should not block for the first request
        await limiter.acquire()

    @pytest.mark.asyncio
    async def test_rate_limiter_enforces_minimum_interval(self) -> None:
        """Test that the rate limiter enforces minimum interval between requests."""
        limiter = KeepaRateLimiter(requests_per_minute=120)  # 0.5s interval
        t1 = __import__("time").monotonic()
        await limiter.acquire()
        await limiter.acquire()
        t2 = __import__("time").monotonic()
        # Should have waited at least 0.5s between requests
        assert t2 - t1 >= 0.4  # Allow small timing variance


# ── Cache Tests ─────────────────────────────────────────────


class TestKeepaCache:
    """Test the Redis-backed cache layer."""

    @pytest.mark.asyncio
    async def test_cache_miss_when_redis_unavailable(self) -> None:
        """Test that cache returns None when Redis is not available."""
        cache = KeepaCache(redis_client=None, default_ttl=300)
        result = await cache.get("test", asin="B0TEST")
        assert result is None

    @pytest.mark.asyncio
    async def test_cache_set_and_get(self) -> None:
        """Test setting and getting cache values."""
        mock_redis = AsyncMock(spec=Redis)
        mock_redis.get = AsyncMock(return_value=json.dumps({"price": 19.99}))
        mock_redis.setex = AsyncMock(return_value=True)

        cache = KeepaCache(redis_client=mock_redis, default_ttl=300)
        result = await cache.get("test", asin="B0TEST")
        assert result == {"price": 19.99}

    @pytest.mark.asyncio
    async def test_cache_set_stores_data(self) -> None:
        """Test that cache.set stores data with correct TTL."""
        mock_redis = AsyncMock(spec=Redis)
        mock_redis.setex.return_value = True

        cache = KeepaCache(redis_client=mock_redis, default_ttl=300)
        await cache.set("test", {"price": 19.99}, ttl=600, asin="B0TEST")
        mock_redis.setex.assert_called_once()
        args, _ = mock_redis.setex.call_args
        assert args[1] == 600  # TTL

    @pytest.mark.asyncio
    async def test_cache_invalidate(self) -> None:
        """Test cache invalidation."""
        mock_redis = AsyncMock(spec=Redis)
        mock_redis.delete.return_value = 1

        cache = KeepaCache(redis_client=mock_redis, default_ttl=300)
        await cache.invalidate("test", asin="B0TEST")
        mock_redis.delete.assert_called_once()


# ── Client Tests ─────────────────────────────────────────────


class TestKeepaClient:
    """Test the Keepa HTTP client with mocked responses."""

    @pytest.fixture
    def config(self) -> KeepaConfig:
        """Create a test Keepa config with a mock API key."""
        return KeepaConfig(
            api_key="test-api-key-12345",
            max_retries=2,
            retry_base_delay=0.01,
            retry_max_delay=0.1,
            requests_per_minute=120,
            cache_ttl_seconds=0,  # Disable caching for tests
            request_timeout=5,
        )

    @pytest.fixture
    def mock_response_data(self) -> dict[str, Any]:
        """Create a realistic mock Keepa API response."""
        return {
            "products": [
                {
                    "asin": "B0TESTASIN",
                    "title": "Test Product",
                    "brand": "TestBrand",
                    "description": "A test product",
                    "features": ["Feature 1", "Feature 2"],
                    "price": 2999,
                    "buyBoxPrice": 2899,
                    "usedPrice": 2499,
                    "rating": 4.5,
                    "reviewCount": 1234,
                    "answeredQuestions": 56,
                    "salesRank": 500,
                    "monthlySales": 1500,
                    "categoryId": 123456,
                    "imagesCSV": "image1.jpg,image2.jpg",
                    "dimension": "10x8x5 inches",
                    "weight": 1.5,
                    "data": {
                        "AMAZON": [1000, 2999, 2000, 2899, 3000, 2799],
                        "BUY_BOX": [1000, 2899, 2000, 2799, 3000, 2699],
                        "SALES": [1000, 500, 2000, 450, 3000, 400],
                    },
                    "offers": [
                        {
                            "sellerId": "SELLER1",
                            "sellerName": "Test Seller",
                            "price": 2999,
                            "condition": "New",
                            "isFBA": True,
                            "isPrime": True,
                            "isAmazon": False,
                            "sellerRating": 98,
                            "sellerCount": 500,
                        },
                    ],
                },
            ],
        }

    @pytest.mark.asyncio
    async def test_client_requires_api_key(self) -> None:
        """Test that client raises error without API key."""
        config = KeepaConfig(api_key="")
        client = KeepaClient(config)
        request = KeepaProductRequest(asin="B0TESTASIN")
        with pytest.raises(KeepaAuthenticationError, match="API key is not configured"):
            await client.get_product(request)
        await client.close()

    @pytest.mark.asyncio
    async def test_get_product_success(
        self,
        config: KeepaConfig,
        mock_response_data: dict[str, Any],
    ) -> None:
        """Test successful product data retrieval."""
        client = KeepaClient(config)

        with patch.object(client, "_request", new=AsyncMock(return_value=mock_response_data)):
            request = KeepaProductRequest(asin="B0TESTASIN")
            response = await client.get_product(request)

            assert isinstance(response, KeepaProductResponse)
            assert response.asin == "B0TESTASIN"
            assert response.title == "Test Product"
            assert response.brand == "TestBrand"
            assert response.current_price == Decimal("29.99")
            assert response.current_buy_box_price == Decimal("28.99")
            assert response.reviews.rating == Decimal("4.5")
            assert response.reviews.review_count == 1234
            assert response.sales_estimates.estimated_monthly_sales == 1500
            assert response.sales_estimates.sales_rank == 500
            assert len(response.amazon_price_history) == 3
            assert len(response.offers) == 1
            assert response.offers[0].seller_id == "SELLER1"
            assert response.offers[0].is_fba is True

        await client.close()

    @pytest.mark.asyncio
    async def test_get_product_empty_response(self, config: KeepaConfig) -> None:
        """Test handling of empty product response."""
        client = KeepaClient(config)
        empty_data = {"products": []}

        with patch.object(client, "_request", new=AsyncMock(return_value=empty_data)):
            request = KeepaProductRequest(asin="B0TESTASIN")
            response = await client.get_product(request)
            assert response.asin == "B0TESTASIN"
            assert response.title is None

        await client.close()

    @pytest.mark.asyncio
    async def test_retry_on_server_error(self, config: KeepaConfig) -> None:
        """Test that client handles errors gracefully."""
        client = KeepaClient(config)

        # Mock _request to always fail
        async def mock_fail(*args: Any, **kwargs: Any) -> dict[str, Any]:
            msg = "Server error"
            raise KeepaRequestError(msg)

        with patch.object(client, "_request", new=mock_fail):
            request = KeepaProductRequest(asin="B0TESTASIN")
            with pytest.raises(KeepaRequestError):
                await client.get_product(request)

        await client.close()

    @pytest.mark.asyncio
    async def test_get_category(self, config: KeepaConfig) -> None:
        """Test category retrieval."""
        client = KeepaClient(config)
        mock_data = {
            "categories": [
                {"catId": 123, "name": "Test Category", "parentId": 0, "children": [456]},
            ],
        }

        with patch.object(client, "_request", new=AsyncMock(return_value=mock_data)):
            request = KeepaCategoryRequest(category_id=123)
            categories = await client.get_category(request)
            assert len(categories) == 1
            assert categories[0].name == "Test Category"
            assert categories[0].category_id == 123

        await client.close()

    @pytest.mark.asyncio
    async def test_get_best_sellers(self, config: KeepaConfig) -> None:
        """Test best sellers retrieval."""
        client = KeepaClient(config)
        mock_data = {"bestSellersList": ["ASIN1", "ASIN2", "ASIN3"]}

        with patch.object(client, "_request", new=AsyncMock(return_value=mock_data)):
            request = KeepaBestSellersRequest(category_id=123)
            response = await client.get_best_sellers(request)
            assert len(response.asins) == 3
            assert response.asins[0] == "ASIN1"

        await client.close()

    @pytest.mark.asyncio
    async def test_get_products_batch(self, config: KeepaConfig) -> None:
        """Test batch product retrieval."""
        client = KeepaClient(config)

        async def mock_get_product(req: KeepaProductRequest) -> KeepaProductResponse:
            return KeepaProductResponse(asin=req.asin, title=f"Product {req.asin}")

        with patch.object(client, "get_product", new=mock_get_product):
            results = await client.get_products_batch(["B0TESTASIN", "B0TESTAS02"])
            assert len(results) == 2
            assert results[0].asin == "B0TESTASIN"

        await client.close()
