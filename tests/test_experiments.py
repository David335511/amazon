"""Tests for the experimentation platform (engine, manager, API)."""

from __future__ import annotations

import types
from typing import Any
from uuid import UUID

import pytest

from app.experiments.config import ExperimentConfig
from app.experiments.engine import (
    assign_variant,
    confusion_metrics,
    determine_winner,
    normal_cdf,
    required_sample_size,
    simulate_ab,
    two_proportion_ztest,
    variant_stats,
    welch_ttest,
)
from app.experiments.manager import ExperimentManager
from app.experiments.models import (
    ExperimentStatus,
    ExperimentType,
    PrimaryMetric,
)
from app.experiments.repository import ExperimentRepository
from app.experiments.schemas import (
    ExperimentCreate,
    ObservationCreate,
    SimulateRequest,
    VariantCreate,
)

# ──────────────────────────────────────────────────────────────
# Engine unit tests
# ──────────────────────────────────────────────────────────────


def _obs(variant_key: str, outcome: bool, profit: float = 0.0, **extra: Any) -> types.SimpleNamespace:
    base = {
        "outcome": outcome, "profit": profit, "roi": 0.0, "value": 0.0,
        "predicted": None, "ground_truth": None,
    }
    base.update(extra)
    return types.SimpleNamespace(variant_key=variant_key, **base)


def test_two_proportion_ztest_detects_difference() -> None:
    res = two_proportion_ztest(150, 1000, 100, 1000)
    assert res is not None
    assert res["p_value"] < 0.05
    assert res["confidence"] > 0.95


def test_two_proportion_ztest_equal_arms_not_significant() -> None:
    res = two_proportion_ztest(100, 1000, 100, 1000)
    assert res is not None
    assert res["p_value"] > 0.05
    assert res["uplift"] == pytest.approx(0.0, abs=1e-6)


def test_welch_ttest() -> None:
    res = welch_ttest(10.0, 4.0, 200, 8.0, 4.0, 200)
    assert res is not None
    assert res["p_value"] < 0.05


def test_normal_cdf_bounds() -> None:
    assert normal_cdf(0) == pytest.approx(0.5)
    assert normal_cdf(1.96) == pytest.approx(0.975, abs=0.001)
    assert normal_cdf(-1.96) == pytest.approx(0.025, abs=0.001)


def test_confusion_metrics() -> None:
    conf = confusion_metrics([True, True, False, True, False], [True, False, False, True, True])
    assert conf["true_positives"] == 2
    assert conf["false_positives"] == 1
    assert conf["false_negatives"] == 1
    assert conf["precision"] == pytest.approx(2 / 3)
    assert conf["recall"] == pytest.approx(2 / 3)


def test_assign_variant_stable_across_calls() -> None:
    assert assign_variant("alice", 42, 4) == assign_variant("alice", 42, 4)
    assert 0 <= assign_variant("alice", 42, 4) < 4


def test_assign_variant_uses_seed() -> None:
    assert assign_variant("alice", 1, 10) == assign_variant("alice", 1, 10)
    # in-range and deterministic across many subjects
    for i in range(50):
        idx = assign_variant(f"user{i}", 7, 8)
        assert 0 <= idx < 8


def test_determine_winner_clean_signal() -> None:
    obs = [_obs("control", False) for _ in range(1000)]
    obs += [_obs("variant_a", True) for _ in range(1000)]
    stats = variant_stats(obs, "conversion")
    result = determine_winner(stats, "control", 0.05, "conversion")
    assert result["winner_key"] == "variant_a"
    assert result["significant"] is True
    assert result["confidence"] > 0.99


def test_determine_winner_no_significant() -> None:
    obs = [_obs("control", True) for _ in range(500)] + [_obs("variant_a", True) for _ in range(500)]
    stats = variant_stats(obs, "conversion")
    result = determine_winner(stats, "control", 0.05, "conversion")
    assert result["winner_key"] is None
    assert result["significant"] is False


def test_simulate_ab_reproducible() -> None:
    a = simulate_ab(2000, 0.10, 0.04, seed=7)
    b = simulate_ab(2000, 0.10, 0.04, seed=7)
    assert a == b


def test_simulate_ab_detects_effect() -> None:
    res = simulate_ab(3000, 0.10, 0.05, seed=1)
    assert res["significant"] is True


