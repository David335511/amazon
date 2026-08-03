"""Persistence layer for the commerce knowledge graph.

``PostgresGraphStore`` implements the ``GraphStore`` interface over the
``graph_nodes`` / ``graph_edges`` tables. The manager and engine depend only on
``GraphStore``, so a dedicated graph database can later swap in behind the same
interface.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import func, select

from app.infrastructure.repositories.base import BaseRepository
from app.knowledge_graph.models import GraphEdge, GraphNode
from app.knowledge_graph.store import GraphStore


def _dumps(obj: Any) -> str | None:
    if obj is None:
        return None
    return json.dumps(obj, default=str)


def _to_uuid(value: Any) -> Any:
    """Coerce a string id to a UUID object for Uuid()-typed columns."""
    if isinstance(value, str):
        try:
            return uuid.UUID(value)
        except ValueError:
            return value
    return value


class PostgresGraphStore(GraphStore, BaseRepository[GraphNode]):
    """GraphStore backed by the relational graph tables."""

    def __init__(self, session) -> None:
        BaseRepository.__init__(self, session, GraphNode)

    # ── Nodes ─────────────────────────────────────────────────────────────

    async def get_node(self, node_type: str, key: str) -> GraphNode | None:
        result = await self._session.execute(
            select(GraphNode).where(
                GraphNode.node_type == node_type, GraphNode.key == key
            )
        )
        return result.scalar_one_or_none()

    async def get_node_by_id(self, node_id: Any) -> GraphNode | None:
        result = await self._session.execute(
            select(GraphNode).where(GraphNode.id == _to_uuid(node_id))
        )
        return result.scalar_one_or_none()

    async def upsert_node(
        self,
        *,
        node_type: str,
        key: str,
        label: str,
        attributes: dict[str, Any] | None,
        embedding: list[float] | None,
    ) -> GraphNode:
        node = await self.get_node(node_type, key)
        if node is None:
            node = GraphNode(
                node_type=node_type,
                key=key,
                label=label,
                attributes_json=_dumps(attributes),
                embedding_json=_dumps(embedding),
            )
            self._session.add(node)
        else:
            node.label = label
            node.attributes_json = _dumps(attributes)
            node.embedding_json = _dumps(embedding)
        await self._session.flush()
        await self._session.refresh(node)
        return node

    async def delete_node(self, node_id: Any) -> bool:
        node = await self.get_node_by_id(node_id)
        if node is None:
            return False
        await self._session.delete(node)
        await self._session.flush()
        return True
    async def list_nodes(
        self, *, node_type: str | None = None, limit: int = 100, offset: int = 0
    ) -> tuple[list[GraphNode], int]:
        statement = select(GraphNode)
        if node_type:
            statement = statement.where(GraphNode.node_type == node_type)
        total = int(
            (await self._session.execute(
                select(func.count()).select_from(statement.subquery())
            )).scalar_one()
        )
        statement = (
            statement.order_by(GraphNode.created_at.desc()).offset(offset).limit(limit)
        )
        result = await self._session.execute(statement)
        return list(result.scalars().all()), total

    async def all_nodes(self) -> list[GraphNode]:
        result = await self._session.execute(select(GraphNode))
        return list(result.scalars().all())

    # ── Edges ─────────────────────────────────────────────────────────────

    async def get_edge(self, source_id: Any, target_id: Any, edge_type: str) -> GraphEdge | None:
        result = await self._session.execute(
            select(GraphEdge).where(
                GraphEdge.source_id == _to_uuid(source_id),
                GraphEdge.target_id == _to_uuid(target_id),
                GraphEdge.edge_type == edge_type,
            )
        )
        return result.scalar_one_or_none()

    async def create_edge(
        self,
        *,
        source_id: Any,
        target_id: Any,
        edge_type: str,
        weight: float,
        attributes: dict[str, Any] | None,
    ) -> GraphEdge:
        edge = await self.get_edge(source_id, target_id, edge_type)
        if edge is None:
            edge = GraphEdge(
                source_id=_to_uuid(source_id),
                target_id=_to_uuid(target_id),
                edge_type=edge_type,
                weight=weight,
                attributes_json=_dumps(attributes),
            )
            self._session.add(edge)
        else:
            edge.weight = weight
            edge.attributes_json = _dumps(attributes)
        await self._session.flush()
        await self._session.refresh(edge)
        return edge

    async def delete_edge(self, edge_id: Any) -> bool:
        result = await self._session.execute(
            select(GraphEdge).where(GraphEdge.id == _to_uuid(edge_id))
        )
        edge = result.scalar_one_or_none()
        if edge is None:
            return False
        await self._session.delete(edge)
        await self._session.flush()
        return True

    async def all_edges(self) -> list[GraphEdge]:
        result = await self._session.execute(select(GraphEdge))
        return list(result.scalars().all())

    # ── Stats ─────────────────────────────────────────────────────────────

    async def stats(self) -> dict[str, Any]:
        node_total = int((await self._session.execute(
            select(func.count()).select_from(GraphNode)
        )).scalar_one())
        edge_total = int((await self._session.execute(
            select(func.count()).select_from(GraphEdge)
        )).scalar_one())
        nodes_by_type = {
            r[0]: int(r[1])
            for r in (await self._session.execute(
                select(GraphNode.node_type, func.count()).group_by(GraphNode.node_type)
            )).all()
        }
        edges_by_type = {
            r[0]: int(r[1])
            for r in (await self._session.execute(
                select(GraphEdge.edge_type, func.count()).group_by(GraphEdge.edge_type)
            )).all()
        }
        return {
            "node_count": node_total,
            "edge_count": edge_total,
            "nodes_by_type": nodes_by_type,
            "edges_by_type": edges_by_type,
        }
