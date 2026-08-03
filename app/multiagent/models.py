"""ORM models for the multi-agent orchestration framework.

Three tables:
- ``multiagent_runs`` — one row per pipeline, capturing task, status, summary,
  shared-memory snapshot and timing.
- ``multiagent_traces`` — one row per agent reasoning trace (replayable).
- ``multiagent_evaluations`` — one row per evaluated agent run (supervision).

The run id FK lets an operator pull the full reasoning trace and evaluations for
any pipeline from the API.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.models.base import Base, TimestampMixin, UUIDMixin


class MultiAgentRun(Base, UUIDMixin, TimestampMixin):
    """A single supervised multi-agent pipeline execution."""

    __tablename__ = "multiagent_runs"

    task_type: Mapped[str] = mapped_column(
        String(64), nullable=False, default="general", index=True,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="succeeded")
    task_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    shared_memory_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    def __repr__(self) -> str:
        return f"<MultiAgentRun({self.task_type}, {self.status})>"


class MultiAgentTrace(Base, UUIDMixin, TimestampMixin):
    """One reasoning step recorded by an agent within a pipeline."""

    __tablename__ = "multiagent_traces"

    run_id: Mapped[object] = mapped_column(
        ForeignKey("multiagent_runs.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    agent_role: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    step: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    detail: Mapped[str] = mapped_column(Text, nullable=False, default="")
    data_json: Mapped[str | None] = mapped_column(Text, nullable=True)


class MultiAgentEvaluation(Base, UUIDMixin, TimestampMixin):
    """Quality metrics for one agent run within a pipeline."""

    __tablename__ = "multiagent_evaluations"

    run_id: Mapped[object] = mapped_column(
        ForeignKey("multiagent_runs.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    agent_role: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    latency_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    completeness: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    tool_usage: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
