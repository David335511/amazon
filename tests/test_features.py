"""Benchmark tests for the feature engineering platform.

Covers the compute-once-and-reuse feature store, all 14 feature computers
(deterministic formula checks), freshness/force/refresh semantics, lineage and
versioning, signal override merging, batch calculation, and the HTTP API.
"""

from __future__ import annotations

from datetime import UTC

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.features import (
    FeatureConfig,
    FeatureManager,
    FeatureRepository,
    feature_registry,
    get_feature_computer,
)
from app.features.errors import FeatureNotFoundError, FeatureValidationError
from app.features.signals import LocalSignalProvider

EXPECTED_KEYS = {
    "price_stability_score",
    "brand_risk_score",
    "supplier_reliability_score",
    "competition_score",
    "buy_box_stability",
    "inventory_health",
    "velocity_score",
    "seasonality_score",
    "coupon_frequency",
    "restock_probability",
    "expected_margin",
    "expected_roi",
    "expected_sales",
    "expected_turnover",
}


def make_manager(
    db_session: AsyncSession,
    ttl: int | None = None,
    signals: dict | None = None,
) -> FeatureManager:
    cfg = FeatureConfig(default_ttl_seconds=ttl if ttl is not None else 3600)
    return FeatureManager(
        FeatureRepository(db_session),
        config=cfg,
        signal_provider=LocalSignalProvider(signals),
    )


# ──────────────────────────────────────────────────────────────
# Registry & definitions
# ──────────────────────────────────────────────────────────────


class TestRegistry:
    def test_all_features_registered(self) -> None:
        keys = set(feature_registry())
        assert EXPECTED_KEYS.issubset(keys)

    def test_each_feature_has_metadata(self) -> None:
        for key in EXPECTED_KEYS:
            cls = get_feature_computer(key)
            assert cls is not None
            assert cls.name
            assert cls.description
            assert cls.formula
            assert cls.version == "1.0.0"

    async def test_unknown_feature_raises(self, db_session) -> None:
        mgr = make_manager(db_session)
        with pytest.raises(FeatureValidationError):
            mgr.definition("nope")
        with pytest.raises(FeatureValidationError):
            await mgr.calculate("nope", "product", "P1")

    def test_capabilities(self, db_session) -> None:
        mgr = make_manager(db_session)
        caps = mgr.capabilities()
        assert caps.enabled is True
        assert caps.feature_count == len(EXPECTED_KEYS)
        assert caps.signal_provider == "local"
        assert len(caps.features) == caps.feature_count


# ──────────────────────────────────────────────────────────────
# Individual feature computations
# ──────────────────────────────────────────────────────────────


