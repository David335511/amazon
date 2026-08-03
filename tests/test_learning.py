"""Tests for the continuous-learning platform (engine, manager, API)."""

from __future__ import annotations

import pytest

from app.learning.config import LearningConfig
from app.learning.engine import (
    accuracy_summary,
    bias,
    directional_accuracy,
    mae,
    mape,
    optimize_threshold,
    pearson,
    reweight_feature,
    rmse,
    rolling_accuracy,
    scan_issues,
)
from app.learning.manager import LearningManager
from app.learning.repository import LearningRepository


def _manager(db_session) -> LearningManager:
    return LearningManager(LearningRepository(db_session), config=LearningConfig())


async def _record_prediction(
    db_session,
    *,
    ptype: str,
    subject: str,
    decision_type: str,
    decision_id: str,
    predicted: float,
    model_version: str = "1.0.0",
    features: list[dict] | None = None,
    external_id: str | None = None,
) -> dict:
    mgr = _manager(db_session)
    body = {
        "prediction_type": ptype,
        "subject_key": subject,
        "decision_type": decision_type,
        "decision_id": decision_id,
        "model_version": model_version,
        "predicted_value": predicted,
    }
    if features is not None:
        body["features"] = features
    if external_id:
        body["external_id"] = external_id
    body.setdefault("external_id", None)
    body.setdefault("predicted_at", None)
    body.setdefault("features", None)
    body.setdefault("context", None)
    await mgr.record_prediction(type("R", (), body)())
    return body


async def _record_outcome(
    db_session, *, ptype: str, subject: str, decision_id: str, actual: float
) -> int:
    mgr = _manager(db_session)
    req = type(
        "O", (),
        {"prediction_type": ptype, "subject_key": subject,
         "decision_id": decision_id, "model_version": None,
         "external_id": None, "actual_value": actual, "outcome_at": None},
    )()
    return await mgr.record_outcome(req)


# ──────────────────────────────────────────────────────────────
# Engine unit tests
# ──────────────────────────────────────────────────────────────


def test_error_metrics() -> None:
    actuals = [10.0, 20.0, 30.0]
    preds = [9.0, 22.0, 28.0]
    assert mae(actuals, preds) == pytest.approx(1.6667, abs=0.001)
    assert rmse(actuals, preds) == pytest.approx(1.732, abs=0.001)
    assert mape(actuals, preds) == pytest.approx(8.8889, abs=0.01)
    assert bias(actuals, preds) == pytest.approx(-0.3333, abs=0.01)


def test_directional_accuracy() -> None:
    # base = mean(actuals) = 2.0; predictions agree on the side of the mean.
    actuals = [1.0, 3.0, 5.0]
    preds = [1.5, 3.5, 5.5]  # all on same side as actuals
    assert directional_accuracy(actuals, preds) == 1.0


def test_accuracy_summary_shape() -> None:
    summary = accuracy_summary([1.0, 2.0, 3.0], [1.5, 2.0, 2.5])
    assert set(summary) >= {"mae", "rmse", "mape", "bias", "directional_accuracy", "correlation"}
    assert summary["n"] == 3


def test_pearson() -> None:
    assert pearson([1.0, 2.0, 3.0], [2.0, 4.0, 6.0]) == pytest.approx(1.0)
    assert pearson([1.0, 2.0, 3.0], [3.0, 2.0, 1.0]) == pytest.approx(-1.0)
    assert pearson([1.0, 1.0, 1.0], [1.0, 2.0, 3.0]) == 0.0  # zero variance


def test_rolling_accuracy() -> None:
    records = [
        {"actual": 1.0, "pred": 2.0, "at": "t1"},
        {"actual": 2.0, "pred": 2.0, "at": "t2"},
        {"actual": 3.0, "pred": 3.0, "at": "t3"},
    ]
    series = rolling_accuracy(records, window=2)
    assert len(series) == 3
    assert series[0]["n"] == 1
    assert series[1]["n"] == 2
    assert series[2]["n"] == 2
    assert series[0]["mae"] == pytest.approx(1.0)


