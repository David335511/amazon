"""ToolRegistry — named tools agents can invoke through the context.

Tools are the boundary between agent reasoning and the rest of the platform.
The manager builds a registry from pure helper tools (always available) plus
optional engine-backed tools (reverse sourcing, forecasting, supplier intel)
wired through DI. Adding a tool is a one-file change; agents discover tools by
name at runtime.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from app.multiagent.base import Tool
from app.multiagent.errors import ToolNotFoundError


class ToolRegistry:
    """Holds named tools and dispatches calls to them."""

    def __init__(self, tools: Iterable[Tool] | None = None) -> None:
        self._tools: dict[str, Tool] = {}
        for tool in tools or []:
            self.register(tool)

    def register(self, tool: Tool) -> Tool:
        self._tools[tool.name] = tool
        return tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def has(self, name: str) -> bool:
        return name in self._tools

    def names(self) -> list[str]:
        return sorted(self._tools)

    async def call(self, name: str, context: Any, **kwargs: Any) -> Any:
        """Invoke a tool by name, raising `ToolNotFoundError` if absent."""
        tool = self._tools.get(name)
        if tool is None:
            raise ToolNotFoundError(name)
        return await tool.invoke(context, **kwargs)

    def to_dict(self) -> list[dict[str, Any]]:
        return [tool.to_dict() for tool in self._tools.values()]
