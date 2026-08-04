"""Unit tests for the retailers (Walmart / Home Depot) integration.

Tests use mocked HTTP responses to avoid hitting the real SerpApi.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from redis.asyncio import Redis

from app.integrations.retailers.budget import RetailerBudget
from app.integrations.retailers.client import (
    RetailerAuthenticationError,
    RetailerBudgetExceededError,
    RetailerCache,
    RetailerRateLimiter,
    RetailerRequestError,
    SerpApiClient,
)
from app.integrations.retailers.config import RetailerConfig
from app.integrations.retailers.models import (
    RetailerLookupRequest,
    RetailerProduct,
    RetailerProvider,
)
from app.integrations.retailers.providers import (
    HomeDepotProvider,
    WalmartProvider,
)
from app.integrations.retailers.scheduler import RetailerRefreshJob
from app.integrations.retailers.service import RetailerService

# ── Rate Limiter Tests ───────────────────────────────────────


class TestRetailerRateLimiter:
    @pytest.mark.asyncio
    async def test_allows_first_request(self) -> None:
        limiter = RetailerRateLimiter(requests_per_minute=60)
        await limiter.acquire()  # should not block

    @pytest.mark.asyncio
    async def test_enforces_minimum_interval(self) -> None:
        limiter = RetailerRateLimiter(requests_per_minute=120)  # 0.5s interval
        import time

        t1 = time.monotonic()
        await limiter.acquire()
        await limiter.acquire()
        t2 = time.monotonic()
        assert t2 - t1 >= 0.4


# ── Cache Tests ─────────────────────────────────────────────


class TestRetailerCache:
    @pytest.mark.asyncio
    async def test_miss_when_redis_unavailable(self) -> None:
        cache = RetailerCache(redis_client=None, default_ttl=300)
        result = await cache.get(engine="walmart_product", product_id="123")
        assert result is None

    @pytest.mark.asyncio
    async def test_set_and_get(self) -> None:
        mock_redis = AsyncMock(spec=Redis)
        mock_redis.get = AsyncMock(return_value=json.dumps({"price": 19.99}))
        mock_redis.setex = AsyncMock(return_value=True)

        cache = RetailerCache(redis_client=mock_redis, default_ttl=300)
        result = await cache.get(engine="walmart_product", product_id="123")
        assert result == {"price": 19.99}

    @pytest.mark.asyncio
    async def test_set_uses_ttl(self) -> None:
        mock_redis = AsyncMock(spec=Redis)
        mock_redis.setex.return_value = True

        cache = RetailerCache(redis_client=mock_redis, default_ttl=300)
        await cache.set({"price": 19.99}, ttl=600, engine="walmart_product")
        args, _ = mock_redis.setex.call_args
        assert args[1] == 600


# ── Client Tests ─────────────────────────────────────────────


class TestSerpApiClient:
    @pytest.fixture
    def config(self) -> RetailerConfig:
        return RetailerConfig(
            api_key="test-key",
            max_retries=1,
            retry_base_delay=0.01,
            retry_max_delay=0.1,
            requests_per_minute=120,
            cache_ttl_seconds=0,
            request_timeout=5,
        )

    @pytest.mark.asyncio
    async def test_requires_api_key(self) -> None:
        client = SerpApiClient(RetailerConfig(api_key=""))
        with pytest.raises(RetailerAuthenticationError, match="not configured"):
            await client.fetch_product(RetailerProvider.WALMART, "123")
        await client.close()

    @pytest.mark.asyncio
    async def test_fetch_product_returns_payload(self, config: RetailerConfig) -> None:
        client = SerpApiClient(config)
        payload = {"product_results": {"title": "Widget"}}

        with patch.object(client, "_request", new=AsyncMock(return_value=payload)):
            data = await client.fetch_product(RetailerProvider.WALMART, "123")
            assert data == payload

        await client.close()

    @pytest.mark.asyncio
    async def test_request_error_propagates(self, config: RetailerConfig) -> None:
        client = SerpApiClient(config)

        async def fail(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            raise RetailerRequestError("boom")

        with (
            patch.object(client, "_request", new=fail),
            pytest.raises(RetailerRequestError),
        ):
            await client.fetch_product(RetailerProvider.HOME_DEPOT, "123")
        await client.close()


# ── Provider Parsing Tests ───────────────────────────────────


class TestWalmartProvider:
    def test_parses_walmart_payload(self) -> None:
        raw: dict[str, Any] = {
            "product_results": {
                "title": "Blender",
                "price": 29.99,
                "rating": 4.4,
                "reviews": 120,
                "upc": "012345678905",
                "model_number": "B100",
                "store_sku_number": "SKU1",
                "link": "https://www.walmart.com/ip/123",
                "brand": {"name": "Acme"},
                "images": ["https://example.com/img.jpg"],
                "in_stock": True,
            },
        }
        product = WalmartProvider.parse(raw, "123")
        assert isinstance(product, RetailerProduct)
        assert product.provider == RetailerProvider.WALMART
        assert product.title == "Blender"
        assert product.price.current == Decimal("29.99")
        assert product.rating.rating == Decimal("4.4")
        assert product.rating.review_count == 120
        assert product.upc == "012345678905"
        assert product.brand == "Acme"
        assert product.in_stock is True

    def test_parses_price_dict_and_defaults(self) -> None:
        raw: dict[str, Any] = {
            "product_results": {
                "title": "Widget",
                "price": {"value": 9.99, "original": 19.99, "currency": "USD"},
            },
        }
        product = WalmartProvider.parse(raw, "x")
        assert product.price.current == Decimal("9.99")
        assert product.price.original == Decimal("19.99")
        assert product.price.is_on_sale is True
        assert product.price.savings == Decimal("10.00")
        assert product.rating.rating is None

    def test_parses_real_serpapi_walmart_shape(self) -> None:
        """Parse the ``product_result`` + ``price_map`` + ``offers`` shape that
        the live walmart_product engine actually returns."""
        raw: dict[str, Any] = {
            "product_result": {
                "title": "Community Coffee Ground 16 oz",
                "upc": "035700019403",
                "rating": 4.8,
                "reviews": 1320,
                "in_stock": True,
                "price_map": {
                    "unit_price": 0.656,
                    "price": 10.49,
                    "was_price": {"price": 11.74, "currencyUnit": "USD"},
                    "currency": "USD",
                },
                "offers": [
                    {"seller_name": "Walmart.com", "price": 10.49},
                    {"seller_name": "ThirdParty", "price": 11.0},
                ],
                "images": ["https://example.com/img.jpg"],
            },
        }
        product = WalmartProvider.parse(raw, "10291024")
        assert product.title == "Community Coffee Ground 16 oz"
        assert product.price.current == Decimal("10.49")
        assert product.price.original == Decimal("11.74")
        assert product.price.currency == "USD"
        assert product.price.is_on_sale is True
        assert product.rating.rating == Decimal("4.8")
        assert product.rating.review_count == 1320
        assert product.seller_count == 2
        assert product.in_stock is True

    def test_parses_singular_product_result(self) -> None:
        raw: dict[str, Any] = {"product_result": {"title": "Hammer", "price": "$12.50"}}
        product = HomeDepotProvider.parse(raw, "1")
        assert product.title == "Hammer"
        assert product.price.current == Decimal("12.50")


class TestHomeDepotProvider:
    def test_parses_home_depot_payload(self) -> None:
        raw: dict[str, Any] = {
            "product_results": {
                "title": "Drill",
                "price": 99.0,
                "rating": 4.8,
                "reviews": 15240,
                "upc": "088591234567",
                "model_number": "DCD771C2",
                "store_sku_number": "1010127831",
                "link": "https://www.homedepot.com/p/x/203202930",
                "brand": {"name": "DEWALT"},
                "images": [["https://example.com/a.jpg", "https://example.com/b.jpg"]],
                "availability_type": "Available",
            },
        }
        product = HomeDepotProvider.parse(raw, "203202930")
        assert product.provider == RetailerProvider.HOME_DEPOT
        assert product.title == "Drill"
        assert product.price.current == Decimal("99.00")
        assert product.rating.review_count == 15240
        assert product.model_number == "DCD771C2"
        assert product.image == "https://example.com/a.jpg"
        assert product.in_stock is True

    def test_out_of_stock_inference(self) -> None:
        raw: dict[str, Any] = {"product_results": {"availability_type": "Out of Stock"}}
        product = HomeDepotProvider.parse(raw, "1")
        assert product.in_stock is False

    def test_price_string_cleaning(self) -> None:
        raw: dict[str, Any] = {"product_results": {"price": "$1,299.00"}}
        product = HomeDepotProvider.parse(raw, "1")
        assert product.price.current == Decimal("1299.00")


# ── Service Tests ─────────────────────────────────────────────


class TestRetailerService:
    def _service(self, client: SerpApiClient) -> RetailerService:
        return RetailerService(client)

    @pytest.mark.asyncio
    async def test_fetch_product_routes_to_provider(self) -> None:
        client = AsyncMock(spec=SerpApiClient)
        raw = {"product_results": {"title": "Blender", "price": 25.0}}
        client.fetch_product = AsyncMock(return_value=raw)

        service = self._service(client)  # type: ignore[arg-type]
        product = await service.fetch_product(
            RetailerLookupRequest(product_id="123", provider=RetailerProvider.WALMART)
        )
        assert product.title == "Blender"
        assert product.price.current == Decimal("25.00")
        client.fetch_product.assert_awaited_once()

    def test_to_sourcing_data_retail_arbitrage(self) -> None:
        service = RetailerService(AsyncMock())
        product = RetailerProduct(
            provider=RetailerProvider.HOME_DEPOT,
            product_id="203202930",
            title="Drill",
            price={"current": "99.00"},
            seller_count=3,
            in_stock=True,
        )
        data = service.to_sourcing_data(
            product,
            amazon_price=Decimal("149.99"),
        )
        assert data["lowest_supplier_price"] == Decimal("99.00")
        assert data["amazon_price"] == Decimal("149.99")
        assert data["supplier_count"] == 3
        assert data["in_stock"] is True
        assert data["price_cv"] == Decimal("0")
        assert data["estimated_monthly_sales"] == 0
        # Selling above cost yields a positive profit/ROI.
        assert data["net_profit"] > 0
        assert data["roi_percentage"] > 0

    def test_score_runs_rules_with_profit(self) -> None:
        product = RetailerProduct(
            provider=RetailerProvider.WALMART,
            product_id="123",
            title="Widget",
            price={"current": "10.00"},
            seller_count=4,
        )
        service = RetailerService(AsyncMock())
        data = service.to_sourcing_data(product, amazon_price=Decimal("30.00"))
        score = service.score(data)

        # Cost=$10, sell=$30 → profitable. ROI/Profit rules pass; sales volume
        # is unknown (0/month) so the sales rule fails (major, not critical).
        assert len(score.rule_results) == 7
        assert score.total_score >= Decimal("0")
        assert score.critical_failures == 0
        assert data["net_profit"] > 0

    def test_build_helper_returns_service(self) -> None:
        from app.integrations.retailers.service import build_retailer_service

        service = build_retailer_service()
        assert isinstance(service, RetailerService)


# ── Budget Tests ──────────────────────────────────────────────


class TestRetailerBudget:
    @pytest.mark.asyncio
    async def test_acquire_respects_monthly_limit(self) -> None:
        budget = RetailerBudget(monthly_limit=5)
        for _ in range(5):
            assert await budget.try_acquire() is True
        assert await budget.try_acquire() is False
        assert await budget.used_this_month() == 5
        assert await budget.remaining() == 0

    @pytest.mark.asyncio
    async def test_release_returns_token(self) -> None:
        budget = RetailerBudget(monthly_limit=5)
        assert await budget.try_acquire() is True
        assert await budget.try_acquire() is True
        await budget.release()
        assert await budget.used_this_month() == 1
        assert await budget.try_acquire() is True

    @pytest.mark.asyncio
    async def test_daily_allowance_paces_remaining_budget(self) -> None:
        budget = RetailerBudget(monthly_limit=250)
        allowance = await budget.daily_allowance()
        # 250 / ~30 days remaining ≈ 8/day.
        assert 1 <= allowance <= 10
        assert allowance <= 250

    @pytest.mark.asyncio
    async def test_daily_allowance_zero_when_exhausted(self) -> None:
        budget = RetailerBudget(monthly_limit=1)
        assert await budget.try_acquire() is True
        assert await budget.daily_allowance() == 0

    @pytest.mark.asyncio
    async def test_release_does_not_go_negative(self) -> None:
        budget = RetailerBudget(monthly_limit=3)
        await budget.release()
        assert await budget.used_this_month() == 0


class TestClientBudgetEnforcement:
    @pytest.mark.asyncio
    async def test_raises_when_budget_exhausted(self) -> None:
        config = RetailerConfig(
            SERPAPI_API_KEY="test-key", SERPAPI_MONTHLY_BUDGET=1, SERPAPI_MAX_RETRIES=0
        )
        client = SerpApiClient(config=config)
        with (
            patch.object(client._budget, "try_acquire", new=AsyncMock(return_value=False)),
            pytest.raises(RetailerBudgetExceededError),
        ):
            await client._request({"engine": "walmart_product", "product_id": "1"})

    @pytest.mark.asyncio
    async def test_cache_hit_does_not_consume_budget(self) -> None:
        config = RetailerConfig(SERPAPI_API_KEY="test-key", SERPAPI_MONTHLY_BUDGET=1)
        client = SerpApiClient(config=config)
        payload = {"product_results": {"title": "Blender"}}
        with (
            patch.object(client._cache, "get", new=AsyncMock(return_value=payload)),
            patch.object(
                client._budget, "try_acquire", new=AsyncMock(return_value=True)
            ) as acquire,
        ):
            result = await client._request({"engine": "walmart_product", "product_id": "1"})
        assert result == payload
        acquire.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_release_token_on_failure(self) -> None:
        config = RetailerConfig(
            SERPAPI_API_KEY="test-key", SERPAPI_MONTHLY_BUDGET=5, SERPAPI_MAX_RETRIES=0
        )
        client = SerpApiClient(config=config)
        acquire = AsyncMock(return_value=True)
        release = AsyncMock()
        with (
            patch.object(client._budget, "try_acquire", new=acquire),
            patch.object(client._budget, "release", new=release),
            patch.object(
                client, "_request_uncached", new=AsyncMock(side_effect=RuntimeError("boom"))
            ),
            pytest.raises(RuntimeError),
        ):
            await client._request({"engine": "walmart_product", "product_id": "1"})
        acquire.assert_awaited_once()
        release.assert_awaited_once()


# ── Scheduler Tests ──────────────────────────────────────────


class TestRetailerRefreshJob:
    @pytest.mark.asyncio
    async def test_paces_to_daily_allowance(self) -> None:
        service = RetailerService(AsyncMock())
        service.fetch_product = AsyncMock()
        budget = RetailerBudget(monthly_limit=100)
        requests = [
            RetailerLookupRequest(product_id=f"p{i}", provider=RetailerProvider.WALMART)
            for i in range(20)
        ]

        job = RetailerRefreshJob(service=service, budget=budget)
        allowance = await budget.daily_allowance()
        assert 1 <= allowance <= 20
        refreshed = await job._refresh_cycle(requests)
        assert refreshed == allowance
        assert service.fetch_product.await_count == allowance

    @pytest.mark.asyncio
    async def test_refresh_single_honors_budget(self) -> None:
        service = RetailerService(AsyncMock())
        service.fetch_product = AsyncMock(side_effect=RetailerBudgetExceededError("full"))
        budget = RetailerBudget(monthly_limit=250)
        job = RetailerRefreshJob(service=service, budget=budget)
        ok = await job.refresh_single(
            RetailerLookupRequest(product_id="1", provider=RetailerProvider.WALMART)
        )
        assert ok is False
        service.fetch_product.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_refresh_single_success(self) -> None:
        service = RetailerService(AsyncMock())
        service.fetch_product = AsyncMock(
            return_value=RetailerProduct(
                provider=RetailerProvider.WALMART,
                product_id="1",
                title="T",
                price={"current": "5.00"},
            )
        )
        budget = RetailerBudget(monthly_limit=250)
        job = RetailerRefreshJob(service=service, budget=budget)
        ok = await job.refresh_single(
            RetailerLookupRequest(product_id="1", provider=RetailerProvider.WALMART)
        )
        assert ok is True


# ── Monitor-List Parsing Tests ───────────────────────────────


class TestParseMonitorProducts:
    def test_parses_valid_entries(self) -> None:
        from app.integrations.retailers.service import parse_monitor_products

        lookups = parse_monitor_products("walmart:10291024, home_depot:203202930")
        assert len(lookups) == 2
        assert lookups[0].provider == RetailerProvider.WALMART
        assert lookups[0].product_id == "10291024"
        assert lookups[1].provider == RetailerProvider.HOME_DEPOT
        assert lookups[1].product_id == "203202930"

    def test_empty_input(self) -> None:
        from app.integrations.retailers.service import parse_monitor_products

        assert parse_monitor_products("") == []
        assert parse_monitor_products(None) == []  # type: ignore[arg-type]

    def test_skips_unknown_provider_and_empty_entries(self) -> None:
        from app.integrations.retailers.service import parse_monitor_products

        lookups = parse_monitor_products("badprov:1, walmart:2, ")
        assert len(lookups) == 1
        assert lookups[0].provider == RetailerProvider.WALMART
        assert lookups[0].product_id == "2"


# ── Sourcing API Route Tests ─────────────────────────────────


class TestRetailerSourcingRoutes:
    @pytest.mark.asyncio
    async def test_lookup_returns_product_and_score(self) -> None:
        from app.api.v1.sourcing_retailers import (
            RetailerLookupRequestModel,
            lookup_retailer_product,
        )
        from app.sourcing.models import OpportunityScore

        service = AsyncMock()
        product = RetailerProduct(
            provider=RetailerProvider.WALMART,
            product_id="123",
            title="Blender",
            price={"current": "10.00"},
        )
        score = OpportunityScore(
            total_score=Decimal("70"),
            weighted_score=Decimal("0.70"),
            rule_results=[],
            critical_failures=0,
            is_viable=True,
        )
        service.fetch_and_score = AsyncMock(return_value=(product, score))

        body = RetailerLookupRequestModel(
            provider=RetailerProvider.WALMART,
            product_id="123",
            amazon_price=Decimal("30"),
        )
        resp = await lookup_retailer_product(body, service=service)
        assert resp.product.title == "Blender"
        assert resp.product.current_price == Decimal("10.00")
        assert resp.opportunity.is_viable is True
        service.fetch_and_score.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_lookup_429_when_budget_exhausted(self) -> None:
        from fastapi import HTTPException

        from app.api.v1.sourcing_retailers import (
            RetailerLookupRequestModel,
            lookup_retailer_product,
        )

        service = AsyncMock()
        service.fetch_and_score = AsyncMock(side_effect=RetailerBudgetExceededError("budget full"))
        body = RetailerLookupRequestModel(provider=RetailerProvider.WALMART, product_id="123")
        with pytest.raises(HTTPException) as exc:
            await lookup_retailer_product(body, service=service)
        assert exc.value.status_code == 429

    @pytest.mark.asyncio
    async def test_budget_status_not_configured(self) -> None:
        import app.api.v1.sourcing_retailers as mod

        with patch.object(mod, "get_shared_budget", return_value=None):
            result = await mod.get_budget_status()
        assert result["configured"] is False

    @pytest.mark.asyncio
    async def test_budget_status_configured(self) -> None:
        from types import SimpleNamespace

        import app.api.v1.sourcing_retailers as mod

        budget = SimpleNamespace(monthly_limit=250)
        budget.used_this_month = AsyncMock(return_value=10)
        budget.remaining = AsyncMock(return_value=240)
        budget.daily_allowance = AsyncMock(return_value=8)
        with patch.object(mod, "get_shared_budget", return_value=budget):
            result = await mod.get_budget_status()
        assert result["configured"] is True
        assert result["monthly_limit"] == 250
        assert result["used"] == 10
        assert result["remaining"] == 240
        assert result["daily_allowance"] == 8

    @pytest.mark.asyncio
    async def test_status_reports_scheduler(self) -> None:
        from types import SimpleNamespace

        import app.api.v1.sourcing_retailers as mod

        job = SimpleNamespace(_interval=21600)
        budget = SimpleNamespace(monthly_limit=250)
        with (
            patch.object(mod, "get_shared_job", return_value=job),
            patch.object(mod, "get_shared_budget", return_value=budget),
        ):
            result = await mod.get_status()
        assert result["scheduler_running"] is True
        assert result["monthly_budget"] == 250
        assert result["interval_seconds"] == 21600
