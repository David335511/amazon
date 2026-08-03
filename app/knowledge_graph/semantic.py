"""Semantic search over the knowledge graph.

Pure-stdlib lexical semantic search with an **optional pluggable embedder**:

- If an ``embedder`` callable is provided (e.g. a real embedding model wired in
  the DI layer), search uses cosine similarity over dense embedding vectors —
  either ones stored on nodes (``embedding_json``) or computed on the fly.
- Otherwise it falls back to a deterministic **token-overlap cosine** (TF-style
  term weighting) over each node's label + attribute text, which needs no
  external services and is always available.

Both paths are deterministic given the same input.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from typing import Any

from app.knowledge_graph.engine import cosine

_STOPWORDS = frozenset(
    ["a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has", "he", "her", "his", "i", "in", "is", "it", "its", "of", "on", "or", "that", "the", "their", "them", "they", "this", "to", "was", "we", "with", "you", "our", "your", "us", "are", "were", "will", "have", "had", "not", "but", "what", "which", "who", "whom", "when", "where", "how", "all", "any", "both", "each", "few", "more", "most", "other", "some", "such", "no", "nor", "only", "own", "same", "so", "than", "too", "very", "can", "just", "about", "into", "over", "after", "out", "then", "there", "these", "those"]
)

_WORD_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """Lowercase, alphanumeric tokens, stopwords removed, length > 1."""
    return [
        w
        for w in _WORD_RE.findall(text.lower())
        if w not in _STOPWORDS and len(w) > 1
    ]


def term_freq(tokens: list[str]) -> dict[str, float]:
    out: dict[str, float] = {}
    for t in tokens:
        out[t] = out.get(t, 0.0) + 1.0
    return out


class SemanticIndex:
    """Accumulates text/embeddings per node and answers ranked queries."""

    def __init__(
        self,
        embedder: Callable[[str], list[float]] | None = None,
        embedding_dim: int = 64,
    ) -> None:
        self._embedder = embedder
        self._dim = embedding_dim
        self._lexical: dict[Any, dict[str, float]] = {}
        self._embeddings: dict[Any, list[float]] = {}

    def add(self, node_id: Any, text: str, embedding: list[float] | None = None) -> None:
        """Index a node's text and optional precomputed embedding."""
        if text:
            self._lexical[node_id] = term_freq(tokenize(text))
        if self._embedder and not embedding:
            embedding = self._embedder(text)
        if embedding:
            self._embeddings[node_id] = embedding

    def search(self, query: str, top_k: int = 10, exclude: Any = None) -> list[tuple[Any, float]]:
        """Return ``[(node_id, score), ...]`` ranked descending.

        Uses dense embeddings when an embedder is configured, else lexical cosine.
        """
        scores: list[tuple[Any, float]] = []
        if self._embeddings and self._embedder:
            qv = self._embedder(query)
            if qv:
                scores = [(nid, cosine(qv, vec)) for nid, vec in self._embeddings.items()]
        else:
            q = term_freq(tokenize(query))
            if not q:
                return []
            qnorm = math.sqrt(sum(f * f for f in q.values()))
            for nid, tf in self._lexical.items():
                dot = sum(tf.get(t, 0.0) * f for t, f in q.items())
                nnorm = math.sqrt(sum(f * f for f in tf.values()))
                denom = qnorm * nnorm
                scores.append((nid, dot / denom if denom else 0.0))
        scores = [(nid, s) for nid, s in scores if nid != exclude]
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]

    def __len__(self) -> int:
        return len(self._lexical) or len(self._embeddings)
