"""Commerce knowledge graph.

Represents products, brands, categories, suppliers, marketplaces, customers,
AI decisions, historical events, price changes, inventory and seasonality as a
labelled, weighted graph of nodes and edges, and exposes graph traversal,
semantic search, relationship discovery, recommendation generation, similarity
search, profitable clusters, hidden opportunities and explainable reasoning.

The storage layer is abstracted behind ``GraphStore`` so a future dedicated
graph database can back the same engine without changing the algorithms or API.
"""

from __future__ import annotations

from app.knowledge_graph.config import KnowledgeGraphConfig
from app.knowledge_graph.manager import KnowledgeGraphManager
from app.knowledge_graph.repository import PostgresGraphStore
from app.knowledge_graph.store import GraphStore

__all__ = [
    "GraphStore",
    "KnowledgeGraphConfig",
    "KnowledgeGraphManager",
    "PostgresGraphStore",
]
