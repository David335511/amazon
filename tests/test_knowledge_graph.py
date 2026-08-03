"""Tests for the commerce knowledge graph (engine, manager, API)."""

from __future__ import annotations

import types

import pytest

from app.knowledge_graph.config import KnowledgeGraphConfig
from app.knowledge_graph.engine import (
    adjacency_map,
    bfs,
    connected_components,
    cosine,
    jaccard,
    label_propagation,
    page_rank,
    shortest_path,
)
from app.knowledge_graph.errors import (
    KnowledgeGraphNotFoundError,
    KnowledgeGraphValidationError,
)
from app.knowledge_graph.manager import KnowledgeGraphManager
from app.knowledge_graph.repository import PostgresGraphStore
from app.knowledge_graph.schemas import EdgeCreate, NodeCreate


def _node(nid: str) -> types.SimpleNamespace:
    return types.SimpleNamespace(id=nid, node_type="product", key=nid, label=nid)


def _edge(s: str, t: str, et: str = "related_to", w: float = 1.0) -> types.SimpleNamespace:
    return types.SimpleNamespace(source_id=s, target_id=t, edge_type=et, weight=w)


# ──────────────────────────────────────────────────────────────
# Engine unit tests
# ──────────────────────────────────────────────────────────────


def test_bfs_depth_and_parent() -> None:
    nodes = [_node("a"), _node("b"), _node("c"), _node("d")]
    edges = [_edge("a", "b"), _edge("b", "c"), _edge("c", "d")]
    adj = adjacency_map(nodes, edges)
    depth, parent, order = bfs(adj, "a")
    assert depth == {"a": 0, "b": 1, "c": 2, "d": 3}
    assert parent["c"] == "b"
    assert order[0] == "a"


def test_bfs_max_depth() -> None:
    nodes = [_node("a"), _node("b"), _node("c")]
    edges = [_edge("a", "b"), _edge("b", "c")]
    adj = adjacency_map(nodes, edges)
    depth, _parent, _order = bfs(adj, "a", max_depth=1)
    assert depth == {"a": 0, "b": 1}


def test_shortest_path_weighted() -> None:
    nodes = [_node("a"), _node("b"), _node("c"), _node("d")]
    edges = [_edge("a", "b", "x", 1.0), _edge("b", "c", "x", 1.0), _edge("a", "c", "x", 5.0), _edge("c", "d", "x", 1.0)]
    adj = adjacency_map(nodes, edges)
    path, weight = shortest_path(adj, "a", "d")
    assert path == ["a", "b", "c", "d"]
    assert weight == pytest.approx(3.0)


def test_shortest_path_unreachable() -> None:
    nodes = [_node("a"), _node("b")]
    edges = [_edge("a", "a", "x", 1.0)]
    adj = adjacency_map(nodes, edges)
    # b has no edges, so it's disconnected from a's component (a has a self-loop)
    assert shortest_path(adj, "a", "b") is None


def test_connected_components() -> None:
    nodes = [_node("a"), _node("b"), _node("c")]
    edges = [_edge("a", "b")]
    adj = adjacency_map(nodes, edges)
    comps = connected_components(adj)
    assert any("a" in c and "b" in c for c in comps)
    assert any("c" in c for c in comps)


def test_page_rank_positive_and_normalised() -> None:
    nodes = [_node("a"), _node("b")]
    edges = [_edge("a", "b")]
    adj = adjacency_map(nodes, edges)
    rank = page_rank(adj, iterations=20, damping=0.85)
    assert set(rank.keys()) == {"a", "b"}
    assert all(v > 0 for v in rank.values())


def test_label_propagation_groups_connected() -> None:
    nodes = [_node("a"), _node("b"), _node("c"), _node("d")]
    edges = [_edge("a", "b", "x", 2.0), _edge("c", "d", "x", 1.0)]
    adj = adjacency_map(nodes, edges)
    communities = label_propagation(adj)
    groups = [set(v) for v in communities.values()]
    assert {"a", "b"} in groups
    assert {"c", "d"} in groups


def test_jaccard() -> None:
    assert jaccard({"a", "b"}, {"a", "c"}) == pytest.approx(1 / 3)
    assert jaccard(set(), set()) == 0.0