class TestComputations:
    async def _calc(self, db_session, key: str, entity_id: str = "P1", **signals):
        mgr = make_manager(db_session)
        return await mgr.calculate(key, "product", entity_id, force=True, signals=signals)

    async def test_price_stability(self, db_session) -> None:
        r = await self._calc(db_session, "price_stability_score", price_history=[10, 10, 10])
        assert r.value == pytest.approx(1.0)
        r2 = await self._calc(db_session, "price_stability_score", "P2", price_history=[10, 100, 10])
        assert r2.value < 0.5

    async def test_brand_risk(self, db_session) -> None:
        r = await self._calc(db_session, "brand_risk_score", brand="Acme")
        assert r.value == pytest.approx(0.05)
        r2 = await self._calc(
            db_session,
            "brand_risk_score",
            "P2",
            brand="Bad",
            brand_risk_indicators=["lawsuit", "counterfeit"],
            recall_flag=True,
        )
        assert r2.value == pytest.approx(0.75)

    async def test_supplier_reliability(self, db_session) -> None:
        r = await self._calc(
            db_session,
            "supplier_reliability_score",
            supplier_on_time_rate=0.95,
            supplier_fill_rate=0.9,
            supplier_rating=5,
            supplier_incidents=0,
        )
        assert r.value == pytest.approx(0.95)

    async def test_competition(self, db_session) -> None:
        r = await self._calc(
            db_session,
            "competition_score",
            competitor_prices=[1, 2, 3],
            list_price=10,
            buy_box_price=5,
        )
        assert r.value == pytest.approx(0.44)

    async def test_buy_box_stability(self, db_session) -> None:
        r = await self._calc(
            db_session,
            "buy_box_stability",
            buy_box_share=0.8,
            price_volatility=0.1,
            win_rate=0.7,
        )
        assert r.value == pytest.approx(0.81)

    async def test_inventory_health(self, db_session) -> None:
        r = await self._calc(
            db_session,
            "inventory_health",
            stock_level=100,
            reorder_point=10,
            max_stock=200,
        )
        assert r.value == pytest.approx(1.0)
        r2 = await self._calc(
            db_session,
            "inventory_health",
            "P2",
            stock_level=0,
            reorder_point=10,
            max_stock=200,
        )
        assert r2.value == pytest.approx(0.0)

    async def test_velocity(self, db_session) -> None:
        r = await self._calc(db_session, "velocity_score", sales_velocity=30, category_avg_velocity=10)
        assert r.value == pytest.approx(1.0)

    async def test_seasonality(self, db_session) -> None:
        r = await self._calc(
            db_session,
            "seasonality_score",
            monthly_sales=[10, 10, 30, 10, 10, 10, 10, 10, 10, 10, 10, 10],
        )
        assert r.value == pytest.approx(1 - 10 / 30, abs=1e-3)

    async def test_coupon_frequency(self, db_session) -> None:
        r = await self._calc(db_session, "coupon_frequency", coupon_count=6, coupon_window_days=30)
        assert r.value == pytest.approx(6.0)

    async def test_restock_probability(self, db_session) -> None:
        r = await self._calc(
            db_session,
            "restock_probability",
            stock_level=100,
            sales_velocity=10,
            lead_time_days=5,
            demand_std=5,
        )
        assert 0.0 < r.value < 0.2
        r2 = await self._calc(
            db_session,
            "restock_probability",
            "P2",
            stock_level=0,
            sales_velocity=10,
            lead_time_days=5,
        )
        assert r2.value > 0.9

    async def test_expected_margin(self, db_session) -> None:
        r = await self._calc(
            db_session,
            "expected_margin",
            sell_price=100,
            cost=60,
            fees_pct=0.15,
            holding_cost=5,
        )
        assert r.value == pytest.approx(0.20)

    async def test_expected_roi(self, db_session) -> None:
        r = await self._calc(db_session, "expected_roi", expected_profit=15, invested_capital=100)
        assert r.value == pytest.approx(0.15)

    async def test_expected_sales(self, db_session) -> None:
        r = await self._calc(
            db_session,
            "expected_sales",
            sales_velocity=10,
            seasonality_factor=1.2,
            demand_growth_rate=0.1,
            promotion_effect=0.2,
        )
        assert r.value == pytest.approx(15.84)

    async def test_expected_turnover(self, db_session) -> None:
        r = await self._calc(
            db_session,
            "expected_turnover",
            annual_sales_qty=120,
            avg_inventory_qty=20,
        )
        assert r.value == pytest.approx(6.0)


# ──────────────────────────────────────────────────────────────
# Store semantics: compute-once-and-reuse
# ──────────────────────────────────────────────────────────────


