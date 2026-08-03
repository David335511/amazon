"""Benchmark tests for the reverse sourcing engine.

Covers the pure ranking/highlight/recommendation math, the manager + engine
(persisting runs and accumulating historical per-(supplier, ASIN) series), the
plug-in-friendly provider seam (adding a supplier requires no engine change),
and the HTTP API.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_reverse_sourcing_manager
from app.plugins.models import (
    SupplierAvailability,
    SupplierCoupon,
    SupplierPricing,
    SupplierProductSearchResult,
    SupplierShipping,
)
from app.reverse_sourcing import (
    PassthroughAsinResolver,
    ReverseSourcingConfig,
    ReverseSourcingManager,
    ReverseSourcingRepository,
    ReverseSourcingRequest,
    TrendDiscountPredictor,
)
from app.reverse_sourcing.offer import Offer
from app.reverse_sourcing.provider import SupplierProvider
from app.reverse_sourcing.scoring import (
    build_summary,
    highlights,
    rank_offers,
    recommendations,
)

CFG = ReverseSourcingConfig()


# ──────────────────────────────────────────────────────────────
# Fake supplier provider (stands in for the PluginManager seam)
# ──────────────────────────────────────────────────────────────


class FakeProvider(SupplierProvider):
    """A canned supplier provider: adding a supplier is just adding a dict."""

    def __init__(self) -> None:
        self._suppliers: dict[str, dict] = {
            "walmart": {"sku": "WM1", "price": "10.00", "ship_cost": 5.99, "days": 5, "in_stock": True, "discount": "10"},
            "target": {"sku": "TG1", "price": "12.00", "ship_cost": 4.99, "days": 3, "in_stock": True, "discount": None},
            "costco": {"sku": "CS1", "price": "7.00", "ship_cost": 7.99, "days": 7, "in_stock": True, "discount": "5"},
        }

    def add_supplier(self, code: str, data: dict) -> None:
        self._suppliers[code] = data

    def enabled_suppliers(self) -> list[str]:
        return list(self._suppliers)

    async def find_product(self, code, query, upc):  # noqa: ARG002 (base signature)
        data = self._suppliers.get(code)
        if not data:
            return None
        return SupplierProductSearchResult(
            supplier_sku=data["sku"],
            title="Some Product",
            upc=upc,
            price=Decimal(data["price"]),
            moq=1,
            in_stock=data["in_stock"],
            estimated_delivery_days=data["days"],
        )

    async def pricing(self, code, sku):  # noqa: ARG002 (base signature)
        data = self._suppliers.get(code)
        if not data:
            return None
        return SupplierPricing(unit_price=Decimal(data["price"]))

    async def availability(self, code, sku):
        data = self._suppliers.get(code)
        if not data:
            return None
        return SupplierAvailability(
            supplier_sku=sku,
            is_available=data["in_stock"],
            stock_status="in_stock" if data["in_stock"] else "out_of_stock",
        )

    async def shipping(self, code, sku, quantity, postal_code):  # noqa: ARG002 (base signature)
        data = self._suppliers.get(code)
        if not data:
            return None
        return SupplierShipping(methods=[{"name": "std", "cost": data["ship_cost"], "days": data["days"]}])

    async def coupon(self, code):
        data = self._suppliers.get(code)
        if not data or not data.get("discount"):
            return []
        return [
            SupplierCoupon(
                code="X", description="discount",
                discount_type="percentage",
                discount_value=Decimal(data["discount"]),
            )
        ]


def make_manager(db_session: AsyncSession, provider: SupplierProvider | None = None) -> ReverseSourcingManager:
    return ReverseSourcingManager(
        ReverseSourcingRepository(db_session),
        config=CFG,
        provider=provider or FakeProvider(),
        resolver=PassthroughAsinResolver(),
        predictor=TrendDiscountPredictor(),
        intel_manager=None,
    )


def _offers() -> list[Offer]:
    return [
        Offer("walmart", "Walmart", "WM1", 10.0, "USD", 5.99, 5, 15.99, True, "in_stock", 1, 0.1),
        Offer("target", "Target", "TG1", 12.0, "USD", 4.99, 3, 16.99, True, "in_stock", 1, 0.0),
        Offer("costco", "Costco", "CS1", 7.0, "USD", 7.99, 7, 14.99, True, "in_stock", 1, 0.05),
    ]


# ──────────────────────────────────────────────────────────────
# Pure scoring
# ──────────────────────────────────────────────────────────────


class TestScoring:
    def test_rank_offers_picks_lowest_landed_highest(self) -> None:
        ranking, _ = rank_offers(_offers(), {}, CFG.rank_weights)
        assert ranking[0]["supplier_code"] == "costco"
        assert ranking[0]["rank"] == 1
        assert [r["rank"] for r in ranking] == [1, 2, 3]
        assert set(r["supplier_code"] for r in ranking) == {"walmart", "target", "costco"}

    def test_highlights(self) -> None:
        ranking, _ = rank_offers(_offers(), {}, CFG.rank_weights)
        hl = highlights(_offers(), ranking, {})
        assert hl["best"]["supplier_code"] == "costco"
        assert hl["cheapest"]["supplier_code"] == "costco"
        assert hl["fastest"]["supplier_code"] == "target"
        assert hl["highest_confidence"]["supplier_code"] == "costco"

    def test_highlights_honor_intel_confidence(self) -> None:
        ranking, _ = rank_offers(_offers(), {}, CFG.rank_weights)
        intel = {"walmart": {"reliability": 0.9, "risk": 0.1, "confidence": 0.95}}
        hl = highlights(_offers(), ranking, intel)
        assert hl["highest_confidence"]["supplier_code"] == "walmart"

    def test_recommendations_and_summary(self) -> None:
        ranking, _ = rank_offers(_offers(), {}, CFG.rank_weights)
        hl = highlights(_offers(), ranking, {})
        recs = recommendations(
            _offers(), hl, {"costco": 0.1, "walmart": 0.2, "target": 0.0}, {}
        )
        assert any("Buy from" in r for r in recs)
        assert any("predicted ~20% off" in r for r in recs)
        summary = build_summary("B0TEST001", ranking, hl)
        assert "evaluated 3" in summary
        assert "costco" in summary

    def test_empty_offers(self) -> None:
        ranking, _ = rank_offers([], {}, CFG.rank_weights)
        assert ranking == []
        assert highlights([], [], {}) == {}


# ──────────────────────────────────────────────────────────────
# Manager / engine
# ──────────────────────────────────────────────────────────────


class TestManager:
    async def test_source_basic(self, db_session) -> None:
        mgr = make_manager(db_session)
        await mgr.source(ReverseSourcingRequest(asin="B0TEST001", quantity=1))
        result = await mgr.source(ReverseSourcingRequest(asin="B0TEST001", quantity=1))
        assert result.asin == "B0TEST001"
        assert len(result.offers) == 3
        assert result.highlights["best"].supplier_code == "costco"
        assert result.highlights["fastest"].supplier_code == "target"
        assert result.ranking[0].supplier_code == "costco"
        # Discount prediction needs prior history, so it appears on the 2nd run.
        assert result.predicted_discounts["walmart"] == pytest.approx(0.1)
        assert result.recommendations
        assert "evaluated 3" in result.summary
        assert result.created_at

    async def test_adding_supplier_needs_no_engine_change(self, db_session) -> None:
        provider = FakeProvider()
        mgr = make_manager(db_session, provider)
        result = await mgr.source(ReverseSourcingRequest(asin="B0TEST001"))
        assert len(result.offers) == 3

        # Add a brand-new supplier to the provider — the engine just picks it up.
        provider.add_supplier(
            "etsy", {"sku": "ET1", "price": "15.00", "ship_cost": 3.00, "days": 9, "in_stock": True, "discount": None}
        )
        result = await mgr.source(ReverseSourcingRequest(asin="B0TEST001"))
        assert len(result.offers) == 4
        assert any(o.supplier_code == "etsy" for o in result.offers)

    async def test_out_of_stock_supplier_present_but_penalized(self, db_session) -> None:
        provider = FakeProvider()
        provider._suppliers["costco"]["in_stock"] = False  # type: ignore[union-attr]
        mgr = make_manager(db_session, provider)
        result = await mgr.source(ReverseSourcingRequest(asin="B0TEST001"))
        costco = next(o for o in result.offers if o.supplier_code == "costco")
        assert costco.in_stock is False
        assert result.highlights["best"].supplier_code != "costco"

    async def test_historical_accumulates_over_runs(self, db_session) -> None:
        mgr = make_manager(db_session)
        await mgr.source(ReverseSourcingRequest(asin="B0TEST001"))
        hist = await mgr.historical("walmart", "B0TEST001")
        assert hist is not None
        assert hist.sample_count == 1
        assert hist.prices == [pytest.approx(10.0)]
        assert hist.discounts == [pytest.approx(0.1)]

        await mgr.source(ReverseSourcingRequest(asin="B0TEST001"))
        hist2 = await mgr.historical("walmart", "B0TEST001")
        assert hist2 is not None
        assert hist2.sample_count == 2
        assert hist2.avg_price == pytest.approx(10.0)

    async def test_runs_list_get_stats(self, db_session) -> None:
        mgr = make_manager(db_session)
        await mgr.source(ReverseSourcingRequest(asin="B0TEST001"))
        await mgr.source(ReverseSourcingRequest(asin="B0TEST001"))

        runs = await mgr.list_runs(asin="B0TEST001")
        assert runs.total == 2
        first = await mgr.get_run(runs.items[0].id)
        assert first.asin == "B0TEST001"
        assert first.best_supplier == "costco"

        stats = await mgr.stats()
        assert stats.total_runs == 2
        assert stats.total_offers == 6
        assert stats.asins == 1
        assert stats.runs_by_asin["B0TEST001"] == 2

    async def test_capabilities(self, db_session) -> None:
        mgr = make_manager(db_session)
        caps = mgr.capabilities()
        assert caps.enabled is True
        assert set(caps.suppliers) == {"walmart", "target", "costco"}
        assert caps.max_suppliers == 50


# ──────────────────────────────────────────────────────────────
# HTTP API
# ──────────────────────────────────────────────────────────────


class TestAPI:
    async def test_source_endpoint(self, client: AsyncClient, test_app: FastAPI, db_session: AsyncSession) -> None:
        mgr = make_manager(db_session)
        test_app.dependency_overrides[get_reverse_sourcing_manager] = lambda: mgr
        response = await client.post(
            "/api/v1/reverse-sourcing/source",
            json={"asin": "B0TEST001", "quantity": 2},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["asin"] == "B0TEST001"
        assert len(data["offers"]) == 3
        assert data["highlights"]["best"]["supplier_code"] == "costco"
        assert data["recommendations"]

    async def test_runs_and_stats_endpoints(self, client: AsyncClient, test_app: FastAPI, db_session: AsyncSession) -> None:
        mgr = make_manager(db_session)
        test_app.dependency_overrides[get_reverse_sourcing_manager] = lambda: mgr
        await client.post("/api/v1/reverse-sourcing/source", json={"asin": "B0TEST001"})

        runs = await client.get("/api/v1/reverse-sourcing/runs?asin=B0TEST001")
        assert runs.status_code == 200
        assert runs.json()["total"] == 1

        stats = await client.get("/api/v1/reverse-sourcing/stats")
        assert stats.status_code == 200
        assert stats.json()["total_runs"] == 1

        caps = await client.get("/api/v1/reverse-sourcing/capabilities")
        assert caps.status_code == 200
        assert caps.json()["enabled"] is True
