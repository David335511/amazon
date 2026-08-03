"""Configuration for the AI memory system.

Follows the same layered-config convention as every other subsystem: Pydantic
defaults, overridable via YAML (``config/<env>.yaml``) and environment vars.
The DI layer builds a `MemoryConfig` from the raw ``memory:`` YAML block (same
pattern as the browser framework).
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class MemoryConfig(BaseSettings):
    """Runtime settings for the AI memory system."""

    enabled: bool = True

    # Embedding: "local" (deterministic hashing, always available) or "ollama"
    # (real semantic embeddings via a local Ollama instance).
    embedding_provider: str = "local"
    embedding_enabled: bool = True
    embedding_dim: int = 128
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "nomic-embed-text"

    # Lifecycle defaults.
    short_term_ttl_seconds: int = 86_400  # 1 day for short-term working memory
    consolidation_importance_threshold: float = 0.7  # promote >= this importance
    decay_factor: float = 0.05  # per-consolidation importance decay for episodic
    min_importance: float = 0.1  # episodic memories below this are purged

    # Retrieval defaults.
    recall_top_k: int = 10
    recall_threshold: float = 0.25
    recall_recent_limit: int = 20
    max_results_per_type: int = 100

    model_config = SettingsConfigDict(extra="ignore")
