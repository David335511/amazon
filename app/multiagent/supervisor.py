"""AgentSupervisor — plans, delegates and monitors a multi-agent pipeline.

The supervisor is the control plane. It:

- **supervises** by running the `planner` agent first (when present),
- builds a **dependency DAG** from each agent's ``depends_on`` and executes it
  in **parallel waves** (independent agents run concurrently via ``gather``),
- provides each agent a shared `AgentContext` (memory, tools, registry),
- collects per-agent `AgentRun`s, **evaluates** them, and reports a single
  aggregate `PipelineResult`.

It knows nothing about the concrete agents — only the `Agent` interface and
each agent's declared dependencies — so adding agents needs no change here.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.multiagent.base import AgentResult, AgentRun, PipelineResult, new_run_id
from app.multiagent.config import MultiAgentConfig
from app.multiagent.context import AgentContext
from app.multiagent.evaluation import evaluate_run
from app.multiagent.registry import AgentRegistry
from app.multiagent.tool import ToolRegistry
from app.multiagent.tools import default_tools


class AgentSupervisor:
    """Executes and monitors multi-agent pipelines."""

    def __init__(
        self,
        registry: AgentRegistry,
        *,
        memory_sharing: Any | None = None,
        tool_registry: ToolRegistry | None = None,
        config: MultiAgentConfig | None = None,
    ) -> None:
        self._registry = registry
        self._memory_sharing = memory_sharing
        self._tool_registry = tool_registry or ToolRegistry(default_tools())
        self._config = config or MultiAgentConfig()

    # ── Public API ──────────────────────────────────────────────────

    async def run_pipeline(
        self,
        task: dict[str, Any],
        *,
        roles: list[str] | None = None,
    ) -> PipelineResult:
        """Run a supervised pipeline over a set of roles (default: all)."""
        run_id = new_run_id()
        start = datetime.now(UTC)
        roles = [r for r in (roles or self._config.default_pipeline_roles) if self._registry.has(r)]
        seed = dict(task.get("seed") or {})
        context = AgentContext(
            task=dict(task),
            run_id=run_id,
            shared_memory=seed,
            memory_sharing=self._memory_sharing,
            tool_registry=self._tool_registry,
            registry=self._registry,
            max_delegations=self._config.max_delegations_per_agent,
        )

        runs: list[AgentRun] = []

        # Supervision: run the planner first (alone) to produce a plan.
        remaining = set(roles)
        if "planner" in remaining:
            runs.append(await self._run_agent("planner", context))
            remaining.discard("planner")

        # Execute the rest as a dependency DAG in parallel waves.
        for wave in self._resolve_waves(list(remaining)):
            if not wave:
                continue
            chunk = wave[: self._config.max_parallel_agents]
            wave_runs = await self.__gather([self._run_agent(r, context) for r in chunk])
            runs.extend(wave_runs)

        evaluations = [evaluate_run(r) for r in runs]
        status = "succeeded" if all(r.status == "succeeded" for r in runs) else "degraded"
        report = None
        reporting = context.shared_memory.get("reporting")
        if isinstance(reporting, dict):
            report = reporting.get("report")
        finished = datetime.now(UTC)
        return PipelineResult(
            run_id=run_id,
            task=dict(task),
            status=status,
            runs=runs,
            evaluations=evaluations,
            shared_memory=dict(context.shared_memory),
            started_at=start,
            finished_at=finished,
            duration_ms=(finished - start).total_seconds() * 1000.0,
            report=report,
        )

    async def run_single(self, role: str, task: dict[str, Any]) -> AgentRun:
        """Run one agent in isolation against a fresh context."""
        run_id = new_run_id()
        seed = dict(task.get("seed") or {})
        context = AgentContext(
            task=dict(task),
            run_id=run_id,
            shared_memory=seed,
            memory_sharing=self._memory_sharing,
            tool_registry=self._tool_registry,
            registry=self._registry,
            max_delegations=self._config.max_delegations_per_agent,
        )
        return await self._run_agent(role, context)

    # ── Internals ───────────────────────────────────────────────────

    async def _run_agent(self, role: str, context: AgentContext) -> AgentRun:
        """Execute one agent, capturing its traces/tools/delegations and result."""
        agent = self._registry.get(role)
        run = AgentRun(run_id=context.run_id, role=role, task=dict(context.task))
        sub = context.spawn(dict(context.task))
        sub.role = role
        run.status = "running"
        try:
            result = await agent.run(sub)
            run.result = result if isinstance(result, AgentResult) else AgentResult(
                role=role, summary=str(result)
            )
            run.status = "succeeded"
        except Exception as exc:
            run.status = "failed"
            run.error = f"{type(exc).__name__}: {exc}"
        run.finished_at = datetime.now(UTC)
        run.duration_ms = (run.finished_at - run.started_at).total_seconds() * 1000.0
        run.traces = sub.traces
        run.tools_used = sub.tools_used
        run.delegations = sub.delegations
        return run

    def _resolve_waves(self, roles: list[str]) -> list[list[str]]:
        """Topologically sort roles into parallel waves by ``depends_on``."""
        role_set = set(roles)
        deps = {r: set(self._registry.get(r).depends_on) & role_set for r in roles}
        remaining = set(roles)
        waves: list[list[str]] = []
        while remaining:
            ready = {r for r in remaining if not deps[r]}
            if not ready:
                ready = set(remaining)  # break dependency cycles deterministically
            ready_sorted = sorted(ready)
            waves.append(ready_sorted)
            for r in ready:
                remaining.discard(r)
                for other in remaining:
                    deps[other].discard(r)
        return waves

    async def __gather(self, coros: list[Any]) -> list[AgentRun]:
        """Run a wave's agents concurrently (gather keeps failure isolation)."""
        import asyncio

        return await asyncio.gather(*coros)
