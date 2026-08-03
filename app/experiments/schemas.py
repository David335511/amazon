"""Pydantic schemas for the experimentation API."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.experiments.errors import ExperimentValidationError
from app.experiments.models import (
    Assignment,
    Experiment,
    ExperimentReport,
    ExperimentType,
    Observation,
    PrimaryMetric,
    Variant,
)

# Default metric per experiment type.
TYPE_DEFAULT_METRIC: dict[str, str] = {
    ExperimentType.AB.value: PrimaryMetric.CONVERSION.value,
    ExperimentType.FEATURE_FLAG.value: PrimaryMetric.CONVERSION.value,
    ExperimentType.PROMPT.value: PrimaryMetric.CONVERSION.value,
    ExperimentType.RULE.value: PrimaryMetric.CONVERSION.value,
    ExperimentType.SCORING_COMPARISON.value: PrimaryMetric.PRECISION.value,
    ExperimentType.LLM_COMPARISON.value: PrimaryMetric.ACCURACY.value,
    ExperimentType.SUPPLIER_COMPARISON.value: PrimaryMetric.PROFIT.value,
    ExperimentType.PREDICTION_COMPARISON.value: PrimaryMetric.PRECISION.value,
}


# ──────────────────────────────────────────────────────────────
# Variants
# ──────────────────────────────────────────────────────────────


class VariantCreate(BaseModel):
    """Add a variant to an experiment."""

    key: str = Field(min_length=1, max_length=64)
    label: str = Field(default="", max_length=255)
    parameters: dict[str, Any] = Field(default_factory=dict)
    is_control: bool = False


class VariantRead(BaseModel):
    """A variant as exposed by the API."""

    id: UUID
    key: str
    label: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    is_control: bool

    @classmethod
    def from_row(cls, row: Variant) -> VariantRead:
        from app.experiments.manager import _loads

        return cls(
            id=row.id,
            key=row.key,
            label=row.label,
            parameters=_loads(row.parameters_json),
            is_control=row.is_control,
        )


# ──────────────────────────────────────────────────────────────
# Experiments
# ──────────────────────────────────────────────────────────────


class ExperimentCreate(BaseModel):
    """Create an experiment (draft)."""

    name: str = Field(min_length=1, max_length=255)
    experiment_type: ExperimentType
    description: str | None = None
    hypothesis: str | None = None
    primary_metric: PrimaryMetric | None = None  # defaults by type
    alpha: float = Field(default=0.05, gt=0, lt=1)
    min_sample_size: int = Field(default=100, ge=1)
    seed: int = Field(default=42, ge=0)
    control_variant_key: str | None = None
    variants: list[VariantCreate] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ExperimentValidationError("Experiment name cannot be blank")
        return v


class ExperimentUpdate(BaseModel):
    """Update mutable experiment fields (draft only)."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    hypothesis: str | None = None
    control_variant_key: str | None = None


class ExperimentRead(BaseModel):
    """An experiment as exposed by the API."""

    id: UUID
    name: str
    experiment_type: str
    status: str
    description: str | None
    hypothesis: str | None
    primary_metric: str
    alpha: float
    min_sample_size: int
    seed: int
    control_variant_key: str | None
    code_version: str | None
    config_snapshot: dict[str, Any] = Field(default_factory=dict)
    started_at: datetime | None
    stopped_at: datetime | None
    created_at: datetime
    variant_count: int = 0
    assignment_count: int = 0
    observation_count: int = 0

    @classmethod
    def from_row(
        cls,
        row: Experiment,
        variant_count: int = 0,
        assignment_count: int = 0,
        observation_count: int = 0,
    ) -> ExperimentRead:
        from app.experiments.manager import _loads

        return cls(
            id=row.id,
            name=row.name,
            experiment_type=row.experiment_type,
            status=row.status,
            description=row.description,
            hypothesis=row.hypothesis,
            primary_metric=row.primary_metric,
            alpha=row.alpha,
            min_sample_size=row.min_sample_size,
            seed=row.seed,
            control_variant_key=row.control_variant_key,
            code_version=row.code_version,
            config_snapshot=_loads(row.config_snapshot_json),
            started_at=_as_aware(row.started_at),
            stopped_at=_as_aware(row.stopped_at),
            created_at=row.created_at,
            variant_count=variant_count,
            assignment_count=assignment_count,
            observation_count=observation_count,
        )


class ExperimentList(BaseModel):
    """Paginated experiments."""

    items: list[ExperimentRead]
    total: int


class ExperimentDetail(BaseModel):
    """Experiment + its variants + current live results."""

    experiment: ExperimentRead
    variants: list[VariantRead]
    results: dict[str, Any]


# ──────────────────────────────────────────────────────────────
# Assignment / observations
# ──────────────────────────────────────────────────────────────


class AssignmentRequest(BaseModel):
    """Assign a subject to a variant (deterministic by seed + subject)."""

    subject_key: str = Field(min_length=1, max_length=255)


