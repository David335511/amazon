"""Graph storage interface.

``GraphStore`` is the seam that decouples the knowledge-graph engine from any
concrete database. The production implementation is ``PostgresGraphStore``
(backed by the ``graph_nodes`` / ``graph_edges`` tables); the engine, manager
and API only ever talk to this interface. A future dedicated graph database
(Neo4j, Dgraph, Memgraph, ...) can be added as a new ``GraphStore`` subclass
with **zero changes** to the algorithms, semantics, or API.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.knowledge_graph.models import GraphEdge, GraphNode


class GraphStore(ABC):
    """Abstract graph persistence layer."""

    # ── Nodes ─────────────────────────────────────────────────────────────

    @abstractmethod
    async def get_node(self, node_type: str, key: str) -> GraphNode | None:
        """Fetch a node by its natural (node_type, key) handle."""

    @abstractmethod
    async def get_node_by_id(self, node_id: Any) -> GraphNode | None:
        """Fetch a node by its internal id."""

    @abstractmethod
    async def upsert_node(
        self,
        *,
        node_type: str,
        key: str,
        label: str,
        attributes: dict[str, Any] | None,
        embedding: list[float] | None,
    ) -> GraphNode:
        """Create or update a node by (node_type, key)."""

    @abstractmethod
    async def delete_node(self, node_id: Any) -> bool:
        """Delete a node (edges cascade). Returns True if deleted."""

    @abstractmethod
    async def list_nodes(
        self, *, node_type: str | None = None, limit: int = 100, offset: int = 0
    ) -> tuple[list[GraphNode], int]:
        """List nodes, optionally filtered by node_type."""

    @abstractmethod
    async def all_nodes(self) -> list[GraphNode]:
        """Fetch every node (used by in-memory graph algorithms)."""

    # ── Edges ─────────────────────────────────────────────────────────────

    @abstractmethod
    async def get_edge(self, source_id: Any, target_id: Any, edge_type: str) -> GraphEdge | None:
        """Fetch an edge by its (source, target, type)."""

    @abstractmethod
    async def create_edge(
        self,
        *,
        source_id: Any,
        target_id: Any,
        edge_type: str,
        weight: float,
        attributes: dict[str, Any] | None,
    ) -> GraphEdge:
        """Create an edge (idempotent upsert on source+target+type)."""

    @abstractmethod
    async def delete_edge(self, edge_id: Any) -> bool:
        """Delete an edge. Returns True if deleted."""

    @abstractmethod
    async def all_edges(self) -> list[GraphEdge]:
        """Fetch every edge (used by in-memory graph algorithms)."""

    # ── Stats ─────────────────────────────────────────────────────────────

    @abstractmethod
    async def stats(self) -> dict[str, Any]:
        """Return node/edge counts and per-type breakdowns."""