class TestStoreSemantics:
    async def test_calculate_reuses_fresh_value(self, db_session) -> None:
        mgr = make_manager(db_session)
        first = await mgr.calculate(
            "price_stability_score", "product", "P1", signals={"price_history": [10, 10, 10]}
        )
        # Stored value is fresh -> the store is reused even with different signals.
        second = await mgr.calculate(
            "price_stability_score", "product", "P1", signals={"price_history": [10, 100, 10]}
        )
        assert second.id == first.id
        assert second.value == pytest.approx(1.0)

    async def test_force_recomputes(self, db_session) -> None:
        mgr = make_manager(db_session)
        first = await mgr.calculate(
            "price_stability_score", "product", "P1", signals={"price_history": [10, 10, 10]}
        )
        forced = await mgr.calculate(
            "price_stability_score",
            "product",
            "P1",
            force=True,
            signals={"price_history": [10, 100, 10]},
        )
        assert forced.value < first.value
        assert forced.computed_at >= first.computed_at

    async def test_refresh_overwrites(self, db_session) -> None:
        mgr = make_manager(db_session)
        first = await mgr.calculate(
            "price_stability_score", "product", "P1", signals={"price_history": [10, 10, 10]}
        )
        refreshed = await mgr.refresh(
            "price_stability_score", "product", "P1", signals={"price_history": [10, 100, 10]}
        )
        assert refreshed.id == first.id
        assert refreshed.value < first.value

    async def test_stale_value_recomputed(self, db_session) -> None:
        from datetime import datetime, timedelta

        mgr = make_manager(db_session)
        first = await mgr.calculate(
            "price_stability_score", "product", "P1", signals={"price_history": [10, 10, 10]}
        )
        # Force the stored value past its refresh point.
        row = await mgr._repo.get_latest("price_stability_score", "product", "P1")
        row.stale_after = datetime.now(UTC) - timedelta(seconds=1)
        await db_session.flush()
        second = await mgr.calculate(
            "price_stability_score", "product", "P1", signals={"price_history": [10, 100, 10]}
        )
        assert second.value < first.value  # recomputed, not reused

    async def test_get_retrieves_without_computing(self, db_session) -> None:
        mgr = make_manager(db_session)
        await mgr.calculate("velocity_score", "product", "P1", signals={"sales_velocity": 30, "category_avg_velocity": 10})
        got = await mgr.get("velocity_score", "product", "P1")
        assert got.value == pytest.approx(1.0)

    async def test_get_unknown_raises_not_found(self, db_session) -> None:
        mgr = make_manager(db_session)
        with pytest.raises(FeatureNotFoundError):
            await mgr.get("velocity_score", "product", "NOPE")

    async def test_signal_provider_defaults(self, db_session) -> None:
        # Provider supplies neutral signals; value still computed from them.
        mgr = make_manager(db_session, signals={"price_history": [5, 5, 5]})
        r = await mgr.calculate("price_stability_score", "product", "P1", force=True)
        assert r.value == pytest.approx(1.0)


# ──────────────────────────────────────────────────────────────
# Lineage, versioning, confidence
# ──────────────────────────────────────────────────────────────


class TestProvenance:
    async def test_lineage_recorded(self, db_session) -> None:
        mgr = make_manager(db_session)
        r = await mgr.calculate(
            "expected_margin",
            "product",
            "P1",
            force=True,
            signals={"sell_price": 100, "cost": 60, "fees_pct": 0.15, "holding_cost": 5},
        )
        assert r.version == "1.0.0"
        lineage = r.lineage
        assert lineage["feature"] == "expected_margin"
        assert lineage["version"] == "1.0.0"
        assert lineage["method"]
        assert lineage["output_hash"]
        assert lineage["computed_at"]
        assert len(lineage["inputs"]) == 4

    async def test_confidence_reflects_signal_availability(self, db_session) -> None:
        mgr = make_manager(db_session)
        full = await mgr.calculate(
            "brand_risk_score",
            "product",
            "P1",
            force=True,
            signals={"brand": "X", "brand_risk_indicators": [], "negative_reviews_rate": 0.1, "recall_flag": False},
        )
        partial = await mgr.calculate(
            "brand_risk_score", "product", "P2", force=True, signals={"brand": "X"}
        )
        assert full.confidence == pytest.approx(1.0)
        assert partial.confidence == pytest.approx(0.25)


# ──────────────────────────────────────────────────────────────
# Batch
# ──────────────────────────────────────────────────────────────


class TestBatch:
    async def test_batch_calculates_many(self, db_session) -> None:
        from app.features import FeatureBatchItem

        mgr = make_manager(db_session)
        requests = [
            FeatureBatchItem(feature_key="velocity_score", entity_type="product", entity_id="P1"),
            FeatureBatchItem(feature_key="expected_turnover", entity_type="product", entity_id="P1"),
        ]
        results = await mgr.calculate_batch(requests, force=True, signals={"sales_velocity": 30, "category_avg_velocity": 10, "annual_sales_qty": 120, "avg_inventory_qty": 20})
        assert len(results) == 2
        assert {r.feature_key for r in results} == {"velocity_score", "expected_turnover"}

    async def test_batch_over_limit_rejected(self, db_session) -> None:
        from app.features import FeatureBatchItem

        cfg = FeatureConfig(max_batch_size=1)
        mgr = FeatureManager(FeatureRepository(db_session), config=cfg)
        requests = [
            FeatureBatchItem(feature_key="velocity_score", entity_type="product", entity_id="P1"),
            FeatureBatchItem(feature_key="velocity_score", entity_type="product", entity_id="P2"),
        ]
        with pytest.raises(FeatureValidationError):
            await mgr.calculate_batch(requests)


# ──────────────────────────────────────────────────────────────
# List / stats
# ──────────────────────────────────────────────────────────────


