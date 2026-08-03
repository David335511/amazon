"""MemorySharing — the durable memory channel between agents.

Backs the in-process ``shared_memory`` dict with optional persistence to the
AI memory system (`app.memory`) so agent insights survive restarts. When no
`MemoryManager` is available it degrades to a process-local store, so the
framework is fully usable without a database.
"""

from __future__ import annotations

import contextlib
from typing import Any

from app.memory import MemoryType


class MemorySharing:
    """Shared, optionally-persisted memory for agent collaboration."""

    def __init__(self, memory_manager: Any | None = None) -> None:
        self._manager = memory_manager
        self._local: dict[str, Any] = {}

    async def remember(
        self,
        *,
        role: str,
        key: str,
        value: Any,
        task_id: str | None = None,
    ) -> Any:
        """Store a value under ``role:key``; persist it when a manager exists."""
        self._local[f"{role}:{key}"] = value
        if self._manager is not None:
            with contextlib.suppress(Exception):
                await self._manager.remember(
                    MemoryType.GENERAL,
                    title=f"{role}:{key}",
                    content=str(value),
                    user_id="agent",
                    metadata={"role": role, "key": key, "value": value, "task_id": task_id},
                )
        return value

    async def recall(self, *, role: str | None = None, key: str | None = None) -> list[Any]:
        """Recall local memories, optionally filtered by role / key."""
        items = list(self._local.items())
        if role is not None:
            items = [(k, v) for k, v in items if k.startswith(f"{role}:")]
        if key is not None:
            items = [(k, v) for k, v in items if k.endswith(f":{key}")]
        return items

    def snapshot(self) -> dict[str, Any]:
        return dict(self._local)
