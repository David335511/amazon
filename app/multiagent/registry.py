"""AgentRegistry — discovers and holds all registered agents.

Auto-discovery imports the ``app.multiagent.roles`` package and collects every
`Agent` subclass with a non-empty ``role``. Because discovery is driven by
subclassing + a unique ``role`` string, **adding a new agent is just adding a
file** that is imported by the roles package — the supervisor, memory sharing,
delegation and evaluation all work with it unchanged.
"""

from __future__ import annotations

import importlib
from collections.abc import Iterable
from typing import Any

from app.multiagent.base import Agent
from app.multiagent.errors import AgentNotFoundError


class AgentRegistry:
    """Registry of agents keyed by role."""

    def __init__(self, agents: Iterable[Agent] | None = None) -> None:
        self._agents: dict[str, Agent] = {}
        for agent in agents or []:
            self.register(agent)

    def register(self, agent: Agent | type[Agent]) -> Agent:
        """Register an agent instance (or class, which is instantiated)."""
        if isinstance(agent, type):
            agent = agent()
        if not agent.role:
            raise ValueError(f"Agent {type(agent).__name__} must define a 'role'")
        self._agents[agent.role] = agent
        return agent

    def get(self, role: str) -> Agent:
        agent = self._agents.get(role)
        if agent is None:
            raise AgentNotFoundError(f"Unknown agent role: {role!r}")
        return agent

    def has(self, role: str) -> bool:
        return role in self._agents

    def all(self) -> list[Agent]:
        return list(self._agents.values())

    def roles(self) -> list[str]:
        return sorted(self._agents)

    def capabilities(self) -> list[dict[str, Any]]:
        """Introspect all registered agents."""
        out = []
        for agent in self.all():
            out.append(
                {
                    "role": agent.role,
                    "display_name": agent.display_name,
                    "description": agent.description,
                    "capabilities": agent.capabilities,
                    "default_tools": agent.default_tools,
                    "depends_on": agent.depends_on,
                }
            )
        return out

    @classmethod
    def discover(cls, module: str = "app.multiagent.roles") -> AgentRegistry:
        """Build a registry by importing a module and collecting `Agent` subclasses."""
        registry = cls()
        mod = importlib.import_module(module)
        for name in dir(mod):
            obj = getattr(mod, name)
            if (
                isinstance(obj, type)
                and issubclass(obj, Agent)
                and obj is not Agent
                and getattr(obj, "role", "")
            ):
                registry.register(obj())
        return registry
