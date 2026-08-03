"""Vector store abstraction for memory embedding search.

Design decisions:
- `VectorStore` is the seam for future vector databases (pgvector, Qdrant,
  Weaviate, Milvus, ...). The memory manager only depends on this interface.
- `InMemoryVectorStore` ranks candidate vectors with brute-force cosine
  similarity. It is the default for the current single-node platform and is
  deterministic/testable. Candidate embeddings are loaded from the memory
  repository.
- To adopt a dedicated vector DB later, implement `VectorStore.rank` (or add a
  DB-backed search method) and swap it in DI — no domain code changes.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from collections.abc import Sequence


class VectorStore(ABC):
    """Contract for ranking memory vectors by similarity to a query vector."""

    @abstractmethod
    def rank(
        self,
        query: Sequence[float],
        candidates: Sequence[tuple[str, Sequence[float]]],
        *,
        top_k: int = 10,
        threshold: float = 0.0,
    ) -> list[tuple[str, float]]:
        """Rank ``(memory_id, vector)`` candidates by cosine similarity.

        Returns ``(memory_id, score)`` pairs sorted descending by score, filtered
        to ``score >= threshold`` and capped at ``top_k``.
        """


class InMemoryVectorStore(VectorStore):
    """Brute-force cosine-similarity ranking (in-process, deterministic)."""

    def rank(
        self,
        query: Sequence[float],
        candidates: Sequence[tuple[str, Sequence[float]]],
        *,
        top_k: int = 10,
        threshold: float = 0.0,
    ) -> list[tuple[str, float]]:
        query_vec = list(query)
        scored: list[tuple[str, float]] = []
        for memory_id, vector in candidates:
            vec = list(vector)
            if not vec:
                continue
            score = _cosine(query_vec, vec)
            if score >= threshold:
                scored.append((memory_id, score))
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:top_k]


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors of equal length."""
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
