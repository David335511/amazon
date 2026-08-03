"""Multimodal product matching.

Combines vision similarity (embedding, color, shape, size, barcode, logo,
model numbers) with catalog signals (UPC, brand, title, attributes) into a
single `VisionMatchResult`: a fused confidence score, per-feature matched /
unmatched breakdown, and a human-readable explanation.

The weights come from `VisionConfig`, so fusion is tunable and provider-agnostic.
A feature with no data on either side is simply omitted (it neither helps nor
hurts); a *definitive* contradiction (both UPCs present but different, or both
brands present but different) explicitly drags confidence down.
"""

from __future__ import annotations

from app.vision.analyze import cosine, histogram_intersection
from app.vision.config import VisionConfig
from app.vision.models import (
    FeatureMatch,
    FeatureSimilarity,
    ImageAnalysis,
    SimilarityTarget,
    VisionComparison,
    VisionMatchResult,
)
from app.vision.text import (
    attribute_overlap,
    extract_model_numbers,
    normalize_brand,
    text_similarity,
)

# ──────────────────────────────────────────────────────────────
# Catalog signals
# ──────────────────────────────────────────────────────────────


def _upc(a: str | None, b: str | None) -> tuple[float, str] | None:
    na, nb = (a or "").strip(), (b or "").strip()
    if not na or not nb:
        return None
    if na == nb:
        return 1.0, f"UPC matches ({na})"
    return 0.0, f"UPC differs ({na} vs {nb})"


def _brand(a: str | None, b: str | None) -> tuple[float, str] | None:
    na, nb = normalize_brand(a), normalize_brand(b)
    if not na or not nb:
        return None
    if na == nb:
        return 1.0, f"Brand matches ({na})"
    if len(na) >= 2 and len(nb) >= 2 and (na in nb or nb in na):
        return 0.8, f"Brand partially matches ({na} ~ {nb})"
    return 0.0, f"Brand differs ({na} vs {nb})"


def _models(target: SimilarityTarget) -> set[str]:
    """Union of model numbers from any available text and OCR."""
    values: set[str] = set()
    for text in (target.upc, target.title, target.brand):
        values.update(extract_model_numbers(text))
    values.update(str(v) for v in target.attributes.values())
    if target.analysis:
        values.update(target.analysis.model_numbers)
    return values


# ──────────────────────────────────────────────────────────────
# Vision signals
# ──────────────────────────────────────────────────────────────


def _shape_similarity(a: ImageAnalysis, b: ImageAnalysis) -> float:
    sig_sim = cosine(a.shape_signature, b.shape_signature)
    a_ar, b_ar = a.shape.aspect_ratio, b.shape.aspect_ratio
    aspect_sim = 1.0 - min(1.0, abs(a_ar - b_ar) / max(a_ar, b_ar, 0.0001))
    return round(0.7 * sig_sim + 0.3 * aspect_sim, 4)


def _size_similarity(a: ImageAnalysis, b: ImageAnalysis) -> float:
    a_ar, b_ar = a.size.aspect_ratio, b.size.aspect_ratio
    aspect_sim = 1.0 - min(1.0, abs(a_ar - b_ar) / max(a_ar, b_ar, 0.0001))
    area_a, area_b = a.size.pixel_area, b.size.pixel_area
    area_sim = min(area_a, area_b) / max(area_a, area_b, 1)
    return round(0.5 * aspect_sim + 0.5 * area_sim, 4)


def _package_similarity(a: ImageAnalysis, b: ImageAnalysis) -> float:
    shape_sim = _shape_similarity(a, b)
    color_sim = histogram_intersection(a.color_histogram, b.color_histogram)
    return round(0.5 * shape_sim + 0.5 * color_sim, 4)


def _barcode_similarity(a: ImageAnalysis, b: ImageAnalysis) -> tuple[float, str] | None:
    obs = next((x for x in a.barcodes if x.detected), None)
    ref = next((x for x in b.barcodes if x.detected), None)
    if obs is None or ref is None:
        return None
    if obs.value and ref.value:
        matched = obs.value == ref.value
        return (1.0 if matched else 0.0), f"barcode {'matches' if matched else 'differs'} ({obs.value} vs {ref.value})"
    return 0.6, "both images contain a barcode pattern"


