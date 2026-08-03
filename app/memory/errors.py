"""Exception hierarchy for the AI memory system.

Follows the error-hierarchy convention used by the marketplace and event layers:
a small base class plus specific subtypes so callers can handle known failures
while a generic `MemoryError` catches everything else.
"""

from __future__ import annotations


class MemoryError(Exception):
    """Base error for all memory-system failures."""


class MemoryNotFoundError(MemoryError):
    """Raised when a requested memory record does not exist."""

    def __init__(self, memory_id: object) -> None:
        self.memory_id = memory_id
        super().__init__(f"Memory not found: {memory_id}")


class MemoryValidationError(MemoryError):
    """Raised when a memory create/update payload is invalid."""


class MemoryEmbeddingError(MemoryError):
    """Raised when embedding generation or vector search fails."""
