"""Pydantic API schemas for the commerce knowledge graph."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class NodeCreate(BaseModel):
    """Create/upsert a graph node."""

    node_type: Literal[
        "product", "brand", "category", "supplier", "marketplace", "customer",
        "ai_decision", "historical_event", "price_change", "inventory",
        "seasonality", "other",
    ]
    key: str = Field(min_length=1, max_length=128)
    label: str = Field(default="", max_length=255)
    attributes: dict[str, Any] = Field(default_factory=dict)
    embedding: list[float] | None = None


class NodeRead(BaseModel):
    id: str
    node_type: str
    key: str
    label: str
    attributes: dict[str, Any]
    created_at: datetime


class NodeList(BaseModel):
    items: list[NodeRead]
    total: int


class EdgeCreate(BaseModel):
    source: str = Field(description="source node id")
    target: str = Field(description="target node id")
    edge_type: Literal[
        "belongs_to", "supplied_by", "sells_on", "bought_by", "decided_by",
        "led_to", "priced_at", "has_stock", "seasonal_in", "related_to",
        "similar_to", "has_variant", "affected_by", "part_of", "purchased",
    ]
    weight: float = 1.0
    attributes: dict[str, Any] = Field(default_factory=dict)


class EdgeRead(BaseModel):
    id: str
    source_id: str
    target_id: str
    edge_type: str
    weight: float
    attributes: dict[str, Any]
    created_at: datetime


class EdgeList(BaseModel):
    items: list[EdgeRead]
    total: int


class BulkNodeCreate(BaseModel):
    nodes: list[NodeCreate] = Field(max_length=500)


class BulkEdgeCreate(BaseModel):
    edges: list[EdgeCreate] = Field(max_length=500)


class PathNode(BaseModel):
    step: int
    node_id: str
    node_type: str
    label: str


class PathResult(BaseModel):
    start: str
    target: str
    found: bool
    total_weight: float | None = None
    path: list[PathNode] = Field(default_factory=list)


class TraversalNode(BaseModel):
    node_id: str
    node_type: str
    label: str
    depth: int


class TraversalResult(BaseModel):
    start: str
    max_depth: int
    nodes: list[TraversalNode] = Field(default_factory=list)
    node_count: int


class RelatedItem(BaseModel):
    id: str
    node_type: str
    label: str
    key: str
    score: float
    signals: dict[str, float] = Field(default_factory=dict)
    reasoning: str = ""


class RelatedResult(BaseModel):
    target: str
    target_label: str
    items: list[RelatedItem] = Field(default_factory=list)


class SemanticHit(BaseModel):
    id: str
    node_type: str
    label: str
    key: str
    score: float


class SemanticResult(BaseModel):
    query: str
    items: list[SemanticHit] = Field(default_factory=list)


class SimilarityResult(BaseModel):
    source: str
    target: str
    score: float
    explanation: str


class ClusterResult(BaseModel):
    id: int
    node_count: int
    product_count: int
    profit: float
    roi: float
    top_products: list[str] = Field(default_factory=list)
    explanation: str = ""


class OpportunityResult(BaseModel):
    type: str
    title: str
    description: str
    score: float
    nodes: list[str] = Field(default_factory=list)
    explanation: str = ""


class GraphStats(BaseModel):
    node_count: int
    edge_count: int
    nodes_by_type: dict[str, int]
    edges_by_type: dict[str, int]
    connected_components: int


class GraphCapabilities(BaseModel):
    enabled: bool
    node_types: list[str]
    edge_types: list[str]
    capabilities: list[str]


class ExplanationResult(BaseModel):
    summary: str
    items: list[dict[str, Any]] = Field(default_factory=list)