def test_cosine() -> None:
    assert cosine([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert cosine([], [1.0]) == 0.0


# ──────────────────────────────────────────────────────────────
# Manager tests (against the Postgres store on sqlite)
# ──────────────────────────────────────────────────────────────


def _manager(db_session) -> KnowledgeGraphManager:
    return KnowledgeGraphManager(PostgresGraphStore(db_session), config=KnowledgeGraphConfig())


@pytest.mark.asyncio
async def test_seed_demo_builds_graph(db_session) -> None:
    mgr = _manager(db_session)
    result = await mgr.seed_demo()
    assert result["seeded"] is True
    assert result["node_count"] > 0
    assert result["edge_count"] > 0
    stats = await mgr.stats()
    assert stats.node_count > 0
    assert stats.edge_count > 0
    assert stats.nodes_by_type.get("product", 0) == 9
    assert stats.nodes_by_type.get("supplier", 0) == 4


@pytest.mark.asyncio
async def test_seed_is_idempotent(db_session) -> None:
    mgr = _manager(db_session)
    await mgr.seed_demo()
    r2 = await mgr.seed_demo()
    assert r2["node_count"] == r2["node_count"]  # no growth
    stats = await mgr.stats()
    assert stats.node_count > 0


@pytest.mark.asyncio
async def test_node_crud(db_session) -> None:
    mgr = _manager(db_session)
    created = await mgr.create_node(NodeCreate(node_type="product", key="ASIN-X", label="X", attributes={"price": 10.0}))
    assert created.key == "ASIN-X"
    fetched = await mgr.get_node("product", "ASIN-X")
    assert fetched.label == "X"
    # upsert updates
    updated = await mgr.create_node(NodeCreate(node_type="product", key="ASIN-X", label="X2"))
    assert updated.label == "X2"
    listing = await mgr.list_nodes(node_type="product")
    assert listing.total == 1
    deleted = await mgr.delete_node(created.id)
    assert deleted is True
    listing2 = await mgr.list_nodes(node_type="product")
    assert listing2.total == 0


@pytest.mark.asyncio
async def test_edge_crud_and_validation(db_session) -> None:
    mgr = _manager(db_session)
    a = await mgr.create_node(NodeCreate(node_type="product", key="A", label="A"))
    b = await mgr.create_node(NodeCreate(node_type="supplier", key="B", label="B"))
    edge = await mgr.add_edge(EdgeCreate(source=a.id, target=b.id, edge_type="supplied_by", weight=2.0))
    assert edge.weight == 2.0
    # self-loop rejected
    with pytest.raises(KnowledgeGraphValidationError):
        await mgr.add_edge(EdgeCreate(source=a.id, target=a.id, edge_type="supplied_by"))
    # missing endpoint rejected
    with pytest.raises(KnowledgeGraphNotFoundError):
        await mgr.add_edge(EdgeCreate(source=a.id, target="00000000-0000-0000-0000-000000000000", edge_type="supplied_by"))
    removed = await mgr.remove_edge(edge.id)
    assert removed is True


@pytest.mark.asyncio
async def test_related_products(db_session) -> None:
    mgr = _manager(db_session)
    await mgr.seed_demo()
    res = await mgr.related_products("ASIN-ERG01")
    keys = [i.key for i in res.items]
    assert "ASIN-ERG02" in keys  # same category + brand + co-purchased + supplier
    assert "ASIN-DSK01" in keys
    assert "ASIN-YOG01" not in keys  # different category/brand/supplier
    top = res.items[0]
    assert top.score > 0
    assert top.reasoning


@pytest.mark.asyncio
async def test_related_suppliers(db_session) -> None:
    mgr = _manager(db_session)
    await mgr.seed_demo()
    res = await mgr.related_suppliers("acme-mfg")
    keys = [i.key for i in res.items]
    assert "furniture-wholesale" in keys  # shares category + a product


@pytest.mark.asyncio
async def test_semantic_search(db_session) -> None:
    mgr = _manager(db_session)
    await mgr.seed_demo()
    res = await mgr.semantic_search("ergonomic office chair", top_k=5)
    assert res.items
    # chair products should rank above unrelated nodes
    labels = [i.label.lower() for i in res.items]
    assert any("chair" in lab for lab in labels)


@pytest.mark.asyncio
async def test_similarity(db_session) -> None:
    mgr = _manager(db_session)
    await mgr.seed_demo()
    a = await mgr.get_node("product", "ASIN-ERG01")
    b = await mgr.get_node("product", "ASIN-ERG02")
    sim = await mgr.similarity(a.id, b.id)
    assert sim.score > 0
    assert sim.explanation


@pytest.mark.asyncio
async def test_traversal(db_session) -> None:
    mgr = _manager(db_session)
    await mgr.seed_demo()
    res = await mgr.traversal("product", "ASIN-ERG01", max_depth=2)
    assert res.node_count > 1
    assert res.start == "ASIN-ERG01"


@pytest.mark.asyncio
async def test_shortest_path_between_products(db_session) -> None:
    mgr = _manager(db_session)
    await mgr.seed_demo()
    a = await mgr.get_node("product", "ASIN-ERG01")
    b = await mgr.get_node("product", "ASIN-YOG01")
    res = await mgr.shortest_path(a.id, b.id)
    assert res.found is True
    assert len(res.path) > 1


@pytest.mark.asyncio
async def test_profitable_clusters(db_session) -> None:
    mgr = _manager(db_session)
    await mgr.seed_demo()
    clusters = await mgr.profitable_clusters()
    assert isinstance(clusters, list)
    if clusters:
        assert clusters[0].profit >= 0
        assert clusters[0].product_count > 0


@pytest.mark.asyncio
async def test_hidden_opportunities(db_session) -> None:
    mgr = _manager(db_session)
    await mgr.seed_demo()
    opps = await mgr.hidden_opportunities()
    types = {o.type for o in opps}
    assert "unconnected_profitable_product" in types  # ASIN-WGT01
    assert "single_supplier_dependency" in types       # ASIN-SSG01
    assert "underserved_category" in types             # Outdoors
    assert all(o.explanation for o in opps)


@pytest.mark.asyncio
async def test_explain_recommendations(db_session) -> None:
    mgr = _manager(db_session)
    await mgr.seed_demo()
    expl = await mgr.explain("product", "ASIN-ERG01")
    assert expl.summary
    assert expl.items
    assert any("chair" in (i.get("candidate") or "").lower() for i in expl.items)


@pytest.mark.asyncio
async def test_capabilities(db_session) -> None:
    mgr = _manager(db_session)
    caps = mgr.capabilities()
    assert "product" in caps.node_types
    assert "supplied_by" in caps.edge_types
    assert "semantic_search" in caps.capabilities


# ──────────────────────────────────────────────────────────────
# API tests
# ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_api_capabilities(client) -> None:
    resp = await client.get("/api/v1/knowledge-graph/capabilities")
    assert resp.status_code == 200
    data = resp.json()
    assert "product" in data["node_types"]
    assert "explainable_reasoning" in data["capabilities"]


@pytest.mark.asyncio
async def test_api_seed_and_stats(client) -> None:
    resp = await client.post("/api/v1/knowledge-graph/seed")
    assert resp.status_code == 200
    stats = await client.get("/api/v1/knowledge-graph/stats")
    assert stats.status_code == 200
    assert stats.json()["node_count"] > 0


@pytest.mark.asyncio
async def test_api_related_products(client) -> None:
    await client.post("/api/v1/knowledge-graph/seed")
    resp = await client.get("/api/v1/knowledge-graph/products/ASIN-ERG01/related")
    assert resp.status_code == 200
    keys = [i["key"] for i in resp.json()["items"]]
    assert "ASIN-ERG02" in keys


@pytest.mark.asyncio
async def test_api_semantic_search(client) -> None:
    await client.post("/api/v1/knowledge-graph/seed")
    resp = await client.get("/api/v1/knowledge-graph/search", params={"q": "yoga mat", "top_k": 3})
    assert resp.status_code == 200
    assert resp.json()["items"]


@pytest.mark.asyncio
async def test_api_opportunities_and_clusters(client) -> None:
    await client.post("/api/v1/knowledge-graph/seed")
    opps = await client.get("/api/v1/knowledge-graph/opportunities")
    assert opps.status_code == 200
    types = {o["type"] for o in opps.json()}
    assert "underserved_category" in types
    clusters = await client.get("/api/v1/knowledge-graph/clusters/profitable")
    assert clusters.status_code == 200


@pytest.mark.asyncio
async def test_api_node_crud(client) -> None:
    resp = await client.post(
        "/api/v1/knowledge-graph/nodes",
        json={"node_type": "brand", "key": "acme", "label": "Acme", "attributes": {"country": "US"}},
    )
    assert resp.status_code == 201
    nid = resp.json()["id"]
    got = await client.get("/api/v1/knowledge-graph/nodes/brand/acme")
    assert got.json()["label"] == "Acme"
    deleted = await client.delete(f"/api/v1/knowledge-graph/nodes/{nid}")
    assert deleted.status_code == 204
    gone = await client.get("/api/v1/knowledge-graph/nodes/brand/acme")
    assert gone.status_code == 404


@pytest.mark.asyncio
async def test_api_explain(client) -> None:
    await client.post("/api/v1/knowledge-graph/seed")
    resp = await client.get("/api/v1/knowledge-graph/explain/product/ASIN-ERG01")
    assert resp.status_code == 200
    body = resp.json()
    assert body["summary"]
    assert body["items"]


@pytest.mark.asyncio
async def test_api_explain_path(client) -> None:
    await client.post("/api/v1/knowledge-graph/seed")
    a = (await client.get("/api/v1/knowledge-graph/nodes/product/ASIN-ERG01")).json()
    b = (await client.get("/api/v1/knowledge-graph/nodes/product/ASIN-YOG01")).json()
    resp = await client.get(
        "/api/v1/knowledge-graph/explain/path",
        params={"source": a["id"], "target": b["id"]},
    )
    assert resp.status_code == 200
    assert resp.json()["summary"]


@pytest.mark.asyncio
async def test_api_path_not_found(client) -> None:
    await client.post("/api/v1/knowledge-graph/seed")
    a = (await client.get("/api/v1/knowledge-graph/nodes/product/ASIN-ERG01")).json()
    resp = await client.get(
        "/api/v1/knowledge-graph/path",
        params={"source": a["id"], "target": "00000000-0000-0000-0000-000000000000"},
    )
    assert resp.status_code == 404