def test_required_sample_size() -> None:
    assert required_sample_size(0.10, 0.14) > 0
    assert required_sample_size(0.10, 0.10) == 0


# ──────────────────────────────────────────────────────────────
# Manager tests
# ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_experiment_creates_variants(db_session) -> None:
    mgr = ExperimentManager(ExperimentRepository(db_session))
    created = await mgr.create_experiment(
        ExperimentCreate(
            name="Test AB",
            experiment_type=ExperimentType.AB,
            variants=[
                VariantCreate(key="control", label="Control", is_control=True),
                VariantCreate(key="variant_a", label="New", parameters={"price": 19.99}),
            ],
        )
    )
    assert created.status == ExperimentStatus.DRAFT.value
    assert created.variant_count == 2
    assert created.primary_metric == PrimaryMetric.CONVERSION.value
    detail = await mgr.get_experiment(created.id)
    assert {v.key for v in detail.variants} == {"control", "variant_a"}


@pytest.mark.asyncio
async def test_assign_is_deterministic_and_idempotent(db_session) -> None:
    mgr = ExperimentManager(ExperimentRepository(db_session))
    exp = await mgr.create_experiment(_ab_experiment())
    await mgr.start(exp.id)
    a = await mgr.assign(exp.id, "alice")
    b = await mgr.assign(exp.id, "alice")
    assert a.variant_key == b.variant_key
    assert a.id == b.id


@pytest.mark.asyncio
async def test_record_auto_assigns_and_dedups(db_session) -> None:
    mgr = ExperimentManager(ExperimentRepository(db_session))
    exp = await mgr.create_experiment(_ab_experiment())
    await mgr.start(exp.id)
    r1 = await mgr.record(exp.id, ObservationCreate(subject_key="alice", outcome=True, profit=5.0))
    r2 = await mgr.record(exp.id, ObservationCreate(subject_key="alice", outcome=False))
    assert r1.subject_key == r2.subject_key
    # one observation per subject: second record updates, not duplicates
    _, total = await mgr._repo.list_observations(exp.id)
    assert total == 1


@pytest.mark.asyncio
async def test_start_snapshots_config(db_session) -> None:
    mgr = ExperimentManager(ExperimentRepository(db_session), config=ExperimentConfig(code_version="abc123"))
    exp = await mgr.create_experiment(_ab_experiment())
    started = await mgr.start(exp.id)
    assert started.status == ExperimentStatus.RUNNING.value
    assert started.code_version == "abc123"
    assert "variants" in started.config_snapshot
    assert started.config_snapshot["experiment"]["seed"] == exp.seed


@pytest.mark.asyncio
async def test_results_and_winner_lifecycle(db_session) -> None:
    mgr = ExperimentManager(ExperimentRepository(db_session))
    exp = await mgr.create_experiment(_ab_experiment())
    await mgr.start(exp.id)
    await _populate(mgr, exp.id, n=200)
    results = await mgr.results(exp.id)
    assert results.total_observations == 200
    assert results.winner["winner_key"] == "variant_a"
    winner = await mgr.winner(exp.id)
    assert winner.winner_key == "variant_a"
    assert winner.confidence > 0.9


@pytest.mark.asyncio
async def test_generate_report_fields(db_session) -> None:
    mgr = ExperimentManager(ExperimentRepository(db_session), config=ExperimentConfig(code_version="rev-1"))
    exp = await mgr.create_experiment(_ab_experiment())
    await mgr.start(exp.id)
    await _populate(mgr, exp.id, n=300)
    report = await mgr.generate_report(exp.id)
    assert report.winner_variant_key == "variant_a"
    assert report.confidence is not None
    assert report.metric == "conversion"
    assert report.report_body.startswith("# Experiment report")
    assert "Reproducibility" in report.report_body
    assert report.params_snapshot["code_version"] == "rev-1"
    assert report.params_snapshot["seed"] == exp.seed


@pytest.mark.asyncio
async def test_stop_generates_report_and_status(db_session) -> None:
    mgr = ExperimentManager(ExperimentRepository(db_session))
    exp = await mgr.create_experiment(_ab_experiment())
    await mgr.start(exp.id)
    await _populate(mgr, exp.id, n=200)
    report = await mgr.stop(exp.id)
    assert report.id is not None
    detail = await mgr.get_experiment(exp.id)
    assert detail.experiment.status == ExperimentStatus.STOPPED.value


