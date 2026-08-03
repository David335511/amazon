"""Benchmark tests for supplier intelligence.

Covers the pure scoring math (reliability, volatility, discount, risk,
seasonality), the manager (record history, scores, profile, explanation,
batch), and the HTTP API. Everything is exercised through historical
observation series, as the design requires.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.supplier_intel import (
    ObservationCreate,
    SupplierIntelConfig,
    SupplierIntelManager,
    SupplierIntelRepository,
)
from app.supplier_intel.scoring import compute_scores, explain, summarize

CFG = SupplierIntelConfig(min_samples=8)


def make_manager(db_session: AsyncSession) -> SupplierIntelManager:
    return SupplierIntelManager(SupplierIntelRepository(db_session), config=CFG)


def _period(index: int) -> datetime:
    return datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=7 * index)


async def _seed(manager: SupplierIntelManager, supplier_id: str, rows: list[dict]) -> None:
    for i, row in enumerate(rows):
        await manager.record_observation(
            ObservationCreate(
                supplier_id=supplier_id,
                supplier_name=supplier_id.title(),
                observed_at=_period(i),
                **row,
            )
        )


# A dependable, low-volatility, low-discount, low-risk supplier.
GOOD_ROWS = [
    {"price": 10.0, "shipping_days": 3, "inventory_level": 100, "inventory_variance": 1,
     "order_cancellation_rate": 0.01, "customer_service_score": 0.9,
     "return_policy_score": 0.8, "discount_depth": 0.05, "coupon_events": 0,
     "sale_events": 0, "stockouts": 0}
    for _ in range(10)
]

# An unstable, high-discount, high-risk supplier.
BAD_ROWS = [
    {"price": 5.0 if i % 2 == 0 else 20.0, "shipping_days": 13, "inventory_level": 10 if i % 2 else 200,
     "inventory_variance": 80, "order_cancellation_rate": 0.4,
     "customer_service_score": 0.2, "return_policy_score": 0.1,
     "discount_depth": 0.5, "coupon_events": 5, "sale_events": 4, "stockouts": 3}
    for i in range(10)
]

# A strongly seasonal supplier (alternating high/low price -> 2-period cycle).
SEASONAL_ROWS = [
    {"price": 10.0 if i % 2 == 0 else 25.0, "shipping_days": 5, "inventory_level": 50,
     "inventory_variance": 2, "order_cancellation_rate": 0.05,
     "customer_service_score": 0.7, "return_policy_score": 0.6,
     "discount_depth": 0.1, "coupon_events": 1, "sale_events": 1, "stockouts": 0}
    for i in range(10)
]


# ──────────────────────────────────────────────────────────────
# Pure scoring math
# ──────────────────────────────────────────────────────────────


def _obs(rows: list[dict]):
    from app.supplier_intel.models import SupplierObservation

    out = []
    for i, row in enumerate(rows):
        out.append(SupplierObservation(observed_at=_period(i), **row))
    return out


class TestScoring:
    def test_reliability_high_for_good_supplier(self) -> None:
        scores = compute_scores(_obs(GOOD_ROWS), CFG)
        assert scores["reliability"]["value"] > 0.8

    def test_reliability_low_for_bad_supplier(self) -> None:
        scores = compute_scores(_obs(BAD_ROWS), CFG)
        assert scores["reliability"]["value"] < 0.3
        # good >> bad
        assert compute_scores(_obs(GOOD_ROWS), CFG)["reliability"]["value"] > scores["reliability"]["value"]

    def test_volatility_low_for_good_high_for_bad(self) -> None:
        good = compute_scores(_obs(GOOD_ROWS), CFG)
        bad = compute_scores(_obs(BAD_ROWS), CFG)
        assert good["volatility"]["value"] < 0.2
        assert bad["volatility"]["value"] > 0.6

    def test_discount_low_for_good_high_for_discounter(self) -> None:
        good = compute_scores(_obs(GOOD_ROWS), CFG)
        bad = compute_scores(_obs(BAD_ROWS), CFG)
        assert good["discount"]["value"] < 0.2
        assert bad["discount"]["value"] > 0.6

    def test_risk_low_for_good_high_for_bad(self) -> None:
        good = compute_scores(_obs(GOOD_ROWS), CFG)
        bad = compute_scores(_obs(BAD_ROWS), CFG)
        assert good["risk"]["value"] < 0.3
        assert bad["risk"]["value"] > 0.6

    def test_seasonality_detects_periodic_pattern(self) -> None:
        seasonal = compute_scores(_obs(SEASONAL_ROWS), CFG)
        assert seasonal["seasonality"]["value"] > 0.8
        assert seasonal["seasonality"]["components"]["best_period"] == 2

    def test_seasonality_low_for_flat_series(self) -> None:
        flat = compute_scores(_obs(GOOD_ROWS), CFG)
        assert flat["seasonality"]["value"] < 0.2

    def test_scores_have_confidence_and_components(self) -> None:
        scores = compute_scores(_obs(GOOD_ROWS), CFG)
        assert set(scores) == {"reliability", "volatility", "discount", "risk", "seasonality"}
        for _name, payload in scores.items():
            assert 0.0 <= payload["value"] <= 1.0
            assert 0.0 <= payload["confidence"] <= 1.0
            assert isinstance(payload["components"], dict)

    def test_empty_history_returns_zero_scores(self) -> None:
        scores = compute_scores([], CFG)
        assert scores["reliability"]["value"] == 0.0


class TestExplanation:
    def test_explain_builds_narrative(self) -> None:
        scores = compute_scores(_obs(GOOD_ROWS), CFG)
        metrics = summarize(_obs(GOOD_ROWS), CFG)
        text = explain(scores, metrics)
        assert "reliable" in text.lower()
        assert metrics["sample_count"] == 10
        assert len(text) > 100

    def test_explain_calls_out_seasonality(self) -> None:
        scores = compute_scores(_obs(SEASONAL_ROWS), CFG)
        metrics = summarize(_obs(SEASONAL_ROWS), CFG)
        text = explain(scores, metrics)
        assert "seasonal" in text.lower() or "cycle" in text.lower()


# ──────────────────────────────────────────────────────────────
# Manager
# ──────────────────────────────────────────────────────────────


class TestManager:
    async def test_record_and_list_observations(self, db_session) -> None:
        mgr = make_manager(db_session)
        await _seed(mgr, "walmart", GOOD_ROWS)
        listed = await mgr.list_observations(supplier_id="walmart")
        assert listed.total == 10
        assert listed.items[0].supplier_name == "Walmart"
        assert listed.items[0].price == pytest.approx(10.0)

    async def test_scores(self, db_session) -> None:
        mgr = make_manager(db_session)
        await _seed(mgr, "target", GOOD_ROWS)
        scores = await mgr.scores("target")
        assert set(scores) == {"reliability", "volatility", "discount", "risk", "seasonality"}
        assert scores["reliability"].name.value == "reliability"
        assert scores["reliability"].value > 0.8

    async def test_profile_returns_metrics_and_explanation(self, db_session) -> None:
        mgr = make_manager(db_session)
        await _seed(mgr, "costco", GOOD_ROWS)
        profile = await mgr.profile("costco")
        assert profile.supplier_id == "costco"
        assert profile.supplier_name == "Costco"
        assert profile.sample_count == 10
        assert profile.metrics["avg_price"] == pytest.approx(10.0)
        assert profile.metrics["avg_shipping_days"] == pytest.approx(3.0)
        assert profile.explanation
        assert profile.computed_at

    async def test_profile_raises_when_no_history(self, db_session) -> None:
        from app.supplier_intel.errors import SupplierIntelNotFoundError

        mgr = make_manager(db_session)
        with pytest.raises(SupplierIntelNotFoundError):
            await mgr.profile("nobody")

    async def test_profile_batch(self, db_session) -> None:
        from app.supplier_intel import SupplierIntelBatchRequest

        mgr = make_manager(db_session)
        await _seed(mgr, "walmart", GOOD_ROWS)
        await _seed(mgr, "target", BAD_ROWS)
        result = await mgr.profile_batch(
            SupplierIntelBatchRequest(supplier_ids=["walmart", "target", "missing"])
        )
        assert [r.supplier_id for r in result] == ["walmart", "target"]

    async def test_explain_method(self, db_session) -> None:
        mgr = make_manager(db_session)
        await _seed(mgr, "walmart", GOOD_ROWS)
        text = await mgr.explain("walmart")
        assert "Based on 10 historical period" in text

    async def test_capabilities(self, db_session) -> None:
        mgr = make_manager(db_session)
        caps = mgr.capabilities()
        assert caps.enabled is True
        assert caps.scores == ["reliability", "volatility", "discount", "risk", "seasonality"]
        assert "shipping_speed" in caps.tracked_metrics

    async def test_suppliers_and_stats(self, db_session) -> None:
        mgr = make_manager(db_session)
        await _seed(mgr, "walmart", GOOD_ROWS)
        await _seed(mgr, "target", BAD_ROWS)
        suppliers = await mgr.suppliers()
        assert set(suppliers) == {"walmart", "target"}
        stats = await mgr.stats()
        assert stats.total_observations == 20
        assert stats.suppliers == 2
        assert stats.observations_by_supplier["walmart"] == 10


# ──────────────────────────────────────────────────────────────
# HTTP API
# ──────────────────────────────────────────────────────────────


class TestAPI:
    async def test_record_observation(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/supplier-intel/observations",
            json={
                "supplier_id": "walmart",
                "price": 12.5,
                "shipping_days": 4,
                "inventory_level": 100,
                "customer_service_score": 0.8,
                "order_cancellation_rate": 0.02,
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["supplier_id"] == "walmart"
        assert data["price"] == 12.5
        assert data["shipping_days"] == 4

    async def test_list_observations(self, client: AsyncClient) -> None:
        await client.post(
            "/api/v1/supplier-intel/observations",
            json={"supplier_id": "target", "price": 9.0, "shipping_days": 5},
        )
        response = await client.get("/api/v1/supplier-intel/observations?supplier_id=target")
        assert response.status_code == 200
        assert response.json()["total"] == 1

    async def test_scores_endpoint(self, client: AsyncClient) -> None:
        await _seed_via_api(client, "walmart", GOOD_ROWS)
        response = await client.get("/api/v1/supplier-intel/scores?supplier_id=walmart")
        assert response.status_code == 200
        data = response.json()
        assert set(data) == {"reliability", "volatility", "discount", "risk", "seasonality"}
        assert data["reliability"]["value"] > 0.8

    async def test_profile_endpoint(self, client: AsyncClient) -> None:
        await _seed_via_api(client, "costco", GOOD_ROWS)
        response = await client.get("/api/v1/supplier-intel/profile?supplier_id=costco")
        assert response.status_code == 200
        data = response.json()
        assert data["sample_count"] == 10
        assert data["metrics"]["avg_price"] == pytest.approx(10.0)
        assert data["explanation"]
        assert "reliability" in data["scores"]

    async def test_profile_endpoint_404(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/supplier-intel/profile?supplier_id=ghost")
        assert response.status_code == 404

    async def test_explain_endpoint(self, client: AsyncClient) -> None:
        await _seed_via_api(client, "walmart", GOOD_ROWS)
        response = await client.get("/api/v1/supplier-intel/explain?supplier_id=walmart")
        assert response.status_code == 200
        assert "Based on 10 historical period" in response.json()["explanation"]

    async def test_suppliers_and_stats_endpoints(self, client: AsyncClient) -> None:
        await _seed_via_api(client, "walmart", GOOD_ROWS)
        suppliers = await client.get("/api/v1/supplier-intel/suppliers")
        assert suppliers.status_code == 200
        assert "walmart" in suppliers.json()

        stats = await client.get("/api/v1/supplier-intel/stats")
        assert stats.status_code == 200
        assert stats.json()["total_observations"] == 10
        assert stats.json()["suppliers"] == 1

    async def test_capabilities_endpoint(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/supplier-intel/capabilities")
        assert response.status_code == 200
        data = response.json()
        assert data["scores"] == ["reliability", "volatility", "discount", "risk", "seasonality"]
        assert len(data["tracked_metrics"]) >= 10


async def _seed_via_api(client: AsyncClient, supplier_id: str, rows: list[dict]) -> None:
    for i, row in enumerate(rows):
        payload = {"supplier_id": supplier_id, "observed_at": _period(i).isoformat(), **row}
        response = await client.post("/api/v1/supplier-intel/observations", json=payload)
        assert response.status_code == 201
