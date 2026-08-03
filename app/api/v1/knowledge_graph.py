"""API router for the commerce knowledge graph.

The router talks ONLY to `KnowledgeGraphManager` (via DI); it contains no graph
logic itself. It exposes node/edge modelling, traversal, shortest path, related
entities, semantic search, similarity, recommendations, profitable clusters,
hidden opportunities, and explainable reasoning.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.dependencies import get_knowledge_graph_manager
from app.knowledge_graph.errors import (
    KnowledgeGraphError,
    KnowledgeGraphNotFoundError,
    KnowledgeGraphValidationError,
)
from app.knowledge_graph.manager import KnowledgeGraphManager
from app.knowledge_graph.schemas import (
    BulkEdgeCreate,
    BulkNodeCreate,
    ClusterResult,
    EdgeCreate,
    EdgeList,
    EdgeRead,
    ExplanationResult,
    GraphCapabilities,
    GraphStats,
    NodeCreate,
    NodeList,
    NodeRead,
    OpportunityResult,
    PathResult,
    RelatedResult,
    SemanticResult,
    SimilarityResult,
    TraversalResult,
)

router = APIRouter(prefix="/knowledge-graph", tags=["knowledge-graph"])

ManagerDep = Annotated[KnowledgeGraphManager, Depends(get_knowledge_graph_manager)]


def _http(e: KnowledgeGraphError) -> HTTPException:
    if isinstance(e, KnowledgeGraphNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    if isinstance(e, KnowledgeGraphValidationError):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(e))
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# ── Capabilities / stats ──────────────────────────────────────────────────


@router.get("/capabilities", response_model=GraphCapabilities)
async def capabilities(manager: ManagerDep) -> GraphCapabilities:
    """Report supported entity/relationship types and graph capabilities."""
    return manager.capabilities()


@router.get("/stats", response_model=GraphStats)
async def stats(manager: ManagerDep) -> GraphStats:
    """Node/edge counts, per-type breakdowns, and connected components."""
    return await manager.stats()


@router.post("/seed", response_model=dict)
async def seed(manager: ManagerDep) -> dict:
    """Seed a small representative commerce graph (idempotent)."""
    return await manager.seed_demo()


# ── Nodes ─────────────────────────────────────────────────────────────────


@router.post("/nodes", response_model=NodeRead, status_code=status.HTTP_201_CREATED)
async def create_node(body: NodeCreate, manager: ManagerDep) -> NodeRead:
    """Upsert a graph node (product, brand, supplier, ...)."""
    try:
        return await manager.create_node(body)
    except KnowledgeGraphError as exc:
        raise _http(exc) from exc


@router.post("/nodes/bulk", response_model=list[NodeRead])
async def bulk_create_nodes(body: BulkNodeCreate, manager: ManagerDep) -> list[NodeRead]:
    """Upsert many nodes at once."""
    try:
        return await manager.bulk_create_nodes(body)
    except KnowledgeGraphError as exc:
        raise _http(exc) from exc


@router.get("/nodes", response_model=NodeList)
async def list_nodes(
    manager: ManagerDep,
    node_type: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> NodeList:
    """List nodes, optionally filtered by node_type."""
    return await manager.list_nodes(node_type=node_type, limit=limit, offset=offset)


@router.get("/nodes/{node_type}/{key}", response_model=NodeRead)
async def get_node(node_type: str, key: str, manager: ManagerDep) -> NodeRead:
    """Fetch a node by its natural (node_type, key) handle."""
    try:
        return await manager.get_node(node_type, key)
    except KnowledgeGraphError as exc:
        raise _http(exc) from exc


@router.delete("/nodes/{node_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_node(node_id: str, manager: ManagerDep) -> None:
    """Delete a node (its edges cascade)."""
    if not await manager.delete_node(node_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Node not found")


# ── Edges ─────────────────────────────────────────────────────────────────


@router.post("/edges", response_model=EdgeRead, status_code=status.HTTP_201_CREATED)
async def add_edge(body: EdgeCreate, manager: ManagerDep) -> EdgeRead:
    """Create a labelled, weighted edge between two nodes."""
    try:
        return await manager.add_edge(body)
    except KnowledgeGraphError as exc:
        raise _http(exc) from exc


@router.post("/edges/bulk", response_model=list[EdgeRead])
async def bulk_create_edges(body: BulkEdgeCreate, manager: ManagerDep) -> list[EdgeRead]:
    """Create many edges at once."""
    try:
        return await manager.bulk_create_edges(body)
    except KnowledgeGraphError as exc:
        raise _http(exc) from exc


@router.get("/edges", response_model=EdgeList)
async def list_edges(
    manager: ManagerDep,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> EdgeList:
    """List all edges."""
    return await manager.list_edges(limit=limit, offset=offset)


@router.delete("/edges/{edge_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_edge(edge_id: str, manager: ManagerDep) -> None:
    """Delete an edge."""
    if not await manager.remove_edge(edge_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Edge not found")


# ── Graph algorithms ──────────────────────────────────────────────────────


@router.get("/traversal/{node_type}/{key}", response_model=TraversalResult)
async def traversal(
    node_type: str,
    key: str,
    manager: ManagerDep,
    max_depth: int | None = Query(default=None, ge=1, le=20),
) -> TraversalResult:
    """Breadth-first traversal from a node."""
    try:
        return await manager.traversal(node_type, key, max_depth)
    except KnowledgeGraphError as exc:
        raise _http(exc) from exc


@router.get("/path", response_model=PathResult)
async def path(
    manager: ManagerDep,
    source: str = Query(...),
    target: str = Query(...),
) -> PathResult:
    """Shortest (cheapest) path between two nodes."""
    try:
        return await manager.shortest_path(source, target)
    except KnowledgeGraphError as exc:
        raise _http(exc) from exc


@router.get("/related/{node_type}/{key}", response_model=RelatedResult)
async def related(
    node_type: str,
    key: str,
    manager: ManagerDep,
    top_k: int | None = Query(default=None, ge=1, le=50),
) -> RelatedResult:
    """Discover same-type entities related to a node."""
    try:
        return await manager.related(node_type, key, top_k)
    except KnowledgeGraphError as exc:
        raise _http(exc) from exc


@router.get("/products/{key}/related", response_model=RelatedResult)
async def related_products(
    key: str,
    manager: ManagerDep,
    top_k: int | None = Query(default=None, ge=1, le=50),
) -> RelatedResult:
    """Find products related to a product."""
    try:
        return await manager.related_products(key, top_k)
    except KnowledgeGraphError as exc:
        raise _http(exc) from exc


@router.get("/suppliers/{key}/related", response_model=RelatedResult)
async def related_suppliers(
    key: str,
    manager: ManagerDep,
    top_k: int | None = Query(default=None, ge=1, le=50),
) -> RelatedResult:
    """Find suppliers related to a supplier."""
    try:
        return await manager.related_suppliers(key, top_k)
    except KnowledgeGraphError as exc:
        raise _http(exc) from exc


# ── Semantic search / similarity ──────────────────────────────────────────


@router.get("/search", response_model=SemanticResult)
async def search(
    manager: ManagerDep,
    q: str = Query(...),
    node_type: str | None = Query(default=None),
    top_k: int | None = Query(default=None, ge=1, le=50),
) -> SemanticResult:
    """Semantic search over node text (embeddings or lexical cosine)."""
    return await manager.semantic_search(q, node_type, top_k)


@router.get("/similarity", response_model=SimilarityResult)
async def similarity(
    manager: ManagerDep,
    source: str = Query(...),
    target: str = Query(...),
) -> SimilarityResult:
    """Similarity between two nodes (embedding cosine or neighbour Jaccard)."""
    try:
        return await manager.similarity(source, target)
    except KnowledgeGraphError as exc:
        raise _http(exc) from exc


# ── Recommendations / clusters / opportunities ────────────────────────────


@router.get("/recommendations/{node_type}/{key}", response_model=RelatedResult)
async def recommendations(
    node_type: str,
    key: str,
    manager: ManagerDep,
    top_k: int | None = Query(default=None, ge=1, le=50),
) -> RelatedResult:
    """Generate recommendations for a node."""
    try:
        return await manager.recommendations(node_type, key, top_k)
    except KnowledgeGraphError as exc:
        raise _http(exc) from exc


@router.get("/clusters/profitable", response_model=list[ClusterResult])
async def profitable_clusters(manager: ManagerDep) -> list[ClusterResult]:
    """Rank profitable clusters (communities) by aggregate profit."""
    return await manager.profitable_clusters()


@router.get("/opportunities", response_model=list[OpportunityResult])
async def opportunities(manager: ManagerDep) -> list[OpportunityResult]:
    """Discover hidden opportunities (gaps / risks in the graph)."""
    return await manager.hidden_opportunities()


# ── Explainable reasoning ─────────────────────────────────────────────────


@router.get("/explain/{node_type}/{key}", response_model=ExplanationResult)
async def explain(
    node_type: str,
    key: str,
    manager: ManagerDep,
    top_k: int | None = Query(default=None, ge=1, le=50),
) -> ExplanationResult:
    """Explain why items are related to / recommended for a node."""
    try:
        return await manager.explain(node_type, key, top_k)
    except KnowledgeGraphError as exc:
        raise _http(exc) from exc


@router.get("/explain/path", response_model=ExplanationResult)
async def explain_path(
    manager: ManagerDep,
    source: str = Query(...),
    target: str = Query(...),
) -> ExplanationResult:
    """Explain a graph path hop-by-hop."""
    try:
        return await manager.explain_path(source, target)
    except KnowledgeGraphError as exc:
        raise _http(exc) from exc