class AssignmentRead(BaseModel):
    """The resulting variant assignment."""

    id: UUID
    experiment_id: UUID
    variant_id: UUID
    variant_key: str
    subject_key: str
    assigned_at: datetime

    @classmethod
    def from_rows(cls, assignment: Assignment, variant_key: str) -> AssignmentRead:
        return cls(
            id=assignment.id,
            experiment_id=assignment.experiment_id,
            variant_id=assignment.variant_id,
            variant_key=variant_key,
            subject_key=assignment.subject_key,
            assigned_at=assignment.created_at,
        )


class ObservationCreate(BaseModel):
    """Record one outcome for a subject (auto-assigns if not yet assigned)."""

    subject_key: str = Field(min_length=1, max_length=255)
    outcome: bool = False
    profit: float | None = None
    roi: float | None = None
    value: float | None = None
    predicted: bool | None = None
    ground_truth: bool | None = None


class ObservationBatch(BaseModel):
    """Record many outcomes at once (bounded by config.max_batch_size)."""

    observations: list[ObservationCreate] = Field(min_length=1)


class ObservationRead(BaseModel):
    """A recorded observation."""

    id: UUID
    experiment_id: UUID
    variant_id: UUID
    variant_key: str
    subject_key: str
    outcome: bool
    profit: float | None
    roi: float | None
    value: float | None
    predicted: bool | None
    ground_truth: bool | None
    recorded_at: datetime

    @classmethod
    def from_rows(cls, row: Observation, variant_key: str) -> ObservationRead:
        return cls(
            id=row.id,
            experiment_id=row.experiment_id,
            variant_id=row.variant_id,
            variant_key=variant_key,
            subject_key=row.subject_key,
            outcome=row.outcome,
            profit=row.profit,
            roi=row.roi,
            value=row.value,
            predicted=row.predicted,
            ground_truth=row.ground_truth,
            recorded_at=_as_aware(row.recorded_at),
        )


class ObservationList(BaseModel):
    """Paginated observations."""

    items: list[ObservationRead]
    total: int


# ──────────────────────────────────────────────────────────────
# Results / reports
# ──────────────────────────────────────────────────────────────


class VariantResult(BaseModel):
    """Live aggregated stats for one variant."""

    key: str
    n: int
    conversion: float
    mean_profit: float
    mean_roi: float
    mean_value: float
    precision: float | None = None
    recall: float | None = None
    false_positives: int | None = None
    false_negatives: int | None = None


class ResultsRead(BaseModel):
    """Live per-variant results + current winner for an experiment."""

    experiment_id: UUID
    metric: str
    alpha: float
    total_observations: int
    min_sample_size: int
    sample_complete: bool
    variants: list[VariantResult]
    winner: dict[str, Any]


class WinnerRead(BaseModel):
    """The current winner + confidence."""

    experiment_id: UUID
    winner_key: str | None
    winner_label: str | None
    confidence: float | None
    significant: bool
    p_value: float | None
    metric: str
    leading_key: str | None


class ReportRead(BaseModel):
    """A generated experiment report."""

    id: UUID
    experiment_id: UUID
    winner_variant_key: str | None
    winner_label: str | None
    confidence: float | None
    metric: str
    profit_impact: float | None
    roi_impact: float | None
    precision: float | None
    recall: float | None
    false_positives: int | None
    false_negatives: int | None
    report_body: str
    params_snapshot: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

    @classmethod
    def from_row(cls, row: ExperimentReport) -> ReportRead:
        from app.experiments.manager import _loads

        return cls(
            id=row.id,
            experiment_id=row.experiment_id,
            winner_variant_key=row.winner_variant_key,
            winner_label=row.winner_label,
            confidence=row.confidence,
            metric=row.metric,
            profit_impact=row.profit_impact,
            roi_impact=row.roi_impact,
            precision=row.precision,
            recall=row.recall,
            false_positives=row.false_positives,
            false_negatives=row.false_negatives,
            report_body=row.report_body,
            params_snapshot=_loads(row.params_snapshot_json),
            created_at=row.created_at,
        )


class ReportList(BaseModel):
    """Paginated reports for an experiment."""

    items: list[ReportRead]
    total: int


# ──────────────────────────────────────────────────────────────
# Platform-level
# ──────────────────────────────────────────────────────────────


class ExperimentCapabilities(BaseModel):
    """Which experiment types / metrics / stats this deployment supports."""

    enabled: bool
    experiment_types: list[str]
    metrics: list[str]
    statuses: list[str]
    default_alpha: float
    default_min_sample_size: int
    code_version: str
    track: list[str]  # winner, confidence, profit impact, ROI, precision, recall, FP, FN


class ExperimentStats(BaseModel):
    """Platform-wide aggregation."""

    total_experiments: int
    by_type: dict[str, int]
    by_status: dict[str, int]
    total_variants: int
    total_assignments: int
    total_observations: int
    total_reports: int


class SimulateRequest(BaseModel):
    """Plan a prospective A/B test deterministically."""

    n: int = Field(default=100, ge=1)
    base_conversion: float = Field(default=0.1, ge=0, le=1)
    effect_size: float = Field(default=0.03, ge=-1, le=1)
    seed: int = Field(default=42, ge=0)
    alpha: float = Field(default=0.05, gt=0, lt=1)


def _as_aware(dt: datetime | None) -> datetime | None:
    if dt is None or dt.tzinfo is not None:
        return dt
    return dt.replace(tzinfo=UTC)
