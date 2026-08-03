"""Pydantic schemas for the continuous-learning platform API."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class PredictionCreate(BaseModel):
    """Record a prediction (predicted value for a subject/metric)."""

    prediction_type: str = Field(..., description="profit | sales | roi | risk")
    subject_key: str = Field(..., max_length=128)
    decision_type: str = Field(..., description="rule | prompt | ai_decision | match | ranking")
    decision_id: str | None = Field(None, max_length=128)
    model_version: str = Field(default="1.0.0", max_length=32)
    predicted_value: float
    predicted_at: datetime | None = None
    features: list[dict[str, Any]] | None = Field(
        None, description="Feature snapshot: [{name, value, weight}]",
    )
    context: dict[str, Any] | None = None
    external_id: str | None = Field(None, max_length=128)


class OutcomeCreate(BaseModel):
    """Record the realised outcome for one or more matching predictions."""

    prediction_type: str
    subject_key: str
    actual_value: float
    decision_id: str | None = None
    model_version: str | None = None
    external_id: str | None = None
    outcome_at: datetime | None = None


class PredictionRead(BaseModel):
    """A stored prediction with its realised outcome (if any)."""

    id: UUID
    prediction_type: str
    subject_key: str
    decision_type: str
    decision_id: str | None
    model_version: str
    predicted_value: float
    actual_value: float | None
    predicted_at: datetime | None
    outcome_at: datetime | None
    features: list[dict[str, Any]] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)
    external_id: str | None
    created_at: datetime

    @classmethod
    def from_row(cls, row) -> PredictionRead:
        return cls(
            id=row.id,
            prediction_type=row.prediction_type,
            subject_key=row.subject_key,
            decision_type=row.decision_type,
            decision_id=row.decision_id,
            model_version=row.model_version,
            predicted_value=row.predicted_value,
            actual_value=row.actual_value,
            predicted_at=row.predicted_at,
            outcome_at=row.outcome_at,
            features=_loads_list(row.features_json),
            context=_loads_dict(row.context_json),
            external_id=row.external_id,
            created_at=row.created_at,
        )


class PredictionList(BaseModel):
    items: list[PredictionRead]
    total: int


class ComparisonRead(BaseModel):
    """Predicted vs actual comparison for one metric."""

    prediction_type: str
    sample_size: int
    predicted_mean: float
    actual_mean: float
    mae: float
    bias: float
    correlation: float
    directional_accuracy: float


class AccuracyRead(BaseModel):
    """Accuracy summary + rolling series for one metric/model."""

    prediction_type: str
    model_version: str | None
    summary: dict[str, float]
    drift: dict[str, Any]
    series: list[dict[str, Any]]


class ModelAccuracy(BaseModel):
    """Accuracy summary for a single model version (dashboard)."""

    model_version: str
    prediction_type: str
    decision_type: str | None
    sample_size: int
    mae: float
    mape: float
    bias: float
    directional_accuracy: float
    severity: float


class IssueRead(BaseModel):
    """An automatically detected issue (not yet persisted)."""

    issue_type: str
    decision_type: str
    decision_id: str
    model_version: str | None
    prediction_type: str | None
    sample_size: int
    mae: float
    bias: float
    directional_accuracy: float
    correlation: float
    severity: float
    mode: str


class RecommendationRead(BaseModel):
    """A persisted improvement recommendation."""

    id: UUID
    run_id: UUID | None
    target_type: str
    target_id: str | None
    issue_type: str
    severity: float
    confidence: float
    current_value: float | None
    proposed_value: float | None
    proposed_action: str
    explanation: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    status: str
    model_version: str | None
    created_at: datetime

    @classmethod
    def from_row(cls, row) -> RecommendationRead:
        return cls(
            id=row.id,
            run_id=row.run_id,
            target_type=row.target_type,
            target_id=row.target_id,
            issue_type=row.issue_type,
            severity=row.severity,
            confidence=row.confidence,
            current_value=row.current_value,
            proposed_value=row.proposed_value,
            proposed_action=row.proposed_action,
            explanation=row.explanation,
            evidence=_loads_dict(row.evidence_json),
            status=row.status,
            model_version=row.model_version,
            created_at=row.created_at,
        )


class RecommendationList(BaseModel):
    items: list[RecommendationRead]
    total: int


class RecommendationUpdate(BaseModel):
    status: str | None = Field(None, description="open | applied | dismissed")


class RunRead(BaseModel):
    """A versioned continuous-learning cycle run."""

    id: UUID
    run_number: int
    status: str
    params_snapshot: dict[str, Any] = Field(default_factory=dict)
    summary: dict[str, Any] = Field(default_factory=dict)
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime

    @classmethod
    def from_row(cls, row) -> RunRead:
        return cls(
            id=row.id,
            run_number=row.run_number,
            status=row.status,
            params_snapshot=_loads_dict(row.params_snapshot_json),
            summary=_loads_dict(row.summary_json),
            started_at=row.started_at,
            completed_at=row.completed_at,
            created_at=row.created_at,
        )


class RunList(BaseModel):
    items: list[RunRead]
    total: int


class RuleTuneResult(BaseModel):
    """Result of deterministic rule-threshold optimisation."""

    decision_id: str
    current_threshold: float
    proposed_threshold: float
    current_score: float
    proposed_score: float
    improvement: float
    sample_size: int
    tp: int
    fp: int
    tn: int
    fn: int
    applied: bool


class ReweightResult(BaseModel):
    """Result of feature re-weighting on supplied data."""

    feature: str
    correlation: float
    current_weight: float
    suggested_weight: float
    change_pct: float
    explanation: str


class LearningCapabilities(BaseModel):
    """What the platform supports."""

    enabled: bool
    prediction_types: list[str]
    decision_types: list[str]
    recommendation_targets: list[str]
    issue_types: list[str]
    metrics: list[str]
    code_version: str


class LearningStats(BaseModel):
    total_predictions: int
    resolved_predictions: int
    unresolved_predictions: int
    open_recommendations: int
    runs_completed: int
    last_run_number: int | None
    by_prediction_type: dict[str, int]


class DashboardRead(BaseModel):
    """Model-accuracy-over-time dashboard."""

    overall: dict[str, float]
    by_metric: dict[str, dict[str, float]]
    models: list[ModelAccuracy]
    open_recommendations: int
    last_run_number: int | None
    series: dict[str, list[dict[str, Any]]]


def _loads_list(s: str | None) -> list[dict[str, Any]]:
    import json

    if not s:
        return []
    try:
        value = json.loads(s)
        return value if isinstance(value, list) else []
    except (ValueError, TypeError):
        return []


def _loads_dict(s: str | None) -> dict[str, Any]:
    import json

    if not s:
        return {}
    try:
        value = json.loads(s)
        return value if isinstance(value, dict) else {}
    except (ValueError, TypeError):
        return {}
