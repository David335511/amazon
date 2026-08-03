"""Pure ranking / highlighting / recommendation math for reverse sourcing.

Deterministic and stdlib-only (unit-testable). Given a set of supplier offers
(and optional supplier-intelligence scores), it ranks suppliers, picks the
highlights (best / cheapest / fastest / highest-confidence), and generates
sourcing recommendations + a summary.
"""

from __future__ import annotations

from typing import Any

from app.reverse_sourcing.offer import Offer


def _weighted(values: list[float], weights: list[float]) -> float:
    total = sum(weights)
    if total <= 0:
        return 0.0
    return sum(v * w for v, w in zip(values, weights, strict=True)) / total


def rank_offers(
    offers: list[Offer],
    intel: dict[str, dict[str, float]],
    weights: list[float],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Rank offers by a weighted score. Returns (ranking, score_map)."""
    if not offers:
        return [], {}

    landed = [o.landed_cost for o in offers]
    min_landed, max_landed = min(landed), max(landed)
    days = [o.shipping_days for o in offers]
    max_days = max(days) if days else 0

    score_map: dict[str, dict[str, Any]] = {}
    for o in offers:
        price_score = 1.0 if max_landed == min_landed else 1.0 - (o.landed_cost - min_landed) / (max_landed - min_landed)
        speed_score = 1.0 if max_days == 0 else 1.0 - o.shipping_days / max_days
        avail = 1.0 if o.in_stock else 0.3
        rel = intel.get(o.supplier_code, {}).get("reliability", 0.5)
        risk_inv = 1.0 - intel.get(o.supplier_code, {}).get("risk", 0.5)
        comps = {
            "price": price_score,
            "speed": speed_score,
            "availability": avail,
            "discount": o.current_discount,
            "reliability": rel,
            "risk_inverse": risk_inv,
        }
        score_map[o.supplier_code] = {
            "score": _weighted(
                [price_score, speed_score, avail, o.current_discount, rel, risk_inv], weights
            ),
            "components": comps,
        }

    ordered = sorted(offers, key=lambda o: score_map[o.supplier_code]["score"], reverse=True)
    ranking = []
    for i, o in enumerate(ordered, 1):
        ranking.append(
            {
                "supplier_code": o.supplier_code,
                "supplier_name": o.supplier_name,
                "score": round(score_map[o.supplier_code]["score"], 4),
                "rank": i,
                "components": score_map[o.supplier_code]["components"],
            }
        )
    return ranking, score_map


def _by_code(offers: list[Offer]) -> dict[str, Offer]:
    return {o.supplier_code: o for o in offers}


def _highlight(code: str, offers: list[Offer], ranking: list[dict[str, Any]], reason: str) -> dict[str, Any]:
    o = _by_code(offers)[code]
    score = next((r["score"] for r in ranking if r["supplier_code"] == code), 0.0)
    return {
        "supplier_code": code,
        "supplier_name": o.supplier_name,
        "reason": reason,
        "landed_cost": round(o.landed_cost, 2),
        "shipping_days": o.shipping_days,
        "score": round(score, 4),
    }


def highlights(
    offers: list[Offer],
    ranking: list[dict[str, Any]],
    intel: dict[str, dict[str, float]],
) -> dict[str, dict[str, Any]]:
    """Pick best / cheapest / fastest / highest-confidence suppliers."""
    if not offers:
        return {}
    by_code = _by_code(offers)
    best_code = ranking[0]["supplier_code"] if ranking else offers[0].supplier_code

    cheapest = min(offers, key=lambda o: o.landed_cost)
    fastest = min(
        [o for o in offers if o.shipping_days > 0] or offers,
        key=lambda o: (o.shipping_days, o.landed_cost),
    )

    def confidence(code: str) -> float:
        return intel.get(code, {}).get("confidence", 0.0)

    highest_confidence = max(
        offers, key=lambda o: (confidence(o.supplier_code), -by_code[o.supplier_code].landed_cost)
    )

    return {
        "best": _highlight(best_code, offers, ranking, "highest ranked supplier"),
        "cheapest": _highlight(cheapest.supplier_code, offers, ranking, "lowest landed cost"),
        "fastest": _highlight(fastest.supplier_code, offers, ranking, "fastest shipping"),
        "highest_confidence": _highlight(
            highest_confidence.supplier_code, offers, ranking, "most historical data / highest confidence"
        ),
    }


def recommendations(
    offers: list[Offer],
    highlights: dict[str, dict[str, Any]],
    predicted: dict[str, float | None],
    intel: dict[str, dict[str, float]],
) -> list[str]:
    """Generate actionable sourcing recommendations."""
    out: list[str] = []
    best = highlights.get("best")
    cheapest = highlights.get("cheapest")
    fastest = highlights.get("fastest")
    hc = highlights.get("highest_confidence")

    if best:
        out.append(
            f"Buy from {best['supplier_name']} ({best['supplier_code']}): landed cost "
            f"${best['landed_cost']:.2f}, ~{best['shipping_days']} day shipping."
        )
    if cheapest and cheapest["supplier_code"] != (best or {}).get("supplier_code"):
        out.append(
            f"For lowest cost, source from {cheapest['supplier_name']} "
            f"({cheapest['supplier_code']}) at ${cheapest['landed_cost']:.2f} landed."
        )
    if fastest and fastest["supplier_code"] != (best or {}).get("supplier_code"):
        out.append(
            f"For fastest delivery, use {fastest['supplier_name']} "
            f"({fastest['supplier_code']}) at ~{fastest['shipping_days']} days."
        )
    if hc and hc["supplier_code"] != (best or {}).get("supplier_code"):
        out.append(
            f"Highest-confidence source: {hc['supplier_name']} ({hc['supplier_code']})."
        )

    for code, pred in predicted.items():
        if pred is not None and pred >= 0.1:
            name = next((o.supplier_name for o in offers if o.supplier_code == code), code)
            out.append(
                f"{name} ({code}) is predicted ~{pred * 100:.0f}% off next period; "
                "consider timing the purchase."
            )

    for code, scores in intel.items():
        if scores.get("risk", 0.0) >= 0.6:
            name = next((o.supplier_name for o in offers if o.supplier_code == code), code)
            out.append(
                f"{name} ({code}) has elevated risk ({scores['risk']:.2f}); keep a backup supplier."
            )
    return out


def build_summary(asin: str, ranking: list[dict[str, Any]], highlights: dict[str, dict[str, Any]]) -> str:
    """One-paragraph summary of the reverse-sourcing run."""
    n = len(ranking)
    best = highlights.get("best")
    part = f"Reverse sourcing for ASIN {asin}: evaluated {n} supplier(s)."
    if best:
        part += (
            f" Recommended supplier is {best['supplier_name']} ({best['supplier_code']}) "
            f"with landed cost ${best['landed_cost']:.2f}."
        )
    else:
        part += " No suppliers currently carry this product."
    return part
