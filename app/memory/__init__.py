"""AI memory system.

Gives the platform a persistent, queryable memory so the AI (sourcing agent,
assistant) can learn over time: successful/failed purchases, false positives,
favorite suppliers and brands, high-performing categories, seasonality, past
conversations and user preferences.

Four memory systems, like human memory:
- SHORT_TERM  — volatile working memory (TTL-bounded).
- LONG_TERM   — durable facts promoted from short-term/episodic.
- EPISODIC    — specific events/experiences.
- SEMANTIC    — generalized knowledge (favorites, trends, preferences).

Memories are stored in their own `memories` table, fully separate from product
data, and are searchable via embeddings (with a pluggable embedding provider and
a vector-store seam for future vector databases). Retrieval is exposed through
`MemoryManager` and the `/api/v1/memory` endpoints.
"""

from app.memory.config import MemoryConfig
from app.memory.embedding import (
    EmbeddingProvider,
    HashEmbeddingProvider,
    OllamaEmbeddingProvider,
    build_embedding_provider,
)
from app.memory.errors import (
    MemoryEmbeddingError,
    MemoryError,
    MemoryNotFoundError,
    MemoryValidationError,
)
from app.memory.manager import MemoryManager
from app.memory.models import Memory, MemorySystem, MemoryType, default_system_for
from app.memory.repository import MemoryRepository
from app.memory.schemas import (
    ConsolidationReport,
    MemoryCreate,
    MemoryRead,
    MemoryRecallResult,
    MemoryStats,
)
from app.memory.vector import InMemoryVectorStore, VectorStore

__all__ = [
    "ConsolidationReport",
    "EmbeddingProvider",
    "HashEmbeddingProvider",
    "InMemoryVectorStore",
    "Memory",
    "MemoryConfig",
    "MemoryCreate",
    "MemoryEmbeddingError",
    "MemoryError",
    "MemoryManager",
    "MemoryNotFoundError",
    "MemoryRead",
    "MemoryRecallResult",
    "MemoryRepository",
    "MemoryStats",
    "MemorySystem",
    "MemoryType",
    "MemoryValidationError",
    "OllamaEmbeddingProvider",
    "VectorStore",
    "build_embedding_provider",
    "default_system_for",
]
