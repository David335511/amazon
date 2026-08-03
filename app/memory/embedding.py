"""Embedding providers for semantic memory search.

Design decisions:
- `EmbeddingProvider` is the ONLY contract the memory system depends on for
  turning text into vectors. It is pluggable so the platform can use a local
  model (Ollama), a hosted API (OpenAI), or a deterministic fallback.
- `HashEmbeddingProvider` is the default. It produces a stable, deterministic
  vector from text (character/token hashing), so embedding search works out of
  the box with no external service and is fully testable. Real semantic recall
  is enabled by switching to `OllamaEmbeddingProvider`.
- Providers are async and report availability so the manager can degrade to
  keyword search when no embedding model is reachable.
"""

from __future__ import annotations

import hashlib
import math
from abc import ABC, abstractmethod

import httpx

from app.memory.errors import MemoryEmbeddingError


class EmbeddingProvider(ABC):
    """Contract for turning text into a numeric vector."""

    name: str = ""

    @abstractmethod
    async def embed(self, text: str) -> list[float]:
        """Embed text into a vector of floats."""

    @abstractmethod
    async def is_available(self) -> bool:
        """Whether this provider can currently embed text."""


class HashEmbeddingProvider(EmbeddingProvider):
    """Deterministic bag-of-tokens hashing embedder.

    Produces the same vector for the same text, so cosine similarity is stable
    and the full recall pipeline works without any external embedding model.
    Useful as a safe default and in tests.
    """

    name = "local"

    def __init__(self, dim: int = 128) -> None:
        self._dim = dim

    async def embed(self, text: str) -> list[float]:
        vector = [0.0] * self._dim
        tokens = _tokenize(text)
        for token in tokens:
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            index = int.from_bytes(digest, "little") % self._dim
            sign = 1.0 if digest[0] % 2 == 0 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(v * v for v in vector))
        if norm > 0:
            vector = [v / norm for v in vector]
        return vector

    async def is_available(self) -> bool:
        return True


class OllamaEmbeddingProvider(EmbeddingProvider):
    """Real semantic embeddings via a local Ollama instance.

    Uses Ollama's `/api/embed` endpoint. Requires Ollama running locally with
    an embedding model pulled (e.g. ``ollama pull nomic-embed-text``).
    """

    name = "ollama"

    def __init__(
        self,
        *,
        base_url: str = "http://localhost:11434",
        model: str = "nomic-embed-text",
        timeout: float = 30.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout

    async def embed(self, text: str) -> list[float]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                f"{self._base_url}/api/embed",
                json={"model": self._model, "input": text},
            )
            response.raise_for_status()
            data = response.json()
        try:
            return [float(v) for v in data["embeddings"][0]]
        except (KeyError, IndexError, TypeError) as exc:
            msg = f"Unexpected Ollama embed response: {data}"
            raise MemoryEmbeddingError(msg) from exc

    async def is_available(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                response = await client.get(f"{self._base_url}/api/tags")
            return response.status_code == 200
        except Exception:
            return False


def build_embedding_provider(config: object) -> EmbeddingProvider:
    """Build the embedding provider selected by config.

    Args:
        config: A `MemoryConfig`-like object exposing `embedding_provider`,
            `embedding_dim`, `ollama_url`, `ollama_model`.

    Returns:
        An `EmbeddingProvider` instance.
    """
    if getattr(config, "embedding_provider", "local") == "ollama":
        return OllamaEmbeddingProvider(
            base_url=getattr(config, "ollama_url", "http://localhost:11434"),
            model=getattr(config, "ollama_model", "nomic-embed-text"),
        )
    return HashEmbeddingProvider(dim=getattr(config, "embedding_dim", 128))


def _tokenize(text: str) -> list[str]:
    """Split text into lowercase alphanumeric tokens."""
    return [t for t in text.lower().split() if t.isalnum()]