def test_optimize_threshold_separated() -> None:
    pairs = [(1.0, 1), (0.9, 1), (0.8, 1), (0.2, 0), (0.1, 0)]
    best = optimize_threshold(pairs)
    assert best["threshold"] == pytest.approx(0.5)
    assert best["score"] >= 0.99
    assert best["tp"] == 3 and best["fp"] == 0


def test_optimize_threshold_inverted() -> None:
    # Truth is inverted: low scores are positive. Default 0.5 would be wrong.
    pairs = [(0.9, 0), (0.8, 0), (0.7, 0), (0.3, 1), (0.2, 1), (0.1, 1)]
    best = optimize_threshold(pairs)
    assert best["threshold"] <= 0.4
    assert best["score"] > 0.6


def test_reweight_feature_downweights_correlated() -> None:
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    errors = [1.0, 2.0, 3.0, 4.0, 5.0]  # feature perfectly tracks error
    result = reweight_feature(values, errors, 1.0)
    assert result["correlation"] == pytest.approx(1.0)
    assert result["suggested_weight"] < result["current_weight"]
    assert result["explanation"]


def test_scan_issues_flags_bad_group() -> None:
    # decision 'r1' over-predicts badly across 5 outcomes -> flagged.
    predictions = [
        {"prediction_type": "profit", "decision_type": "rule", "decision_id": "r1",
         "model_version": "1.0.0", "pred": 100.0 + i, "actual": 1.0}
        for i in range(5)
    ] + [
        {"prediction_type": "profit", "decision_type": "rule", "decision_id": "r-good",
         "model_version": "1.0.0", "pred": 1.0, "actual": 1.0}
        for _ in range(5)
    ]
    issues = scan_issues(predictions, min_samples=3, severity_threshold=0.4)
    kinds = {i["decision_id"]: i["issue_type"] for i in issues}
    assert "r1" in kinds
    assert kinds["r1"] == "bad_rule"
    assert "r-good" not in kinds


def test_scan_issues_no_flags_when_accurate() -> None:
    predictions = [
        {"prediction_type": "sales", "decision_type": "match", "decision_id": "m1",
         "model_version": "1.0.0", "pred": 10.0, "actual": 10.0}
        for _ in range(5)
    ]
    issues = scan_issues(predictions, min_samples=3, severity_threshold=0.4)
    assert issues == []


# ──────────────────────────────────────────────────────────────
# Manager tests
# ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_record_prediction_idempotent_by_external_id(db_session) -> None:
    mgr = _manager(db_session)
    await _record_prediction(
        db_session, ptype="profit", subject="A", decision_type="rule",
        decision_id="r1", predicted=5.0, external_id="ext-1",
    )
    # second record with same external_id is idempotent
    await _record_prediction(
        db_session, ptype="profit", subject="A", decision_type="rule",
        decision_id="r1", predicted=999.0, external_id="ext-1",
    )
    result = await mgr.list_predictions()
    assert result.total == 1


@pytest.mark.asyncio
async def test_record_outcome_sets_actual(db_session) -> None:
    mgr = _manager(db_session)
    await _record_prediction(
        db_session, ptype="sales", subject="S1", decision_type="prompt",
        decision_id="p1", predicted=50.0,
    )
    updated = await _record_outcome(
        db_session, ptype="sales", subject="S1", decision_id="p1", actual=45.0
    )
    assert updated == 1
    result = await mgr.list_predictions(resolved_only=True)
    assert result.total == 1
    assert result.items[0].actual_value == 45.0


@pytest.mark.asyncio
async def test_accuracy_and_comparison(db_session) -> None:
    mgr = _manager(db_session)
    for i, (pred, actual) in enumerate([(10.0, 9.0), (20.0, 19.0), (30.0, 31.0)]):
        await _record_prediction(
            db_session, ptype="profit", subject=f"S{i}", decision_type="ai_decision",
            decision_id="d1", predicted=pred,
        )
        await _record_outcome(
            db_session, ptype="profit", subject=f"S{i}", decision_id="d1", actual=actual
        )
    acc = await mgr.accuracy("profit")
    assert acc.summary["n"] == 3
    assert acc.summary["mae"] > 0
    assert len(acc.series) == 3
    cmp = await mgr.comparison()
    assert cmp and cmp[0].prediction_type == "profit"
    assert cmp[0].sample_size == 3


