"""Pydantic schemas for the multi-agent framework's API."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.multiagent.base import COLLABORATION_CAPABILITIES


class ReasoningTraceRead(BaseModel):
    """One recorded reasoning step."""

    step: str
    detail: str
    data: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime


class AgentResultRead(BaseModel):
    """Structured output of an agent run."""

    role: str
    summary: str
    data: dict[str, Any] = Field(default_factory=dict)
    recommendations: list[str] = Field(default_factory=list)
    confidence: float
    risk_level: str | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)


class DelegationRead(BaseModel):
    """A subtask one agent delegated to another."""

    role: str
    task: dict[str, Any] = Field(default_factory=dict)
    result: AgentResultRead | None = None
    error: str | None = None


class AgentRunRead(BaseModel):
    """One agent's execution within a pipeline."""

    run_id: str
    role: str
    task: dict[str, Any] = Field(default_factory=dict)
    status: str
    started_at: datetime
    finished_at: datetime | None = None
    duration_ms: float
    traces: list[ReasoningTraceRead] = Field(default_factory=list)
    tools_used: list[str] = Field(default_factory=list)
    delegations: list[DelegationRead] = Field(default_factory=list)
    result: AgentResultRead | None = None
    error: str | None = None


class AgentEvaluationRead(BaseModel):
    """Quality metrics for one agent run."""

    role: str
    run_id: str
    success: bool
    latency_ms: float
    confidence: float
    completeness: float
    tool_usage: int
    score: float
    error: str | None = None
    created_at: datetime


class AgentCapabilityRead(BaseModel):
    """Introspection of one registered agent."""

    role: str
    display_name: str
    description: str
    capabilities: list[str] = Field(default_factory=list)
    default_tools: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)


class MultiAgentCapabilities(BaseModel):
    """What the multi-agent framework exposes."""

    enabled: bool
    agents: list[AgentCapabilityRead]
    roles: list[str]
    default_pipeline_roles: list[str]
    collaboration: list[str] = COLLABORATION_CAPABILITIES
    tools: list[str]
    max_parallel_agents: int


class PipelineRunRequest(BaseModel):
    """Request to run a multi-agent pipeline."""

    task: dict[str, Any]
    roles: list[str] | None = None


class SingleAgentRunRequest(BaseModel):
    """Request to run a single agent in isolation."""

    task: dict[str, Any]


class PipelineResultRead(BaseModel):
    """Aggregate outcome of a supervised pipeline."""

    run_id: str
    task: dict[str, Any] = Field(default_factory=dict)
    status: str
    duration_ms: float
    runs: list[AgentRunRead]
    evaluations: list[AgentEvaluationRead]
    report: str | None = None
    shared_memory_keys: list[str] = Field(default_factory=list)


class MultiAgentRunRead(BaseModel):
    """A stored pipeline run (summary view)."""

    id: UUID
    task_type: str
    status: str
    task: dict[str, Any] = Field(default_factory=dict)
    summary: str
    duration_ms: float
    finished_at: datetime | None = None
    created_at: datetime


class MultiAgentRunDetail(MultiAgentRunRead):
    """A stored pipeline run with its traces and evaluations."""

    traces: list[ReasoningTraceRead] = Field(default_factory=list)
    evaluations: list[AgentEvaluationRead] = Field(default_factory=list)
    shared_memory: dict[str, Any] = Field(default_factory=dict)


class MultiAgentStats(BaseModel):
    """Aggregate statistics over the multi-agent store."""

    total_runs: int = 0
    total_traces: int = 0
    total_evaluations: int = 0
    runs_by_status: dict[str, int] = Field(default_factory=dict)
    avg_duration_ms: float = 0.0
    evaluation_summary: dict[str, Any] = Field(default_factory=dict)


def _as_aware(dt: datetime | None) -> datetime | None:
    if dt is None or dt.tzinfo is not None:
        return dt
    from datetime import UTC

    return dt.replace(tzinfo=UTC)
