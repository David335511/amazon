"""MultiAgentManager — the facade for the multi-agent framework.

This is the ONLY entry point the rest of the platform (and the API router) uses
to run and introspect multi-agent pipelines. It owns:

- the `AgentRegistry` (auto-discovered specialist agents),
- the `AgentSupervisor` (planning, delegation, parallel waves, evaluation),
- the `ToolRegistry` (pure tools + engine-backed tools wired through DI),
- an optional `MemorySharing` backend (AI memory system),
- the persistence repository (runs, traces, evaluations).

It is DB-bound (built per request with a session) so traces and evaluations are
recorded for every pipeline it runs.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from app.multiagent.base import AgentResult, AgentRun, PipelineResult
from app.multiagent.config import MultiAgentConfig
from app.multiagent.evaluation import evaluate_run, summarize_evaluations
from app.multiagent.memory import MemorySharing
from app.multiagent.models import MultiAgentRun as RunRow
from app.multiagent.registry import AgentRegistry
from app.multiagent.repository import MultiAgentRepository
from app.multiagent.schemas import (
    AgentEvaluationRead,
    AgentRunRead,
    MultiAgentCapabilities,
    MultiAgentRunDetail,
    MultiAgentRunRead,
    MultiAgentStats,
    PipelineResultRead,
    PipelineRunRequest,
    ReasoningTraceRead,
)
from app.multiagent.supervisor import AgentSupervisor
from app.multiagent.tool import ToolRegistry
from app.multiagent.tools import default_tools


class MultiAgentManager:
    """Facade for running and introspecting multi-agent pipelines."""

    def __init__(
        self,
        repository: MultiAgentRepository,
        *,
        registry: AgentRegistry | None = None,
        tools: list[Any] | None = None,
        memory_sharing: MemorySharing | None = None,
        config: MultiAgentConfig | None = None,
    ) -> None:
        self._repo = repository
        self._registry = registry or AgentRegistry.discover()
        self._tool_registry = ToolRegistry(default_tools() + list(tools or []))
        self._config = config or MultiAgentConfig()
        self._memory_sharing = memory_sharing
        self._supervisor = AgentSupervisor(
            self._registry,
            memory_sharing=self._memory_sharing,
            tool_registry=self._tool_registry,
            config=self._config,
        )

    # ── Introspection ─────────────────────────────────────────────────

    def capabilities(self) -> MultiAgentCapabilities:
        return MultiAgentCapabilities(
            enabled=self._config.enabled,
            agents=self._registry.capabilities(),
            roles=self._registry.roles(),
            default_pipeline_roles=list(self._config.default_pipeline_roles),
            tools=self._tool_registry.names(),
            max_parallel_agents=self._config.max_parallel_agents,
        )

    # ── Execution ─────────────────────────────────────────────────────

    async def run_pipeline(
        self, request: PipelineRunRequest
    ) -> PipelineResultRead:
        result = await self._supervisor.run_pipeline(
            request.task, roles=request.roles
        )
        await self._persist(result)
        return _pipeline_to_read(result)

    async def run_agent(self, role: str, task: dict[str, Any]) -> AgentRunRead:
        run = await self._supervisor.run_single(role, task)
        pipeline = PipelineResult(
            run_id=run.run_id,
            task=dict(task),
            status="succeeded" if run.status == "succeeded" else "degraded",
            runs=[run],
            evaluations=[evaluate_run(run)],
            shared_memory={},
            report=None,
        )
        await self._persist(pipeline)
        return _run_to_read(run)

    # ── Retrieval ─────────────────────────────────────────────────────

    async def list_runs(
        self, *, task_type: str | None = None, limit: int = 50, offset: int = 0
    ) -> tuple[list[MultiAgentRunRead], int]:
        rows, total = await self._repo.list_runs(
            task_type=task_type, limit=limit, offset=offset
        )
        return [_run_row_to_read(r) for r in rows], total

    async def get_run(self, run_id: UUID) -> MultiAgentRunDetail | None:
        row = await self._repo.get_run(run_id)
        if row is None:
            return None
        traces = await self._repo.traces_for(run_id)
        evaluations = await self._repo.evaluations_for(run_id)
        shared_memory = _load_json(row.shared_memory_json)
        return MultiAgentRunDetail(
            **(_run_row_to_read(row).model_dump()),
            traces=[
                ReasoningTraceRead(
                    step=t.step,
                    detail=t.detail,
                    data=_load_json(t.data_json),
                    timestamp=t.created_at,
                )
                for t in traces
            ],
            evaluations=[_eval_row_to_read(e) for e in evaluations],
            shared_memory=shared_memory,
        )

    async def traces(
        self, run_id: UUID
    ) -> list[ReasoningTraceRead]:
        traces = await self._repo.traces_for(run_id)
        return [
            ReasoningTraceRead(
                step=t.step,
                detail=t.detail,
                data=_load_json(t.data_json),
                timestamp=t.created_at,
            )
            for t in traces
        ]

    async def list_evaluations(
        self, *, role: str | None = None, limit: int = 100, offset: int = 0
    ) -> tuple[list[AgentEvaluationRead], int]:
        rows, total = await self._repo.list_evaluations(
            role=role, limit=limit, offset=offset
        )
        return [_eval_row_to_read(e) for e in rows], total

    async def stats(self) -> MultiAgentStats:
        raw = await self._repo.stats()
        evaluations, _ = await self._repo.list_evaluations(limit=1000)
        summary = summarize_evaluations(
            [_eval_row_to_read(e) for e in evaluations]
        )
        return MultiAgentStats(
            **raw,
            evaluation_summary=summary,
        )

    # ── Persistence helpers ───────────────────────────────────────────

    async def _persist(self, result: PipelineResult) -> None:
        row = await self._repo.create_run(
            task_type=_task_type(result.task),
            status=result.status,
            task_json=json.dumps(result.task, default=str),
            summary=result.report or "",
            shared_memory_json=(
                json.dumps(result.shared_memory, default=str)
                if self._config.store_shared_memory
                else None
            ),
            duration_ms=result.duration_ms,
            finished_at=result.finished_at,
        )
        await self._persist_runs(row.id, result.runs)
        for ev in result.evaluations:
            await self._repo.create_evaluation(
                run_id=row.id,
                agent_role=ev.role,
                success=ev.success,
                latency_ms=ev.latency_ms,
                confidence=ev.confidence,
                completeness=ev.completeness,
                tool_usage=ev.tool_usage,
                score=ev.score,
                error=ev.error,
            )

    async def _persist_runs(self, run_id: UUID, runs: list[AgentRun]) -> None:
        for run in runs:
            for trace in run.traces:
                await self._repo.create_trace(
                    run_id=run_id,
                    agent_role=run.role,
                    step=trace.step,
                    detail=trace.detail,
                    data_json=json.dumps(trace.data, default=str),
                )


def _task_type(task: dict[str, Any]) -> str:
    return str(task.get("action") or task.get("type") or task.get("objective") or "general")


def _load_json(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return {}


def _run_to_read(run: AgentRun) -> AgentRunRead:
    return AgentRunRead(
        run_id=run.run_id,
        role=run.role,
        task=run.task,
        status=run.status,
        started_at=run.started_at,
        finished_at=run.finished_at,
        duration_ms=round(run.duration_ms, 2),
        traces=[ReasoningTraceRead(**t.to_dict()) for t in run.traces],
        tools_used=run.tools_used,
        delegations=[_delegation_to_read(d) for d in run.delegations],
        result=_result_to_read(run.result) if run.result else None,
        error=run.error,
    )


def _result_to_read(result: AgentResult) -> Any:
    from app.multiagent.schemas import AgentResultRead

    return AgentResultRead(
        role=result.role,
        summary=result.summary,
        data=result.data,
        recommendations=result.recommendations,
        confidence=result.confidence,
        risk_level=result.risk_level,
        metrics=result.metrics,
    )


def _delegation_to_read(d: Any) -> Any:
    from app.multiagent.schemas import DelegationRead

    return DelegationRead(
        role=d.role,
        task=d.task,
        result=_result_to_read(d.result) if d.result else None,
        error=d.error,
    )


def _pipeline_to_read(result: PipelineResult) -> PipelineResultRead:
    return PipelineResultRead(
        run_id=result.run_id,
        task=result.task,
        status=result.status,
        duration_ms=round(result.duration_ms, 2),
        runs=[_run_to_read(r) for r in result.runs],
        evaluations=[_eval_read(e) for e in result.evaluations],
        report=result.report,
        shared_memory_keys=sorted(result.shared_memory),
    )


def _eval_read(e: Any) -> AgentEvaluationRead:
    return AgentEvaluationRead(
        role=e.role,
        run_id=e.run_id,
        success=e.success,
        latency_ms=round(e.latency_ms, 2),
        confidence=e.confidence,
        completeness=e.completeness,
        tool_usage=e.tool_usage,
        score=e.score,
        error=e.error,
        created_at=e.created_at,
    )


def _eval_row_to_read(e: Any) -> AgentEvaluationRead:
    return AgentEvaluationRead(
        role=e.agent_role,
        run_id=str(e.run_id),
        success=e.success,
        latency_ms=e.latency_ms,
        confidence=e.confidence,
        completeness=e.completeness,
        tool_usage=e.tool_usage,
        score=e.score,
        error=e.error,
        created_at=e.created_at,
    )


def _run_row_to_read(row: RunRow) -> MultiAgentRunRead:
    return MultiAgentRunRead(
        id=row.id,
        task_type=row.task_type,
        status=row.status,
        task=_load_json(row.task_json),
        summary=row.summary,
        duration_ms=row.duration_ms,
        finished_at=row.finished_at,
        created_at=row.created_at,
    )