@pytest.mark.asyncio
async def test_scan_and_cycle_detects_and_recommends(db_session) -> None:
    mgr = _manager(db_session)
    # 5 over-predicting rules (profit) -> issue + rule_threshold/forecast recs.
    for i in range(5):
        await _record_prediction(
            db_session, ptype="profit", subject=f"r1-{i}", decision_type="rule",
            decision_id="r1", predicted=100.0 + i,
        )
        await _record_outcome(
            db_session, ptype="profit", subject=f"r1-{i}", decision_id="r1", actual=1.0
        )
    issues = await mgr.scan_issues()
    assert any(i["decision_id"] == "r1" for i in issues)

    run = await mgr.run_cycle()
    assert run.run_number == 1
    assert run.status == "completed"
    assert len(run.summary["issues"]) >= 1
    assert len(run.summary["recommendations"]) >= 1
    # rule_threshold + forecast_model recs generated for the failing profit rule
    targets = {r["target_type"] for r in run.summary["recommendations"]}
    assert "rule_threshold" in targets
    assert "forecast_model" in targets


@pytest.mark.asyncio
async def test_auto_tune_rule_threshold(db_session) -> None:
    mgr = _manager(db_session)
    pairs = [(0.9, 0), (0.8, 0), (0.7, 0), (0.3, 1), (0.2, 1), (0.1, 1)]
    for i, (score, actual) in enumerate(pairs):
        await _record_prediction(
            db_session, ptype="risk", subject=f"t-{i}", decision_type="rule",
            decision_id="r2", predicted=score,
            features=[{"name": "score", "value": score, "weight": 1.0}],
        )
        await _record_outcome(
            db_session, ptype="risk", subject=f"t-{i}", decision_id="r2", actual=float(actual)
        )
    result = await mgr.optimize_rule("r2")
    assert result.sample_size == 6
    assert result.proposed_threshold < 0.5
    assert result.applied is True

    run = await mgr.run_cycle()
    applied = [r for r in run.summary["recommendations"]
               if r["target_type"] == "rule_threshold" and r["status"] == "applied"]
    assert applied


@pytest.mark.asyncio
async def test_auto_reweight_feature(db_session) -> None:
    mgr = _manager(db_session)
    for i in range(5):
        x = float(i + 1)
        await _record_prediction(
            db_session, ptype="sales", subject=f"f-{i}", decision_type="ai_decision",
            decision_id="mdl1", predicted=10.0 + x,
            features=[{"name": "markup", "value": x, "weight": 1.0}],
        )
        await _record_outcome(
            db_session, ptype="sales", subject=f"f-{i}", decision_id="mdl1", actual=10.0
        )
    # explicit reweight
    res = await mgr.reweight(
        feature="markup", values=[1.0, 2.0, 3.0, 4.0, 5.0],
        errors=[1.0, 2.0, 3.0, 4.0, 5.0], current_weight=1.0,
    )
    assert res.suggested_weight < 1.0

    run = await mgr.run_cycle()
    reweight_recs = [r for r in run.summary["recommendations"]
                     if r["target_type"] == "feature_weight"]
    assert reweight_recs


@pytest.mark.asyncio
async def test_dashboard_and_runs(db_session) -> None:
    mgr = _manager(db_session)
    await _record_prediction(
        db_session, ptype="profit", subject="A", decision_type="rule",
        decision_id="r1", predicted=5.0,
    )
    await _record_outcome(
        db_session, ptype="profit", subject="A", decision_id="r1", actual=4.0
    )
    dash = await mgr.dashboard()
    assert dash.overall
    assert "profit" in dash.by_metric
    assert dash.models

    run = await mgr.run_cycle()
    runs = await mgr.list_runs()
    assert runs.total == 1
    fetched = await mgr.get_run(run.id)
    assert fetched.run_number == 1


