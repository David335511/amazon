"""Pure statistics for the experimentation platform (deterministic, stdlib only).

Everything is a pure function of the stored observations, so any experiment can
be reproduced exactly: the same observations produce the same winner, confidence,
impact and report every time.

Implemented (no third-party stats library):

- **Two-proportion z-test** — for binary metrics (conversion, accuracy,
  precision, recall): A/B variant vs control significance.
- **Welch's t-test** — for continuous metrics (profit, ROI, value), using a
  regularized incomplete-beta t CDF (accurate for small samples).
- **Confusion metrics** — precision, recall, accuracy, F1, false positives,
  false negatives for prediction / scoring / LLM comparisons.
- **Deterministic variant assignment** — ``seed + subject_key`` hashes to a
  stable variant, so re-running yields the identical split.
- **Winner determination** — the best variant whose uplift is statistically
  significant vs the control at ``alpha``, with confidence = ``1 - p_value``.
- **Sample-size planning** — how many observations per variant a minimum
  detectable effect needs (normal inverse CDF, Acklam's approximation).

Everything is round-trippable: ``variant_stats`` -> ``determine_winner`` -> the
report is a pure pipeline.
"""

from __future__ import annotations

import hashlib
import math
from typing import Any

# ──────────────────────────────────────────────────────────────
# Normal distribution helpers
# ──────────────────────────────────────────────────────────────


def normal_cdf(x: float) -> float:
    """Standard-normal CDF via the error function."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def normal_ppf(p: float) -> float:
    """Standard-normal inverse CDF (Acklam's rational approximation)."""
    if p <= 0.0:
        return -math.inf
    if p >= 1.0:
        return math.inf
    a = [
        -3.969683028665376e01, 2.209460984245205e02, -2.759285104469687e02,
        1.383577518672690e02, -3.066479806614716e01, 2.506628277459239e00,
    ]
    b = [
        -5.447609879822406e01, 1.615858368580409e02, -1.556989798598866e02,
        6.680131188771972e01, -1.328068155288572e01,
    ]
    c = [
        -7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e00,
        -2.549732539343734e00, 4.374664141464968e00, 2.938163982698783e00,
    ]
    d = [
        7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00,
        3.754408661907416e00,
    ]
    plow, phigh = 0.02425, 1.0 - 0.02425
    if p < plow:
        q = math.sqrt(-2.0 * math.log(p))
        return (
            (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5])
            / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
        )
    if p > phigh:
        q = math.sqrt(-2.0 * math.log(1.0 - p))
        return -(
            (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5])
            / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
        )
    q = p - 0.5
    r = q * q
    return (
        (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5])
        * q
        / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0)
    )


# ──────────────────────────────────────────────────────────────
# Student's t CDF (regularized incomplete beta)
# ──────────────────────────────────────────────────────────────


