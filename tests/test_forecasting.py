"""Benchmark tests for the forecasting platform.

Covers the modular model registry (statistical / LLM / ensemble; ML gated on
sklearn availability), each statistical + LLM + ensemble formula (deterministic
checks), confidence intervals, the manager's forecast / batch / retrieve /
record-actual / historical-accuracy / stats flows, and the HTTP API.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.forecasting import (
    ForecastActualRequest,
    ForecastConfig,
    ForecastingManager,
    ForecastingRepository,
    ForecastModel,
    ForecastRequest,
    ForecastTarget,
    build_models,
)
from app.forecasting.base import ForecastContext
from app.forecasting.ensemble import EnsembleModel
from app.forecasting.errors import ForecastValidationError
from app.forecasting.llm import LLMReasoningModel
from app.forecasting.statistical import (
    ExponentialSmoothingModel,
    LinearTrendModel,
    MovingAverageModel,
    PersistenceModel,
    SeasonalAverageModel,
)

PRICE = ForecastTarget.PRICE


def make_manager(
    db_session: AsyncSession, config: ForecastConfig | None = None
) -> ForecastingManager:
    cfg = config or ForecastConfig()
    return ForecastingManager(
        ForecastingRepository(db_session),
        config=cfg,
        models=build_models(cfg),
    )


def ctx(
    series: list[float],
    horizon: int = 1,
    target: ForecastTarget = PRICE,
    metadata: dict | None = None,
) -> ForecastContext:
    return ForecastContext(
        target=target,
        entity_type="product",
        entity_id="P1",
        horizon=horizon,
        series=series,
        metadata=metadata or {},
    )


# ──────────────────────────────────────────────────────────────
# Registry / modularity
# ──────────────────────────────────────────────────────────────


class TestRegistry:
    def test_statistical_models_always_available(self) -> None:
        models = build_models(ForecastConfig(enable_ml=True, enable_llm=False))
        for name in ("moving_average", "exponential_smoothing", "linear_trend", "seasonal_average", "persistence"):
            assert name in models

    def test_llm_included_by_default(self) -> None:
        models = build_models(ForecastConfig(enable_llm=True))
        assert "llm_reasoning" in models

    def test_llm_can_be_disabled(self) -> None:
        models = build_models(ForecastConfig(enable_llm=False))
        assert "llm_reasoning" not in models

    def test_ml_gated_on_sklearn(self) -> None:
        # sklearn is not installed in this environment -> ML models are absent.
        models = build_models(ForecastConfig(enable_ml=True))
        assert "ml_linear_regression" not in models
        assert "ml_gradient_boosting" not in models
        # ...but the ensemble still works over the available members.
        assert "ensemble" in models

    def test_ensemble_combines_all_available_members(self) -> None:
        models = build_models(ForecastConfig())
        members = models["ensemble"]._members  # type: ignore[attr-defined]
        assert {m.name for m in members} >= {
            "moving_average",
            "exponential_smoothing",
            "linear_trend",
            "seasonal_average",
            "persistence",
            "llm_reasoning",
        }


# ──────────────────────────────────────────────────────────────
# Statistical models (deterministic)
# ──────────────────────────────────────────────────────────────


class TestStatisticalModels:
    def test_moving_average(self) -> None:
        r = MovingAverageModel().forecast(ctx([10, 10, 10, 10]))
        assert r.prediction == pytest.approx(10.0)
        assert r.model_name == "moving_average"

    def test_linear_trend(self) -> None:
        r = LinearTrendModel().forecast(ctx([1, 2, 3, 4, 5], horizon=1))
        assert r.prediction == pytest.approx(6.0)

    def test_exponential_smoothing(self) -> None:
        r = ExponentialSmoothingModel(alpha=0.3).forecast(ctx([10, 10, 10]))
        assert r.prediction == pytest.approx(10.0)

    def test_seasonal_average(self) -> None:
        r = SeasonalAverageModel(period=3).forecast(
            ctx([5, 10, 15, 5, 10, 15, 5, 10, 15])
        )
        assert r.prediction == pytest.approx(10.0)

    def test_persistence(self) -> None:
        r = PersistenceModel().forecast(ctx([1, 2, 3]))
        assert r.prediction == pytest.approx(3.0)

    def test_all_models_emit_interval_and_confidence(self) -> None:
        for model in (MovingAverageModel(), LinearTrendModel(), ExponentialSmoothingModel(), SeasonalAverageModel(), PersistenceModel()):
            r = model.forecast(ctx([10, 12, 9, 11, 13, 10]))
            assert r.lower < r.prediction < r.upper
            assert 0.05 <= r.confidence <= 1.0
            assert r.explanation
            assert r.version == "1.0.0"

    def test_supports_all_targets(self) -> None:
        for target in ForecastTarget:
            r = PersistenceModel().forecast(ctx([0.5, 0.6, 0.55], target=target))
            assert r.target == target
            assert r.prediction >= 0.0


# ──────────────────────────────────────────────────────────────
# LLM reasoning
# ──────────────────────────────────────────────────────────────


class TestLLM:
    def test_reasoned_prediction_matches_trend(self) -> None:
        r = LLMReasoningModel().forecast(ctx([10, 20, 30, 40, 50], horizon=1))
        # mean=30, slope=10 -> 30 + 10*1 = 40
        assert r.prediction == pytest.approx(40.0)
        assert r.model_name == "llm_reasoning"

    def test_context_adjustment(self) -> None:
        r = LLMReasoningModel().forecast(
            ctx([10, 20, 30, 40, 50], horizon=1, metadata={"promotion_expected": "true"})
        )
        assert r.prediction == pytest.approx(44.0)

    def test_explanation_is_narrative(self) -> None:
        r = LLMReasoningModel().forecast(ctx([10, 20, 30, 40, 50]))
        assert len(r.explanation) > 40
        assert r.lower < r.prediction < r.upper


# ──────────────────────────────────────────────────────────────
# Ensemble
# ──────────────────────────────────────────────────────────────


class TestEnsemble:
    def test_prediction_within_member_range(self) -> None:
        members = [MovingAverageModel(), LinearTrendModel(), PersistenceModel()]
        ensemble = EnsembleModel(members)
        r = ensemble.forecast(ctx([1, 2, 3, 4, 5], horizon=1))
        member_preds = [m.forecast(ctx([1, 2, 3, 4, 5], horizon=1)).prediction for m in members]
        assert min(member_preds) <= r.prediction <= max(member_preds)
        assert r.model_name == "ensemble"
        assert set(r.used_models) == {"moving_average", "linear_trend", "persistence"}

    def test_confidence_interval(self) -> None:
        ensemble = EnsembleModel([MovingAverageModel(), PersistenceModel()])
        r = ensemble.forecast(ctx([5, 5, 5, 5]))
        assert r.lower < r.prediction < r.upper
        assert 0.05 <= r.confidence <= 1.0

    def test_unsupported_target_raises(self) -> None:
        # A contrived ensemble whose members support nothing -> unavailable.
        class Empty(ForecastModel):
            name = "empty"
            method = "empty"
            version = "1.0.0"
            family = "statistical"
            supports = ()

            def forecast(self, _c):
                raise NotImplementedError

        from app.forecasting.errors import ForecastUnavailableError

        with pytest.raises(ForecastUnavailableError):
            EnsembleModel([Empty()]).forecast(ctx([1, 2, 3]))


# ──────────────────────────────────────────────────────────────
# Manager — forecasting & store
# ──────────────────────────────────────────────────────────────


class TestManagerForecast:
    async def test_forecast_returns_and_stores(self, db_session) -> None:
        mgr = make_manager(db_session)
        f = await mgr.forecast(
            ForecastRequest(
                target=PRICE,
                entity_type="product",
                entity_id="P1",
                series=[1, 2, 3, 4, 5],
                horizon=1,
            )
        )
        assert f.id
        assert f.model_name == "ensemble"
        assert f.historical_accuracy == {"sample_count": 0}
        # stored
        listed = await mgr.list_forecasts(entity_id="P1")
        assert listed.total == 1

    async def test_forecast_specific_model(self, db_session) -> None:
        mgr = make_manager(db_session)
        f = await mgr.forecast(
            ForecastRequest(
                target=PRICE, entity_type="product", entity_id="P1",
                series=[1, 2, 3, 4, 5], model="linear_trend",
            )
        )
        assert f.model_name == "linear_trend"

    async def test_unknown_model_raises(self, db_session) -> None:
        mgr = make_manager(db_session)
        with pytest.raises(ForecastValidationError):
            await mgr.forecast(
                ForecastRequest(target=PRICE, entity_type="product", entity_id="P1", series=[1], model="nope")
            )

    async def test_ml_model_unavailable_in_this_env(self, db_session) -> None:
        mgr = make_manager(db_session)
        with pytest.raises(ForecastValidationError):
            await mgr.forecast(
                ForecastRequest(target=PRICE, entity_type="product", entity_id="P1", series=[1, 2, 3], model="ml_linear_regression")
            )

    async def test_horizon_over_limit_raises(self, db_session) -> None:
        mgr = make_manager(db_session, ForecastConfig(max_horizon=2))
        with pytest.raises(ForecastValidationError):
            await mgr.forecast(
                ForecastRequest(target=PRICE, entity_type="product", entity_id="P1", series=[1, 2, 3], horizon=5)
            )

    async def test_batch(self, db_session) -> None:
        mgr = make_manager(db_session)
        from app.forecasting import ForecastBatchItem, ForecastBatchRequest

        req = ForecastBatchRequest(
            requests=[
                ForecastBatchItem(target=PRICE, entity_type="product", entity_id="P1", series=[1, 2, 3]),
                ForecastBatchItem(target=ForecastTarget.SALES, entity_type="product", entity_id="P1", series=[10, 11, 12]),
            ]
        )
        results = await mgr.forecast_batch(req)
        assert len(results) == 2
        assert {r.target for r in results} == {PRICE, ForecastTarget.SALES}

    async def test_batch_over_limit(self, db_session) -> None:
        mgr = make_manager(db_session, ForecastConfig(max_batch_size=1))
        from app.forecasting import ForecastBatchItem, ForecastBatchRequest

        req = ForecastBatchRequest(
            requests=[
                ForecastBatchItem(target=PRICE, entity_type="product", entity_id="P1", series=[1]),
                ForecastBatchItem(target=PRICE, entity_type="product", entity_id="P2", series=[1]),
            ]
        )
        with pytest.raises(ForecastValidationError):
            await mgr.forecast_batch(req)

    async def test_get_and_list(self, db_session) -> None:
        mgr = make_manager(db_session)
        f = await mgr.forecast(
            ForecastRequest(target=PRICE, entity_type="product", entity_id="P1", series=[1, 2, 3, 4], model="persistence")
        )
        got = await mgr.get_forecast(f.id)
        assert got.id == f.id
        assert got.prediction == pytest.approx(4.0)

        filtered = await mgr.list_forecasts(entity_type="product", model="persistence")
        assert filtered.total == 1
        empty = await mgr.list_forecasts(entity_type="order")
        assert empty.total == 0

    async def test_capabilities(self, db_session) -> None:
        mgr = make_manager(db_session)
        caps = mgr.capabilities()
        assert caps.enabled is True
        assert set(caps.targets) == set(ForecastTarget)
        assert caps.default_model == "ensemble"
        model_names = {m.name for m in caps.models}
        assert "ensemble" in model_names
        assert "llm_reasoning" in model_names


# ──────────────────────────────────────────────────────────────
# Historical accuracy
# ──────────────────────────────────────────────────────────────


class TestAccuracy:
    async def test_accuracy_before_actuals_is_zero(self, db_session) -> None:
        mgr = make_manager(db_session)
        acc = await mgr.accuracy(model="moving_average", target=PRICE)
        assert acc == []

    async def test_accuracy_after_recording(self, db_session) -> None:
        mgr = make_manager(db_session)
        f = await mgr.forecast(
            ForecastRequest(
                target=PRICE, entity_type="product", entity_id="P1",
                series=[10, 10, 10], model="moving_average",
            )
        )
        # moving average prediction = 10; record actual 8 -> error -2
        await mgr.record_actual(ForecastActualRequest(forecast_id=f.id, actual_value=8))

        acc = await mgr.accuracy(model="moving_average", target=PRICE)
        assert len(acc) == 1
        a = acc[0]
        assert a.sample_count == 1
        assert a.mae == pytest.approx(2.0)
        assert a.mape == pytest.approx(0.25)
        assert a.rmse == pytest.approx(2.0)
        assert a.bias == pytest.approx(-2.0)

    async def test_accuracy_by_entity(self, db_session) -> None:
        mgr = make_manager(db_session)
        f = await mgr.forecast(
            ForecastRequest(target=PRICE, entity_type="product", entity_id="P1", series=[5, 5, 5], model="persistence")
        )
        actual = await mgr.record_actual(
            ForecastActualRequest(target=PRICE, entity_type="product", entity_id="P1", actual_value=6)
        )
        assert actual.forecast_id == f.id
        acc = await mgr.accuracy()
        assert acc and acc[0].sample_count == 1

    async def test_accuracy_reflected_on_forecast_read(self, db_session) -> None:
        mgr = make_manager(db_session)
        f = await mgr.forecast(
            ForecastRequest(target=PRICE, entity_type="product", entity_id="P1", series=[10, 10, 10], model="moving_average")
        )
        await mgr.record_actual(ForecastActualRequest(forecast_id=f.id, actual_value=8))
        got = await mgr.get_forecast(f.id)
        assert got.historical_accuracy["sample_count"] == 1
        assert got.historical_accuracy["mae"] == pytest.approx(2.0)

    async def test_record_actual_unknown_forecast(self, db_session) -> None:
        from app.forecasting.errors import ForecastNotFoundError

        mgr = make_manager(db_session)
        with pytest.raises(ForecastNotFoundError):
            await mgr.record_actual(
                ForecastActualRequest(forecast_id=None, target=PRICE, entity_type="product", entity_id="NOPE", actual_value=1)
            )

    async def test_stats(self, db_session) -> None:
        mgr = make_manager(db_session)
        await mgr.forecast(
            ForecastRequest(target=PRICE, entity_type="product", entity_id="P1", series=[1, 2, 3], model="persistence")
        )
        await mgr.forecast(
            ForecastRequest(target=PRICE, entity_type="product", entity_id="P1", series=[1, 2, 3], model="moving_average")
        )
        s = await mgr.stats()
        assert s.total_forecasts == 2
        assert s.by_model.get("persistence") == 1
        assert s.by_target.get("price") == 2


# ──────────────────────────────────────────────────────────────
# HTTP API
# ──────────────────────────────────────────────────────────────


class TestAPI:
    async def test_forecast_endpoint(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/forecasting/forecast",
            json={
                "target": "price",
                "entity_type": "product",
                "entity_id": "P1",
                "horizon": 1,
                "series": [1, 2, 3, 4, 5],
                "model": "linear_trend",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["model_name"] == "linear_trend"
        assert data["prediction"] == pytest.approx(6.0)
        assert data["lower"] < data["prediction"] < data["upper"]
        assert data["historical_accuracy"] == {"sample_count": 0}

    async def test_batch_endpoint(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/forecasting/batch",
            json={
                "requests": [
                    {"target": "price", "entity_type": "product", "entity_id": "P1", "series": [1, 2, 3]},
                    {"target": "sales", "entity_type": "product", "entity_id": "P1", "series": [10, 11, 12]},
                ]
            },
        )
        assert response.status_code == 200
        assert len(response.json()) == 2

    async def test_unknown_model_422(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/forecasting/forecast",
            json={"target": "price", "entity_type": "product", "entity_id": "P1", "series": [1], "model": "nope"},
        )
        assert response.status_code == 422

    async def test_get_and_list(self, client: AsyncClient) -> None:
        created = await client.post(
            "/api/v1/forecasting/forecast",
            json={"target": "price", "entity_type": "product", "entity_id": "P1", "series": [1, 2, 3], "model": "persistence"},
        )
        fid = created.json()["id"]

        got = await client.get(f"/api/v1/forecasting/forecasts/{fid}")
        assert got.status_code == 200
        assert got.json()["prediction"] == pytest.approx(3.0)

        listed = await client.get("/api/v1/forecasting/forecasts", params={"entity_type": "product"})
        assert listed.status_code == 200
        assert listed.json()["total"] >= 1

        missing = await client.get("/api/v1/forecasting/forecasts/00000000-0000-0000-0000-000000000000")
        assert missing.status_code == 404

    async def test_record_actual_and_accuracy(self, client: AsyncClient) -> None:
        created = await client.post(
            "/api/v1/forecasting/forecast",
            json={"target": "price", "entity_type": "product", "entity_id": "P1", "series": [10, 10, 10], "model": "moving_average"},
        )
        fid = created.json()["id"]

        rec = await client.post(
            f"/api/v1/forecasting/forecasts/{fid}/actual",
            json={"actual_value": 8},
        )
        assert rec.status_code == 201
        assert rec.json()["actual_value"] == 8

        acc = await client.get("/api/v1/forecasting/accuracy", params={"model": "moving_average", "target": "price"})
        assert acc.status_code == 200
        assert acc.json()[0]["sample_count"] == 1
        assert acc.json()[0]["mae"] == pytest.approx(2.0)

    async def test_actuals_by_entity(self, client: AsyncClient) -> None:
        await client.post(
            "/api/v1/forecasting/forecast",
            json={"target": "sales", "entity_type": "product", "entity_id": "P1", "series": [10, 10, 10], "model": "persistence"},
        )
        rec = await client.post(
            "/api/v1/forecasting/actuals",
            json={"target": "sales", "entity_type": "product", "entity_id": "P1", "actual_value": 12},
        )
        assert rec.status_code == 201

    async def test_capabilities_and_models(self, client: AsyncClient) -> None:
        caps = await client.get("/api/v1/forecasting/capabilities")
        assert caps.status_code == 200
        assert set(caps.json()["targets"]) == {"price", "roi", "profit", "inventory", "sales", "buy_box", "competition"}
        assert "ensemble" in {m["name"] for m in caps.json()["models"]}

        models = await client.get("/api/v1/forecasting/models")
        assert models.status_code == 200
        assert any(m["name"] == "llm_reasoning" for m in models.json())

    async def test_stats_endpoint(self, client: AsyncClient) -> None:
        await client.post(
            "/api/v1/forecasting/forecast",
            json={"target": "price", "entity_type": "product", "entity_id": "P1", "series": [1, 2, 3], "model": "persistence"},
        )
        stats = await client.get("/api/v1/forecasting/stats")
        assert stats.status_code == 200
        assert stats.json()["total_forecasts"] >= 1
