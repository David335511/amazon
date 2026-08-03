"""Pure graph algorithms for the commerce knowledge graph.

Every function here is **standard-library only** and deterministic — it operates
on an in-memory adjacency map built from ``(nodes, edges)``, so the same
algorithms work identically whether the graph is backed by Postgres today or a
dedicated graph database tomorrow.

Adjacency convention: ``adj[node_id] -> list[(neighbor_id, weight, edge_type)]``.
The engine builds an **undirected** adjacency by default (traversal and
similarity are symmetric), which is what the commerce use-cases need.
"""

from __future__ import annotations

import heapq
import math
from collections import deque
from typing import Any

# ──────────────────────────────────────────────────────────────
# Graph construction
# ──────────────────────────────────────────────────────────────


def adjacency_map(
    nodes: list[Any], edges: list[Any], directed: bool = False
) -> dict[Any, list[tuple[Any, float, str]]]:
    """Build an adjacency map from node/edge ORM rows.

    ``directed=False`` (default) adds each edge in both directions so BFS,
    PageRank, similarity and clustering work symmetrically.
    """
    adj: dict[Any, list[tuple[Any, float, str]]] = {n.id: [] for n in nodes}
    for e in edges:
        w = float(e.weight if e.weight is not None else 1.0)
        adj.setdefault(e.source_id, []).append((e.target_id, w, e.edge_type))
        if not directed:
            adj.setdefault(e.target_id, []).append((e.source_id, w, e.edge_type))
    return adj


# ──────────────────────────────────────────────────────────────
# Traversal
# ──────────────────────────────────────────────────────────────


def bfs(
    adj: dict[Any, list[tuple[Any, float, str]]],
    start: Any,
    max_depth: int | None = None,
) -> tuple[dict[Any, int], dict[Any, Any], list[Any]]:
    """Breadth-first traversal from ``start``.

    Returns ``(depth_map, parent_map, order)`` where ``depth_map[node]`` is the
    BFS distance from ``start`` (0 for the start node).
    """
    depth: dict[Any, int] = {start: 0}
    parent: dict[Any, Any] = {start: None}
    order: list[Any] = []
    queue: deque[Any] = deque([start])
    while queue:
        cur = queue.popleft()
        order.append(cur)
        if max_depth is not None and depth[cur] >= max_depth:
            continue
        for nbr, _w, _et in adj.get(cur, []):
            if nbr not in depth:
                depth[nbr] = depth[cur] + 1
                parent[nbr] = cur
                queue.append(nbr)
    return depth, parent, order


def shortest_path(
    adj: dict[Any, list[tuple[Any, float, str]]],
    start: Any,
    target: Any,
) -> tuple[list[Any], float] | None:
    """Dijkstra's shortest path from ``start`` to ``target``.

    Returns ``(path, total_weight)`` or ``None`` if unreachable.
    """
    inf = math.inf
    dist: dict[Any, float] = {start: 0.0}
    prev: dict[Any, Any] = {start: None}
    pq: list[tuple[float, Any]] = [(0.0, start)]
    visited: set[Any] = set()
    while pq:
        d, u = heapq.heappop(pq)
        if u in visited:
            continue
        visited.add(u)
        if u == target:
            break
        for nbr, w, _et in adj.get(u, []):
            nd = d + w
            if nd < dist.get(nbr, inf):
                dist[nbr] = nd
                prev[nbr] = u
                heapq.heappush(pq, (nd, nbr))
    if target not in dist:
        return None
    path: list[Any] = []
    u: Any = target
    while u is not None:
        path.append(u)
        u = prev[u]
    path.reverse()
    return path, dist[target]


# ──────────────────────────────────────────────────────────────
# Components / ranking / clustering
# ──────────────────────────────────────────────────────────────


def connected_components(adj: dict[Any, list[tuple[Any, float, str]]]) -> list[set[Any]]:
    """Return every connected component as a set of node ids."""
    seen: set[Any] = set()
    comps: list[set[Any]] = []
    for node in adj:
        if node in seen:
            continue
        comp: set[Any] = set()
        stack: list[Any] = [node]
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            comp.add(cur)
            stack.extend(nbr for nbr, _w, _et in adj.get(cur, []))
        comps.append(comp)
    return comps


def page_rank(
    adj: dict[Any, list[tuple[Any, float, str]]],
    iterations: int = 30,
    damping: float = 0.85,
) -> dict[Any, float]:
    """PageRank via power iteration over the (undirected) adjacency."""
    nodes = list(adj.keys())
    n = len(nodes)
    if n == 0:
        return {}
    rank: dict[Any, float] = {node: 1.0 / n for node in nodes}
    out_deg = {node: len(adj[node]) for node in nodes}
    for _ in range(iterations):
        dangling = sum(rank[node] for node in nodes if out_deg[node] == 0)
        new_rank: dict[Any, float] = {}
        for node in nodes:
            contrib = 0.0
            for nbr, _w, _et in adj[node]:
                contrib += rank[nbr] / max(1, out_deg[nbr])
            new_rank[node] = (1.0 - damping) / n + damping * (contrib + dangling / n)
        rank = new_rank
    return rank


def label_propagation(
    adj: dict[Any, list[tuple[Any, float, str]]],
    iterations: int = 20,
) -> dict[int, list[Any]]:
    """Label-propagation community detection.

    Returns ``{community_id: [node_ids, ...]}`` with integer community ids.
    """
    nodes = sorted(adj.keys())
    labels: dict[Any, Any] = {node: i for i, node in enumerate(nodes)}
    for _ in range(iterations):
        for node in nodes:
            tally: dict[Any, float] = {}
            for nbr, w, _et in adj[node]:
                tally[labels[nbr]] = tally.get(labels[nbr], 0.0) + w
            if tally:
                labels[node] = max(tally, key=tally.get)
    # Canonicalize labels into contiguous community ids.
    mapping: dict[Any, int] = {}
    communities: dict[int, list[Any]] = {}
    for node in nodes:
        lab = labels[node]
        if lab not in mapping:
            mapping[lab] = len(mapping)
        communities.setdefault(mapping[lab], []).append(node)
    return communities


# ──────────────────────────────────────────────────────────────
# Similarity
# ──────────────────────────────────────────────────────────────


def jaccard(set_a: set[Any], set_b: set[Any]) -> float:
    """Jaccard similarity of two neighbor sets."""
    if not set_a and not set_b:
        return 0.0
    union = set_a | set_b
    if not union:
        return 0.0
    return len(set_a & set_b) / len(union)


def cosine(vec_a: list[float] | tuple[float, ...], vec_b: list[float] | tuple[float, ...]) -> float:
    """Cosine similarity of two vectors."""
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot = sum(x * y for x, y in zip(vec_a, vec_b, strict=False))
    na = math.sqrt(sum(x * x for x in vec_a))
    nb = math.sqrt(sum(y * y for y in vec_b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def neighbor_similarity(
    adj: dict[Any, list[tuple[Any, float, str]]],
    a: Any,
    b: Any,
) -> float:
    """Jaccard similarity of the two nodes' neighbor sets."""
    return jaccard({nbr for nbr, _w, _et in adj.get(a, [])}, {nbr for nbr, _w, _et in adj.get(b, [])})