def _betacf(a: float, b: float, x: float, itermax: int = 200, eps: float = 3e-7) -> float:
    """Continued-fraction evaluation of the incomplete beta function."""
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < 1e-30:
        d = 1e-30
    d = 1.0 / d
    h = d
    for m in range(1, itermax + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + aa / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + aa / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def _betai(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta function I_x(a, b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    bt = math.exp(
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
        + a * math.log(x) + b * math.log(1.0 - x)
    )
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def t_cdf(t: float, df: float) -> float:
    """Student's t CDF (two-sided supported via caller)."""
    if df <= 0:
        return 0.5
    x = df / (df + t * t)
    if t >= 0:
        return 1.0 - 0.5 * _betai(df / 2.0, 0.5, x)
    return 0.5 * _betai(df / 2.0, 0.5, x)


# ──────────────────────────────────────────────────────────────
# Hypothesis tests
# ──────────────────────────────────────────────────────────────


def two_proportion_ztest(
    successes_a: float, n_a: float, successes_b: float, n_b: float
) -> dict[str, float] | None:
    """Two-proportion z-test; ``a`` is the variant, ``b`` is the control.

    Returns ``{z, p_value, confidence, uplift}`` or ``None`` if either arm has
    no observations.
    """
    if n_a <= 0 or n_b <= 0:
        return None
    p_a = successes_a / n_a
    p_b = successes_b / n_b
    p_pool = (successes_a + successes_b) / (n_a + n_b)
    if 0.0 < p_pool < 1.0:
        se = math.sqrt(p_pool * (1.0 - p_pool) * (1.0 / n_a + 1.0 / n_b))
        z = (p_a - p_b) / se if se > 0 else 0.0
    else:
        z = 0.0
    p_value = 2.0 * (1.0 - normal_cdf(abs(z)))
    uplift = (p_a - p_b) / p_b if p_b > 0 else (p_a - p_b)
    return {"z": z, "p_value": p_value, "confidence": 1.0 - p_value, "uplift": uplift}


def welch_df(var_a: float, n_a: float, var_b: float, n_b: float) -> float:
    """Welch-Satterthwaite degrees of freedom."""
    if n_a <= 1 or n_b <= 1:
        return n_a + n_b - 2
    den = (var_a / n_a) ** 2 / (n_a - 1) + (var_b / n_b) ** 2 / (n_b - 1)
    if den <= 0:
        return n_a + n_b - 2
    return (var_a / n_a + var_b / n_b) ** 2 / den


def welch_ttest(
    mean_a: float, var_a: float, n_a: float,
    mean_b: float, var_b: float, n_b: float,
) -> dict[str, float] | None:
    """Welch's t-test; ``a`` is the variant, ``b`` is the control.

    Returns ``{t, df, p_value, confidence, uplift}`` or ``None`` if either arm
    has fewer than 2 observations (variance undefined).
    """
    if n_a < 2 or n_b < 2:
        return None
    se = math.sqrt(var_a / n_a + var_b / n_b)
    if se == 0:
        if mean_a == mean_b:
            return {
                "t": 0.0, "df": n_a + n_b - 2, "p_value": 1.0,
                "confidence": 0.0, "uplift": 0.0,
            }
        t = 1e15
    else:
        t = (mean_a - mean_b) / se
    df = welch_df(var_a, n_a, var_b, n_b)
    p_value = 2.0 * (1.0 - t_cdf(abs(t), df))
    p_value = max(0.0, min(1.0, p_value))
    return {
        "t": t, "df": df, "p_value": p_value,
        "confidence": 1.0 - p_value, "uplift": mean_a - mean_b,
    }


def required_sample_size(
    conversion_a: float, conversion_b: float, alpha: float = 0.05, power: float = 0.8
) -> int:
    """Per-arm sample size needed to detect ``conversion_a -> conversion_b``."""
    diff = conversion_b - conversion_a
    if diff == 0:
        return 0
    z_alpha = normal_ppf(1.0 - alpha / 2.0)
    z_beta = normal_ppf(power)
    p_pool = (conversion_a + conversion_b) / 2.0
    sd = math.sqrt(conversion_a * (1.0 - conversion_a) + conversion_b * (1.0 - conversion_b))
    n = (
        z_alpha * math.sqrt(2.0 * p_pool * (1.0 - p_pool))
        + z_beta * sd
    ) ** 2 / (diff * diff)
    return math.ceil(max(n, 0.0))


# ──────────────────────────────────────────────────────────────
# Deterministic assignment
# ──────────────────────────────────────────────────────────────


def assign_variant(subject_key: str, seed: int, num_variants: int) -> int:
    """Deterministically map a subject to a variant index in ``[0, num_variants)``.

    Uses a stable SHA-256 of ``"{seed}:{subject_key}"`` so the same subject under
    the same seed always lands on the same variant — including across process
    restarts and deployments (unlike Python's process-randomized builtin
    ``hash()``), which is what makes experiment splits reproducible.
    """
    if num_variants <= 0:
        return 0
    digest = hashlib.sha256(f"{seed}:{subject_key}".encode()).hexdigest()
    return int(digest[:8], 16) % num_variants


# ──────────────────────────────────────────────────────────────
# Confusion metrics
# ──────────────────────────────────────────────────────────────


def confusion_metrics(
    predicted: list[bool], ground_truth: list[bool]
) -> dict[str, Any]:
    """Precision / recall / accuracy / F1 / FP / FN from two aligned label lists."""
    tp = fp = tn = fn = 0
    for p, g in zip(predicted, ground_truth, strict=False):
        if bool(g):
            if bool(p):
                tp += 1
            else:
                fn += 1
        else:
            if bool(p):
                fp += 1
            else:
                tn += 1
    total = tp + fp + tn + fn
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    accuracy = (tp + tn) / total if total > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    return {
        "true_positives": tp,
        "false_positives": fp,
        "true_negatives": tn,
        "false_negatives": fn,
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "accuracy": round(accuracy, 6),
        "f1": round(f1, 6),
    }


# ──────────────────────────────────────────────────────────────
# Variant aggregation
# ──────────────────────────────────────────────────────────────


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _variance(values: list[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    m = _mean(values)
    return sum((v - m) ** 2 for v in values) / (n - 1)


def variant_stats(
    observations: list[Any], _primary_metric: str
) -> dict[str, dict[str, Any]]:
    """Aggregate observations (objects with variant_key + metric attributes).

    Each observation exposes ``variant_key``, ``outcome``, ``profit``, ``roi``,
    ``value``, ``predicted``, ``ground_truth`` (nullable). Returns per-variant
    summary stats keyed by ``variant_key``.
    """
    groups: dict[str, list[Any]] = {}
    for o in observations:
        groups.setdefault(o.variant_key, []).append(o)

    stats: dict[str, dict[str, Any]] = {}
    for key, items in groups.items():
        n = len(items)
        outcomes = [bool(o.outcome) for o in items if o.outcome is not None]
        successes = sum(outcomes)
        profits = [float(o.profit) for o in items if o.profit is not None]
        rois = [float(o.roi) for o in items if o.roi is not None]
        values = [float(o.value) for o in items if o.value is not None]
        predicted = [bool(o.predicted) for o in items if o.predicted is not None]
        truth = [bool(o.ground_truth) for o in items if o.ground_truth is not None]
        conf = confusion_metrics(predicted, truth) if predicted and truth else None

        stats[key] = {
            "key": key,
            "n": n,
            "successes": successes,
            "conversion": round(successes / n, 6) if n else 0.0,
            "mean_profit": round(_mean(profits), 6),
            "var_profit": _variance(profits),
            "mean_roi": round(_mean(rois), 6),
            "var_roi": _variance(rois),
            "mean_value": round(_mean(values), 6),
            "var_value": _variance(values),
            "confusion": conf,
        }
    return stats


# ──────────────────────────────────────────────────────────────
# Winner determination
# ──────────────────────────────────────────────────────────────


def _comparison(
    entry: dict[str, Any], control: dict[str, Any], alpha: float, primary_metric: str
) -> dict[str, Any] | None:
    """Significance comparison of one variant vs the control for a metric."""
    if primary_metric == "conversion":
        res = two_proportion_ztest(
            entry["successes"], entry["n"], control["successes"], control["n"]
        )
        if res is None:
            return None
        better = entry["conversion"] > control["conversion"]
        return {
            "p_value": res["p_value"], "confidence": res["confidence"],
            "better": better, "uplift": res["uplift"],
            "significant": better and res["p_value"] < alpha,
        }
    if primary_metric in ("accuracy", "precision", "recall"):
        e = entry["confusion"]
        c = control["confusion"]
        if e is None or c is None:
            return None
        if primary_metric == "accuracy":
            count_a, den_a = e["true_positives"] + e["true_negatives"], entry["n"]
            count_b, den_b = c["true_positives"] + c["true_negatives"], control["n"]
        elif primary_metric == "precision":
            count_a, den_a = e["true_positives"], e["true_positives"] + e["false_positives"]
            count_b, den_b = c["true_positives"], c["true_positives"] + c["false_positives"]
        else:  # recall
            count_a, den_a = e["true_positives"], e["true_positives"] + e["false_negatives"]
            count_b, den_b = c["true_positives"], c["true_positives"] + c["false_negatives"]
        res = two_proportion_ztest(count_a, den_a, count_b, den_b)
        if res is None:
            return None
        score_a = e[primary_metric]
        score_b = c[primary_metric]
        better = score_a > score_b
        return {
            "p_value": res["p_value"], "confidence": res["confidence"],
            "better": better, "uplift": score_a - score_b,
            "significant": better and res["p_value"] < alpha,
        }
    if primary_metric == "f1":
        score_a = (entry["confusion"] or {}).get("f1", 0.0)
        score_b = (control["confusion"] or {}).get("f1", 0.0)
        better = score_a > score_b
        return {
            "p_value": None, "confidence": 0.0, "better": better,
            "uplift": score_a - score_b, "significant": better,
        }
    # continuous: profit / roi / value
    field = primary_metric
    res = welch_ttest(
        entry[f"mean_{field}"], entry[f"var_{field}"], entry["n"],
        control[f"mean_{field}"], control[f"var_{field}"], control["n"],
    )
    if res is None:
        return None
    better = entry[f"mean_{field}"] > control[f"mean_{field}"]
    return {
        "p_value": res["p_value"], "confidence": res["confidence"],
        "better": better, "uplift": res["uplift"],
        "significant": better and res["p_value"] < alpha,
    }


def score_of(entry: dict[str, Any], primary_metric: str) -> float:
    """The scalar score a variant is ranked by for a metric."""
    if primary_metric == "conversion":
        return entry["conversion"]
    if primary_metric in ("accuracy", "precision", "recall", "f1"):
        return (entry["confusion"] or {}).get(primary_metric, 0.0)
    return entry.get(f"mean_{primary_metric}", 0.0)


def determine_winner(
    stats: dict[str, dict[str, Any]],
    control_key: str | None,
    alpha: float,
    primary_metric: str,
) -> dict[str, Any]:
    """Pick the statistically-significant best variant vs the control.

    Returns ``{winner_key, winner_label, confidence, significant, leading_key,
    p_value, comparisons, control_key, metric}``. ``winner_key`` is ``None`` when
    no variant beats the control significantly (or there is no control / data).
    ``leading_key`` is always the top-scoring variant (even if not significant).
    """
    if not stats:
        return _winner_result(None, None, alpha, primary_metric, control_key, {})
    if control_key is None or control_key not in stats:
        leading = max(stats, key=lambda k: score_of(stats[k], primary_metric))
        return _winner_result(None, leading, alpha, primary_metric, control_key, {})
    control = stats[control_key]

    comparisons: dict[str, Any] = {}
    significant_candidates: list[tuple[str, dict[str, Any]]] = []
    for key, entry in stats.items():
        if key == control_key:
            continue
        comp = _comparison(entry, control, alpha, primary_metric)
        if comp is None:
            continue
        comparisons[key] = comp
        if comp["significant"] and comp["better"]:
            significant_candidates.append((key, comp))

    if significant_candidates:
        winner_key = max(
            significant_candidates,
            key=lambda kv: (kv[1]["uplift"], score_of(stats[kv[0]], primary_metric)),
        )[0]
        comp = comparisons[winner_key]
        return _winner_result(
            winner_key, winner_key, alpha, primary_metric, control_key, comparisons,
            confidence=comp["confidence"], p_value=comp["p_value"],
        )

    leading = max(stats, key=lambda k: score_of(stats[k], primary_metric))
    return _winner_result(None, leading, alpha, primary_metric, control_key, comparisons)


def _winner_result(
    winner_key: str | None,
    leading_key: str | None,
    alpha: float,
    primary_metric: str,
    control_key: str | None,
    comparisons: dict[str, Any],
    confidence: float | None = None,
    p_value: float | None = None,
) -> dict[str, Any]:
    return {
        "winner_key": winner_key,
        "winner_label": None,
        "confidence": confidence,
        "significant": winner_key is not None,
        "leading_key": leading_key,
        "p_value": p_value,
        "comparisons": comparisons,
        "control_key": control_key,
        "metric": primary_metric,
        "alpha": alpha,
    }


# ──────────────────────────────────────────────────────────────
# Reproducible simulation (planning / demo)
# ──────────────────────────────────────────────────────────────


def simulate_ab(
    n: int,
    base_conversion: float,
    effect_size: float,
    seed: int = 42,
    alpha: float = 0.05,
) -> dict[str, Any]:
    """Deterministically simulate an A/B experiment and report its outcome.

    Outcomes are generated with a seeded RNG, so the exact same inputs always
    produce the exact same simulated observations and winner.
    """
    import random

    rng = random.Random(seed)
    control = [1.0 if rng.random() < base_conversion else 0.0 for _ in range(n)]
    variant = [
        1.0 if rng.random() < min(1.0, base_conversion + effect_size) else 0.0
        for _ in range(n)
    ]
    succ_c, succ_v = sum(control), sum(variant)
    res = two_proportion_ztest(succ_v, n, succ_c, n)
    p_value = res["p_value"] if res else 1.0
    significant = res is not None and p_value < alpha and succ_v / n > succ_c / n
    return {
        "n": n,
        "seed": seed,
        "alpha": alpha,
        "control": {"n": n, "conversion": round(succ_c / n, 6)},
        "variant": {"n": n, "conversion": round(succ_v / n, 6)},
        "uplift": res["uplift"] if res else None,
        "p_value": p_value,
        "confidence": (1.0 - p_value) if res else 0.0,
        "significant": significant,
        "required_sample_size": required_sample_size(
            base_conversion, base_conversion + effect_size, alpha
        ),
    }