def _logo_similarity(a: ImageAnalysis, b: ImageAnalysis) -> tuple[float, str] | None:
    if not a.logos or not b.logos:
        return None
    la, lb = a.logos[0], b.logos[0]
    color_sim = cosine([la.r, la.g, la.b], [lb.r, lb.g, lb.b])
    fraction_prox = min(la.fraction, lb.fraction) / max(la.fraction, lb.fraction, 0.0001)
    score = round(0.7 * color_sim + 0.3 * fraction_prox, 4)
    return score, f"logo region signature similarity {score:.2f}"


def _model_similarity(obs: SimilarityTarget, ref: SimilarityTarget) -> tuple[float, str] | None:
    om, rm = _models(obs), _models(ref)
    if not om or not rm:
        return None
    common = om & rm
    score = len(common) / max(len(om), len(rm))
    detail = f"model numbers {'match' if score > 0 else 'differ'}"
    if common:
        detail += f" ({', '.join(sorted(common))})"
    return round(score, 4), detail


def _vision_signals(
    obs_an: ImageAnalysis,
    ref_an: ImageAnalysis,
) -> list[tuple[str, float, str]]:
    """All image-vs-image signals with data, as (feature, score, detail)."""
    signals: list[tuple[str, float, str]] = [
        ("embedding", cosine(obs_an.embedding, ref_an.embedding), "visual embedding similarity"),
        ("color", histogram_intersection(obs_an.color_histogram, ref_an.color_histogram), "color histogram similarity"),
        ("shape", _shape_similarity(obs_an, ref_an), "shape signature + aspect ratio"),
        ("size", _size_similarity(obs_an, ref_an), "aspect ratio + relative area"),
        ("package", _package_similarity(obs_an, ref_an), "packaging shape + color"),
    ]
    barcode = _barcode_similarity(obs_an, ref_an)
    if barcode is not None:
        signals.append(("barcode", barcode[0], barcode[1]))
    logo = _logo_similarity(obs_an, ref_an)
    if logo is not None:
        signals.append(("logo", logo[0], logo[1]))
    return signals


_VISION_WEIGHTS = {
    "embedding": "weight_embedding",
    "color": "weight_color",
    "shape": "weight_shape",
    "size": "weight_size",
    "package": "weight_shape",  # package reuses the shape weight
    "barcode": "weight_barcode",
    "logo": "weight_logo",
}


def _signal_weight(feature: str, cfg: VisionConfig) -> float:
    attr = _VISION_WEIGHTS.get(feature, "weight_model")
    return float(getattr(cfg, attr))


def _build_explanation(
    confidence: float,
    overall: float,
    matched: list[FeatureMatch],
    unmatched: list[FeatureMatch],
) -> str:
    parts = []
    if matched:
        listed = ", ".join(f"{f.feature} ({f.score:.2f})" for f in matched)
        parts.append(f"matched: {listed}")
    if unmatched:
        listed = ", ".join(f"{f.feature} ({f.score:.2f})" for f in unmatched)
        parts.append(f"unmatched: {listed}")
    if not parts:
        parts.append("no comparable features supplied")
    return f"Confidence {confidence:.2f}; visual similarity {overall:.2f}; " + "; ".join(parts)