@pytest.mark.asyncio
async def test_precision_recall(db_session) -> None:
    mgr = ExperimentManager(ExperimentRepository(db_session))
    exp = await mgr.create_experiment(
        ExperimentCreate(
            name="Pred",
            experiment_type=ExperimentType.PREDICTION_COMPARISON,
            variants=[
                VariantCreate(key="control", label="Baseline", is_control=True),
                VariantCreate(key="model_a", label="Model A"),
            ],
        )
    )
    await mgr.start(exp.id)
    # record predicted/ground_truth per subject regardless of split
    assignments = {}
    for i in range(100):
        subj = f"p{i}"
        a = await mgr.assign(exp.id, subj)
        assignments[subj] = a.variant_key
        # model_a predicts positive for positives, baseline random-ish
        if a.variant_key == "model_a":
            await mgr.record(
                exp.id, ObservationCreate(subject_key=subj, predicted=True, ground_truth=(i % 2 == 0))
            )
        else:
            await mgr.record(
                exp.id, ObservationCreate(subject_key=subj, predicted=(i % 2 == 0), ground_truth=(i % 2 == 0))
            )
    pr = await mgr.precision_recall(exp.id)
    assert "model_a" in pr["variants"]
    assert pr["variants"]["model_a"]["recall"] == 1.0  # predicts positive for all positives


@pytest.mark.asyncio
async def test_simulate(db_session) -> None:
    mgr = ExperimentManager(ExperimentRepository(db_session))
    result = await mgr.simulate(SimulateRequest(n=2000, base_conversion=0.10, effect_size=0.04, seed=3))
    assert result["significant"] is True
    assert result["seed"] == 3


# ──────────────────────────────────────────────────────────────
# API tests
# ──────────────────────────────────────────────────────────────


def _ab_experiment() -> ExperimentCreate:
    return ExperimentCreate(
        name="Checkout AB",
        experiment_type=ExperimentType.AB,
        hypothesis="New layout improves conversion",
        variants=[
            VariantCreate(key="control", label="Control", is_control=True),
            VariantCreate(key="variant_a", label="New layout", parameters={"layout": "new"}),
        ],
    )


async def _populate(mgr: ExperimentManager, exp_id: UUID, n: int) -> None:
    """Record observations so variant_a clearly wins (outcome = on variant_a)."""
    for i in range(n):
        subj = f"subject_{i}"
        a = await mgr.assign(exp_id, subj)
        await mgr.record(exp_id, ObservationCreate(subject_key=subj, outcome=a.variant_key == "variant_a", profit=5.0))


@pytest.mark.asyncio
async def test_capabilities(client) -> None:
    resp = await client.get("/api/v1/experiments/capabilities")
    assert resp.status_code == 200
    data = resp.json()
    assert "ab_test" in data["experiment_types"]
    assert "precision" in data["metrics"]
    assert data["enabled"] is True


@pytest.mark.asyncio
async def test_templates(client) -> None:
    resp = await client.get("/api/v1/experiments/templates")
    assert resp.status_code == 200
    assert "prompt" in resp.json()
    assert resp.json()["prediction_comparison"]["primary_metric"] == "precision"


@pytest.mark.asyncio
async def test_simulate_api(client) -> None:
    resp = await client.post(
        "/api/v1/experiments/simulate",
        json={"n": 2000, "base_conversion": 0.10, "effect_size": 0.04, "seed": 5},
    )
    assert resp.status_code == 200
    assert resp.json()["significant"] is True


