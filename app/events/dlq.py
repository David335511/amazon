"""Dead letter queue for events whose handlers exhausted their retries.

A dead-lettered event is retained (bounded by capacity) with the handler that
failed and the error, so it can be inspected and later replayed. The queue is a
passive store; the bus owns the replay/purge orchestration (see
`InMemoryEventBus.replay_dead_letters`).
"""

from __future__ import annotations

import asyncio
from collections import deque
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from app.events.models import Event, EventPriority, EventType


class DeadLetterRecord(BaseModel):
    """A single retained failed delivery."""

    event_id: str
    event_type: EventType
    handler: str
    error: str
    attempts: int
    failed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    priority: EventPriority
    event: Event


class DeadLetterQueue:
    """In-memory, bounded store of dead-lettered events."""

    def __init__(self, *, cap: int = 1000) -> None:
        self._cap = cap
        self._records: deque[DeadLetterRecord] = deque()
        self._lock = asyncio.Lock()

    async def put(self, record: DeadLetterRecord) -> None:
        """Append a record, evicting the oldest once capacity is exceeded."""
        async with self._lock:
            self._records.append(record)
            while len(self._records) > self._cap:
                self._records.popleft()

    def list(self) -> list[DeadLetterRecord]:
        """Return a snapshot of all retained records (newest first)."""
        return list(reversed(self._records))

    async def purge(self, event_type: EventType | None = None) -> int:
        """Remove retained records (optionally filtered by event type).

        Returns the number of records removed.
        """
        async with self._lock:
            if event_type is None:
                count = len(self._records)
                self._records.clear()
                return count
            before = len(self._records)
            self._records = deque(
                r for r in self._records if r.event_type != event_type
            )
            return before - len(self._records)

    def count(self) -> int:
        """Number of retained dead-letter records."""
        return len(self._records)

    def capacity(self) -> int:
        return self._cap
