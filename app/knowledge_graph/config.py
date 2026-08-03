"""Configuration for the commerce knowledge graph.

Governs how many entities are returned, how deep traversal goes, how many
PageRank iterations run, the minimum profit threshold for a "profitable
cluster", and the weights used when generating recommendations. Follows the
layered-config convention: Pydantic defaults overridable via YAML
(``config/<env>.yaml`` -> ``knowledge_graph:`` block) and environment variables.
The DI layer validates the raw YAML block into a `KnowledgeGraphConfig`.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class KnowledgeGraphConfig(BaseSettings):
    """Runtime settings for the commerce knowledge graph."""

    enabled: bool = True

    # ── Search / ranking ──────────────────────────────────────────────────
    semantic_top_k: int = 10          # default hits for semantic search
    semantic_min_score: float = 0.0   # drop hits below this cosine score
    default_embedding_dim: int = 64   # fallback dim if no embedder configured

    # ── Graph algorithms ──────────────────────────────────────────────────
    traversal_max_depth: int = 3      # default max depth for BFS traversal
    page_rank_iterations: int = 30    # power-iteration count for PageRank
    page_rank_damping: float = 0.85   # random-surfer damping factor
    max_path_nodes: int = 50          # cap on nodes loaded into memory for a query

    # ── Recommendations ───────────────────────────────────────────────────
    recommend_top_k: int = 10
    recommend_min_score: float = 0.05
    # Weight of each signal in the composite recommendation score.
    recommend_weights: dict[str, float] = {
        "shared_category": 0.25,
        "shared_brand": 0.20,
        "co_purchased": 0.25,
        "shared_supplier": 0.15,
        "neighbor_similarity": 0.15,
    }

    # ── Clusters / opportunities ──────────────────────────────────────────
    min_cluster_profit: float = 0.0   # clusters at/above this profit are "profitable"
    max_clusters: int = 10
    max_opportunities: int = 20

    # ── Guardrails ────────────────────────────────────────────────────────
    max_batch_size: int = 500         # max nodes/edges per bulk create call

    model_config = SettingsConfigDict(extra="ignore")