class TestListStats:
    async def test_list_and_stats(self, db_session) -> None:
        mgr = make_manager(db_session)
        await mgr.calculate("velocity_score", "product", "P1", force=True, signals={"sales_velocity": 30, "category_avg_velocity": 10})
        await mgr.calculate("expected_roi", "product", "P1", force=True, signals={"expected_profit": 10, "invested_capital": 100})
        await mgr.calculate("velocity_score", "product", "P2", force=True, signals={"sales_velocity": 5, "category_avg_velocity": 10})

        listed = await mgr.list_values()
        assert listed.total == 3

        by_feature = await mgr.list_values(feature_key="velocity_score")
        assert by_feature.total == 2

        stats = await mgr.stats()
        assert stats.total_values == 3
        assert stats.by_feature.get("velocity_score") == 2


# ──────────────────────────────────────────────────────────────
# HTTP API
# ──────────────────────────────────────────────────────────────


class TestAPI:
    async def test_calculate_endpoint(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/features/calculate",
            json={
                "feature_key": "expected_margin",
                "entity_type": "product",
                "entity_id": "P1",
                "force": True,
                "signals": {"sell_price": 100, "cost": 60, "fees_pct": 0.15, "holding_cost": 5},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["feature_key"] == "expected_margin"
        assert data["value"] == pytest.approx(0.20)
        assert data["version"] == "1.0.0"
        assert data["lineage"]["feature"] == "expected_margin"

    async def test_calculate_unknown_feature(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/features/calculate",
            json={"feature_key": "bogus", "entity_type": "product", "entity_id": "P1"},
        )
        assert response.status_code == 422

    async def test_refresh_endpoint(self, client: AsyncClient) -> None:
        await client.post(
            "/api/v1/features/calculate",
            json={"feature_key": "price_stability_score", "entity_type": "product", "entity_id": "P1", "signals": {"price_history": [10, 10, 10]}},
        )
        response = await client.post(
            "/api/v1/features/refresh",
            json={"feature_key": "price_stability_score", "entity_type": "product", "entity_id": "P1", "signals": {"price_history": [10, 100, 10]}},
        )
        assert response.status_code == 200
        assert response.json()["value"] < 1.0

    async def test_get_value_endpoint(self, client: AsyncClient) -> None:
        await client.post(
            "/api/v1/features/calculate",
            json={"feature_key": "expected_turnover", "entity_type": "product", "entity_id": "P1", "signals": {"annual_sales_qty": 120, "avg_inventory_qty": 20}},
        )
        response = await client.get(
            "/api/v1/features/value",
            params={"feature_key": "expected_turnover", "entity_type": "product", "entity_id": "P1"},
        )
        assert response.status_code == 200
        assert response.json()["value"] == pytest.approx(6.0)

    async def test_get_missing_value_404(self, client: AsyncClient) -> None:
        response = await client.get(
            "/api/v1/features/value",
            params={"feature_key": "expected_turnover", "entity_type": "product", "entity_id": "NOPE"},
        )
        assert response.status_code == 404

    async def test_batch_endpoint(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/features/batch",
            json={
                "requests": [
                    {"feature_key": "velocity_score", "entity_type": "product", "entity_id": "P1"},
                    {"feature_key": "expected_turnover", "entity_type": "product", "entity_id": "P1"},
                ],
                "force": True,
                "signals": {"sales_velocity": 30, "category_avg_velocity": 10, "annual_sales_qty": 120, "avg_inventory_qty": 20},
            },
        )
        assert response.status_code == 200
        assert len(response.json()) == 2

    async def test_definitions_endpoint(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/features/definitions")
        assert response.status_code == 200
        keys = {d["key"] for d in response.json()}
        assert EXPECTED_KEYS.issubset(keys)

    async def test_definition_by_key(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/features/definitions/price_stability_score")
        assert response.status_code == 200
        assert response.json()["formula"]

    async def test_capabilities_endpoint(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/features/capabilities")
        assert response.status_code == 200
        assert response.json()["feature_count"] == len(EXPECTED_KEYS)

    async def test_values_endpoint(self, client: AsyncClient) -> None:
        await client.post(
            "/api/v1/features/calculate",
            json={"feature_key": "velocity_score", "entity_type": "product", "entity_id": "P1", "signals": {"sales_velocity": 30, "category_avg_velocity": 10}},
        )
        response = await client.get("/api/v1/features/values")
        assert response.status_code == 200
        assert response.json()["total"] >= 1
