"""ORM models for the experimentation platform.

Four tables:

- ``experiments`` — an experiment (A/B, feature flag, prompt, rule, scoring /
  LLM / supplier / prediction comparison) with its statistical config, seed,
  and reproducibility snapshot (config + code version at start).
- ``experiment_variants`` — one arm of an experiment (key, label, the exact
  parameters tested, whether it is the control).
- ``experiment_assignments`` — which variant a subject was deterministically
  assigned to (unique per experiment + subject).
- ``experiment_observations`` — one outcome per subject (conversion, profit,
  ROI, value, predicted vs ground truth). Unique per experiment + subject.
- ``experiment_reports`` — every generated report with its winner, confidence,
  profit/ROI impact, precision/recall/FP/FN and reproducibility snapshot.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.models.base import Base, TimestampMixin, UUIDMixin


class ExperimentType(StrEnum):
    """What is being compared across variants."""

    AB = "ab_test"
    FEATURE_FLAG = "feature_flag"
    PROMPT = "prompt"
    RULE = "rule"
    SCORING_COMPARISON = "scoring_comparison"
    LLM_COMPARISON = "llm_comparison"
    SUPPLIER_COMPARISON = "supplier_comparison"
    PREDICTION_COMPARISON = "prediction_comparison"


class ExperimentStatus(StrEnum):
    """Lifecycle of an experiment."""

    DRAFT = "draft"
    RUNNING = "running"
    STOPPED = "stopped"
    ARCHIVED = "archived"


class PrimaryMetric(StrEnum):
    """The metric an experiment's winner is decided on."""

    CONVERSION = "conversion"
    PROFIT = "profit"
    ROI = "roi"
    VALUE = "value"
    ACCURACY = "accuracy"
    PRECISION = "precision"
    RECALL = "recall"
    F1 = "f1"


class Experiment(Base, UUIDMixin, TimestampMixin):
    """A single experiment and its statistical configuration."""

    __tablename__ = "experiments"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    experiment_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ExperimentStatus.DRAFT.value, index=True,
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    hypothesis: Mapped[str | None] = mapped_column(Text, nullable=True)
    primary_metric: Mapped[str] = mapped_column(
        String(16), nullable=False, default=PrimaryMetric.CONVERSION.value,
    )
    alpha: Mapped[float] = mapped_column(Float, nullable=False, default=0.05)
    min_sample_size: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    seed: Mapped[int] = mapped_column(Integer, nullable=False, default=42, index=True)
    control_variant_key: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Reproducibility snapshot captured when the experiment is started.
    config_snapshot_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    code_version: Mapped[str | None] = mapped_column(String(128), nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Variant(Base, UUIDMixin, TimestampMixin):
    """One arm of an experiment."""

    __tablename__ = "experiment_variants"

    experiment_id: Mapped[object] = mapped_column(
        ForeignKey("experiments.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    parameters_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_control: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class Assignment(Base, UUIDMixin, TimestampMixin):
    """Deterministic variant assignment for a subject."""

    __tablename__ = "experiment_assignments"
    __table_args__ = (
        UniqueConstraint("experiment_id", "subject_key", name="uq_assignments_exp_subject"),
    )

    experiment_id: Mapped[object] = mapped_column(
        ForeignKey("experiments.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    variant_id: Mapped[object] = mapped_column(
        ForeignKey("experiment_variants.id", ondelete="CASCADE"), nullable=False,
    )
    subject_key: Mapped[str] = mapped_column(String(255), nullable=False, index=True)


class Observation(Base, UUIDMixin, TimestampMixin):
    """A single outcome recorded for a subject in an experiment."""

    __tablename__ = "experiment_observations"
    __table_args__ = (
        UniqueConstraint("experiment_id", "subject_key", name="uq_observations_exp_subject"),
    )

    experiment_id: Mapped[object] = mapped_column(
        ForeignKey("experiments.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    variant_id: Mapped[object] = mapped_column(
        ForeignKey("experiment_variants.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    subject_key: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    outcome: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    profit: Mapped[float | None] = mapped_column(Float, nullable=True)
    roi: Mapped[float | None] = mapped_column(Float, nullable=True)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    predicted: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    ground_truth: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True,
    )


class ExperimentReport(Base, UUIDMixin, TimestampMixin):
    """A generated report for an experiment (winner, impact, quality, snapshot)."""

    __tablename__ = "experiment_reports"

    experiment_id: Mapped[object] = mapped_column(
        ForeignKey("experiments.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    winner_variant_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    winner_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    metric: Mapped[str] = mapped_column(String(16), nullable=False)
    profit_impact: Mapped[float | None] = mapped_column(Float, nullable=True)
    roi_impact: Mapped[float | None] = mapped_column(Float, nullable=True)
    precision: Mapped[float | None] = mapped_column(Float, nullable=True)
    recall: Mapped[float | None] = mapped_column(Float, nullable=True)
    false_positives: Mapped[int | None] = mapped_column(Integer, nullable=True)
    false_negatives: Mapped[int | None] = mapped_column(Integer, nullable=True)
    report_body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    params_snapshot_json: Mapped[str | None] = mapped_column(Text, nullable=True)
