"""Explainable graph reasoning.

Turns raw graph results into human-readable, step-by-step explanations so every
answer from the knowledge graph can be audited. All explanations are
deterministic and reference the actual evidence (paths, shared attributes,
community members, opportunity features).
"""

from __future__ import annotations

from typing import Any


def label_for(node: Any) -> str:
    return node.label or str(node.key)


def explain_path(
    nodes_by_id: dict[Any, Any],
    path: list[Any],
    total_weight: float | None = None,
) -> dict[str, Any]:
    """Explain a shortest-path result as a hop-by-hop reasoning trace."""
    steps: list[dict[str, Any]] = []
    for i, node_id in enumerate(path):
        node = nodes_by_id.get(node_id)
        steps.append(
            {
                "step": i,
                "node_id": str(node_id),
                "node_type": node.node_type if node else "?",
                "label": label_for(node) if node else str(node_id),
            }
        )
    summary = (
        f"Path of {len(path)} node(s): " + " → ".join(s["label"] for s in steps)
    )
    if total_weight is not None:
        summary += f" (total weight {total_weight:.2f})"
    return {"summary": summary, "steps": steps}


def explain_recommendation(target: Any, candidate: Any, score: float, reasons: list[str]) -> str:
    """Explain one recommendation with its contributing signals."""
    base = f"'{label_for(candidate)}' is recommended alongside '{label_for(target)}' "
    base += f"(score {score:.3f})"
    if reasons:
        base += " because it " + "; ".join(reasons) + "."
    else:
        base += "."
    return base


def explain_recommendations(target: Any, ranked: list[tuple[Any, float, dict[str, float], list[str]]]) -> dict[str, Any]:
    """Explain a full recommendation list."""
    summary = f"Recommendations for '{label_for(target)}' ({len(ranked)} candidate(s))."
    items = [
        {
            "candidate": label_for(n),
            "candidate_id": str(n.id),
            "score": score,
            "signals": signals,
            "reasoning": explain_recommendation(target, n, score, reasons),
        }
        for n, score, signals, reasons in ranked
    ]
    return {"summary": summary, "items": items}


def explain_cluster(cluster: dict[str, Any]) -> str:
    top = ", ".join(cluster.get("top_products", []) or [])
    return (
        f"Cluster {cluster['id']} contains {cluster['node_count']} node(s) "
        f"({cluster['product_count']} product(s)) with aggregate profit "
        f"${cluster['profit']:,.2f} and mean ROI {cluster['roi']:.2%}. "
        + (f"Notable products: {top}." if top else "")
    )


def explain_opportunity(opp: dict[str, Any]) -> str:
    return f"{opp['title']}. {opp['description']}"
