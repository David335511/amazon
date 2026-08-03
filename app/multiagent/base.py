"""Core contracts for the multi-agent framework.

Defines the `Agent` abstract base class every specialist agent implements, the
value objects that flow through a pipeline (`AgentResult`, `AgentRun`,
`PipelineResult`, `Delegation`) and the `Tool` seam for tool usage.

Adding a new agent requires zero engine changes: write a subclass of `Agent`
with a unique `role` and register it (see `AgentRegistry` / auto-discovery). The
supervisor, memory sharing, delegation and evaluation all work with any `Agent`.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, ClassVar

from app.multiagent.trace import ReasoningTrace

# Collaboration capabilities the framework provides to every agent.
COLLABORATION_CAPABILITIES: list[str] = [
    "task_delegation",
    "memory_sharing",
    "reasoning_traces",
    "tool_usage",
    "parallel_execution",
    "agent_supervision",
    "agent_evaluation",
]


@dataclass
class AgentResult:
    """Structured output produced by one agent run."""

    role: str
    summary: str
    data: dict[str, Any] = field(default_factory=dict)
    recommendations: list[str] = field(default_factory=list)
    confidence: float = 1.0
    risk_level: str | None = None
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "summary": self.summary,
            "data": self.data,
            "recommendations": self.recommendations,
            "confidence": self.confidence,
            "risk_level": self.risk_level,
            "metrics": self.metrics,
        }


@dataclass
class Delegation:
    """A subtask one agent handed to another (recorded for traceability)."""

    role: str
    task: dict[str, Any]
    result: AgentResult | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "task": self.task,
            "result": self.result.to_dict() if self.result else None,
            "error": self.error,
        }


@dataclass
class AgentRun:
    """One execution of a single agent within a pipeline."""

    run_id: str
    role: str
    task: dict[str, Any] = field(default_factory=dict)
    status: str = "pending"  # pending | running | succeeded | failed
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None
    duration_ms: float = 0.0
    traces: list[ReasoningTrace] = field(default_factory=list)
    tools_used: list[str] = field(default_factory=list)
    delegations: list[Delegation] = field(default_factory=list)
    result: AgentResult | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "role": self.role,
            "task": self.task,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": round(self.duration_ms, 2),
            "traces": [t.to_dict() for t in self.traces],
            "tools_used": self.tools_used,
            "delegations": [d.to_dict() for d in self.delegations],
            "result": self.result.to_dict() if self.result else None,
            "error": self.error,
        }


@dataclass
class PipelineResult:
    """The aggregate outcome of a supervised multi-agent pipeline."""

    run_id: str
    task: dict[str, Any]
    status: str  # succeeded | degraded
    runs: list[AgentRun] = field(default_factory=list)
    evaluations: list[Any] = field(default_factory=list)
    shared_memory: dict[str, Any] = field(default_factory=dict)
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None
    duration_ms: float = 0.0
    report: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "task": self.task,
            "status": self.status,
            "runs": [r.to_dict() for r in self.runs],
            "evaluations": [e.to_dict() for e in self.evaluations],
            "shared_memory_keys": sorted(self.shared_memory),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": round(self.duration_ms, 2),
            "report": self.report,
        }


class Tool:
    """A named capability an agent may invoke via ``context.use_tool(...)``.

    Tools are the boundary between pure agent reasoning and the rest of the
    platform (reverse sourcing, forecasting, supplier intel, finance, ...).
    """

    name: ClassVar[str] = ""
    description: ClassVar[str] = ""

    def __init__(self) -> None:
        if not self.name:
            raise TypeError(f"{type(self).__name__} must define a 'name'")

    async def invoke(self, context: Any, **kwargs: Any) -> Any:
        """Execute the tool. Subclasses override this."""
        raise NotImplementedError

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description}


class Agent(ABC):
    """Abstract base for every specialist agent.

    Subclasses declare a unique ``role`` and metadata (``display_name``,
    ``description``, ``capabilities``, ``default_tools``, ``depends_on``), then
    implement ``run(context)``. They collaborate by reading/writing the shared
    context (memory), recording reasoning traces and delegating subtasks.
    """

    role: ClassVar[str] = ""
    display_name: ClassVar[str] = ""
    description: ClassVar[str] = ""
    capabilities: ClassVar[list[str]] = []
    default_tools: ClassVar[list[str]] = []
    # Agent roles whose outputs this agent needs (drives parallel-wave ordering).
    depends_on: ClassVar[list[str]] = []

    @abstractmethod
    async def run(self, context: Any) -> AgentResult:
        """Execute the agent against the given `AgentContext`.

        Args:
            context: shared, mutable context (task, shared memory, traces,
                tool registry, agent registry for delegation).

        Returns:
            An `AgentResult` with a summary, structured data, recommendations
            and a confidence score.
        """
        raise NotImplementedError


def new_run_id() -> str:
    """Generate a short unique run id for a pipeline/agent run."""
    return uuid.uuid4().hex
