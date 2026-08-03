"""Pure-stdlib statistical engine for the continuous-learning platform.

All functions are deterministic, side-effect-free and depend only on their
inputs — the same stored outcomes always reproduce the same accuracy numbers,
issues, tuned thresholds and reweights. This is what makes every learning run
versionable and explainable.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from statistics import fmean, pstdev
from typing import Any


def mae(actuals: list[float], preds: list[float]) -> float:
    """Mean absolute error."""
    if not actuals:
        return 0.0
    return fmean(abs(a - p) for a, p in zip(actuals, preds, strict=False))


def rmse(actuals: list[float], preds: list[float]) -> float:
    """Root mean squared error."""
    if not actuals:
        return 0.0
    return math.sqrt(fmean((a - p) ** 2 for a, p in zip(actuals, preds, strict=False)))


def mape(actuals: list[float], preds: list[float]) -> float:
    """Mean absolute percentage error (%). Skips zero actuals."""
    pairs = [(a, p) for a, p in zip(actuals, preds, strict=False) if a != 0]
    if not pairs:
        return 0.0
    return 100.0 * fmean(abs(a - p) / abs(a) for a, p in pairs)


def bias(actuals: list[float], preds: list[float]) -> float:
    """Mean signed error (pred - actual). Positive = over-prediction."""
    if not actuals:
        return 0.0
    return fmean(p - a for a, p in zip(actuals, preds, strict=False))


def directional_accuracy(actuals: list[float], preds: list[float]) -> float:
    """Fraction of predictions on the same side of the mean as the actual.

    A measure of whether the model gets the *direction* of the outcome right,
    which matters for risk and ranking decisions. Falls back to 0.5 when the
    data has no variation.
    """
    if len(actuals) < 2:
        return 0.0
    base = fmean(actuals)
    correct = 0
    total = 0
    for a, p in zip(actuals, preds, strict=False):
        da = a - base
        dp = p - base
        if da == 0 or dp == 0:
            continue
        total += 1
        if (da > 0) == (dp > 0):
            correct += 1
    if total == 0:
        return 0.5
    return correct / total


def pearson(xs: Iterable[float], ys: Iterable[float]) -> float:
    """Pearson correlation coefficient; 0 on zero variance / no data."""
    x = list(xs)
    y = list(ys)
    n = min(len(x), len(y))
    if n < 2:
        return 0.0
    sx = pstdev(x) if len(x) > 1 else 0.0
    sy = pstdev(y) if len(y) > 1 else 0.0
    if sx == 0 or sy == 0:
        return 0.0
    mx = fmean(x)
    my = fmean(y)
    cov = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y, strict=False)) / n
    return cov / (sx * sy)


def accuracy_summary(actuals: list[float], preds: list[float]) -> dict[str, float]:
    """Full accuracy summary for a pair of aligned sequences."""
    return {
        "n": float(len(actuals)),
        "mae": round(mae(actuals, preds), 6),
        "rmse": round(rmse(actuals, preds), 6),
        "mape": round(mape(actuals, preds), 4),
        "bias": round(bias(actuals, preds), 6),
        "directional_accuracy": round(directional_accuracy(actuals, preds), 4),
        "correlation": round(pearson(actuals, preds), 4),
    }


def rolling_accuracy(
    records: list[dict[str, Any]], window: int
) -> list[dict[str, Any]]:
    """Rolling accuracy series over time-ordered records.

    ``records`` is a list of ``{"actual": float, "pred": float, "at": str}``
    sorted ascending by time. Each entry summarises the trailing ``window``
    resolved outcomes — the accuracy-over-time dashboard series.
    """
    out: list[dict[str, Any]] = []
    for i in range(len(records)):
        lo = max(0, i - window + 1)
        chunk = records[lo : i + 1]
        actuals = [r["actual"] for r in chunk]
        preds = [r["pred"] for r in chunk]
        summary = accuracy_summary(actuals, preds)
        out.append({
            "at": records[i]["at"],
            "n": len(chunk),
            **summary,
        })
    return out


def drift(records: list[dict[str, Any]], recent_window: int = 10) -> dict[str, Any]:
    """Compare the most recent resolved outcomes against the whole history.

    Returns the recent vs baseline mean bias and a ``drifted`` flag when the
    recent bias has moved materially relative to overall variability — a simple,
    deterministic degradation detector.
    """
    if len(records) < 2:
        return {"drifted": False, "recent_bias": 0.0, "baseline_bias": 0.0, "delta": 0.0}
    actuals = [r["actual"] for r in records]
    preds = [r["pred"] for r in records]
    baseline_bias = bias(actuals, preds)
    recent = records[-recent_window:]
    recent_bias = bias([r["actual"] for r in recent], [r["pred"] for r in recent])
    scale = max(1e-9, abs(baseline_bias), pstdev(actuals) if len(actuals) > 1 else 0.0)
    delta = recent_bias - baseline_bias
    drifted = abs(delta) > 0.25 * scale
    return {
        "drifted": drifted,
        "recent_bias": round(recent_bias, 6),
        "baseline_bias": round(baseline_bias, 6),
        "delta": round(delta, 6),
    }


def _confusion(predicted_pos: list[bool], actual_pos: list[bool]) -> dict[str, int]:
    tp = fp = tn = fn = 0
    for pp, ap in zip(predicted_pos, actual_pos, strict=False):
        if ap and pp:
            tp += 1
        elif ap and not pp:
            fn += 1
        elif not ap and pp:
            fp += 1
        else:
            tn += 1
    return {"tp": tp, "fp": fp, "tn": tn, "fn": fn}


def _f1(cm: dict[str, int]) -> float:
    precision = cm["tp"] / (cm["tp"] + cm["fp"]) if (cm["tp"] + cm["fp"]) else 0.0
    recall = cm["tp"] / (cm["tp"] + cm["fn"]) if (cm["tp"] + cm["fn"]) else 0.0
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def optimize_threshold(pairs: list[tuple[float, float]]) -> dict[str, Any]:
    """Find the classification threshold that best separates binary outcomes.

    ``pairs`` is a list of ``(score, actual_label)`` where ``actual_label`` is
    0/1. A grid search over midpoints of the observed scores maximises F1,
    returning the tuned threshold plus confusion metrics and the improvement
    over the naive midpoint.
    """
    if len(pairs) < 2:
        return {"threshold": None, "score": 0.0, "tp": 0, "fp": 0, "tn": 0, "fn": 0}
    scores = sorted({p[0] for p in pairs})
    labels = [bool(p[1]) for p in pairs]
    best: dict[str, Any] = {"score": -1.0}
    for idx in range(len(scores) - 1):
        t = (scores[idx] + scores[idx + 1]) / 2.0
        predicted = [s >= t for s, _ in pairs]
        cm = _confusion(predicted, labels)
        s = _f1(cm)
        if s > best["score"]:
            best = {"threshold": t, "score": round(s, 4), **cm}
    # Also consider classifying everything below the lowest score as positive.
    for t in (scores[0] - 1.0, scores[-1] + 1.0):
        predicted = [s >= t for s, _ in pairs]
        cm = _confusion(predicted, labels)
        s = _f1(cm)
        if s > best["score"]:
            best = {"threshold": t, "score": round(s, 4), **cm}
    return best


def reweight_feature(
    values: list[float],
    errors: list[float],
    current_weight: float,
    min_weight: float = 0.05,
    max_scale: float = 2.0,
) -> dict[str, Any]:
    """Suggest a new weight for a feature based on its error correlation.

    A feature whose value correlates with the prediction error is mis-calibrated:
    positively-correlated features are down-weighted, negatively-correlated ones
    are up-weighted. Deterministic and explainable.
    """
    corr = pearson(values, errors)
    if math.isnan(corr):
        corr = 0.0
    factor = max(0.2, 1.0 - corr)
    suggested = max(min_weight, min(current_weight * factor, current_weight * max_scale))
    change_pct = (suggested - current_weight) / current_weight if current_weight else 0.0
    explanation = (
        f"Feature value correlates with prediction error (r={corr:.3f}); "
        f"weight {current_weight:.4f} -> {suggested:.4f} ({change_pct:+.1%})"
    )
    return {
        "correlation": round(corr, 4),
        "current_weight": current_weight,
        "suggested_weight": round(suggested, 4),
        "change_pct": round(change_pct, 4),
        "explanation": explanation,
    }


# Decision-type -> issue classification.
ISSUE_TYPE_BY_DECISION = {
    "rule": "bad_rule",
    "prompt": "weak_prompt",
    "ai_decision": "poor_decision",
    "match": "incorrect_match",
    "ranking": "ranking_mistake",
}

# Which improvement target(s) each decision-type maps to.
TARGETS_BY_DECISION = {
    "rule": ["rule_threshold"],
    "prompt": ["prompt"],
    "ai_decision": ["prompt"],
    "match": ["matching_algorithm"],
    "ranking": ["matching_algorithm"],
}

# Numeric forecast metrics that can also justify a forecast-model recommendation.
FORECAST_METRICS = {"profit", "sales", "roi"}


def _severity(summary: dict[str, float]) -> float:
    scale = max(1e-9, abs(summary.get("bias", 0.0)), summary.get("mae", 0.0))
    norm_mae = summary["mae"] / scale if scale > 1e-9 else 0.0
    return 0.6 * min(1.0, norm_mae) + 0.4 * (1.0 - summary["directional_accuracy"])


def scan_issues(
    predictions: list[dict[str, Any]],
    *,
    min_samples: int = 5,
    severity_threshold: float = 0.4,
) -> list[dict[str, Any]]:
    """Automatically identify bad rules / weak prompts / poor decisions /
    incorrect matches / ranking mistakes from resolved predictions.

    Predictions with an ``actual_value`` are grouped by (decision_type,
    decision_id-or-model-version); groups with at least ``min_samples`` outcomes
    that clear ``severity_threshold`` are flagged as issues.
    """
    resolved = [p for p in predictions if p.get("actual") is not None]
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for p in resolved:
        gid = p.get("decision_id") or p.get("model_version") or "global"
        groups.setdefault((p["decision_type"], gid), []).append(p)

    issues: list[dict[str, Any]] = []
    for (decision_type, gid), group in groups.items():
        if len(group) < min_samples:
            continue
        actuals = [g["actual"] for g in group]
        preds = [g["pred"] for g in group]
        summary = accuracy_summary(actuals, preds)
        severity = _severity(summary)
        if severity < severity_threshold:
            continue
        scale = max(1e-9, abs(summary["bias"]), summary["mae"])
        mode = "degraded accuracy"
        if summary["bias"] > 0.2 * scale:
            mode = "over-prediction"
        elif summary["bias"] < -0.2 * scale:
            mode = "under-prediction"
        issues.append({
            "issue_type": ISSUE_TYPE_BY_DECISION[decision_type],
            "decision_type": decision_type,
            "decision_id": gid,
            "model_version": group[0].get("model_version"),
            "prediction_type": group[0].get("prediction_type"),
            "sample_size": len(group),
            "mae": summary["mae"],
            "bias": summary["bias"],
            "directional_accuracy": summary["directional_accuracy"],
            "correlation": summary["correlation"],
            "severity": round(severity, 4),
            "mode": mode,
        })
    return sorted(issues, key=lambda i: i["severity"], reverse=True)
