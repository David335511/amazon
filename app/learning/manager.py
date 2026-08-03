"""Continuous-learning platform facade.

`LearningManager` is the ONLY entry point for recording predictions, feeding back
outcomes, computing accuracy-over-time, automatically detecting issues (bad
rules / weak prompts / poor AI decisions / incorrect matches / ranking
mistakes), generating improvement recommendations (prompts, feature weights,
matching algorithms, forecast models, rule thresholds), deterministically
auto-tuning rule thresholds and feature weights, and running a versioned
continuous-learning cycle.

Reproducibility & versioning are enforced end-to-end:

- All statistics / tuning / scanning are pure functions of the stored outcomes
  (`app/learning/engine.py`) — the same data always reproduces the same numbers.
- Every prediction carries its **model version** and a feature snapshot.
- Every cycle persists a **versioned run** (monotonic run number) with a full
  config + code-version snapshot and a summary of what was measured, flagged,
  auto-tuned and recommended.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from app.learning.config import LearningConfig
from app.learning.engine import (
    FORECAST_METRICS,
    TARGETS_BY_DECISION,
    accuracy_summary,
    optimize_threshold,
    reweight_feature,
    rolling_accuracy,
    scan_issues,
)
from app.learning.errors import (
    LearningNotFoundError,
    LearningValidationError,
)
from app.learning.models import (
    DecisionType,
    PredictionType,
    RecommendationStatus,
    RecommendationTarget,
    RunStatus,
)
from app.learning.repository import LearningRepository
from app.learning.schemas import (
    AccuracyRead,
    ComparisonRead,
    DashboardRead,
    LearningCapabilities,
    LearningStats,
    ModelAccuracy,
    OutcomeCreate,
    PredictionCreate,
    PredictionList,
    PredictionRead,
    RecommendationList,
    RecommendationRead,
    RecommendationUpdate,
    ReweightResult,
    RuleTuneResult,
    RunList,
    RunRead,
)


def _dumps(obj: Any) -> str:
    return json.dumps(obj, default=str)


def _loads_list(s: str | None) -> list[dict[str, Any]]:
    if not s:
        return []
    try:
        value = json.loads(s)
        return value if isinstance(value, list) else []
    except (ValueError, TypeError):
        return []


def _loads_dict(s: str | None) -> dict[str, Any]:
    if not s:
        return {}
    try:
        value = json.loads(s)
        return value if isinstance(value, dict) else {}
    except (ValueError, TypeError):
        return {}


def _feature_map(features: list[dict[str, Any]]) -> dict[str, Any]:
    """Collapse a feature snapshot [{name, value, weight}] to {name: value}."""
    return {f.get("name", ""): f.get("value") for f in features if f.get("name")}


class LearningManager:
    """Facade for the continuous-learning platform."""

    def __init__(
        self, repository: LearningRepository, config: LearningConfig | None = None
    ) -> None:
        self._repo = repository
        self._config = config or LearningConfig()

    # ── Capabilities / stats ──────────────────────────────────────────────

    def capabilities(self) -> LearningCapabilities:
        return LearningCapabilities(
            enabled=self._config.enabled,
            prediction_types=[t.value for t in PredictionType],
            decision_types=[d.value for d in DecisionType],
            recommendation_targets=[t.value for t in RecommendationTarget],
            issue_types=[
                "bad_rule", "weak_prompt", "poor_decision",
                "incorrect_match", "ranking_mistake",
            ],
            metrics=["mae", "mape", "rmse", "bias", "directional_accuracy", "correlation"],
            code_version=self._config.code_version,
        )

    async def stats(self) -> LearningStats:
        return LearningStats(**await self._repo.stats())

    # ── Recording predictions & outcomes ─────────────────────────────────

    async def record_prediction(self, request: PredictionCreate) -> PredictionRead:
        if not self._config.enabled:
            raise LearningValidationError("Continuous-learning platform is disabled")
        if request.prediction_type not in PredictionType._value2member_map_:
            raise LearningValidationError(
                f"prediction_type must be one of {[t.value for t in PredictionType]}"
            )
        if request.decision_type not in DecisionType._value2member_map_:
            raise LearningValidationError(
                f"decision_type must be one of {[d.value for d in DecisionType]}"
            )
        if request.external_id:
            existing = await self._repo.get_by_external_id(request.external_id)
            if existing is not None:
                return PredictionRead.from_row(existing)
        row = await self._repo.create_prediction(
            prediction_type=request.prediction_type,
            subject_key=request.subject_key,
            decision_type=request.decision_type,
            decision_id=request.decision_id,
            model_version=request.model_version,
            predicted_value=request.predicted_value,
            predicted_at=request.predicted_at or datetime.now(UTC),
            features_json=_dumps(request.features) if request.features else None,
            context_json=_dumps(request.context) if request.context else None,
            external_id=request.external_id,
        )
        return PredictionRead.from_row(row)

    async def record_outcome(self, request: OutcomeCreate) -> int:
        """Record a realised outcome on matching unresolved predictions.

        Returns how many predictions were updated. Matching is by
        (prediction_type, subject_key) plus optional decision_id / model_version,
        or by external_id when supplied.
        """
        outcome_at = request.outcome_at or datetime.now(UTC)
        updated = 0
        if request.external_id:
            pred = await self._repo.get_by_external_id(request.external_id)
            candidates = [pred] if pred else []
        else:
            candidates = await self._repo.find_unresolved(
                prediction_type=request.prediction_type,
                subject_key=request.subject_key,
                decision_id=request.decision_id,
                model_version=request.model_version,
            )
        for pred in candidates:
            await self._repo.update_prediction(
                pred, actual_value=request.actual_value, outcome_at=outcome_at
            )
            updated += 1
        return updated

    async def list_predictions(
        self,
        *,
        prediction_type: str | None = None,
        decision_type: str | None = None,
        model_version: str | None = None,
        resolved_only: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> PredictionList:
        rows, total = await self._repo.list_predictions(
            prediction_type=prediction_type,
            decision_type=decision_type,
            model_version=model_version,
            resolved_only=resolved_only,
            limit=limit,
            offset=offset,
        )
        return PredictionList(items=[PredictionRead.from_row(r) for r in rows], total=total)

    # ── Accuracy / comparison / dashboard ────────────────────────────────

    async def accuracy(
        self, prediction_type: str, model_version: str | None = None
    ) -> AccuracyRead:
        rows = await self._repo.resolved_predictions(
            limit=self._config.max_predictions_per_scan, prediction_type=prediction_type
        )
        if model_version:
            rows = [r for r in rows if r.model_version == model_version]
        records = [_series_record(r) for r in rows]
        actuals = [r["actual"] for r in records]
        preds = [r["pred"] for r in records]
        return AccuracyRead(
            prediction_type=prediction_type,
            model_version=model_version,
            summary=accuracy_summary(actuals, preds),
            drift=_drift(records),
            series=rolling_accuracy(records, self._config.rolling_window),
        )

    async def comparison(self) -> list[ComparisonRead]:
        out: list[ComparisonRead] = []
        for ptype in PredictionType:
            rows = await self._repo.resolved_predictions(
                limit=self._config.max_predictions_per_scan, prediction_type=ptype.value
            )
            if not rows:
                continue
            actuals = [r.actual_value for r in rows]
            preds = [r.predicted_value for r in rows]
            summary = accuracy_summary(actuals, preds)
            out.append(ComparisonRead(
                prediction_type=ptype.value,
                sample_size=len(rows),
                predicted_mean=round(sum(actuals) / len(actuals), 6),
                actual_mean=round(sum(preds) / len(preds), 6),
                mae=summary["mae"],
                bias=summary["bias"],
                correlation=summary["correlation"],
                directional_accuracy=summary["directional_accuracy"],
            ))
        return out

    async def dashboard(self) -> DashboardRead:
        overall_actuals: list[float] = []
        overall_preds: list[float] = []
        by_metric: dict[str, dict[str, float]] = {}
        series: dict[str, list[dict[str, Any]]] = {}
        models: list[ModelAccuracy] = []

        for ptype in PredictionType:
            rows = await self._repo.resolved_predictions(
                limit=self._config.max_predictions_per_scan, prediction_type=ptype.value
            )
            if not rows:
                continue
            actuals = [r.actual_value for r in rows]
            preds = [r.predicted_value for r in rows]
            overall_actuals.extend(actuals)
            overall_preds.extend(preds)
            by_metric[ptype.value] = accuracy_summary(actuals, preds)
            series[ptype.value] = rolling_accuracy(
                [_series_record(r) for r in rows], self._config.rolling_window
            )
            models.extend(self._model_accuracy(rows))

        overall = accuracy_summary(overall_actuals, overall_preds) if overall_actuals else {}
        stats = await self._repo.stats()
        models.sort(key=lambda m: m.severity, reverse=True)
        return DashboardRead(
            overall=overall,
            by_metric=by_metric,
            models=models,
            open_recommendations=int(stats["open_recommendations"]),
            last_run_number=stats["last_run_number"],
            series=series,
        )

    # ── Automatic issue detection ────────────────────────────────────────

    async def scan_issues(self) -> list[dict[str, Any]]:
        rows = await self._repo.resolved_predictions(
            limit=self._config.max_predictions_per_scan
        )
        return scan_issues(
            [_view(r) for r in rows],
            min_samples=self._config.min_samples_for_issues,
            severity_threshold=self._config.issue_severity_threshold,
        )

    # ── Deterministic auto-tuning ─────────────────────────────────────────

    async def optimize_rule(self, decision_id: str) -> RuleTuneResult:
        """Deterministically tune a rule's classification threshold."""
        resolved = await self._repo.resolved_predictions(
            limit=self._config.max_predictions_per_scan
        )
        pairs: list[tuple[float, float]] = []
        for r in resolved:
            if r.decision_type != DecisionType.RULE.value or r.decision_id != decision_id:
                continue
            if r.actual_value not in (0.0, 1.0):
                continue
            score = _feature_map(_loads_list(r.features_json)).get("score")
            if score is None:
                continue
            pairs.append((float(score), float(r.actual_value)))
        if len(pairs) < 2:
            raise LearningNotFoundError(
                f"No binary rule outcomes with a 'score' feature for decision '{decision_id}'"
            )
        current = self._config.default_rule_threshold
        best = optimize_threshold(pairs)
        proposed = float(best["threshold"])
        cur_score = _f1_at(pairs, current)
        improvement = best["score"] - cur_score
        applied = (
            proposed is not None
            and abs(proposed - current) >= self._config.rule_tune_min_delta
            and improvement >= self._config.rule_tune_min_improvement
        )
        return RuleTuneResult(
            decision_id=decision_id,
            current_threshold=current,
            proposed_threshold=proposed,
            current_score=round(cur_score, 4),
            proposed_score=best["score"],
            improvement=round(improvement, 4),
            sample_size=len(pairs),
            tp=best["tp"],
            fp=best["fp"],
            tn=best["tn"],
            fn=best["fn"],
            applied=applied,
        )

    async def reweight(
        self, *, feature: str, values: list[float], errors: list[float], current_weight: float
    ) -> ReweightResult:
        result = reweight_feature(values, errors, current_weight)
        return ReweightResult(feature=feature, **result)

    # ── Continuous-learning cycle ─────────────────────────────────────────

    async def run_cycle(self) -> RunRead:
        """Run the full continuous-learning cycle and persist a versioned run.

        Measures accuracy (overall + per metric), computes the accuracy-over-time
        series, scans for issues, auto-tunes rule thresholds and feature weights,
        and persists the generated recommendations — all reproducibly, against a
        config + code-version snapshot, under a monotonic run number.
        """
        if not self._config.enabled:
            raise LearningValidationError("Continuous-learning platform is disabled")
        resolved = await self._repo.resolved_predictions(
            limit=self._config.max_predictions_per_scan
        )
        views = [_view(r) for r in resolved]

        # 1) Measure accuracy per metric + overall.
        metrics: dict[str, dict[str, float]] = {}
        overall_actuals: list[float] = []
        overall_preds: list[float] = []
        series: dict[str, list[dict[str, Any]]] = {}
        for ptype in PredictionType:
            subset = [v for v in views if v["prediction_type"] == ptype.value]
            if not subset:
                continue
            actuals = [v["actual"] for v in subset]
            preds = [v["pred"] for v in subset]
            overall_actuals.extend(actuals)
            overall_preds.extend(preds)
            metrics[ptype.value] = accuracy_summary(actuals, preds)
            series[ptype.value] = rolling_accuracy(
                [{"actual": v["actual"], "pred": v["pred"], "at": v["at"]} for v in subset],
                self._config.rolling_window,
            )
        overall = accuracy_summary(overall_actuals, overall_preds) if overall_actuals else {}

        # 2) Detect issues.
        issues = scan_issues(
            views,
            min_samples=self._config.min_samples_for_issues,
            severity_threshold=self._config.issue_severity_threshold,
        )

        # 3) Build + persist recommendations.
        recommendations = self._recommendations_for_issues(issues)
        auto_rules = self._auto_tune_rules(views)
        auto_features = self._auto_reweight(views)
        recommendations.extend(auto_rules)
        recommendations.extend(auto_features)
        recommendations = recommendations[: self._config.max_recommendations_per_run]

        run = await self._repo.create_run(
            run_number=await self._repo.next_run_number(),
            status=RunStatus.RUNNING.value,
            params_snapshot_json=_dumps(self._config.as_snapshot),
            started_at=datetime.now(UTC),
        )
        for rec in recommendations:
            await self._repo.create_recommendation(
                run_id=run.id,
                target_type=rec["target_type"],
                target_id=rec.get("target_id"),
                issue_type=rec.get("issue_type", ""),
                severity=rec.get("severity", 0.0),
                confidence=rec.get("confidence", 0.0),
                current_value=rec.get("current_value"),
                proposed_value=rec.get("proposed_value"),
                proposed_action=rec.get("proposed_action", ""),
                explanation=rec.get("explanation", ""),
                evidence_json=_dumps(rec.get("evidence", {})),
                status=rec.get("status", RecommendationStatus.OPEN.value),
                model_version=rec.get("model_version"),
            )

        summary = {
            "overall": overall,
            "by_metric": metrics,
            "accuracy_series": series,
            "issues": issues,
            "recommendations": recommendations,
            "auto_tuned_rules": auto_rules,
            "auto_reweighted_features": auto_features,
            "code_version": self._config.code_version,
            "predictions_scanned": len(views),
        }
        run = await self._repo.update_run(
            run,
            status=RunStatus.COMPLETED.value,
            summary_json=_dumps(summary),
            completed_at=datetime.now(UTC),
        )
        return RunRead.from_row(run)

    async def list_runs(self, limit: int = 50, offset: int = 0) -> RunList:
        rows, total = await self._repo.list_runs(limit=limit, offset=offset)
        return RunList(items=[RunRead.from_row(r) for r in rows], total=total)

    async def get_run(self, run_id: uuid.UUID) -> RunRead:
        run = await self._repo.get_run(run_id)
        if run is None:
            raise LearningNotFoundError(f"Learning run {run_id} not found")
        return RunRead.from_row(run)

    async def list_recommendations(
        self,
        *,
        status: str | None = None,
        target_type: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> RecommendationList:
        rows, total = await self._repo.list_recommendations(
            status=status, target_type=target_type, limit=limit, offset=offset,
        )
        return RecommendationList(
            items=[RecommendationRead.from_row(r) for r in rows], total=total
        )

    async def update_recommendation(
        self, recommendation_id: uuid.UUID, request: RecommendationUpdate
    ) -> RecommendationRead:
        rec = await self._repo.get_recommendation(recommendation_id)
        if rec is None:
            raise LearningNotFoundError(f"Recommendation {recommendation_id} not found")
        if request.status not in RecommendationStatus._value2member_map_:
            raise LearningValidationError(
                f"status must be one of {[s.value for s in RecommendationStatus]}"
            )
        rec = await self._repo.update_recommendation_status(rec, request.status)
        return RecommendationRead.from_row(rec)

    # ── Report ────────────────────────────────────────────────────────────

    async def generate_report(self) -> str:
        """Render a markdown learning report from the current resolved outcomes."""
        resolved = await self._repo.resolved_predictions(
            limit=self._config.max_predictions_per_scan
        )
        views = [_view(r) for r in resolved]
        issues = scan_issues(
            views,
            min_samples=self._config.min_samples_for_issues,
            severity_threshold=self._config.issue_severity_threshold,
        )
        recommendations = self._recommendations_for_issues(issues)
        auto_rules = self._auto_tune_rules(views)
        auto_features = self._auto_reweight(views)
        stats = await self._repo.stats()

        lines: list[str] = []
        lines.append("# Continuous-learning report")
        lines.append("")
        lines.append("## Overview")
        lines.append(f"- Predictions recorded: {stats['total_predictions']}")
        lines.append(f"- Resolved outcomes: {stats['resolved_predictions']}")
        lines.append(f"- Open recommendations: {stats['open_recommendations']}")
        lines.append(f"- Code version: {self._config.code_version or 'unknown'}")
        lines.append("")

        lines.append("## Predicted vs actual")
        lines.append("| Metric | n | MAE | bias | directional | correlation |")
        lines.append("|---|---|---|---|---|---|")
        overall_actuals: list[float] = []
        overall_preds: list[float] = []
        for ptype in PredictionType:
            subset = [v for v in views if v["prediction_type"] == ptype.value]
            if not subset:
                continue
            actuals = [v["actual"] for v in subset]
            preds = [v["pred"] for v in subset]
            overall_actuals.extend(actuals)
            overall_preds.extend(preds)
            s = accuracy_summary(actuals, preds)
            lines.append(
                f"| {ptype.value} | {len(subset)} | {s['mae']:.4f} | {s['bias']:+.4f} "
                f"| {s['directional_accuracy']:.2%} | {s['correlation']:.3f} |"
            )
        if overall_actuals:
            s = accuracy_summary(overall_actuals, overall_preds)
            lines.append(f"| **overall** | {len(overall_actuals)} | {s['mae']:.4f} | {s['bias']:+.4f} | {s['directional_accuracy']:.2%} | {s['correlation']:.3f} |")
        lines.append("")

        lines.append("## Automatically detected issues")
        if not issues:
            lines.append("- No issues above the severity threshold.")
        else:
            lines.append("| Issue | Decision | target | n | severity | mode |")
            lines.append("|---|---|---|---|---|---|")
            for i in issues:
                lines.append(
                    f"| {i['issue_type']} | {i['decision_id']} | {i['prediction_type']} "
                    f"| {i['sample_size']} | {i['severity']:.3f} | {i['mode']} |"
                )
        lines.append("")

        lines.append("## Improvement recommendations")
        recs = recommendations + auto_rules + auto_features
        if not recs:
            lines.append("- None (the model is within tolerance).")
        else:
            lines.append("| Target | id | action | severity |")
            lines.append("|---|---|---|---|")
            for r in recs[:50]:
                lines.append(
                    f"| {r['target_type']} | {r.get('target_id') or '-'} | "
                    f"{r['proposed_action']} | {r.get('severity', 0.0):.3f} |"
                )
        lines.append("")

        lines.append("## Reproducibility")
        lines.append(
            "- All metrics, issues, tuned thresholds and reweights are pure "
            "functions of the stored outcomes; re-running reproduces them exactly."
        )
        lines.append(
            f"- This report reflects code version `{self._config.code_version or 'unknown'}` "
            "and the current config snapshot."
        )
        return "\n".join(lines)

    # ── Internals ─────────────────────────────────────────────────────────

    def _recommendations_for_issues(
        self, issues: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        recs: list[dict[str, Any]] = []
        for issue in issues:
            decision_type = issue["decision_type"]
            targets = list(TARGETS_BY_DECISION.get(decision_type, []))
            if (
                issue.get("prediction_type") in FORECAST_METRICS
                and "forecast_model" not in targets
            ):
                targets.append("forecast_model")
            for target in targets:
                recs.append(self._build_recommendation(issue, target))
        return recs

    def _build_recommendation(
        self, issue: dict[str, Any], target_type: str
    ) -> dict[str, Any]:
        target_id = issue["decision_id"]
        model_version = issue.get("model_version")
        prediction_type = issue.get("prediction_type")
        mode = issue.get("mode", "degraded accuracy")
        n = issue["sample_size"]
        if target_type == RecommendationTarget.RULE_THRESHOLD.value:
            action = (
                f"Tune the rule threshold for decision '{target_id}' "
                f"(model {model_version}) — observed {mode} over {n} outcomes."
            )
            current_value = self._config.default_rule_threshold
            proposed_value = None
            evidence = {
                "mae": issue["mae"], "bias": issue["bias"],
                "directional_accuracy": issue["directional_accuracy"],
            }
        elif target_type == RecommendationTarget.PROMPT.value:
            action = (
                f"Rewrite prompt '{target_id}' (model {model_version}) and A/B the "
                f"revised prompt against the current version; {mode} over {n} outcomes."
            )
            current_value = proposed_value = None
            evidence = {"mae": issue["mae"], "bias": issue["bias"]}
        elif target_type == RecommendationTarget.MATCHING_ALGORITHM.value:
            action = (
                f"Retrain / re-parametrize the matching or ranking algorithm for "
                f"'{target_id}' (model {model_version}); validate via a scoring "
                f"comparison experiment. {mode} over {n} outcomes."
            )
            current_value = proposed_value = None
            evidence = {
                "directional_accuracy": issue["directional_accuracy"],
                "correlation": issue["correlation"],
            }
        elif target_type == RecommendationTarget.FORECAST_MODEL.value:
            action = (
                f"Version-bump the forecast model producing {prediction_type} for "
                f"'{target_id}' (model {model_version}); compare revised MAE on the "
                f"same series. {mode} over {n} outcomes."
            )
            current_value = proposed_value = None
            evidence = {"mae": issue["mae"], "bias": issue["bias"]}
        else:
            action = f"Review feature weights for '{target_id}' — {mode} over {n} outcomes."
            current_value = proposed_value = None
            evidence = {"bias": issue["bias"], "mae": issue["mae"]}
        return {
            "target_type": target_type,
            "target_id": target_id,
            "issue_type": issue["issue_type"],
            "severity": issue["severity"],
            "confidence": min(1.0, 0.3 + 0.7 * (n / max(1, self._config.min_samples_for_issues * 4))),
            "current_value": current_value,
            "proposed_value": proposed_value,
            "proposed_action": action,
            "explanation": (
                f"Decision '{target_id}' ({prediction_type}, model {model_version}) "
                f"shows {mode} with MAE {issue['mae']:.4f} and directional accuracy "
                f"{issue['directional_accuracy']:.2%} over {n} resolved outcomes."
            ),
            "evidence": evidence,
            "status": RecommendationStatus.OPEN.value,
            "model_version": model_version,
        }

    def _auto_tune_rules(self, views: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Deterministically tune rule thresholds and emit 'applied' recs."""
        groups: dict[str, list[tuple[float, float]]] = {}
        for v in views:
            if v["decision_type"] != DecisionType.RULE.value or v.get("actual") not in (0.0, 1.0):
                continue
            score = _feature_map(v.get("features") or []).get("score")
            if score is None:
                continue
            gid = v.get("decision_id") or v.get("model_version") or "global"
            groups.setdefault(gid, []).append((float(score), float(v["actual"])))

        recs: list[dict[str, Any]] = []
        for gid, pairs in groups.items():
            if len(pairs) < self._config.min_samples_for_issues:
                continue
            current = self._config.default_rule_threshold
            best = optimize_threshold(pairs)
            proposed = float(best["threshold"])
            cur_score = _f1_at(pairs, current)
            improvement = best["score"] - cur_score
            if (
                abs(proposed - current) < self._config.rule_tune_min_delta
                or improvement < self._config.rule_tune_min_improvement
            ):
                continue
            recs.append({
                "target_type": RecommendationTarget.RULE_THRESHOLD.value,
                "target_id": gid,
                "issue_type": "bad_rule",
                "severity": round(1.0 - best["score"], 4),
                "confidence": min(1.0, 0.4 + 0.6 * (len(pairs) / 20.0)),
                "current_value": current,
                "proposed_value": proposed,
                "proposed_action": (
                    f"Auto-tuned rule threshold for '{gid}' from {current:.3f} to "
                    f"{proposed:.3f} (F1 {cur_score:.3f} -> {best['score']:.3f})."
                ),
                "explanation": (
                    f"Optimising the classification threshold over {len(pairs)} "
                    f"binary outcomes improves F1 by {improvement:.3f}."
                ),
                "evidence": {
                    "threshold": proposed, "f1_current": round(cur_score, 4),
                    "f1_proposed": best["score"], "sample_size": len(pairs),
                    "tp": best["tp"], "fp": best["fp"], "tn": best["tn"], "fn": best["fn"],
                },
                "status": RecommendationStatus.APPLIED.value,
                "model_version": views[0].get("model_version") if views else None,
            })
        return recs

    def _auto_reweight(self, views: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Propose feature reweights from per-feature correlation with error."""
        feature_values: dict[str, list[tuple[float, float, float]]] = {}
        for v in views:
            if v.get("actual") is None:
                continue
            error = v["pred"] - v["actual"]
            for f in v.get("features") or []:
                name = f.get("name")
                value = f.get("value")
                if not name or not isinstance(value, (int, float)):
                    continue
                weight = float(f.get("weight") or 1.0)
                feature_values.setdefault(name, []).append((float(value), error, weight))

        recs: list[dict[str, Any]] = []
        for name, tuples in feature_values.items():
            if len(tuples) < self._config.min_samples_for_issues:
                continue
            values = [t[0] for t in tuples]
            errors = [t[1] for t in tuples]
            current = sum(t[2] for t in tuples) / len(tuples)
            result = reweight_feature(values, errors, current)
            if abs(result["correlation"]) < self._config.feature_reweight_min_abs_corr:
                continue
            recs.append({
                "target_type": RecommendationTarget.FEATURE_WEIGHT.value,
                "target_id": name,
                "issue_type": "poor_decision",
                "severity": round(abs(result["correlation"]), 4),
                "confidence": 0.6,
                "current_value": result["current_weight"],
                "proposed_value": result["suggested_weight"],
                "proposed_action": (
                    f"Adjust feature '{name}' weight from {result['current_weight']:.4f} "
                    f"to {result['suggested_weight']:.4f}."
                ),
                "explanation": result["explanation"],
                "evidence": {
                    "correlation": result["correlation"],
                    "sample_size": len(tuples),
                },
                "status": RecommendationStatus.OPEN.value,
                "model_version": None,
            })
        return recs

    def _model_accuracy(self, rows: list[Any]) -> list[ModelAccuracy]:
        grouped: dict[tuple[str, str], list[Any]] = {}
        for r in rows:
            grouped.setdefault((r.model_version, r.decision_type), []).append(r)
        out: list[ModelAccuracy] = []
        for (model_version, decision_type), group in grouped.items():
            actuals = [g.actual_value for g in group]
            preds = [g.predicted_value for g in group]
            s = accuracy_summary(actuals, preds)
            scale = max(1e-9, abs(s["bias"]), s["mae"])
            severity = 0.6 * min(1.0, s["mae"] / scale) + 0.4 * (1.0 - s["directional_accuracy"])
            out.append(ModelAccuracy(
                model_version=model_version,
                prediction_type=rows[0].prediction_type,
                decision_type=decision_type,
                sample_size=len(group),
                mae=s["mae"],
                mape=s["mape"],
                bias=s["bias"],
                directional_accuracy=s["directional_accuracy"],
                severity=round(severity, 4),
            ))
        return out


def _view(p: Any) -> dict[str, Any]:
    return {
        "prediction_type": p.prediction_type,
        "decision_type": p.decision_type,
        "decision_id": p.decision_id,
        "model_version": p.model_version,
        "pred": p.predicted_value,
        "actual": p.actual_value,
        "features": _loads_list(p.features_json),
        "at": (p.outcome_at or p.created_at).isoformat(),
    }


def _series_record(p: Any) -> dict[str, Any]:
    return {
        "actual": p.actual_value,
        "pred": p.predicted_value,
        "at": (p.outcome_at or p.created_at).isoformat(),
    }


def _drift(records: list[dict[str, Any]]) -> dict[str, Any]:
    if not records:
        return {"drifted": False, "recent_bias": 0.0, "baseline_bias": 0.0, "delta": 0.0}
    actuals = [r["actual"] for r in records]
    preds = [r["pred"] for r in records]
    baseline_bias = sum(p - a for a, p in zip(actuals, preds, strict=False)) / len(actuals)
    recent = records[-10:]
    recent_bias = (
        sum(r["pred"] - r["actual"] for r in recent) / len(recent) if recent else 0.0
    )
    scale = max(1e-9, abs(baseline_bias), sum((a - sum(actuals) / len(actuals)) ** 2 for a in actuals) / len(actuals) ** 0.5)
    delta = recent_bias - baseline_bias
    return {
        "drifted": abs(delta) > 0.25 * scale,
        "recent_bias": round(recent_bias, 6),
        "baseline_bias": round(baseline_bias, 6),
        "delta": round(delta, 6),
    }


def _f1_at(pairs: list[tuple[float, float]], threshold: float) -> float:
    tp = fp = tn = fn = 0
    for score, actual in pairs:
        positive = score >= threshold
        truth = bool(actual)
        if truth and positive:
            tp += 1
        elif truth and not positive:
            fn += 1
        elif not truth and positive:
            fp += 1
        else:
            tn += 1
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)
