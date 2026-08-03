"""Recommendation generation over the commerce knowledge graph.

Pure functions that score candidate entities relative to a target using graph
signals. Each candidate accumulates a weighted composite score and a list of
human-readable reasons, which feed the "explain graph reasoning" feature.
"""

from __future__ import annotations

import json
from typing import Any

from app.knowledge_graph.engine import adjacency_map, jaccard


def _attrs(node: Any) -> dict[str, Any]:
    if node is None:
        return {}
    raw = getattr(node, "attributes_json", None)
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return {}


def _edge_set(edges: list[Any]) -> set[tuple[Any, Any, str]]:
    return {(e.source_id, e.target_id, e.edge_type) for e in edges}


def _related_by(edge_set: set[tuple[Any, Any, str]], node_id: Any, edge_type: str) -> set[Any]:
    """Neighbours of ``node_id`` joined by ``edge_type`` (either direction)."""
    out: set[Any] = set()
    for s, t, et in edge_set:
        if et != edge_type:
            continue
        if s == node_id:
            out.add(t)
        if t == node_id:
            out.add(s)
    return out


def _categories(node: Any) -> set[str]:
    a = _attrs(node)
    cat = a.get("category") or a.get("category_key")
    if cat:
        return {cat}
    cats = a.get("categories")
    if isinstance(cats, list):
        return {c for c in cats if isinstance(c, str)}
    return set()


def _composite(signals: dict[str, float], weights: dict[str, float]) -> float:
    return round(sum(weights.get(k, 0.0) * v for k, v in signals.items()), 4)


def recommend_related(
    nodes: list[Any],
    edges: list[Any],
    target_id: Any,
    weights: dict[str, float] | None = None,
) -> list[tuple[Any, float, dict[str, float], list[str]]]:
    """Score same-type candidates related to ``target_id``.

    Returns ``[(candidate_node, score, signals, reasons)]`` sorted by score desc.
    """
    default_weights = {
        "shared_category": 0.25,
        "shared_brand": 0.20,
        "co_purchased": 0.25,
        "shared_supplier": 0.15,
        "neighbor_similarity": 0.15,
    }
    weights = weights or default_weights
    nodes_by_id = {n.id: n for n in nodes}
    target = nodes_by_id.get(target_id)
    if target is None:
        return []
    adj = adjacency_map(nodes, edges, directed=False)
    edge_set = _edge_set(edges)

    t_attrs = _attrs(target)
    t_cats = _categories(target)
    t_brand = t_attrs.get("brand") or t_attrs.get("brand_key")
    t_type = target.node_type
    t_neighbors = {nbr for nbr, _w, _et in adj.get(target_id, [])}
    t_buyers = _related_by(edge_set, target_id, "bought_by")
    t_suppliers = _related_by(edge_set, target_id, "supplied_by")

    results: list[tuple[Any, float, dict[str, float], list[str]]] = []
    for n in nodes:
        if n.id == target_id or n.node_type != t_type:
            continue
        a = _attrs(n)
        signals: dict[str, float] = {}
        reasons: list[str] = []

        n_cats = _categories(n)
        shared_cats = t_cats & n_cats
        if shared_cats:
            signals["shared_category"] = 1.0
            reasons.append(f"shares category '{next(iter(shared_cats))}'")

        n_brand = a.get("brand") or a.get("brand_key")
        if t_brand and n_brand == t_brand:
            signals["shared_brand"] = 1.0
            reasons.append(f"shares brand '{t_brand}'")

        n_buyers = _related_by(edge_set, n.id, "bought_by")
        shared_buyers = t_buyers & n_buyers
        if shared_buyers:
            signals["co_purchased"] = 1.0
            reasons.append(f"co-purchased by {len(shared_buyers)} customer(s)")

        n_suppliers = _related_by(edge_set, n.id, "supplied_by")
        if t_suppliers & n_suppliers:
            signals["shared_supplier"] = 1.0
            reasons.append("shares a supplier")

        n_neighbors = {nbr for nbr, _w, _et in adj.get(n.id, [])}
        sim = jaccard(t_neighbors, n_neighbors)
        if sim > 0:
            signals["neighbor_similarity"] = sim
            reasons.append(f"{sim:.0%} overlapping neighbours")

        score = _composite(signals, weights)
        if score > 0:
            results.append((n, score, signals, reasons))
    results.sort(key=lambda x: x[1], reverse=True)
    return results
