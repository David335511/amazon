"""ORM models for the continuous-learning platform.

Four tables:

- ``learning_predictions`` — one row per recorded prediction (profit / sales /
  ROI / risk) carrying the predicted value, the observed ``actual_value`` once
  known, the model version, the decision context (rule / prompt / AI decision /
  match / ranking) and a snapshot of the features used. ``external_id`` gives
  idempotent ingestion.
- ``learning_recommendations`` — improvement proposals (tune a rule threshold,
  rewrite a prompt, reweight a feature, retrain a matching/forecast model) with
  severity, confidence, evidence and a lifecycle status.
- ``learning_runs`` — a versioned run of the continuous-learning cycle: the
  config snapshot, the summary of what was measured, flagged and proposed.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.models.base import Base, TimestampMixin, UUIDMixin


class PredictionType(StrEnum):
    """What quantity is being predicted."""

    PROFIT = "profit"
    SALES = "sales"
    ROI = "roi"
    RISK = "risk"


class DecisionType(StrEnum):
    """What kind of decision produced the prediction."""

    RULE = "rule"
    PROMPT = "prompt"
    AI_DECISION = "ai_decision"
    MATCH = "match"
    RANKING = "ranking"


class RecommendationTarget(StrEnum):
    """What the recommendation proposes to improve."""

    PROMPT = "prompt"
    FEATURE_WEIGHT = "feature_weight"
    MATCHING_ALGORITHM = "matching_algorithm"
    FORECAST_MODEL = "forecast_model"
    RULE_THRESHOLD = "rule_threshold"


class IssueType(StrEnum):
    """Automatic issue classifications."""

    BAD_RULE = "bad_rule"
    WEAK_PROMPT = "weak_prompt"
    POOR_DECISION = "poor_decision"
    INCORRECT_MATCH = "incorrect_match"
    RANKING_MISTAKE = "ranking_mistake"


class RunStatus(StrEnum):
    """Lifecycle of a learning cycle run."""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class RecommendationStatus(StrEnum):
    """Lifecycle of a recommendation."""

    OPEN = "open"
    APPLIED = "applied"
    DISMISSED = "dismissed"


class LearningPrediction(Base, UUIDMixin, TimestampMixin):
    """A recorded prediction together with its realised outcome."""

    __tablename__ = "learning_predictions"

    prediction_type: Mapped[str] = mapped_column(
        String(16), nullable=False, index=True,
        comment="PredictionType (profit | sales | roi | risk)",
    )
    subject_key: Mapped[str] = mapped_column(
        String(128), nullable=False, index=True,
        comment="What is being predicted (ASIN, supplier, SKU, prompt id, ...)",
    )
    decision_type: Mapped[str] = mapped_column(
        String(24), nullable=False, index=True,
        comment="DecisionType (rule | prompt | ai_decision | match | ranking)",
    )
    decision_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, index=True,
        comment="Rule / prompt / matcher / ranking identifier",
    )
    model_version: Mapped[str] = mapped_column(
        String(32), nullable=False, default="1.0.0", index=True,
        comment="Which model version produced the prediction",
    )
    predicted_value: Mapped[float] = mapped_column(Float, nullable=False)
    actual_value: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="Observed outcome (None until recorded)",
    )
    predicted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    outcome_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    features_json: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="Snapshot of features/context used to predict (reproducibility)",
    )
    context_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    external_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, unique=True, index=True,
        comment="Client-supplied idempotency key",
    )

    def __repr__(self) -> str:
        return (
            f"<LearningPrediction({self.prediction_type}, {self.subject_key}, "
            f"pred={self.predicted_value}, actual={self.actual_value})>"
        )


class LearningRun(Base, UUIDMixin, TimestampMixin):
    """A versioned continuous-learning cycle."""

    __tablename__ = "learning_runs"

    run_number: Mapped[int] = mapped_column(
        Integer, nullable=False, unique=True, comment="Monotonic, versioned run number",
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=RunStatus.RUNNING.value)
    params_snapshot_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="{}", comment="Config snapshot (reproducibility)",
    )
    summary_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="{}",
        comment="Metrics, issues, recommendations, tunings produced by this run",
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<LearningRun({self.run_number}, {self.status})>"


class LearningRecommendation(Base, UUIDMixin, TimestampMixin):
    """An improvement proposal generated from observed outcomes."""

    __tablename__ = "learning_recommendations"

    run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("learning_runs.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    target_type: Mapped[str] = mapped_column(
        String(24), nullable=False, index=True,
        comment="RecommendationTarget (prompt | feature_weight | matching_algorithm | forecast_model | rule_threshold)",
    )
    target_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, index=True,
        comment="Which prompt / matcher / rule / model to improve",
    )
    issue_type: Mapped[str] = mapped_column(String(24), nullable=False)
    severity: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    current_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    proposed_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    proposed_action: Mapped[str] = mapped_column(Text, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=RecommendationStatus.OPEN.value, index=True,
    )
    model_version: Mapped[str | None] = mapped_column(String(32), nullable=True)

    def __repr__(self) -> str:
        return f"<LearningRecommendation({self.target_type}, {self.issue_type}, {self.status})>"
