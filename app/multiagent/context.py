"""AgentContext — the shared, mutable collaboration medium for a pipeline.

Every agent receives the same `AgentContext`. It carries:

- the **task** being worked,
- the **shared memory** (a dict all agents read/write — memory sharing),
- the **reasoning traces** the current agent appends,
- the **tool registry** (tool usage),
- the **agent registry** (task delegation),
- an optional durable **MemorySharing** backend (AI memory system).

Agents never talk to one another directly; they communicate through this
context, which keeps them decoupled and interchangeable.
"""

from __future__ import annotations

from typing import Any

from app.multiagent.base import Delegation
from app.multiagent.errors import MultiAgentError, ToolNotFoundError
from app.multiagent.trace import ReasoningTrace


class AgentContext:
    """Shared context passed to every agent in a pipeline."""

    def __init__(
        self,
        *,
        task: dict[str, Any],
        run_id: str,
        shared_memory: dict[str, Any] | None = None,
        memory_sharing: Any | None = None,
        tool_registry: Any | None = None,
        registry: Any | None = None,
        max_delegations: int = 10,
    ) -> None:
        self.task = dict(task or {})
        self.run_id = run_id
        self.shared_memory: dict[str, Any] = shared_memory if shared_memory is not None else {}
        self.memory_sharing = memory_sharing
        self.tool_registry = tool_registry
        self.registry = registry
        self.max_delegations = max_delegations
        self.role: str | None = None
        self.traces: list[ReasoningTrace] = []
        self.tools_used: list[str] = []
        self.delegations: list[Delegation] = []

    # ── Reasoning traces ────────────────────────────────────────────

    def trace(self, step: str, detail: str = "", **data: Any) -> ReasoningTrace:
        """Record one reasoning step for this agent's run."""
        trace = ReasoningTrace(step=step, detail=detail, data=data)
        self.traces.append(trace)
        return trace

    # ── Memory sharing ──────────────────────────────────────────────

    def share(self, key: str, value: Any) -> Any:
        """Write a value to the shared memory so other agents can see it."""
        self.shared_memory[key] = value
        return value

    def recall(self, key: str, default: Any = None) -> Any:
        """Read a value from shared memory (written by this or another agent)."""
        return self.shared_memory.get(key, default)

    def has(self, key: str) -> bool:
        """Whether shared memory contains a key."""
        return key in self.shared_memory

    # ── Tool usage ──────────────────────────────────────────────────

    async def use_tool(self, name: str, **kwargs: Any) -> Any:
        """Invoke a registered tool by name, recording usage + a trace."""
        if self.tool_registry is None:
            raise ToolNotFoundError(name)
        result = await self.tool_registry.call(name, self, **kwargs)
        if name not in self.tools_used:
            self.tools_used.append(name)
        self.trace("tool_used", f"Used tool '{name}'", tool=name, kwargs=kwargs)
        return result

    # ── Task delegation ─────────────────────────────────────────────

    async def delegate(self, role: str, task: dict[str, Any] | None = None) -> Any:
        """Delegate a subtask to another agent and await its result.

        Uses the shared agent registry, so delegating to a newly added agent
        works with no code change. The delegated result is also written to
        shared memory under ``delegation:{role}``.
        """
        if self.registry is None:
            raise MultiAgentError("No agent registry available for delegation")
        if len(self.delegations) >= self.max_delegations:
            raise MultiAgentError("Delegation limit exceeded")
        agent = self.registry.get(role)
        sub_task = dict(task) if task else dict(self.task)
        sub_ctx = self.spawn(sub_task)
        sub_ctx.role = role
        sub_ctx.trace("delegated", f"Delegated subtask to '{role}'", parent_run=self.run_id)
        try:
            result = await agent.run(sub_ctx)
        except Exception as exc:  # record + re-raise for the supervisor
            self.delegations.append(Delegation(role=role, task=sub_task, error=str(exc)))
            raise
        delegation = Delegation(role=role, task=sub_task, result=result)
        self.delegations.append(delegation)
        self.shared_memory[f"delegation:{role}"] = result.to_dict()
        return result

    # ── Helpers ─────────────────────────────────────────────────────

    def spawn(self, task: dict[str, Any] | None = None) -> AgentContext:
        """Create a child context sharing the same memory/tools/registries."""
        return AgentContext(
            task=task if task is not None else self.task,
            run_id=self.run_id,
            shared_memory=self.shared_memory,
            memory_sharing=self.memory_sharing,
            tool_registry=self.tool_registry,
            registry=self.registry,
            max_delegations=self.max_delegations,
        )
