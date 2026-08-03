"""Persistence layer for the multi-agent framework.

Stores pipeline runs, their agent reasoning traces and evaluations. The manager
turns in-memory `PipelineResult` / `AgentRun` objects into rows here.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select

from app.infrastructure.repositories.base import BaseRepository
from app.multiagent.models import (
    MultiAgentEvaluation,
    MultiAgentRun,
    MultiAgentTrace,
)


class MultiAgentRepository(BaseRepository[MultiAgentRun]):
    """Repository for multi-agent runs, traces and evaluations."""

    def __init__(self, session) -> None:
        super().__init__(session, MultiAgentRun)

    # ── Runs ──────────────────────────────────────────────────────────

    async def create_run(
        self,
        *,
        task_type: str,
        status: str,
        task_json: str,
        summary: str,
        shared_memory_json: str | None,
        duration_ms: float,
        finished_at: datetime | None,
    ) -> MultiAgentRun:
        return await self.create(
            task_type=task_type,
            status=status,
            task_json=task_json,
            summary=summary,
            shared_memory_json=shared_memory_json,
            duration_ms=duration_ms,
            finished_at=finished_at,
        )

    async def get_run(self, run_id: UUID) -> MultiAgentRun | None:
        return await self.get(run_id)

    async def list_runs(
        self,
        *,
        task_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[MultiAgentRun], int]:
        statement = select(MultiAgentRun)
        if task_type:
            statement = statement.where(MultiAgentRun.task_type == task_type)
        total = await self._count(statement)
        statement = (
            statement.order_by(MultiAgentRun.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.execute(statement)
        return list(result.scalars().all()), total

    # ── Traces ────────────────────────────────────────────────────────

    async def create_trace(
        self,
        *,
        run_id: UUID,
        agent_role: str,
        step: str,
        detail: str,
        data_json: str | None,
    ) -> MultiAgentTrace:
        row = MultiAgentTrace(
            run_id=run_id,
            agent_role=agent_role,
            step=step,
            detail=detail,
            data_json=data_json,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def traces_for(self, run_id: UUID) -> list[MultiAgentTrace]:
        result = await self._session.execute(
            select(MultiAgentTrace)
            .where(MultiAgentTrace.run_id == run_id)
            .order_by(MultiAgentTrace.created_at.asc())
        )
        return list(result.scalars().all())

    # ── Evaluations ───────────────────────────────────────────────────

    async def create_evaluation(
        self,
        *,
        run_id: UUID,
        agent_role: str,
        success: bool,
        latency_ms: float,
        confidence: float | None,
        completeness: float,
        tool_usage: int,
        score: float,
        error: str | None,
    ) -> MultiAgentEvaluation:
        row = MultiAgentEvaluation(
            run_id=run_id,
            agent_role=agent_role,
            success=success,
            latency_ms=latency_ms,
            confidence=confidence,
            completeness=completeness,
            tool_usage=tool_usage,
            score=score,
            error=error,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def evaluations_for(self, run_id: UUID) -> list[MultiAgentEvaluation]:
        result = await self._session.execute(
            select(MultiAgentEvaluation)
            .where(MultiAgentEvaluation.run_id == run_id)
            .order_by(MultiAgentEvaluation.created_at.asc())
        )
        return list(result.scalars().all())

    async def list_evaluations(
        self,
        *,
        role: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[MultiAgentEvaluation], int]:
        statement = select(MultiAgentEvaluation)
        if role:
            statement = statement.where(MultiAgentEvaluation.agent_role == role)
        total = await self._count(statement)
        statement = (
            statement.order_by(MultiAgentEvaluation.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.execute(statement)
        return list(result.scalars().all()), total

    # ── Stats ─────────────────────────────────────────────────────────

    async def stats(self) -> dict[str, Any]:
        total_runs = await self._session.execute(
            select(func.count()).select_from(MultiAgentRun)
        )
        by_status = await self._session.execute(
            select(MultiAgentRun.status, func.count()).group_by(MultiAgentRun.status)
        )
        avg_duration = await self._session.execute(
            select(func.avg(MultiAgentRun.duration_ms))
        )
        total_traces = await self._session.execute(
            select(func.count()).select_from(MultiAgentTrace)
        )
        total_evals = await self._session.execute(
            select(func.count()).select_from(MultiAgentEvaluation)
        )
        return {
            "total_runs": int(total_runs.scalar_one()),
            "total_traces": int(total_traces.scalar_one()),
            "total_evaluations": int(total_evals.scalar_one()),
            "runs_by_status": {r[0]: int(r[1]) for r in by_status.all()},
            "avg_duration_ms": round(float(avg_duration.scalar_one() or 0.0), 2),
        }

    async def _count(self, statement: Any) -> int:
        result = await self._session.execute(
            select(func.count()).select_from(statement.subquery())
        )
        return int(result.scalar_one())
