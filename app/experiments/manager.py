"""Experimentation platform facade.

`ExperimentManager` is the ONLY entry point for creating experiments, managing
variants, deterministically assigning subjects, recording observations,
computing winners / confidence / impact / precision-recall, and generating
reproducible reports.

Reproducibility is enforced end-to-end:

- **Assignment** is a pure function of ``(seed, subject_key)`` — the same
  subject always lands on the same variant.
- **Statistics** are pure functions of the stored observations — the same data
  always produces the same winner / confidence / report.
- Every experiment captures a **config + code-version snapshot** when started,
  and every report stores its **params snapshot**, so the exact inputs behind a
  result are always on record.
- Per-experiment uniqueness on (experiment, subject) for assignments and
  observations means replaying a subject stream never doubles data.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from app.experiments.config import ExperimentConfig
from app.experiments.engine import (
    assign_variant,
    determine_winner,
    simulate_ab,
    variant_stats,
)
from app.experiments.errors import (
    ExperimentConflictError,
    ExperimentNotFoundError,
    ExperimentValidationError,
)
from app.experiments.models import (
    Experiment,
    ExperimentStatus,
    ExperimentType,
    PrimaryMetric,
    Variant,
)
from app.experiments.repository import ExperimentRepository
from app.experiments.schemas import (
    TYPE_DEFAULT_METRIC,
    AssignmentRead,
    ExperimentCapabilities,
    ExperimentCreate,
    ExperimentDetail,
    ExperimentList,
    ExperimentRead,
    ExperimentStats,
    ExperimentUpdate,
    ObservationBatch,
    ObservationCreate,
    ObservationList,
    ObservationRead,
    ReportList,
    ReportRead,
    ResultsRead,
    SimulateRequest,
    VariantCreate,
    VariantRead,
    WinnerRead,
)


def _dumps(obj: Any) -> str:
    return json.dumps(obj, default=str)


def _loads(s: str | None) -> Any:
    if not s:
        return {}
    try:
        return json.loads(s)
    except (ValueError, TypeError):
        return {}


class ExperimentManager:
    """Facade for the experimentation platform."""

    def __init__(
        self, repository: ExperimentRepository, config: ExperimentConfig | None = None
    ) -> None:
        self._repo = repository
        self._config = config or ExperimentConfig()

    # ── Capabilities / templates ──────────────────────────────────────────

    def capabilities(self) -> ExperimentCapabilities:
        return ExperimentCapabilities(
            enabled=self._config.enabled,
            experiment_types=[t.value for t in ExperimentType],
            metrics=[m.value for m in PrimaryMetric],
            statuses=[s.value for s in ExperimentStatus],
            default_alpha=self._config.default_alpha,
            default_min_sample_size=self._config.default_min_sample_size,
            code_version=self._config.code_version,
            track=["winner", "confidence", "profit_impact", "roi_impact",
                   "precision", "recall", "false_positives", "false_negatives"],
        )

    # ── Lifecycle ─────────────────────────────────────────────────────────

    async def create_experiment(self, request: ExperimentCreate) -> ExperimentRead:
        if not self._config.enabled:
            raise ExperimentValidationError("Experimentation platform is disabled")
        if len(request.variants) > self._config.max_variants_per_experiment:
            raise ExperimentValidationError(
                f"Too many variants: max {self._config.max_variants_per_experiment}"
            )
        metric = (
            request.primary_metric.value
            if request.primary_metric
            else TYPE_DEFAULT_METRIC[request.experiment_type.value]
        )
        experiment = await self._repo.create_experiment(
            name=request.name,
            experiment_type=request.experiment_type.value,
            status=ExperimentStatus.DRAFT.value,
            description=request.description,
            hypothesis=request.hypothesis,
            primary_metric=metric,
            alpha=request.alpha,
            min_sample_size=request.min_sample_size,
            seed=request.seed,
            control_variant_key=request.control_variant_key,
        )
        # Control variant first if provided / requested, then the rest.
        ordered = list(request.variants)
        control = next((v for v in ordered if v.is_control), None)
        if control is not None:
            ordered.remove(control)
            ordered.insert(0, control)
        for v in ordered:
            await self._repo.create_variant(
                experiment_id=experiment.id,
                key=v.key,
                label=v.label,
                parameters_json=_dumps(v.parameters),
                is_control=v.is_control,
            )
            if v.is_control and not experiment.control_variant_key:
                await self._repo.update_experiment(
                    experiment, control_variant_key=v.key
                )
        if (
            (control_variant_key := experiment.control_variant_key)
            and await self._repo.get_variant(experiment.id, control_variant_key) is None
        ):
            await self._repo.create_variant(
                experiment_id=experiment.id,
                key=control_variant_key,
                label="Control",
                parameters_json=_dumps({}),
                is_control=True,
            )
        return await self._to_read(experiment)

    async def add_variant(self, experiment_id: uuid.UUID, request: VariantCreate) -> VariantRead:
        experiment = await self._get_experiment(experiment_id)
        if experiment.status != ExperimentStatus.DRAFT.value:
            raise ExperimentConflictError(
                "Variants can only be added while the experiment is a draft"
            )
        count = await self._repo.count_variants(experiment_id)
        if count >= self._config.max_variants_per_experiment:
            raise ExperimentValidationError(
                f"Too many variants: max {self._config.max_variants_per_experiment}"
            )
        if request.is_control and experiment.control_variant_key:
            raise ExperimentValidationError(
                f"Experiment already has control '{experiment.control_variant_key}'"
            )
        if await self._repo.get_variant(experiment_id, request.key):
            raise ExperimentValidationError(f"Variant '{request.key}' already exists")
        variant = await self._repo.create_variant(
            experiment_id=experiment_id,
            key=request.key,
            label=request.label,
            parameters_json=_dumps(request.parameters),
            is_control=request.is_control,
        )
        if request.is_control:
            await self._repo.update_experiment(
                experiment, control_variant_key=request.key
            )
        return VariantRead.from_row(variant)

    async def update_experiment(
        self, experiment_id: uuid.UUID, request: ExperimentUpdate
    ) -> ExperimentRead:
        experiment = await self._get_experiment(experiment_id)
        if experiment.status != ExperimentStatus.DRAFT.value:
            raise ExperimentConflictError("Only draft experiments are editable")
        kwargs: dict[str, Any] = {}
        for field in ("name", "description", "hypothesis", "control_variant_key"):
            value = getattr(request, field)
            if value is not None:
                kwargs[field] = value
        experiment = await self._repo.update_experiment(experiment, **kwargs)
        return await self._to_read(experiment)

    async def start(self, experiment_id: uuid.UUID) -> ExperimentRead:
        experiment = await self._get_experiment(experiment_id)
        if experiment.status not in (
            ExperimentStatus.DRAFT.value, ExperimentStatus.RUNNING.value,
        ):
            raise ExperimentConflictError(
                f"Cannot start experiment in status '{experiment.status}'"
            )
        variants = await self._repo.list_variants(experiment_id)
        if not variants:
            raise ExperimentValidationError("Add at least one variant before starting")
        snapshot = {
            "experiment": {
                "name": experiment.name,
                "experiment_type": experiment.experiment_type,
                "primary_metric": experiment.primary_metric,
                "alpha": experiment.alpha,
                "min_sample_size": experiment.min_sample_size,
                "seed": experiment.seed,
                "control_variant_key": experiment.control_variant_key,
            },
            "variants": [
                {
                    "key": v.key, "label": v.label,
                    "parameters": _loads(v.parameters_json), "is_control": v.is_control,
                }
                for v in variants
            ],
            "code_version": self._config.code_version,
        }
        experiment = await self._repo.update_experiment(
            experiment,
            status=ExperimentStatus.RUNNING.value,
            started_at=datetime.now(UTC),
            config_snapshot_json=_dumps(snapshot),
            code_version=self._config.code_version,
        )
        return await self._to_read(experiment)

    async def stop(self, experiment_id: uuid.UUID) -> ReportRead:
        experiment = await self._get_experiment(experiment_id)
        if experiment.status != ExperimentStatus.RUNNING.value:
            raise ExperimentConflictError(
                f"Cannot stop experiment in status '{experiment.status}'"
            )
        await self._repo.update_experiment(
            experiment, status=ExperimentStatus.STOPPED.value, stopped_at=datetime.now(UTC)
        )
        return await self.generate_report(experiment_id)

    # ── Assignment & observations ─────────────────────────────────────────

    async def assign(self, experiment_id: uuid.UUID, subject_key: str) -> AssignmentRead:
        experiment = await self._get_experiment(experiment_id)
        if experiment.status == ExperimentStatus.ARCHIVED.value:
            raise ExperimentConflictError("Archived experiments cannot be assigned")
        existing = await self._repo.get_assignment(experiment_id, subject_key)
        if existing:
            variant = await self._variant_by_id(experiment_id, existing.variant_id)
            return AssignmentRead.from_rows(existing, variant.key)
        variants = await self._repo.list_variants(experiment_id)
        if not variants:
            raise ExperimentValidationError("Add at least one variant first")
        idx = assign_variant(subject_key, experiment.seed, len(variants))
        variant = variants[idx]
        assignment = await self._repo.create_assignment(
            experiment_id=experiment_id, variant_id=variant.id, subject_key=subject_key,
        )
        return AssignmentRead.from_rows(assignment, variant.key)

    async def record(
        self, experiment_id: uuid.UUID, request: ObservationCreate
    ) -> ObservationRead:
        experiment = await self._get_experiment(experiment_id)
        if experiment.status not in (
            ExperimentStatus.RUNNING.value, ExperimentStatus.STOPPED.value,
        ):
            raise ExperimentConflictError(
                f"Cannot record observations in status '{experiment.status}'"
            )
        assignment = await self._repo.get_assignment(experiment_id, request.subject_key)
        if not assignment:
            await self.assign(experiment_id, request.subject_key)
            assignment = await self._repo.get_assignment(experiment_id, request.subject_key)
            assert assignment is not None  # just created
        variant = await self._variant_by_id(experiment_id, assignment.variant_id)
        recorded_at = datetime.now(UTC)
        existing = await self._repo.get_observation(experiment_id, request.subject_key)
        if existing is not None:
            row = await self._repo.update_observation(
                existing,
                outcome=request.outcome,
                profit=request.profit,
                roi=request.roi,
                value=request.value,
                predicted=request.predicted,
                ground_truth=request.ground_truth,
                recorded_at=recorded_at,
            )
        else:
            row = await self._repo.create_observation(
                experiment_id=experiment_id,
                variant_id=assignment.variant_id,
                subject_key=request.subject_key,
                outcome=request.outcome,
                profit=request.profit,
                roi=request.roi,
                value=request.value,
                predicted=request.predicted,
                ground_truth=request.ground_truth,
                recorded_at=recorded_at,
            )
        return ObservationRead.from_rows(row, variant.key)

    async def record_many(
        self, experiment_id: uuid.UUID, batch: ObservationBatch
    ) -> list[ObservationRead]:
        if len(batch.observations) > self._config.max_batch_size:
            raise ExperimentValidationError(
                f"Batch of {len(batch.observations)} exceeds max {self._config.max_batch_size}"
            )
        seen: set[str] = set()
        reads: list[ObservationRead] = []
        for obs in batch.observations:
            if obs.subject_key in seen:
                continue  # de-duplicate within the batch (one observation per subject)
            seen.add(obs.subject_key)
            reads.append(await self.record(experiment_id, obs))
        return reads

    # ── Results / winner / precision-recall ───────────────────────────────

    async def results(self, experiment_id: uuid.UUID) -> ResultsRead:
        experiment = await self._get_experiment(experiment_id)
        stats, observations = await self._load_stats(experiment)
        winner = determine_winner(
            stats, experiment.control_variant_key, experiment.alpha, experiment.primary_metric
        )
        total = len(observations)
        variants = []
        for key, entry in sorted(stats.items()):
            conf = entry["confusion"]
            variants.append(
                {
                    "key": key,
                    "n": entry["n"],
                    "conversion": entry["conversion"],
                    "mean_profit": entry["mean_profit"],
                    "mean_roi": entry["mean_roi"],
                    "mean_value": entry["mean_value"],
                    "precision": conf["precision"] if conf else None,
                    "recall": conf["recall"] if conf else None,
                    "false_positives": conf["false_positives"] if conf else None,
                    "false_negatives": conf["false_negatives"] if conf else None,
                }
            )
        winner["winner_label"] = await self._label_for(
            experiment_id, winner.get("winner_key")
        )
        return ResultsRead(
            experiment_id=experiment_id,
            metric=experiment.primary_metric,
            alpha=experiment.alpha,
            total_observations=total,
            min_sample_size=experiment.min_sample_size,
            sample_complete=total >= experiment.min_sample_size,
            variants=variants,
            winner=winner,
        )

    async def winner(self, experiment_id: uuid.UUID) -> WinnerRead:
        experiment = await self._get_experiment(experiment_id)
        stats, _ = await self._load_stats(experiment)
        result = determine_winner(
            stats, experiment.control_variant_key, experiment.alpha, experiment.primary_metric
        )
        return WinnerRead(
            experiment_id=experiment_id,
            winner_key=result["winner_key"],
            winner_label=await self._label_for(experiment_id, result["winner_key"]),
            confidence=result["confidence"],
            significant=result["significant"],
            p_value=result["p_value"],
            metric=experiment.primary_metric,
            leading_key=result["leading_key"],
        )

    async def precision_recall(self, experiment_id: uuid.UUID) -> dict[str, Any]:
        experiment = await self._get_experiment(experiment_id)
        stats, _ = await self._load_stats(experiment)
        out: dict[str, Any] = {}
        for key, entry in stats.items():
            conf = entry["confusion"]
            if conf is None:
                out[key] = {
                    "precision": None, "recall": None, "accuracy": None, "f1": None,
                    "false_positives": None, "false_negatives": None,
                    "true_positives": None, "true_negatives": None,
                }
            else:
                out[key] = conf
        return {"experiment_id": str(experiment_id), "metric": experiment.primary_metric, "variants": out}

    # ── Reports ───────────────────────────────────────────────────────────

    async def generate_report(self, experiment_id: uuid.UUID) -> ReportRead:
        experiment = await self._get_experiment(experiment_id)
        stats, observations = await self._load_stats(experiment)
        winner = determine_winner(
            stats, experiment.control_variant_key, experiment.alpha, experiment.primary_metric
        )
        chosen = winner["winner_key"] or winner["leading_key"]
        control_key = experiment.control_variant_key

        profit_impact = roi_impact = precision = recall = None
        false_positives = false_negatives = None
        if chosen and chosen in stats and control_key and control_key in stats:
            chosen_s = stats[chosen]
            control_s = stats[control_key]
            profit_impact = round(chosen_s["mean_profit"] - control_s["mean_profit"], 6)
            roi_impact = round(chosen_s["mean_roi"] - control_s["mean_roi"], 6)
            if chosen_s["confusion"]:
                precision = chosen_s["confusion"]["precision"]
                recall = chosen_s["confusion"]["recall"]
                false_positives = chosen_s["confusion"]["false_positives"]
                false_negatives = chosen_s["confusion"]["false_negatives"]

        winner_label = await self._label_for(experiment_id, winner["winner_key"])
        body = self._render_markdown(
            experiment, stats, winner, chosen, profit_impact, roi_impact, len(observations)
        )
        snapshot = {
            "experiment_id": str(experiment_id),
            "metric": experiment.primary_metric,
            "alpha": experiment.alpha,
            "seed": experiment.seed,
            "control_variant_key": control_key,
            "code_version": experiment.code_version,
            "observation_count": len(observations),
            "config_snapshot": _loads(experiment.config_snapshot_json),
            "variants": [
                {
                    "key": v.key, "label": v.label,
                    "parameters": _loads(v.parameters_json), "is_control": v.is_control,
                }
                for v in await self._repo.list_variants(experiment_id)
            ],
        }
        row = await self._repo.create_report(
            experiment_id=experiment_id,
            winner_variant_key=winner["winner_key"],
            winner_label=winner_label,
            confidence=winner["confidence"],
            metric=experiment.primary_metric,
            profit_impact=profit_impact,
            roi_impact=roi_impact,
            precision=precision,
            recall=recall,
            false_positives=false_positives,
            false_negatives=false_negatives,
            report_body=body,
            params_snapshot_json=_dumps(snapshot),
        )
        return ReportRead.from_row(row)

    async def get_report(self, experiment_id: uuid.UUID) -> ReportRead:
        row = await self._repo.latest_report(experiment_id)
        if row is None:
            raise ExperimentNotFoundError("No report generated for this experiment yet")
        return ReportRead.from_row(row)

    async def list_reports(
        self, experiment_id: uuid.UUID, limit: int = 20, offset: int = 0
    ) -> ReportList:
        rows, total = await self._repo.list_reports(experiment_id, limit=limit, offset=offset)
        return ReportList(items=[ReportRead.from_row(r) for r in rows], total=total)

    # ── Listing / detail / delete / stats / simulate ──────────────────────

    async def list_experiments(
        self,
        *,
        experiment_type: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> ExperimentList:
        rows, total = await self._repo.list_experiments(
            experiment_type=experiment_type, status=status, limit=limit, offset=offset,
        )
        items = [await self._to_read(r) for r in rows]
        return ExperimentList(items=items, total=total)

    async def get_experiment(self, experiment_id: uuid.UUID) -> ExperimentDetail:
        experiment = await self._get_experiment(experiment_id)
        variants = [
            VariantRead.from_row(v)
            for v in await self._repo.list_variants(experiment_id)
        ]
        results = await self.results(experiment_id)
        return ExperimentDetail(
            experiment=await self._to_read(experiment),
            variants=variants,
            results=results.model_dump(),
        )

    async def list_observations(
        self, experiment_id: uuid.UUID, limit: int = 100, offset: int = 0
    ) -> ObservationList:
        rows, total = await self._repo.list_observations(
            experiment_id, limit=limit, offset=offset,
        )
        key_by_id = {
            v.id: v.key for v in await self._repo.list_variants(experiment_id)
        }
        items = [ObservationRead.from_rows(r, key_by_id.get(r.variant_id, "?")) for r in rows]
        return ObservationList(items=items, total=total)

    async def delete_experiment(self, experiment_id: uuid.UUID) -> bool:
        return await self._repo.delete(experiment_id)

    async def stats(self) -> ExperimentStats:
        return ExperimentStats(**await self._repo.stats())

    async def simulate(self, request: SimulateRequest) -> dict[str, Any]:
        return simulate_ab(
            request.n,
            request.base_conversion,
            request.effect_size,
            seed=request.seed,
            alpha=request.alpha,
        )

    # ── Internals ─────────────────────────────────────────────────────────

    async def _get_experiment(self, experiment_id: uuid.UUID) -> Experiment:
        experiment = await self._repo.get(experiment_id)
        if experiment is None:
            raise ExperimentNotFoundError(f"Experiment {experiment_id} not found")
        return experiment

    async def _variant_by_id(self, experiment_id: uuid.UUID, variant_id: uuid.UUID) -> Variant:
        for v in await self._repo.list_variants(experiment_id):
            if v.id == variant_id:
                return v
        raise ExperimentNotFoundError(f"Variant {variant_id} not found in experiment")

    async def _label_for(self, experiment_id: uuid.UUID, key: str | None) -> str | None:
        if not key:
            return None
        variant = await self._repo.get_variant(experiment_id, key)
        return variant.label if variant else key

    async def _load_stats(
        self, experiment: Experiment,
    ) -> tuple[dict[str, Any], list[Any]]:
        observations, _ = await self._repo.list_observations(experiment.id, limit=100000, offset=0)
        keys = {v.id: v.key for v in await self._repo.list_variants(experiment.id)}
        views = []
        for o in observations:
            views.append(type(
                "_Obs", (),
                {"variant_key": keys.get(o.variant_id, "?"),
                 "outcome": o.outcome, "profit": o.profit, "roi": o.roi,
                 "value": o.value, "predicted": o.predicted, "ground_truth": o.ground_truth},
            )())
        stats = variant_stats(views, experiment.primary_metric)
        return stats, views

    async def _to_read(self, experiment: Experiment) -> ExperimentRead:
        variants = await self._repo.list_variants(experiment.id)
        return ExperimentRead.from_row(
            experiment,
            variant_count=len(variants),
            assignment_count=await self._repo.count_assignments(experiment.id),
            observation_count=await self._repo.count_observations(experiment.id),
        )

    # ── Report rendering ──────────────────────────────────────────────────

    def _render_markdown(
        self,
        experiment: Experiment,
        stats: dict[str, Any],
        winner: dict[str, Any],
        chosen: str | None,
        profit_impact: float | None,
        roi_impact: float | None,
        observation_count: int,
    ) -> str:
        lines: list[str] = []
        lines.append(f"# Experiment report: {experiment.name}")
        lines.append("")
        lines.append("## Overview")
        lines.append(f"- Type: **{experiment.experiment_type}**")
        lines.append(f"- Status: {experiment.status}")
        lines.append(f"- Primary metric: {experiment.primary_metric}")
        lines.append(f"- Significance threshold (alpha): {experiment.alpha}")
        lines.append(f"- Min sample size / variant: {experiment.min_sample_size}")
        lines.append(f"- Observations recorded: {observation_count}")
        lines.append(f"- Seed: {experiment.seed}")
        lines.append(f"- Code version: {experiment.code_version or 'unknown'}")
        if experiment.hypothesis:
            lines.append(f"- Hypothesis: {experiment.hypothesis}")
        lines.append("")

        lines.append("## Variant results")
        lines.append("| Variant | n | conversion | mean profit | mean ROI | precision | recall | FP | FN |")
        lines.append("|---|---|---|---|---|---|---|---|---|")
        for key in sorted(stats):
            s = stats[key]
            conf = s["confusion"]
            prec = f"{conf['precision']:.4f}" if conf else "-"
            rec = f"{conf['recall']:.4f}" if conf else "-"
            fp = str(conf["false_positives"]) if conf else "-"
            fn = str(conf["false_negatives"]) if conf else "-"
            lines.append(
                f"| {key} | {s['n']} | {s['conversion']:.4f} | {s['mean_profit']:.2f} "
                f"| {s['mean_roi']:.2f} | {prec} "
                f"| {rec} "
                f"| {fp} "
                f"| {fn} |"
            )
        lines.append("")

        lines.append("## Winner")
        if winner["winner_key"]:
            lines.append(
                f"- **Winner: {winner['winner_key']}**"
                f" (confidence {winner['confidence']:.2%}, p={winner['p_value']:.4f})"
            )
        elif winner["leading_key"]:
            lines.append(
                f"- No statistically significant winner (alpha={experiment.alpha}). "
                f"Leading: **{winner['leading_key']}**."
            )
        else:
            lines.append("- No observations recorded yet.")
        if profit_impact is not None:
            lines.append(f"- Profit impact vs control: **{profit_impact:+.2f}**")
        if roi_impact is not None:
            lines.append(f"- ROI impact vs control: **{roi_impact:+.2f}**")
        lines.append("")

        lines.append("## Quality (prediction / scoring types)")
        if chosen and chosen in stats and stats[chosen]["confusion"]:
            conf = stats[chosen]["confusion"]
            lines.append(
                f"- Precision: **{conf['precision']:.4f}**, "
                f"Recall: **{conf['recall']:.4f}**, "
                f"F1: {conf['f1']:.4f}, Accuracy: {conf['accuracy']:.4f}"
            )
            lines.append(
                f"- False positives: {conf['false_positives']}, "
                f"False negatives: {conf['false_negatives']}, "
                f"True positives: {conf['true_positives']}, "
                f"True negatives: {conf['true_negatives']}"
            )
        else:
            lines.append("- No predicted/ground-truth labels recorded for this experiment.")
        lines.append("")

        lines.append("## Reproducibility")
        lines.append(f"- Assignment seed: `{experiment.seed}`")
        lines.append(
            "- Assignment = stable SHA-256(`{seed}:{subject}`) % num_variants "
            "(deterministic across restarts)"
        )
        lines.append(f"- Code version: `{experiment.code_version or 'unknown'}`")
        lines.append(
            "- This report stores its full params snapshot; re-running the analysis "
            "on the same observations reproduces these numbers exactly."
        )
        return "\n".join(lines)