def match(
    observed: SimilarityTarget,
    reference: SimilarityTarget,
    cfg: VisionConfig,
) -> VisionMatchResult:
    """Fuse an observed product against a reference product."""
    obs_an, ref_an = observed.analysis, reference.analysis
    features: list[FeatureMatch] = []

    # Catalog signals.
    upc = _upc(observed.upc, reference.upc)
    if upc is not None:
        features.append(FeatureMatch(feature="upc", kind="catalog", matched=upc[0] >= cfg.match_threshold, score=upc[0], detail=upc[1], weight=cfg.weight_upc))
    brand = _brand(observed.brand, reference.brand)
    if brand is not None:
        features.append(FeatureMatch(feature="brand", kind="catalog", matched=brand[0] >= cfg.match_threshold, score=brand[0], detail=brand[1], weight=cfg.weight_brand))
    if observed.title and reference.title:
        title_score = text_similarity(observed.title, reference.title)
        features.append(FeatureMatch(feature="title", kind="catalog", matched=title_score >= cfg.match_threshold, score=title_score, detail=f"title text similarity {title_score:.2f}", weight=cfg.weight_title))
    if observed.attributes and reference.attributes:
        attrs_score = attribute_overlap(observed.attributes, reference.attributes)
        features.append(FeatureMatch(feature="attributes", kind="catalog", matched=attrs_score >= cfg.match_threshold, score=attrs_score, detail=f"attribute overlap {attrs_score:.2f}", weight=cfg.weight_attributes))

    # Vision signals (require both images).
    if obs_an is not None and ref_an is not None:
        for feature, score, detail in _vision_signals(obs_an, ref_an):
            features.append(FeatureMatch(feature=feature, kind="vision", matched=score >= cfg.match_threshold, score=score, detail=detail, weight=_signal_weight(feature, cfg)))
        model = _model_similarity(observed, reference)
        if model is not None:
            features.append(FeatureMatch(feature="model_number", kind="vision", matched=model[0] >= cfg.match_threshold, score=model[0], detail=model[1], weight=cfg.weight_model))

    matched = [f for f in features if f.score >= cfg.match_threshold]
    unmatched = [f for f in features if f.score < cfg.match_threshold]

    # Fused confidence over available signals.
    total_weight = sum(f.weight for f in features)
    if total_weight <= 0:
        result = VisionMatchResult(
            confidence=0.0,
            overall_similarity=0.0,
            matched_features=[],
            unmatched_features=[],
            explanation="No comparable features supplied (provide an image and/or UPC/title/brand/attributes).",
            provider_used=obs_an.provider_used if obs_an else "local",
        )
        return result

    weighted = sum(f.score * f.weight for f in features) / total_weight
    hard = _hard_mismatches(observed, reference)
    confidence = max(0.0, min(1.0, weighted * (cfg.hard_mismatch_penalty**hard)))

    overall = (
        cosine(obs_an.embedding, ref_an.embedding)
        if obs_an is not None and ref_an is not None and obs_an.embedding and ref_an.embedding
        else round(weighted, 4)
    )

    return VisionMatchResult(
        confidence=round(confidence, 4),
        overall_similarity=round(overall, 4),
        matched_features=matched,
        unmatched_features=unmatched,
        explanation=_build_explanation(confidence, overall, matched, unmatched),
        provider_used=obs_an.provider_used if obs_an is not None else "local",
    )


def _hard_mismatches(observed: SimilarityTarget, reference: SimilarityTarget) -> int:
    """Count definitive contradictions (both present but different)."""
    count = 0
    upc = _upc(observed.upc, reference.upc)
    if upc is not None and upc[0] == 0.0:
        count += 1
    brand = _brand(observed.brand, reference.brand)
    if brand is not None and brand[0] == 0.0:
        count += 1
    return count


def compare_analyses(a: ImageAnalysis, b: ImageAnalysis, cfg: VisionConfig) -> VisionComparison:
    """Feature-by-feature visual comparison of two analyzed images."""
    features: list[FeatureSimilarity] = []
    for feature, score, detail in _vision_signals(a, b):
        features.append(FeatureSimilarity(feature=feature, similarity=score, detail=detail))
    model = _model_similarity(
        SimilarityTarget(analysis=a),
        SimilarityTarget(analysis=b),
    )
    if model is not None:
        features.append(FeatureSimilarity(feature="model_number", similarity=model[0], detail=model[1]))

    if not features:
        return VisionComparison(overall_visual_similarity=0.0, features=[])
    total = sum(_signal_weight(f.feature, cfg) for f in features) or 1.0
    overall = sum(f.similarity * _signal_weight(f.feature, cfg) for f in features) / total
    return VisionComparison(overall_visual_similarity=round(overall, 4), features=features)