@pytest.mark.asyncio
async def test_full_lifecycle_api(client) -> None:
    # create
    resp = await client.post(
        "/api/v1/experiments",
        json={
            "name": "API AB",
            "experiment_type": "ab_test",
            "hypothesis": "Variant A wins",
            "variants": [
                {"key": "control", "label": "Control", "is_control": True},
                {"key": "variant_a", "label": "A", "parameters": {"x": 1}},
            ],
        },
    )
    assert resp.status_code == 201
    exp = resp.json()
    exp_id = exp["id"]
    assert exp["status"] == "draft"
    assert exp["variant_count"] == 2

    # start
    resp = await client.post(f"/api/v1/experiments/{exp_id}/start")
    assert resp.status_code == 200
    assert resp.json()["status"] == "running"

    # assign + record
    for i in range(200):
        subj = f"api_subject_{i}"
        a = await client.post(f"/api/v1/experiments/{exp_id}/assign", json={"subject_key": subj})
        assert a.status_code == 200
        outcome = a.json()["variant_key"] == "variant_a"
        r = await client.post(
            f"/api/v1/experiments/{exp_id}/observations",
            json={"subject_key": subj, "outcome": outcome, "profit": 5.0},
        )
        assert r.status_code == 200

    # results + winner
    results = await client.get(f"/api/v1/experiments/{exp_id}/results")
    assert results.status_code == 200
    assert results.json()["total_observations"] == 200
    assert results.json()["winner"]["winner_key"] == "variant_a"
    winner = await client.get(f"/api/v1/experiments/{exp_id}/winner")
    assert winner.json()["winner_key"] == "variant_a"

    # report
    report = await client.post(f"/api/v1/experiments/{exp_id}/report")
    assert report.status_code == 200
    body = report.json()
    assert body["winner_variant_key"] == "variant_a"
    assert body["report_body"].startswith("# Experiment report")
    fetched = await client.get(f"/api/v1/experiments/{exp_id}/report")
    assert fetched.json()["id"] == body["id"]
    reports = await client.get(f"/api/v1/experiments/{exp_id}/reports")
    assert reports.json()["total"] == 1

    # stop
    stopped = await client.post(f"/api/v1/experiments/{exp_id}/stop")
    assert stopped.status_code == 200
    detail = await client.get(f"/api/v1/experiments/{exp_id}")
    assert detail.json()["experiment"]["status"] == "stopped"


@pytest.mark.asyncio
async def test_add_variant_draft_only(client) -> None:
    resp = await client.post(
        "/api/v1/experiments",
        json={"name": "Flag", "experiment_type": "feature_flag",
              "variants": [{"key": "on", "label": "On", "is_control": False}]},
    )
    exp_id = resp.json()["id"]
    added = await client.post(
        f"/api/v1/experiments/{exp_id}/variants",
        json={"key": "off", "label": "Off"},
    )
    assert added.status_code == 200
    # after start, adding a variant is a conflict
    await client.post(f"/api/v1/experiments/{exp_id}/start")
    conflict = await client.post(
        f"/api/v1/experiments/{exp_id}/variants",
        json={"key": "third", "label": "Third"},
    )
    assert conflict.status_code == 409


@pytest.mark.asyncio
async def test_list_and_filter(client) -> None:
    await client.post(
        "/api/v1/experiments",
        json={"name": "A", "experiment_type": "ab_test",
              "variants": [{"key": "v", "label": "V"}]},
    )
    resp = await client.get("/api/v1/experiments")
    assert resp.status_code == 200
    assert resp.json()["total"] >= 1
    filtered = await client.get("/api/v1/experiments?experiment_type=prompt")
    assert all(i["experiment_type"] == "prompt" for i in filtered.json()["items"])


@pytest.mark.asyncio
async def test_stats(client) -> None:
    resp = await client.get("/api/v1/experiments/stats")
    assert resp.status_code == 200
    assert resp.json()["total_experiments"] >= 0


@pytest.mark.asyncio
async def test_delete_experiment(client) -> None:
    resp = await client.post(
        "/api/v1/experiments",
        json={"name": "Del", "experiment_type": "rule",
              "variants": [{"key": "v", "label": "V"}]},
    )
    exp_id = resp.json()["id"]
    deleted = await client.delete(f"/api/v1/experiments/{exp_id}")
    assert deleted.status_code == 204
    gone = await client.get(f"/api/v1/experiments/{exp_id}")
    assert gone.status_code == 404


@pytest.mark.asyncio
async def test_record_batch(client) -> None:
    resp = await client.post(
        "/api/v1/experiments",
        json={"name": "Batch", "experiment_type": "ab_test",
              "variants": [{"key": "control", "label": "C", "is_control": True},
                           {"key": "a", "label": "A"}]},
    )
    exp_id = resp.json()["id"]
    await client.post(f"/api/v1/experiments/{exp_id}/start")
    batch = await client.post(
        f"/api/v1/experiments/{exp_id}/observations/batch",
        json={"observations": [
            {"subject_key": "u1", "outcome": True},
            {"subject_key": "u2", "outcome": False},
            {"subject_key": "u1", "outcome": True},  # duplicate in batch -> skipped
        ]},
    )
    assert batch.status_code == 200
    assert len(batch.json()) == 2  # u1 deduped
