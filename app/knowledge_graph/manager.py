"""Facade for the commerce knowledge graph.

`KnowledgeGraphManager` is the ONLY entry point for modelling entities and
relationships, traversing the graph, running semantic search, discovering
relationships, generating recommendations, finding profitable clusters, surfacing
hidden opportunities, computing similarity, and explaining graph reasoning.

It depends on the `GraphStore` interface (not a concrete DB) and the pure
algorithms in `engine.py`, so the same code works with any graph backing store.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from app.knowledge_graph.cluster import (
    hidden_opportunities,
    profitable_clusters,
)
from app.knowledge_graph.config import KnowledgeGraphConfig
from app.knowledge_graph.engine import (
    adjacency_map,
    bfs,
    connected_components,
    cosine,
    neighbor_similarity,
    shortest_path,
)
from app.knowledge_graph.errors import (
    KnowledgeGraphNotFoundError,
    KnowledgeGraphValidationError,
)
from app.knowledge_graph.explain import (
    explain_cluster,
    explain_opportunity,
    explain_path,
    explain_recommendations,
    label_for,
)
from app.knowledge_graph.models import EdgeType, NodeType
from app.knowledge_graph.recommend import recommend_related
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
    PathNode,
    PathResult,
    RelatedItem,
    RelatedResult,
    SemanticHit,
    SemanticResult,
    SimilarityResult,
    TraversalNode,
    TraversalResult,
)
from app.knowledge_graph.semantic import SemanticIndex
from app.knowledge_graph.store import GraphStore


def _attrs_json(node: Any) -> dict[str, Any]:
    raw = getattr(node, "attributes_json", None)
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return {}


def _node_to_read(node: Any) -> NodeRead:
    return NodeRead(
        id=str(node.id),
        node_type=node.node_type,
        key=node.key,
        label=node.label,
        attributes=_attrs_json(node),
        created_at=node.created_at,
    )


def _edge_to_read(edge: Any) -> EdgeRead:
    return EdgeRead(
        id=str(edge.id),
        source_id=str(edge.source_id),
        target_id=str(edge.target_id),
        edge_type=edge.edge_type,
        weight=edge.weight,
        attributes=_attrs_json(edge),
        created_at=edge.created_at,
    )


class KnowledgeGraphManager:
    """Facade over the commerce knowledge graph."""

    def __init__(
        self,
        store: GraphStore,
        config: KnowledgeGraphConfig | None = None,
        embedder: Callable[[str], list[float]] | None = None,
    ) -> None:
        self._store = store
        self._config = config or KnowledgeGraphConfig()
        self._embedder = embedder

    # ── Capabilities / stats ─────────────────────────────────────────────

    def capabilities(self) -> GraphCapabilities:
        return GraphCapabilities(
            enabled=self._config.enabled,
            node_types=[n.value for n in NodeType],
            edge_types=[e.value for e in EdgeType],
            capabilities=[
                "graph_traversal",
                "semantic_search",
                "relationship_discovery",
                "recommendation_generation",
                "similarity_search",
                "profitable_clusters",
                "hidden_opportunities",
                "explainable_reasoning",
            ],
        )

    async def stats(self) -> GraphStats:
        s = await self._store.stats()
        nodes, edges = await self._load_raw()
        comps = connected_components(adjacency_map(nodes, edges, directed=False))
        return GraphStats(
            node_count=s["node_count"],
            edge_count=s["edge_count"],
            nodes_by_type=s["nodes_by_type"],
            edges_by_type=s["edges_by_type"],
            connected_components=len(comps),
        )

    # ── Node CRUD ─────────────────────────────────────────────────────────

    async def create_node(self, request: NodeCreate) -> NodeRead:
        node = await self._store.upsert_node(
            node_type=request.node_type,
            key=request.key,
            label=request.label,
            attributes=request.attributes,
            embedding=request.embedding,
        )
        return _node_to_read(node)

    async def bulk_create_nodes(self, request: BulkNodeCreate) -> list[NodeRead]:
        if len(request.nodes) > self._config.max_batch_size:
            raise KnowledgeGraphValidationError(
                f"Batch size {len(request.nodes)} exceeds max {self._config.max_batch_size}"
            )
        return [await self.create_node(n) for n in request.nodes]

    async def get_node(self, node_type: str, key: str) -> NodeRead:
        node = await self._store.get_node(node_type, key)
        if node is None:
            raise KnowledgeGraphNotFoundError(f"Node {node_type}/{key} not found")
        return _node_to_read(node)

    async def delete_node(self, node_id: str) -> bool:
        return await self._store.delete_node(node_id)

    async def list_nodes(self, *, node_type: str | None = None, limit: int = 100, offset: int = 0) -> NodeList:
        rows, total = await self._store.list_nodes(node_type=node_type, limit=limit, offset=offset)
        return NodeList(items=[_node_to_read(r) for r in rows], total=total)

    # ── Edge CRUD ─────────────────────────────────────────────────────────

    async def add_edge(self, request: EdgeCreate) -> EdgeRead:
        src = await self._store.get_node_by_id(request.source)
        tgt = await self._store.get_node_by_id(request.target)
        if src is None or tgt is None:
            raise KnowledgeGraphNotFoundError(
                f"Edge endpoints not found (source={'yes' if src else 'no'}, target={'yes' if tgt else 'no'})"
            )
        if src.id == tgt.id:
            raise KnowledgeGraphValidationError("Self-loops are not allowed")
        edge = await self._store.create_edge(
            source_id=src.id,
            target_id=tgt.id,
            edge_type=request.edge_type,
            weight=request.weight,
            attributes=request.attributes,
        )
        return _edge_to_read(edge)

    async def bulk_create_edges(self, request: BulkEdgeCreate) -> list[EdgeRead]:
        if len(request.edges) > self._config.max_batch_size:
            raise KnowledgeGraphValidationError(
                f"Batch size {len(request.edges)} exceeds max {self._config.max_batch_size}"
            )
        return [await self.add_edge(e) for e in request.edges]

    async def remove_edge(self, edge_id: str) -> bool:
        return await self._store.delete_edge(edge_id)

    async def list_edges(self, *, limit: int = 100, offset: int = 0) -> EdgeList:
        edges = await self._store.all_edges()
        paged = edges[offset:offset + limit]
        return EdgeList(items=[_edge_to_read(e) for e in paged], total=len(edges))

    # ── Graph algorithms ──────────────────────────────────────────────────

    async def traversal(self, node_type: str, key: str, max_depth: int | None = None) -> TraversalResult:
        node = await self._resolve(node_type, key)
        nodes, edges = await self._load_raw()
        adj = adjacency_map(nodes, edges, directed=False)
        depth = self._config.traversal_max_depth if max_depth is None else max_depth
        depth_map, _parent, _order = bfs(adj, node.id, max_depth=depth)
        nodes_by_id = {n.id: n for n in nodes}
        items = [
            TraversalNode(
                node_id=str(nid),
                node_type=nodes_by_id[nid].node_type,
                label=label_for(nodes_by_id[nid]),
                depth=d,
            )
            for nid, d in sorted(depth_map.items(), key=lambda x: x[1])
        ]
        return TraversalResult(start=node.key, max_depth=depth, nodes=items, node_count=len(items))

    async def shortest_path(self, source: str, target: str) -> PathResult:
        src = await self._store.get_node_by_id(source)
        tgt = await self._store.get_node_by_id(target)
        if src is None or tgt is None:
            raise KnowledgeGraphNotFoundError("Path endpoint(s) not found")
        nodes, edges = await self._load_raw()
        adj = adjacency_map(nodes, edges, directed=False)
        result = shortest_path(adj, src.id, tgt.id)
        if result is None:
            return PathResult(start=source, target=target, found=False)
        path, weight = result
        nodes_by_id = {n.id: n for n in nodes}
        return PathResult(
            start=source,
            target=target,
            found=True,
            total_weight=round(weight, 4),
            path=[
                PathNode(
                    step=i,
                    node_id=str(nid),
                    node_type=nodes_by_id[nid].node_type,
                    label=label_for(nodes_by_id[nid]),
                )
                for i, nid in enumerate(path)
            ],
        )

    async def related(self, node_type: str, key: str, top_k: int | None = None) -> RelatedResult:
        """Find same-type entities related to the given node."""
        target = await self._resolve(node_type, key)
        nodes, edges = await self._load_raw()
        k = self._config.recommend_top_k if top_k is None else top_k
        ranked = recommend_related(nodes, edges, target.id, self._config.recommend_weights)
        ranked = [r for r in ranked if r[1] >= self._config.recommend_min_score]
        items = [
            RelatedItem(
                id=str(n.id),
                node_type=n.node_type,
                label=n.label or n.key,
                key=n.key,
                score=score,
                signals=signals,
                reasoning="; ".join(reasons) or "related via shared graph structure",
            )
            for n, score, signals, reasons in ranked[:k]
        ]
        return RelatedResult(
            target=f"{node_type}:{key}",
            target_label=target.label or target.key,
            items=items,
        )

    async def related_products(self, key: str, top_k: int | None = None) -> RelatedResult:
        return await self.related(NodeType.PRODUCT.value, key, top_k)

    async def related_suppliers(self, key: str, top_k: int | None = None) -> RelatedResult:
        return await self.related(NodeType.SUPPLIER.value, key, top_k)

    # ── Semantic search / similarity ──────────────────────────────────────

    async def semantic_search(
        self, query: str, node_type: str | None = None, top_k: int | None = None
    ) -> SemanticResult:
        nodes, _edges = await self._load_raw()
        k = self._config.semantic_top_k if top_k is None else top_k
        index = SemanticIndex(embedder=self._embedder, embedding_dim=self._config.default_embedding_dim)
        nodes_by_id = {n.id: n for n in nodes}
        for n in nodes:
            if node_type and n.node_type != node_type:
                continue
            text = n.label or n.key
            attrs = _attrs_json(n)
            text += " " + " ".join(str(v) for v in attrs.values())
            embedding = None
            if n.embedding_json:
                try:
                    parsed = json.loads(n.embedding_json)
                    if isinstance(parsed, list):
                        embedding = [float(x) for x in parsed]
                except (TypeError, ValueError):
                    embedding = None
            index.add(n.id, text, embedding)
        hits = index.search(query, top_k=k)
        items = [
            SemanticHit(
                id=str(nid),
                node_type=nodes_by_id[nid].node_type,
                label=nodes_by_id[nid].label or nodes_by_id[nid].key,
                key=nodes_by_id[nid].key,
                score=round(score, 4),
            )
            for nid, score in hits
        ]
        return SemanticResult(query=query, items=items)

    async def similarity(self, source: str, target: str) -> SimilarityResult:
        src = await self._store.get_node_by_id(source)
        tgt = await self._store.get_node_by_id(target)
        if src is None or tgt is None:
            raise KnowledgeGraphNotFoundError("Similarity endpoint(s) not found")
        nodes, edges = await self._load_raw()
        adj = adjacency_map(nodes, edges, directed=False)

        src_emb = self._embedding_of(src)
        tgt_emb = self._embedding_of(tgt)
        if src_emb and tgt_emb:
            score = cosine(src_emb, tgt_emb)
            explanation = f"Cosine similarity of embeddings ({score:.3f})."
        else:
            score = neighbor_similarity(adj, src.id, tgt.id)
            explanation = f"Jaccard similarity of graph neighbourhoods ({score:.3f})."
        return SimilarityResult(
            source=source,
            target=target,
            score=round(score, 4),
            explanation=explanation,
        )

    # ── Recommendations ───────────────────────────────────────────────────

    async def recommendations(self, node_type: str, key: str, top_k: int | None = None) -> RelatedResult:
        return await self.related(node_type, key, top_k)

    # ── Clusters / opportunities ──────────────────────────────────────────

    async def profitable_clusters(self) -> list[ClusterResult]:
        nodes, edges = await self._load_raw()
        clusters = profitable_clusters(
            nodes, edges,
            min_profit=self._config.min_cluster_profit,
            top_k=self._config.max_clusters,
        )
        return [
            ClusterResult(
                id=c["id"],
                node_count=c["node_count"],
                product_count=c["product_count"],
                profit=c["profit"],
                roi=c["roi"],
                top_products=c["top_products"],
                explanation=explain_cluster(c),
            )
            for c in clusters
        ]

    async def hidden_opportunities(self) -> list[OpportunityResult]:
        nodes, edges = await self._load_raw()
        opps = hidden_opportunities(nodes, edges, top_k=self._config.max_opportunities)
        return [
            OpportunityResult(
                type=o["type"],
                title=o["title"],
                description=o["description"],
                score=o["score"],
                nodes=[str(n) for n in o["nodes"]],
                explanation=explain_opportunity(o),
            )
            for o in opps
        ]

    # ── Explainable reasoning ─────────────────────────────────────────────

    async def explain(self, node_type: str, key: str, top_k: int | None = None) -> ExplanationResult:
        target = await self._resolve(node_type, key)
        nodes, edges = await self._load_raw()
        k = self._config.recommend_top_k if top_k is None else top_k
        ranked = recommend_related(nodes, edges, target.id, self._config.recommend_weights)[:k]
        ranked = [r for r in ranked if r[1] >= self._config.recommend_min_score]
        explanation = explain_recommendations(target, ranked)
        return ExplanationResult(summary=explanation["summary"], items=explanation["items"])

    async def explain_path(self, source: str, target: str) -> ExplanationResult:
        result = await self.shortest_path(source, target)
        if not result.found:
            return ExplanationResult(summary=f"No path between {source} and {target}.")
        nodes, _edges = await self._load_raw()
        nodes_by_id = {str(n.id): n for n in nodes}
        path_ids = [p.node_id for p in result.path]
        explanation = explain_path(nodes_by_id, path_ids, result.total_weight)
        return ExplanationResult(
            summary=explanation["summary"],
            items=[{"node_id": s["node_id"], "node_type": s["node_type"], "label": s["label"]} for s in explanation["steps"]],
        )

    # ── Demo seed ─────────────────────────────────────────────────────────

    async def seed_demo(self) -> dict[str, Any]:
        """Build a small, representative commerce graph (idempotent)."""

        async def n(
            node_type: str, key: str, label: str, attrs: dict[str, Any] | None = None
        ) -> Any:
            return await self._store.upsert_node(
                node_type=node_type,
                key=key,
                label=label,
                attributes=attrs or {},
                embedding=None,
            )

        async def e(
            src: Any,
            tgt: Any,
            edge_type: str,
            weight: float = 1.0,
            attrs: dict[str, Any] | None = None,
        ) -> None:
            await self._store.create_edge(
                source_id=src.id,
                target_id=tgt.id,
                edge_type=edge_type,
                weight=weight,
                attributes=attrs,
            )

        # Products
        p1 = await n(NodeType.PRODUCT.value, "ASIN-ERG01", "Ergo Chair Pro",
                     {"brand": "Acme", "category": "Furniture", "price": 299.0, "profit": 40.0, "roi": 0.35})
        p2 = await n(NodeType.PRODUCT.value, "ASIN-ERG02", "Ergo Chair Lite",
                     {"brand": "Acme", "category": "Furniture", "price": 199.0, "profit": 25.0, "roi": 0.28})
        p3 = await n(NodeType.PRODUCT.value, "ASIN-DSK01", "Standing Desk",
                     {"brand": "Acme", "category": "Furniture", "price": 349.0, "profit": 35.0, "roi": 0.30})
        p4 = await n(NodeType.PRODUCT.value, "ASIN-YOG01", "Yoga Mat",
                     {"brand": "Zen", "category": "Fitness", "price": 25.0, "profit": 15.0, "roi": 0.20})
        p5 = await n(NodeType.PRODUCT.value, "ASIN-BND01", "Resistance Bands",
                     {"brand": "Zen", "category": "Fitness", "price": 18.0, "profit": 18.0, "roi": 0.22})
        # Unconnected profitable product -> triggers an opportunity.
        p6 = await n(NodeType.PRODUCT.value, "ASIN-WGT01", "Unconnected Widget",
                     {"brand": "Acme", "category": "Gadgets", "price": 120.0, "profit": 50.0, "roi": 0.40})
        # Single-supplier dependency -> triggers an opportunity.
        p7 = await n(NodeType.PRODUCT.value, "ASIN-SSG01", "Single-Source Gadget",
                     {"brand": "Acme", "category": "Gadgets", "price": 200.0, "profit": 60.0, "roi": 0.30})
        # Underserved category (no suppliers) -> triggers an opportunity.
        p8 = await n(NodeType.PRODUCT.value, "ASIN-CMP01", "Camping Stove",
                     {"category": "Outdoors", "price": 60.0, "profit": 20.0, "roi": 0.20})
        p9 = await n(NodeType.PRODUCT.value, "ASIN-TNT01", "Backpacking Tent",
                     {"category": "Outdoors", "price": 150.0, "profit": 22.0, "roi": 0.25})

        # Brands / categories / suppliers / marketplaces / customers
        brand_acme = await n(NodeType.BRAND.value, "acme", "Acme")
        brand_zen = await n(NodeType.BRAND.value, "zen", "Zen")
        cat_furniture = await n(NodeType.CATEGORY.value, "furniture", "Furniture")
        cat_fitness = await n(NodeType.CATEGORY.value, "fitness", "Fitness")
        cat_gadgets = await n(NodeType.CATEGORY.value, "gadgets", "Gadgets")
        cat_outdoors = await n(NodeType.CATEGORY.value, "outdoors", "Outdoors")
        s1 = await n(NodeType.SUPPLIER.value, "acme-mfg", "Acme Manufacturing",
                     {"categories": ["Furniture"], "country": "CN"})
        s2 = await n(NodeType.SUPPLIER.value, "zen-mfg", "Zen Manufacturing",
                     {"categories": ["Fitness"], "country": "VN"})
        s3 = await n(NodeType.SUPPLIER.value, "gadget-sourcing", "Gadget Sourcing",
                     {"categories": ["Gadgets"], "country": "US"})
        s4 = await n(NodeType.SUPPLIER.value, "furniture-wholesale", "Furniture Wholesale",
                     {"categories": ["Furniture"], "country": "CN"})
        m_amazon = await n(NodeType.MARKETPLACE.value, "amazon", "Amazon")
        c1 = await n(NodeType.CUSTOMER.value, "cust-1", "Customer 1")
        c2 = await n(NodeType.CUSTOMER.value, "cust-2", "Customer 2")
        c3 = await n(NodeType.CUSTOMER.value, "cust-3", "Customer 3")

        # Events / decisions / price / inventory / seasonality
        dec1 = await n(NodeType.AI_DECISION.value, "decision-pricing", "Pricing decision",
                       {"kind": "pricing"})
        event1 = await n(NodeType.HISTORICAL_EVENT.value, "event-disruption", "Sourcing disruption",
                         {"kind": "disruption"})
        price1 = await n(NodeType.PRICE_CHANGE.value, "price-erg01", "Price change Ergo Chair",
                         {"delta": -10.0, "pct": -0.03})
        inv1 = await n(NodeType.INVENTORY.value, "inv-erg01", "Inventory Ergo Chair",
                       {"units": 42})
        season1 = await n(NodeType.SEASONALITY.value, "season-holiday", "Holiday demand spike",
                          {"peak": "Q4"})

        # Relationships
        await e(p1, brand_acme, EdgeType.HAS_VARIANT.value)
        await e(p2, brand_acme, EdgeType.HAS_VARIANT.value)
        await e(p3, brand_acme, EdgeType.HAS_VARIANT.value)
        await e(p4, brand_zen, EdgeType.HAS_VARIANT.value)
        await e(p5, brand_zen, EdgeType.HAS_VARIANT.value)

        for p, cat in [(p1, cat_furniture), (p2, cat_furniture), (p3, cat_furniture),
                       (p4, cat_fitness), (p5, cat_fitness), (p6, cat_gadgets),
                       (p7, cat_gadgets), (p8, cat_outdoors), (p9, cat_outdoors)]:
            await e(p, cat, EdgeType.BELONGS_TO.value)

        await e(p1, s1, EdgeType.SUPPLIED_BY.value)
        await e(p2, s1, EdgeType.SUPPLIED_BY.value)
        await e(p3, s1, EdgeType.SUPPLIED_BY.value)
        await e(p3, s4, EdgeType.SUPPLIED_BY.value)  # p3 dual-sourced
        await e(p4, s2, EdgeType.SUPPLIED_BY.value)
        await e(p5, s2, EdgeType.SUPPLIED_BY.value)
        await e(p7, s3, EdgeType.SUPPLIED_BY.value)  # p7 single supplier

        for p in [p1, p2, p3, p4, p5, p7]:
            await e(p, m_amazon, EdgeType.SELLS_ON.value)

        await e(p1, c1, EdgeType.BOUGHT_BY.value)
        await e(p1, c2, EdgeType.BOUGHT_BY.value)
        await e(p2, c1, EdgeType.BOUGHT_BY.value)
        await e(p3, c2, EdgeType.BOUGHT_BY.value)
        await e(p4, c3, EdgeType.BOUGHT_BY.value)
        await e(p5, c3, EdgeType.BOUGHT_BY.value)

        # Event / price / inventory / seasonality / decision links
        await e(p1, price1, EdgeType.PRICED_AT.value)
        await e(p1, inv1, EdgeType.HAS_STOCK.value)
        await e(p1, season1, EdgeType.SEASONAL_IN.value)
        await e(p1, dec1, EdgeType.DECIDED_BY.value)
        await e(event1, s1, EdgeType.AFFECTED_BY.value)

        stats = await self._store.stats()
        return {"seeded": True, **stats}

    # ── Internals ─────────────────────────────────────────────────────────

    async def _resolve(self, node_type: str, key: str):
        node = await self._store.get_node(node_type, key)
        if node is None:
            raise KnowledgeGraphNotFoundError(f"Node {node_type}/{key} not found")
        return node

    async def _load_raw(self) -> tuple[list[Any], list[Any]]:
        nodes = await self._store.all_nodes()
        edges = await self._store.all_edges()
        return nodes, edges

    @staticmethod
    def _embedding_of(node: Any) -> list[float] | None:
        raw = getattr(node, "embedding_json", None)
        if not raw:
            return None
        if isinstance(raw, list):
            return [float(x) for x in raw]
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [float(x) for x in parsed]
        except (TypeError, ValueError):
            return None
        return None
