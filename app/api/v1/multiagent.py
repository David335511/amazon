"""Multi-agent orchestration API.

The router talks ONLY to `MultiAgentManager` (via DI); it contains no agent
logic. It exposes capabilities, running a full supervised pipeline, running a
single agent, and retrieving runs, reasoning traces, evaluations and stats.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.dependencies import get_multiagent_manager
from app.multiagent import (
    AgentCapabilityRead,
    AgentEvaluationRead,
    AgentNotFoundError,
    AgentRunRead,
    MultiAgentCapabilities,
    MultiAgentManager,
    MultiAgentRunDetail,
    MultiAgentRunRead,
    MultiAgentStats,
    PipelineResultRead,
    PipelineRunRequest,
    ReasoningTraceRead,
    SingleAgentRunRequest,
)

router = APIRouter(prefix="/multiagent", tags=["multiagent"])

ManagerDep = Annotated[MultiAgentManager, Depends(get_multiagent_manager)]


@router.get("/capabilities", response_model=MultiAgentCapabilities)
async def capabilities(manager: ManagerDep) -> MultiAgentCapabilities:
    """Report the registered agents and collaboration capabilities."""
    return manager.capabilities()


@router.post("/pipeline", response_model=PipelineResultRead)
async def run_pipeline(
    request: PipelineRunRequest, manager: ManagerDep
) -> PipelineResultRead:
    """Run a supervised multi-agent pipeline over a task.

    The supervisor runs the planner first, then executes the (default or
    requested) agents as parallel dependency-DAG waves, sharing memory and
    recording traces + evaluations.
    """
    return await manager.run_pipeline(request)


@router.post("/agents/{role}/run", response_model=AgentRunRead)
async def run_agent(
    role: str, request: SingleAgentRunRequest, manager: ManagerDep
) -> AgentRunRead:
    """Run a single agent in isolation."""
    try:
        return await manager.run_agent(role, request.task)
    except AgentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.get("/runs", response_model=list[MultiAgentRunRead])
async def list_runs(
    manager: ManagerDep,
    task_type: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[MultiAgentRunRead]:
    """List stored pipeline runs, optionally filtered by task type."""
    items, _ = await manager.list_runs(task_type=task_type, limit=limit, offset=offset)
    return items


@router.get("/runs/{run_id}", response_model=MultiAgentRunDetail)
async def get_run(manager: ManagerDep, run_id: UUID) -> MultiAgentRunDetail:
    """Return a stored run with its reasoning traces and evaluations."""
    run = await manager.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return run


@router.get("/runs/{run_id}/traces", response_model=list[ReasoningTraceRead])
async def get_traces(manager: ManagerDep, run_id: UUID) -> list[ReasoningTraceRead]:
    """Return the reasoning traces recorded during a run."""
    return await manager.traces(run_id)


@router.get("/evaluations", response_model=list[AgentEvaluationRead])
async def list_evaluations(
    manager: ManagerDep,
    role: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[AgentEvaluationRead]:
    """List agent evaluations, optionally filtered by agent role."""
    items, _ = await manager.list_evaluations(role=role, limit=limit, offset=offset)
    return items


@router.get("/stats", response_model=MultiAgentStats)
async def stats(manager: ManagerDep) -> MultiAgentStats:
    """Aggregate statistics and per-role evaluation summary."""
    return await manager.stats()


@router.get("/agents", response_model=list[AgentCapabilityRead])
async def agents(manager: ManagerDep) -> list[AgentCapabilityRead]:
    """List the registered specialist agents (for discovery)."""
    return manager.capabilities().agents
