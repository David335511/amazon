"""Profitable clusters and hidden opportunities.

Pure functions over the in-memory graph:

- ``profitable_clusters`` — group nodes into communities (label propagation),
  aggregate per-community profit / ROI, and surface the clusters that clear a
  profit threshold.
- ``hidden_opportunities`` — structural gaps worth investigating: profitable
  products with no supplier, single-supplier dependencies, underserved
  categories, underutilised suppliers, and products not listed on any
  marketplace.
"""

from __future__ import annotations

import json
from typing import Any

from app.knowledge_graph.engine import adjacency_map, label_propagation


def _attrs(node: Any) -> dict[str, Any]:
    raw = getattr(node, "attributes_json", None)
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return {}


def profitable_clusters(
    nodes: list[Any],
    edges: list[Any],
    min_profit: float = 0.0,
    top_k: int = 10,
) -> list[dict[str, Any]]:
    """Rank communities by aggregate profit (from node attributes)."""
    adj = adjacency_map(nodes, edges, directed=False)
    communities = label_propagation(adj)
    nodes_by_id = {n.id: n for n in nodes}
    results: list[dict[str, Any]] = []
    for cid, members in communities.items():
        member_nodes = [nodes_by_id[m] for m in members if m in nodes_by_id]
        profit = 0.0
        roi_sum = 0.0
        product_count = 0
        top_products: list[str] = []
        for n in member_nodes:
            a = _attrs(n)
            profit += float(a.get("profit", 0.0))
            roi_sum += float(a.get("roi", 0.0))
            if n.node_type == "product":
                product_count += 1
                top_products.append(n.label or n.key)
        if profit >= min_profit:
            results.append(
                {
                    "id": cid,
                    "node_count": len(member_nodes),
                    "product_count": product_count,
                    "profit": round(profit, 2),
                    "roi": round(roi_sum / max(1, len(member_nodes)), 4),
                    "top_products": top_products[:5],
                }
            )
    results.sort(key=lambda x: x["profit"], reverse=True)
    return results[:top_k]


def hidden_opportunities(
    nodes: list[Any],
    edges: list[Any],
    top_k: int = 20,
) -> list[dict[str, Any]]:
    """Discover structural gaps / opportunities in the graph."""
    nodes_by_id = {n.id: n for n in nodes}
    edge_set = {(e.source_id, e.target_id, e.edge_type) for e in edges}

    products = [n for n in nodes if n.node_type == "product"]
    suppliers = {n.id for n in nodes if n.node_type == "supplier"}
    marketplaces = {n.id for n in nodes if n.node_type == "marketplace"}
    categories = {n.id for n in nodes if n.node_type == "category"}
    categories_by_id = {c.id: c for c in nodes if c.node_type == "category"}

    def related(node_id: Any, edge_type: str) -> set[Any]:
        out: set[Any] = set()
        for s, t, et in edge_set:
            if et != edge_type:
                continue
            if s == node_id:
                out.add(t)
            if t == node_id:
                out.add(s)
        return out

    opportunities: list[dict[str, Any]] = []

    # 1) Profitable product with no supplier connected.
    for p in products:
        a = _attrs(p)
        profit = float(a.get("profit", 0.0))
        if profit > 0 and not (related(p.id, "supplied_by") & suppliers):
            opportunities.append(
                {
                    "type": "unconnected_profitable_product",
                    "title": f"Unconnected profitable product: {p.label or p.key}",
                    "description": (
                        f"This product is profitable (${profit:,.2f}) but has no "
                        "supplier. Sourcing it could unlock the profit."
                    ),
                    "score": round(min(profit, 100.0), 2),
                    "nodes": [p.id],
                }
            )

    # 2) Profitable product with a single-supplier dependency (supply risk).
    for p in products:
        a = _attrs(p)
        profit = float(a.get("profit", 0.0))
        supps = related(p.id, "supplied_by") & suppliers
        if profit > 0 and len(supps) == 1:
            opportunities.append(
                {
                    "type": "single_supplier_dependency",
                    "title": f"Single-supplier risk: {p.label or p.key}",
                    "description": (
                        "This profitable product depends on exactly one supplier "
                        "(${profit:,.2f} at risk). Adding a second supplier reduces "
                        "supply risk."
                    ),
                    "score": round(min(profit, 100.0), 2),
                    "nodes": [p.id, next(iter(supps))],
                }
            )

    # 3) Under-utilised supplier (fewer than 2 profitable products sourced).
    for sid in suppliers:
        prod_ids = related(sid, "supplied_by") & {n.id for n in products}
        profitable = [
            p for p in products if p.id in prod_ids and float(_attrs(p).get("profit", 0.0)) > 0
        ]
        if len(profitable) < 2 and len(prod_ids) >= 0:
            supp = nodes_by_id.get(sid)
            opportunities.append(
                {
                    "type": "underutilised_supplier",
                    "title": f"Under-utilised supplier: {supp.label if supp else sid}",
                    "description": (
                        f"Supplier sources {len(prod_ids)} product(s) but only "
                        f"{len(profitable)} are profitable. Expanding this supplier's "
                        "profitable product range may be low-effort."
                    ),
                    "score": round(1.0 - min(len(profitable), 2) / 2.0, 2),
                    "nodes": [sid],
                }
            )

    # 4) Underserved category: many products but zero suppliers.
    for cid in categories:
        cat_products = [p for p in products if cid in related(p.id, "belongs_to")]
        if len(cat_products) >= 2:
            cat_suppliers = set()
            for p in cat_products:
                cat_suppliers |= related(p.id, "supplied_by") & suppliers
            if not cat_suppliers:
                cat = categories_by_id.get(cid)
                opportunities.append(
                    {
                        "type": "underserved_category",
                        "title": f"Underserved category: {cat.label if cat else cid}",
                        "description": (
                            f"{len(cat_products)} products in this category have no "
                            "supplier. Entering this category as a supplier has no "
                            "competition in the graph."
                        ),
                        "score": round(min(len(cat_products), 5) / 5.0, 2),
                        "nodes": [cid] + [p.id for p in cat_products[:5]],
                    }
                )

    # 5) Profitable product not listed on any marketplace.
    for p in products:
        a = _attrs(p)
        profit = float(a.get("profit", 0.0))
        if profit > 0 and not (related(p.id, "sells_on") & marketplaces):
            opportunities.append(
                {
                    "type": "unlisted_marketplace",
                    "title": f"Unlisted profitable product: {p.label or p.key}",
                    "description": (
                        f"This product is profitable (${profit:,.2f}) but is not "
                        "listed on any marketplace. Adding a marketplace listing "
                        "could increase reach."
                    ),
                    "score": round(min(profit, 100.0), 2),
                    "nodes": [p.id],
                }
            )

    opportunities.sort(key=lambda x: x["score"], reverse=True)
    return opportunities[:top_k]
