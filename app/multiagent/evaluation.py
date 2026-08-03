"""Agent evaluation — how the framework measures agent output quality.

Every `AgentRun` is turned into an `AgentEvaluation` with a composite score
(0..1) weighting success, self-reported confidence and output completeness.
`summarize_evaluations` aggregates per-role stats over many runs so a supervisor
or operator can see which agents are reliable and which are underperforming.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.multiagent.base import AgentRun


@dataclass
class AgentEvaluation:
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
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "run_id": self.run_id,
            "success": self.success,
            "latency_ms": round(self.latency_ms, 2),
            "confidence": self.confidence,
            "completeness": self.completeness,
            "tool_usage": self.tool_usage,
            "score": self.score,
            "error": self.error,
        }


def _completeness(result: Any) -> float:
    """Fraction of expected output dimensions the agent produced."""
    if result is None:
        return 0.0
    dims = [
        bool(getattr(result, "summary", "")),
        bool(getattr(result, "recommendations", None)),
        bool(getattr(result, "data", None)),
        getattr(result, "confidence", None) is not None,
    ]
    return round(sum(dims) / len(dims), 4) if dims else 0.0


def evaluate_run(run: AgentRun) -> AgentEvaluation:
    """Evaluate a single completed agent run."""
    success = run.status == "succeeded"
    result = run.result
    confidence = result.confidence if result else 0.0
    completeness = _completeness(result)
    tool_usage = len(run.tools_used)
    score = round(0.5 * int(success) + 0.2 * confidence + 0.3 * completeness, 4)
    return AgentEvaluation(
        role=run.role,
        run_id=run.run_id,
        success=success,
        latency_ms=run.duration_ms,
        confidence=confidence,
        completeness=completeness,
        tool_usage=tool_usage,
        score=score,
        error=run.error,
    )


def summarize_evaluations(evaluations: list[AgentEvaluation]) -> dict[str, Any]:
    """Aggregate per-role stats over many evaluations."""
    if not evaluations:
        return {}
    by_role: dict[str, list[AgentEvaluation]] = {}
    for ev in evaluations:
        by_role.setdefault(ev.role, []).append(ev)
    return {
        role: {
            "runs": len(es),
            "success_rate": round(sum(1 for e in es if e.success) / len(es), 4),
            "avg_score": round(sum(e.score for e in es) / len(es), 4),
            "avg_latency_ms": round(sum(e.latency_ms for e in es) / len(es), 2),
        }
        for role, es in by_role.items()
    }