@pytest.mark.asyncio
async def test_recommendations_lifecycle(db_session) -> None:
    mgr = _manager(db_session)
    for i in range(5):
        await _record_prediction(
            db_session, ptype="profit", subject=f"c-{i}", decision_type="rule",
            decision_id="c1", predicted=100.0 + i,
        )
        await _record_outcome(
            db_session, ptype="profit", subject=f"c-{i}", decision_id="c1", actual=1.0
        )
    await mgr.run_cycle()
    recs = await mgr.list_recommendations()
    assert recs.total >= 1
    rec = recs.items[0]
    updated = await mgr.update_recommendation(
        rec.id, type("U", (), {"status": "applied"})()
    )
    assert updated.status == "applied"


# ──────────────────────────────────────────────────────────────
# API tests
# ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_api_capabilities(client) -> None:
    resp = await client.get("/api/v1/learning/capabilities")
    assert resp.status_code == 200
    data = resp.json()
    assert "profit" in data["prediction_types"]
    assert "rule_threshold" in data["recommendation_targets"]
    assert "bad_rule" in data["issue_types"]


@pytest.mark.asyncio
async def test_api_record_and_accuracy(client) -> None:
    for i, (pred, actual) in enumerate([(10.0, 9.0), (20.0, 19.0), (30.0, 31.0)]):
        r = await client.post(
            "/api/v1/learning/predictions",
            json={"prediction_type": "profit", "subject_key": f"S{i}",
                  "decision_type": "ai_decision", "decision_id": "d1",
                  "predicted_value": pred},
        )
        assert r.status_code == 201
        await client.post(
            "/api/v1/learning/outcomes",
            json={"prediction_type": "profit", "subject_key": f"S{i}",
                  "decision_id": "d1", "actual_value": actual},
        )
    acc = await client.get("/api/v1/learning/accuracy", params={"prediction_type": "profit"})
    assert acc.status_code == 200
    assert acc.json()["summary"]["n"] == 3
    cmp = await client.get("/api/v1/learning/comparison")
    assert cmp.status_code == 200
    assert cmp.json()[0]["sample_size"] == 3


@pytest.mark.asyncio
async def test_api_dashboard_and_cycle(client) -> None:
    dash = await client.get("/api/v1/learning/dashboard")
    assert dash.status_code == 200
    run = await client.post("/api/v1/learning/cycle")
    assert run.status_code == 200
    assert run.json()["run_number"] == 1
    runs = await client.get("/api/v1/learning/runs")
    assert runs.json()["total"] == 1
    recs = await client.get("/api/v1/learning/recommendations")
    assert recs.status_code == 200


@pytest.mark.asyncio
async def test_api_scan_issues_and_report(client) -> None:
    for i in range(5):
        await client.post(
            "/api/v1/learning/predictions",
            json={"prediction_type": "profit", "subject_key": f"r{i}",
                  "decision_type": "rule", "decision_id": "r1", "predicted_value": 100.0 + i},
        )
        await client.post(
            "/api/v1/learning/outcomes",
            json={"prediction_type": "profit", "subject_key": f"r{i}",
                  "decision_id": "r1", "actual_value": 1.0},
        )
    issues = await client.post("/api/v1/learning/scan/issues")
    assert issues.status_code == 200
    assert any(i["decision_id"] == "r1" for i in issues.json())
    report = await client.post("/api/v1/learning/report")
    assert report.status_code == 200
    assert "Predicted vs actual" in report.json()["report"]


@pytest.mark.asyncio
async def test_api_optimize_rule(client) -> None:
    pairs = [(0.9, 0), (0.8, 0), (0.7, 0), (0.3, 1), (0.2, 1), (0.1, 1)]
    for i, (score, actual) in enumerate(pairs):
        await client.post(
            "/api/v1/learning/predictions",
            json={"prediction_type": "risk", "subject_key": f"t{i}",
                  "decision_type": "rule", "decision_id": "r2",
                  "predicted_value": score,
                  "features": [{"name": "score", "value": score, "weight": 1.0}]},
        )
        await client.post(
            "/api/v1/learning/outcomes",
            json={"prediction_type": "risk", "subject_key": f"t{i}",
                  "decision_id": "r2", "actual_value": float(actual)},
        )
    resp = await client.post(
        "/api/v1/learning/optimize/rule-threshold", params={"decision_id": "r2"}
    )
    assert resp.status_code == 200
    assert resp.json()["applied"] is True
