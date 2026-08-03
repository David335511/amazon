"""ORM models for the commerce knowledge graph.

Two tables model the graph generically (entity-relationship style):

- ``graph_nodes`` — every entity: products, brands, categories, suppliers,
  marketplaces, customers, AI decisions, historical events, price changes,
  inventory snapshots, and seasonality signals. Each node carries a ``node_type``
  plus a natural ``key`` (unique within its type) so callers can address entities
  by a familiar handle (an ASIN, a supplier slug, a category name, ...).
- ``graph_edges`` — labelled, weighted relationships between nodes
  (``belongs_to``, ``supplied_by``, ``sells_on``, ``bought_by``, ``led_to``,
  ``priced_at``, ``has_stock``, ``seasonal_in``, ``related_to``, ``similar_to``,
  ...). The graph is directed-capable but the engine traverses it as an
  undirected adjacency by default.

Attributes and optional dense embeddings are stored as JSON so the schema stays
stable while entity/edge semantics evolve. This is the persistence for a
``GraphStore`` interface (``app/knowledge_graph/store.py``) so a future graph
database (Neo4j, Dgraph, ...) can back the same algorithms without changing the
engine.
"""

from __future__ import annotations

import uuid
from enum import StrEnum

from sqlalchemy import Float, ForeignKey, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.models.base import Base, TimestampMixin, UUIDMixin


class NodeType(StrEnum):
    """The kinds of entities stored in the commerce knowledge graph."""

    PRODUCT = "product"
    BRAND = "brand"
    CATEGORY = "category"
    SUPPLIER = "supplier"
    MARKETPLACE = "marketplace"
    CUSTOMER = "customer"
    AI_DECISION = "ai_decision"
    HISTORICAL_EVENT = "historical_event"
    PRICE_CHANGE = "price_change"
    INVENTORY = "inventory"
    SEASONALITY = "seasonality"
    # Generic catch-all so the graph can absorb new entity types without a
    # schema change.
    OTHER = "other"


class EdgeType(StrEnum):
    """The kinds of relationships stored in the commerce knowledge graph."""

    BELONGS_TO = "belongs_to"        # product -> category
    SUPPLIED_BY = "supplied_by"      # product -> supplier
    SELLS_ON = "sells_on"            # product -> marketplace
    BOUGHT_BY = "bought_by"          # product -> customer
    DECIDED_BY = "decided_by"        # product/decision -> ai_decision
    LED_TO = "led_to"                # event/decision -> event/decision
    PRICED_AT = "priced_at"          # product -> price_change
    HAS_STOCK = "has_stock"          # product -> inventory
    SEASONAL_IN = "seasonal_in"      # product/category -> seasonality
    RELATED_TO = "related_to"        # product <-> product (editorial/catalog)
    SIMILAR_TO = "similar_to"        # product <-> product (similarity)
    HAS_VARIANT = "has_variant"      # brand/category -> product
    AFFECTED_BY = "affected_by"      # product -> historical_event
    PART_OF = "part_of"              # generic containment

    # Convenience alias used by the demo/seed graph and scoring logic (kept
    # distinct so traversal semantics are explicit).
    PURCHASED = "purchased"          # customer -> product (reverse of bought_by)


class GraphNode(Base, UUIDMixin, TimestampMixin):
    """A single entity in the commerce knowledge graph."""

    __tablename__ = "graph_nodes"

    node_type: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True,
        comment="One of NodeType values.",
    )
    key: Mapped[str] = mapped_column(
        String(128), nullable=False, index=True,
        comment="Natural unique key within its node_type (ASIN, slug, ...).",
    )
    label: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    attributes_json: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="Arbitrary JSON properties (price, profit, roi, ...).",
    )
    embedding_json: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="Optional dense embedding vector (JSON list of floats).",
    )

    __table_args__ = (
        UniqueConstraint("node_type", "key", name="uq_graph_nodes_type_key"),
    )

    def __repr__(self) -> str:
        return f"<GraphNode({self.node_type}:{self.key})>"


class GraphEdge(Base, UUIDMixin, TimestampMixin):
    """A labelled, weighted relationship between two graph nodes."""

    __tablename__ = "graph_edges"

    source_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("graph_nodes.id", ondelete="CASCADE"),
        index=True, nullable=False,
    )
    target_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("graph_nodes.id", ondelete="CASCADE"),
        index=True, nullable=False,
    )
    edge_type: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True,
        comment="One of EdgeType values.",
    )
    weight: Mapped[float] = mapped_column(
        Float, nullable=False, default=1.0,
        comment="Edge weight; larger = stronger/more important.",
    )
    attributes_json: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="Arbitrary JSON properties (date, quantity, delta, ...).",
    )

    __table_args__ = (
        UniqueConstraint("source_id", "target_id", "edge_type", name="uq_graph_edges_src_tgt_type"),
    )

    def __repr__(self) -> str:
        return f"<GraphEdge({self.source_id} -[{self.edge_type}]-> {self.target_id}, {self.weight})>"
